# Decisions

Answers to each round of questions and what the code does as a result. New questions are in [QUESTIONS.md](QUESTIONS.md). The answered question files are in `docs/data_issues/`.

## Round 1 (Oct. 21, 2026)

| # | Question | Answer | What was done |
|---|---|---|---|
| A1 | Census API key in the original repository | Not a concern | No change. The new repository reads the key from `.env`. The Census API now requires a key for every data request, so `download` stops with a message when none is set. |
| A2 | Counts and individual medians published as household medians | List the wrong records and write code to fix them; do not run it | Wrong records with counts: [docs/data_issues/wrong_records_2026-10-22.csv](docs/data_issues/wrong_records_2026-10-22.csv). Fix rules in `config/corrections/relabel.csv` and `replacements.csv`. The `corrections` command builds append and retire files. Not run. |
| A3 | B25004_007E published as Other Vacant | Add to the fix code; do not run | `relabel.csv` renames 007E to For migrant workers. `replacements.csv` downloads B25004_008E. `field_updates.csv` refills the curated layer's Other Vacant field. `config/curated_layers.csv` now uses 008E. Not run. |
| A4 | Presence of Children groups double count | Yes; add to the fix code; do not run | `config/groupings.csv` now uses B25012_003E, _009E, _011E, and _017E. `regroup.csv` retires the published groups and rebuilds them from published detail records. Not run. |
| B1 | Grouped variable code format | Keep for now | No change |
| B2 | Prefixes in the dataset field | Yes; add to the fix code | New grouped rows keep the Census dataset. The corrections step resets prefixed values in all three tables. |
| B3 | Two vehicle groupings in Census Data | Do not change | Both stay published. `config/groupings.csv` builds "Household Vehicle Numbers Grouped" for new years. |
| B4 | Spelling | Fix; add to the fix code; do not run | Config files use the corrected spellings. `spelling.csv` lists every published value to fix, including "Prescence", "Housholds", "povety", "Sanfranciso CMSA", and the two spellings of Tenure categories and Home Value (Median). |
| B5 | Partial sums | Publish with a flag; a blank can be real | Group and summary steps add the values present and list the gaps in `_partial.csv` files. The Demographic Summaries layout puts the flag in Notes. |
| B6 | Margin of error field in the dashboard table | Not needed | Summary files match the published layout without it. Margins of error go to a separate `_margins_of_error.csv` for review. |
| B7 | Demographic Summaries (layer 18) | Keep in sync | The summarize step also writes the layer 18 layout. Tract-based values are used because layer 18 has no sample level field. |
| B8 | Tract and block group summaries | Keep both | No change |
| B9 | Neighborhood summaries | Yes | `Neighborhood` is in `summary_levels` |
| C1 | Age_18_to_65 covers 18 to 64 | Leave | No change |
| C2 | With_Disability covers ages 20 to 64 | "keep rename and switch to b18101" | Keep the B23024 group under a new name, With_Disability_20_to_64, and make With_Disability the all-ages group from B18101. B18101 is published for tracts only, so the TDC block group layout keeps the 20 to 64 group. `relabel.csv` renames published rows. Confirmed in round 2. |
| C3 | Medians for home value and gross rent | Build it | Added to `config/medians.csv` with separate bins for 2011 to 2014 and 2015 and later, checked against the Census API. Bin variables added to `config/variables.csv`. |
| C4 | Median margins of error | Yes | Census Bureau design factor method, with national design factors. See docs/groupings_and_medians.md. |
| C5 | Reliability thresholds | Use 12 and 40 percent | No change |
| D1 | Port the remaining notebooks | All of them | `comparison`, `jobs`, `lodes`, `curated`, `tessellation`, `import-1990`, `enrollment`, and `inflate` commands. See docs/other_sources.md. |
| D2 | Full published variable list | Keep what is used today | No merge. Variables used by groupings, medians, curated layers, and the 1990 import were added. |
| D3 | Run the checks against the live service | No answer yet | Carried to round 2, still open |
| D4 | Hosting and shared assets | OK | No change |
| D5 | Old first-draft files | Fine | Removed; still in Git history |
| D6 | Git | Later | Nothing committed |

## Round 2 (Oct. 22, 2026)

| # | Question | Answer | What was done |
|---|---|---|---|
| 1 | sde password in the original repository | Make sure it is not in the new one | It is not. `tests/test_no_secrets.py` now fails if any file holds something that looks like a password, connection string, or API key. The same test finds the password and the Census key in the original repository. |
| 2 | With_Disability reading | Yes | No change |
| 3 | Demographic Summaries sample level | Tracts | No change |
| 4 | LODES workplace file type | S000 and JT01 | No change |
| 5 | Jobs before 2018 | Replace the workbook values with downloads | `jobs --year 1998 --year-end 2017 --replace-published` writes append, retire, and comparison files. It reads each year's variable list first, picks the all-industries row, and blanks withheld values with flag D. The four South Lake Tahoe PO box ZIP codes are used through 2017, as published. Not run: it needs your Census API key. |
| 6 | Inflation factors after 2021 | Look them up | `config/inflation_adjustments.csv` now stores the BLS annual average R-CPI-U-RS index for 1990 and 2000 to 2025. The code computes factors to any year. |
| 7 | School enrollment detail | Read individual schools | `enrollment` reads CDE school files (1998-99 on) and NDE workbooks (2015-16 on) for each school in `config/school_enrollment_schools.csv`. Nevada output matched every published value from 2015-16 to 2022-23. California could not be downloaded from here and needs a check run. |
| 8 | Median design factors | National | No change |
| 9 | Live checks | No answer | Carried to round 3 |
