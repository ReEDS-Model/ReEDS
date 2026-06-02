# Sets

## Formatting guidelines

- Primary sets (those that define elements that are not subsets of other sets):
  - No header column
  - One element per line
  - No element-wise comments; each line should contain only the element
- Subsets (groups of elements from other sets, either 1-dimensional or multidimensional):
  - Include a header column specifying the relevant primary sets
  - The header column should start with a `*`
    - Even 1-dimensional subsets should have a header column.
    So if the set `food` has elements `[apple, banana, cauliflower]`, the subset `fruit(food)` (specified by `fruit.csv`) has the following lines:
      - `*food`
      - `apple`
      - `banana`
- Don't use * or # for element expansion in GAMS
- Don't use * for full-line comments; only use it for the first (header) row in subset definitions

## Set-defining files

- `ctt.csv`: cooling technology types
  - `o`: once through
  - `r`: recirculating
  - `d`: dry cooled
  - `p`: pond cooled
  - `n`: no cooling (or generic placeholder)
- `sc_cat.csv`: resource supply curve data categories
  - `cap`: power capacity available [MW]
  - `cost`: total supply curve cost [\$/MW]
  - `cost_trans`: transmission (spur, point-of-interconnection, and reinforcement) component of supply curve cost [\$/MW]
  - `cost_cap`: economies of scale, land cost, and other modifier components of supply curve cost [\$/MW]
- `wst.csv`: water source type
  - `fsu`: fresh surface water that is unappropriated
  - `fsa`: fresh surface water that is appropriated
  - `fsl`: fresh surface lake
  - `fg`: fresh groundwater
  - `sg`: brackish or saline groundwater
  - `ss`: saline surface water
  - `ww`: wastewater effluent

## Special-case files

- `_aliases.csv`: aliases (extra names for the same set) used in GAMS
  - Aliases of primary sets should be added here
  - Aliases of sets defined in `b_inputs.gms` (e.g., `h`→`hh`) should instead be defined in GAMS after the set definition
- `_pcat.csv`: prescribed capacity categories
  - The `pcat` set in GAMS (defined in `writecapdat.py`) includes the members of the `i` set; this file includes only the *extra* elements on top of the `i` set
