from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from .algebra import ROWS, Row
from .compare_spec import EQUATIONS, GROUP_TITLES, HELPERS, INTRO, NOTATION, SYNTAX, SYNTAX_PATTERNS
from .port_registry import GROUPS
from .validate_slice import EQ_DIMS, VAR_DIMS

ROOT = Path(__file__).resolve().parents[2]
GAMS_FILES = ["reeds/core/setup/c_model.gms", "reeds/core/setup/d_objective.gms"]
PORT_FILES = {"prep": "reeds/open/prep.py", "build": "reeds/open/build_pyoframe.py", "algebra": "reeds/open/algebra.py"}
DERIVE_FILES = ["reeds/open/derive.py", "reeds/open/derive_capacity.py", "reeds/open/derive_costs.py",
                "reeds/open/derive_temporal.py", "reeds/open/derive_ops.py", "reeds/open/derive_case.py"]
MATHJAX = "https://cdn.jsdelivr.net/npm/mathjax@4.0.0/tex-mml-chtml.js"
HELPER_CALL = re.compile(r"(?<![\w.])(" + "|".join(re.escape(h) for h in sorted(HELPERS, key=len, reverse=True)) + r")\(")

DEF_START = re.compile(r"^(eq_[A-Za-z0-9_]+)\(")
DECL = re.compile(r'^\s*(eq_[A-Za-z0-9_]+)\(([^)]*)\)\s+"([^"]*)"')
VAR_DECL = re.compile(r'^\s+([A-Z][A-Za-z0-9_]*)\(([^)]*)\)\s+"([^"]*)"')


def read_lines(rel: str) -> list[str]:
    return (ROOT / rel).read_text(encoding="utf-8").split("\n")


def parse_gams() -> tuple[dict, dict, dict]:
    defs: dict[str, dict] = {}
    decls: dict[str, dict] = {}
    variables: dict[str, dict] = {}
    for rel in GAMS_FILES:
        lines = read_lines(rel)
        in_vars = False
        for ln in lines:
            if ln.lower().startswith("positive variables") or ln.lower().startswith("variables"):
                in_vars = True
            elif ln.upper().startswith("EQUATION"):
                in_vars = False
            m = DECL.match(ln)
            if m:
                decls[m.group(1).lower()] = {"name": m.group(1), "dims": m.group(2), "desc": m.group(3)}
            m = VAR_DECL.match(ln)
            if m and in_vars:
                variables[m.group(1)] = {"dims": m.group(2), "desc": m.group(3)}
        i = 0
        while i < len(lines):
            m = DEF_START.match(lines[i])
            if not m or DECL.match(lines[i]):
                i += 1
                continue
            j = i
            while True:
                s = lines[j].rstrip()
                if not s.startswith("*") and s.endswith(";"):
                    break
                j += 1
            defs[m.group(1).lower()] = {"name": m.group(1), "file": rel, "line": i + 1, "text": "\n".join(lines[i:j + 1])}
            i = j + 1
    return defs, decls, variables


def statement_end(lines: list[str], start: int) -> int:
    depth = 0
    j = start
    while j < len(lines):
        for ch in lines[j]:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
        if depth <= 0 and not lines[j].rstrip().endswith(("\\", ",")):
            return j
        j += 1
    raise ValueError(f"unterminated statement from line {start + 1}")


def function_end(lines: list[str], start: int) -> int:
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = statement_end(lines, start)
    j = end + 1
    while j < len(lines):
        ln = lines[j]
        if ln.strip() and len(ln) - len(ln.lstrip()) <= indent:
            break
        if ln.strip():
            end = j
        j += 1
    return end


def entry_end(lines: list[str], start: int) -> int:
    depth = 0
    for j in range(start, len(lines)):
        depth += lines[j].count("(") - lines[j].count(")")
        if depth <= 0:
            return j
    raise ValueError(f"unbalanced parentheses from line {start + 1}")


