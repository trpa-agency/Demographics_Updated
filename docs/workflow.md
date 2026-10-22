# Yearly update

The Census Bureau usually releases new ACS 5-year estimates in December. Use these steps each time a new year is out.

## Quick version

Double-click `tools/2_download_and_summarize_year.bat`, type the year, and press Enter twice. When it finishes, open the QAQC report it names.

## Step by step

All commands run from the repository folder with `PYTHONPATH=src` set (see [Setup](setup.md)).

### 1. Check the variable list

Open `config/variables.csv` in Excel. Rows with `active` set to `Y` are downloaded, for the years their `years` column allows. Add new variables with the find tool (see [Adding variables](adding_variables.md)).

### 2. Download

```
python -m trpa_demographics download --year 2024
```

Options:

| Option | Use |
|---|---|
| `--year-end 2024` | Download every year from `--year` through this year |
| `--dataset dec/dhc` | Only one dataset |
| `--category "Housing Units" Race` | Only some categories |
| `--label housing` | Add a word to the output file name |

Output in `outputs/downloads/2024/`:

| File | Contents |
|---|---|
| `census_data_2024.csv` | One row per basin tract or block group, variable, and year, in the Census Data layout |
| `annotations_2024.csv` | Values the Census Bureau replaced with annotation codes such as -666666666. These are blank in the data file. |
| `unknown_variables_2024.csv` | Codes the API did not recognize for that year |
| `_checkpoints/` | One file per request. If the connection drops, run the same command again and finished requests are skipped. Delete the folder to force a fresh download. |

### 3. Group

```
python -m trpa_demographics group --input outputs/downloads/2024/census_data_2024.csv
```

Writes `outputs/grouped/grouped_census_data_2024.csv`. If a member value is blank for some geography, the other members are still added and the geography is listed in a file ending in `_partial.csv`. A blank can be real: the Census Bureau publishes nothing for some empty areas.

### 4. Summarize

```
python -m trpa_demographics summarize --input outputs/downloads/2024/census_data_2024.csv outputs/grouped/grouped_census_data_2024.csv
```

Writes `outputs/summaries/summary_census_data_2024_and_1_more.csv` in the Climate Resilience Dashboard layout, plus:

* `_demographic_summaries.csv`: the same values in the Demographic Summaries (layer 18) layout, so both tables stay in sync. Layer 18 has no sample level field, so only the level in `demographic_summaries_layout` (tract) is written. The variable name and any partial flag go in Notes.
* `_margins_of_error.csv`: the summary with a MarginOfError column. The dashboard table has no field for it.
* `_skipped.csv`: medians, averages, and percentages left out because they cannot be added
* `_partial.csv`: summary values that add up only the tracts or block groups that had values
* `_median_notes.csv`: medians that fell in the open-ended top bin, or whose margin of error could not be calculated

Summaries are built from tracts and from block groups separately; both are kept. Use `--levels Basin County` to build only some levels.

### 5. Check

```
python -m trpa_demographics qaqc --input outputs/downloads/2024/census_data_2024.csv --summary outputs/summaries/summary_census_data_2024_and_1_more.csv --compare-service
```

Open `outputs/qaqc/<name>/qaqc_report.html`. Fix every check marked fail before publishing. See [QAQC checks](qaqc.md) for what each one means.

`--compare-service` reads the published Census Data table and lists rows that already exist there, which would become duplicates if appended.

### 6. Load (manual)

The toolkit stops here on purpose. A staff member reviews the files and loads them. To make a file geodatabase table for loading in ArcGIS Pro:

```
python -m trpa_demographics export-gdb --input outputs/downloads/2024/census_data_2024.csv --gdb C:\GIS\Scratch.gdb --table census_data_2024
```

`export-gdb` refuses `.sde` paths.

## All in one

`run` performs steps 2 through 5 for each year:

```
python -m trpa_demographics run --year 2024 --compare-service
```

## Fixing published errors

See [Corrections](corrections.md).

## Checking the published service

```
python -m trpa_demographics inventory --registry-year 2024
python -m trpa_demographics qaqc --service --service-year 2024
```

`inventory` writes what is published to `outputs/inventory/`. With `--registry-year`, it also writes a list in the `config/variables.csv` format, which is a quick way to bring every published variable into the download list.
