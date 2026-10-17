from __future__ import annotations

import importlib

GROUP_TITLES = {
    "slice": "Slice group: load, dispatch, capacity stock, supply curves, storage, transmission capacity, emissions",
    "stock": "Stock group: retirements, prescriptions, refurbishment, upgrades, upsizing",
    "ops": "Operations group: reserves, ramping, dispatch limits, biomass, mandates",
    "trans": "Transmission investment group",
    "spur": "Spur-line group: reV-site spur lines",
    "policy": "Policy group: carbon caps, CSAPR, RECs, queues, growth limits",
    "h2": "Hydrogen and production group",
    "objective": "Objective function",
    "unported": "Not ported (switch off in both reference cases)",
}

HELPERS = {
    "_in": ("reeds/open/prep.py", "def _in(", None,
            "Keep the rows whose column <code>col</code> is a member of a set. GAMS: a <code>$set(i)</code> condition on one index."),
    "_not_in": ("reeds/open/prep.py", "def _not_in(", None,
                "Keep the rows whose column <code>col</code> is not a member of a set. GAMS: <code>$[not set(i)]</code>."),
    "_on_domain": ("reeds/open/prep.py", "def _on_domain(", None,
                   "Left-join a parameter onto a constraint domain and fill missing values with 0, so a GAMS row whose constant is zero still exists."),
    "_add": ("reeds/open/prep.py", "def _add(", None,
             "Add sign × right onto the rows of left; a missing right value counts as 0, as a missing GAMS parameter does."),
    "_signed": ("reeds/open/prep.py", "def _signed(", None, "A coefficient table with a constant value on every row of a domain."),
    "_mul": ("reeds/open/prep.py", "def _mul(", None, "Inner join of two coefficient tables with the values multiplied (GAMS: missing = 0)."),
    "_fsum": ("reeds/open/prep.py", "def _fsum(", None, "Group-by sum with math.fsum, which matches GAMS extended-precision accumulation."),
    "_stock_terms": ("reeds/open/prep.py", "def _stock_terms(", None,
                     "For a capacity-stock domain: the coefficient table of the current-year investment variable and the constant that collects "
                     "prior-year investments (state tables), prescribed retirements and an optional exogenous addition."),
    "_netup_cur": ("reeds/open/prep.py", "def _netup_cur(", None,
                   "Current-year UPGRADES and UPGRADES_RETIRE columns of the upgrade techs ii that upgrade from i, with the GAMS right-hand-side signs."),
    "_netup_past": ("reeds/open/prep.py", "def _netup_past(", None,
                    "Net prior-year upgrades Σ(UPGRADES − UPGRADES_RETIRE) of techs ii upgrading from i, over fixed years up to the column named by upto."),
    "_prev_cap": ("reeds/open/prep.py", "def _prev_cap(", None,
                  "Constant for the retmo equations: CAP of the previous solve year (optionally degraded) plus net upgrades up to that year, "
                  "minus net prior-year upgrades up to the current year."),
    "_capup_terms": ("reeds/open/prep.py", "def _capup_terms(", None,
                     "Current-year INV_CAP_UP coefficients (degrade_new(i,t,t) or 1) and the constant from prior-year INV_CAP_UP levels."),
    "load_terms": ("reeds/open/prep.py", "def load_terms(", None,
                   "REC requirement load terms by RecStyle: constants from Canada exports, LOAD coefficients and GEN coefficients (distpv / all gen)."),
    "into": ("reeds/open/prep.py", "def into(", None, "RECS columns imported into the row state (ast = row state)."),
    "outof": ("reeds/open/prep.py", "def outof(", None, "RECS columns exported out of the row state (st = row state, ast ≠ st)."),
    "bundled_terms": ("reeds/open/prep.py", "def bundled_terms(", None,
                      "Bundled-category RECS columns credited to the unbundled row category (rps_bundled → rps_all, ces_bundled → ces)."),
    "recs_coef": ("reeds/open/prep.py", "def recs_coef(", None,
                  "Stack RECS coefficient parts into one table keyed by row (rpscat, st, t) and column (rpscat_v, i, st_v, ast)."),
    "_fsum_all": ("reeds/open/prep.py", "def _fsum_all(", None,
                  "Sum a whole column with math.fsum (exactly rounded), used for scalar constants so the result does not depend on row order."),
    "_scale": ("reeds/open/prep.py", "def _scale(", None,
               "Multiply objective coefficients by cost_scale and the present-value factor of their year (pvf_capital or pvf_onm)."),
    "_objective": ("reeds/open/prep.py", "def _objective(", None,
                   "Objective coefficients of one variable: the precomposed slice_objinv_ or slice_objop_ table restricted to the variable domain, "
                   "then scaled; rows outside the domain are counted in options['objective_rows_off_domain']."),
    "_sorted": ("reeds/open/prep.py", "def _sorted(", None,
                "Sort every domain and coefficient table by its index columns so row and column order, and hence the vertex HiGHS returns, are reproducible."),
    "P": ("reeds/open/build_pyoframe.py", "def P(", None,
          "Wrap a coefficient table (index columns plus <code>value</code>) as a pyoframe parameter, so <code>P(K[...]) * m.VAR</code> "
          "is an inner join on the shared index columns."),
    "_row": ("reeds/open/build_pyoframe.py", "def _row(", None,
             "Build one constraint from a constant table and a list of (coefficient table, variable, rename, sum_by[, post-rename]) terms; "
             "the row set is the union of the term rows, missing terms count as zero."),
    "U": ("reeds/open/build_pyoframe.py", "def U(", None,
          "Union-sum of pyoframe expressions: each term is marked <code>keep_extras()</code>, so a label present in only one term is kept and "
          "the missing terms count as 0 (a GAMS sum of terms defined over different domains)."),
    "_term_entries": ("reeds/open/build_linopy.py", "def _term_entries(", None,
                      "linopy: one term of a row as (row index, column label, value) triples. The coefficient table is inner-joined to the "
                      "variable domain (renamed first) on their shared index columns, the column label is the variable's position in its domain, "
                      "and the row index is <code>sum_by</code> (a GAMS sum) or the full joined index, renamed by <code>post</code>."),
    "_add_row": ("reeds/open/build_linopy.py", "def _add_row(", None,
                 "linopy: build one constraint from the algebra Row. The row set is the sorted union of the term rows and the constant's rows; "
                 "entries are summed per (row, column), packed into padded coefficient and label arrays over (row, _term) with label −1 for "
                 "no variable, and added as <code>expr sense −const</code>."),
    "semi": ("reeds/open/derive.py", "def semi(", None,
             "Rows of df whose keys appear in other (polars semi join on the distinct keys). GAMS: a <code>$set(i,v,r,t)</code> condition."),
    "anti": ("reeds/open/derive.py", "def anti(", None,
             "Rows of df whose keys do not appear in other (polars anti join). GAMS: <code>$[not set(i,v,r,t)]</code>."),
    "isin": ("reeds/open/derive.py", "def isin(", None,
             "polars expression that is true when a column value is in a Python set; used inside <code>filter</code> and <code>when</code>."),
    "members": ("reeds/open/derive.py", "def members(", None, "The members of a one-column set table as a Python set."),
    "one_col": ("reeds/open/derive.py", "def one_col(", None, "Build a sorted one-column string set table."),
    "cross": ("reeds/open/derive.py", "def cross(", None, "Cartesian product of several tables. GAMS: an index that ranges over a whole set."),
    "lookup": ("reeds/open/derive.py", "def lookup(", None,
               "Left join one parameter onto a table under a new column name and fill missing values with <code>fill</code> "
               "(0 by default, because a missing GAMS parameter is 0)."),
    "fsum_by": ("reeds/open/derive.py", "def fsum_by(", None,
                "Group-by sum with math.fsum per group. GAMS accumulates sums in extended precision, so a plain float sum can differ in the last digits."),
    "nonzero": ("reeds/open/derive.py", "def nonzero(", None, "Drop zero values: GAMS stores no zeros, so a zero parameter entry does not exist."),
    "gams_round": ("reeds/open/derive.py", "def gams_round(", None,
                   "GAMS <code>round(x, n)</code>: half away from zero, which differs from the round-half-to-even of polars and numpy."),
    "yr": ("reeds/open/derive_capacity.py", "def yr(", None,
           "Cast a year column to integer for comparisons such as <code>yeart(tt) &lt;= yeart(t)</code>."),
    "_assign": ("reeds/open/derive_capacity.py", "def _assign(", None,
                "GAMS conditional assignment <code>x(keys)$domain = new</code>: rows of target inside domain are replaced by new, rows outside "
                "keep their old value, and zeros in new are dropped."),
}