def excerpt(rel: str, start_anchor: str, end_anchor: str | None = None, occurrence: int = 1, entry: bool = False) -> tuple[int, str]:
    lines = read_lines(rel)
    hits = [i for i, ln in enumerate(lines) if start_anchor in ln]
    if len(hits) < occurrence:
        raise KeyError(f"{rel}: anchor {start_anchor!r} occurrence {occurrence} not found ({len(hits)} hits)")
    start = hits[occurrence - 1]
    if end_anchor is None and entry:
        end = entry_end(lines, start)
    elif end_anchor is None and lines[start].lstrip().startswith("def "):
        end = function_end(lines, start)
    elif end_anchor is None:
        end = statement_end(lines, start)
    else:
        ends = [i for i, ln in enumerate(lines) if end_anchor in ln and i >= start]
        if not ends:
            raise KeyError(f"{rel}: end anchor {end_anchor!r} not found after line {start + 1}")
        end = statement_end(lines, ends[0])
    block = lines[start:end + 1]
    if len(block) > 160:
        raise ValueError(f"{rel}: excerpt from {start_anchor!r} to {end_anchor!r} spans {len(block)} lines; the anchors are probably wrong")
    indent =min(len(ln) - len(ln.lstrip()) for ln in block if ln.strip())
    return start + 1, "\n".join(ln[indent:] if ln.strip() else "" for ln in block)


BUILDER_OF: dict[str, str] = {}


def case_label(report_path: str) -> str:
    parts = report_path.split("/")
    k = next(i for i, x in enumerate(parts) if x.startswith("validate_"))
    label = parts[k - 2]
    if report_path in BUILDER_OF:
        label += f" ({BUILDER_OF[report_path]})"
    return label


def load_reports(paths: list[str]) -> dict[str, dict[str, int]]:
    out = {}
    for p in paths:
        rep = json.loads((ROOT / p).read_text(encoding="utf-8"))
        BUILDER_OF[p] = rep["builder"] if "builder" in rep else "pyoframe"
        out[p] = {"rows": {k.lower(): v for k, v in rep["size"]["constraints"].items()}, "cols": rep["size"]["variables"],
                  "gate1": rep["gate1_matrix"]["pass"], "gate2": rep["gate2_objective"]["pass"],
                  "gate3": rep["gate3_gams_primal"]["pass"], "gate4": rep["gate4_kkt"]["pass"]}
    return out


def status(name: str, group: str | None, reports: dict, guard_only: bool) -> tuple[str, dict[str, int]]:
    rows = {p: r["rows"].get(name, 0) for p, r in reports.items()}
    if name in ("eq_objfn_inv", "eq_objfn_op"):
        return "objective", rows
    if group is None or guard_only:
        return "not-ported", rows
    if any(v > 0 for v in rows.values()):
        return "validated", rows
    return "ported-empty", rows


def esc(s: str) -> str:
    return html.escape(s, quote=False)


SPACING = re.compile(r"^(\s|\\;|\\,|\\!|\\quad|\\qquad|\\ )*")
OPEN_SIZED = re.compile(r"\\(big|Big|bigg|Bigg)l?([(\[]|\\\{)")
CLOSE_SIZED = re.compile(r"\\(big|Big|bigg|Bigg)r?([)\]]|\\\})")
RELATION = re.compile(r"\\(geq|leq|ge|le)(?![A-Za-z])")
OPERATOR_END = re.compile(r"(\+|-|=|\\ge|\\le|\\geq|\\leq|\\cdot|\\times)$")


def strip_spacing(text: str) -> str:
    out = text.strip()
    while True:
        new = re.sub(r"(\\;|\\,|\\!|\\quad|\\qquad|\\ )$", "", out).strip()
        new = SPACING.sub("", new).strip()
        if new == out:
            return out
        out = new


