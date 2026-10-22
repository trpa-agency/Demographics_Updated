# Open questions, second round

Answers to the first round are recorded in [DECISIONS.md](DECISIONS.md). Answer inline under each question. **Default** shows what the code does now.

Confidence tags: [Certain] means checked against the files, the services, or Census definitions. [Likely] means strong evidence. [Guessing] means it needs your knowledge.

---

### 1. A database password is in plain text in the original repository [Certain]

`scripts/misc/Demographics_CreateLayers.ipynb` holds a SQL Server connection string with the sde user name and password. This is a different risk from the Census API key: it opens the enterprise geodatabase.

* Should the sde password be changed and the notebook scrubbed from history?

> Answer:
No just make sure it isn't in the new one
### 2. With_Disability (C2)

Your answer was "keep rename and switch to b18101". The code reads it as:

* the B23024 group stays, renamed With_Disability_20_to_64
* With_Disability now means all ages, from B18101
* the TDC block group layout keeps the 20 to 64 group, because B18101 is published for tracts only [Certain: the published Census Data table has B18101 for tracts only]

Is that right?

> Answer:
yes
### 3. Demographic Summaries sample level

Layer 18 has no sample level field, so the toolkit writes only one level there.

**Default:** tract (`demographic_summaries_layout` in settings.json). Tracts have smaller margins of error. The 2023 rows already in layer 18 do not say which level they used.

> Answer:
tracts
### 4. LODES workplace file type [Guessing]

The work locations table (MapServer/142) has the workplace area columns but no note on which LODES segment and job type it holds.

**Default:** all workers (S000), primary jobs (JT01), to match the origin-destination table.

> Answer:
that's correct
### 5. Jobs before 2018

Published 1998 to 2017 values came from a hand-built workbook. The `jobs` command can download 1998 to 2017 from ZIP Code Business Patterns instead.

* Replace the workbook values with downloads, or leave them?

> Answer: do that

### 6. Inflation factors after 2021

`config/inflation_adjustments.csv` ends at 2021. Converting 2022 to 2024 dollars needs those years' R-CPI-U-RS values.

* Should I look them up and add them, or will you supply them?

> Answer: look them up

### 7. School enrollment detail

The published School Enrollment table has one row per school, including Nevada schools. The ported California download returns district totals by grade.

* Is the district total enough, or should the code read individual schools in California and Nevada?

> Answer: code should read individual schools

### 8. Median design factors

Margins of error for medians use national design factors. The Census Bureau also publishes state factors for California and Nevada, which differ slightly.

**Default:** national factors.

> Answer: national

### 9. Checks against the live service (carried over)

The corrections code was tested against fake service data only, as you asked. Before loading anything, run `tools/5_build_corrections.bat` (it only reads) and `tools/4_check_published_service.bat`, and look at `conflicts.csv` if one is written.

> Answer:
