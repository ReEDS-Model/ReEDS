"""Gas-CC value and cost factors re-estimated against the national gas supply curve.

The valcostfac runs use static gas prices (GSw_GasCurve=2), which removes the
main cost-escalation channel a gas plant has: burning more gas raises its own
fuel price. Under the default GSw_GasCurve=1 the price responds to quantity,
nationally and by census division. This re-estimates Gas-CC's cost factor with
that response applied to the solved run, without re-solving.

Why estimate rather than re-solve
---------------------------------
Mode 1 charges gas through three terms. The largest, gasmultterm, is indexed by
tech and could be scaled by forcetechmult like every other ForceMandate cost.
The two bin terms - VGASBINQ_REGIONAL and VGASBINQ_NATIONAL, which price the
change in consumption from one solve year to the next - are not indexed by tech
and cannot be. In these runs gas use grows 1-5 Quads per solve year, so those
terms run from 4% of the mandate-scaled cost in 2030 to 23% in 2042 and 60% in
2050. Re-solving would therefore reintroduce exactly the pathology the scaled
transmission FOM and start costs were fixed to remove: a cost held at full value
while everything around it is scaled down, corrupting the de-scaled cost factor
worst where the mandate is deepest. An estimate on the solved run avoids that.

How the price response is approximated
--------------------------------------
GSw_GasCurve picks between two constructions, and `method` below picks which of
them this estimate reproduces. Mode 1, the model default, is LINEAR:

    dprice(cendiv) = nat_beta * dQ_national + cd_beta(cendiv) * dQ_elec,cendiv

while modes 0 and 3 are a POWER LAW in quantity with exponent 1/gas_elasticity
and no betas at all. So the choice spans a functional form as well as a
geographic scope, and the options are not a simple ordering.

The three mode 1 options differ only in what happens to the regional term. A
new plant in division d faces dprice_d, and the average over new plants is

    dp = dQ_nat * [ nat_beta + SUM_d w_d * s_d * cd_beta(d) ]

with s_d the share of the national increase landing in d and w_d the share of
new gas generation there. Those are the same quantity, so with w_d = s_d the
regional terms collapse into one effective national coefficient

    beta_eff = nat_beta + SUM_d s_d^2 * cd_beta(d)

The square is not a slip: a division's price response reaches only its own
plants, so its share enters once for how much of the increase it takes and once
for how much of the new generation feels it. Geographic spread therefore damps
the regional effect hard - SUM_d s_d^2 is about 0.15 here against 1.0 if all the
gas went to one division.

Which shares to use is the real choice. Reference usage gives beta_eff 1.06x
nat_beta; this run's actual increase gives 1.28x, because the increase lands
disproportionately in the two most price-sensitive divisions (New England,
cd_beta 2.36, takes 4.0% of the increase against 1.3% of reference usage;
Pacific, 0.70, takes 14.4% against 5.8%) while reference usage sits in
divisions that barely respond or respond negatively (West_South_Central -0.127
at 17% of reference, South_Atlantic 0.030 at 23%). Reference shares are the
default because they do not bake in a siting pattern that was itself found
under static prices and would move if gas got dearer.

What this is not
----------------
Partial equilibrium on a fixed solution. A real re-solve would build less gas
because it costs more, so dQ and the price rise would both be smaller: this is
an upper bound on the cost-side effect. Non-electric gas demand would also
respond and damp it further. Pushing the other way, nat_beta is a linear
coefficient calibrated near reference quantities and is extrapolated here to
roughly double the reference electric gas demand, where a real supply curve is
convex - so the true national response at that extreme is likely larger than
linear. The two errors do not cancel in any way that can be claimed.

Which base is which
-------------------
lcoe_base in the results is ALREADY multiplied by force_mult; lcoe_base_orig is
the unscaled ATB cost. The identities are

    cost_factor       = lvoe / lcoe_base = (lvoe/force_mult) / lcoe_base_orig
    value_factor      = lvoe / benchmark_price
    value_cost_factor = lcoe_base / benchmark_price = value_factor / cost_factor

so the de-scaled marginal cost is cost_factor * lcoe_base_orig, and that is what
the fuel increase - a real, unscaled price - is added to. Adding it to the
scaled base instead inflates the late years absurdly, because the scaled base
falls to a twentieth of the real one by 2050 while the fuel increase does not.

The value side
--------------
value_cost_factor is lcoe_base / benchmark_price and carries no LVOE term, so a
cost-side correction moves it only through the benchmark price. The benchmark
would rise - gas sets the marginal price in most hours at these market shares -
but by how much is not derivable from the solved run. Rather than invent a
benchmark response, VCF is reported under the identity VCF = VF / CF with the
value factor held at its modelled level. That is the natural reading when the
forced tech sets the price in most hours: its revenue and the benchmark rise
together, leaving VF roughly unchanged and pushing the whole correction into
the cost factor. If instead the benchmark barely moved, VF would rise and VCF
would stay near its static value - so the plotted VCF is the more pessimistic
of the two readings, and the cost factor, which needs no such assumption, is
the defensible number.
"""