def split_terms(math: str) -> list[str]:
    terms: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(math)

    def flush():
        text = strip_spacing("".join(buf))
        if text:
            terms.append(text)
        buf.clear()

    def at_term_start() -> bool:
        text = strip_spacing("".join(buf))
        return text == "" or bool(OPERATOR_END.search(text))

    while i < n:
        ch = math[i]
        m_open = OPEN_SIZED.match(math, i)
        m_close = CLOSE_SIZED.match(math, i)
        if m_open:
            depth += 1
            buf.append(m_open.group(0))
            i = m_open.end()
            continue
        if m_close:
            depth -= 1
            buf.append(m_close.group(0))
            i = m_close.end()
            continue
        if math.startswith("\\left", i) or math.startswith("\\right", i):
            raise ValueError("\\left/\\right fences are not supported by split_terms; use \\big( \\big)")
        if ch == "\\" and i + 1 < n and math[i + 1] in "{}":
            buf.append(math[i:i + 2])
            i += 2
            continue
        if ch == "\\" and i + 1 < n and math[i + 1] == "\\":
            if depth == 0:
                flush()
            else:
                buf.append("\\\\")
            i += 2
            continue
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        if depth < 0:
            return [math]
        if depth == 0:
            m_rel = RELATION.match(math, i)
            if ch in "+-" and not at_term_start():
                flush()
            elif ch in "=<>" and not at_term_start():
                flush()
            elif m_rel and not at_term_start():
                flush()
        buf.append(ch)
        i += 1
    flush()
    if depth != 0:
        return [math]
    return terms


def brace_end(text: str, start: int) -> int:
    if text[start] != "{":
        raise ValueError(f"expected '{{' at position {start} of {text[:60]!r}")
    depth = 0
    i = start
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in "{}":
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced braces in {text[:60]!r}")


def extract_underbraces(math: str) -> tuple[str, list[tuple[str, str]]]:
    defs: list[tuple[str, str]] = []
    out = math
    while "\\underbrace{" in out:
        start = out.index("\\underbrace{")
        body_start = start + len("\\underbrace")
        body_end = brace_end(out, body_start)
        rest = body_end + 1
        while rest < len(out) and out[rest].isspace():
            rest += 1
        if not out.startswith("_{", rest):
            raise ValueError(f"\\underbrace without a _{{label}} in {math[:60]!r}")
        label_end = brace_end(out, rest + 1)
        body = out[body_start + 1:body_end]
        label = out[rest + 2:label_end]
        defs.append((label, body))
        out = out[:start] + "{" + label + "}" + out[label_end + 1:]
    return out, defs


def term_spans(math: str) -> str:
    return "".join(f'<span class="term">\\(\\displaystyle {esc(t)}\\)</span>' for t in split_terms(math))


CONTINUATION = re.compile(r"\s*(\+|-|=|<|>|\\ge|\\le|\\geq|\\leq)")


def split_condition(math: str) -> tuple[str, str | None]:
    depth = 0
    i = 0
    while i < len(math):
        if math.startswith("\\{", i) or math.startswith("\\}", i):
            i += 2
            continue
        m_open = OPEN_SIZED.match(math, i)
        m_close = CLOSE_SIZED.match(math, i)
        if m_open:
            depth += 1
            i = m_open.end()
            continue
        if m_close:
            depth -= 1
            i = m_close.end()
            continue
        ch = math[i]
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        elif depth == 0 and math.startswith("\\qquad", i):
            rest = math[i + len("\\qquad"):]
            if not CONTINUATION.match(rest) and math[:i].strip():
                return math[:i], rest.strip()
        i += 1
    return math, None


def render_math(math: str) -> str:
    main, defs = extract_underbraces(math)
    main, cond = split_condition(main)
    cond_span = f'<span class="term cond"><span class="def-tag">rows</span>\\({esc(cond)}\\)</span>' if cond else ""
    parts = [f'<div class="math">{term_spans(main)}{cond_span}</div>']
    for label, body in defs:
        parts.append(f'<div class="math def"><span class="def-tag">where</span>{term_spans(label + " = " + body)}</div>')
    return "".join(parts)


def link_helpers(escaped: str) -> str:
    return HELPER_CALL.sub(lambda m: f'<a class="hl" href="#helper-{m.group(1)}">{m.group(1)}</a>(', escaped)


def code_block(title: str, text: str, lang: str) -> str:
    body = link_helpers(esc(text)) if lang == "python" else esc(text)
    return f'<div class="code"><div class="code-title">{esc(title)}</div><pre class="lang-{lang}">{body}</pre></div>'


def helpers_used(texts: list[str], listed: list[str]) -> list[str]:
    found = set(listed)
    for text in texts:
        found |= {m.group(1) for m in HELPER_CALL.finditer(text)}
    return [h for h in HELPERS if h in found]


def syntax_used(texts: list[str]) -> list[str]:
    joined = "\n".join(texts)
    return [label for pattern, label in SYNTAX_PATTERNS if re.search(pattern, joined)]


def render_terms(terms: list) -> str:
    if not terms:
        return ""
    rows = []
    for term in terms:
        gams_term, math_term, port, note = term
        rows.append(f"<tr><td><code>{esc(gams_term)}</code></td><td>\\({math_term}\\)</td>"
                    f"<td>{esc(port)}</td><td>{esc(note)}</td></tr>")
    head = "<tr><th>GAMS term</th><th>Mathematics</th><th>Port (coefficient table, variable)</th><th>Status / note</th></tr>"
    return f'<table class="terms">{head}{"".join(rows)}</table>'


ROWS_BY_KEY = {k.lower(): (k, v) for k, v in ROWS.items()}


def _index(dims) -> str:
    return "(" + ",".join(dims) + ")"


def render_linopy(key: str) -> str:
    if key not in ROWS_BY_KEY:
        return ""
    name, row = ROWS_BY_KEY[key]
    row_dims = list(EQ_DIMS[name]) if name in EQ_DIMS else []
    dim = f"{name}_idx"
    lines = []
    for k, term in enumerate(row.terms, 1):
        var_dims = list(VAR_DIMS[term.var]) if term.var in VAR_DIMS else []
        if term.rename:
            var_dims = [term.rename.get(d, d) for d in var_dims]
        if term.sum_by:
            out_dims = list(term.sum_by)
        else:
            out_dims = row_dims if row_dims else var_dims
        if term.post:
            out_dims = [term.post.get(d, d) for d in out_dims]
        action = (f"sum to {_index(term.sum_by)}" if term.sum_by else "rows = joined index")
        if term.post:
            action += f", then rename {esc(str(term.post))}"
        lines.append(f"<tr><td>{k}</td><td><code>K[{esc(term.coef)!s}]</code></td>"
                     f"<td><code>{esc(term.var)}{esc(_index(var_dims))}</code>"
                     + (f"<br><span class=\"meta\">index renamed {esc(str(term.rename))}</span>" if term.rename else "")
                     + f"</td><td><code>{esc(_index(var_dims))}</code></td><td>{esc(action)} → <code>{esc(_index(out_dims))}</code></td></tr>")
    rhs = (f"<code>rhs = −K[{esc(row.const)}]</code> joined onto the rows (0 where the constant table has no row)"
           if row.const else "<code>rhs = 0</code>")
    sense = "≥" if row.sense == ">=" else "="
    head = ("<tr><th>#</th><th>coefficient table</th><th>variable (index after rename)</th><th>joined on</th>"
            "<th>row index</th></tr>")
    return ('<div class="linopy"><div class="code-title">linopy  build_linopy._add_row</div>'
            f'<p class="meta">rows = union of the term row tuples'
            + (" and the rows of the constant table" if row.const else "")
            + f', sorted; one <code>LinearExpression</code> over <code>({esc(dim)}, _term)</code>, padded with label −1; '
            f'<code>add_constraints(expr, "{esc(row.sense)}", rhs, name="{esc(name)}")</code> — row {sense} rhs.</p>'
            f'<table class="terms">{head}{"".join(lines)}</table><p class="meta">{rhs}. Each (row, column) pair is summed before packing, '
            'zero coefficients are dropped, and the column label is the variable\'s position in its prep domain.</p></div>')


def render_equation(name: str, spec: dict, gdef: dict | None, gdecl: dict | None, st: str, rows: dict, groups_of: str | None) -> str:
    key = name.lower()
    title = gdef["name"] if gdef else name
    dims = gdecl["dims"] if gdecl else ""
    desc = gdecl["desc"] if gdecl else ""
    badge = {"validated": "validated", "ported-empty": "ported, no rows in either reference case",
             "not-ported": "not ported", "objective": "objective"}[st]
    rowtxt = " · ".join(f"{case_label(p)}: {n:,} rows" for p, n in rows.items())
    parts = [f'<section class="eq" id="{esc(key)}">',
             f'<h3><code>{esc(title)}({esc(dims)})</code> <span class="badge {st}">{badge}</span></h3>',
             f'<p class="desc">{esc(desc)}</p>',
             f'<p class="meta">group: {esc(groups_of or "none")} · {esc(rowtxt)}'
             + (f' · GAMS source: <code>{esc(gdef["file"])}:{gdef["line"]}</code>' if gdef else "") + "</p>"]
    if spec.get("summary"):
        parts.append(f'<p class="summary">{spec["summary"]}</p>')
    parts.append(render_math(spec["math"]))
    if spec.get("where"):
        parts.append('<div class="where"><b>Where</b><ul>' + "".join(f"<li>{w}</li>" for w in spec["where"]) + "</ul></div>")
    parts.append(render_terms(spec.get("terms", [])))
    if spec.get("dropped"):
        parts.append('<div class="dropped"><b>GAMS terms not in the port</b><ul>' + "".join(f"<li>{d}</li>" for d in spec["dropped"]) + "</ul></div>")
    left = code_block(f'GAMS  {gdef["file"]}:{gdef["line"]}', gdef["text"], "gams") if gdef else ""
    right = []
    texts = []
    for item in spec.get("prep", []):
        ln, text = excerpt(PORT_FILES["prep"], *item) if isinstance(item, tuple) else excerpt(PORT_FILES["prep"], item)
        right.append(code_block(f"prep.py:{ln}", text, "python"))
        texts.append(text)
    for item in spec.get("build", []):
        if isinstance(item, tuple):
            ln, text = excerpt(PORT_FILES["build"], *item)
            right.append(code_block(f"build_pyoframe.py:{ln}", text, "python"))
        else:
            ln, text = excerpt(PORT_FILES["algebra"], item, entry=True)
            right.append(code_block(f"algebra.py:{ln}", text, "python"))
        texts.append(text)
    for item in spec.get("derive", []):
        rel = item[0]
        ln, text = excerpt(rel, *item[1:])
        right.append(code_block(f"{Path(rel).name}:{ln}", text, "python"))
        texts.append(text)
    linopy_block = render_linopy(key)
    if linopy_block:
        right.append(linopy_block)
    used = helpers_used(texts, spec.get("helpers", []) + (["_term_entries", "_add_row"] if linopy_block else []))
    if used:
        right.append('<p class="helpers"><b>Helpers in this code:</b> '
                     + ", ".join(f'<a href="#helper-{h}"><code>{esc(h)}</code></a>' for h in used) + "</p>")
    ops = syntax_used(texts)
    if ops:
        right.append('<div class="syntax-used"><b>pyoframe and polars operations in this code</b> '
                     '(<a href="#syntax">syntax reference</a>)<ul>' + "".join(f"<li>{o}</li>" for o in ops) + "</ul></div>")
    if st == "not-ported" and spec.get("port_note"):
        right.append(f'<div class="port-note">{spec["port_note"]}</div>')
    parts.append(f'<div class="cols"><div class="col">{left}</div><div class="col">{"".join(right)}</div></div>')
    if spec.get("notes"):
        parts.append('<div class="notes"><b>Notes</b><ul>' + "".join(f"<li>{n}</li>" for n in spec["notes"]) + "</ul></div>")
    parts.append("</section>")
    return "\n".join(parts)


