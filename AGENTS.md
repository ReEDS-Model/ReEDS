# AGENTS.md — Guidance for AI Coding Assistants

This file gives AI coding tools (Claude, ChatGPT, GitHub Copilot, Cursor, Codex,
etc.) the context and operating rules they need to make safe, high-quality
contributions to the ReEDS repository. Human contributors should also feel free
to read it.

If anything in this file conflicts with
[`docs/source/developer_best_practices.md`](docs/source/developer_best_practices.md)
or with explicit user instructions, the developer best practices document and
the user win.

**This file is meant to grow.** If you discover a recurring gotcha, a useful
workflow, a switch interaction that's easy to miss, or any other piece of
guidance that would have saved time on a previous task, it belongs here.
Humans may add it directly; AI tools should propose the addition to the
human rather than editing this file unprompted. Keep additions concise and
verify them against the current repo.

---

## 1. What ReEDS is (and why it matters for AI assistants)

ReEDS (Regional Energy Deployment System) is the National Laboratory of the
Rockies (NLR) long-term capacity-expansion and dispatch model for the U.S.
electricity system. It is:

- **Large.** Hundreds of input files, hundreds of switches in `cases.csv`, and
  many GAMS, Python, and Julia files that interact through a multi-stage
  pipeline.
- **Mixed-language.** GAMS (`*.gms`) defines the optimization model and
  requires a commercial license (CPLEX or compatible); Python 3.11 drives
  preprocessing, orchestration, and postprocessing; Julia 1.12.1
  (`reeds/resource_adequacy/reeds2pras/`) handles resource-adequacy stress-period analysis.
- **Production research software.** Results are used in published studies and
  by external stakeholders. Silent changes to defaults or to widely-used
  switches can invalidate analyses.

Small, local-looking changes can have non-obvious downstream effects
across switches, scenarios, and postprocessing scripts.

---

## 2. Core operating principles

### 2.0 The human drives; the AI assists
The human contributor decides what changes, approves the approach, and is
accountable for every line merged — they must be able to explain and defend
it in review. Optimize for the human's understanding, not for speed or
volume of output. A change the human doesn't understand is not finished.

- **Plan before editing.** For any non-trivial change, propose the approach,
  the files you expect to touch, the alternatives you considered, and the
  expected effect on the default case — then wait for approval. Changes to
  the model formulation (equations, the objective, sets that gate variable
  or equation generation) always need a plan first, however small.
- **Surface decisions; don't make them silently.** When you choose between
  reasonable options (where logic lives, how to handle an edge case, whether
  to add a switch), name the choice and the alternative you rejected.
- **Keep changes reviewable.** Split large work into steps the human can
  review one at a time, and pause after each logical step rather than
  producing one large diff. Don't generate more change at once than the
  human can review in one sitting.
- **Don't make problems disappear.** If a check, test, or run fails, do not
  loosen tolerances, skip or delete tests, wrap code in `try/except`, pass
  `-f`, or add special cases just to get it to pass. Report the failure and
  your diagnosis, and let the human decide.

### 2.1 Keep changes scoped to the task
- Make the change the task requires, plus whatever that change *makes
  necessary*: docs (§2.2), and `runfiles.csv` / `futurefiles.csv` /
  `cases.csv` entries (§2.3).
- Beyond that, no unprompted edits: no "while I'm here" refactors, renames,
  reformatting, or speculative abstractions. Don't add docstrings, comments,
  type hints, or error handling to code you did not otherwise need to touch.
- **If you notice something worth fixing outside the task, report it — don't
  fix it.** End your response with a short "noticed, not changed" list.
- Prefer the smallest patch that correctly accomplishes the request.
- Unrelated edits are expensive here: a cosmetic change to a `.gms` or
  preprocessing file can turn a change that needed no rerun into one that
  needs a full `USA_defaults` comparison (§2.3).
- Don't introduce new dependencies (Python, Julia, or otherwise) without
  explicit approval. Changes to [`environment.yml`](environment.yml) or
  [`Project.toml`](Project.toml) must be called out.

### 2.2 Keep documentation in sync with code
The repo treats documentation as part of the change, not an afterthought. When
your change touches model behavior, switches, inputs, or outputs, update the
relevant file(s) under [`docs/source/`](docs/source):

