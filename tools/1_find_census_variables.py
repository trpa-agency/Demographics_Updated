"""Find Census variables and add them to config/variables.csv.

What it does
    Looks up every variable in one Census table, such as B25003 (Tenure), and
    writes draft rows for config/variables.csv. Each row gets the TRPA
    category you type. You choose whether the rows are added to
    config/variables.csv right away or only saved for review.

What it reads
    The Census Bureau's variable list for the year you type, from
    api.census.gov. No API key is needed for this step.

What it writes
    outputs/variable_search/search_<table>.csv, always.
    New rows at the bottom of config/variables.csv, only when you answer Y.
    Rows already in variables.csv are not added twice.
    Nothing is written to SDE or to any service.

How to run it
    Double-click this file, or run: python tools/1_find_census_variables.py
    Same as: python -m trpa_demographics find --table B25003 --year 2023 --category "Housing Units" [--add]

After it runs
    Open config/variables.csv in Excel and review the new rows. Shorten names
    and set active to N for anything you do not need. See docs/adding_variables.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trpa_demographics import launcher  # noqa: E402


def main():
    launcher.ensure_environment(__file__)
    print("Find Census variables and add them to config/variables.csv\n")
    table = launcher.ask("Census table code (for example B25003)").upper()
    year = launcher.ask_year("Data year to look up (for example 2023)")
    category = launcher.ask("TRPA category name for these variables (for example Housing Units)")
    add = launcher.ask_yes_no("Add them to config/variables.csv now?")

    arguments = ["find", "--table", table, "--year", str(year), "--category", category]
    if add:
        arguments.append("--add")
    if launcher.run_command(arguments):
        print("\nOpen config/variables.csv in Excel to review names before downloading.")
    launcher.pause_before_close()


if __name__ == "__main__":
    main()
