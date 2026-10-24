'''Builds battery_report.html: the storage figures of the value/cost-factor pipeline, as one page.

The companion to valcostfac_report.html, which covers every technology on shared terms and keeps
storage only where it is one line among several. Storage gets its own page because most of what
describes it has no counterpart for the other technologies: a duration the model chooses, a
capacity credit built from the price spread inside the stress periods rather than from output, and
a value factor that starts above one.

Run after plcoe_pitch.make_figs, which writes every png and csv read here, from
run_report_valcostfac.py. Like the main report it carries figures, tables and descriptions of what
each one plots, and no findings; sections whose inputs are missing are skipped.

Run this file on the reeds2 conda environment.
'''
import os
import numpy as np
import pandas as pd
import valcostfac_report as vr
from valcostfac_report import CSS, figure, table, read_csv_or_empty, _num, _swatch
from plcoe_pitch import (years as table_years, display_tech, load_style_colors, tech_style_path,
                         normalize_tech_name)
from report_switches import dollar_year

# User inputs
valcostfac_core_path = vr.valcostfac_core_path #Only used when running this file standalone.
report_name = 'battery_report.html' #Written into output_dir, next to valcostfac_report.html.
report_title = 'Battery Figures' #Page title and headline.
storage_tech = 'Battery' #Name in valcostfac_core.csv of the storage technology this page covers.


