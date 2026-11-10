"""Read-only pipeline audit and independent RF split-conformal evaluation.

Run with the study's reeds2 Python environment. Writes ONLY to --out.
No ReEDS runs; no production model, manuscript, or existing analysis is changed.
Default: 10 outer folds, 25% of each outer development set for calibration,
200-tree independent RF per output, seed 42. All settings fixed before results.
Use --summarize-only to rebuild CSV summaries from the saved fold predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
import sklearn
from joblib import Parallel, delayed, parallel_backend
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import KFold, train_test_split
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STAGE = REPO / 'postprocessing/reedssurr/Stage2'
sys.path.insert(0, str(STAGE / 'code'))
import surrogate_ml_models as pipeline
from surrogate_constraints import (apply_constraints, clip_train_targets,
                                   transmission_floors, system_transmission_floors)

FOLD_SEED = 42
CAL_SEED = 1042
ALPHA = 0.1
NAMES = {'rf': 'Random Forest', 'nn': 'MLP', 'ngboost': 'NGBoost',
         'xgb': 'XGBoost', 'knn': 'k-NN', 'ridge': 'Ridge', 'lasso': 'Lasso'}
FOLDERS = {'system': 'overall', 'regional': 'regional'}


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_data():
    data = {}
    for layer, folder in FOLDERS.items():
        path = STAGE / 'inputs' / f'{folder}_ml_numeric_merged.csv'
        frame = pd.read_csv(path)
        xc = [c for c in frame if c.startswith('x_')]
        yc = [c for c in frame if c not in xc + ['case_name']]
        X, Y = frame[xc].to_numpy(float), frame[yc].to_numpy(float)
        assert np.isfinite(X).all() and np.isfinite(Y).all()
        assert len(frame) == 486 and len(np.unique(X, axis=0)) == 486
        assert np.prod([len(np.unique(X[:, j])) for j in range(X.shape[1])]) == 486
        data[layer] = dict(path=path, frame=frame, X=X, Y=Y, xc=xc, yc=yc,
                           paper_mask=Y.var(axis=0) > 1e-10)
    assert np.array_equal(data['system']['X'], data['regional']['X'])
    assert data['system']['frame'].case_name.tolist() == data['regional']['frame'].case_name.tolist()
    return data


def r2_independent(Y, P):
    """Independent SSE/SST implementation; constants are undefined, not R2=1."""
    sst = ((Y - Y.mean(axis=0)) ** 2).sum(axis=0)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(sst > 1e-10, 1 - ((Y - P) ** 2).sum(axis=0) / sst, np.nan)


def instrument_cv(X, Y):
    """Execute the actual CV function with spy models/scalers, without refitting.

    Check data passed to every fit/transform/predict, and held-out placement.
    Covers raw-target, scaled-target, and NGBoost fold-constant branches.
    This verifies current control flow, not historical artifact provenance.
    """
    splits = list(KFold(10, shuffle=True, random_state=FOLD_SEED).split(X))
    result = {}
    for name in ('rf', 'nn', 'ngboost'):
        state = dict(k=-1, fits=0, yfits=0, predicts=0)

        class CheckedScaler(StandardScaler):
            def fit(self, values, y=None, sample_weight=None):
                if values.shape[1] == X.shape[1]:
                    state['k'] += 1
                    tr, te = splits[state['k']]
                    np.testing.assert_array_equal(values, X[tr])
                    state['sx'] = self
                    self.is_x = True
                else:
                    tr, te = splits[state['k']]
                    expected = Y[tr]
                    if name == 'ngboost':
                        expected = expected[:, expected.std(0) > 1e-9]
                    np.testing.assert_array_equal(values, expected)
                    self.is_x = False
                    state['sy'] = self
                    state['yfits'] += 1
                return super().fit(values, y, sample_weight)

            def transform(self, values, copy=None):
                tr, te = splits[state['k']]
                if self.is_x:
                    assert np.array_equal(values, X[tr]) or np.array_equal(values, X[te])
                return super().transform(values, copy)

        class SpyModel:
            def fit(self, xx, yy):
                tr, te = splits[state['k']]
                sx = StandardScaler().fit(X[tr])
                np.testing.assert_allclose(xx, sx.transform(X[tr]))
                expected = Y[tr]
                if name == 'ngboost':
                    expected = expected[:, expected.std(0) > 1e-9]
                if name in ('nn', 'ngboost'):
                    expected = StandardScaler().fit_transform(expected)
                np.testing.assert_allclose(yy, expected)
                self.mean = yy.mean(0)
                state['fits'] += 1
                return self

            def predict(self, xx):
                tr, te = splits[state['k']]
                np.testing.assert_allclose(xx, StandardScaler().fit(X[tr]).transform(X[te]))
                state['predicts'] += 1
                return np.tile(self.mean, (len(xx), 1))

        with patch.object(pipeline, 'StandardScaler', CheckedScaler), patch.object(
                pipeline, 'get_model', lambda *args: (SpyModel(), 'audit spy')):
            P = pipeline.compute_oof_predictions(X, Y, name, pipeline.Config())
        for tr, te in splits:
            np.testing.assert_allclose(P[te], np.tile(Y[tr].mean(0), (len(te), 1)), atol=1e-5)
        assert state['fits'] == state['predicts'] == 10
        result[name] = {k: state[k] for k in ('fits', 'yfits', 'predicts')}
    return result


def audit_existing(data, out):
    residual_path = HERE / 'data/10_stored_residuals.npz'
    residuals = np.load(residual_path)
    column_map = json.loads((HERE / 'data/10_stored_residuals_cols.json').read_text())
    xgb = np.load(HERE / 'data/18_xgb_nohints_oof.npz')
    evidence, table, peroutput, coverage = {}, [], [], []
    for layer, d in data.items():
        X, full_Y, mask = d['X'], d['Y'], d['paper_mask']
        yc = np.array(d['yc'])[mask].tolist()
        Y = full_Y[:, mask]
        Yclip = clip_train_targets(Y, yc)
        foldid = np.full(len(X), -1)
        seen = np.zeros(len(X), int)
        overlaps, constant_train_difference, floor_difference = [], [], []
        for k, (tr, te) in enumerate(KFold(10, shuffle=True, random_state=42).split(X)):
            overlaps.append(len(np.intersect1d(tr, te)))
            seen[te] += 1
            foldid[te] = k
            constant_train_difference.append(float(np.max(abs(full_Y[tr][:, ~mask].mean(0) - full_Y[:, ~mask].mean(0)))))
            if layer == 'regional':
                tc = [c for c in d['frame'] if c.startswith('tran_')]
                floor_difference.append(float(abs(d['frame'].iloc[tr][tc].min() - d['frame'][tc].min()).max()))
        assert not any(overlaps) and np.all(seen == 1)
        assert np.ptp(full_Y[:, ~mask], axis=0).max() == 0
        evidence[layer] = dict(rows=len(X), unique_designs=len(np.unique(X, axis=0)),
            n_paper_outputs=int(mask.sum()), n_constants=int((~mask).sum()),
            constant_max_range=float(np.ptp(full_Y[:, ~mask], axis=0).max()),
            max_train_constant_mean_difference=max(constant_train_difference),
            max_train_floor_difference=max(floor_difference, default=0),
            fold_sizes=np.bincount(foldid).tolist(), overlaps=overlaps,
            each_row_tested_once=bool(np.all(seen == 1)),
            clipped_cells=int((Yclip != Y).sum()), max_clip=float(abs(Yclip-Y).max()),
            instrumented_current_cv=instrument_cv(X, Yclip))
        reference = json.loads((STAGE / 'outputs' / FOLDERS[layer] / 'summary.json').read_text())
        for model, label in NAMES.items():
            if model == 'xgb':
                assert list(xgb[layer+'_cols']) == yc
                P = xgb[layer+'_oof']
            else:
                assert column_map[f'{layer}_{model}'] == yc
                P = Yclip - residuals[f'{layer}_{model}'].astype(float)
            scores = r2_independent(Y, P)
            metric = pipeline.evaluate_predictions(Y, P, yc)['aggregate']
            assert abs(scores.mean() - metric['r2_mean']) < 1e-10
            ref = reference['models'][model]
            row = dict(layer=layer, model=label, mean=float(scores.mean()), median=float(np.median(scores)),
                n_gt_0_9=int((scores > .9).sum()), n_outputs=len(yc),
                mean_delta_vs_summary=float(scores.mean()-ref['oof_r2_mean']),
                median_delta_vs_summary=float(np.median(scores)-ref['oof_r2_median']))
            assert abs(row['mean_delta_vs_summary']) < 1e-5
            assert abs(row['median_delta_vs_summary']) < 1e-5
            assert row['n_gt_0_9'] == ref['n_outputs_r2_above_0.9']
            table.append(row)
            peroutput.extend(dict(layer=layer, model=label, output=c, r2=float(s)) for c,s in zip(yc,scores))
        z = np.load(HERE / f'data/01_oof_{layer}.npz')
        assert np.array_equal(z['fold_id'], foldid) and list(z['y_cols']) == yc
        R = abs(Yclip-z['P_rf'])
        cross = np.zeros_like(R, bool)
        for k in range(10):
            cross[foldid==k] = R[foldid==k] <= np.quantile(R[foldid!=k], .9, axis=0)
        pooled = R <= np.quantile(R, .9, axis=0)
        for method, inc in [('pooled_residual_self_check',pooled),('crossfold_residual_diagnostic',cross)]:
            for c,v in zip(yc,inc.mean(0)):
                coverage.append(dict(layer=layer, method=method, output=c, coverage=float(v)))
    pd.DataFrame(table).to_csv(out/'table_iii_recomputed.csv',index=False)
    pd.DataFrame(peroutput).to_csv(out/'table_iii_per_output.csv',index=False)
    pd.DataFrame(coverage).to_csv(out/'existing_coverage_diagnostics.csv',index=False)
    write_json(out/'cv_checks.json',evidence)
    print('Existing CV checks and all 14 Table III rows verified.', flush=True)


def finite_quantile(scores, alpha=ALPHA):
    """Exact ceil((m+1)*(1-alpha))-th order statistic, no interpolation."""
    m = len(scores)
    rank = int(math.ceil((m + 1) * (1-alpha)))
    if rank > m:
        return np.full(scores.shape[1], np.inf), rank
    return np.partition(scores, rank-1, axis=0)[rank-1], rank


def fit_one(Xtrain, ytrain, Xeval):
    # All settings identical to the study RF; one forest per output.
    if ytrain.var() <= 1e-10:
        return np.full(len(Xeval), float(ytrain.mean()))
    model = RandomForestRegressor(n_estimators=200, min_samples_leaf=2,
                                   max_depth=None, random_state=42, n_jobs=1)
    model.fit(Xtrain, ytrain)
    return model.predict(Xeval)


def constrain_pair(pred, data, constants, floors):
    result = {l:np.empty_like(p) for l,p in pred.items()}
    for i in range(len(pred['system'])):
        s = apply_constraints(pd.Series(pred['system'][i],index=data['system']['yc']),
                constants=constants['system'],floors=system_transmission_floors(floors))
        r = apply_constraints(pd.Series(pred['regional'][i],index=data['regional']['yc']),
                constants=constants['regional'],floors=floors,overall_pred=s)
        result['system'][i] = s.reindex(data['system']['yc']).to_numpy()
        result['regional'][i] = r.reindex(data['regional']['yc']).to_numpy()
    return result


def run_outer(data, out, jobs):
    X = data['system']['X']
    fold_info, assignments = [], []
    tested = np.zeros(len(X), int)
    for k, (dev, test) in enumerate(KFold(10, shuffle=True, random_state=FOLD_SEED).split(X)):
        start = time.perf_counter()
        proper, cal = train_test_split(dev, test_size=.25, random_state=CAL_SEED+k)
        proper, cal, test = map(np.sort,(proper,cal,test))
        assert not set(proper)&set(cal) and not set(proper)&set(test) and not set(cal)&set(test)
        assert len(set(proper)|set(cal)|set(test)) == len(X)
        tested[test] += 1
        for role,ids in [('proper_training',proper),('calibration',cal),('test',test)]:
            assignments.extend(dict(outer_fold=k,row=int(i),case_name=data['system']['frame'].case_name.iloc[i],role=role) for i in ids)
        evaluate = np.concatenate([cal,test])
        sx = StandardScaler().fit(X[proper])
        assert sx.n_samples_seen_ == len(proper)
        train_x, eval_x = sx.transform(X[proper]), sx.transform(X[evaluate])
        constants, pred = {}, {}
        print(f'Outer fold {k+1}/10: proper={len(proper)}, calibration={len(cal)}, test={len(test)}; fitting RF',flush=True)
        for layer,d in data.items():
            train_raw = d['Y'][proper]
            cm = train_raw.var(0) <= 1e-10
            constants[layer] = {c:float(train_raw[:,j].mean()) for j,c in enumerate(d['yc']) if cm[j]}
            train_y = clip_train_targets(train_raw,d['yc'])
            with parallel_backend('loky', inner_max_num_threads=1):
                columns = Parallel(n_jobs=jobs)(delayed(fit_one)(train_x,train_y[:,j],eval_x) for j in range(train_y.shape[1]))
            pred[layer] = np.column_stack(columns)
        # Bounds and constant values use proper training only, never calibration/test.
        floors = transmission_floors(data['regional']['frame'].iloc[proper])
        constrained = constrain_pair(pred,data,constants,floors)
        arrays = dict(proper_idx=proper,cal_idx=cal,test_idx=test,x_scaler_mean=sx.mean_,x_scaler_scale=sx.scale_)
        rank = None
        for layer,d in data.items():
            arrays[layer+'_cols'] = np.array(d['yc'])
            arrays[layer+'_proper_constant'] = d['Y'][proper].var(0) <= 1e-10
            for method,p in [('raw',pred[layer]),('constrained',constrained[layer])]:
                # Fix the complete point predictor before looking at calibration targets.
                scores = abs(d['Y'][cal]-p[:len(cal)])
                q,rank = finite_quantile(scores)
                assert rank == 100 and len(cal) == 110
                assert np.array_equal(q,np.sort(scores,axis=0)[rank-1])
                prefix = layer+'_'+method
                arrays[prefix+'_cal_pred'] = p[:len(cal)]
                arrays[prefix+'_test_pred'] = p[len(cal):]
                arrays[prefix+'_q'] = q
                arrays[prefix+'_cal_scores'] = scores
                assert np.isfinite(p).all() and np.isfinite(q).all() and (q>=0).all()
        np.savez_compressed(out/f'outer_fold_{k:02d}.npz',**arrays)
        info = dict(outer_fold=k,n_proper=len(proper),n_cal=len(cal),n_test=len(test),
                    rank=rank,cal_seed=CAL_SEED+k,elapsed_seconds=time.perf_counter()-start,
                    constants={l:len(c) for l,c in constants.items()},corridor_floors=floors)
        fold_info.append(info)
        write_json(out/'outer_folds.json',fold_info)
        pd.DataFrame(assignments).to_csv(out/'split_assignments.csv',index=False)
        print(f'Outer fold {k+1}/10 saved in {info["elapsed_seconds"]:.1f}s',flush=True)
    assert np.all(tested == 1)


def summarize(data,out):
    records, foldrecords, summaries = [], [], []
    for layer,d in data.items():
        for method in ('raw','constrained'):
            n,p = d['Y'].shape
            P,Q = np.full((n,p),np.nan),np.full((n,p),np.nan)
            seen = np.zeros(n,int)
            for k in range(10):
                z = np.load(out/f'outer_fold_{k:02d}.npz')
                assert list(z[layer+'_cols']) == d['yc']
                idx=z['test_idx']; seen[idx]+=1
                P[idx]=z[layer+'_'+method+'_test_pred']; Q[idx]=z[layer+'_'+method+'_q']
                inside=abs(d['Y'][idx]-P[idx])<=Q[idx]
                for j,c in enumerate(d['yc']):
                    foldrecords.append(dict(layer=layer,method=method,outer_fold=k,output=c,
                       n_test=len(idx),coverage=float(inside[:,j].mean()),full_width=float(2*Q[idx[0],j])))
            assert np.all(seen==1) and np.isfinite(P).all() and np.isfinite(Q).all()
            inc=abs(d['Y']-P)<=Q
            r2=r2_independent(d['Y'],P)
            for j,c in enumerate(d['yc']):
                active=abs(d['Y'][:,j])>1e-8
                sd=d['Y'][:,j].std()
                row=dict(layer=layer,method=method,output=c,in_paper_metrics=bool(d['paper_mask'][j]),
                    n_test=n,coverage=float(inc[:,j].mean()),n_active=int(active.sum()),
                    coverage_active=float(inc[active,j].mean()) if active.any() else np.nan,
                    coverage_inactive=float(inc[~active,j].mean()) if (~active).any() else np.nan,
                    mean_full_width=float((2*Q[:,j]).mean()),median_full_width=float(np.median(2*Q[:,j])),
                    mean_full_width_over_sd=float((2*Q[:,j]).mean()/sd) if sd>1e-5 else np.nan,
                    zero_width_fraction=float((Q[:,j]==0).mean()),r2=float(r2[j]),
                    unit='MW' if c.startswith(('cap_','tran_')) else 'MWh' if c.startswith('gen_') else 'USD' if c.startswith('cost_') else 'seconds')
                records.append(row)
            mask=d['paper_mask']; cv=inc[:,mask].mean(0)
            summaries.append(dict(layer=layer,method=method,n_outputs=int(mask.sum()),
                coverage_mean=float(cv.mean()),coverage_median=float(np.median(cv)),coverage_min=float(cv.min()),
                coverage_max=float(cv.max()),n_below_85pct=int((cv<.85).sum()),n_below_90pct=int((cv<.9).sum()),
                median_normalized_full_width=float(np.median((2*Q[:,mask]).mean(0)/d['Y'][:,mask].std(0)))))
            np.savez_compressed(out/f'test_predictions_{layer}_{method}.npz',prediction=P,halfwidth=Q,
                                truth=d['Y'],y_cols=np.array(d['yc']),paper_mask=mask)
    df=pd.DataFrame(records)
    df.to_csv(out/'uq_per_output.csv',index=False)
    pd.DataFrame(foldrecords).to_csv(out/'uq_per_output_per_fold.csv',index=False)
    pd.DataFrame(summaries).to_csv(out/'uq_summary.csv',index=False)
    headline=['cost_total','tran_total','cap_wind-ons','gen_wind-ons','cap_upv','gen_upv',
              'cap_gas-cc','gen_gas-cc','cap_battery_li','gen_battery_li','cap_nuclear',
              'cap_nuclear-smr','cap_Gas-CC_Gas-CC-CCS_mod','cost_inv_h2_production','cost_inv_h2_storage',
              'cap_H2-CT','cap_H2-CC','cap_electrolyzer']
    df[(df.layer=='system') & df.output.isin(headline)].to_csv(out/'uq_headline_outputs.csv',index=False)
    df[df.in_paper_metrics & (df.n_active>0) & (df.n_active<49)].to_csv(out/'uq_rare_outputs.csv',index=False)
    print(pd.DataFrame(summaries).to_string(index=False),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=HERE/'independent_audit_20261110')
    parser.add_argument('--jobs',type=int,default=10)
    parser.add_argument('--summarize-only',action='store_true')
    args=parser.parse_args(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    data=read_data()
    if not args.summarize_only:
        sources=[Path(__file__),*(d['path'] for d in data.values()),
                 *[STAGE/'code'/f for f in ('surrogate_ml_models.py','surrogate_constraints.py','surrogate_uq.py')],
                 *[HERE/'data'/f for f in ('10_stored_residuals.npz','10_stored_residuals_cols.json','18_xgb_nohints_oof.npz','01_oof_system.npz','01_oof_regional.npz')],
                 *[STAGE/'outputs'/f/'summary.json' for f in FOLDERS.values()]]
        hashes={str(p):digest(p) for p in sources}
        meta=dict(python=sys.version,sklearn=sklearn.__version__,numpy=np.__version__,pandas=pd.__version__,
            platform=platform.platform(),cpu_count=os.cpu_count(),jobs=args.jobs,
            outer_folds=10,outer_seed=FOLD_SEED,cal_seed_base=CAL_SEED,cal_fraction=.25,alpha=ALPHA,
            rf=dict(n_estimators=200,min_samples_leaf=2,max_depth=None,random_state=42),
            source_sha256=hashes,complete=False)
        write_json(out/'manifest.json',meta)
        audit_existing(data,out)
        # Check quantile edge cases before training, including the infinite-width case.
        q,k=finite_quantile(np.arange(110.)[:,None]); assert k==100 and q[0]==99
        q,k=finite_quantile(np.arange(5.)[:,None]); assert k==6 and np.isinf(q[0])
        run_outer(data,out,args.jobs)
        assert all(digest(p)==hashes[str(p)] for p in sources), 'An input changed during validation'
        meta['complete']=True
        write_json(out/'manifest.json',meta)
    summarize(data,out)


if __name__=='__main__':
    main()