SYNTAX = [
    ("<code>eq_x(r,h,t).. sum{...} =g= const</code>", "linopy: <code>_add_row</code> builds a <code>LinearExpression</code> over <code>(eq_x_idx, _term)</code>",
     "Every variable has one flat integer coordinate (its position in the prep domain). A row is the padded list of (coefficient, column label) "
     "pairs; a label of −1 means no variable. <code>add_constraints(expr, sign, rhs)</code> adds the row with <code>rhs = −const</code>."),
    ("<code>coef(i,r) * CAP(i,v,r,t)</code> in a row", "linopy: <code>_term_entries</code> inner join of the coefficient table with the variable domain",
     "Same join as pyoframe's parameter times variable, written out: the shared index columns are the join key, the variable's position becomes the "
     "column label, and <code>sum_by</code> groups the entries to the row index."),
    ("GAMS marginal / reduced cost", "linopy: <code>m.dual[eq]</code>; <code>c − Aᵀy</code> from <code>m.matrices</code>",
     "Duals come from HiGHS through linopy in constraint-label order; reduced costs are recomputed from the matrices because linopy does not expose them."),
    ("<code>sum{(i,v)$valgen(i,v,r,t), GEN(i,v,r,h,t)}</code>",
     '<code>m.GEN.to_expr().within(K[...]).sum_by("r", "h", "t")</code>',
     "Restrict a variable to the labels of a table (the $-condition), then sum out the indices that are not kept. "
     "<code>to_expr</code> turns the variable into an expression, <code>within</code> filters it, <code>sum_by</code> keeps the named dimensions."),
    ("<code>coef(i,r) * CAP(i,v,r,t)</code>", '<code>P(K["coef"]) * m.CAP</code>',
     "Parameter times variable is an inner join on the shared index columns; a missing coefficient drops the term, like a zero GAMS parameter."),
    ("<code>term_a + term_b</code> over different domains", "<code>U(a, b)</code>, which is <code>a.keep_extras() + b.keep_extras()</code>",
     "pyoframe refuses to add expressions whose labels differ unless told how; <code>keep_extras</code> keeps a label present on one side "
     "and the other side contributes 0."),
    ("<code>CAP(i,v,r,t) - GEN(i,v,r,h,t)</code> where GEN has extra labels", "<code>... - m.GEN.drop_extras()</code>",
     "Drop the labels of GEN that are not on the domain of the other side: a $-filter on the variable."),
    ("<code>FLOW(rr,r,h,t,trtype)</code> (indices swapped)", '<code>m.FLOW.rename({"r": "rr", "rr": "r"})</code>',
     "Rename index columns so the variable lines up with the row index, for example imports into r."),
    ("<code>STORAGE_LEVEL(i,v,r,hh,t)$nexth(h,hh)</code>", '<code>m.STORAGE_LEVEL.rename({"h": "hh"}).map(K["nexth"])</code>',
     "Map one index onto another through a mapping table (h to its successor hh)."),
    ("<code>eq(...).. lhs =g= rhs</code>", "<code>m.eq = expr &gt;= 0</code> with expr = lhs &minus; rhs",
     "Every row is written as (left side) &minus; (right side) against 0, so the solver dual carries the GAMS marginal sign."),
    ("<code>$[set(i)]</code> on a table", '<code>_in(df, "i", S["set"])</code> or <code>semi(df, set_table, keys)</code>',
     "Keep rows by membership: <code>_in</code> tests one column against a Python set, <code>semi</code> tests several key columns against a table."),
    ("<code>$[not set(i)]</code>", "<code>_not_in(...)</code> or <code>anti(...)</code>", "The complement of the row above."),
    ("<code>param(i,r)</code> read where missing = 0",
     '<code>df.join(par, on=keys, how="left")</code> then <code>fill_null(0.0)</code>; <code>_on_domain</code>; <code>lookup</code>',
     "A left join keeps every row of the domain and a missing parameter value becomes 0."),
    ("<code>a(i) + b(i)</code> as data", "<code>_add(left, right, on)</code>", "Left join right onto left and add; a missing right value is 0."),
    ("<code>a(i) * b(i)</code> as data", "<code>_mul(left, right, on)</code>", "Inner join and multiply; a missing factor removes the row."),
    ("<code>sum{j, x(i,j)}</code> as data",
     '<code>_fsum(df, keys)</code>, <code>fsum_by(df, keys)</code>, <code>group_by(keys).agg(pl.col("value").sum())</code>',
     "Group-by sum over the dropped index; the fsum versions are used where the result must match GAMS to the last digit."),
    ("<code>x(i)$cond = expr</code>", "<code>_assign(target, new, keys, domain)</code>",
     "Conditional assignment: replace the rows inside the domain, keep the rows outside."),
    ("<code>(i,j)</code> over whole sets", '<code>a.join(b, how="cross")</code> or <code>cross(a, b)</code>', "Cartesian product of index sets."),
    ("GAMS stores no zeros", '<code>nonzero(df)</code> or <code>filter(pl.col("value") != 0.0)</code>',
     "A stored zero would otherwise create a term or a row that GAMS does not have."),
    ("<code>round(x, n)</code>", "<code>gams_round(expr, n)</code>", "Half away from zero, as in GAMS."),
    ("<code>yeart(tt) &lt;= yeart(t)</code>", '<code>yr("tt") &lt;= yr("t")</code>',
     "Years are strings in the tables and are cast to integers to compare them."),
]

