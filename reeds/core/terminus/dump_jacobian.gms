$title Dump one solve year's LP matrix, so a variable's constraints can be read

* What this is for
* ----------------
* "Which equations does this variable actually enter?" Source-level grep answers
* that badly: an equation's $ conditions decide whether it is in the model at
* all, switches are read at compile time, and an equation can be live even when
* its switch is off (eq_CSAPR_Assurance was, until 2026-09). The solved matrix
* has no such ambiguity - it lists exactly the rows the solver saw.
*
* This restarts from a g00, rebuilds one year's model, and writes the Jacobian
* with the CONVERT solver. No solve happens: CONVERT writes the matrix and
* returns, so the LP's own solution is untouched. Read a column out of the
* result with jacobian_column.py.
*
* Usage
* -----
*   cd runs/<case>
*   gams reeds/core/terminus/dump_jacobian.gms \
*        r=g00files/<case>_<year>i<n>.g00 --year=2050 --out=jac2050.gdx
*
* The gdx is large - roughly 2 GB for a national run - and is pure scratch.
* Write it somewhere disposable and delete it when done; do not leave it in a
* run directory where it will be mistaken for an output.
*
* Notes
* -----
* holdfixed=0 keeps variables that 5_varfix.gms has fixed as columns in the
* matrix. Without it every prior year's variable is substituted out as a
* constant and its rows vanish, which is exactly the history one is usually
* trying to inspect.
*
* Only the year given by --year is built (tmodel is set to it alone), matching
* how the sequential solve builds one year at a time. Equations are conditioned
* on $tmodel(t), so asking for a year other than the restart file's own gives a
* matrix the solver never saw - the levels and duals in the file belong to the
* restart year. Dump the year you intend to read.

$if not set year $abort 'Set --year=<solve year>, e.g. --year=2050'
$if not set out  $setglobal out jacobian.gdx

tmodel(t) = no ;
tmodel("%year%") = yes ;

ReEDSmodel.holdfixed = 0 ;
option lp = convert ;
ReEDSmodel.optfile = 1 ;
$echo dumpgdx %out% > convert.opt

solve ReEDSmodel minimizing z using lp ;
