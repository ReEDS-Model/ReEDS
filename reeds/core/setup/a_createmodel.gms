$setglobal ds \
$ifthen.unix %system.filesys% == UNIX
$setglobal ds /
$endif.unix

$include reeds%ds%core%ds%setup%ds%b_inputs.gms

$ifthene.finito_link %GSw_FINITO_Link% == 1
$include finito%ds%model%ds%finito_input.gms
$include finito%ds%model%ds%finito_vars_eqs.gms
$endif.finito_link

$include reeds%ds%core%ds%setup%ds%c_model.gms

$ifthene.finito_link %GSw_FINITO_Link% == 1
$include finito%ds%model%ds%finito_model.gms
$endif.finito_link

$include reeds%ds%core%ds%setup%ds%d_objective.gms
$include reeds%ds%core%ds%setup%ds%d_mga.gms
$include reeds%ds%core%ds%setup%ds%e_solveprep.gms