SYNTAX_PATTERNS = [
    (r"\.within\(", "<code>.within(table)</code>: keep only the labels present in table"),
    (r"\.sum_by\(", "<code>.sum_by(dims)</code>: keep dims and sum out every other index"),
    (r"\.keep_extras\(\)", "<code>.keep_extras()</code>: keep labels missing on the other side of + (counted as 0)"),
    (r"\.drop_extras\(\)", "<code>.drop_extras()</code>: drop labels missing on the other side of + or &minus;"),
    (r"\.to_expr\(\)", "<code>.to_expr()</code>: turn a variable into an expression so it can be filtered"),
    (r"\.map\(", "<code>.map(table)</code>: re-index through a mapping table"),
    (r"\.rename\(", "<code>.rename({...})</code>: rename index columns to line up with the row"),
    (r'how="semi"', '<code>how="semi"</code>: keep rows whose keys are in the other table ($-condition)'),
    (r'how="anti"', '<code>how="anti"</code>: keep rows whose keys are not in the other table'),
    (r'how="inner"', '<code>how="inner"</code>: keep matching rows of both (a missing factor removes the row)'),
    (r'how="left"', '<code>how="left"</code>: keep every row of the left table (missing values become null, then 0)'),
    (r'how="cross"', '<code>how="cross"</code>: Cartesian product'),
    (r"fill_null\(", "<code>fill_null(0.0)</code>: a missing GAMS parameter is 0"),
    (r"group_by\(", "<code>group_by(keys).agg(...)</code>: sum over the indices not in keys"),
    (r"pl\.concat\(", "<code>pl.concat([...])</code>: stack row sets (union of domains)"),
    (r"\.unique\(", "<code>.unique()</code>: distinct rows, so a domain has no duplicates"),
    (r"pl\.when\(", "<code>pl.when(c).then(a).otherwise(b)</code>: elementwise conditional (GAMS <code>$</code> on a value)"),
]

