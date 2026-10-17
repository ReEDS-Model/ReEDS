"""ReEDS formulation slice for the Python modeling-language bake-off (pyoframe vs Pyomo).

Pipeline: contract (raw GAMS-exported tables) -> prep (shared domains and
coefficients, polars) -> build_pyoframe / build_pyomo (algebra only).
"""
