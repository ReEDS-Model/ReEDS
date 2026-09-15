#%% Imports
import ArgParse
import DataFrames
import Logging
import LoggingExtras
import Dates
import PRAS
import HDF5

const DF = DataFrames

### Shared assess/write-results logic (also used by run_pras.jl)
include(joinpath(@__DIR__, "pras_assess.jl"))

#%% Functions
"""
    Parse command line arguments for run_pras_cross_load.jl
"""
function parse_commandline()
    s = ArgParse.ArgParseSettings()

    @ArgParse.add_arg_table s begin
        "--base_pras"
            help = "Path to the .pras file supplying the generation/storage/transmission fleet"
            arg_type = String
            required = true
        "--load_pras"
            help = "Path to the .pras file whose regional load timeseries will be substituted in"
            arg_type = String
            required = true
        "--outfile"
            help = "Path to write assessment results (.h5)"
            arg_type = String
            required = true
        "--samples"
            help = "Number of Monte Carlo samples to run in PRAS"
            arg_type = Int
            default = 100
            required = false
        "--write_flow"
            help = "Write the hourly interface flows"
            arg_type = Int
            default = 0
            required = false
        "--write_surplus"
            help = "Write the hourly surplus"
            arg_type = Int
            default = 0
            required = false
        "--write_energy"
            help = "Write the hourly storage energy"
            arg_type = Int
            default = 0
            required = false
        "--write_shortfall_samples"
            help = "Write the sample-level shortfall"
            arg_type = Int
            default = 0
            required = false
        "--write_availability_samples"
            help = "Write the sample-level generator and storage availability"
            arg_type = Int
            default = 0
            required = false
        "--overwrite"
            help = "Overwrite an existing output file"
            arg_type = Int
            default = 1
            required = false
        "--pras_seed"
            help = "Random seed for PRAS (positive integer; ignored and set randomly if 0)"
            arg_type = Int
            default = 1
            required = false
        "--debug"
            help = "Log debug-level messages"
            arg_type = Int
            default = 0
            required = false
    end
    return ArgParse.parse_args(s)
end

"""
    Set up logging to file and console
"""
function setup_logger(outfile::String, args::Dict)
    logfile = replace(outfile, ".h5"=>".log")

    if args["debug"] == 1
        logfilehandle = LoggingExtras.MinLevelLogger(
            LoggingExtras.FileLogger(logfile; append=true),
            Logging.Debug)
    else
        logfilehandle = LoggingExtras.MinLevelLogger(
            LoggingExtras.FileLogger(logfile; append=true),
            Logging.Info)
    end

    logger = LoggingExtras.TeeLogger(
        Logging.global_logger(),
        logfilehandle
    )

    timestamp_logger(logger) = LoggingExtras.TransformerLogger(logger) do log
        merge(
            log,
            (; message = "$(Dates.format(Dates.now(), "yyyy-mm-dd HH:MM:SS")) | $(log.message)")
        )
    end

    Logging.global_logger(timestamp_logger(logger))
end

"""
    Build a new PRAS SystemModel using `base_sys`'s generators, storages,
    generator-storages, demand responses, and transmission network, but with
    `load_sys`'s regional load timeseries substituted in for `base_sys`'s own load.

    The two systems must model the same set of regions (region names, not just
    the count, must match) and have the same number of timesteps; PRAS systems
    built from ReEDS runs satisfy this whenever the two ReEDS cases share the
    same modeled-region set (GSw_Region) and the same resource-adequacy weather
    years (GSw_PRM_StressYears / resource_adequacy_years_list).
"""
function swap_load(base_sys::PRAS.SystemModel, load_sys::PRAS.SystemModel)
    base_names = base_sys.regions.names
    load_names = load_sys.regions.names

    issetequal(base_names, load_names) || error(
        "Region sets differ between the base system ($(join(sort(base_names), ", "))) " *
        "and the load system ($(join(sort(load_names), ", "))); cross-load testing " *
        "requires both systems to model the same regions."
    )

    N_base = size(base_sys.regions.load, 2)
    N_load = size(load_sys.regions.load, 2)
    N_base == N_load || error(
        "Base system has $(N_base) timesteps but load system has $(N_load) timesteps; " *
        "they must match to swap load timeseries."
    )

    ## Reorder the load system's load matrix to match the base system's region order
    load_lookup = Dict(n => i for (i, n) in enumerate(load_names))
    reorder = [load_lookup[n] for n in base_names]
    new_load = load_sys.regions.load[reorder, :]

    N, L, T, P, E = PRAS.get_params(base_sys)
    new_regions = PRAS.Regions{N,P}(base_names, new_load)

    return PRAS.SystemModel(
        new_regions, base_sys.interfaces,
        base_sys.generators, base_sys.region_gen_idxs,
        base_sys.storages, base_sys.region_stor_idxs,
        base_sys.generatorstorages, base_sys.region_genstor_idxs,
        base_sys.demandresponses, base_sys.region_dr_idxs,
        base_sys.lines, base_sys.interface_line_idxs,
        base_sys.timestamps, base_sys.attrs,
    )
end

#%% Main function
"""
    Load `base_pras`, substitute in the regional load from `load_pras`, run PRAS
    on the resulting hybrid system, and write the shortfall/EUE/LOLE results.
"""
function main(args::Dict)
    outfile = args["outfile"]

    if (args["overwrite"] == 0) && isfile(outfile)
        @info "$(outfile) already exists and --overwrite=0; skipping."
        return nothing
    end

    setup_logger(outfile, args)
    @info "Julia version: $(VERSION)"
    @info "Running run_pras_cross_load.jl with the following inputs:"
    for (arg, val) in args
        @info "$arg  =>  $val"
    end

    @info "Parsing base PRAS System (generation/storage/transmission) from $(args["base_pras"]) ..."
    base_sys = PRAS.SystemModel(args["base_pras"])

    @info "Parsing load PRAS System (regional load) from $(args["load_pras"]) ..."
    load_sys = PRAS.SystemModel(args["load_pras"])

    @info "Building hybrid system: base fleet + substituted load ..."
    sys = swap_load(base_sys, load_sys)

    @info "Running PRAS on the hybrid system ..."
    dfout = assess_and_write(sys, args, outfile)
    @info "Finished run_pras_cross_load.jl"

    return dfout
end


#%% Procedure
if abspath(PROGRAM_FILE) == @__FILE__
    #%% Inputs for debugging
    # args = Dict(
    #     "base_pras" => "/path/to/ReEDS/runs/basecase/handoff/PRAS/PRAS_2035i0.pras",
    #     "load_pras" => "/path/to/ReEDS/runs/othercase/handoff/PRAS/PRAS_2035i0.pras",
    #     "outfile" => "/path/to/ReEDS/runs/basecase/handoff/PRAS/crossload/PRAS_2035i0_loadfrom_othercase-100.h5",
    #     "samples" => 100,
    #     "write_flow" => 0,
    #     "write_surplus" => 0,
    #     "write_energy" => 0,
    #     "write_shortfall_samples" => 0,
    #     "write_availability_samples" => 0,
    #     "overwrite" => 1,
    #     "pras_seed" => 1,
    #     "debug" => 0,
    # )

    #%% Parse the command line arguments
    args = parse_commandline()

    #%% Run it
    main(args)

    #%%
end
