#%% Imports
import ArgParse
import DataFrames
import Logging
import LoggingExtras
import Dates
import PRAS
import HDF5

const DF = DataFrames

### Shared assess/write-results logic (also used by run_pras_cross_load.jl)
include(joinpath(@__DIR__, "pras_assess.jl"))

#%% Functions
"""
    Parse command line arguments for use with ReEDS2PRAS and PRAS
"""
function parse_commandline()
    s = ArgParse.ArgParseSettings()

    @ArgParse.add_arg_table s begin
        "--reeds_path"
            help = "Path to ReEDS folder"
            arg_type = String
            required = true
        "--reedscase"
            help = "Path to ReEDS run (usually .../ReEDS/runs/{casename})"
            arg_type = String
            required = true
        "--solve_year"
            help = "ReEDS solve year (usually in [2020..2050])"
            arg_type = Int
            required = true
        "--weather_year"
            help = "The weather year to start from, in [2007..2013,2016..2023]"
            arg_type = Int
            default = 2007
            required = true
        "--samples"
            help = "Number of Monte Carlo samples to run in PRAS"
            arg_type = Int
            default = 10
            required = false
        "--timesteps"
            help = "Number of hourly timesteps to use"
            arg_type = Int
            default = 61320
            required = false
        "--hydro_energylim"
            help = "Model hydropower as an energy-limited resource"
            arg_type = Int
            default = 0
            required = false
        "--scheduled_outage"
            help = "Include monthly scheduled outage"
            arg_type = Int
            default = 0
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
        "--iteration"
            help = "Solve-year iteration number (only used in file label)"
            arg_type = Int
            default = 0
            required = false
        "--overwrite"
            help = "Overwrite an existing .pras file"
            arg_type = Int
            default = 1
            required = false
        "--include_samples"
            help = "Include the number of samples in the output .csv filename"
            arg_type = Int
            default = 0
            required = false
        "--pras_agg_ogs_lfillgas"
            help = "Aggregate existing o-g-s and landfill gas using size for new units"
            arg_type = Int
            default = 0
            required = false
        "--pras_existing_unit_size"
            help = "Use average existing unit size by (tech,region) when disaggregating new units"
            arg_type = Int
            default = 1
            required = false
        "--pras_max_unitsize_prm"
            help = "Cap the upper bound of disaggregated unit size by zone at the zonal PRM in MW"
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
function setup_logger(pras_system_path::String, args::Dict)
    if ~isnothing(pras_system_path)
        logfile = replace(pras_system_path, ".pras"=>".log")

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

        ### https://github.com/JuliaLogging/LoggingExtras.jl#add-timestamp-to-all-logging
        timestamp_logger(logger) = LoggingExtras.TransformerLogger(logger) do log
            merge(
                log,
                (; message = "$(Dates.format(Dates.now(), "yyyy-mm-dd HH:MM:SS")) | $(log.message)")
            )
        end

        Logging.global_logger(timestamp_logger(logger))
    end
end

"""
    Simple PRAS analysis.

    Parameters
    ----------

    Returns
    -------
"""
function run_pras(pras_system_path::String, args::Dict)
    #%% Load the system model
    @info "Parsing PRAS System ..."
    sys = PRAS.SystemModel(pras_system_path);

    #%% Assess it and write the results (shared with run_pras_cross_load.jl)
    if args["include_samples"] == 1
        outfile = replace(pras_system_path, ".pras"=>"-$(args["samples"]).h5")
    else
        outfile = replace(pras_system_path, ".pras"=>".h5")
    end
    return assess_and_write(sys, args, outfile)
end


#%% Main function
"""
    Run ReEDS2PRAS and PRAS
"""
function main(args::Dict)
    #%% Define some intermediate filenames
    pras_system_path = joinpath(
        args["reedscase"], "handoff", "PRAS",
        "PRAS_$(args["solve_year"])i$(args["iteration"]).pras"
    )

    #%% Set up the logger
    setup_logger(pras_system_path, args)
    @info "Julia version: $(VERSION)"
    @info "Julia executable: $(joinpath(Sys.BINDIR, "julia"))"
    @info "Running ReEDS2PRAS with the following inputs:"
    for (arg, val) in args
        @info "$arg  =>  $val"
    end

    #%% Run ReEDS2PRAS
    if (args["overwrite"] == 1) | ~isfile(pras_system_path)
        ### Create and save the PRAS system
        ## Could use compression_level={integer} here but it doesn't really help
        PRAS.savemodel(
            ReEDS2PRAS.reeds_to_pras(
                args["reedscase"],
                args["solve_year"],
                args["timesteps"],
                args["weather_year"],
                # Boolean switches: == to convert from integer to boolean
                args["scheduled_outage"] == 1,
                args["hydro_energylim"] == 1,
                args["pras_agg_ogs_lfillgas"] == 1,
                args["pras_existing_unit_size"] == 1,
                args["pras_max_unitsize_prm"] == 1,
            ),
            pras_system_path,
            verbose=true,
        )
        @info "Finished ReEDS2PRAS"
    end

    #%% Run PRAS
    if args["samples"] > 0
        @info "Running PRAS"
        dfout = run_pras(pras_system_path, args)
        @info "Finished PRAS"
        #%%
        return dfout
    end
end


#%% Procedure
if abspath(PROGRAM_FILE) == @__FILE__
    #%% Inputs for debugging
    # julia --project=/path/to/ReEDS --threads=1
    # args = Dict(
    #     "reeds_path" => "/path/to/ReEDS",
    #     "reedscase" => (
    #         "/path/to/ReEDS/runs/"
    #         *"runname"),
    #     "solve_year" => 2035,
    #     "weather_year" => 2007,
    #     "samples" => 10,
    #     "iteration" => 0,
    #     "timesteps" => 131400,
    #     "hydro_energylim" => 1,
    #     "write_flow" => 0,
    #     "write_surplus" => 0,
    #     "write_energy" => 0,
    #     "write_shortfall_samples" => 1,
    #     "write_availability_samples" => 0,
    #     "overwrite" => 1,
    #     "debug" => 0,
    #     "include_samples" => 0,
    #     "scheduled_outage" => 0,
    #     "pras_agg_ogs_lfillgas" => 0,
    #     "pras_existing_unit_size" => 1,
    #     "pras_max_unitsize_prm" => 1,
    #     "pras_seed" => 1,
    # )
    # reedscase = args["reedscase"]
    # solve_year = args["solve_year"]
    # timesteps = args["timesteps"]
    # weather_year = args["weather_year"]
    # include(joinpath(args["reeds_path"], "reeds2pras", "src", "ReEDS2PRAS.jl"))

    #%% Parse the command line arguments
    args = parse_commandline()

    #%% Include ReEDS2PRAS
    include(joinpath(
        args["reedscase"], "reeds", "resource_adequacy", "reeds2pras", "src", "ReEDS2PRAS.jl"
    ))

    #%% Run it
    main(args)

    #%%
end
