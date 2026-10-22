# Migration from the original repository

This repository replaces the processing code in the original `Demographics` repository and the first draft that was here before (`Utils.py`, `Data_Processing.ipynb`, `Lookup_Lists/`, and output CSVs). The original repository was not changed.

## Where things went

| Original | Now | What changed |
|---|---|---|
| `utils.py` `get_variable_data`, `census_download_wrapper_checkpointed` | `census_api.download_year` | Requests up to 24 variables per call instead of one, so a year takes about one twentieth of the calls. Checkpoints per request. Bad codes are retried one at a time and listed instead of stopping the run. |
| `utils.py` `backfill_acs_data`, `get_existing_variables` | `inventory` command, `--registry-year` | The published table is summarized on the server instead of downloaded in full |
| `utils.py` `get_tahoe_geometry` | `geography.get_tahoe_geometry` | Uses plain HTTP instead of the arcgis package. Reads TRPAID, not the GEOID field, which is stored as a number and has lost leading zeros. |
| `utils.py` `make_session` | `services.make_session` | Same retry rules |
| `utils.py` `get_fs_data`, `get_fs_as_df`, `Census_Summaries.ipynb` `get_rest_service_data` | `services.query_layer` | One function. Pages through results. |
| `utils.py` and `summary_functions.py` `categorize_values` (three versions) | `grouping.apply_groupings` | One version. Combines margins of error instead of leaving them blank. Leaves a group blank when a member is missing. |
| `sum_across_levels`, `sum_across_levels_moe`, `sum_multiple_variables` | `summarize.summarize` | One pass for all variables. Skips medians and averages. Combines margins of error. |
| `calculate_median_value`, `median_across_levels`, `calculate_median_value_with_moe` | `summarize.compute_medians` | Bin edges come from `config/medians.csv` instead of parsing labels. Fixes two problems: the running total was not reset between geographies, and a median in the top bin returned infinity. |
| `df_to_gdb_table` | `gdb.to_file_gdb` | Refuses `.sde` paths. Will not overwrite without `overwrite=True`. |
| `Census_Category_Lists/*.csv`, `Lookup_Lists/Overall_Grouping_List.csv` | `config/groupings.csv` | One file with a consistent layout |
| `variable_config.csv`, `general_variables.csv`, `Census_Download.ipynb` variable lists | `config/variables.csv` | One list with aggregation rules and notes |
| Hardcoded service URLs, county lists, and API key | `config/settings.json`, `.env` | The API key is no longer in code |
| `Census_Summaries.ipynb` duplicate flagging (writes `delete_flag` in SDE) | `qaqc --service` | Reports duplicates only. Does not edit SDE. |
| `Census_Summaries.ipynb` pivot to feature class | `curated` command | Columns come from `config/curated_layers.csv` instead of a variable list and name sanitizing. Other Vacant uses B25004_008E. |
| `Census_Summaries.ipynb` hexbin tessellation and adjustment factors | `tessellation` command | Same steps. Rates use the data year only (the notebook used that year and later). The math is tested without ArcGIS. |
| `get_non_tahoe_data` (MSAs, CSA, full counties, states) | `comparison` command | Finished: the old function never returned its data. Geographies are in settings. |
| `CBP_download.ipynb` | `jobs` command | Uses cbp for 2018 and later and zbp before. Reads each year's variable list first. Output matches the Census_Jobs table. `--replace-published` builds files to swap the 1998 to 2017 workbook values for downloads. |
| `scripts/LODES_Download.ipynb` | `lodes` command | Downloads the files itself, uses TIGERweb centroids, writes append files and a QAQC report instead of an InsertCursor into SDE. |
| `scripts/misc/Import_1990_Data.ipynb` | `import-1990` command | Reads DBF files without the dbfread package. Variables come from `config/variables.csv`. |
| `scripts/misc/School_Enrollment_Download.ipynb` | `enrollment` command | Reads individual schools from the California and Nevada state download files instead of the DataQuest page. Covers Nevada from 2015-16. |
| `scripts/misc/inflation_adjustments.csv` | `inflate` command, `config/inflation_adjustments.csv` | Stores the BLS index instead of factors, so it converts to any year. Extended through 2025. |
| `scripts/misc/tdc_make_layer.ipynb` | `curated --layer tdc_values` | Same columns, from groupings instead of TDC_categories.csv |

## Left behind

| Item | Why |
|---|---|
| `DemographicDataVisualizations.ipynb`, chart HTML outputs | Charts are in the Explorer and the Climate Resilience Dashboard |
| `scripts/misc/Demographics_CreateLayers.ipynb` | One-time 2010 to 2020 block change layer with a database password in the code. Rebuild with `curated` if needed. |
| Visitation and water use tables (MapServer/33, 34) | Not Census data; no download code existed |
