"""Shared plain-language captions for the surrogate-model evaluation surfaces.

Two surfaces consume these strings:

* ``surrogate_dashboard.py`` — the *Evaluation results* tab in the bokeh
  dashboard (renders explainers as HTML ``Div`` widgets).
* ``surrogate_eval.py`` — ``REPORT.md`` / ``REPORT.html`` (renders the same
  explainers as markdown blockquotes).

The single source of truth is :data:`EXPLAINERS`. Edit the strings here and
both surfaces update on next launch / re-run. Captions are intentionally
**static** (always-true descriptions of what each chart is and how to read
it) so they don't go stale across re-runs. The optional auto-readouts in
:func:`auto_readout_r0` / :func:`auto_readout_r5` build the only data-driven
sentences and are clearly labelled "Current run:".
"""
from __future__ import annotations

from typing import Iterable, Mapping

# ---------------------------------------------------------------------------
# Top-of-page intro (shown once at the very top of the Evaluation tab and
# at the start of REPORT.md). Kept conversational — assumes the reader
# understands power-system modelling but not statistics / ML.
# ---------------------------------------------------------------------------

INTRO_BODY = (
    "**What this page is:** We built fast \"surrogate\" models that imitate "
    "the full ReEDS capacity-expansion model. We ran ReEDS 486 times — every "
    "combination of six input settings (demand, fuel price, renewable cost, "
    "siting, battery cost, policy) — and trained the surrogates to reproduce "
    "those results in an instant. Each chart below answers one question "
    "about how far you can trust those instant predictions.\n\n"
    "**Three terms used throughout:** **R²** = how much of the "
    "scenario-to-scenario variation a model captures (1.0 = perfect, "
    "0 = no better than always guessing the average, negative = worse than "
    "that). **Out-of-fold (OOF)** = every prediction is scored on a scenario "
    "the model did NOT train on, so the scores don't flatter the model. "
    "A **conformal interval** = the ± uncertainty band around a prediction; "
    "§R3 checks those bands are honest."
)


# ---------------------------------------------------------------------------
# Per-section explainer text. Each entry has three parts:
#   plain    — the one question this chart answers
#   read     — what the axes / bars / dots / columns mean
#   look_for — guidance on interpreting it
# Section IDs match :func:`bokeh_explainer_div` / :func:`md_explainer` keys.
# ---------------------------------------------------------------------------

EXPLAINERS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------
    # Sections §1 – §7 — the existing "Evaluation results" diagnostics.
    # ------------------------------------------------------------------
    "s1_leaderboard": {
        "plain": (
            "Ranks the prediction methods best-to-worst on two target sets: "
            "system-wide totals (Overall) and per-region detail (Regional)."
        ),
        "read": (
            "Each row is one method. 'Pooled R²' lumps all outputs into a "
            "single score and is dominated by the largest-dollar variables "
            "(cost, generation), so it looks very high — don't over-read it. "
            "'Outputs > 0.9' counts how many individual variables are "
            "predicted well, which is the fairer score. For the honest "
            "per-variable ranking with error bars, see §R0."
        ),
        "look_for": (
            "Look at 'Outputs > 0.9', not just Pooled R². If the top two "
            "methods differ by only a few thousandths, treat them as tied. "
            "Baselines (Mean / Ridge / Lasso) scoring far below the ML "
            "methods confirms the extra model complexity is worth it."
        ),
    },
    "s1_parity": {
        "plain": (
            "A visual predicted-vs-actual check, one panel per method."
        ),
        "read": (
            "Each dot is one prediction; the dashed line is 'perfect' "
            "(predicted = actual). The tighter the dots hug the line, the "
            "more accurate the method."
        ),
        "look_for": (
            "This view is dominated by the big-magnitude variables, so "
            "every good method looks tight here — use it as a sanity check, "
            "not the final verdict. Small variables are invisible at this "
            "scale; §2 and §R1 cover those."
        ),
    },
    "s2_percase": {
        "plain": (
            "How well the best method does on each of the 486 scenarios, "
            "hardest scenario first."
        ),
        "read": (
            "Each dot is one scenario (one combination of the six inputs). "
            "Outputs are put on a common scale first, so a small variable "
            "counts as much as total cost — this is the honest R² "
            "(~0.75–0.9), not the inflated pooled number. Dots are sorted "
            "low-to-high, so the leftmost are the scenarios this model "
            "finds hardest."
        ),
        "look_for": (
            "A high flat plateau with only a few dots dropping off on the "
            "left = the model is reliable across most of the design space "
            "and struggles only in a few extreme corners. Hover a dot to "
            "see which input combination it is."
        ),
    },
    "s3_bias": {
        "plain": (
            "Is accuracy even across the four output catalogs (Capacity, "
            "Generation, System cost, Transmission), and on the Regional "
            "layer, across regions?"
        ),
        "read": (
            "One small panel per catalog. Each bar is one item inside that "
            "catalog (a tech for capacity / generation, a cost component "
            "for system cost, a line for transmission), with bar height = "
            "<b>median</b> R². Items are sorted worst-on-the-left within "
            "each panel. Near-constant outputs (deployed in fewer than "
            "~5% of cases, e.g. nuclear) are marked or excluded because "
            "their R² is unstable by definition. The region panel only "
            "fills in when you switch the Layer selector to Regional — "
            "the Overall layer has no per-region decomposition."
        ),
        "look_for": (
            "Within a panel: a long tail of low bars on the left tells "
            "you which items inside that catalog the surrogate struggles "
            "with. Across panels: a panel that is uniformly lower than "
            "the others is a catalog-wide weakness, not an item-specific "
            "one. Median (rather than mean) shields the chart from a few "
            "near-constant items skewing the picture."
        ),
    },
    "s4_percatalog": {
        "plain": (
            "Which TYPES of output are predicted best — capacity, "
            "generation, cost, or transmission — across the top-N methods?"
        ),
        "read": (
            "Bars are grouped by output type and compare the top-N methods "
            "(default N = 6, configurable; ranked by the honest §R0 mean "
            "R²). Taller = better median R² for that type. Both layers "
            "are shown side by side so you can see where per-region "
            "detail costs accuracy."
        ),
        "look_for": (
            "Big height differences between types mean a method is strong "
            "on some kinds of variable and weak on others. Compare the "
            "same type across the Overall vs Regional groups to see where "
            "added detail hurts. If the top-N converge on a type, that "
            "type is well-modelled by every reasonable method."
        ),
    },
    "s5_crosslayer": {
        "plain": (
            "What accuracy do we give up by going from system-wide totals "
            "to per-region detail, across the top-N methods?"
        ),
        "read": (
            "Each dot is one output. Columns = top-N methods × two layers "
            "(Overall, Regional). The thick black bar is the <b>median</b> "
            "of each column. Default N = 6, configurable; ranking uses the "
            "honest §R0 metric (per-output R² with bootstrap CIs), NOT "
            "§1's pooled score."
        ),
        "look_for": (
            "Compare the two columns for the same method. A big median "
            "drop plus a wider spread on the Regional side means: trust "
            "the system totals, but treat per-region predictions cautiously."
        ),
    },
    "s6_active": {
        "plain": (
            "If running ReEDS is expensive, can we choose training "
            "scenarios cleverly so we need fewer of them?"
        ),
        "read": (
            "X-axis = how many scenarios the model was trained on. The "
            "two lines pick the next scenario either by 'where the model "
            "is least sure' (uncertainty) or at random. A higher line = "
            "better accuracy for the same number of expensive runs."
        ),
        "look_for": (
            "If the uncertainty line sits above random, smart selection "
            "is paying off. This is measured on a held-out test set, so "
            "don't compare these R² values directly to the out-of-fold "
            "numbers elsewhere — read the gap between the two lines."
        ),
    },
    "s7_table": {
        "plain": (
            "The full table of numbers behind every chart — one row per "
            "variable."
        ),
        "read": (
            "R² (higher = better). RMSE / MAE are raw errors in each "
            "variable's own units, so they are NOT comparable between rows. "
            "NRMSE rescales error by the variable's range, so it IS "
            "comparable (lower = better). Click any column header to sort."
        ),
        "look_for": (
            "Use this to look up any single variable. Sort by NRMSE to "
            "find the consistently hardest ones."
        ),
    },
    # ------------------------------------------------------------------
    # Research-grade diagnostics §R0 – §R8 (from surrogate_eval.py).
    # ------------------------------------------------------------------
    "r0_ranking": {
        "plain": (
            "The honest model ranking, with error bars, so you can tell "
            "whether 'method A beats B' is real or just luck."
        ),
        "read": (
            "For each model: the average R² across scenarios, plus a 95% "
            "range (CI) found by resampling the 486 scenarios 200 times. "
            "'point' is the single best estimate; the CI shows how much "
            "it could wobble."
        ),
        "look_for": (
            "If two models' CIs overlap heavily, the difference between "
            "them isn't meaningful — call them tied. This is the table "
            "to cite in a paper, in preference to §1's pooled R²."
        ),
    },
    "r1_grouped": {
        "plain": (
            "Accuracy broken down by output category (capacity / "
            "generation / transmission / cost) and by technology, plus "
            "extra diagnostics beyond plain R²."
        ),
        "read": (
            "The new columns in plain terms — signed_bias / norm_bias: "
            "does the model consistently over- or under-shoot? (near 0 = "
            "unbiased). spearman: does it get the RANKING of scenarios "
            "right even when exact numbers are off? (near 1 = yes). "
            "std_ratio: does it preserve how much a variable swings "
            "across scenarios, or flatten it? (below 1 = slightly "
            "flattened, a common surrogate tendency). "
            "n_excluded_mostly_zero: how many near-constant variables "
            "were dropped from the average."
        ),
        "look_for": (
            "When the mean R² is much lower than the median, most "
            "variables are fine and a few bad ones are dragging the "
            "average down — read the median for the typical case. Bias "
            "near zero and spearman near one are both good signs."
        ),
    },
    "r3_calibration": {
        "plain": (
            "When a model says it's '90% confident,' is it actually right "
            "about 90% of the time? This is what validates the uncertainty "
            "bands on the Predict tab."
        ),
        "read": (
            "The curve plots promised coverage (x-axis) against actual "
            "coverage (y-axis); the straight diagonal is perfect. Points "
            "ABOVE the line mean the model is being cautious — real "
            "coverage higher than promised, the safe direction. "
            "'Sharpness' = how wide the bands are as a fraction of the "
            "variable's range (smaller = more useful)."
        ),
        "look_for": (
            "Points hugging the diagonal (or just above it) with small "
            "sharpness = trustworthy, tight intervals. Points far BELOW "
            "the line would mean the model is overconfident — a red flag."
        ),
    },
    "r5_headline": {
        "plain": (
            "The four numbers people actually care about — total system "
            "cost, total capacity, total generation, total transmission — "
            "each with a 90% uncertainty band."
        ),
        "read": (
            "r2 = how well the scenario-to-scenario variation is "
            "captured. conformal_relative_width = the ± band as a "
            "fraction of the variable's range, the practical 'how tight "
            "is it.' These measure different things: a high R² can still "
            "come with a fairly wide band."
        ),
        "look_for": (
            "Read both columns together. When you quote a surrogate "
            "prediction (e.g. a total cost), quote it WITH its ± band, "
            "not as a single number."
        ),
    },
    "r6_difficulty": {
        "plain": (
            "For every variable, is it hard because NO model can predict "
            "it (the variable is the problem) or because only SOME models "
            "fail (a model-choice problem)?"
        ),
        "read": (
            "intrinsic_hard = true → no model clears R²=0.5 → the "
            "variable barely varies or is near zero, so switching models "
            "won't help. model_specific_hard = true → at least one model "
            "is great and another is terrible → here switching models "
            "WOULD help. Sorted hardest-first."
        ),
        "look_for": (
            "If the hard variables are almost all 'intrinsic,' that's "
            "reassuring: the model choice is fine and the low scores "
            "come from genuinely flat variables (e.g. nuclear, "
            "early-stage hydrogen). The 'model_specific' rows are the "
            "ones worth acting on."
        ),
    },
    "r8_clipping": {
        "plain": (
            "Does forcing physically-impossible predictions (negative "
            "capacity, etc.) up to zero actually help accuracy?"
        ),
        "read": (
            "mean_delta_r2 > 0 = clipping is a net improvement. "
            "n_outputs_clipping_hurts = how many variables it makes "
            "slightly worse."
        ),
        "look_for": (
            "If 'hurts' is zero, clipping is free safety. It usually "
            "helps the linear models and gradient boosting most (they "
            "can predict negatives), while tree models barely need it. "
            "This is the check that justifies the clipping built into "
            "the prediction pipeline."
        ),
    },
    "bias_design": {
        "plain": (
            "Does the model fail specifically when one input setting is "
            "high or low — e.g. always under-predicting under high demand?"
        ),
        "read": (
            "For each of the six input knobs there's a box of prediction "
            "errors at each level (0/1/2). A box centered on zero means "
            "no systematic error at that level."
        ),
        "look_for": (
            "If every box sits centered near zero, the model has no "
            "built-in bias along any single input — the hard scenarios "
            "are scattered, not aligned to one setting. Boxes that drift "
            "consistently above or below zero as a level changes would "
            "flag a systematic problem."
        ),
    },
    # ------------------------------------------------------------------
    # Extra REPORT.md headings without a direct dashboard equivalent.
    # ------------------------------------------------------------------
    "r2_bias_diagnostics": {
        "plain": (
            "Three bias views per model: residual-vs-prediction (shape of "
            "errors), residual-vs-design-knob (where the systematic "
            "failures are), and Q-Q vs a normal distribution (do residuals "
            "behave well enough for the conformal band math)."
        ),
        "read": (
            "Look at each PNG under figs/. residvspred plots flag "
            "heteroscedasticity (errors growing with magnitude); byDesign "
            "boxplots align errors against the six input settings; the "
            "Q-Q plot tracks how close the standardised residuals are to "
            "a straight line (a normal distribution)."
        ),
        "look_for": (
            "A clean residvspred plot looks like an even cloud around "
            "zero. A clean byDesign plot has every box centered on zero. "
            "A clean Q-Q plot follows the diagonal in the middle but is "
            "allowed to peel off in the tails — physical models often "
            "have heavier tails than a true normal."
        ),
    },
    "r4_regional_vs_overall": {
        "plain": (
            "How much accuracy do you give up moving from system totals "
            "(Overall, ~86 outputs) to per-region detail (Regional, ~382 "
            "outputs)?"
        ),
        "read": (
            "Run both layers. The bootstrap CIs in §R0 / §0 of each "
            "report quantify the gap; the per-region heatmap (regional "
            "layer only) shows which BAs are predicted reliably vs "
            "poorly."
        ),
        "look_for": (
            "A modest median R² drop with a few BAs much worse than the "
            "rest is normal. Look for spatially-correlated weak spots "
            "(neighbouring BAs all bad) — that hints at a missing "
            "feature (e.g. transmission topology, weather pattern)."
        ),
    },
    "r5_distributional": {
        "plain": (
            "Beyond R², does the surrogate also reproduce the *shape* of "
            "each output's distribution across scenarios?"
        ),
        "read": (
            "distribution_fidelity_<m>.csv: Spearman (rank agreement), "
            "KS (distribution-shape distance), std_ratio (does the "
            "surrogate flatten variability). build_classification_<m>.csv: "
            "for cap_* outputs, does the surrogate get whether a tech is "
            "deployed at all (binary True/False), even if its magnitude "
            "is off?"
        ),
        "look_for": (
            "Spearman near 1 means even when exact numbers are off the "
            "surrogate ranks scenarios correctly — usually enough for "
            "decision support. std_ratio < 1 is the typical 'regression "
            "to the mean' tendency; below 0.7 is a red flag."
        ),
    },
    "r6_worst_cases": {
        "plain": (
            "Which scenarios and which outputs are the hardest, so you "
            "know where to look first when something looks wrong?"
        ),
        "read": (
            "per_case_error_ranking.csv ranks the 486 scenarios by total "
            "normalised |residual|. per_output_difficulty.csv ranks "
            "outputs by min/max R² across models, flagging "
            "intrinsic_hard (all models < 0.5) vs model_specific_hard "
            "(best > 0.9, worst < 0)."
        ),
        "look_for": (
            "If the worst scenarios cluster at one input corner (e.g. "
            "Hi demand, Lo gas), retraining with extra runs at that "
            "corner is the first lever. If the hard outputs are mostly "
            "intrinsic, the model is fine — those variables just don't "
            "vary much."
        ),
    },
    "r7_robustness": {
        "plain": (
            "Is the model leaderboard robust to which 486 scenarios "
            "happened to be drawn, or could a slightly different sample "
            "have flipped the ranking?"
        ),
        "read": (
            "We resample the 486 OOF cases 200 times and recompute each "
            "model's mean R². The CI is the 95% range over those "
            "resamples. Per-output R² is winsorised at -1 first so a "
            "single near-constant output can't blow up the average."
        ),
        "look_for": (
            "Tight CIs that don't overlap = the ranking is real. "
            "Heavily-overlapping CIs = the top methods are tied to "
            "within sampling noise; pick on secondary criteria "
            "(speed, interpretability)."
        ),
    },
    "r8_correctness": {
        "plain": (
            "Two correctness checks the deployed predict() pipeline "
            "depends on: clipping physical bounds, and the difference "
            "between within-grid interpolation and outside-grid "
            "extrapolation."
        ),
        "read": (
            "8a Clipping: clipping_delta_<m>.csv lists the per-output R² "
            "delta from forcing impossible values (negative cap, etc.) "
            "up to physical bounds. 8b Extrapolation: structured_cv "
            "(opt-in via --structured_cv or --extrapolation) holds out "
            "one level of one X dimension at a time and measures held-out "
            "R² — the honest extrapolation diagnostic."
        ),
        "look_for": (
            "8a: net positive mean_delta_r2 = clipping is helping; if "
            "any output is hurt, that's a model-specific bug worth "
            "investigating. 8b: a big drop from in-grid to out-of-grid "
            "R² means the surrogate should not be queried beyond the "
            "original 486-case envelope."
        ),
    },
    # ------------------------------------------------------------------
    # Paper-readiness additions: extrapolation diagnostic, limitations,
    # by-catalog distributional fidelity summary.
    # ------------------------------------------------------------------
    "extrapolation": {
        "plain": (
            "Two flavours of accuracy. <b>Interpolation</b> = predict a "
            "setting we never ran but which sits inside the 486-case grid "
            "(filling a gap). <b>Extrapolation</b> = predict a setting at "
            "a level we never ran for some input. The standard out-of-fold "
            "score in §R0 measures interpolation; this section measures "
            "extrapolation."
        ),
        "read": (
            "For each design dimension we hold out ALL cases at one of its "
            "levels (leave-one-level-out, LOLO), retrain on the rest, and "
            "score the held-out level. The bar chart shows two bars per "
            "method: the in-grid OOF mean R² and the average LOLO mean R² "
            "across dimensions. The accompanying table breaks the LOLO "
            "score down by dimension and flags which dimension is hardest "
            "to extrapolate along (largest R² drop)."
        ),
        "look_for": (
            "Small drop from OOF to LOLO = the surrogate generalises beyond "
            "the trained levels. Large drop = the surrogate has memorised "
            "levels and should not be queried at unseen settings of the "
            "hardest dimension. The surrogate is <i>validated</i> for "
            "interpolation and only <i>tested</i> for extrapolation."
        ),
    },
    "limitations": {
        "plain": (
            "What this surrogate is and is not validated for, in one place."
        ),
        "read": (
            "Three threads matter: (a) the metric we report from §R0 is "
            "<b>within-grid interpolation</b> accuracy, not extrapolation; "
            "(b) Pooled R² in §1 is inflated by high-magnitude outputs and "
            "is shown for context only; (c) intervals are calibrated "
            "split-conformal and assume the deployed input distribution "
            "matches the 486-case envelope."
        ),
        "look_for": (
            "For paper claims: cite §R0 mean / median R² with the bootstrap "
            "CI and, if you ran extrapolation, the §8b LOLO drop. Avoid "
            "quoting Pooled R² or unconditional intervals at settings "
            "outside the trained envelope."
        ),
    },
    "s5_distfidelity": {
        "plain": (
            "Does the surrogate preserve scenario-to-scenario STRUCTURE, "
            "not just hit average values?"
        ),
        "read": (
            "Per-output: <b>std_ratio</b> = std(predicted) / std(actual) — "
            "below 1.0 means the surrogate is regressing toward the mean "
            "(compressing variation). <b>Spearman</b> = rank correlation — "
            "how well the surrogate's <i>ordering</i> of scenarios matches "
            "the truth. The summary panel reports each catalog's median "
            "std_ratio and Spearman."
        ),
        "look_for": (
            "std_ratio close to 1 and Spearman close to 1 = the surrogate "
            "reproduces both magnitudes and ordering. std_ratio < 0.7 = "
            "meaningful compression, especially dangerous for "
            "sensitivity-style downstream analyses; act on it before "
            "trusting per-scenario rankings."
        ),
    },
}


