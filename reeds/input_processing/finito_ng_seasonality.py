"""FINITO exogenous NG demand: representative day's OWN calendar month.

No constituent-day averaging, optimization, or alteration of ReEDS time weights.
The input shares are national volume-based EIA shapes; they scale existing MMBtu
annual demands. They are not monthly energy targets imposed on the reduced year.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd

SECTORS = ('Residential', 'Commercial', 'Industrial')
SWITCH = 'GSw_NGDemandSeasonality'
SOURCE = 'ng_demand_monthly_shares.csv'
OUTPUT = 'finito_ng_month_multiplier.csv'


def enabled(sw) -> bool:
    value = str(sw.get(SWITCH, '0')).strip()
    if value not in ('0', '1', '0.0', '1.0'):
        raise ValueError(f'{SWITCH} must be 0 or 1, not {value!r}')
    return bool(int(float(value))) and bool(int(sw.get('GSw_FINITO_Link', 0)))


def read_shares(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={c: c.lstrip('*') for c in df.columns})
    if 'sector' in df and 'aeo_sector' not in df:
        df = df.rename(columns={'sector': 'aeo_sector'})
    if not {'aeo_sector', 'month', 'share'}.issubset(df.columns):
        raise ValueError(f'{path}: require aeo_sector,month,share (36 rows)')
    df = df[['aeo_sector', 'month', 'share']].copy()
    df['aeo_sector'] = df.aeo_sector.astype(str).str.strip()
    # R's month(label=TRUE) CSV exports are also accepted, explicitly.
    names = {m.lower(): i for i, m in enumerate(
        ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'], 1)}
    def month_number(v):
        s = str(v).strip()
        if s[:3].lower() in names:
            return names[s[:3].lower()]
        f = float(s)
        if not f.is_integer():
            raise ValueError('Month must be an integer or English month name')
        return int(f)
    df['month'] = df.month.map(month_number)
    df['share'] = pd.to_numeric(df.share, errors='raise').astype(float)
    if df.duplicated(['aeo_sector', 'month']).any():
        raise ValueError('Duplicate sector/month share rows')
    actual = set(zip(df.aeo_sector, df.month))
    expected = {(s, m) for s in SECTORS for m in range(1, 13)}
    if actual != expected:
        raise ValueError(f'Share grid must be exactly 3 sectors x 12 months. Missing: {expected-actual}; extra: {actual-expected}')
    if not np.isfinite(df.share).all() or (df.share < 0).any():
        raise ValueError('Monthly shares must be finite and nonnegative')
    totals = df.groupby('aeo_sector').share.sum()
    if (totals <= 0).any() or (totals-1).abs().max() > 1e-5:
        raise ValueError(f'Input values must be FRACTIONS summing to 1 per sector, not percentages: {totals.to_dict()}')
    df['share'] /= df.aeo_sector.map(totals)
    return df.sort_values(['aeo_sector', 'month']).reset_index(drop=True)


def read_hours(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path).rename(columns={'*h': 'h'})
    if not {'h','numhours'}.issubset(df):
        raise ValueError(f'{path}: expected h and numhours')
    df = df[['h','numhours']].copy()
    if df.h.isna().any() or df.h.duplicated().any():
        raise ValueError('Timeslice keys must be present and unique')
    df['h'] = df.h.astype(str)
    df['numhours'] = pd.to_numeric(df.numhours, errors='raise').astype(float)
    if not np.isfinite(df.numhours).all() or (df.numhours <= 0).any():
        raise ValueError('Timeslice numhours must be positive and finite')
    # ReEDS rounds hours(h) to 3 decimals AFTER the FINITO temporal include.
    # GAMS performs authoritative normalization using its own round(hours,3).
    df['numhours_effective'] = np.floor(df.numhours * 1000 + 0.5) / 1000
    return df


def raw_profile(hours: pd.DataFrame, calendar: pd.DataFrame,
                shares: pd.DataFrame, hourly_type: str) -> pd.DataFrame:
    if hourly_type not in ('day', 'year'):
        raise ValueError('This own-calendar-DAY method supports day/year, not representative weks')
    required = {'actual_h', 'timestamp'}
    if not required.issubset(calendar):
        raise ValueError('ReEDS calendar requires actual_h and timestamp')
    lookup = calendar[['actual_h', 'timestamp']].copy()
    if lookup.actual_h.duplicated().any():
        raise ValueError('Duplicate actual_h calendar keys')
    # Match selected representative h directly to its ORIGINAL date; never
    # use calendar.h or fractions of actual days mapped onto that representative.
    lookup = lookup.rename(columns={'actual_h': 'h'})
    mapped = hours.merge(lookup, on='h', how='left', validate='one_to_one')
    if mapped.timestamp.isna().any():
        raise ValueError(f'Representative timestamps missing: {mapped.loc[mapped.timestamp.isna(), "h"].tolist()[:8]}')
    # Timestamps from ReEDS are already in the model calendar/timezone.
    mapped['month'] = [pd.Timestamp(t).month for t in mapped.timestamp]
    mapped['rep_date'] = [pd.Timestamp(t).strftime('%Y-%m-%d') for t in mapped.timestamp]
    out = mapped.merge(shares, on='month', how='left', validate='many_to_many')
    if len(out) != len(hours)*3 or out.share.isna().any():
        raise ValueError('Incomplete monthly profile after mapping')
    # Unique-month share/mean(12 shares) = 12*share. The scalar cancels
    # during numhours-weighted normalization, including R's merged-row mean.
    out['raw_multiplier'] = 12.0 * out.share
    return out.sort_values(['aeo_sector','h']).reset_index(drop=True)


def normalization(raw: pd.DataFrame) -> dict[str, float]:
    denom = (raw.raw_multiplier * raw.numhours_effective).groupby(raw.aeo_sector).sum()
    if set(denom.index) != set(SECTORS) or not np.isfinite(denom).all() or (denom <= 0).any():
        raise ValueError('Representative weighted normalization has zero/missing sector mass')
    return {str(k): float(v) for k,v in denom.items()}


def apply_normalization(raw: pd.DataFrame, norm: dict) -> pd.DataFrame:
    out = raw.copy()
    out['profile_1_per_h'] = out.raw_multiplier / out.aeo_sector.map(norm)
    out['annual_share'] = out.profile_1_per_h * out.numhours_effective
    if not np.isfinite(out.profile_1_per_h).all() or (out.profile_1_per_h < 0).any():
        raise ValueError('Invalid normalized hourly rate')
    return out


def write_empty(sw, inputs_case, periodtype):
    if not enabled(sw):
        return
    if periodtype == 'rep':
        raise ValueError('Cannot normalize an empty representative-year domain')
    if not periodtype.startswith('stress'):
        raise ValueError(f'Unsupported temporal context: {periodtype}')
    pd.DataFrame(columns=['*aeo_sector','h','raw_multiplier']).to_csv(
        Path(inputs_case)/periodtype/OUTPUT, index=False)


def write_for_run(sw, inputs_case, periodtype, calendar):
    """Hook after ReEDS writes final chunked numhours and hmap tables."""
    if not enabled(sw):
        return
    if periodtype != 'rep' and not periodtype.startswith('stress'):
        raise ValueError(f'NG demand seasonality has not been validated for {periodtype!r}')
    inputs = Path(inputs_case)
    outdir = inputs/periodtype
    source = inputs.parent/'finito'/'inputs'/SOURCE
    # Read the RUN-SNAPSHOT input, not a changing repository input at runtime.
    shares = read_shares(source)
    hours = read_hours(outdir/'numhours.csv')
    if hours.empty:
        write_empty(sw, inputs_case, periodtype)
        return
    raw = raw_profile(hours, calendar, shares, str(sw['GSw_HourlyType']))
    if periodtype == 'rep':
        norm = normalization(raw)
    else:
        rep_hours = read_hours(inputs/'rep'/'numhours.csv')
        rep_raw = pd.read_csv(inputs/'rep'/OUTPUT).rename(columns={'*aeo_sector':'aeo_sector'})
        rep_raw = rep_raw.merge(rep_hours, on='h', how='left', validate='many_to_one')
        if rep_raw.numhours_effective.isna().any():
            raise ValueError('Representative normalization data incomplete for stress profile')
        norm = normalization(rep_raw)
    audit = apply_normalization(raw, norm)
    raw[['aeo_sector','h','raw_multiplier']].rename(columns={'aeo_sector':'*aeo_sector'}).to_csv(
        outdir/OUTPUT, index=False, float_format='%.17g')
    audit.to_csv(outdir/'finito_ng_demand_profile_audit.csv', index=False, float_format='%.17g')
    if periodtype == 'rep':
        totals = audit.groupby('aeo_sector').annual_share.sum().reindex(SECTORS)
        if not np.allclose(totals.to_numpy(), 1.0, atol=1e-11, rtol=0):
            raise ValueError(f'Annual unit-demand conservation failed: {totals.to_dict()}')
        annual = totals.rename('realized_annual_share').reset_index()
        annual['target_annual_share'] = 1.0
        annual['error'] = annual.realized_annual_share - 1.0
        annual.to_csv(outdir/'finito_ng_demand_annual_check.csv', index=False, float_format='%.17g')
        rep_month = audit.groupby(['aeo_sector','month']).annual_share.sum().rename('realized_share').reset_index()
        check = shares.merge(rep_month, on=['aeo_sector','month'], how='left').fillna({'realized_share':0.0})
        check['error_pp'] = 100*(check.realized_share-check.share)
        check['basis'] = 'group_by_representative_own_month'
        check.to_csv(outdir/'finito_ng_demand_month_check.csv', index=False, float_format='%.17g')
        # OPTIONAL diagnostic only: reconstruct actual-calendar allocation.
        # These fractions NEVER feed the raw or normalized multipliers.
        hm = pd.read_csv(outdir/'hmap_myr.csv').rename(columns={'*timestamp':'timestamp'})
        if {'timestamp','h'}.issubset(hm):
            hm['month'] = [pd.Timestamp(t).month for t in hm.timestamp]
            cnt = hm.groupby(['h','month']).size().rename('n').reset_index()
            cnt['fraction'] = cnt.n / cnt.groupby('h').n.transform('sum')
            tmp = audit[['aeo_sector','h','annual_share']].merge(cnt, on='h', validate='many_to_many')
            tmp['actual_month_share'] = tmp.annual_share * tmp.fraction
            cm = tmp.groupby(['aeo_sector','month']).actual_month_share.sum().rename('realized_share').reset_index()
            chk = shares.merge(cm, on=['aeo_sector','month'], how='left').fillna({'realized_share':0.0})
            chk['error_pp'] = 100*(chk.realized_share-chk.share)
            chk['basis'] = 'reconstructed_actual_calendar_DIAGNOSTIC_ONLY'
            chk.to_csv(outdir/'finito_ng_demand_calendar_month_check.csv', index=False, float_format='%.17g')
        print('FINITO NG SEASONALITY: own-month + numhours-weighted normalization; annual unit-demand checks PASS')
    else:
        print(f'FINITO NG SEASONALITY: {periodtype} uses REP normalization; stress hours excluded from annual denominator')
    meta = {'method':'representative-own-calendar-month', 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'periodtype':periodtype, 'normalization_denominator_rep':norm,
            'calendar':'provided ReEDS actual_h/timestamp; no independently constructed leap-year rule',
            'scope':'Residential/Commercial exogenous NG pool; Industrial exogenous NG ROI only',
            'non_goals':'endogenous industry/power fuel use, WNG supply, transport, other fuels unchanged'}
    (outdir/'finito_ng_seasonality_method.json').write_text(json.dumps(meta,indent=2)+'\n')
