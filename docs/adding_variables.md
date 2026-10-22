# Adding variables

Everything the toolkit downloads is listed in `config/variables.csv`. To add a variable, add a row. You do not need to change any code.

## The easy way

1. Find the Census table you want. data.census.gov lists tables by topic. For example, B25003 is Tenure (owner or renter).
2. Double-click `tools/1_find_census_variables.bat`.
3. Type the table code, the year, and a TRPA category name, and answer Y to add the rows.
4. Open `config/variables.csv` in Excel and review the new rows at the bottom. Shorten names if you like and set `active` to `N` for anything you do not need.
5. Run `tools/3_check_groupings.bat` if you also changed groupings.

## Searching by words

```
python -m trpa_demographics find --search "heating fuel" --year 2023
python -m trpa_demographics find --table B25040 --year 2023 --category "House Heating Fuel" --add
```

`--search` downloads the full list of Census variables once (a few megabytes) and caches it in `outputs/cache`. Every word must appear in the label or concept.

## Columns in variables.csv

| Column | Meaning | Example |
|---|---|---|
| `variable_code` | Census variable code. ACS estimates end in E. Decennial 2020 codes end in N. Do not list margin of error codes; they are downloaded automatically. | `B25003_002E` |
| `variable_name` | Name shown in tables and charts | `Occupied Housing Units: Owner Occupied` |
| `variable_category` | TRPA category. Use an existing category when one fits, spelled exactly the same. | `Housing Units` |
| `dataset` | Census dataset | `acs/acs5`, `acs/acs5/subject`, `dec/dhc` |
| `sample_level` | Geography levels, separated by a semicolon | `tract;block group` |
| `years` | Years the variable exists. Blank means every year. `2020` means only 2020 (Decennial). `2015-` means 2015 and later. `-2014` means 2014 and earlier. | `2015-` |
| `aggregation` | `sum` for counts. `none` for medians, averages, percentages, and rates, which cannot be added. | `sum` |
| `active` | `Y` to download, `N` to keep for reference only | `Y` |
| `notes` | Anything a future reader should know, such as a universe limit or a known label problem | `Universe is the population 20 to 64 years.` |

## Things to watch

* **Block groups.** Some ACS tables are published only for tracts. If every block group value comes back blank, set `sample_level` to `tract`.
* **Medians and averages.** Mark them `aggregation = none`. The summarize step skips them. To get a basin median, list the count bins in `config/medians.csv` instead.
* **Table changes.** The Census Bureau sometimes renumbers or redefines variables between years. The download writes unknown codes to `unknown_variables_<year>.csv`. The QAQC year-over-year check flags large jumps.
* **Universe.** Each table counts a specific population, such as households, people 5 and over, or people 20 to 64. Note it in `notes` when the name could mislead.
* **Decennial variables.** Give them a `years` value, such as `2020` for dec/dhc, so a yearly ACS download does not ask for them.
