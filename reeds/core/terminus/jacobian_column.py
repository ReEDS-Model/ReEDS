"""Read a variable's constraints out of a Jacobian written by dump_jacobian.gms.

Two questions this answers that reading c_model.gms does not:

  --var    what does THIS variable enter, with what coefficient? The column is
           the reduced-cost identity, term by term: sum over rows of
           (coefficient x dual) must equal the objective coefficient for a
           variable that is free and away from its bounds.

  --tech   what does a technology's every variable enter, anywhere in the LP?
           Grep over the source misses rows whose equation is live despite its
           switch being off, and finds rows whose $ conditions exclude the tech.
           The matrix has neither problem.

The --tech form samples, because reading every column is not feasible: GAMS
iterates the equation x variable product, so a family with 300k columns against
10M rows does not finish. It samples per (variable family, vintage, year), not
per family, because a family is not homogeneous: INV for an initial vintage
enters only the retirement accounting where a new one also enters the
objective, and INV for a PRIOR year - kept as a column by holdfixed=0 - enters
neither. Most columns belong to prior years, so stratifying on the year is what
keeps the modelled year in the sample at all.

So --tech gives a map, not a proof. Confirm anything load-bearing with --var on
a specific column, which is exact.

Usage
-----
  # write the matrix first (about 5 minutes, about 2 GB)
  cd runs/<case>
  gams reeds/core/terminus/dump_jacobian.gms r=g00files/<case>_2050i0.g00 \
       --year=2050 --out=/tmp/jac2050.gdx

  # one column, every row it touches
  python reeds/core/terminus/jacobian_column.py /tmp/jac2050.gdx \
      --var 'GEN(coal-new,new27,GA,y2012d116h006,2050)'

  # every equation family a tech's variables enter
  python reeds/core/terminus/jacobian_column.py /tmp/jac2050.gdx --tech battery_li

The gdx is scratch: delete it when done.
"""

import argparse
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import defaultdict

# gdxdump renders the variable set as:  'x1234' 'GEN(coal-new,new13,r,h,t)',
ENTRY = re.compile(r"'(x\d+)'\s+'(.*?)',?\s*$")
FAMILY = re.compile(r'^([A-Za-z_0-9]+)')


