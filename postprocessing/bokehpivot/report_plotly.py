"""
Interactive Plotly versions of report figures, layered over the static ones.

Each interactive figure is the report's ordinary figure block (the embedded png and its caption)
with a chart spec and a collapsed data table added. A script at the end of the page loads Plotly
from cdnjs and swaps each png for its chart; if Plotly does not load, the png stays. Charts take
their colours from the page's CSS tokens, so they follow light and dark mode.
"""
import html
import json
import os
import numpy as np
import pandas as pd

# User inputs
plotly_src = 'https://cdnjs.cloudflare.com/ajax/libs/plotly.js/4.2.0/plotly-cartesian.min.js' #Plotly bundle the page loads. The cartesian bundle covers scatter and line charts at about a third of the full bundle's size.
series_colors = [('#2A6F8E', '#5BA4C8'), ('#C0392B', '#E8705C')] #(light, dark) line colour of each series, in order: the base run, then the sensitivity. The light pair is the matplotlib figures' pair; the dark pair is lighter steps of the same hues for the dark surface.
series_styles = [('solid', 'circle'), ('dash', 'square')] #(line dash, marker symbol) of each series, matching the matplotlib figures, so the runs differ by more than colour.

CSS = '''
figure.pfig .plot{width:100%;}
figure.pfig details{margin-top:.7rem;font-size:.8rem;color:var(--muted);}
figure.pfig summary{cursor:pointer;font-family:"IBM Plex Mono",monospace;font-size:.7rem;
  letter-spacing:.08em;text-transform:uppercase;}
figure.pfig details .tw{margin-top:.6rem;}
'''

JS = '''
(function(){
  const figs = Array.from(document.querySelectorAll('figure.pfig'));
  if (!figs.length) return;
  const root = document.documentElement;
  const isDark = () => root.dataset.theme ? root.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  const tok = v => getComputedStyle(root).getPropertyValue(v).trim();
  const ncols = w => w >= 900 ? 4 : w >= 540 ? 2 : 1;
  function draw(fig) {
    const spec = JSON.parse(fig.querySelector('script.pspec').textContent);
    const el = fig.querySelector('.plot');
    const nc = ncols(el.clientWidth), np = spec.panels.length, nr = Math.ceil(np / nc);
    const dark = isDark(), ink = tok('--ink'), muted = tok('--muted'), rule = tok('--rule'),
          grid = tok('--rule-soft'), bg = tok('--raise');
    const traces = [], annotations = [], shapes = [];
    const layout = {
      height: nr * (nc === 1 ? 250 : 255) + (nc === 1 ? 90 : 70), paper_bgcolor: bg, plot_bgcolor: bg,
      font: {family: '"IBM Plex Sans", system-ui, sans-serif', size: 12, color: muted},
      margin: {l: 52, r: 14, t: nc === 1 ? 84 : 64, b: 44},
      grid: {rows: nr, columns: nc, pattern: 'independent', xgap: 0.22, ygap: nc === 1 ? 0.45 : 0.32},
      showlegend: true,
      legend: {orientation: 'h', x: 0, xanchor: 'left', yref: 'container', y: 1, yanchor: 'top',
               font: {color: ink}},
      hovermode: 'closest', hoverdistance: 24,
      hoverlabel: {bgcolor: bg, bordercolor: rule, font: {color: ink, size: 12}},
      annotations: annotations, shapes: shapes
    };
    spec.panels.forEach((p, i) => {
      const n = i ? String(i + 1) : '';
      layout['xaxis' + n] = {title: {text: spec.xlabel, font: {size: 11}}, rangemode: 'tozero',
        ticksuffix: '%', gridcolor: grid, linecolor: rule, zeroline: false, ticks: 'outside',
        tickcolor: rule, automargin: true};
      layout['yaxis' + n] = {rangemode: 'tozero', gridcolor: grid, linecolor: rule,
        zeroline: false, ticks: 'outside', tickcolor: rule, automargin: true,
        tickformat: p.ymax ? ',.0f' : null};
      if (p.ymax) layout['yaxis' + n].range = [0, p.ymax];
      annotations.push({text: p.title, xref: 'x' + n + ' domain', yref: 'y' + n + ' domain',
        x: 0, y: 1, xanchor: 'left', yanchor: 'bottom', yshift: 4, showarrow: false,
        font: {size: 13, color: ink}});
      const top = Math.max(...spec.series.flatMap(s => s.y[p.col].filter(v => v !== null)));
      if (p.ref1 && top >= 1) shapes.push({type: 'line', xref: 'x' + n + ' domain', x0: 0, x1: 1,
        yref: 'y' + n, y0: 1, y1: 1, layer: 'below', line: {color: muted, width: 1, dash: 'dot'}});
      spec.series.forEach(s => {
        const color = dark ? s.color[1] : s.color[0];
        traces.push({type: 'scatter', mode: 'lines+markers', x: s.x, y: s.y[p.col],
          customdata: s.year, connectgaps: true, name: s.label, legendgroup: s.label,
          showlegend: i === 0, xaxis: 'x' + n, yaxis: 'y' + n,
          line: {color: color, width: 2, dash: s.dash},
          marker: {size: 7, symbol: s.symbol, color: color, line: {color: bg, width: 1}},
          hovertemplate: '<b>' + s.label + '</b><br>%{customdata} &middot; %{x:.1f}%<br>'
            + p.title + ': %{y:' + p.fmt + '}<extra></extra>'});
      });
    });
    Plotly.react(el, traces, layout, {displaylogo: false, responsive: true, displayModeBar: nc > 1,
      modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
      toImageButtonOptions: {format: 'png', scale: 2}});
    el.dataset.ncols = nc;
  }
  function init() {
    figs.forEach(fig => {
      const img = fig.querySelector('img'), el = fig.querySelector('.plot');
      el.hidden = false;
      try { draw(fig); if (img) img.style.display = 'none'; }
      catch (e) { el.hidden = true; console.error(e); }
    });
    let t;
    addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => figs.forEach(fig => {
      const el = fig.querySelector('.plot');
      if (!el.hidden && String(ncols(el.clientWidth)) !== el.dataset.ncols) draw(fig);
    }), 150); });
    const redraw = () => figs.forEach(fig => { if (!fig.querySelector('.plot').hidden) draw(fig); });
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redraw);
    new MutationObserver(redraw).observe(root, {attributes: true, attributeFilter: ['data-theme']});
  }
  if (window.Plotly) { init(); return; }
  const s = document.createElement('script');
  s.src = PLOTLY_SRC; s.onload = init; document.head.appendChild(s);
})();
'''