- [`docs/source/model_documentation.md`](docs/source/model_documentation.md) —
  high-level description of default model behavior. Use admonition blocks for
  developer-only details (switch names, parameter names, file paths in
  backticks).
- [`docs/source/user_guide.md`](docs/source/user_guide.md) — user/developer
  description of switches and input files.
- [`docs/source/faq.md`](docs/source/faq.md) — limitations, caveats, known
  issues.
- [`docs/source/postprocessing_tools.md`](docs/source/postprocessing_tools.md) —
  postprocessing scripts.
- Most `inputs/{subfolder}/` folders have a `README.md` (e.g.,
  [`inputs/sets/README.md`](inputs/sets/README.md),
  [`inputs/plant_characteristics/README.md`](inputs/plant_characteristics/README.md))
  — update it when you change files in that folder. Not every subfolder
  has one; check the target folder rather than assuming. Each README is
  aggregated automatically into [`docs/source/inputs.md`](docs/source/inputs.md)
  by [`docs/scripts/generate_inputs_markdown.py`](docs/scripts/generate_inputs_markdown.py)
  when the docs are built (`make html`); do not edit `inputs.md` by hand.
- [`docs/source/setup.md`](docs/source/setup.md) — installation/setup changes.

If you add or rename a switch, update `cases.csv` (description **and**
`Choices` columns) **and** `user_guide.md`. A value that does not match
`Choices` raises an error at launch, before the run starts. Case columns in
`cases_*.csv` are optional overlays — blank entries fall back to that file's
`Default Value`, then to `cases.csv` — so a new switch needs a row only in
`cases.csv`. If you add or rename an input file, register it as described
in §2.3 item 3 and update the relevant input-folder README.

Citations live in [`docs/source/references.bib`](docs/source/references.bib)
(Better BibTeX format, managed via the ReEDS Zotero library — see
`developer_best_practices.md` §"Adding Citations in the Documentation"). Do
not hand-edit `.bib` entries unless the user explicitly asks.

[`docs/sources.csv`](docs/sources.csv) is scoped to sourced files **outside**
`inputs/` (e.g., under `hourlize/`, `postprocessing/`, `preprocessing/`,
`reeds2pras/`, `tests/`) — update it directly when you change one of those
files.
Input-file documentation belongs in the per-folder READMEs above instead.

### 2.3 Avoid unintended consequences
ReEDS has many switches in [`cases.csv`](cases.csv) that gate large blocks of
behavior. A change that looks isolated in one `.gms` or `.py` file may
silently affect:

- Other scenarios in [`cases.csv`](cases.csv),
  [`cases_test.csv`](cases_test.csv), [`cases_standardscenarios.csv`](cases_standardscenarios.csv), etc.
- Files declared in [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv) (governs which inputs are
  copied into a run's `inputs_case/` directory and how they are aggregated /
  disaggregated).
- The objective function (`reeds/core/setup/d_objective.gms`) — inputs used here should
  also appear in [`tests/objective_function_params.yaml`](tests/objective_function_params.yaml)
  so [`reeds/input_processing/check_inputs.py`](reeds/input_processing/check_inputs.py) can
  validate them.
- Reported outputs declared in [`reeds/core/terminus/report_params.csv`](reeds/core/terminus/report_params.csv)
  and assembled in [`reeds/core/terminus/report.gms`](reeds/core/terminus/report.gms). Adding, removing,
  renaming, or changing the indices of a reported parameter touches both
  files plus any downstream postprocessing (`postprocessing/`,
  `compare_cases.py`, BokehPivot, R2X) that reads it. Index changes are the
  easiest to miss: [`reeds/core/solve/6_data_dump.gms`](reeds/core/solve/6_data_dump.gms)
  shares a symbol namespace with `report_params.csv`, and BokehPivot
  (`postprocessing/bokehpivot/reeds2.py`) and `hourlize/reeds_to_rev.py` read
  columns by position. Grep all of them before reindexing.
- The resource adequacy module (`reeds/resource_adequacy/`) — runs **between** solve
  years to compute capacity credit and curtailment that feed back into the
  next solve. It is not a postprocessing step; changes here can change
  results.
- Postprocessing reports that depend on parameter names, units, or
  CSV column headers.

