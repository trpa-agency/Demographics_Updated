# Open questions from the first pass

Answer inline under each question. Items marked **Default** show what the code does now if you do not answer.

Confidence tags: [Certain] means checked against the files, the services, or Census definitions. [Likely] means strong evidence. [Guessing] means it needs your knowledge.

---

## A. Urgent

### A1. The Census API key is committed in the original repository [Certain]

The key is in plain text in `Census_Download.ipynb`, `Census_Download_Script.py`, and `CBP_download.ipynb` in the original Demographics repository, and in its Git history. The new repository reads the key from `.env` or an environment variable.

* Is `trpa-agency/Demographics` public on GitHub?
* Will you request a new key and retire the old one? Removing it from the files does not remove it from Git history.

> Answer: that's fine don't care

### A2. Published values that are wrong [Certain]

These are in services the public and the Climate Resilience Dashboard read. Fixing them means editing SDE, which needs your approval.

| Where | Problem |
|---|---|
| Demographic Summaries (layer 18), 2023, Basin | "Home Value (Median)" = 14,932. The code is B25075_001E, which counts owner-occupied housing units. It is not a median. Median home value is B25077_001E. |
| Census Data (layer 28) | B25075_001E is named "Median home value". It is the total of the home value table (a count of units). |
| Census Data (layer 28) | B25063_001E is named "Median Gross Rent". It is the total of the gross rent table (a count of renter units). Median gross rent is B25064_001E. |
| Census Data (layer 28) | B06011_001E is named "Median Household Income". B06011 is median income of individuals 15 and over, by place of birth. Median household income is B19013_001E. |
| Census Data (layer 28) | B19001_001E (total households) sits in category "Income (Median)". |

* Should these rows be relabeled, removed, or replaced with the correct codes?
* Any summary built from these codes with a sum is also wrong. Should I list every affected summary row?

`config/variables.csv` carries the correct codes and marks the mislabeled ones `active = N` with a note. The Explorer's Data quality tab flags them.

> Answer: Yes = ;ost tje pmes that are wrong and make mode to fix them - don't run it

### A3. "Other vacant" is probably the wrong code [Likely]

`general_variables.csv` names B25004_007E "Vacant Housing Units: Other Vacant". In ACS table B25004, _007E is "For migrant workers" and _008E is "Other vacant". The Tahoe Census Curated layer (layer 3) has a field `vacant_housing_units_other_vacant` that likely came from _007E. A comment in `Census_Summaries.ipynb` says _008E is not in the service.

* Confirm, and decide whether layer 3 should be rebuilt with B25004_008E.

`config/variables.csv` now lists both codes with their Census names.

> Answer: yes - add to fixing code do not run

### A4. The "Prescence of Children" grouping counts households two or three times [Certain]

Table B25012 nests: "With related children" (_003E) already includes "With own children" (_004E) and "No own children" (_008E), and _004E already includes _005E through _007E. The grouping adds all of them into "Owner Occupied Households With Children". It also puts _008E, "No own children", into "With Children". The renter side has the same problem.

**Proposed fix:** With children = _003E (owner) and _011E (renter). With no children = _009E and _017E.

The file still holds the old definition so new rows match published rows until you decide. `qaqc --config` flags it as a failure.

* Approve the fix? If yes, should published grouped rows be rebuilt?

> Answer:
yes - but do not run fix add to fix code
---

## B. Publishing conventions

### B1. Grouped variable codes

Published grouped rows use codes like `TRPA Grouped: B01001_003E, B01001_004E, ...`, cut at 255 characters. Long groups lose members off the end.

**Default:** keep this format so new rows match old ones.

* Or switch to a short code such as `TRPA Grouped: Age_Under_18`, with members listed in `config/groupings.csv`?

> Answer: keep for now

### B2. The dataset field on grouped rows

Published grouped rows use three styles: `acs/acs5`, `Household Vehicle Numbers: acs/acs5`, and `TRPA 5-year Age Categoriesacs/acs5` (no separator).

**Default:** `dataset` always holds the Census dataset (`acs/acs5`). The grouping set is already in `variable_code` and `variable_category`.

* OK? Should published rows be cleaned to match?

> Answer: yes add to fix code

### B3. Duplicate vehicle groupings

Layer 28 holds two vehicle groupings: "Household Vehicle Numbers Grouped" and "Household Vehicle Numbers: Tenure by Vehicles Available". The dashboard table uses the first.

**Default:** keep "Household Vehicle Numbers Grouped" only.

> Answer: don't change

### B4. Category spelling

Layer 28 has pairs such as "Tenure By Age Of Householder" and "Tenure by Age of Householder", and "Home Value (Median)" and "Home Values (Median)". The published category "Tenure by Prescence of Children" is misspelled.