def page_script():
    """The script that turns every interactive figure on the page into its chart. Put it once, at
    the end of the page."""
    return f'<script>{JS.replace("PLOTLY_SRC", json.dumps(plotly_src))}</script>'


def _clean(values, digits=4):
    return [None if pd.isna(v) else round(float(v), digits) for v in values]


def interactive_figure(static_html, csv_path, panels, x, xlabel, scenario, table_html=''):
    """Add a Plotly chart to a static figure block from figure().

    csv_path is the table the static figure was drawn from, one row per run and year with a
    scenario and a variant (series label) column. panels is a list of dicts with col, title, fmt (a
    d3 number format for the hover), and optionally ymax (initial y range cap) and ref1 (a dotted
    line at 1, where the data reaches 1). x is the column on the x axis, a fraction drawn as a percent. The run named
    scenario is drawn second, the others first. Returns static_html unchanged if the figure or its
    table is missing.
    """
    if not static_html or not os.path.exists(csv_path):
        return static_html
    d = pd.read_csv(csv_path)
    runs = sorted(d['scenario'].unique(), key=lambda s: s == scenario)
    series = []
    for i, scen in enumerate(runs):
        r = d[d['scenario'] == scen].dropna(subset=[x]).sort_values(x)
        series.append({'label': r['variant'].iloc[0], 'color': series_colors[i],
                       'dash': series_styles[i][0], 'symbol': series_styles[i][1],
                       'x': _clean(r[x] * 100, 3), 'year': r['year'].astype(int).tolist(),
                       'y': {p['col']: _clean(r[p['col']]) for p in panels}})
    spec = {'xlabel': xlabel, 'panels': panels, 'series': series}
    spec_json = json.dumps(spec, separators=(',', ':')).replace('</', '<\\/')
    plot = (f'<div class="plot" hidden></div>'
            f'<script type="application/json" class="pspec">{spec_json}</script>')
    data = (f'<details><summary>Data</summary>{table_html}</details>' if table_html else '')
    out = static_html.replace('<figure>', '<figure class="pfig">', 1)
    out = out.replace('<figcaption>', plot + '<figcaption>', 1)
    return out.replace('</figure>', data + '</figure>', 1)


def sensitivity_table(csv_path, panels, x, xname, table_fn):
    """The data of a sensitivity chart as a table block: one row per run and year, with x and each
    panel's quantity. table_fn is the report's table() helper."""
    d = pd.read_csv(csv_path).sort_values(['variant', 'year'])
    headers = [('Run', False), ('Year', True), (xname, True)] + [(p['title'], True) for p in panels]
    rows = []
    for _, r in d.iterrows():
        cells = [f'<td class="t">{html.escape(str(r["variant"]))}</td>',
                 f'<td class="num">{int(r["year"])}</td>',
                 f'<td class="num">{r[x] * 100:.1f}%</td>']
        for p in panels:
            v = r[p['col']]
            cells.append('<td class="num">&mdash;</td>' if pd.isna(v) else
                         f'<td class="num">{v:{p["pyfmt"]}}</td>')
        rows.append(f'<tr>{"".join(cells)}</tr>')
    return table_fn('Values plotted, by run and model year', headers, rows)