import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import plcoe_pitch
from report_switches import dollar_year, start_year

#--- switches ---
gas_scenario = 'gas'        #Scenario in valcostfac.csv whose Gas-CC rows are corrected.
gas_tech = 'Gas-CC'         #Tech label in the core results.
gas_prefix = 'gas-cc'       #Raw tech name prefix in the run outputs.
method = 'mode1_reference'  #Which price response to reproduce:
                            #  'mode1_national_only' nat_beta alone - the regional term dropped, on
                            #                        the grounds that re-siting could avoid it
                            #  'mode1_reference'     beta_eff weighted by AEO reference gas usage
                            #                        (default)
                            #  'mode1_actual'        beta_eff weighted by this run's own increase
                            #  'mode3'               the power-law national curve, a different
                            #                        functional form, included to show how much the
                            #                        answer depends on form rather than on scope
fit_form = 'power'          #Matches the VCF figures this section sits under.
dpi = 130


def _scalars(run_dir):
    d = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'scalars.csv'),
                    header=None, names=['k', 'v', 'desc'])
    return d.set_index(d.k.astype(str).str.strip()).v


def _switch(run_dir, key, default=''):
    d = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'switches.csv'),
                    header=None, names=['k', 'v'])
    d = d.set_index(d.k.astype(str).str.strip()).v
    return str(d.get(key, default)).strip()


def national_beta(run_dir):
    """nat_beta in $/MMBtu per Quad, picked by GSw_GasSector as b_inputs.gms does.

    Note the naming reads backwards: GSw_GasSector='electric_sector' selects
    nat_beta_NONENERGY, and 'energy_sector' selects nat_beta_energy. That
    matches b_inputs.gms, where the energy_sector branch takes the all-sector
    coefficients and everything else falls through to the other pair.
    """
    sector = _switch(run_dir, 'GSw_GasSector', 'electric_sector')
    key = 'nat_beta_energy' if sector == 'energy_sector' else 'nat_beta_nonenergy'
    return float(_scalars(run_dir)[key])


def division_beta(run_dir):
    """cd_beta by census division, the regional partner to nat_beta."""
    sector = _switch(run_dir, 'GSw_GasSector', 'electric_sector')
    name = 'cd_beta0_allsector.csv' if sector == 'energy_sector' else 'cd_beta0.csv'
    d = pd.read_csv(os.path.join(run_dir, 'inputs_case', name),
                    header=0, names=['cendiv', 'beta'])
    d = d[~d.cendiv.astype(str).str.startswith('*')]
    return d.set_index('cendiv').beta.astype(float)