Before handing a non-trivial change back to the human, mentally (and where
reasonable, actually) check:

1. **Switch coverage.** Does the change behave correctly for every documented
   value of every switch it touches? In particular: `GSw_Region`,
   `GSw_HourlyType`, `GSw_HourlyNumClusters`, `GSw_AnnualCap`, `GSw_H2`,
   `GSw_Canada`, `GSw_PRM_CapCredit`, `GSw_Storage`. If a switch defaults to
   off, document the assumption explicitly in the PR.
2. **Default case neutrality.** If the change is *not expected to alter
   results for the default case* (for example, a rename, a reformat, or new
   code that only runs when an off-by-default switch is turned on), say so
   explicitly so the reviewer knows that the comparison report should show
   no differences.
3. **`reeds/input_processing/runfiles.csv` consistency.** If you add, remove, or rename a CSV file
   that is read by GAMS, update `reeds/input_processing/runfiles.csv`. Pay attention to
   `aggfunc`/`disaggfunc`, `region_col`, `fix_cols`, `i_col`, `wide`,
   `header`, `key`, `post_copy`, `GAMStype`, `GAMSname`, and `required_if`
   columns. A wrong `required_if` expression silently breaks switch-gated
   runs (the file is not copied into `inputs_case/` and GAMS later fails
   loading it). Scalar parameters live in
   [`inputs/scalars.csv`](inputs/scalars.csv); add new scalars there rather
   than hard-coding values. New files that get copied to `inputs_case/`
   also need an entry in [`inputs/userinput/futurefiles.csv`](inputs/userinput/futurefiles.csv),
   which tells [`reeds/input_processing/forecast.py`](reeds/input_processing/forecast.py)
   how to project the file forward in time — forecast.py will print a
   loud warning if a file is missing from it.
4. **Units and dollar year.** Costs read into `b_inputs.gms` must already be
   in 2004$. Use `inputs/financials/deflator.csv` (do not hard-code
   conversions). Add unit suffixes to new column names
   (e.g., `capcost_usd.per.kw`).
5. **Tests.** Run `pytest` from the repo root. The suite in
   [`tests/`](tests) is a smoke test (input checks, h5 read sanity), not a
   model-correctness test. All CI workflows must pass before a PR merges.

The map of change → recommended testing:

- **Pure post-processing / cosmetic change:** confirm postprocessing still
  runs against an existing `runs/` output; no model rerun required.
- **Code change not expected to affect default-case results** (e.g., behind
  an off-by-default switch, a rename, or rounding below model tolerance):
  run the Pacific test case (`cases_test.csv`) and produce a comparison
  report.
- **Any change that affects default-case outputs** (even if the change is
  correct and intentional — e.g., a solver swap that produces a different
  but equally valid solution): run `USA_defaults` from `cases_test.csv` and
  produce a comparison report with `postprocessing/compare_cases.py`.
  `USA_defaults` is the primary analysis case; understanding how any change
  affects its outputs is required before opening a PR. Be able to explain
  changes in capacity, generation, transmission, bulk system price, system
  cost, and runtime.

