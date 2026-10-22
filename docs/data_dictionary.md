# Data dictionary

## Services the toolkit and the Explorer read

| Layer | What it is |
|---|---|
| [Demographics/MapServer/27](https://maps.trpa.org/server/rest/services/Demographics/MapServer/27) Tahoe Census Geography | Every tract, block group, and block inside the basin for 1990, 2000, 2010, and 2020 boundaries. The list that decides what counts as "in the basin". |
| [Demographics/MapServer/28](https://maps.trpa.org/server/rest/services/Demographics/MapServer/28) Census Data | Raw and grouped values by tract and block group. The download and group steps produce rows in this layout. |
| [Demographics/MapServer/18](https://maps.trpa.org/server/rest/services/Demographics/MapServer/18) Demographic Summaries | Older summary table: Category, Code, Value, Year, Source, Notes, Geography. |
| [LTinfo_Climate_Resilience_Dashboard/MapServer/135](https://maps.trpa.org/server/rest/services/LTinfo_Climate_Resilience_Dashboard/MapServer/135) Census Data | Summaries read by the Climate Resilience Dashboard. The summarize step produces rows in this layout. |
| [Demographics/MapServer/3](https://maps.trpa.org/server/rest/services/Demographics/MapServer/3) Tahoe Census Curated | One polygon per tract, block group, or hexagon and year, with selected variables as columns. Built by the `curated` and `tessellation` commands. |
| [Demographics/MapServer/2](https://maps.trpa.org/server/rest/services/Demographics/MapServer/2) Demographics_Tessellation | Hexagon grid with parcel-based estimates. Built by the `tessellation` command. |
| [Demographics/MapServer/0](https://maps.trpa.org/server/rest/services/Demographics/MapServer/0), [1](https://maps.trpa.org/server/rest/services/Demographics/MapServer/1), and [Climate Resilience 125](https://maps.trpa.org/server/rest/services/LTinfo_Climate_Resilience_Dashboard/MapServer/125) | TDC block group values for 2021 and 2022, and the dashboard copy. The `curated --layer tdc_values` command builds the wide layout. |
| [Demographics/MapServer/35](https://maps.trpa.org/server/rest/services/Demographics/MapServer/35) Census_Jobs | Jobs, establishments, and payroll by ZIP code. Built by the `jobs` command. |
| [Demographics/MapServer/32](https://maps.trpa.org/server/rest/services/Demographics/MapServer/32) School Enrollment | Enrollment by school and year |
| [Climate Resilience 141](https://maps.trpa.org/server/rest/services/LTinfo_Climate_Resilience_Dashboard/MapServer/141) and [142](https://maps.trpa.org/server/rest/services/LTinfo_Climate_Resilience_Dashboard/MapServer/142) | LODES origin-destination flows and workplace jobs. Built by the `lodes` command. |

## Raw table (Census Data layout)

One row per geography, variable, year, sample level, and dataset.

| Column | Type | Meaning |
|---|---|---|
| `GEO_ID` | text | Census geography code without the summary level prefix. Tract: 11 digits. Block group: 12 digits. Keep as text; California codes start with 0. |
| `value` | number | The estimate or count. Blank when the Census Bureau did not publish it. |
| `MarginOfError` | number | ACS margin of error at the 90 percent confidence level. Blank for Decennial data. Zero when the Census Bureau controls the estimate to a known total. |
| `state`, `county`, `tract`, `block_group` | text | FIPS parts of the geography code |
| `variable_code` | text | Census code such as `B25003_002E`, or a grouped code such as `TRPA Grouped: B01001_003E, ...` |
| `variable_name` | text | TRPA name from `config/variables.csv`, or the group name |
| `variable_category` | text | TRPA category |
| `year_sample` | integer | Data year. For ACS 5-year data, the last year of the five. |
| `sample_level` | text | `tract`, `block group`, or `block` |
| `dataset` | text | Census dataset, such as `acs/acs5` or `dec/dhc` |
| `census_geom_year` | integer | Census boundary year: 2020 for data years 2020 and later, 2010 for 2010 to 2019 |
| `TRPAID` | text | `GEO_ID` plus `census_geom_year`. Links each row to its shape in layer 27. |
| `NEIGHBORHOOD` | text | Neighborhood name from layer 27 |

The published table also has `OBJECTID`, `Data_Scale`, and `delete_flag`, which the database manages.

## Summary table (Climate Resilience Dashboard layout)

One row per summary geography, variable, year, sample level, dataset, and category.

| Column | Meaning |
|---|---|
| `variable_code`, `variable_name`, `dataset`, `sample_level`, `year_sample` | Same as the raw table. Summaries built from tracts and from block groups are kept apart by `sample_level`. |
| `value` | Sum of tract or block group values, or a median from count bins. When some areas were blank, the sum of the others; see the `_partial.csv` file. |
| `Geography` | `Basin`, a county such as `El Dorado County (Tahoe Basin)`, `North Lake`, `South Lake`, `California`, or `Nevada` |
| `Category` | The variable category |

### Summary geographies

| Geography | Built from |
|---|---|
| Basin | Every basin tract or block group |
| El Dorado County (Tahoe Basin) | County 06017 |
| Placer County (Tahoe Basin) | County 06061 |
| Douglas County (Tahoe Basin) | County 32005 |
| Washoe County (Tahoe Basin) | County 32031 |
| North Lake | Placer and Washoe |
| South Lake | El Dorado and Douglas |
| California, Nevada | The basin part of each state |

Carson City (county 32510) is not in `config/settings.json`, so it is not downloaded. Earlier processing also removed Carson City rows before summarizing.

## Census annotation codes

The Census API sometimes returns a code instead of a number. The download step replaces them and lists them in `annotations_<year>.csv`.

| Code | Meaning | Becomes |
|---|---|---|
| -666666666 | Estimate could not be computed (too few sample cases) | blank value |
| -999999999, -888888888, -222222222, -333333333 | Other "not available" codes | blank value |
| -555555555 in the margin of error | Estimate is controlled; no sampling error | margin of error 0 |

Source: [Census Bureau notes on ACS estimate and annotation values](https://www.census.gov/data/developers/data-sets/acs-1year/notes-on-acs-estimate-and-annotation-values.html).

## Margins of error

* Sums: square root of the sum of squared margins. This is the Census Bureau's standard approximation. It gets less accurate as more estimates are added, especially when many are zero.
* Coefficient of variation: margin of error divided by 1.645, divided by the estimate. The QAQC report flags values above 40 percent as unreliable.
* Medians from bins: Census Bureau design factor method; see [Groupings and medians](groupings_and_medians.md).
* Summary margins of error are written to a separate `_margins_of_error.csv` file. The published summary tables have no field for them.