# ---------------------------------------------------------------------------
# Bokeh helpers — return Div widgets ready to drop into a layout column.
# ---------------------------------------------------------------------------

_BOKEH_CALLOUT_STYLE = (
    "background:#f4f8fc;border-left:4px solid #1f77b4;"
    "padding:8px 12px;margin:6px 0 6px 0;border-radius:3px;"
    "font-size:13px;line-height:1.45;color:#222"
)
_BOKEH_INTRO_STYLE = (
    "background:#fff8e1;border-left:4px solid #f0a050;"
    "padding:10px 14px;margin:6px 0 12px 0;border-radius:3px;"
    "font-size:13px;line-height:1.5;color:#222"
)


def _format_bokeh_explainer_html(parts: Mapping[str, str]) -> str:
    """Render the three-part explainer as HTML for a Bokeh ``Div``."""
    return (
        f"<div style=\"{_BOKEH_CALLOUT_STYLE}\">"
        f"<div style='margin-bottom:4px'><b>📖 In plain words.</b> "
        f"{parts['plain']}</div>"
        f"<div style='margin-bottom:4px'><b>🔍 How to read it.</b> "
        f"{parts['read']}</div>"
        f"<div><b>👀 What to look for.</b> "
        f"{parts['look_for']}</div>"
        f"</div>"
    )


