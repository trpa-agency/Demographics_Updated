"""List and check what is published in the Census Data service. Read only.

What it does
    Runs two read-only steps against TRPA's published tables:
    1. Inventory: lists every variable, year, and geography level published.
    2. Quality checks: looks for duplicate records, one variable code
       published under more than one name, and negative values. Negative
       values are Census annotation codes stored as data.

What it reads
    The TRPA ArcGIS REST layers listed under services in config/settings.json.
    It only reads them.

What it writes
    An inventory under outputs/inventory/ and a report at
    outputs/qaqc/published_service/qaqc_report.html.
    Nothing is written to SDE or to any service.

How to run it
    Double-click this file, or run: python tools/4_check_published_service.py
    Same as running these two commands:
        python -m trpa_demographics inventory
        python -m trpa_demographics qaqc --service --label published_service

After it runs
    Open outputs/qaqc/published_service/qaqc_report.html. The Explorer's Data
    quality tab shows the same kinds of checks in a browser.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trpa_demographics import launcher  # noqa: E402


def main():
    launcher.ensure_environment(__file__)
    print("List and check what is published in the Census Data service (read only)")
    inventory_ok = launcher.run_command(["inventory"])
    checks_ok = launcher.run_command(["qaqc", "--service", "--label", "published_service"])
    if inventory_ok and checks_ok:
        print("\nOpen outputs/qaqc/published_service/qaqc_report.html to see the results.")
    else:
        print("\nOne step stopped with an error. Read the messages above.")
    launcher.pause_before_close()


if __name__ == "__main__":
    main()
