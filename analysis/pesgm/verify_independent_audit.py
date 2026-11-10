"""Verify saved independent audit outputs without fitting models.

Also compare Table III directly with the current Word draft, and execute the
production UQ helpers on the saved residuals. Writes only new audit outputs.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from independent_cv_uq_audit import read_data, HERE, STAGE, FOLDERS
from surrogate_uq import conformal_widths, empirical_coverage
from surrogate_constraints import clip_train_targets


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=HERE/'independent_audit_20261110')
    ap.add_argument('--manuscript',type=Path,default=Path(
        'C:/Users/ychen10/OneDrive - NREL/Project 18 - ReEDS Surrogate/IEEE PES 2027/PESGM2027_ReEDS_Surrogate_0.docx'))
    args=ap.parse_args(); out=args.out
    data=read_data(); checks=[]; old_rows=[]
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['complete']
    for path,sha in manifest['source_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    checks.append('All original source/input hashes still match; main run completed.')
    actual=pd.read_csv(out/'uq_per_output.csv')
    for layer,d in data.items():
        seen=np.zeros(486,int)
        allp={m:np.zeros_like(d['Y']) for m in ('raw','constrained')}
        allq={m:np.zeros_like(d['Y']) for m in ('raw','constrained')}
        for k in range(10):
            z=np.load(out/f'outer_fold_{k:02d}.npz')
            tr,ca,te=[z[c] for c in ('proper_idx','cal_idx','test_idx')]
            assert len(set(tr)|set(ca)|set(te))==486
            assert not set(tr)&set(ca) and not set(tr)&set(te) and not set(ca)&set(te)
            assert len(ca)==110
            np.testing.assert_allclose(z['x_scaler_mean'],d['X'][tr].mean(0),atol=0,rtol=1e-14)
            np.testing.assert_array_equal(z[layer+'_proper_constant'],d['Y'][tr].var(0)<=1e-10)
            seen[te]+=1
            for method in ('raw','constrained'):
                prefix=layer+'_'+method
                scores=abs(d['Y'][ca]-z[prefix+'_cal_pred'])
                np.testing.assert_array_equal(scores,z[prefix+'_cal_scores'])
                rank=math.ceil((len(ca)+1)*.9)
                np.testing.assert_array_equal(np.sort(scores,axis=0)[rank-1],z[prefix+'_q'])
                allp[method][te]=z[prefix+'_test_pred']
                allq[method][te]=z[prefix+'_q']
        assert np.all(seen==1)
        for method in ('raw','constrained'):
            # Recompute from endpoints rather than the main script's abs-error test.
            lower=allp[method]-allq[method]; upper=allp[method]+allq[method]
            inside=(d['Y']>=lower)&(d['Y']<=upper)
            # Floating-point endpoint arithmetic can differ by an ulp at a tie;
            # direct absolute-error test is the scoring convention in the output.
            direct=abs(d['Y']-allp[method])<=allq[method]
            saved=actual[(actual.layer==layer)&(actual.method==method)].set_index('output').loc[d['yc']]
            np.testing.assert_allclose(saved.coverage,direct.mean(0),rtol=0,atol=1e-15)
            np.testing.assert_allclose(saved.mean_full_width,(2*allq[method]).mean(0),rtol=1e-14)
            checks.append(f'{layer}/{method}: split isolation, training means/constants, all quantiles, 486 test rows, coverage and widths verified; endpoint-roundoff disagreements={int((inside!=direct).sum())}.')
        mask=d['paper_mask']; yc=np.array(d['yc'])[mask].tolist(); Y=clip_train_targets(d['Y'][:,mask],yc)
        z=np.load(HERE/f'data/01_oof_{layer}.npz'); fold=z['fold_id']; R=Y-z['P_rf']
        art=dict(y_cols=yc,oof_residuals=R)
        q=conformal_widths(art,.1)
        np.testing.assert_array_equal(q,np.quantile(abs(R),.9,axis=0))
        prod=empirical_coverage(art,.1)
        np.testing.assert_allclose(prod['coverage_mean'],(abs(R)<=q).mean())
        constrained=np.load(HERE/f'data/after_fix/{FOLDERS[layer]}/oof_rf.npz')['oof']
        for method,P in [('raw',z['P_rf']),('constrained',constrained)]:
            inc=np.zeros_like(R,bool)
            for k in range(10):
                # Existing method's raw widths; evaluated-fold residuals excluded.
                half=np.quantile(abs(R[fold!=k]),.9,axis=0)
                inc[fold==k]=abs(Y[fold==k]-P[fold==k])<=half
            for j,c in enumerate(yc):
                old_rows.append(dict(layer=layer,method=method,output=c,
                    crossfold_diagnostic_coverage=float(inc[:,j].mean()),
                    pooled_width_diagnostic_coverage=float((abs(Y[:,j]-P[:,j])<=q[j]).mean())))
        splits=list(KFold(10,shuffle=True,random_state=42).split(Y))
        for k,(_,te) in enumerate(splits):
            for j,(tr_cal,_) in enumerate(splits):
                if j!=k:
                    assert set(te).issubset(set(tr_cal))
        checks.append(f'{layer}: production UQ helpers reproduce residual reuse; every other-fold calibration model includes the evaluated fold in training.')
    pd.DataFrame(old_rows).to_csv(out/'existing_raw_and_constrained_coverage.csv',index=False)

    # Plain-text extraction is for methodological/content comparison, not layout QA.
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with zipfile.ZipFile(args.manuscript) as z:
        root=ET.fromstring(z.read('word/document.xml'))
    def text(e):
        return ''.join(t.text or '' for t in e.findall('.//w:t',ns))
    paragraphs=[text(p) for p in root.findall('.//w:body//w:p',ns) if text(p)]
    selected=[f'{i+1}: {p}' for i,p in enumerate(paragraphs) if any(s in p.lower() for s in ['conformal','cross-fold','90%','settings fixed','out-of-fold','scaling'])]
    (out/'manuscript_claims.txt').write_text('\n\n'.join(selected),encoding='utf-8')
    table=pd.read_csv(out/'table_iii_recomputed.csv').set_index(['model','layer'])
    matches=[]
    for t in root.findall('.//w:tbl',ns):
        if 'Sys. mean' not in text(t):
            continue
        for row in t.findall('w:tr',ns)[1:]:
            cells=[text(c) for c in row.findall('w:tc',ns)]
            model=cells[0]
            expected=[]
            for layer in ('system','regional'):
                v=table.loc[(model,layer)]
                expected += [f'{v["mean"]:.2f}',f'{v["median"]:.2f}',str(int(v.n_gt_0_9))]
            assert cells[1:]==expected,(cells,expected)
            matches.append(model)
    assert len(matches)==7
    checks.append('All 42 numerical cells in current manuscript Table III match independently recomputed rounded metrics.')
    evidence=dict(checks=checks,manuscript=str(args.manuscript),
        manuscript_sha256=hashlib.sha256(args.manuscript.read_bytes()).hexdigest(),
        verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        manuscript_models_verified=matches)
    (out/'verification.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print('\n'.join(checks))


if __name__=='__main__':
    main()