def bokeh_explainer_div(key: str):
    """Return a ``bokeh.models.Div`` styled callout for the given section.

    Importing :mod:`bokeh` lazily so this module is cheap to import in
    non-bokeh contexts (e.g. the eval CLI used by ``surrogate_eval.py``).
    """
    from bokeh.models import Div  # local import on purpose

    if key not in EXPLAINERS:
        return Div(text=f"<i>(missing explainer: {key})</i>")
    html = _format_bokeh_explainer_html(EXPLAINERS[key])
    return Div(text=html, sizing_mode="stretch_width")


def bokeh_intro_div():
    """Return a ``bokeh.models.Div`` rendering :data:`INTRO_BODY`."""
    from bokeh.models import Div  # local import on purpose

    # Split INTRO_BODY paragraphs (markdown blank lines) into <p> tags so
    # the bokeh Div doesn't render a wall of text. Bold markers handled
    # via a tiny inline replace so we don't pull in a markdown lib.
    paragraphs = [p.strip() for p in INTRO_BODY.split("\n\n") if p.strip()]
    html_paras = []
    for p in paragraphs:
        # Convert **bold** runs to <b>...</b>. Simple two-pass replace; the
        # intro never contains nested or unbalanced markers.
        out = []
        in_bold = False
        i = 0
        while i < len(p):
            if p[i:i + 2] == "**":
                out.append("</b>" if in_bold else "<b>")
                in_bold = not in_bold
                i += 2
            else:
                out.append(p[i])
                i += 1
        html_paras.append(f"<p style='margin:4px 0'>{''.join(out)}</p>")
    body = "\n".join(html_paras)
    text = f"<div style=\"{_BOKEH_INTRO_STYLE}\">{body}</div>"
    return Div(text=text, sizing_mode="stretch_width")


