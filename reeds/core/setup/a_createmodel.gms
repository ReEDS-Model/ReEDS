$setglobal ds \
$ifthen.unix %system.filesys% == UNIX
$setglobal ds /
$endif.unix

$include reeds%ds%core%ds%setup%ds%b_inputs.gms
$include reeds%ds%core%ds%setup%ds%c_model.gms
$include reeds%ds%core%ds%setup%ds%d_objective.gms
$include reeds%ds%core%ds%setup%ds%d_mga.gms
$include reeds%ds%core%ds%setup%ds%e_solveprep.gms
