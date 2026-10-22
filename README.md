# TRPA Demographics

Tools for downloading US Census Bureau data for the Lake Tahoe Basin, grouping it into TRPA categories, adding it up to Basin, county, shore, and state totals, and checking it before publication. A web page, the Demographic Data Explorer, shows what is published, what values are present, and what each variable means.

Nothing in this repository writes to SDE or to a published service. Every step writes CSV files to the `outputs` folder. A person reviews those files and loads them by hand.

## Start here

| I want to... | Do this |
|---|---|
| See what demographic data TRPA publishes | Double-click `tools/6_open_explorer.bat` to open the [Demographic Data Explorer](explorer/index.html). See [Explorer](docs/explorer.md). |
| Add a new Census variable | Double-click `tools/1_find_census_variables.bat`, or see [Adding variables](docs/adding_variables.md) |
| Download and summarize a new year | Double-click `tools/2_download_and_summarize_year.bat`, or see [Yearly update](docs/workflow.md) |
| Change how variables are grouped | Edit `config/groupings.csv` in Excel, then run `tools/3_check_groupings.bat`. See [Groupings and medians](docs/groupings_and_medians.md) |
| Check the published data for problems | Double-click `tools/4_check_published_service.bat`, or open the Data quality tab in the Explorer |
| Fix known errors in published data | Double-click `tools/5_build_corrections.bat`, or see [Corrections](docs/corrections.md). It builds append files only. |
| Download jobs, LODES, comparison areas, 1990 data, or enrollment, or build map layers | See [Other sources and map layers](docs/other_sources.md) |
| Understand a column or a term | See the [Data dictionary](docs/data_dictionary.md) |
| Set up Python and the Census API key | See [Setup](docs/setup.md) |

## How the pieces fit

```
config/variables.csv ──> download ──> group ──> summarize ──> qaqc ──> outputs/ ──> (person reviews and loads)
                           │            │           │            │
                     Census API   groupings.csv  medians.csv   HTML report
```

1. **Download.** For each variable in `config/variables.csv`, the toolkit asks the Census API for every tract or block group in El Dorado, Placer, Douglas, and Washoe counties. It keeps only geographies inside the basin, using the Tahoe Census Geography layer.
2. **Group.** `config/groupings.csv` adds detailed variables into TRPA categories, such as Age_Under_18, BIPOC, or No Vehicle Available.
3. **Summarize.** Values are added up to the Basin, each county's basin portion, North Lake and South Lake, and California and Nevada. Medians are calculated from count bins listed in `config/medians.csv`.
4. **Check.** QAQC writes an HTML report that flags duplicates, blanks, Census annotation codes, double counting, totals that do not add up, and rows that already exist in the published table.
5. **Load.** Every step writes files for the layouts of the published tables. A person reviews them and appends them.

## Folder layout

| Folder | Contents |
|---|---|
| `config/` | Settings and the CSV lists that drive everything. Edit these, not the code. |
| `src/trpa_demographics/` | The Python package. Each file starts with a plain-language description. |
| `tools/` | Double-click batch files for people who do not use Python. |
| `explorer/` | The Demographic Data Explorer web page. |
| `docs/` | Guides and reference pages. |
| `tests/` | Automated tests. Run `python -m pytest`. |
| `outputs/` | Created when you run the tools. Not stored in Git. |

## For Python users

```
set PYTHONPATH=src
python -m trpa_demographics --help
python -m trpa_demographics run --year 2024 --compare-service
python -m trpa_demographics qaqc --config
```

Each command is described in [Yearly update](docs/workflow.md) and in `python -m trpa_demographics <command> --help`. The package needs pandas, numpy, requests, and openpyxl, which ship with the ArcGIS Pro Python environment. ArcGIS Pro (arcpy and the arcgis package) is needed only for `export-gdb`, `curated --feature-class`, and `tessellation`.

## Decisions and open questions

Decisions made so far are in [DECISIONS.md](DECISIONS.md). Questions still open are in [QUESTIONS.md](QUESTIONS.md).

## Related repositories

The original Demographics repository holds the earlier notebooks, chart outputs, and historical downloads. The [migration notes](docs/migration_from_legacy.md) list what moved here, what changed, and what was left behind.

A Census API key is now required for data downloads. See [Setup](docs/setup.md).
