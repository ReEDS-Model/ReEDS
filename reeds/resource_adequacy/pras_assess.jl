#%%
"""
Shared PRAS assessment / results-writing logic used by both run_pras.jl
(assess a single ReEDS-derived .pras system) and run_pras_cross_load.jl
(assess a system built from one case's generation/transmission fleet paired
with another case's regional load timeseries).

Callers must have already run `import PRAS`, `import DataFrames`, and
`import HDF5`, and defined `const DF = DataFrames`, before `include`-ing
this file.
"""
function assess_and_write(sys::PRAS.SystemModel, args::Dict, outfile::String)
    #%% Specify the results to save
    resultspec = Dict{String,Any}("short" => PRAS.Shortfall())
    if args["write_flow"] == 1
        resultspec["flow"] = PRAS.Flow()
    end
    if args["write_surplus"] == 1
        resultspec["surplus"] = PRAS.Surplus()
    end
    if args["write_energy"] == 1
        resultspec["energy"] = PRAS.StorageEnergy()
    end
    if args["write_shortfall_samples"] == 1
        resultspec["short_samples"] = PRAS.ShortfallSamples()
    end
    if args["write_availability_samples"] == 1
        resultspec["avail_gen"] = PRAS.GeneratorAvailability()
        resultspec["avail_stor"] = PRAS.StorageAvailability()
        resultspec["avail_genstor"] = PRAS.GeneratorStorageAvailability()
        resultspec["energy_samples"] = PRAS.StorageEnergySamples()
    end

    #%% Run PRAS
    if args["pras_seed"] > 0
        method = PRAS.SequentialMonteCarlo(
            samples=args["samples"], threaded=true, verbose=true, seed=args["pras_seed"])
    else
        method = PRAS.SequentialMonteCarlo(
            samples=args["samples"], threaded=true, verbose=true)
    end
    results_tuple = PRAS.assess(sys, method, values(resultspec)...)
    results = Dict{String,Any}(zip(keys(resultspec), results_tuple))

    #%% Print some results for the entire modeled region to show it worked
    @info "$(PRAS.LOLE(results["short"]))"
    @info "$(PRAS.EUE(results["short"]))"
    @info "$(PRAS.NEUE(results["short"]))"

    ## Filter out DC regions used for VSC HVDC transmission
    regions = [r for r in sys.regions.names if !(occursin("|", r))]

    #%% Print some more detailed results if debugging
    for (i, reg) in enumerate(regions)
        @debug "$reg: $(round(PRAS.LOLE(results["short"],reg).lole.estimate)) event-h"
        @debug "$reg: $(round(PRAS.EUE(results["short"],reg).eue.estimate)) MWh"
        @debug "$reg: NEUE = $(round(
            1e6 * PRAS.EUE(results["short"],reg).eue.estimate
            / sum(sys.regions.load[i,:])
        )) ppm\n\n"
    end

    #%% Record the EUE and LOLE outputs by region and timestep
    ## Units are:
    ## * LOLE: event-h
    ## * EUE: MWh
    ## First for the whole modeled area (labeled as "USA" but if modeling a smaller
    ## region (specified by GSw_Region) it will be for that modeled region)
    dfout = DF.DataFrame(
        USA_LOLE=[PRAS.LOLE(results["short"],h).lole.estimate for h in sys.timestamps],
        USA_EUE=[PRAS.EUE(results["short"],h).eue.estimate for h in sys.timestamps],
    )
    ## Now for each constituent region
    for (i,r) in enumerate(regions)
        dfout[!, "$(r)_LOLE"] = [PRAS.LOLE(results["short"],r,h).lole.estimate for h in sys.timestamps]
        dfout[!, "$(r)_EUE"] = [PRAS.EUE(results["short"],r,h).eue.estimate for h in sys.timestamps]
    end

    #%% Write it
    HDF5.h5open(outfile, "w") do f
        for column in DF.names(dfout)
            f[column, compress=4] = convert(Array, dfout[!, column])
        end
    end
    @info("Wrote PRAS EUE and LOLE to $(outfile)")

    #%%### Record more operational details if desired

    ### Flow
    if args["write_flow"] == 1
        dfflow = DF.DataFrame()
        for i in results["flow"].interfaces
            ## Flow results are tuples of (mean, standard deviation). Keep the mean.
            dfflow[!, "$(i)"] = [results["flow"][i,h][1] for h in sys.timestamps]
        end
        ## Write it
        flowfile = replace(outfile, ".h5"=>"-flow.h5")
        HDF5.h5open(flowfile, "w") do f
            for column in DF._names(dfflow)
                f["$column", compress=4] = convert(Array, dfflow[!, column])
            end
        end
        @info("Wrote PRAS flow to $(flowfile)")
    end

    ### Surplus
    if args["write_surplus"] == 1
        dfsurplus = DF.DataFrame()
        for r in regions
            ## Surplus results are tuples of (mean, standard deviation). Keep the mean.
            dfsurplus[!, "$(r)"] = [results["surplus"][r,h][1] for h in sys.timestamps]
        end
        ## Write it
        surplusfile = replace(outfile, ".h5"=>"-surplus.h5")
        HDF5.h5open(surplusfile, "w") do f
            for column in DF._names(dfsurplus)
                f["$column", compress=4] = convert(Array, dfsurplus[!, column])
            end
        end
        @info("Wrote PRAS surplus to $(surplusfile)")
    end
    ### Storage energy
    if args["write_energy"] == 1
        dfenergy = DF.DataFrame()
        for i in sys.storages.names
            ## Energy results are tuples of (mean, standard deviation). Keep the mean.
            dfenergy[!, strip("$(i)", '_')] = [results["energy"][i,h][1] for h in sys.timestamps]
        end
        ## Write it
        energyfile = replace(outfile, ".h5"=>"-energy.h5")
        HDF5.h5open(energyfile, "w") do f
            for column in DF._names(dfenergy)
                f["$column", compress=4] = convert(Array, dfenergy[!, column])
            end
        end
        @info("Wrote PRAS storage energy to $(energyfile)")
    end

    ### Sample-level shortfall
    if args["write_shortfall_samples"] == 1
        dictshort = Dict(s => DF.DataFrame() for s = 1:args["samples"])
        for s in range(1, args["samples"])
            dictshort[s] = DF.DataFrame(
                transpose(getindex.(results["short_samples"][:, :], s)),
                sys.regions.names
            )
            # subset to regions (filter out DC regions)
            dictshort[s] = dictshort[s][:,findall(regions .∈ Ref(sys.regions.names))]
        end
        ## Write it
        shortfile = replace(outfile, ".h5"=>"-shortfall_samples.h5")
        HDF5.h5open(shortfile, "w") do f
            ## Create a group for each sample. Within each group, write an array for each region.
            for s in range(1, args["samples"])
                HDF5.create_group(f, "$s")
                for column in DF._names(dictshort[s])
                    f["$s"]["$column", compress=4] = convert(Array, dictshort[s][!, column])
                end
            end
        end
        @info("Wrote PRAS shortfall by sample to $(shortfile)")
    end

    ### Sample-level generator and storage availability
    if args["write_availability_samples"] == 1
        dictavail = Dict(s => DF.DataFrame() for s = 1:args["samples"])
        for s in range(1, args["samples"])
            dictavail[s] = hcat(
                DF.DataFrame(
                    transpose(getindex.(results["avail_gen"][:, :], s)),
                    strip.(results["avail_gen"].generators, '_')
                ),
                DF.DataFrame(
                    transpose(getindex.(results["avail_stor"][:, :], s)),
                    strip.(results["avail_stor"].storages, '_')
                ),
                DF.DataFrame(
                    transpose(getindex.(results["avail_genstor"][:, :], s)),
                    strip.(results["avail_genstor"].generatorstorages, '_')
                ),
            )
        end
        ## Write it
        availabilityfile = replace(outfile, ".h5"=>"-avail.h5")
        HDF5.h5open(availabilityfile, "w") do f
            ## Create a group for each sample. Within each group, write an array for each unit.
            for s in range(1, args["samples"])
                HDF5.create_group(f, "$s")
                for column in DF._names(dictavail[s])
                    f["$s"]["$column", compress=4] = convert(Array, dictavail[s][!, column])
                end
            end
        end
        @info("Wrote PRAS unit availability to $(availabilityfile)")
        ### Same for storage energy by sample
        dictstoravail = Dict(s => DF.DataFrame() for s = 1:args["samples"])
        for s in range(1, args["samples"])
            dictstoravail[s] = DF.DataFrame(
                transpose(getindex.(results["energy_samples"][:, :], s)),
                strip.(results["energy_samples"].storages, '_')
            )
        end
        ## Write it
        energysamplesfile = replace(outfile, ".h5"=>"-energy_samples.h5")
        HDF5.h5open(energysamplesfile, "w") do f
            for s in range(1, args["samples"])
                HDF5.create_group(f, "$s")
                for column in DF._names(dictstoravail[s])
                    f["$s"]["$column", compress=4] = convert(Array, dictstoravail[s][!, column])
                end
            end
        end
        @info("Wrote PRAS storage energy by sample to $(energysamplesfile)")
    end

    #%%
    return dfout
end
