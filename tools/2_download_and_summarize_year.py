"""Download, group, summarize, and check Census data for one or more years.

What it does
    Runs the yearly update from start to finish for each year you choose:
    1. Downloads every active variable in config/variables.csv for the
       Basin's tracts and block groups.
    2. Combines detailed variables into TRPA categories using config/groupings.csv.
    3. Adds values up to the Basin, each county, North Lake and South Lake,
       State, and Neighborhood, and calculates medians from config/medians.csv.
    4. Runs the quality checks and compares the new rows with the published
       Census Data table.

What it reads
    config/settings.json, config/variables.csv, config/groupings.csv, and
    config/medians.csv. Census data from api.census.gov, which needs a Census
    API key in .env (see docs/setup.md). The published Census Data table, read only.

What it writes
    Files under outputs/ for review: downloads, grouped and summary tables in
    the published layouts, and a QAQC report at outputs/qaqc/<label>/qaqc_report.html.
    Nothing is written to SDE or to any service.

How to run it
    Double-click this file, or run: python tools/2_download_and_summarize_year.py
    Same as: python -m trpa_demographics run --year 2024 --year-end 2024 --compare-service

After it runs
    Open the qaqc_report.html it names before loading anything. See docs/workflow.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trpa_demographics import launcher  # noqa: E402


def main():
    launcher.ensure_environment(__file__)
    print("Download, group, summarize, and check Census data for one or more years\n")
    first = launcher.ask_year("First year (for example 2024)")
    while True:
        last = launcher.ask_year("Last year (press Enter for one year only)", default=first)
        if last >= first:
            break
        print(f"  The last year must be {first} or later.")

    arguments = ["run", "--year", str(first), "--year-end", str(last), "--compare-service"]
    if launcher.run_command(arguments):
        print("\nResults are in the outputs folder. Open the qaqc_report.html named above first.")
    launcher.pause_before_close()


if __name__ == "__main__":
    main()