CSS = """
:root { --bg:#fff; --fg:#1b1b1b; --muted:#555; --line:#ddd; --code:#f6f7f9; --ok:#1a7f37; --warn:#9a6700; --no:#b42318; --obj:#4f46e5; }
body { font-family: Segoe UI, Helvetica, Arial, sans-serif; color: var(--fg); background: var(--bg); margin: 0; line-height: 1.45; }
.wrap { display: grid; grid-template-columns: 300px minmax(0, 1fr); min-height: 100vh; }
nav { border-right: 1px solid var(--line); padding: 16px; position: sticky; top: 0; height: 100vh; overflow-y: auto; font-size: 13px; }
nav a { display: block; color: var(--fg); text-decoration: none; padding: 1px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
nav .grp { margin-top: 10px; font-weight: 600; }
main { padding: 24px 32px; max-width: 1700px; min-width: 0; }
h1 { margin-top: 0; }
section.eq { border-top: 2px solid var(--line); padding-top: 12px; margin-top: 28px; }
.badge { font-size: 12px; padding: 2px 8px; border-radius: 10px; color: #fff; vertical-align: middle; font-weight: 500; }
.badge.validated { background: var(--ok); } .badge.ported-empty { background: var(--warn); } .badge.not-ported { background: var(--no); } .badge.objective { background: var(--obj); }
.desc { color: var(--muted); margin: 2px 0; } .meta { font-size: 13px; color: var(--muted); }
.math { padding: 8px 0 8px 1.5em; max-width: 100%; display: flex; flex-wrap: wrap; align-items: baseline; row-gap: 10px; column-gap: 0.45em; }
.math .term { max-width: 100%; overflow-x: auto; overflow-y: hidden; }
.math .term:first-child { margin-left: -1.5em; }
.math.def { padding-top: 0; font-size: 0.95em; }
.math .term.cond { flex-basis: 100%; margin-left: 0; font-size: 0.92em; }
.math .term.cond .def-tag { font-size: 12px; color: var(--muted); margin-right: 0.4em; }
.math.def .def-tag { font-size: 12px; color: var(--muted); margin-left: -1.5em; margin-right: 0.3em; }
.math.def .def-tag + .term { margin-left: 0; }
table.terms td:nth-child(2) { min-width: 11em; }
a.hl { color: inherit; text-decoration: underline dotted; }
.syntax-used { font-size: 12px; color: var(--muted); }
.syntax-used ul { margin: 2px 0 8px 18px; }
table.syntax { border-collapse: collapse; font-size: 13px; width: 100%; }
table.syntax th, table.syntax td { border: 1px solid var(--line); padding: 4px 8px; vertical-align: top; text-align: left; }
.cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
@media (max-width: 1200px) { .cols { grid-template-columns: minmax(0, 1fr); } .wrap { grid-template-columns: minmax(0, 1fr); } nav { position: static; height: auto; } }
pre { background: var(--code); border: 1px solid var(--line); padding: 10px; overflow-x: auto; font-size: 12px; line-height: 1.35; margin: 0 0 10px 0; white-space: pre; }
.code-title { font-size: 12px; color: var(--muted); font-family: Consolas, monospace; margin: 6px 0 2px; }
table.terms { border-collapse: collapse; font-size: 13px; margin: 10px 0; width: 100%; }
table.terms th, table.terms td { border: 1px solid var(--line); padding: 4px 8px; vertical-align: top; text-align: left; }
table.summary { border-collapse: collapse; font-size: 13px; display: block; overflow-x: auto; }
table.summary th, table.summary td { border: 1px solid var(--line); padding: 3px 8px; text-align: left; }
.where ul, .dropped ul, .notes ul { margin: 4px 0 8px 18px; }
.dropped { background: #fff8e6; border: 1px solid #f1d78a; padding: 6px 10px; border-radius: 4px; font-size: 13px; }
.port-note { background: #fde8e8; border: 1px solid #f3b4b4; padding: 6px 10px; border-radius: 4px; font-size: 13px; }
.notes, .where { font-size: 13px; }
code { font-family: Consolas, Menlo, monospace; font-size: 0.93em; }
.helpers { font-size: 12px; color: var(--muted); }
.linopy { border: 1px solid var(--line); border-radius: 4px; padding: 6px 10px; margin: 8px 0; background: #f3f8ff; }
.linopy table.terms { margin: 6px 0; }
"""