AI tools generally cannot run these full scenarios themselves. **State
clearly which tier of testing the change requires** so the human contributor
can run it before opening a PR. To catch errors earlier, see
[§6 “Fast inner loop”](#6-fast-inner-loop-iterating-on-a-single-step-from-call_).

### 2.4 Ask the human when something is unclear
Stop and ask when:

- The intent of a switch, parameter, or set is ambiguous.
- The same value or behavior could plausibly be controlled in more than one
  place and you can't tell which is canonical.
- A change would alter default-case results, even slightly, and the user did
  not say that was the goal.
- You would need to add a dependency, change `environment.yml` /
  `Project.toml`, modify CI, or touch large data files.
- The fix appears to require modifying inputs hosted in
  [ReEDS_Input_Processing](https://github.com/ReEDS-Model/ReEDS_Input_Processing)
  or on Zenodo rather than (or in addition to) this repo.
- A request seems to conflict with the developer best practices document.

When asking, present 2–3 concrete options and your recommendation rather than
an open-ended question.

---

## 3. Repository map (the parts you'll touch most often)

| Path | Purpose |
| --- | --- |
| [`runreeds.py`](runreeds.py) | Top-level launcher; reads `cases_{suffix}.csv` and creates a `runs/{batch}_{case}/` directory per case. Interactive by default — see §7 for non-interactive flags. |
| [`cases.csv`](cases.csv), `cases_*.csv` | Switch definitions and scenario specifications. The first columns describe each switch; remaining columns are scenarios. |
| [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv) | Declares every input/output CSV the run pipeline knows about, including how to aggregate/disaggregate spatially and how it maps to GAMS. |
| [`inputs/scalars.csv`](inputs/scalars.csv) | Central registry of GAMS scalar parameters and their default values. |
| [`reeds/core/`](reeds/core) | All GAMS model code, organized into `setup/`, `solve/`, `solve_pcm/`, and `terminus/` subdirectories. |
| [`reeds/core/setup/b_inputs.gms`](reeds/core/setup/b_inputs.gms) | Loads inputs from `inputs_case/` into GAMS sets/parameters. |
| [`reeds/core/setup/a_createmodel.gms`](reeds/core/setup/a_createmodel.gms) | Entry point that `$include`s `b_inputs.gms`, `c_model.gms`, `d_objective.gms`, and `e_solveprep.gms` to compile the model. Re-run this line from `call_*` to surface compilation errors quickly without doing a solve. |
| [`reeds/core/setup/c_model.gms`](reeds/core/setup/c_model.gms), [`reeds/core/setup/d_objective.gms`](reeds/core/setup/d_objective.gms) | Variables, equations, and objective of the optimization model. |
| [`reeds/core/setup/e_solveprep.gms`](reeds/core/setup/e_solveprep.gms) | Pre-solve data preparation; also `$include`d by `a_createmodel.gms`. |
| [`reeds/core/solve/`](reeds/core/solve) | Sequential / intertemporal / window solve loop, orchestrated by `solve.py`. |
| [`reeds/core/solve_pcm/`](reeds/core/solve_pcm) | Production-cost (PCM) dispatch mode, launched by [`postprocessing/run_pcm.py`](postprocessing/run_pcm.py). |
| [`reeds/core/terminus/`](reeds/core/terminus) | Reporting (`report.gms`, `report_dump.py`, `report_params.csv`); see §2.3. |
| [`reeds/resource_adequacy/`](reeds/resource_adequacy) | Capacity credit and curtailment between solve years (see §2.3); includes `reeds2pras/` (Julia). |
| [`reeds/input_processing/`](reeds/input_processing) | Python preprocessing — load, hourly clustering, supply curves, financials, copying input files into `inputs_case/`, etc. |
| [`hourlize/`](hourlize) | Hourly load/resource preprocessing pipeline (often run upstream and committed as data). |
| [`postprocessing/`](postprocessing) | Reports, plots, comparison tools (`compare_cases.py`, BokehPivot, retail-rate module, R2X runner, etc.). |
| [`inputs/`](inputs) | All input data, organized by topic. |
| [`tests/`](tests) | Lightweight `pytest` suite (see §2.3 item 5). |
| [`reeds/`](reeds) | Importable Python package of shared utilities (`financials`, `inputs`, `io`, `spatial`, `techs`, `timeseries`, etc.) plus all core model code. New shared helpers belong here, not duplicated across scripts. |
| [`reeds/hpc/`](reeds/hpc) | HPC (SLURM) and AWS launch templates. HPC vs local execution paths can differ; verify behavior on the target environment. |

A typical run produces `runs/{batch}_{case}/` containing `inputs_case/`,
`g00files/` (GAMS work files), `lstfiles/`, `gdxfiles/`, and `outputs/`.

---

## 4. Coding conventions (summary — read `developer_best_practices.md` for the full set)

### Python
- Target Python 3.11; follow PEP 8.
- Use `os.path.join` for paths; do not change the working directory in
  preprocessing scripts; prefer absolute paths.
- Run `ruff check` (linter only — do **not** auto-format existing files).
- Files ≥10 MB should be `.h5`, not `.csv`.
- Column headers should use the ReEDS set names where practical (e.g., `r`,
  `i`, `h`, `t`, `v`).

### GAMS
- File prefix convention: numeric prefix then descriptive name (e.g.,
  [`reeds/core/solve/2_financials.gms`](reeds/core/solve/2_financials.gms),
  [`reeds/core/solve/3_solve_oneyear.gms`](reeds/core/solve/3_solve_oneyear.gms)).
  Files in `reeds/core/setup/` use a letter prefix
  (e.g., `a_createmodel.gms`, `b_inputs.gms`).
- Parameters: lowercase with underscores, noun first, units in declaration
  comment between `--…--` (e.g., `cap_out(i,r,t) "--MW-- capacity by region"`).
- Variables: ALL_CAPS, noun first.
- Equations: prefix `eq_`, lowercase with underscores.
- Switches: `GSw_UpperCamelCase` in `cases.csv`; numeric switches surface as
  `Sw_Foo` scalars inside GAMS. `0` = off, `1` = on.
- Index ordering: `(ortype, i, v, r, h, …, t)` with `t` always last.
- No inline `//` comments. No `$ontext/$offtext` except as file headers.
- Compile-time conditionals must use a `.tag` (e.g., `$ifthen.switch1
  Sw_One==A`).
- See `developer_best_practices.md` for equation formatting (sums on three
  lines, parameters left of variables, etc.).

### Comments
- Keep comments short — one line where practical.
- When editing a comment, rewrite it to describe current behavior, not the
  edit that produced it.
- Unless otherwise necessary, do not cross-reference other switches, equations,
  or files by name inside a comment.
- Don't restate in a description string what the symbol's own domain already
  implies

### Inputs
- Input CSVs read by `b_inputs.gms` should have the **same name** as the GAMS
  parameter that reads them.
- New CSVs written into `inputs_case/` must be registered in `runfiles.csv`
  and `futurefiles.csv` (§2.3 item 3).
- Add a comment in `reeds/core/setup/b_inputs.gms` noting the upstream script when a file is
  generated by preprocessing (e.g., `* Written by writecapdat.py`).
- Dollar year and unit suffixes: see §2.3 item 4.

---

## 5. How to be a good AI collaborator on this repo

A short checklist to apply to every non-trivial change:

1. **Search for switch interactions.** Grep for any `GSw_*` or `Sw_*` name
   that appears in the file you're editing. Note any switch-gated branches in
   your summary to the user.
2. **Update file registrations (§2.3 item 3) and docs (§2.2) in the same
   change**, not as a follow-up.
3. **Branch and PR hygiene.**
   - Start branches from `main`, not from another feature branch, unless
     the user names an integration branch to build on and target.
   - Keep PRs small and single-topic.
   - Make the PR **title** descriptive and complete — it is reused verbatim
     in the release-notes summary for each ReEDS version.
4. **Disclose AI usage — required.** The PR template has a section
   ("Did you use LLM tools (chatbot or copilot) in the preparation of this
   PR? If so, describe how") that must be filled in. The PR author is
   accountable for every change regardless of how it was generated (§2.0).
5. **Keep git and GitHub actions with the human.** Do not commit, push,
   open PRs or issues, or post comments or reviews on the repo (including
   via `gh` or `/code-review --comment`). Edit files in the working tree
   and report everything in the chat session for the human to act on.
6. **Never** force-push, rewrite published history, modify CI secrets, or
   run destructive `git` commands without explicit instruction.

---

## 6. Fast inner loop: iterating on a single step from `call_*`

A completed run directory (e.g., `runs/p1_Pacific/`) contains a
`call_{case}` script (`.bat` on Windows, `.sh` on macOS/Linux) with every
step of the pipeline as a standalone, fully-parameterized command — each
preprocessing script, the
GAMS `a_createmodel.gms` invocation, every solve year, resource adequacy,
the report, etc. You can re-run any individual step in isolation against the
inputs/outputs the prior steps already wrote into the run folder. This is
much faster than a full rerun and is often the right first check while
iterating on a single file.

### When to use it

| Scope of change | Right test |
| --- | --- |
| Single file, no new cross-step dependencies (e.g., one preprocessing script, `report.gms`, a postprocessing script) | Re-run that step from `call_*`, diff its outputs |
| Anything `$include`d by `a_createmodel.gms` (e.g., `b_inputs.gms`) | Re-run the `a_createmodel.gms` line — surfaces compile and parameter-load errors without a solve |
| Multiple files in the same pipeline stage | Re-run those steps in order, diff |
| Crosses pipeline stages (preprocessing ↔ GAMS, GAMS ↔ resource adequacy, GAMS ↔ report) | Full Pacific rerun + `compare_cases.py` — one step in isolation runs against stale state from the others |
| Interacts with feedback loops (resource adequacy → next solve year) | Full rerun; per-step testing says little about end-to-end behavior |
| Gated by a switch the existing run did not exercise | Full rerun of a case that does exercise it |

This complements the §2.3 testing tiers; it does not replace them.

### Prerequisites and how to ask for them

1. **A completed run must already exist.** Check `runs/` first. If it is
   empty, there is nothing to diff against and the fast inner loop cannot
   be used. Either ask the user to run the Pacific test case first (a
   single ~30-minute investment that pays off across many iterations) or
   fall back to the full-case tier.
2. **If multiple runs exist, ask which to use.** Different folders may come
   from different branches, scenarios, or vintages. Each run's
   `meta.csv` records the branch and commit it was built from — use that to
   confirm with the user, do not guess.
3. **Watch out for the frozen-copy gotcha.** When `runreeds.py` sets up a
   run, it copies the `reeds/` source tree into the run folder. The
   `call_*` script invokes those copies, e.g.:
   ```
   python <repo>/runs/p1_Pacific/reeds/input_processing/writecapdat.py ...
   ```
   If you edited the source file in the repo (e.g.,
   `reeds/input_processing/writecapdat.py`), the rerun will silently use
   the stale frozen copy and show **no diff**. Either:
   - Copy your edited source file into the run folder before invoking, or
   - Invoke the source path explicitly with the same arguments.
   The same applies to GAMS files (`reeds/core/setup/b_inputs.gms`,
   `reeds/core/setup/a_createmodel.gms`,
   `reeds/core/terminus/report.gms`, etc.).

### Diffing outputs

- For Python preprocessing steps, snapshot the relevant `inputs_case/`
  files before re-running, then diff the new versions with pandas
  (row counts, summary stats, max abs/relative differences, regions or
  techs where values changed). Use
  [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv)
  to identify which files a given script writes.
- For GAMS steps, the standard pattern for inspecting intermediate state
  is to add
  ```gams
  execute_unload "temp.gdx" param1, param2, set1;
  ```
  at the point of interest, re-run the step, and read `temp.gdx` from
  Python (e.g., `gdxpds`) to compare against an unmodified-baseline gdx.
  **Always remove these `execute_unload` debug statements before handing
  the change back** — they're easy to leave behind and add noise (and mild
  runtime cost) in production runs.
- For report / postprocessing steps, diff the resulting CSVs in
  `outputs/` (or the generated plots/pptx) against a baseline copy.

### What to report back to the user

- Which step you re-ran and the exact command (copied from `call_*`).
- Which output files changed, and a concise summary of the deltas.
- Whether the deltas are consistent with the intended change.
- An explicit reminder that this does not replace the §2.3 testing tier
  appropriate to the change.

---

## 7. Useful commands

```bash
# Activate environment (after one-time `conda env create -f environment.yml`)
conda activate reeds

# Lightweight smoke tests (not a model-correctness suite)
pytest

# Lint Python (linter only — do not auto-format existing files)
ruff check

# Build docs locally
cd docs && make html   # output at docs/build/html/index.html

# Run a test case. runreeds.py is INTERACTIVE by default; pass -b and -c
# (and optionally -s) for non-interactive use.
python runreeds.py                              # interactive prompts
python runreeds.py -b v20260101_dev -c test     # non-interactive, all cases in cases_test.csv
python runreeds.py -b v20260101_dev -c test -s Pacific   # single case
python runreeds.py -b v20260101_dev -c test -s Pacific -t   # dry run: check inputs/switches only
python runreeds.py -h                           # full flag list
# -f (--skip_checks) skips conda-env and switch-Choices validation; use only when told to.

# Download remote input files up front (optional)
python reeds/remote.py
```

---

## 8. Where to look when stuck

- Model docs and input READMEs: see the list in §2.2.
- Conventions and PR process: [`docs/source/developer_best_practices.md`](docs/source/developer_best_practices.md)
- PR checklist: [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)

When in doubt: ask the human, propose options, and prefer the smallest
correct change.
