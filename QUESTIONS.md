# Open questions, third round

Answers to earlier rounds are recorded in [DECISIONS.md](DECISIONS.md). Answer inline under each question. **Default** shows what the code does now.

Confidence tags: [Certain] means checked against the files, the services, or source documents. [Likely] means strong evidence. [Guessing] means it needs your knowledge.

---

### 1. South Lake Tahoe PO box ZIP codes

The published 1998 to 2017 jobs include 96152, 96154, 96156, and 96157. The published 2018 to 2023 jobs do not [Certain: counted in MapServer/35].

**Default:** use them through 2017 only, so the replacement keeps the same ZIP codes as today.

* Should 2018 and later include them too? That would change published 2018 to 2023 totals if those ZIP codes have data.

> Answer:

### 2. Extra jobs variables for 1998 to 2017

Published 1998 to 2017 has Total Employees only. The download also returns establishments, first quarter payroll, and annual payroll.

**Default:** include all four, to match 2018 and later.

> Answer:

### 3. California enrollment type

From 2020-21, DataQuest counts primary and short-term enrollment together (C). Earlier years count primary only (P). The 2023-24 and later Census Day files do not say which they hold [Guessing].

**Default:** C when a year has it, otherwise P. Check the first comparison file. A jump at 2020-21 or 2023-24 would show a change in definition.

> Answer:

### 4. Lake Tahoe Unified schools

Lake Tahoe Unified is published as one district total. The code can also write each of its schools.

**Default:** keep the single district row.

> Answer:

### 5. Inflation base year

**Default:** 2021 dollars, as before. Any year from the table can be chosen with `--to-year`.

* Should the default move to a later year, such as 2024?

> Answer:

### 6. Checks against the live service (carried over twice)

The corrections, jobs replacement, and California enrollment code were tested on made-up data only. Before loading anything, run:

* `tools/5_build_corrections.bat` and `tools/4_check_published_service.bat`
* `python -m trpa_demographics jobs --year 1998 --year-end 2017 --replace-published`
* `python -m trpa_demographics enrollment --year 2020 --year-end 2025`

All of them only read. Then look at the comparison and conflicts files.

> Answer:
