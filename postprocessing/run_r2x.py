#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "r2x-reeds>=0.3.5",
# ]
# ///

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger
from r2x_core import DataStore, PluginContext
from r2x_core.logger import setup_logging
from r2x_reeds import ReEDSConfig, ReEDSParser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run R2X translation for a ReEDS case.")
    parser.add_argument("--reeds-run-path", required=True, type=Path)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--solve-year", required=True, type=int)
    parser.add_argument("--weather-year", required=True, type=int)
    parser.add_argument("--system-json", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_path = args.reeds_run_path.expanduser().resolve()

    setup_logging()

    config = ReEDSConfig(
        weather_year=args.weather_year,
        solve_year=args.solve_year,
        scenario=args.scenario,
    )

    store = DataStore.from_plugin_config(config, path=run_path)
    ctx = PluginContext(config=config, store=store)
    parser = ReEDSParser.from_context(ctx)
    result_ctx = parser.run()

    system_json = args.system_json.expanduser().resolve()
    result_ctx.system.to_json(system_json)
    logger.info("Built R2X system for scenario '{}' at '{}'", args.scenario, system_json)


if __name__ == "__main__":
    main()
