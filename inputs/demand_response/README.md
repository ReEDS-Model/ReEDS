## Demand Response Input Files

### DR Shed Input Files

- **`dr_shed_hourly_{dr_shedscen}.h5`**: Hourly DR shed resource availability.
- **`inputs/supply_curve/dr_shed_cost_{dr_shedscen}.csv`**: Supply curve cost [$/MW]. Represents the installation cost for the DR-enabling technology (program implementation or procurement costs are not included) in 2020 dollars.
- **`inputs/plant_characteristics/dr_shed_capcost_scalars_{dr_shedscen}.csv`**: Supply curve populated with 2030 cost data, scaled in the model to reflect additional years through 2050.
- **`inputs/supply_curve/dr_shed_cap_{dr_shedscen}.csv`**: Supply curve capacity [MW], populated with maximum technical potential in 2030 for each ReEDS zone from the hourly shed data.
- **`inputs/demand_response/dr_shed_capacity_scalar_{dr_shedscen}.csv`**: Supply curve populated with 2030 capacity data, scaled in the model to reflect additional years through 2050.
- **`inputs/plant_characteristics/dr_shed_vom_{dr_shedscen}.csv`**: Variable operation and maintenance costs for the DR Shed resource [$/MWh].
- **`inputs/plant_characteristics/dr_shed_fom_{dr_shedscen}.csv`**: Fixed operation and maintenance costs for the DR Shed resource [$/MWh].
- **`inputs/demand_response/dr_shed_avail_scalar.csv`**: Scalar representing the response rate of the resource by decrementing availability. Set to 1 by default.
- **`inputs/plant_characteristics/maxdailycf.csv`**: Defines the maximum daily capacity factor for any technology. Default is 4 hours per day for DR shed (0.167 = 4/24).

### DR Shape Input Files

- **`dr_shape_decrease_profile_{dr_shapescen}.h5`**: Hourly time series of fractions representing the amount of “generation” (load that can be delayed).
- **`dr_shape_increase_profile_{dr_shapescen}.h5`**: Hourly time series of fractions representing the amount of added load in a later hour (deferred).
- **`inputs/supply_curve/dr_shape_cost_{dr_shapescen}.csv`**: Supply curve cost [$/MW]. Assumed to be 0 in the demonstration data.
- **`inputs/supply_curve/dr_shape_cap_{dr_shapescen}.csv`**: Supply curve capacity [MW], populated with maximum technical potential in 2030 for each state from the hourly shape data.
- **`inputs/plant_characteristics/dr_shape_cost_scalars_{dr_shapescen}.csv`**: Supply curve populated with 2030 cost data, scaled in the model to reflect additional years through 2050.
- **`inputs/demand_response/dr_shape_capacity_scalar_{dr_shapescen}.csv`**: Supply curve populated with 2030 capacity data, scaled in the model to reflect additional years through 2050.
- **`inputs/plant_characteristics/dr_shape_vom_{dr_shapescen}.csv`**: Variable operation and maintenance costs for the DR Shape resource [$/MWh].
- **`inputs/plant_characteristics/dr_shape_fom_{dr_shapescen}.csv`**: Fixed operation and maintenance costs for the DR Shape resource [$/MWh].

### DR Shift Input Files

- **`dr_shift_decrease_profile_{dr_shiftscen}.h5`**: Baseline/discharge profile of DR resource available to be deferred (or immediate charging/use if not participating in DR).
- **`dr_shift_increase_profile_{dr_shiftscen}.h5`**: Outer bound on when DR resource can be shifted (or latest possible charging/payback).
- **`dr_shift_energy_profile_{dr_shiftscen}.h5`**: Deferment/flexibility potential.
- **`inputs/supply_curve/dr_shift_cost_{dr_shiftscen}.csv`**: Supply curve cost [$/MW]. Assumed to be 0 in the demonstration data.
- **`inputs/supply_curve/dr_shift_cap_{dr_shiftscen}.csv`**: Supply curve capacity [MW], populated with maximum technical potential in 2030 for each state from the hourly shift data.
- **`inputs/plant_characteristics/dr_shift_cost_scalars_{dr_shiftscen}.csv`**: Supply curve populated with 2030 cost data, scaled in the model to reflect additional years through 2050.
- **`inputs/demand_response/dr_shift_capacity_scalar_{dr_shiftscen}.csv`**: Supply curve populated with 2030 capacity data, scaled in the model to reflect additional years through 2050.
- **`inputs/plant_characteristics/dr_shift_vom_{dr_shiftscen}.csv`**: Variable operation and maintenance costs for the DR Shift resource [$/MWh].
- **`inputs/plant_characteristics/dr_shift_fom_{dr_shiftscen}.csv`**: Fixed operation and maintenance costs for the DR Shift resource [$/MWh].