# ---------------------------------------------------------------------------
# Markdown helpers — string output ready to .append() onto a md list.
# ---------------------------------------------------------------------------

def md_explainer(key: str) -> str:
    """Return a markdown blockquote rendering the three-part explainer."""
    if key not in EXPLAINERS:
        return f"> *(missing explainer: {key})*\n"
    parts = EXPLAINERS[key]
    return (
        f"> 📖 **In plain words.** {parts['plain']}\n>\n"
        f"> 🔍 **How to read it.** {parts['read']}\n>\n"
        f"> 👀 **What to look for.** {parts['look_for']}\n"
    )


def md_intro() -> str:
    """Return :data:`INTRO_BODY` as a markdown blockquote."""
    quoted = "\n".join(f"> {line}" if line else ">" for line in INTRO_BODY.splitlines())
    return quoted + "\n"


# ---------------------------------------------------------------------------
# Optional auto-readouts. These are the ONLY data-driven sentences and are
# clearly labelled "Current run:" so the static caption above them stays
# trustworthy across re-runs.
# ---------------------------------------------------------------------------

def auto_readout_r0(bootstrap_df) -> str | None:
    """Build a one-sentence summary of the §R0 leaderboard for the current run.

    Expects the bootstrap dataframe written by ``surrogate_eval.py`` with
    columns ``model``, ``r2_mean_boot_mean``, and the 95% bootstrap CI columns
    ``r2_mean_ci_lo`` / ``r2_mean_ci_hi``. Returns ``None`` if the required
    columns aren't present.
    """
    needed = {"model", "r2_mean_boot_mean", "r2_mean_ci_lo", "r2_mean_ci_hi"}
    if bootstrap_df is None or not needed.issubset(bootstrap_df.columns):
        return None
    df = bootstrap_df.sort_values("r2_mean_boot_mean", ascending=False)
    if len(df) < 2:
        return None
    first = df.iloc[0]
    second = df.iloc[1]
    gap = float(first["r2_mean_boot_mean"]) - float(second["r2_mean_boot_mean"])
    overlap = (
        float(first["r2_mean_ci_lo"]) <= float(second["r2_mean_ci_hi"])
        and float(second["r2_mean_ci_lo"]) <= float(first["r2_mean_ci_hi"])
    )
    overlap_phrase = (
        "their confidence ranges overlap, so treat them as tied"
        if overlap
        else "their confidence ranges do not overlap, so the ordering is real"
    )
    return (
        f"_Current run:_ top method `{first['model']}` leads `{second['model']}` "
        f"by {gap:.3f} mean R²; {overlap_phrase}."
    )