INTRO = """
<p>This page lists every equation of the ReEDS GAMS model (<code>reeds/core/setup/c_model.gms</code> and <code>d_objective.gms</code>) with,
for each one, the GAMS source verbatim, the equation written out mathematically with every term, and the port code that builds the same row:
the coefficient tables from <code>reeds/open/prep.py</code>, the row specification from <code>reeds/open/algebra.py</code> (one entry per equation:
constant table, terms as coefficient table × variable with index rename, sum and post-rename, and the sense), and, where a coefficient is
precomposed from input symbols, the derivation in <code>reeds/open/derive_*.py</code>. Two builders read the same specification:
<code>reeds/open/build_pyoframe.py</code> (polars-backed pyoframe expressions) and <code>reeds/open/build_linopy.py</code> (xarray-backed linopy).
The blue <b>linopy</b> box under each equation shows how that builder turns the specification into a sparse row: for each term the coefficient
table, the variable with its index after renaming, the join key, and the row index after summation; the right-hand side is minus the constant table.
The "GAMS term" table maps each term of the GAMS equation to its mathematical symbol and to the coefficient table that carries it in the port, and
says whether the term is ported, folded into a precomposed coefficient, or absent.</p>
<p>Every port row is written as (GAMS left side) − (GAMS right side) = 0 or ≥ 0, so a positive coefficient in a table is a left-side term.
GAMS stores no zeros and a <code>$param</code> condition means "nonzero"; the port keeps that rule: a missing coefficient removes a term, a
constant that is zero still produces a row. GAMS CONVERT drops rows without variables and columns that appear in no row, and the port restricts
its domains the same way.</p>
<p>Status badges: <b>validated</b> means the equation produced rows in at least one reference case and the matrix, bounds, objective, GAMS
primal point and KKT conditions matched; <b>ported, no rows</b> means the port has code for the equation but both reference cases gave it zero
rows in GAMS and in the port, so the code path has not been exercised against GAMS; <b>not ported</b> means the switch is off in both cases and
<code>prep.prepare</code> raises if it is turned on.</p>
<p>Terms flagged <b>no guard</b> in a term table are GAMS terms the port drops without a check that would stop a run in which they are active.
They are collected in the notes of the affected equations.</p>
"""