def build(out: Path, report_paths: list[str], partial: bool = False) -> None:
    defs, decls, variables = parse_gams()
    reports = load_reports(report_paths)
    group_of: dict[str, str] = {}
    for g, spec in GROUPS.items():
        for e in spec["equations"]:
            group_of[e.lower()] = g
    all_names = list(dict.fromkeys([*(decls[k]["name"] for k in decls), *(defs[k]["name"] for k in defs)]))
    all_keys = list(dict.fromkeys(n.lower() for n in all_names))
    missing_spec = [k for k in all_keys if k not in {s.lower() for s in EQUATIONS}]
    if missing_spec and not partial:
        raise KeyError(f"compare_spec.EQUATIONS lacks entries for: {missing_spec}")
    spec_by_key = {k.lower(): v for k, v in EQUATIONS.items()}
    for k in missing_spec:
        spec_by_key[k] = {"math": r"	ext{(specification not written yet)}"}
    extra = [k for k in spec_by_key if k not in all_keys]
    if extra:
        raise KeyError(f"compare_spec.EQUATIONS has entries without a GAMS equation: {extra}")

    ordered: list[tuple[str, str]] = []
    for g in GROUP_TITLES:
        if g == "unported":
            ordered += [("unported", k) for k in all_keys if k not in group_of and k not in ("eq_objfn_inv", "eq_objfn_op")]
        elif g == "objective":
            ordered += [("objective", "eq_objfn_inv"), ("objective", "eq_objfn_op")]
        else:
            ordered += [(g, e.lower()) for e in GROUPS[g]["equations"]]

    counts = {"validated": 0, "ported-empty": 0, "not-ported": 0, "objective": 0}
    sections, toc, summary_rows = [], [], []
    for g, key in ordered:
        gdef = defs.get(key)
        gdecl = decls.get(key)
        st, rows = status(key, group_of.get(key), reports, bool(spec_by_key[key].get("guard_only", False)))
        counts[st] += 1
        if g != (toc[-1][0] if toc else None):
            toc.append((g, None))
        toc.append((g, key))
        title = gdef["name"] if gdef else (gdecl["name"] if gdecl else key)
        summary_rows.append(f'<tr><td><a href="#{key}">{esc(title)}</a></td><td>{esc(gdecl["dims"] if gdecl else "")}</td>'
                            f'<td>{esc(group_of.get(key, "") if st != "objective" else "objective")}</td>'
                            f'<td class="{st}">{st}</td>' + "".join(f"<td>{n:,}</td>" for n in rows.values()) + "</tr>")
        sections.append(render_equation(key, spec_by_key[key], gdef, gdecl, st, rows, group_of.get(key)))

    helper_html = []
    for hname, (rel, start, end, text) in HELPERS.items():
        ln, code = excerpt(rel, start, end)
        helper_html.append(f'<section class="eq" id="helper-{hname}"><h3><code>{esc(hname)}</code> '
                           f'<span class="meta">{esc(rel)}</span></h3><p>{text}</p>'
                           + code_block(f"{Path(rel).name}:{ln}", code, "python") + "</section>")
    syntax_rows = "".join(f"<tr><td>{g}</td><td>{p}</td><td>{m}</td></tr>" for g, p, m in SYNTAX)
    syntax_html = ('<table class="syntax"><tr><th>GAMS</th><th>Port (polars / pyoframe)</th><th>Meaning</th></tr>'
                   + syntax_rows + "</table>")

    nav = []
    for g, key in toc:
        if key is None:
            nav.append(f'<div class="grp">{esc(GROUP_TITLES[g])}</div>')
        else:
            nav.append(f'<a href="#{key}">{esc(defs[key]["name"] if key in defs else key)}</a>')
    nav.insert(0, '<div class="grp">Reference</div><a href="#syntax">Syntax: GAMS to polars and pyoframe</a><a href="#helpers">Shared helpers</a>')
    nav.append('<div class="grp">Shared helpers</div>' + "".join(f'<a href="#helper-{h}">{esc(h)}</a>' for h in HELPERS))

    gates = "".join(f"<li><code>{esc(p)}</code>: gate 1 matrix {'PASS' if r['gate1'] else 'FAIL'}, gate 2 objective {'PASS' if r['gate2'] else 'FAIL'}, "
                    f"gate 3 GAMS primal {'PASS' if r['gate3'] else 'FAIL'}, gate 4 KKT {'PASS' if r['gate4'] else 'FAIL'}</li>" for p, r in reports.items())
    var_rows = "".join(f'<tr><td><code>{esc(v)}({esc(d["dims"])})</code></td><td>{esc(d["desc"])}</td>'
                       + "".join(f'<td>{r["cols"].get(v, 0):,}</td>' for r in reports.values()) + "</tr>" for v, d in variables.items())
    head_cols = "".join(f"<th>{esc(case_label(p))} rows</th>" for p in reports)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ReEDS constraint comparison (pyoframe and linopy)</title>
