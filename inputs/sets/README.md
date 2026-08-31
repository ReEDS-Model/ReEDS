## Sets

### Formatting guidelines

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

### Set-defining files

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

### Special-case files

- `_aliases.csv`: aliases (extra names for the same set) used in GAMS
  - Aliases of primary sets should be added here
  - Aliases of sets defined in `b_inputs.gms` (e.g., `h`→`hh`) should instead be defined in GAMS after the set definition

### Additional files
- `RPSCat.csv`: set of RPS constraint categories, including clean energy standards

- `aclike.csv`: set of AC transmission capacity types

- `allt.csv`: set of all potential years

- `bioclass.csv`: set of biomass supply curve classes, each a price/quantity bin of biomass feedstock supply

- `captype.csv`: set of capacity types (existing and prescribed)

- `ccsflex_cat.csv`:set of flexible ccs performance parameter categories

- `climate_param.csv`: set of parameters defined in climate_heuristics_finalyear

- `consumecat.csv`: set of categories for consuming facility characteristics

- `csapr_cat.csv`: set of CSAPR regulation categories

- `csapr_group.csv`: set of CSAPR trading groups

- `e.csv`: set of emission categories used in model

- `eall.csv`: set of emission categories used in reporting

- `etype.csv`: set of emission types (process or upstream)

- `f.csv`: set of fuel types

- `flex_type.csv`: set of demand flexibility types

- `fuel2tech.csv`: mapping between fuel types and generations

- `fuelbin.csv`: set of gas usage brackets

- `gb.csv`: set of gas price bins; must have an odd number of bins (e.g. gb1*gb15)

- `gbin.csv`: set of growth bins

- `geotech.csv`: set of geothermal technology categories

- `h2_st.csv`: defines investments needed to store and transport H2

- `h2_stor.csv`: set of H2 storage options

- `hintage_char.csv`: set of characteristics available in hintage_data

- `i.csv`: set of technologies

- `i_geotech.csv`: crosswalk between an individual geothermal technology and its category

- `i_h2_ptc_gen.csv`: set of technologies which can produce energy for electrolyzers claiming the hydrogen production tax credit due to their low lifecycle carbon emissions

- `i_p.csv`: mapping from technologies to the products they produce

- `i_subtech.csv`: set of categories for subtechs

- `i_water_nocooling.csv`: set of technologies that use water, but are not differentiated by cooling tech and water source

- `jtype.csv`: set of job types used in the model (construction and O&M)

- `lcclike.csv`: set of transmission capacity types where lines are bundled with AC/DC converters

- `month.csv`: Calendar months in a year

- `noretire.csv`: set of technologies that will never be retired

- `notvsc.csv`: set of transmission capacity types that are not VSC

- `ofstype.csv`: set of offshore types used in offshore requirement constraint (eq_RPS_OFSWind)

- `ofstype_i.csv`: crosswalk between ofstype and i

- `orcat.csv`: set of operating reserve categories

- `ortype.csv`: set of types of operating reserve constraints

- `p.csv`: set of products produced

- `plantcat.csv`: set of categories for plant characteristics

- `prepost.csv`: Defines pre-2010 versus post-2010 years

- `pvb_agg.csv`: crosswalk between hybrid pv+battery configurations and technology options

- `pvb_config.csv`: set of hybrid pv+battery configurations

- `quarter.csv`: four quarters (listed as seasons) of the year

- `resourceclass.csv`: set of renewable resource classes

- `sdbin.csv`: set of storage duration bins [hours]

- `tg.csv`: set of technology groups used for growth constraints

- `tg_rsc_cspagg.csv`: set of csp technologies that belong to the same class

- `tg_rsc_upvagg.csv`: set of pv and pvb technologies that belong to the same class

- `trancap_fut_cat.csv`: set of categories of near-term transmission projects that describe the likelihood of being completed

- `trtype.csv`: set of transmission capacity types

- `unitspec_upgrades.csv`: set of upgraded technologies that get unit-specific characteristics

- `upgrade_hintage_char.csv`: set to operate over in extension of hintage_data characteristics when sw_upgrades = 1

- `w.csv`: set of water withdrawal or consumption options for water techs

- `wst_climate.csv`: set of water sources affected by climate change

- `wst_surface.csv`: Surface water types, for which access is based on consumption rather than withdrawal

- `yearafter.csv`: set to loop over for the final year calculation
