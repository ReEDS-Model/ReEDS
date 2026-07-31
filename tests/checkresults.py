"""
Given a reedspath and batchname, this script will run the following tests for each run with the given batch name:
test_r2x_integration.py
test_outputs.py

Example command to run: python checkresults.py /Users/kminderm/ReEDS-2.0 2_20_2024
"""

import os
import sys
import argparse
import subprocess


def run_tests(reedspath, run_dir):
    """
    Run tests to check outputs and r2x integration for a given run
    """
    print(f"Running tests for {run_dir} ...")
    try:
        result = subprocess.run(
            [
                "python",
                "-m",
                "pytest",
                "-v",
                "-l",
                os.path.join(reedspath, "tests", "test_outputs.py"),
                "--casepath",
                f"{run_dir}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Tests failed in {run_dir}.\nOutput:\n{e.output}\nError:\n{e.stderr}")


def check_gamslog(run_dir):
    """
    Check for gamslog.txt in a given run folder and print lines that have an error
    """
    gamslog_path = os.path.join(run_dir, "gamslog.txt")
    if os.path.exists(gamslog_path):
        with open(gamslog_path, "r") as file:
            data = file.readlines()
            for line in data:
                if "error" in line or "ERROR" in line:
                    print(line)

    else:
        print(f"\ngamslog.txt not found in {run_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Run tests for each run starting with a specific batch name."
    )
    parser.add_argument("reedspath", help="Path to the ReEDS-2.0 folder")
    parser.add_argument("batchname", help="Batch name for runs")
    args = parser.parse_args()

    reedspath = args.reedspath
    batchname = args.batchname

    folder_path = os.path.join(reedspath, "runs")

    if not os.path.isdir(folder_path):
        print(
            f"Error: The folder '{folder_path}' does not exist or is not a directory."
        )
        sys.exit(1)

    # Find all directories that start with the given batch name.
    run_dirs = [
        os.path.join(folder_path, d)
        for d in os.listdir(folder_path)
        if os.path.isdir(os.path.join(folder_path, d)) and d.startswith(batchname)
    ]

    if not run_dirs:
        print(f"No runs found in '{folder_path}' with batchname '{batchname}'.")
        sys.exit(1)

    for run_dir in run_dirs:
        print("\n========================================")
        print(f"Checking: {run_dir}")
        run_tests(reedspath, run_dir)
        #check_gamslog(run_dir)
        input(
            "Press Enter to continue to the next run..."
        )  # Wait for user input before continuing


if __name__ == "__main__":
    main()