<script>window.MathJax = {{ tex: {{ inlineMath: [['\\\\(', '\\\\)']], displayMath: [['\\\\[', '\\\\]']], tags: 'none',
  macros: {{ V: ['\\\\mathrm{{#1}}', 1], P: ['\\\\mathit{{#1}}', 1], sw: ['[\\\\mathrm{{#1}}]', 1] }} }},
  output: {{ displayOverflow: 'linebreak', linebreaks: {{ inline: true, width: '100%', lineleading: 0.3 }} }},
  options: {{ skipHtmlTags: ['script','noscript','style','textarea','pre','code'] }} }};</script>
<script src="{MATHJAX}" async></script>
<style>{CSS}</style></head>
<body><div class="wrap"><nav>{"".join(nav)}</nav><main>
<h1>ReEDS GAMS to the Python port (pyoframe and linopy): per-constraint comparison</h1>
{INTRO}
<h2>Validation status</h2>
<p>Counts: {counts['validated']} validated with rows, {counts['ported-empty']} ported but with no rows in either reference case,
{counts['not-ported']} not ported, {counts['objective']} objective equations.</p>
<ul>{gates}</ul>
<h2>Notation</h2>{NOTATION}
<h2 id="syntax">Syntax: GAMS constructs and their polars / pyoframe / linopy form</h2>
<p>The port expresses GAMS sets and parameters as polars tables (index columns plus <code>value</code>) and GAMS conditions as joins.
The table below lists each idiom once; each equation section repeats the helpers and operations its code uses, and helper names in the code
excerpts link to their definitions under <a href="#helpers">Shared helpers</a>.</p>
{syntax_html}
<h2>Equation index</h2>
<table class="summary"><tr><th>Equation</th><th>GAMS index</th><th>Group</th><th>Status</th>{head_cols}</tr>{"".join(summary_rows)}</table>
<h2>Variables</h2>
<table class="summary"><tr><th>Variable</th><th>GAMS description</th>{"".join(f"<th>{esc(case_label(p))} columns</th>" for p in reports)}</tr>{var_rows}</table>
{"".join(sections)}
<h2 id="helpers">Shared helpers</h2>
{"".join(helper_html)}
</main></div></body></html>"""
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB): {counts}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reeds/open/docs/constraint_comparison.html")
    ap.add_argument("--report", action="append",
                    default=None, help="validate_slice report.json paths (relative to the repo root)")
    ap.add_argument("--partial", action="store_true")
    args = ap.parse_args(argv)
    reports = args.report or ["runs/v20261010_Pacific_full/port_h2/validate_2030/report.json",
                              "runs/v20261009_Pacific_slice/port_h2/validate_2030/report.json",
                              "../../ReEDS_main/runs/r2_Pacific_mid/port_r2/validate_2030_rows/report.json",
                              "../../ReEDS_main/runs/r2_Pacific_mid/port_r2/validate_2030_linopy/report.json",
                              "../../ReEDS_main/runs/r3_WECC_oracle/port_r3/validate_2035/report.json"]
    build(ROOT / args.out, reports, partial=args.partial)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
