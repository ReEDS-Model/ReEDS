"""
    This function creates a PRAS (Probabilistic Resource Adequacy System) model
    from a set of regions, lines, generators, storages, and generator-storages.
    It takes in a vector of Region objects, a vector of Line objects, a vector
    of Generator objects, a vector of Storage objects, a vector of Gen_Storage
    objects, an integer timesteps representing the number of timesteps, and an
    integer weather_year representing the year of the simulation. It then
    creates a StepRange object for the timestamps, creates
    PRAS lines and interfaces from the sorted lines and interface indices,
    creates PRAS regions from the regions, creates PRAS generators from the
    sorted generators and generator indices, creates PRAS storages from the
    storages and storage indices, creates PRAS generator-storages from the
    sorted generator-storages and generator-storage indices, and finally
    returns a PRAS system model object.

    Parameters
    ----------
    regions : Vector{Region}
        Vector of Region objects.
    lines : Vector{Line}
        Vector of Line objects.
    gens : Vector{<:Generator}
        Vector of Generator objects.
    storages : Vector{<:Storage}
        Vector of Storage objects.
    gen_stors : Vector{<:Gen_Storage}
        Vector of Gen_Storage objects.
    timesteps : Int
        Number of timesteps.
    weather_year : Int
        Year of the simulation.

    Returns
    -------
    PRAS.SystemModel
        PRAS system model object.
"""
function create_pras_system(
    regions::Vector{Region},
    lines::Vector{Line},
    gens::Vector{<:Generator},
    storages::Vector{<:Storage},
    gen_stors::Vector{<:Gen_Storage},
    timesteps::Int,
    weather_year::Int,
)
    first_ts = TimeZones.ZonedDateTime(weather_year, 01, 01, 00, TimeZones.tz"UTC")
    last_ts = first_ts + Dates.Hour(timesteps - 1)
    my_timestamps = StepRange(first_ts, Dates.Hour(1), last_ts)

    out = get_sorted_lines(lines, regions)
    sorted_lines, interface_reg_idxs, interface_line_idxs = out
    pras_lines, pras_interfaces =
        make_pras_interfaces(sorted_lines, interface_reg_idxs, interface_line_idxs, regions)
    pras_regions = PRAS.Regions{timesteps, PRAS.MW}(
        get_name.(regions),
        reduce(vcat, get_load.(regions)),
    )
    ##
    sorted_gens, gen_idxs = get_sorted_components(gens, get_name.(regions))
    n_gens = length(sorted_gens)
    capacity_matrix = Matrix{Int64}(undef, n_gens, timesteps)
    λ_matrix = Matrix{Float64}(undef, n_gens, timesteps)
    μ_matrix = Matrix{Float64}(undef, n_gens, timesteps)
    for (i, g) in enumerate(sorted_gens)
        capacity_matrix[i, :] = get_capacity(g)
        λ_matrix[i, :] = get_λ(g)
        μ_matrix[i, :] = get_μ(g)
    end
    gen_names = get_name.(sorted_gens)
    gen_types = get_type.(sorted_gens)
    sorted_gens = nothing
    GC.gc()
    pras_gens = PRAS.Generators{timesteps, 1, PRAS.Hour, PRAS.MW}(
        gen_names,
        gen_types,
        capacity_matrix,
        λ_matrix,
        μ_matrix,
    )
    ##
    storages, stor_idxs = get_sorted_components(storages, regions)
    n_stors = length(storages)

    stor_names = isempty(get_name.(storages)) ? String[] : get_name.(storages)
    stor_types = isempty(get_type.(storages)) ? String[] : get_type.(storages)
    if n_stors == 0
        stor_charge_cap_array    = Matrix{Int64}(undef, 0, timesteps)
        stor_discharge_cap_array = Matrix{Int64}(undef, 0, timesteps)
        stor_energy_cap_array    = Matrix{Int64}(undef, 0, timesteps)
        stor_chrg_eff_array      = Matrix{Float64}(undef, 0, timesteps)
        stor_dischrg_eff_array   = Matrix{Float64}(undef, 0, timesteps)
        stor_cryovr_eff          = Matrix{Float64}(undef, 0, timesteps)
        λ_stor                   = Matrix{Float64}(undef, 0, timesteps)
        μ_stor                   = Matrix{Float64}(undef, 0, timesteps)
    else
        stor_charge_cap_array    = Matrix{Int64}(undef, n_stors, timesteps)
        stor_discharge_cap_array = Matrix{Int64}(undef, n_stors, timesteps)
        stor_energy_cap_array    = Matrix{Int64}(undef, n_stors, timesteps)
        stor_chrg_eff_array      = Matrix{Float64}(undef, n_stors, timesteps)
        stor_dischrg_eff_array   = Matrix{Float64}(undef, n_stors, timesteps)
        stor_cryovr_eff          = Matrix{Float64}(undef, n_stors, timesteps)
        λ_stor                   = Matrix{Float64}(undef, n_stors, timesteps)
        μ_stor                   = Matrix{Float64}(undef, n_stors, timesteps)
        for (i, s) in enumerate(storages)
            stor_charge_cap_array[i, :]    = get_charge_capacity(s)
            stor_discharge_cap_array[i, :] = get_discharge_capacity(s)
            stor_energy_cap_array[i, :]    = get_energy_capacity(s)
            stor_chrg_eff_array[i, :]      = get_charge_efficiency(s)
            stor_dischrg_eff_array[i, :]   = get_discharge_efficiency(s)
            stor_cryovr_eff[i, :]          = get_carryover_efficiency(s)
            λ_stor[i, :]                   = get_λ(s)
            μ_stor[i, :]                   = get_μ(s)
        end
    end
    storages = nothing
    GC.gc()
    pras_storages = PRAS.Storages{timesteps, 1, PRAS.Hour, PRAS.MW, PRAS.MWh}(
        stor_names,
        stor_types,
        stor_charge_cap_array,
        stor_discharge_cap_array,
        stor_energy_cap_array,
        stor_chrg_eff_array,
        stor_dischrg_eff_array,
        stor_cryovr_eff,
        λ_stor,
        μ_stor,
    )
    ##
    sorted_gen_stors, genstor_idxs = get_sorted_components(gen_stors, regions)
    n_gen_stors = length(sorted_gen_stors)

    gen_stor_names =
        isempty(get_name.(sorted_gen_stors)) ? String[] : get_name.(sorted_gen_stors)
    gen_stor_cats =
        isempty(get_type.(sorted_gen_stors)) ? String[] : get_type.(sorted_gen_stors)
    if n_gen_stors == 0
        gen_stor_cap_array            = Matrix{Int64}(undef, 0, timesteps)
        gen_stor_dis_cap_array        = Matrix{Int64}(undef, 0, timesteps)
        gen_stor_enrgy_cap_array      = Matrix{Int64}(undef, 0, timesteps)
        gen_stor_chrg_eff_array       = Matrix{Float64}(undef, 0, timesteps)
        gen_stor_dischrg_eff_array    = Matrix{Float64}(undef, 0, timesteps)
        gen_stor_carryovr_eff_array   = Matrix{Float64}(undef, 0, timesteps)
        gen_stor_inflow_array         = Matrix{Int64}(undef, 0, timesteps)
        gen_stor_grid_withdrawl_array = Matrix{Int64}(undef, 0, timesteps)
        gen_stor_grid_inj_array       = Matrix{Int64}(undef, 0, timesteps)
        gen_stor_λ                    = Matrix{Float64}(undef, 0, timesteps)
        gen_stor_μ                    = Matrix{Float64}(undef, 0, timesteps)
    else
        gen_stor_cap_array            = Matrix{Int64}(undef, n_gen_stors, timesteps)
        gen_stor_dis_cap_array        = Matrix{Int64}(undef, n_gen_stors, timesteps)
        gen_stor_enrgy_cap_array      = Matrix{Int64}(undef, n_gen_stors, timesteps)
        gen_stor_chrg_eff_array       = Matrix{Float64}(undef, n_gen_stors, timesteps)
        gen_stor_dischrg_eff_array    = Matrix{Float64}(undef, n_gen_stors, timesteps)
        gen_stor_carryovr_eff_array   = Matrix{Float64}(undef, n_gen_stors, timesteps)
        gen_stor_inflow_array         = Matrix{Int64}(undef, n_gen_stors, timesteps)
        gen_stor_grid_withdrawl_array = Matrix{Int64}(undef, n_gen_stors, timesteps)
        gen_stor_grid_inj_array       = Matrix{Int64}(undef, n_gen_stors, timesteps)
        gen_stor_λ                    = Matrix{Float64}(undef, n_gen_stors, timesteps)
        gen_stor_μ                    = Matrix{Float64}(undef, n_gen_stors, timesteps)
        for (i, gs) in enumerate(sorted_gen_stors)
            gen_stor_cap_array[i, :]            = get_charge_capacity(gs)
            gen_stor_dis_cap_array[i, :]        = get_discharge_capacity(gs)
            gen_stor_enrgy_cap_array[i, :]      = get_energy_capacity(gs)
            gen_stor_chrg_eff_array[i, :]       = get_charge_efficiency(gs)
            gen_stor_dischrg_eff_array[i, :]    = get_discharge_efficiency(gs)
            gen_stor_carryovr_eff_array[i, :]   = get_carryover_efficiency(gs)
            gen_stor_inflow_array[i, :]         = get_inflow(gs)
            gen_stor_grid_withdrawl_array[i, :] = get_grid_withdrawl_capacity(gs)
            gen_stor_grid_inj_array[i, :]       = get_grid_injection_capacity(gs)
            gen_stor_λ[i, :]                    = get_λ(gs)
            gen_stor_μ[i, :]                    = get_μ(gs)
        end
    end
    sorted_gen_stors = nothing
    GC.gc()

    gen_stors = PRAS.GeneratorStorages{timesteps, 1, PRAS.Hour, PRAS.MW, PRAS.MWh}(
        gen_stor_names,
        gen_stor_cats,
        gen_stor_cap_array,
        gen_stor_dis_cap_array,
        gen_stor_enrgy_cap_array,
        gen_stor_chrg_eff_array,
        gen_stor_dischrg_eff_array,
        gen_stor_carryovr_eff_array,
        gen_stor_inflow_array,
        gen_stor_grid_withdrawl_array,
        gen_stor_grid_inj_array,
        gen_stor_λ,
        gen_stor_μ,
    )

    return PRAS.SystemModel(
        pras_regions,
        pras_interfaces,
        pras_gens,
        gen_idxs,
        pras_storages,
        stor_idxs,
        gen_stors,
        genstor_idxs,
        pras_lines,
        interface_line_idxs,
        my_timestamps,
    )
end