def effective_beta(run_dir, shares):
    """nat_beta + SUM_d s_d^2 * cd_beta(d): the regional terms as one national coefficient.

    `shares` is s_d, normalised to sum to one. See the module docstring for why
    the share is squared.
    """
    cdb = division_beta(run_dir)
    s = shares.reindex(cdb.index).fillna(0.0)
    s = s / s.sum() if s.sum() else s
    return national_beta(run_dir) + float((s ** 2 * cdb).sum())


def gas_quantities(run_dir):
    """Electric gas burn (Quads) and new Gas-CC heat rate (MMBtu/MWh), by solve year.

    Burn covers every gas tech, because the national price responds to total
    electric-sector gas use, not just the forced tech's. The heat rate is the
    generation-weighted rate of NEW Gas-CC vintages: the correction is a change
    in marginal cost, so it converts at the margin's heat rate, not the fleet's.
    """
    out = os.path.join(run_dir, 'outputs')
    gen = pd.read_csv(os.path.join(out, 'gen_ivrt.csv'))
    gen.columns = ['i', 'v', 'r', 't', 'mwh']
    heat = pd.read_csv(os.path.join(out, 'heat_rate.csv'))
    heat.columns = ['i', 'v', 'r', 't', 'hr']
    gas = gen[gen.i.str.lower().str.startswith(('gas-cc', 'gas-ct'))].merge(
        heat, on=['i', 'v', 'r', 't'])
    burn = (gas.mwh * gas.hr).groupby(gas.t).sum() / 1e9

    new = gen[(gen.i == gas_prefix) & gen.v.str.startswith('new')].merge(
        heat, on=['i', 'v', 'r', 't'])
    hr_new = new.groupby('t').apply(
        lambda d: np.average(d.hr, weights=d.mwh.clip(lower=1e-9)))
    return burn, hr_new


def reference_burn(run_dir, by_division=False):
    """AEO reference electric-sector gas demand, Quads by year (and division)."""
    ref = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'ng_demand_elec.csv'), index_col=0)
    return ref if by_division else ref.sum()


def total_demand(run_dir):
    """AEO reference all-sector gas demand, Quads by year. Only mode 3 needs it."""
    tot = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'ng_demand_tot.csv'), index_col=0)
    return tot.sum()


def reference_price(run_dir):
    """gasprice_nat: the electric-gas-weighted mean of gasprice_ref, per b_inputs.gms."""
    price = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'gasprice_ref.csv'), index_col=0)
    weight = reference_burn(run_dir, by_division=True)
    common = price.index.intersection(weight.index)
    num = (price.loc[common] * weight.loc[common]).sum()
    den = weight.loc[common].sum()
    return num / den.replace(0, np.nan)


def burn_by_division(run_dir):
    """Electric gas burn in the run, Quads by division and year."""
    out = os.path.join(run_dir, 'outputs')
    gen = pd.read_csv(os.path.join(out, 'gen_ivrt.csv'))
    gen.columns = ['i', 'v', 'r', 't', 'mwh']
    heat = pd.read_csv(os.path.join(out, 'heat_rate.csv'))
    heat.columns = ['i', 'v', 'r', 't', 'hr']
    hier = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'hierarchy.csv')
                       ).rename(columns={'*r': 'r'})[['r', 'cendiv']]
    gas = gen[gen.i.str.lower().str.startswith(('gas-cc', 'gas-ct'))].merge(
        heat, on=['i', 'v', 'r', 't']).merge(hier, on='r')
    gas['mmbtu'] = gas.mwh * gas.hr
    return gas.pivot_table(index='cendiv', columns='t', values='mmbtu',
                           aggfunc='sum').fillna(0) / 1e9


