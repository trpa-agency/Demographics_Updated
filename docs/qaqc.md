# QAQC checks

Run checks with `python -m trpa_demographics qaqc` or the batch files in `tools/`. Each run writes `qaqc_report.html`, `qaqc_summary.csv`, and one CSV per check that found something, under `outputs/qaqc/<label>/`.

Severity:

* **fail**: the numbers are wrong or would double count. Fix before publishing.
* **warn**: worth a look. Often explained by how the Census Bureau publishes data.
* **info**: context, not a problem.

## Raw and grouped tables (`--input`)

| Check | Severity | What it looks for | What to do |
|---|---|---|---|
| required_columns | fail | All Census Data columns are present | Rebuild the file with the toolkit |
| duplicate_records | fail | Same TRPAID, variable, year, level, and dataset more than once | Remove the extra rows. Usually caused by appending the same download twice. |
| trpaid_format | fail | TRPAID equals GEO_ID plus boundary year, has the right length, and uses the boundary year that matches the data year | Usually a leading zero lost when a CSV was opened in Excel and saved. Re-download or rebuild GEO_ID as text. |
| inside_basin | fail | Every TRPAID is in layer 27 | Check the boundary year |
| geography_coverage | warn | Each variable has a row for every basin geography in layer 27 | Missing rows usually mean the API returned nothing for some geographies |
| blank_values | warn | Blank values | Often the table is not published at block group. Change `sample_level` to `tract`. Group and summary steps add up the rest and list the gaps in `_partial.csv`. |
| negative_values | fail | Negative numbers | Census annotation codes stored as data. The download step prevents this; older files may have them. |
| missing_margin_of_error | warn | ACS estimates without a margin of error | Re-download |
| low_reliability_estimates | info | Coefficient of variation above 40 percent | Report at a larger geography |
| inconsistent_labels | warn | One code with several names or categories | Pick one name in `config/variables.csv` |
| category_spelling | warn | Categories that differ only in capitalization or spacing | Pick one spelling |
| non_additive_variables_present | info | Medians and averages in the table | Fine in raw data. The summarize step skips them. |
| table_totals_add_up | warn | Where a total and all its parts were downloaded, the parts add up | A gap means a variable was renamed or a part is missing |
| tract_vs_block_group_totals | warn | Basin totals from block groups within 1 percent of totals from tracts | Large gaps mean the two geography lists cover different areas |
| year_over_year_jumps | warn | Basin totals that change by more than 25 percent in one year | Check for boundary changes, redefined variables, or bad data |
| already_published | warn | With `--compare-service`: rows that already exist in the published table | Do not append them again |
| published_value_differs | warn | With `--compare-service`: rows with a different published value | Decide which value is right |

## Summaries (`--summary`)

| Check | Severity | What it looks for |
|---|---|---|
| duplicate_summary_rows | fail | Same geography, variable, year, level, dataset, and category more than once |
| counties_add_to_basin | fail | The four county rows add up to the Basin row |
| shores_add_to_basin | fail | North Lake plus South Lake equals the Basin |
| states_add_to_basin | fail | California plus Nevada equals the Basin |

## Configuration (`--config`)

| Check | Severity | What it looks for |
|---|---|---|
| code_in_two_groups | fail | A Census variable in two groups of the same set |
| group_member_not_in_variables | warn | A group member that is not in `config/variables.csv`, so it never downloads |
| non_additive_group_member | fail | A median or average inside a group |
| group_double_counts | fail | A group that contains a total and one of its parts. Uses Census label structure, so it needs internet access to the Census API. |

## Published service (`--service`)

| Check | Severity | What it looks for |
|---|---|---|
| service_duplicate_records | fail | Duplicate keys in the published Census Data table. Use `--service-year` to check one year faster. |
| service_inconsistent_labels | warn | Published codes with several names or categories |
| service_negative_values | fail | Published negative values |

The Explorer's Data quality tab runs similar checks in the browser, plus checks for known errors that are still published (the rules in `config/corrections`), added medians in summaries, dataset values that are not Census dataset names, unexpected summary geography names, and grouped codes cut at the field length limit.

## LODES

The `lodes` command writes its own QAQC report with the checks listed in [Other sources](other_sources.md).

## Corrections

The `corrections` command writes `conflicts.csv` when an appended record would duplicate a published record that is not being retired. See [Corrections](corrections.md).
