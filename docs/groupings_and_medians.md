# Groupings and medians

## Groupings: config/groupings.csv

Census tables are often more detailed than TRPA needs. Age is split by sex and into 23 bands, for example. A grouping set adds detailed variables into TRPA categories.

Each row assigns one Census variable to one group:

| Column | Meaning | Example |
|---|---|---|
| `grouping_set` | Name of the set. It becomes the start of the grouped variable code. | `TRPA Grouped` |
| `output_category` | Category for the grouped rows. `{source_category}` is replaced with the members' category. | `TRPA Grouped: {source_category}` becomes `TRPA Grouped: Age` |
| `group_name` | The TRPA category. Becomes `variable_name`. | `Age_Under_18` |
| `group_order` | Display order within the set | `1` |
| `variable_code` | Census variable that belongs to the group | `B01001_003E` |
| `dataset` | Census dataset of the variable | `acs/acs5` |
| `notes` | Optional | |

### Rules

* Within a set, each Census variable belongs to one group. The QAQC check `code_in_two_groups` enforces this.
* A group must not contain a total and one of its parts. Census tables nest: "Owner occupied: With related children" already includes "With own children". Adding both counts the same households twice. The check `group_double_counts` uses Census label structure to find these.
* Do not group medians, averages, or percentages.

### What the group step produces

For each geography, year, and level, the members' values are added and the margins of error are combined as the square root of the sum of squared margins. The grouped row uses the same layout as the Census Data table:

* `variable_code`: `TRPA Grouped: B01001_003E, B01001_004E, ...` (cut at 255 characters)
* `variable_name`: the group name
* `variable_category`: from `output_category`
* `dataset`: unchanged, such as `acs/acs5`

If a member value is blank for a geography, the other members are still added and the geography is listed in the `_partial.csv` file.

### Sets included

| Set | Source | Built from |
|---|---|---|
| TRPA Grouped | ACS B01001, B03002 | Age_Under_18, Age_18_to_65, Age_65_and_Over, White_Alone, BIPOC |
| TRPA 5-year Age Categories | ACS B01001 | 5-year age bands, male and female combined |
| English Fluency | ACS B16004 | Speaks English very well or well, and not well or not at all |
| Household Vehicle Numbers | ACS B25044 | Households by vehicles available, owners and renters combined |
| TRPA Census Age Categories Grouped, TRPA 10-year Age Categories Grouped (1990) | 1990 STF3 (dec/sf3) | Age bands from table P014 parts A, B, and C, as published |
| Presence of Children | ACS B25012 | Owner and renter households with and without related children under 18. Corrected in October 2026; the earlier "Prescence of Children" set added nested variables. See [Corrections](corrections.md). |
| With Disability | ACS B23024 | With_Disability_20_to_64: population 20 to 64 with a disability. Kept for block group layers. |
| Disability All Ages | ACS B18101 | With_Disability: civilian noninstitutionalized population of all ages with a disability. Tracts only. |
| TRPA Census Age Categories Grouped, TRPA 10-year Age Categories Grouped, TRPA Census Age Sex Categories Grouped | Decennial 2010 (dec/sf1) and 2020 (dec/dhc) | Age bands from the Decennial age table |

These were combined from `Census_Category_Lists/categories.csv`, `dec_age_categories.csv`, and `dec_age_categories_2020.csv` in the original repository and `Lookup_Lists/Overall_Grouping_List.csv` in this one. Names were kept as published so new rows match old ones.

## Medians: config/medians.csv

A median cannot be added across tracts. To get a basin, county, or shore median, the summarize step adds up count bins (for example, households with income from $50,000 to $59,999) across the area and finds the middle value.

| Column | Meaning |
|---|---|
| `median_set` | Name of the median. Becomes the start of the variable code. |
| `output_name` | Becomes `variable_name` |
| `output_category` | Becomes `Category` |
| `variable_code` | Census count variable for one bin. Several codes can share a bin, such as male and female counts for the same age band. |
| `dataset` | Census dataset |
| `first_year`, `last_year` | Years the bin applies to. Blank means no limit. Used when the Census Bureau changes bins. |
| `bin_lower`, `bin_upper` | Bin edges. Leave `bin_upper` blank for the open top bin, such as $200,000 or more. |
| `design_factor` | Census Bureau design factor for the table, used for the margin of error |
| `notes` | Optional |

### Sets included

| Set | Table | Bins |
|---|---|---|
| TRPA Median Household Income | B19001 | 16 bins, the same in every year since 2011, top bin $200,000 or more |
| TRPA Median Age | B01001 | 23 age bands, male and female added together, top bin 85 and over |
| TRPA Median Home Value | B25075 | 2011 to 2014: top bin $1,000,000 or more. 2015 and later: two more bins and a top bin of $2,000,000 or more. |
| TRPA Median Gross Rent | B25063 | 2011 to 2014: top bin $2,000 or more. 2015 and later: three more bins and a top bin of $3,500 or more. No cash rent is left out, as in the published median (B25064). |

The bin changes in 2015 were checked against the Census API table definitions for 2011, 2014, 2015, and 2023.

### How the median is calculated

1. Add each bin's counts across the area.
2. Find the bin where the running total passes half of all counts.
3. Assume values are spread evenly inside that bin and interpolate.

Example: 20 households under $10,000, 60 from $10,000 to $20,000, and 20 above. Half of 100 is 50. The first bin holds 20, so 30 more are needed from the 60 in the second bin. 30 of 60 is halfway, so the median is $15,000.

When the median falls in the open top bin, the result is the bin's lower edge and is listed in `_median_notes.csv`.

### Margin of error for a median

The summarize step follows the Census Bureau design factor method:

1. Standard error of 50 percent: design factor times the square root of (99 divided by 5 times the total count) times 50 squared.
2. Find the values at 50 percent minus and plus that standard error, by the same interpolation.
3. The median's standard error is half the distance between those two values. The margin of error is 1.645 times that.

When either value falls in the open top bin, the margin of error is left blank, as the Census Bureau does.

The design factors are the national values from the Census Bureau's 2011 to 2015 ACS 5-year PUMS accuracy statement: 1.6 for household income, 1.7 for gross rent, 1.5 for home value, and 1.1 for age. State tables in that document differ slightly. This is an approximation; the Census Bureau's exact method uses replicate weights.

Sources: [Census Bureau ACS 5-year PUMS accuracy statement, 2011 to 2015](https://august.csscr.washington.edu/~data/ACS/5-Year/2011-2015/2015ACS-PUMS/US/document%20files/2011_2015%20%205yr%20ACS-PUMS_Accuracy.pdf); [California Department of Finance, How to Recalculate a Median](https://dof.ca.gov/media/docs/forecasting/Demographics/california-state-data-center-network/How_to_Recalculate_a_Median.pdf).