NOTATION = """
<ul>
<li>Upright names are variables (\\(\\V{CAP}_{i,v,r,t}\\)), italic names are parameters (\\(\\P{avail}_{i,r,h}\\)). Names keep their GAMS spelling.</li>
<li>\\(\\sw{Sw\\_X}\\) is 1 when switch Sw_X is on (or the stated condition holds) and 0 otherwise; a term multiplied by it is dropped by GAMS when it is 0.</li>
<li>\\(\\mathcal{T}=\\mathrm{tfix}\\cup\\mathrm{tmodel}\\) is the set of solved years; \\(t\\) is the current solve year, \\(t^-\\) the previous one (\\(\\mathrm{tprev}(t,t^-)\\)).
In the port \\(\\mathrm{tmodel}=\\{t\\}\\), and sums over \\(tt\\in\\mathcal{T},\\ tt\\le t\\) split into the current-year variable plus a constant built from the prior-year levels
(<code>state_*</code> tables read from the GAMS solution gdx of the previous year).</li>
<li>\\(h_{rep}\\), \\(h_{stress}\\): representative and stress timeslices; \\(\\P{hours}_h\\) their weights; \\(\\P{hd}_h=\\P{hours\\_daily}_h\\).</li>
<li>Sums are over the GAMS <code>$</code>-conditions written under the sum sign; set memberships such as \\(\\mathrm{valgen}(i,v,r,t)\\) are written as \\((i,v)\\in\\mathrm{valgen}_{r,t}\\).</li>
<li>Precomposed coefficients: \\(\\kappa\\) (capacity-limit availability), \\(\\kappa^{s}\\) (storage capacity), \\(d\\) (storage duration), \\(\\P{rsc\\_cap}\\) (gross supply-curve capacity),
\\(\\P{prescr}\\) (degraded prescribed retirements), \\(c^{inv}_\\bullet\\), \\(c^{op}_\\bullet\\) (objective coefficients) are computed once in <code>derive_*.py</code>; the code is shown with the equation that uses them.</li>
</ul>
"""

EQUATIONS: dict[str, dict] = {}
for mod in ["compare_spec_slice", "compare_spec_stock", "compare_spec_ops", "compare_spec_trans", "compare_spec_spur", "compare_spec_policy",
            "compare_spec_h2", "compare_spec_unported"]:
    try:
        m = importlib.import_module(f"{__package__}.{mod}")
    except ModuleNotFoundError as e:
        if e.name != f"{__package__}.{mod}":
            raise
        continue
    for k in m.SPEC:
        if k in EQUATIONS:
            raise KeyError(f"duplicate comparison spec for {k} in {mod}")
    EQUATIONS.update(m.SPEC)
