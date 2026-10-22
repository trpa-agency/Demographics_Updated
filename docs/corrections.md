# Corrections to published data

Review in October 2026 found errors in the published demographic tables. The fixes are written as code and rules. Nothing has been applied to any service or to SDE.

The full list of what is wrong, with record counts, is in [data_issues/wrong_records_2026-10-22.csv](data_issues/wrong_records_2026-10-22.csv).

## What is wrong

| Issue | Where | What happened |
|---|---|---|
| A2 | Census Data, Demographic Summaries | B25075_001E (count of owner-occupied units) is named "Median home value". B25063_001E (count of renter units) is named "Median Gross Rent". B06011_001E (median income of individuals) is named "Median Household Income". B19001_001E (total households) sits in "Income (Median)". Demographic Summaries publishes the B25075_001E and B25063_001E counts as 2023 medians. |
| A3 | Census Data, Tahoe Census Curated | B25004_007E (vacant: for migrant workers) is named "Other Vacant". The curated layer's Other Vacant field was filled from it. Other vacant is B25004_008E. |
| A4 | Census Data, Demographic Summaries | The Presence of Children groups add nested B25012 variables. Owner households with children are counted three times, and households with related but not own children are counted as having no children. |
| B2 | All three summary and data tables | The dataset field holds grouping prefixes, such as "Prescence of Children: acs/acs5" or "TRPA 5-year Age Categoriesacs/acs5". |
| B4 | Census Data, Demographic Summaries | Categories spelled two ways ("Tenure By Age Of Householder" and "Tenure by Age of Householder"), "Prescence", "Housholds", "povety", and "Sanfranciso CMSA". |
| C2 | Census Data | The B23024 group "With_Disability" counts only ages 20 to 64. It is renamed With_Disability_20_to_64. With_Disability now comes from B18101 (all ages, tracts only). |

## How the fix works

The services are treated as append-only. For each wrong record the corrections step writes a corrected copy to an append file and lists the original's OBJECTID in a retire file. A person loads the append file, checks it, and then deletes or flags the retired records.

```
python -m trpa_demographics corrections
python -m trpa_demographics corrections --download
```

Or double-click `tools/5_build_corrections.bat`.

The first command only reads the services. `--download` also downloads the correct Census codes (B25077_001E, B25064_001E, B19013_001E, B25004_008E) for every year and level where a wrong code was published. It needs a Census API key.

Output in `outputs/corrections/<date>/`:

| File | Contents |
|---|---|
| `census_data_append.csv` | Corrected Census Data records, including rebuilt Presence of Children groups |
| `census_data_retire.csv` | OBJECTIDs those records replace, with the reason |
| `demographic_summaries_append.csv`, `_retire.csv` | Same for Demographic Summaries |
| `climate_dashboard_census_data_append.csv`, `_retire.csv` | Same for the dashboard table (dataset prefixes only) |
| `census_data_replacements_append.csv` | With `--download`: the correct Census codes |
| `tahoe_census_curated_field_updates.csv` | Other Vacant values to set in the curated layer, keyed on OBJECTID. The curated layer holds shapes, so it is updated in place or rebuilt with the `curated` command. |
| `conflicts.csv` | Appended records that would duplicate a published record that is not being retired. Resolve these first. |
| `corrections_summary.csv` | Records replaced, by reason |
| `README.txt` | Load steps |

## Rules

The rules are CSV files in `config/corrections/`, so a new fix is a new row:

| File | Columns | Use |
|---|---|---|
| `relabel.csv` | layer, variable_code, dataset, match_name, match_category, new_name, new_category, reason | Rename or recategorize records. A blank variable_code matches any code with the given name and category. |
| `spelling.csv` | layer, field, old_value, new_value, reason | Replace one exact value in one field |
| `regroup.csv` | layer, old_variable_category, grouping_set, reason | Retire every grouped record in a category and rebuild it from the published detail records with the current groupings.csv |
| `replacements.csv` | wrong_code, dataset, replacement_code, reason | Codes to download with `--download` |
| `field_updates.csv` | layer, field, variable_code, dataset, sample_levels, reason | Fields in the curated polygon layer to refill |

Dataset prefixes (B2) need no rule. Any dataset value that is not in `valid_datasets` in `config/settings.json` but ends in one is reset to it.

## Checking

The Explorer's Data quality tab counts published records that still match a rule ("Known errors that are still published"). After loading the fixes, that count drops to zero. `python -m trpa_demographics qaqc --service` checks duplicates and labels.

Layers not covered: the TDC block group layers (Demographics MapServer/0 and 1, Climate Resilience MapServer/125) and the tessellation layer hold their own copies of some values. Rebuild them with the `curated` and `tessellation` commands rather than patching them.
