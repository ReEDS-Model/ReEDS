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

National term only
------------------
Mode 1's curve is linear, so the price response separates:

    dprice(cendiv) = nat_beta * dQ_national + cd_beta(cendiv) * dQ_elec,cendiv

Only the national term is used here. The regional term is the part the model
could avoid by re-siting: cd_beta varies by division and is negative in two of
them (West_South_Central -0.127, East_South_Central -0.026), so gas would move
toward the divisions that price it cheapest, and a regional estimate weighted by
today's siting overstates it. The national term cannot be avoided by moving,
only by building less gas. Including it alone costs little - weighted by current
siting the regional term adds 12-20% on top - and what it buys is a number that
survives re-optimisation.

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
fit_form = 'power'          #Matches the VCF figures this section sits under.
dpi = 130


def national_beta(run_dir):
    """nat_beta in $/MMBtu per Quad, picked by GSw_GasSector as b_inputs.gms does."""
    scalars = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'scalars.csv'),
                          header=None, names=['k', 'v', 'desc'])
    scalars = scalars.set_index(scalars.k.astype(str).str.strip()).v
    switches = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'switches.csv'),
                           header=None, names=['k', 'v'])
    switches = switches.set_index(switches.k.astype(str).str.strip()).v
    sector = str(switches.get('GSw_GasSector', 'electric_sector')).strip()
    key = 'nat_beta_energy' if sector == 'energy_sector' else 'nat_beta_nonenergy'
    return float(scalars[key])


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


def reference_burn(run_dir):
    """AEO reference electric-sector gas demand (Quads) by year, summed over divisions."""
    ref = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'ng_demand_elec.csv'), index_col=0)
    return ref.sum()


def correction(run_dir, usd_mult=1.0):
    """Per-MWh fuel cost increase for a new Gas-CC, by solve year.

    Returned in whatever dollar year the run reports (2004$) times usd_mult, so
    the caller can line it up with the core results' dollar year.
    """
    beta = national_beta(run_dir)
    burn, hr_new = gas_quantities(run_dir)
    ref = reference_burn(run_dir)
    rows = []
    for year in sorted(burn.index):
        #Historical years are solved but not part of the mandate ramp, and the run
        #can differ from the AEO reference there for reasons this correction is not
        #about. Start where the rest of the analysis starts.
        if year < start_year or str(year) not in ref.index or year not in hr_new.index:
            continue
        dq = burn[year] - float(ref[str(year)])
        dprice = beta * dq
        rows.append({'year': year, 'burn_quads': burn[year],
                     'ref_quads': float(ref[str(year)]), 'dq_quads': dq,
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
CURVE_LABEL = 'Gas-CC, national supply curve'


def fuel_figure(corr, output_dir, usd_label):
    """The added fuel cost itself, which is the whole of the correction."""
    fig, ax = plt.subplots(figsize=(5.4, 4.0), dpi=dpi)
    ax.plot(corr.index, corr.dcost_usd_per_mwh, 'o-', color='#b2182b', lw=1.7, ms=4.5)
    ax.set_xlabel('Model year')
    ax.set_ylabel(f'Added fuel cost ({usd_label}$/MWh)')
    ax.set_title('Fuel cost a new Gas-CC would face\nunder the national gas supply curve',
                 fontsize=10)
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
    pair = pd.concat([base.assign(tech=STATIC_LABEL), est.assign(tech=CURVE_LABEL)],
                     ignore_index=True)
    vcf_path = os.path.join(output_dir, 'gas_supply_curve_vcf.png')
    #build_color_map assigns from tab20 by sorted position for techs it does not know, which
    #here hands the static series a near-white blue. Both panels have to be readable side by
    #side, so the two colours are pinned for this call and the function restored after.
    original = plcoe_pitch.build_color_map
    plcoe_pitch.build_color_map = lambda techs: {STATIC_LABEL: '#666666',
                                                 CURVE_LABEL: '#b2182b'}
    try:
        plcoe_pitch.plot_vre_vcf(
            pair, vcf_path, form=fit_form, techs=[STATIC_LABEL, CURVE_LABEL], sync_axes=True,
            basis_note=' - Gas-CC only; the right panel adds the national gas supply-curve fuel '
                       'cost to the cost factor, with the value factor held at its modelled level')
    finally:
        plcoe_pitch.build_color_map = original

    keep = ['year', 'gen_frac', 'cost_factor', 'value_factor', 'value_cost_factor']
    out = base[keep].rename(columns={c: c + '_static' for c in keep[2:]})
    for c in keep[2:]:
        out[c + '_corrected'] = est[c].to_numpy()
    out = out.merge(corr.reset_index()[['year', 'burn_quads', 'ref_quads', 'dq_quads',
                                        'dprice_usd_per_mmbtu', 'dcost_usd_per_mwh']],
                    on='year', how='left')
    csv_path = os.path.join(output_dir, 'gas_supply_curve.csv')
    out.to_csv(csv_path, index=False)
    print(f'gas_supply_curve: wrote {os.path.basename(fuel_path)}, '
          f'{os.path.basename(vcf_path)} and {os.path.basename(csv_path)}')
    return vcf_path
