# Other sources and map layers

These commands were ported from notebooks in the original repository. Each writes files under `outputs/` for review. None writes to SDE.

## Comparison geographies

Whole counties (El Dorado, Placer, Douglas, Washoe, and Carson City), California, Nevada, the Reno-Sparks and Sacramento metro areas, and the San Francisco Bay Area combined statistical area. The list and Census API geography codes are in `comparison_geographies` in `config/settings.json`.

```
python -m trpa_demographics comparison --year 2023 --category Population "Housing Units"
```

Output uses the summary layout with Geography set to the comparison name and sample_level set to county, state, MSA, or CSA. Metro area codes are the 2003 and later definitions, so years before 2003 are skipped.

## Jobs by ZIP code (County Business Patterns)

Employees, establishments, first quarter payroll, and annual payroll for each ZIP code in `config/jobs_zip_codes.csv`. The variables and their flag fields are in `config/jobs_variables.csv`. From 2018 the data comes from the cbp dataset. Earlier years come from ZIP Code Business Patterns (zbp).

```
python -m trpa_demographics jobs --year 2024
python -m trpa_demographics jobs --year 1998 --year-end 2017 --replace-published
```

Writes to `outputs/jobs/`:

* `census_jobs_<years>_append.csv` in the Census_Jobs layout (Demographics MapServer/35)
* `census_jobs_<years>_summary.csv` with Basin, North Lake, and South Lake totals. `withheld_zip_codes` counts ZIP codes left out of a total.

With `--replace-published`, it also writes:

* `census_jobs_<years>_retire.csv`, the OBJECTIDs of every published row in those years
* `census_jobs_<years>_comparison.csv`, published and downloaded values side by side, with the difference and percent difference

How it works:

* Variable names and flags change between years. Before each year the command reads that year's variable list from the Census API, which needs no key. It requests only what the year publishes.
* A ZIP code request can return one row per industry or size class. The command keeps the all-industries, all-sizes row, using the codes in `jobs.total_codes` in settings. It stops with a message if it cannot find exactly one.
* Before 2017, the Census Bureau withheld some ZIP code values to protect businesses. It published 0 with a letter for the size range. The command leaves these values blank and puts `D` in value_flag. The letter is in the downloaded file but not in the published layout.
* The `years` column in `config/jobs_zip_codes.csv` limits a ZIP code to some years. The four South Lake Tahoe PO box ZIP codes (96152, 96154, 96156, and 96157) are used through 2017, as in the published 1998 to 2017 values.

Replacing 1998 to 2017: the published values for those years came from a hand-built workbook with Total Employees only. The replacement adds all four variables. Steps:

1. Run the second command above. It needs a Census API key.
2. Open the comparison file. Look at rows with large differences and at rows marked published only or downloaded only.
3. Load the append file, then retire the listed OBJECTIDs, following the steps in [Corrections](corrections.md).

The 2017 zbp dataset uses a newer layout without suppression flags. The command handles both [Likely]. It was tested on made-up responses only. Check the 2017 rows in the comparison file.

## LODES commute flows and workplace jobs

```
python -m trpa_demographics lodes --year 2023
```

Downloads the California and Nevada LODES 8 origin-destination files (main and aux, primary jobs JT01) and workplace area files, keeps basin flows, labels each flow, and adds tract and block TRPAIDs and centroids. Centroids come from Census TIGERweb 2020 tracts and blocks. Writes:

* `lodes_origin_destination_<year>_append.csv` in the layout of Climate Resilience MapServer/141
* `lodes_work_locations_<year>_append.csv` in the layout of MapServer/142
* `home_locations_<year>.csv` and `work_locations_<year>.csv`, points for mapping
* a QAQC report with the checks from the original notebook: inputs loaded, one LODES release, year not already published, no duplicate pairs, centroids present, only known boundary tracts unmatched, total jobs in range, and each category within 15 percent of the year before

The original notebook used tract centroids from an Esri living atlas layer and computed block centroids from TRPA shapes. TIGERweb centroids can differ slightly. Settings are in `lodes` in `config/settings.json`.

## Curated map layers

Wide tables with one row per tract or block group and year, one column per variable:

```
python -m trpa_demographics curated --layer tahoe_census_curated --year 2013 --year-end 2024
python -m trpa_demographics curated --layer tdc_values --year 2024 --feature-class C:\GIS\Scratch.gdb\TDC_2024
```

Columns and their sources are in `config/curated_layers.csv`. `tahoe_census_curated` matches Demographics MapServer/3 and fills Other Vacant from B25004_008E. `tdc_values` matches the TDC block group layers. Without `--input`, published Census Data is read. `--feature-class` joins the basin shapes and writes a file geodatabase feature class with field aliases (ArcGIS Pro only).

## Hexagon grid (tessellation)

```
python -m trpa_demographics tessellation --year 2012 --year-end 2024
```

Spreads block group values onto the hexagon grid using parcels. See the description at the top of `src/trpa_demographics/tessellation.py`. Needs ArcGIS Pro. Reads parcels and hexagons from the SDE paths in `tessellation` in `config/settings.json` (read only) and writes two feature classes to the file geodatabase there: every hexagon and year with rates and top quartile flags, and the 2020 and later hexagons in the Tahoe Census Curated layout (sample_level Hex Grid). Variables are in `config/tessellation_variables.csv`.

## 1990 Census

The Census API does not serve 1990 data.

```
python -m trpa_demographics import-1990 --folder "C:\path\to\1990_Tables"
```

Reads the STF3 DBF files (no extra packages needed), keeps basin tracts, and writes `outputs/downloads/1990/census_data_1990.csv` for the variables in `config/variables.csv` with dataset dec/sf3 and years 1990. Then run `group` to build the 1990 age groups.

## School enrollment

```
python -m trpa_demographics enrollment --year 2023 --year-end 2025
```

`--year` is the fall year a school year starts. 2023 means 2023-2024.

Builds one row per school and school year in the School Enrollment layout (Demographics MapServer/32). The schools and their state codes are in `config/school_enrollment_schools.csv`. Add a school there. Download addresses are in `school_enrollment` in `config/settings.json`. Add each new year's file there.

Writes to `outputs/enrollment/`:

* `school_enrollment_<years>_review.csv`, every school and year, with the state code and a note
* `school_enrollment_<years>_comparison.csv`, built and published values side by side
* `school_enrollment_<years>_append.csv`, only school years not yet published

Sources:

| State | Source | Years | How the total is found |
|---|---|---|---|
| California | CDE Enrollment by School files | 1998-99 to 2022-23 | Adds up the rows for each school (one per race or ethnicity and gender). From 2014 the files mark primary (P) or combined (C) enrollment. `california_enrollment_type` in settings picks one (default C, which matches DataQuest from 2020-21). District totals add up the district's schools. |
| California | CDE Census Day Enrollment files | 2023-24 on | Uses the school and district rows with reporting category TA (total). District rows use Charter = All. |
| Nevada | NDE Validation Day student counts | 2015-16 on | Finds a sheet with a school code and a total column. If only grade rows exist, adds up the grades. |

Checks done so far:

* Nevada: the reader gave the published value for every school in every year from 2015-16 to 2022-23 [Certain: checked against the published table on Oct. 22, 2026].
* California: CDE blocks automated downloads from this workspace, so the reader was tested on made-up files only [Likely]. Run the command for a published year, such as `--year 2022`, and check the comparison file before appending new years.

Limits:

* Nevada years before 2015-16 came from the Nevada Report Card site, which has no download. Those rows stay as published.
* A school listed without a code, such as the closed Kingsbury Middle School, is reported as 0. That matches the published table.
* Cells the state suppressed (marked *) are left out. The review file notes how many.
* Lake Tahoe Unified is published as one district total, so it stays one row. Its schools can be added to `config/school_enrollment_schools.csv` with aggregate set to school.

## Inflation adjustment

```
python -m trpa_demographics inflate --input outputs/summaries/summary_x.csv --codes B19013_001E --to-year 2024
```

Converts dollar values to one year's dollars with the annual average R-CPI-U-RS index in `config/inflation_adjustments.csv`. A value from year Y becomes target-year dollars as value times index[target] divided by index[Y]. The default target is `inflation.base_year` in settings (2021).

The index runs from 1990 and 2000 through 2025. The values come from the Bureau of Labor Statistics R-CPI-U-RS file (link in `inflation.source_url`). Add a row each spring when BLS publishes the year before.

Two notes:

* The 2025 value averages 11 months. BLS did not publish October 2025.
* The table used to store factors to 2021 dollars, computed from index values rounded to one decimal. Current BLS values change those factors in the fourth or fifth decimal place. For example, 2010 to 2021 was 1.24828 and is now 1.24820.