def auto_readout_r5(headline_df) -> Iterable[str]:
    """Yield one short sentence per row of the §R5 headline-scalars table.

    Expects columns ``headline``, ``r2``, and ``conformal_relative_width``
    (matches what ``surrogate_eval.py`` writes). Yields nothing if those
    columns aren't present.
    """
    needed = {"headline", "r2", "conformal_relative_width"}
    if headline_df is None or not needed.issubset(headline_df.columns):
        return
    for _, row in headline_df.iterrows():
        try:
            r2 = float(row["r2"])
            rel = float(row["conformal_relative_width"])
        except (TypeError, ValueError):
            continue
        yield (
            f"_Current run:_ **{row['headline']}** "
            f"R²={r2:.2f}, ±{rel:.0%} band."
        )


def auto_readout_extrapolation(extrap_df) -> str | None:
    """One-sentence summary of §8b LOLO results for the current run.

    Expects the cross-model summary table written by ``surrogate_eval.py``
    with columns ``model``, ``oof_r2_mean``, ``lolo_r2_mean``,
    ``hardest_dim``, ``hardest_dim_drop``. Returns ``None`` if missing or
    empty.
    """
    needed = {"model", "oof_r2_mean", "lolo_r2_mean",
              "hardest_dim", "hardest_dim_drop"}
    if extrap_df is None or not needed.issubset(extrap_df.columns):
        return None
    if len(extrap_df) == 0:
        return None
    df = extrap_df.copy().sort_values("oof_r2_mean", ascending=False)
    top = df.iloc[0]
    try:
        oof = float(top["oof_r2_mean"])
        lolo = float(top["lolo_r2_mean"])
        drop = float(top["hardest_dim_drop"])
    except (TypeError, ValueError):
        return None
    return (
        f"_Current run:_ best in-grid method `{top['model']}` scores "
        f"R²={oof:.2f} on interpolation but R²={lolo:.2f} on average "
        f"extrapolation; biggest single drop is along "
        f"`{top['hardest_dim']}` ({drop:.2f} R²)."
    )


__all__ = [
    "EXPLAINERS",
    "INTRO_BODY",
    "bokeh_explainer_div",
    "bokeh_intro_div",
    "md_explainer",
    "md_intro",
    "auto_readout_r0",
    "auto_readout_r5",
    "auto_readout_extrapolation",
]
