"""Build append and retire files that fix known errors in the published tables.

What it does
    Reads the published tables and applies the fix rules in config/corrections/,
    such as relabeled variables, spelling fixes, dataset values, and rebuilt
    groups. For each wrong record it writes a corrected copy to an append file
    and lists the original's OBJECTID in a retire file.
    It does not change any published data. A person loads the files after review.

    Optional: it can also download the correct Census codes for every year and
    level where a wrong code was published. That needs a Census API key in .env.

What it reads
    The TRPA ArcGIS REST layers in config/settings.json, read only, and the
    rule files in config/corrections/.

What it writes
    Files under outputs/corrections/<date>/, including a README.txt that lists
    each file. Nothing is written to SDE or to any service.

How to run it
    Double-click this file, or run: python tools/5_build_corrections.py
    Same as: python -m trpa_demographics corrections [--download]

After it runs
    Read outputs/corrections/<date>/README.txt before loading anything. Check
    conflicts.csv if one is written. See docs/corrections.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trpa_demographics import launcher  # noqa: E402


def main():
    launcher.ensure_environment(__file__)
    print("Build append and retire files that fix known errors in the published tables.")
    print("This reads the services only. It does not change any data.\n")
    download = launcher.ask_yes_no("Also download the correct Census codes (needs an API key)?")

    arguments = ["corrections"] + (["--download"] if download else [])
    if launcher.run_command(arguments):
        print("\nRead outputs/corrections/<date>/README.txt before loading anything.")
    launcher.pause_before_close()


if __name__ == "__main__":
    main()