def build_html(output_dir, core_path):
    """Assemble the page from whatever plcoe_pitch left in output_dir."""
    order = []
    core = pd.read_csv(core_path)
    scen = core.loc[core['tech'] == storage_tech, 'scenario']
    scen = scen.iloc[0] if not scen.empty else 'n/a'
    colors = load_style_colors(tech_style_path)
    colors = {t: colors.get(normalize_tech_name(t), '#888888') for t in core['tech'].unique()}
    tech_cell = lambda t: f'<td class="t">{_swatch(t, colors)}{display_tech(t)}</td>'

    # ---- 01 value factor and value-cost factor ----
    lcoe_year_fig = figure(output_dir, 'plcoe_pitch_storage_lcoe_vcf_year.png', 1,
                           'LCOE base, PLCOE, marginal LCOE, value&#8211;cost factor and value '
                           'factor for storage by model year.',
                           'Left axis, in $/MWh: LCOE base, the unforced ATB cost; PLCOE, LCOE base '
                           'times cost factor over value factor, which is LCOE base over '
                           'value&#8211;cost factor; and, faint, the marginal LCOE. On the margin '
                           'the LVOE of new builds equals their LCOE after the forcing cost '
                           'reduction, so marginal LCOE is LVOE divided by the forcing multiplier: '
                           'the LCOE if forcing were a constraint rather than a cost reduction. Over '
                           'LCOE base it is the cost factor. Right axis: value&#8211;cost factor '
                           'and, faint, value factor. Because value&#8211;cost factor is the forced '
                           'LCOE base over the benchmark price, PLCOE here equals the benchmark '
                           'price divided by the forcing multiplier.', order)
    lcoe_share_fig = figure(output_dir, 'plcoe_pitch_storage_lcoe_vcf_share.png', 2,
                            'The same against market share.',
                            'Fig 1 with market share, storage discharge as a share of total '
                            'generation excluding storage, on the x axis.', order)
    vcf_unfit_fig = figure(output_dir, 'plcoe_pitch_VCF_storage_unfitted.png', 3,
                           'Value factor and value&#8211;cost factor for storage, without fits.',
                           'The series of Fig 4 as points joined in order of market share, with no '
                           'fits, no shaded band and no LCOE-base scaling: value factor, '
                           'value&#8211;cost factor and the reciprocal of the cost factor, each as '
                           'computed. The gap between the value-factor and value&#8211;cost-factor '
                           'lines is the cost side read directly from the data.', order)
    vcf_fig = figure(output_dir, 'plcoe_pitch_VCF_power_storage.png', 4,
                     'Value factor and value&#8211;cost factor for storage.',
                     'The construction of the headline value&#8211;cost factor figure in the main '
                     'report, drawn by the same function: power fits of value factor and '
                     'value&#8211;cost factor against market share, with LCOE base scaled so the two '
                     'fits share an intercept at zero market share and the band between them read '
                     'as cost escalation. Storage is drawn on its own axes because its value factor '
                     'starts above one and its market share stops near 15%. The grey series is the '
                     'reciprocal of the cost factor and the dotted grey curve is the ratio the two '
                     'fits imply; for storage those two part company, and the R&sup2; of the implied '
                     'curve against the data it is drawn over is negative, so the shaded band does '
                     'not describe the cost-factor data.', order)

    # ---- 02 value factor by component ----
    comp_fig = figure(output_dir, 'plcoe_pitch_storage_vf_components.png', 5,
                      'Value factor split into energy and capacity components.',
                      'Each component is that value stream per MWh divided by the benchmark price, '
                      'so the two sum to the value factor exactly at every point, and they are '
                      'stacked: energy below, the reserve-margin (capacity) component above, with '
                      'the total marked. Energy value is net of charging. Against the same market '
                      'share as the figure above; the dotted line is a value factor of one.', order)
    comp = read_csv_or_empty(output_dir, 'plcoe_pitch_storage_vf_components.csv')
    comp_rows = []
    for _, r in comp[comp['year'].isin(table_years)].iterrows() if not comp.empty else []:
        comp_rows.append(
            f'<tr><td class="t">{int(r["year"])}</td>'
            f'<td class="num">{_num(r["gen_frac"], "{:.1%}")}</td>'
            f'<td class="num">{_num(r["vf_comp_energy"], "{:.3f}")}</td>'
            f'<td class="num">{_num(r["vf_comp_resmarg"], "{:.3f}")}</td>'
            f'<td class="num">{_num(r["value_factor"], "{:.3f}")}</td></tr>')
    comp_table = table('Value factor components at the headline years',
                       [('Year', False), ('Market share', True), ('Energy', True),
                        ('Capacity', True), ('Value factor', True)], comp_rows)

    # ---- 03 duration ----
    dur_fig = figure(output_dir, 'plcoe_pitch_storage_duration.png', 6,
                     'Duration of the installed storage fleet by model year.',
                     'Each zone&rsquo;s fleet duration is its installed energy capacity divided by its '
                     'installed power capacity, summed over vintages (cap_energy_ivrt over cap_ivrt). '
                     'One box per model year over the zones; boxes and the red mean are weighted by '
                     'installed power capacity, and box width is proportional to the square root of '
                     'the installed capacity. Whiskers are the weighted 10th and 90th percentiles, '
                     'taken over the megawatts installed rather than interpolated between zones. '
                     'Years with less than a gigawatt installed are omitted. Every battery after the '
                     'initial fleet is one vintage whose dispatch valnew pro-rates to new builds, so '
                     'this is the duration behind the value and capacity credit figures. The dashed '
                     'line is the capacity-weighted mean of each year&rsquo;s new investment, '
                     '<span class="eq">INV_ENERGY / INV</span> (cap_energy_new_out over '
                     'cap_new_ivrt), which the fleet trails. Its zone distribution is not drawn: '
                     'power and energy are separate decision variables, so a zone&rsquo;s investment '
                     'can be mostly energy added to existing power capacity, and its ratio is then '
                     'not a battery design.', order)
    dur = read_csv_or_empty(output_dir, 'plcoe_pitch_storage_duration.csv')
    dur_rows = []
    for _, r in dur[dur['year'].isin(table_years)].iterrows() if not dur.empty else []:
        dur_rows.append(
            f'<tr><td class="t">{int(r["year"])}</td>'
            f'<td class="num">{_num(r["gw"], "{:.1f}")}</td>'
            f'<td class="num">{int(r["n_regions"])}</td>'
            f'<td class="num">{_num(r["p25"])}</td>'
            f'<td class="num">{_num(r["median"])}</td>'
            f'<td class="num">{_num(r["p75"])}</td>'
            f'<td class="num">{_num(r["mean"])}</td>'
            f'<td class="num">{_num(r.get("new_mean", np.nan))}</td></tr>')
    dur_table = table(
        'Storage fleet duration at the headline years, capacity-weighted, hours, with the mean '
        'of that year&rsquo;s new builds',
        [('Year', False), ('Installed, GW', True), ('Zones', True), ('p25', True),
         ('Median', True), ('p75', True), ('Mean', True), ('New-build mean', True)], dur_rows)

    # ---- 04 capacity credit of new builds, every technology ----
    cc_fig = figure(output_dir, 'plcoe_pitch_capacity_credit.png', 7,
                    'Capacity credit of new builds against market share.',
                    'For each year&rsquo;s new builds, the reserve-margin value they earned divided '
                    'by what the same capacity would have earned in the same regions had it been '
                    'available in every stress hour: '
                    '<span class="eq">&Sigma;<sub>r</sub> val_resmarg / '
                    '&Sigma;<sub>r</sub> MW &middot; res_marg_ann</span>, where res_marg_ann is the '
                    'sum of a region&rsquo;s stress-hour reserve-margin prices. Both sums run over '
                    'regions before the division, matching how the regional quantity is itself '
                    'built: report.gms forms val_resmarg as a sum over stress hours of firm '
                    'contribution times that hour&rsquo;s price, so the number is price-weighted at '
                    'every level. Because those prices are concentrated in a few hours, this sits '
                    'below an hour-counting ELCC for resource-limited technologies. Storage is net '
                    'of charging, so its credit is a round-trip-net quantity.', order)
    cc_gw_fig = figure(output_dir, 'plcoe_pitch_capacity_credit_gw.png', 8,
                       'The same capacity credits against cumulative installed capacity.',
                       'Identical data to Fig 7 on a different x axis: the cumulative '
                       'national capacity of that technology in its own forcing run. '
                       'Market share and installed capacity order the technologies differently, '
                       'since a gigawatt of storage and a gigawatt of wind are nowhere near the '
                       'same share of generation; against capacity the resource-limited '
                       'technologies fall along visibly separate paths rather than overlapping.', order)
    cc_cap_fig = figure(output_dir, 'plcoe_pitch_capacity_credit_cap.png', 9,
                        'The same capacity credits against installed capacity as a share of peak '
                        'load.',
                        'Fig 8 with each run&rsquo;s capacity divided by that run&rsquo;s national '
                        'peak load, the highest stress-period block of the summed zone loads, as in '
                        'Fig 16. ReEDS scales exogenous stress-period load up by the planning reserve '
                        'margin (12% in these runs), so this peak includes it. This puts every run on '
                        'the scale of its own system and matches the axis of the regional capacity '
                        'credits in Fig 16.', order)
    cc_sc_fig = figure(output_dir, 'plcoe_pitch_capacity_credit_scenarios.png', 10,
                       'Capacity credit of new storage and UPV in every scenario.',
                       'The capacity credit above, computed the same way, for new builds of '
                       'storage and UPV in each run rather than only in the run that forces them. '
                       'Rows are the technology; the columns are against model year, against '
                       'that technology&rsquo;s own installed national capacity in the run as in '
                       'Fig 8, and against that capacity as a share of the run&rsquo;s peak load '
                       'as in Fig 9. Each '
                       'scenario takes the colour of the technology it forces and has its own '
                       'marker; the reference run, which forces nothing, '
                       'is dashed grey. A year in which the run added under a gigawatt of the '
                       'technology is left out, since the credit of a few hundred megawatts '
                       'depends on which one or two regions happened to build, and lines break '
                       'across the omitted years. If a technology&rsquo;s credit depended only on '
                       'how much of it is installed, every scenario would fall on one curve in '
                       'the capacity columns.', order)
    cc_sc = read_csv_or_empty(output_dir, 'plcoe_pitch_capacity_credit_scenarios.csv')
    cc_sc_rows, cc_sc_cols = [], []
    if not cc_sc.empty:
        #The csv is written in scenarios-file order, so its own first-appearance order is that order
        #and the report needs no path to the scenarios file.
        sc_order = list(cc_sc['scenario'].drop_duplicates())
        cc_sc_cols = [(t, y) for t in [t for t in ('Battery', 'UPV') if t in set(cc_sc['tech'])]
                      for y in table_years]
        lookup = cc_sc.set_index(['scenario', 'tech', 'year'])['capacity_credit']
        for sc in sc_order:
            ft = cc_sc.loc[cc_sc['scenario'] == sc, 'forced_tech'].iloc[0]
            label = 'Reference (no forcing)' if pd.isna(ft) else f'{display_tech(ft)} forced'
            cells = ''.join(f'<td class="num">{_num(lookup.get((sc, t, y), np.nan), "{:.2f}")}</td>'
                            for t, y in cc_sc_cols)
            cc_sc_rows.append(f'<tr><td class="t">{label}</td>{cells}</tr>')
    cc_sc_table = table(
        'Capacity credit of new storage and UPV by scenario at the headline years. A dash is a '
        'year in which the run added under a gigawatt of that technology',
        [('Scenario', False)] + [(f'{display_tech(t)} {y}', True) for t, y in cc_sc_cols],
        cc_sc_rows)
    cc_df = read_csv_or_empty(output_dir, 'plcoe_pitch_capacity_credit.csv')
    cc_rows, cc_years = [], []
    if not cc_df.empty:
        #The figure carries the whole trajectory; the table gives anchor values at the
        #report's headline years, since one column per model year runs to thirteen.
        cc_years = [y for y in table_years if y in set(cc_df['year'])]
        wide = cc_df.pivot_table(index='tech', columns='year', values='capacity_credit')
        share = cc_df.pivot_table(index='tech', columns='year', values='gen_frac')
        for tech in wide.index:
            cells = ''.join(
                f'<td class="num">{_num(wide.loc[tech, y], "{:.3f}")}'
                + (f'<span class="sub"> {share.loc[tech, y]:.0%}</span>'
                   if pd.notna(share.loc[tech, y]) else '') + '</td>'
                for y in cc_years)
            cc_rows.append(f'<tr>{tech_cell(tech)}{cells}</tr>')
    cc_table = table(
        'Capacity credit of each year&rsquo;s new builds, with that technology&rsquo;s market '
        'share in small type beside it',
        [('Technology', False)] + [(str(int(y)), True) for y in cc_years], cc_rows)

    # ---- 05 by transmission region ----
    reg_vf_fig = figure(output_dir, 'plcoe_pitch_storage_regional_vf.png', 11,
                        'Value factor of new storage by transmission region.',
                        'One panel per region, each on the same axes. The blue line is the '
                        'region&rsquo;s new-build value factor, value per MWh summed over its zones '
                        'that built that year, over the national benchmark price, as the national '
                        'value factor is built; the grey line is the national value factor. Both are '
                        'against the national market share of storage in that year, so every '
                        'region&rsquo;s points sit at the same x positions as the national curve. A '
                        'line breaks across years with no build.', order)
    reg_grid_fig = figure(output_dir, 'plcoe_pitch_storage_regional_vcf.png', 12,
                          'Value factor, cost factor and value&#8211;cost factor of new storage '
                          'by transmission region.',
                          'Every region on one panel, with the national curve in black. Value '
                          'factor is as in Fig 11. Value&#8211;cost factor is national: LCOE base, '
                          'the forcing multiplier and the benchmark price do not vary by region, so '
                          'each region takes the national value in the years it built, and a '
                          'region&rsquo;s cost factor is its value factor divided by that national '
                          'value&#8211;cost factor. Top row: against national market share, as in '
                          'Fig 11. Bottom row: against the region&rsquo;s own market share, its '
                          'storage discharge over its total generation excluding storage, the '
                          'national definition applied to the region. Points are joined in order '
                          'of market share.', order)
    reg_comp_nat_fig = figure(output_dir, 'plcoe_pitch_storage_regional_vf_components_national.png',
                              13, 'Energy and capacity components of new-storage value factor by '
                              'transmission region, against national market share.',
                              'The split of Fig 5 for each region: value from energy and from the '
                              'reserve margin, each per MWh over the national benchmark price, '
                              'stacked so the top edge is the region&rsquo;s value factor of Fig 11. '
                              'The grey line is the national value factor. Points are joined in '
                              'order of market share, so the areas run across years in which the '
                              'region built nothing.', order)
    reg_comp_reg_fig = figure(output_dir, 'plcoe_pitch_storage_regional_vf_components_regional.png',
                              14, 'Energy and capacity components of new-storage value factor by '
                              'transmission region, against regional market share.',
                              'Fig 13 against the region&rsquo;s own market share, as in the bottom '
                              'row of Fig 12. The grey national value factor is against national '
                              'market share.', order)
    reg_lv_fig = figure(output_dir, 'plcoe_pitch_storage_regional_lvoe_lvoc.png', 15,
                        'Levelized value of energy and of capacity of new storage by transmission '
                        'region.',
                        'The value streams of each year&rsquo;s new builds, summed over the '
                        'region&rsquo;s zones, per MWh discharged (left) and per kW of new capacity '
                        '(right), against model year, with the national value in black. Value per '
                        'MWh divided by the national benchmark price is the value factor of Fig 11. '
                        'Lines break across years in which a region built nothing.', order)

    reg = read_csv_or_empty(output_dir, 'plcoe_pitch_storage_regional_cc.csv')
    level = [c for c in reg.columns if c not in ('year', 'new_mw', 'cap_mw', 'peak_mw',
                                                 'penetration', 'capacity_credit')]
    level = level[0] if level else 'region'
    reg_fig = figure(output_dir, 'plcoe_pitch_storage_regional_cc.png', 16,
                     'Capacity credit of new storage by transmission region.',
                     f'One panel per {level} region, each on the same axes. The blue line is the '
                     'region&rsquo;s new-build capacity credit, the ratio of sums over its zones that '
                     'built that year as in section 04, against its installed storage capacity (MW) '
                     'as a share of its peak load (MW); the peak is coincident, the highest '
                     'stress-period block of the summed zone loads, which includes the planning '
                     'reserve margin ReEDS scales exogenous stress-period load up by (12% in these '
                     'runs). Every region-year that built '
                     'anything is drawn, joined in model-year order, so a line doubles back where '
                     'retirements cut installed capacity and breaks only across years with no build. '
                     'The grey line is the national curve built the same way. Every battery after the '
                     'initial fleet shares one vintage and valnew credits a new build with that '
                     'vintage&rsquo;s dispatch pro-rated by INV/CAP, so a zone&rsquo;s new-build credit '
                     'is its fleet credit; what the size of a region&rsquo;s build changes is how many '
                     'of its zones the ratio covers, so a small build can stand for one zone of '
                     'several.', order)
    reg_rows, reg_years = [], []
    if not reg.empty:
        reg_years = [y for y in table_years if y in set(reg['year'])]
        wide = reg.pivot_table(index=level, columns='year', values='capacity_credit')
        pen = reg.pivot_table(index=level, columns='year', values='penetration')
        built = reg.pivot_table(index=level, columns='year', values='new_mw')
        names = (sorted([n for n in wide.index if n != 'National'])
                 + (['National'] if 'National' in wide.index else []))
        for n in names:
            cells = ''
            for y in reg_years:
                b = built.get(y, pd.Series(dtype=float)).get(n, 0)
                p_ = pen.get(y, pd.Series(dtype=float)).get(n, np.nan)
                cells += (f'<td class="num">{_num(wide.loc[n, y] if b > 0 else np.nan, "{:.2f}")}'
                          + (f'<span class="sub"> {p_:.0%}</span>' if pd.notna(p_) else '')
                          + '</td>')
            label = f'<b>{n}</b>' if n == 'National' else n
            reg_rows.append(f'<tr><td class="t">{label}</td>{cells}</tr>')
    reg_table = table('Capacity credit of new storage by transmission region at the headline years, '
                      'with installed capacity as a share of peak load in small type. A dash is a '
                      'year in which the region built nothing',
                      [('Region', False)] + [(str(int(y)), True) for y in reg_years], reg_rows)

    rdur_fig = figure(output_dir, 'plcoe_pitch_storage_regional_duration.png', 17,
                      'Duration of the installed storage fleet by transmission region.',
                      'Fig 6 repeated for each region over its own zones: boxes are the '
                      'capacity-weighted 10th, 25th, 50th, 75th and 90th percentiles of zone fleet '
                      'duration in that model year, the red line is the capacity-weighted mean, and '
                      'the grey line is the national fleet mean of Fig 6. Box width is proportional '
                      'to the square root of the region&rsquo;s installed capacity. Region-years '
                      'with less than 100 MW installed are omitted. A region with one or two zones '
                      'has a box that collapses to a line.',
                      order)

    # ---- 06 stress-period arbitrage ----
    arb = read_csv_or_empty(output_dir, 'plcoe_pitch_storage_arbitrage.csv')
    #Block length as the run had it, so the caption follows a change of stress resolution.
    blk = (f'{arb["block_hours"].iloc[0]:g}'
           if not arb.empty and 'block_hours' in arb else 'GSw_HourlyChunkLengthStress')
    arb_fig = figure(output_dir, 'plcoe_pitch_storage_arbitrage.png', 18,
                     'How storage earns its reserve-margin value inside the stress periods.',
                     'Left: the reserve-margin price of each stress block, weighted by the '
                     'storage fleet&rsquo;s discharge and by its charging, on a log scale with the '
                     'span between them shaded. ReEDS reports these prices per MW per block, since '
                     'the blocks carry no weight in the annual objective; each block is '
                     f'{blk} hours long (GSw_HourlyChunkLengthStress), so a MW held through it is '
                     f'{blk} MWh, and the price per MW divided by the block length is the value of '
                     'a MWh delivered in that block. The price levels depend on the block length: '
                     're-cutting the stress periods holds this per-MWh price roughly fixed where a '
                     'long stretch of blocks binds, but not where one peak block carries most of '
                     'the day&rsquo;s value, which then keeps its price per MW instead. The ratio '
                     'of the two prices and the credit shares at right do not carry the unit. '
                     'Right: the same years split into the gross value of discharge and the cost of '
                     'charging, whose sum is the net capacity credit of the whole storage fleet in '
                     'every region, where the capacity credit of sections 04 and 05 is each '
                     'year&rsquo;s new builds; for storage the two differ only in which regions '
                     'count. gen_h_stress '
                     'is already net of charging for storage, so a negative entry is a charging '
                     'hour. Net energy over a stress period is zero or slightly negative for '
                     'storage &mdash; it discharges only what it charged, less round-trip losses '
                     '&mdash; so the whole of the capacity credit is the spread between these two '
                     'prices.', order)
    arb_rows = []
    for _, r in arb.iterrows():
        arb_rows.append(
            f'<tr><td class="t">{int(r["year"])}</td>'
            f'<td class="num">{_num(r["gw"], "{:.0f}")}</td>'
            f'<td class="num">{_num(r["price_discharge"], "{:,.0f}")}</td>'
            f'<td class="num">{_num(r["price_charge"], "{:,.0f}")}</td>'
            f'<td class="num">{_num(r["gross"], "{:.3f}")}</td>'
            f'<td class="num">{_num(r["charge_cost"], "{:.3f}")}</td>'
            f'<td class="num">{_num(r["net"], "{:.3f}")}</td></tr>')
    arb_table = table(
        f'Storage stress-period arbitrage by model year. Prices are {dollar_year}$/MWh delivered in '
        'a stress block; the last three columns are shares of fully-firm capacity value and the '
        'first two of them sum to the third',
        [('Year', False), ('Fleet GW', True), ('Discharge price', True), ('Charge price', True),
         ('Gross', True), ('Charging cost', True), ('Fleet net credit', True)], arb_rows)

    # ---- 07 reserve-margin formulation ----
    form_fig = figure(output_dir, 'plcoe_pitch_storage_formulation.png', 19,
                      'Storage under the two reserve-margin formulations.',
                      'The storage forcing case run twice: with the stress-period reserve margin, '
                      'the default and the basis of every other figure here, and with the '
                      'capacity-credit formulation (<span class="eq">GSw_PRM_CapCredit=1</span>), '
                      'which credits storage by duration bin against a fixed planning reserve margin '
                      'rather than by its dispatch in stress periods. Value factor, cost factor and '
                      'value&#8211;cost factor are as computed, without the LCOE-base scaling of '
                      'Fig 4, which is fitted per run; capacity credit is as in section 04. The '
                      'value&#8211;cost factor is LCOE base times the forcing multiplier over the '
                      'benchmark price and carries no value term, so the two runs can differ in it '
                      'only through the benchmark price; the formulation moves the split between '
                      'value factor and cost factor. Under the capacity-credit formulation, credited '
                      'storage MW are a share of a regional pool capped by the duration-bin sizes '
                      'from the capacity credit script, so storage&rsquo;s reserve-margin value is '
                      'taken net of the dual of the bin limit '
                      '(<span class="eq">eq_sdbin_power_limit</span>): what new storage adds to the '
                      'reserve margin rather than its share of the pool. The two runs are not held to '
                      'the same reliability standard: one meets an unserved-energy threshold, the '
                      'other a planning reserve margin.', order)
    form = read_csv_or_empty(output_dir, 'plcoe_pitch_storage_formulation.csv')
    form_rows = []
    if not form.empty:
        for y in [y for y in table_years if y in set(form['year'])]:
            for lab in form['formulation'].drop_duplicates():
                r = form[(form['year'] == y) & (form['formulation'] == lab)]
                if r.empty:
                    continue
                r = r.iloc[0]
                form_rows.append(
                    f'<tr><td class="t">{int(y)}</td><td class="t">{lab}</td>'
                    f'<td class="num">{_num(r["gen_frac"], "{:.1%}")}</td>'
                    f'<td class="num">{_num(r["value_factor"])}</td>'
                    f'<td class="num">{_num(r["vf_comp_resmarg"])}</td>'
                    f'<td class="num">{_num(r["cost_factor"])}</td>'
                    f'<td class="num">{_num(r["value_cost_factor"], "{:.3f}")}</td>'
                    f'<td class="num">{_num(r["capacity_credit"])}</td></tr>')
    form_table = table('Storage under the two reserve-margin formulations at the headline years',
                       [('Year', False), ('Formulation', False), ('Market share', True),
                        ('VF', True), ('VF, capacity part', True), ('CF', True), ('VCF', True),
                        ('Capacity credit', True)], form_rows)

    # ---- 08 per kW ----
    pk_fig = figure(output_dir, 'plcoe_pitch_storage_perkw.png', 20,
                    'Value factor, cost factor and value&#8211;cost factor per MWh and per kW.',
                    'Per MWh is as in the figures above: value per MWh of discharge over the '
                    'benchmark price, value over load MWh. Per kW divides value by new power '
                    'capacity and the benchmark by the reserve-margin requirement MW (the highest '
                    'stress-period load in each zone, summed), the same national ratio of sums. The '
                    'per-kW LCOE base is LCOE base at a capacity factor of 4/24, a four-hour battery '
                    'cycling once a day, so the per-kW value&#8211;cost factor is the per-MWh one '
                    'times those 1,460 hours over load MWh per requirement MW. Same run and market '
                    'share as Fig 2.', order)
    pk = read_csv_or_empty(output_dir, 'plcoe_pitch_storage_perkw.csv')
    pk_rows = []
    for _, r in pk[pk['year'].isin(table_years)].iterrows() if not pk.empty else []:
        pk_rows.append(
            f'<tr><td class="t">{int(r["year"])}</td>'
            f'<td class="num">{_num(r["gen_frac"], "{:.1%}")}</td>'
            f'<td class="num">{_num(r["value_factor"])}</td>'
            f'<td class="num">{_num(r["value_factor_perkw"])}</td>'
            f'<td class="num">{_num(r["cost_factor"])}</td>'
            f'<td class="num">{_num(r["cost_factor_perkw"])}</td>'
            f'<td class="num">{_num(r["value_cost_factor"], "{:.3f}")}</td>'
            f'<td class="num">{_num(r["value_cost_factor_perkw"], "{:.3f}")}</td>'
            f'<td class="num">{_num(r["benchmark_price_perkw"], "{:.0f}")}</td></tr>')
    pk_table = table('Per MWh and per kW at the headline years',
                     [('Year', False), ('Market share', True), ('VF per MWh', True),
                      ('VF per kW', True), ('CF per MWh', True), ('CF per kW', True),
                      ('VCF per MWh', True), ('VCF per kW', True),
                      ('Benchmark ($/kW-yr)', True)], pk_rows)

    fell_back = any(isinstance(o, tuple) for o in order)
    if vr.embed_figures and not fell_back:
        packaging = (f'Figures are embedded at up to {vr.embed_max_width}px wide; the full-size pngs '
                     'are alongside this page.')
    elif vr.embed_figures:
        packaging = ('Figures are referenced rather than embedded, because Pillow was not '
                     'available. This page only renders next to them.')
    else:
        packaging = 'Figures are referenced by filename. This page only renders next to them.'

    def sec(num, title, *blocks):
        body = ''.join(b for b in blocks if b)
        return (f'<section><div class="shead"><div class="snum">{num}</div><h2>{title}</h2></div>'
                f'{body}</section>') if body else ''

    return f'''<title>{report_title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <div class="lbl">ReEDS &middot; value&#8211;cost factor analysis &middot; storage</div>
  <h1>{report_title}</h1>
  <p class="stand">The storage figures of the value&#8211;cost factor pipeline, from the run that
  forces storage, and the capacity credit of every technology, with a description of what each
  one plots. The companion page,
  valcostfac_report.html, covers every technology on shared terms. Numbers are computed from the
  tables written alongside this page, so re-running the report restates them.</p>
  <div class="meta"><span>{storage_tech}</span><span>scenario: {scen}</span>
    <span>{dollar_year}$</span></div>
</header>

{sec('01', 'PLCOE, value factor and value&#8211;cost factor', lcoe_year_fig, lcoe_share_fig, vcf_unfit_fig, vcf_fig)}

{sec('02', 'Value factor by component', comp_fig, comp_table)}

{sec('03', 'Duration',
     '<div class="col"><p>Power and energy capacity are separate investment variables, so the '
     'duration of what is built is an outcome of the model rather than an assumption.</p></div>',
     dur_fig, dur_table)}

{sec('04', 'Capacity credit of new builds',
     '<div class="col"><p>The reserve-margin component of value per MW, expressed as a share of '
     'what a perfectly firm MW earns in the same place and year &mdash; the part of the value '
     'factor that firmness accounts for &mdash; for every technology, so storage can be read '
     'against the others. The first figure uses the market-share axis of the value-factor curves '
     'in the main report. Each technology is read from its own forcing run. Under the '
     'capacity-credit formulation of the reserve margin '
     '(<span class="eq">GSw_PRM_CapCredit=1</span>) the reserve-margin value comes from seasonal '
     'firm capacity rather than stress-period dispatch, net of the duration-bin dual for storage, '
     'and CSP and hybrid PV-battery are not covered.</p></div>',
     cc_fig, cc_table, cc_gw_fig, cc_cap_fig, cc_sc_fig, cc_sc_table)}

{sec('05', 'By transmission region', reg_vf_fig, reg_grid_fig, reg_comp_nat_fig, reg_comp_reg_fig, reg_lv_fig, reg_fig, reg_table, rdur_fig)}

{sec('06', 'Capacity credit inside the stress periods',
     '<div class="col"><p>Storage&rsquo;s capacity credit is built differently from the other '
     'technologies&rsquo;: a battery delivers no net energy over a stress period, so what it earns '
     'there is entirely the price spread between the blocks it discharges in and the blocks it '
     'charges in.</p></div>', arb_fig, arb_table)}

{sec('07', 'Reserve-margin formulation',
     '<div class="col"><p>A sensitivity on how ReEDS represents resource adequacy, which sets most '
     'of what storage is credited for.</p></div>', form_fig, form_table)}

{sec('08', 'Per kW', pk_fig, pk_table)}

<section style="border-bottom:none">
  <footer>Generated by <code>battery_report.py</code> from the figures and tables in this
  directory. All monetary values {dollar_year}$. {packaging}</footer>
</section>
</div>
'''


def make_report(valcostfac_core_path=valcostfac_core_path, output_dir=None):
    """Write the html report next to the figures it references."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(valcostfac_core_path))
    html = build_html(output_dir, valcostfac_core_path)
    path = os.path.join(output_dir, report_name)
    with open(path, 'w') as f:
        f.write(html)
    size = os.path.getsize(path)
    how = 'figures embedded' if vr.embed_figures else 'figures referenced'
    unit = f'{size / 1048576:.1f} MB' if size > 1048576 else f'{size / 1024:.0f} kB'
    print(f'Wrote {path} ({unit}, {how})')
    return path


if __name__ == '__main__':
    make_report()