def correction(run_dir, usd_mult=1.0):
    """Per-MWh fuel cost increase for a new Gas-CC, by solve year, under `method`.

    Returned in the run's dollar year times usd_mult, so the caller can line it
    up with the core results' dollar year.
    """
    burn, hr_new = gas_quantities(run_dir)
    ref = reference_burn(run_dir)
    if method not in ('mode1_national_only', 'mode1_reference', 'mode1_actual', 'mode3'):
        raise ValueError(f'unknown method {method!r}')

    if method == 'mode3':
        elasticity = float(_scalars(run_dir)['gas_elasticity'])
        price_nat, tot = reference_price(run_dir), total_demand(run_dir)
    else:
        ref_div = reference_burn(run_dir, by_division=True)
        burn_div = burn_by_division(run_dir)

    rows = []
    for year in sorted(burn.index):
        #Historical years are solved but not part of the mandate ramp, and the run
        #can differ from the AEO reference there for reasons this correction is not
        #about. Start where the rest of the analysis starts.
        if year < start_year or str(year) not in ref.index or year not in hr_new.index:
            continue
        dq = burn[year] - float(ref[str(year)])

        if method == 'mode3':
            #Power law: price scales with total gas demand relative to reference,
            #so at the reference quantity the bracket is 1 and dprice is 0.
            q_tot = float(tot[str(year)])
            dprice = float(price_nat[str(year)]) * (((dq + q_tot) / q_tot) ** (1 / elasticity) - 1)
            beta = np.nan
        else:
            if method == 'mode1_national_only':
                beta = national_beta(run_dir)
            elif method == 'mode1_reference':
                beta = effective_beta(run_dir, ref_div[str(year)])
            else:
                #Shares of THIS run's increase over reference, floored at zero so a
                #division that fell below reference does not take a negative share.
                incr = (burn_div[year] - ref_div[str(year)].reindex(burn_div.index).fillna(0)
                        ).clip(lower=0)
                beta = effective_beta(run_dir, incr)
            dprice = beta * dq

        rows.append({'year': year, 'burn_quads': burn[year],
                     'ref_quads': float(ref[str(year)]), 'dq_quads': dq, 'beta': beta,
                     'dprice_usd_per_mmbtu': dprice, 'heat_rate': hr_new[year],
                     'dcost_usd_per_mwh': dprice * hr_new[year] * usd_mult})
    return pd.DataFrame(rows).set_index('year')


def apply_correction(df, corr):
    """Gas-CC rows with the supply-curve fuel increase folded into the cost factor.

    The de-scaled marginal cost is cost_factor * lcoe_base_orig, in real dollars,
    and the fuel increase is added to it there. VCF follows from the identity
    VCF = VF / CF with the value factor held at its modelled level; see the
    module docstring for why that is the pessimistic of the two readings.
    """
    out = df[df.tech == gas_tech].copy()
    d = out.year.map(corr['dcost_usd_per_mwh']).astype(float)
    mc = out.cost_factor * out.lcoe_base_orig                #de-scaled marginal cost, real $
    out['dcost_usd_per_mwh'] = d
    out['cost_factor'] = (mc + d) / out.lcoe_base_orig
    out['value_cost_factor'] = out.value_factor / out.cost_factor
    out['inv_cost_factor'] = 1 / out['cost_factor']
    out['cost_value_factor'] = 1 / out['value_cost_factor']
    out['inv_value_factor'] = 1 / out['value_factor']
    return out


STATIC_LABEL = 'Gas-CC, static gas price'
METHOD_LABEL = {
    'mode1_national_only': 'national term of the default curve',
    'mode1_reference': 'default curve, reference-usage weights',
    'mode1_actual': 'default curve, this run\'s usage weights',
    'mode3': 'national power-law curve (mode 3)',
}


def fuel_figure(corr, output_dir, usd_label):
    """The added fuel cost itself, which is the whole of the correction."""
    fig, ax = plt.subplots(figsize=(5.4, 4.0), dpi=dpi)
    ax.plot(corr.index, corr.dcost_usd_per_mwh, 'o-', color='#b2182b', lw=1.7, ms=4.5)
    ax.set_xlabel('Model year')
    ax.set_ylabel(f'Added fuel cost ({usd_label}$/MWh)')
    ax.set_title('Fuel cost a new Gas-CC would face under the gas supply curve\n'
                 f'({METHOD_LABEL[method]})', fontsize=10)
    for year, dy in ((corr.index.min(), 9), (corr.index.max(), -14)):
        ax.annotate(f'{corr.dq_quads[year]:+.0f} Quads vs AEO',
                    (year, corr.dcost_usd_per_mwh[year]), fontsize=7.5,
                    textcoords='offset points', xytext=(0, dy), ha='center', color='#666666')
    ax.grid(alpha=.3, ls=':')
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    path = os.path.join(output_dir, 'gas_supply_curve_fuel.png')
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    return path


