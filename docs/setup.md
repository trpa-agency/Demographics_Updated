# Setup

## Python

Use the ArcGIS Pro Python environment (`arcgispro-py3`) or any clone of it. It already includes pandas, numpy, requests, and openpyxl, which is all the toolkit needs.

The batch files in `tools/` find ArcGIS Pro's Python automatically through `propy.bat`. To use a different environment, set `TRPA_PYTHON` to the full path of its `python.exe` before running a batch file:

```
set TRPA_PYTHON=C:\Users\you\AppData\Local\ESRI\conda\envs\arcgispro-py3-clone\python.exe
```

To run commands yourself, open the ArcGIS Pro Python Command Prompt in the repository folder and point Python at the source folder:

```
set PYTHONPATH=src
python -m trpa_demographics --help
```

Or install the package once in your environment:

```
pip install -e .
```

## Census API key

The Census API refuses data requests without a key (checked October 2026). Variable definitions, which the find command and the Explorer read, still work without one.

1. Request a free key at https://api.census.gov/data/key_signup.html.
2. Copy `.env.example` to `.env` in the repository folder.
3. Paste the key after `CENSUS_API_KEY=`.

`.env` is listed in `.gitignore`, so the key never goes to GitHub. You can also set `CENSUS_API_KEY` as a Windows environment variable instead.

Never paste the key into a notebook, script, or config file.

## Settings

`config/settings.json` holds every value the code would otherwise hardcode:

| Setting | What it controls |
|---|---|
| `census_api` | API address, the environment variable that holds the key, batch size, pause between requests, and timeout |
| `services` | TRPA ArcGIS REST layers the toolkit reads |
| `counties` | Counties to download, with the county, state, and North/South labels used in summaries |
| `geometry_vintages` | Which Census boundary year each data year uses |
| `valid_datasets` | Census dataset names. The corrections step resets prefixed dataset values to one of these. |
| `summary_levels` | Geographies built by the summarize step, including Neighborhood |
| `demographic_summaries_layout` | Which sample level is written in the Demographic Summaries (layer 18) layout |
| `medians` | Constants for median margins of error |
| `comparison_geographies`, `jobs`, `lodes`, `school_enrollment`, `inflation`, `tessellation` | Settings for the commands in [Other sources](other_sources.md) |
| `grouped_code_max_length` | Length limit for grouped variable codes, matching the 255 character text field |
| `qaqc` | Thresholds for reliability, year-over-year change, and tract versus block group totals |
| `outputs_folder` | Where results are written |

## Tests

```
set PYTHONPATH=src
python -m pytest
```

The tests use small made-up tables and a fake Census API, so they run offline in about one second. They were run on Python 3.9 with pandas 1.4 and on Python 3.13 with pandas 3.0. `tests/test_no_secrets.py` fails if any file holds something that looks like a password, connection string, or API key.