def variable_index(gdx, match=None):
    """Stream the 'j' set, returning [(id, name)] for names containing `match`.

    gdxdump writes the whole set - 10M lines for a national run - so this
    filters as it reads rather than building the index in memory.
    """
    proc = subprocess.Popen(
        ['gdxdump', gdx, 'symb=j'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )
    found = []
    for line in proc.stdout:
        if match is not None and match not in line:
            continue
        m = ENTRY.search(line)
        if m:
            found.append((m.group(1), m.group(2)))
    proc.stdout.close()
    proc.wait()
    return found


def family_of(name):
    m = FAMILY.match(name)
    return m.group(1) if m else name


def strata(name):
    """Second and last index: for most families the vintage and the year.

    Both matter for sampling. Initial and new vintages of a variable enter
    different equations. So do different years: holdfixed=0 keeps every prior
    year's fixed variables as columns, and those carry only the accounting rows
    that reach forward - a prior year's INV is in eq_cap_new_noret but not in
    this year's objective, because its cost was charged in its own year. Most
    columns of a family belong to prior years, so a sample that does not
    stratify on the year mostly misses the year actually being modelled.
    """
    inner = name[name.find('(') + 1:name.rfind(')')] if '(' in name else ''
    parts = inner.split(',')
    return (parts[1] if len(parts) > 1 else '', parts[-1] if parts else '')


def extract(gdx, names_by_id, workdir):
    """Run GAMS to pull the given columns out of the Jacobian.

    Returns [(variable name, equation name, coefficient)]. GAMS emits the
    column's label (x1234) rather than its element text - .te on a subset
    returns the label, not the parent set's text - and the label is mapped back
    to the variable's name here, where that mapping is already known.
    """
    out = os.path.join(workdir, 'column.txt')
    gms = os.path.join(workdir, 'column.gms')
    with open(gms, 'w') as f:
        f.write('set i, j ; parameter A(i,j) ;\n')
        f.write(f'$gdxin {gdx}\n$load i j A\n$gdxin\n')
        f.write('set xj(j) / %s / ;\n' % '\n'.join(names_by_id))
        f.write(f"file f / '{out}' / ; f.pw = 32767 ; put f ;\n")
        # '|' separated: element text holds commas and spaces, so neither works
        f.write("loop((i,xj)$A(i,xj),\n"
                "    put xj.tl:0, '|', i.te(i):0, '|', A(i,xj):0:8 / ; ) ;\n"
                "putclose f ;\n")

    res = subprocess.run(
        ['gams', gms, 'o=' + os.path.join(workdir, 'column.lst')],
        capture_output=True, text=True, cwd=workdir,
    )
    if not os.path.exists(out):
        sys.exit(f'GAMS produced no output; see {workdir}/column.lst\n{res.stdout[-2000:]}')
    rows = []
    with open(out) as f:
        for line in f:
            parts = line.rstrip('\n').split('|')
            if len(parts) == 3:
                vid = parts[0].strip()
                rows.append((names_by_id.get(vid, vid), parts[1].strip(), float(parts[2])))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('gdx', help='Jacobian written by dump_jacobian.gms')
    p.add_argument('--var', help="one variable, exactly as GAMS names it, "
                                 "e.g. 'CAP(battery_li,new1,CO,2050)'")
    p.add_argument('--tech', help='a tech name; every variable family holding it '
                                  'is sampled, e.g. battery_li')
    p.add_argument('--year', help="with --tech, keep only columns of this solve year. "
                                  "Usually what you want: holdfixed=0 leaves every "
                                  "prior year's fixed variables in the matrix, and they "
                                  "carry rows the current year's do not - a long-expired "
                                  "INV sits in eq_refurblim, this year's does not.")
    p.add_argument('--per-group', type=int, default=2,
                   help='with --tech, columns to sample per (variable family, vintage, '
                        'year) group (default 2)')
    p.add_argument('--keep', action='store_true', help='keep the GAMS scratch files')
    args = p.parse_args()

    if bool(args.var) == bool(args.tech):
        p.error('give exactly one of --var or --tech')

    if args.var:
        wanted = variable_index(args.gdx, match=args.var)
        exact = [(i, n) for i, n in wanted if n == args.var]
        if not exact:
            near = '\n  '.join(n for _, n in wanted[:10])
            sys.exit(f'No variable named exactly {args.var!r}.'
                     + (f' Near matches:\n  {near}' if near else ''))
        selected = {exact[0][0]: exact[0][1]}
    else:
        # sample a few columns per variable family holding this tech
        hits = variable_index(args.gdx, match=args.tech)
        # the tech must be an index of the variable, not a substring of another
        # name: battery_li must not match battery_li_2 or upv must not match upv_3
        pat = re.compile(r'[(,]' + re.escape(args.tech) + r'[,)]')
        hits = [(i, n) for i, n in hits if pat.search(n)]
        if not hits:
            sys.exit(f'No variables indexed by {args.tech!r} in this matrix.')
        years = defaultdict(int)
        for _, n in hits:
            years[strata(n)[1]] += 1
        if args.year:
            hits = [(i, n) for i, n in hits if strata(n)[1] == args.year]
            if not hits:
                sys.exit(f'No {args.tech} columns for year {args.year}. '
                         f'Years present: {", ".join(sorted(years))}')
        elif len(years) > 1:
            print('Columns span %d years (%s). Prior years are fixed variables kept by\n'
                  'holdfixed=0 and enter rows this year does not; pass --year to filter.\n'
                  % (len(years), ', '.join(sorted(years))))
        by_family = defaultdict(list)
        by_group = defaultdict(list)
        for i, n in hits:
            by_family[family_of(n)].append((i, n))
            by_group[(family_of(n),) + strata(n)].append((i, n))
        # sample at random within each group rather than by a fixed step: ids
        # run in index order, so a step aliases against the period of the
        # region and year indices and can systematically miss a whole year
        rng = random.Random(0)
        selected = {}
        for key in sorted(by_group):
            cols = by_group[key]
            selected.update(dict(rng.sample(cols, min(args.per_group, len(cols)))))
        print(f'{len(hits)} columns indexed by {args.tech}, in '
              f'{len(by_family)} variable families and {len(by_group)} '
              f'(family, vintage, year) groups; sampling {len(selected)}.\n')

    workdir = tempfile.mkdtemp(prefix='jaccol_')
    try:
        rows = extract(args.gdx, selected, workdir)
    finally:
        if args.keep:
            print(f'(scratch kept in {workdir})')
        else:
            subprocess.run(['rm', '-rf', workdir])

    if args.var:
        print(f'{args.var}\n')
        print(f'{"equation":<62} {"coefficient":>14}')
        for _, eq, coef in sorted(rows, key=lambda r: r[1]):
            print(f'{eq:<62} {coef:>14.6f}')
        return

    # --tech: collapse instances to families, which is the reusable answer
    seen = defaultdict(lambda: defaultdict(int))
    example = {}
    for var, eq, coef in rows:
        vf, ef = family_of(var), family_of(eq)
        seen[vf][ef] += 1
        example.setdefault((vf, ef), (eq, coef))
    for vf in sorted(seen):
        print(f'{vf}')
        for ef in sorted(seen[vf]):
            eq, coef = example[(vf, ef)]
            print(f'    {ef:<44} e.g. coefficient {coef:>12.6f}')
        print()


if __name__ == '__main__':
    main()