def make_fig(valcostfac_core_path, run_dir, output_dir=None, usd_mult=1.0):
    """Write the gas supply-curve section's two figures and its csv.

    The value-factor / value-cost-factor figure is drawn by plcoe_pitch.plot_vre_vcf,
    the same function that draws section 02, with the static and corrected series
    passed as two technologies. Reusing it rather than imitating it means the
    intercept matching, the shaded band, the implied cost-factor curve and the
    fitted equations are the same construction here as there, and stay in step if
    that construction changes.
    """
    output_dir = output_dir or os.path.dirname(os.path.abspath(valcostfac_core_path))
    core = pd.read_csv(valcostfac_core_path)
    full = plcoe_pitch.load_full_range(valcostfac_core_path, core)
    base = full[(full.tech == gas_tech) & (full.year >= start_year)].copy()
    if base.empty:
        print('gas_supply_curve: no Gas-CC rows; section skipped.')
        return None

    corr = correction(run_dir, usd_mult=usd_mult)
    if corr.empty:
        print('gas_supply_curve: no overlapping years; section skipped.')
        return None
    est = apply_correction(base, corr)

    usd_label = str(dollar_year) if usd_mult != 1.0 else '2004'
    fuel_path = fuel_figure(corr, output_dir, usd_label)

    #Two series, labelled as technologies, so plot_vre_vcf draws them side by side.
    curve_label = f'Gas-CC, {METHOD_LABEL[method]}'
    pair = pd.concat([base.assign(tech=STATIC_LABEL), est.assign(tech=curve_label)],
                     ignore_index=True)
    vcf_path = os.path.join(output_dir, 'gas_supply_curve_vcf.png')
    #build_color_map assigns from tab20 by sorted position for techs it does not know, which
    #here hands the static series a near-white blue. Both panels have to be readable side by
    #side, so the two colours are pinned for this call and the function restored after.
    original = plcoe_pitch.build_color_map
    plcoe_pitch.build_color_map = lambda techs: {STATIC_LABEL: '#666666',
                                                 curve_label: '#b2182b'}
    try:
        plcoe_pitch.plot_vre_vcf(
            pair, vcf_path, form=fit_form, techs=[STATIC_LABEL, curve_label], sync_axes=True,
            basis_note=' - Gas-CC only; the right panel adds gas supply-curve fuel cost to the '
                       f'cost factor ({METHOD_LABEL[method]}), with the value factor held at its '
                       'modelled level')
    finally:
        plcoe_pitch.build_color_map = original

    keep = ['year', 'gen_frac', 'cost_factor', 'value_factor', 'value_cost_factor']
    out = base[keep].rename(columns={c: c + '_static' for c in keep[2:]})
    for c in keep[2:]:
        out[c + '_corrected'] = est[c].to_numpy()
    out = out.merge(corr.reset_index()[['year', 'burn_quads', 'ref_quads', 'dq_quads', 'beta',
                                        'dprice_usd_per_mmbtu', 'dcost_usd_per_mwh']],
                    on='year', how='left')
    out['method'] = method
    csv_path = os.path.join(output_dir, 'gas_supply_curve.csv')
    out.to_csv(csv_path, index=False)
    print(f'gas_supply_curve: wrote {os.path.basename(fuel_path)}, '
          f'{os.path.basename(vcf_path)} and {os.path.basename(csv_path)}')
    return vcf_path
