"""Check config/groupings.csv for double counting and missing variables.

What it does
    Reads the grouping list and checks it against config/variables.csv and the
    Census Bureau's table definitions. It flags:
    * groups that count the same people twice, such as a subtotal added
      together with its own parts
    * a variable used in two groups of the same set
    * group members missing from config/variables.csv
    * medians, averages, or percentages added into a group

What it reads
    config/groupings.csv, config/variables.csv, and Census table definitions
    from api.census.gov. No API key is needed for this step.

What it writes
    A report at outputs/qaqc/groupings/qaqc_report.html, a summary CSV, and one
    CSV for each check that found something. Nothing else is changed.

How to run it
    Double-click this file, or run: python tools/3_check_groupings.py
    Same as: python -m trpa_demographics qaqc --config --label groupings

After it runs
    Open outputs/qaqc/groupings/qaqc_report.html. Fix flagged rows in
    config/groupings.csv and run this again. See docs/groupings_and_medians.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trpa_demographics import launcher  # noqa: E402


def main():
    launcher.ensure_environment(__file__)
    print("Check config/groupings.csv for double counting and missing variables")
    if launcher.run_command(["qaqc", "--config", "--label", "groupings"]):
        print("\nOpen outputs/qaqc/groupings/qaqc_report.html to see the results.")
    launcher.pause_before_close()


if __name__ == "__main__":
    main()