* Fix spellings in new data and published data, or keep published spellings for continuity?

**Default:** new rows keep published spellings.

> Answer: fix ADD TO FIX CODE DON'T RUN

### B5. Partial sums

When a member of a group, or a tract inside a summary area, is blank, the old code added the rest and published a total that looked complete.

**Default:** the value is left blank and listed in a gaps file.

* OK, or would you rather publish partial sums with a flag?

> Answer: publish with flag - could be real ones where no value was present

### B6. Margins of error in summaries

The summarize step calculates a margin of error for every sum. The Climate Resilience Dashboard table (layer 135) has no MarginOfError field.

* Add the field to layer 135?

> Answer: nope- don't need it

### B7. Which summary table is current?

Demographic Summaries (layer 18) and the dashboard table (layer 135) overlap and use different layouts. The toolkit writes the layer 135 layout.

* Should layer 18 be retired, frozen as historical, or kept in sync? If kept, I can add a writer for its layout.

> Answer: Keep in sync


### B8. Tract and block group summaries

Summaries are built separately from tracts and from block groups, so most variables appear twice per geography and year. The old summaries did the same.

* Keep both, or pick one level per variable? (Tracts have smaller margins of error. Block groups follow the basin boundary more closely.)

> Answer: Keep all layers - there are reasons

### B9. Neighborhood summaries

The old code had a commented-out neighborhood level.

**Default:** off. Add `Neighborhood` to `summary_levels` in `config/settings.json` to turn it on.

* Turn it on?

> Answer: yes

---

## C. Definitions

### C1. Age_18_to_65 covers 18 to 64 [Certain]

The group stops at 62 to 64 years and Age_65_and_Over starts at 65. The name suggests 65 is in both.

* Rename to Age_18_to_64? This changes a published name.

> Answer: Leave

### C2. With_Disability counts only ages 20 to 64 [Certain]

It uses B23024, whose universe is the population 20 to 64 years. A transportation disadvantage indicator may want all ages. B18101 or C18101 cover the civilian noninstitutionalized population of all ages.

* Keep B23024, or switch?

> Answer: keep rename and switch to b18101

### C3. More medians from bins

`config/medians.csv` has median household income (B19001) and median age (B01001).

* Add median home value (B25075) and median gross rent (B25063)? Their top bins changed in 2015 [Likely], so the bins would need a version for 2011 to 2014. I can build it once you confirm you want them.

> Answer: build it

### C4. Margins of error for medians from bins

The Census Bureau method needs a design factor for each table. The old function had a formula with a design factor argument, but I could not confirm its constants against Census documentation.

**Default:** median margins of error are left blank.

* Should I implement the Census Bureau method using its published design factors?

> Answer: sure

### C5. Reliability thresholds

The QAQC report treats a coefficient of variation under 12 percent as reliable and over 40 percent as unreliable. These match a common convention, not a TRPA standard [Likely].

* Use these, or TRPA values?

> Answer: use these

---

## D. Scope for the next pass

### D1. What else to port

Not carried over (see `docs/migration_from_legacy.md`):

* Comparison geographies: Reno-Sparks MSA, Sacramento MSA, San Francisco CSA, full counties, and states
* County Business Patterns jobs by ZIP code
* LODES commute flows
* Pivot to feature class and the hexbin tessellation
* 1990 import, school enrollment, inflation adjustment

* Which, if any, should come next?

> Answer: I want all of those

### D2. The full variable list

`config/variables.csv` has 239 variables gathered from the lists in both repositories. The published table holds more. Running `python -m trpa_demographics inventory --registry-year 2024` writes every published variable in the same layout.

* Merge the full published list into `config/variables.csv`, or keep only what is used today?

> Answer: keep what'used today

### D3. Checks I could not run against the live service

I could read service definitions and run small queries. I could not run the full duplicate scan on layer 28 from this session. Please run `tools/4_check_published_service.bat` and `tools/3_check_groupings.bat` and share the reports, or open the Explorer's Data quality tab.

> Answer: 

### D4. Hosting the Explorer

* Publish with GitHub Pages from this repository? Under which organization?
* The page links the shared token stylesheet at `trpa-agency.github.io/tools/assets/trpa-tokens.css` and uses a copy of the white TRPA logo. OK?

> Answer: ok

### D5. Old files in this repository

The first-draft files that were here (`Utils.py`, `Data_Processing.ipynb`, `Lookup_Lists/`, and five output CSVs and one workbook) are replaced. Their content is in `config/groupings.csv` and the package. They remain in Git history.

> Answer:cool

### D6. Git

Nothing is committed. Should I commit to a new branch and open a pull request?

> Answer: Not yet I'll do all that later
