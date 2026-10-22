"""School enrollment for each Tahoe Basin school, from state download files.

The School Enrollment table (Demographics MapServer/32) has one row per school
and school year: School_Name, State, Level_, Year (such as 2022-2023),
Enrollment, data_source, and school_id. The schools, their state codes, and the
Lake Tahoe Unified district total are listed in config/school_enrollment_schools.csv.

California
    The California Department of Education (CDE) publishes Census Day enrollment
    (the first Wednesday in October) as tab-delimited text files. Files for
    1998 to 2022 hold one row per school, race or ethnicity, and gender, so rows
    are added up by CDS code. Files from 2023-24 hold one row per school or
    district and reporting category; the TA (total) category is used. From 2014
    the files mark primary (P) or combined primary and short-term (C) enrollment.
    The type in settings is used when a year has it.

Nevada
    The Nevada Department of Education publishes Validation Day counts (about
    October 1) as one Excel workbook per year from 2015-16. Layouts change by
    year, so the reader looks for a sheet with a school code column and a total
    column. When only grade-level rows exist, grades are added up. Earlier
    Nevada years came from the Nevada Report Card site, which has no download.

A school listed without a code is reported as 0, which is how the published
table shows a closed school. Download URLs are in config/settings.json
(school_enrollment). Files are cached in outputs/enrollment/cache.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from . import services
from .config import REPO_ROOT, outputs_dir

ENROLLMENT_COLUMNS = ["School_Name", "State", "Level_", "Year", "Enrollment", "data_source", "school_id"]
REVIEW_COLUMNS = ENROLLMENT_COLUMNS + ["source_code", "note"]
CODE_HEADERS = {"school code", "id"}
TOTAL_HEADERS = {"total", "grand total", "ntotal"}
GRADE_HEADERS = {"grade", "grade level"}


def year_label(fall_year: int) -> str:
    """Published year label, such as 2022-2023, for the school year starting in a fall year."""
    return f"{fall_year}-{fall_year + 1}"


def fall_year(value) -> Optional[int]:
    """Fall year from a school year value such as 2019-20, 201920, or 2019-2020."""
    match = re.match(r"\s*(\d{4})", str(value))
    return int(match.group(1)) if match else None


def load_schools(settings: dict) -> pd.DataFrame:
    """Schools from config/school_enrollment_schools.csv, with codes as text."""
    return pd.read_csv(REPO_ROOT / settings["school_enrollment"]["schools"], dtype=str).fillna("")


def _fetch(url: str, session: requests.Session, cache: Path) -> bytes:
    path = cache / url.rsplit("/", 1)[-1]
    if not path.exists():
        response = session.get(url, timeout=300)
        response.raise_for_status()
        path.write_bytes(response.content)
    return path.read_bytes()


# --- California ----------------------------------------------------------------

def read_cde_text(content: bytes) -> pd.DataFrame:
    """Read a CDE tab-delimited enrollment file as text columns."""
    for encoding in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(content), sep="\t", dtype=str, encoding=encoding).fillna("")
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not read the CDE file as UTF-8 or Latin-1 text")


def california_totals(df: pd.DataFrame, enrollment_type: str = "C") -> pd.DataFrame:
    """School and district totals by fall year from either CDE file layout.

    Returns fall_year, aggregate (school or district), code, enrollment, enrollment_type,
    and suppressed (rows marked * that were left out).
    """
    cols = {c.upper(): c for c in df.columns}
    if "AGGREGATELEVEL" in cols:  # Census Day files from 2023-24
        get = lambda name: df[cols[name.upper()]]
        level = get("AggregateLevel").str.strip().str.upper()
        keep = get("ReportingCategory").str.strip().str.upper().eq("TA")
        if "CHARTER" in cols:
            charter = get("Charter").str.strip().str.upper()
            keep &= (level.eq("S") | charter.eq("ALL"))
        keep &= level.isin(["S", "D"])
        part = df[keep]
        county = part[cols["COUNTYCODE"]].str.zfill(2)
        district = part[cols["DISTRICTCODE"]].str.zfill(5)
        school = part[cols["SCHOOLCODE"]].str.zfill(7)
        is_school = part[cols["AGGREGATELEVEL"]].str.strip().str.upper().eq("S")
        raw = part[cols["TOTAL_ENR"]].str.strip()
        out = pd.DataFrame({
            "fall_year": part[cols["ACADEMICYEAR"]].map(fall_year),
            "aggregate": is_school.map({True: "school", False: "district"}),
            "code": (county + district + school.where(is_school, "")),
            "enrollment": pd.to_numeric(raw, errors="coerce"),
            "enrollment_type": "census day",
            "suppressed": raw.eq("*").astype(int),
        })
        return out.reset_index(drop=True)

    # Enrollment by School files, 1998 to 2022: one row per school, race or ethnicity, and gender
    data = df.assign(
        fall_year=df[cols["ACADEMIC_YEAR"]].map(fall_year),
        code=df[cols["CDS_CODE"]].str.strip().str.zfill(14),
        enrollment=pd.to_numeric(df[cols["ENR_TOTAL"]], errors="coerce").fillna(0),
        enrollment_type="P",
    )
    if "ENR_TYPE" in cols:
        data["enrollment_type"] = df[cols["ENR_TYPE"]].str.strip().str.upper()
        has_type = data.groupby("fall_year")["enrollment_type"].transform(lambda s: (s == enrollment_type).any())
        data = data[(data["enrollment_type"] == enrollment_type) | (~has_type & (data["enrollment_type"] == "P"))]
    schools = data.groupby(["fall_year", "code", "enrollment_type"], as_index=False)["enrollment"].sum().assign(aggregate="school")
    districts = schools.assign(code=schools["code"].str[:7]).groupby(["fall_year", "code", "enrollment_type"], as_index=False)["enrollment"].sum().assign(aggregate="district")
    return pd.concat([schools, districts], ignore_index=True).assign(suppressed=0)


def california_files_for(settings: dict, fall_years: List[int]) -> List[dict]:
    """Configured CDE files that cover any of the requested fall years."""
    files = settings["school_enrollment"]["california_files"]
    return [f for f in files if any(f["first_fall_year"] <= y <= f["last_fall_year"] for y in fall_years)]


def download_california(settings: dict, fall_years: List[int], session: requests.Session, cache: Path) -> pd.DataFrame:
    """California totals for the requested fall years, with the file each came from."""
    frames = []
    enrollment_type = settings["school_enrollment"].get("california_enrollment_type", "C")
    for f in california_files_for(settings, fall_years):
        totals = california_totals(read_cde_text(_fetch(f["url"], session, cache)), enrollment_type)
        frames.append(totals[totals["fall_year"].isin(fall_years)].assign(data_source=f["url"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["fall_year", "aggregate", "code", "enrollment", "enrollment_type", "suppressed", "data_source"])


# --- Nevada --------------------------------------------------------------------

def _header_row(sheet: pd.DataFrame) -> Optional[int]:
    for i in range(min(10, len(sheet))):
        names = {str(v).strip().lower() for v in sheet.iloc[i] if pd.notna(v)}
        if names & CODE_HEADERS and names & TOTAL_HEADERS:
            return i
    return None


def nevada_totals(sheets: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """School totals from one Nevada workbook, read with header=None.

    Uses sheets that have a school code and a total column. Sheets without a grade
    column are preferred. If only grade-level sheets exist, grades are added up.
    Returns code (as a whole number in text), enrollment, suppressed, and method.
    """
    total_rows, grade_rows = [], []
    for sheet in sheets.values():
        h = _header_row(sheet)
        if h is None:
            continue
        header = [str(v).strip() for v in sheet.iloc[h]]
        lower = [v.lower() for v in header]
        code_col = next(i for i, v in enumerate(lower) if v in CODE_HEADERS)
        total_col = next(i for i, v in enumerate(lower) if v in TOTAL_HEADERS)
        body = sheet.iloc[h + 1:, [code_col, total_col]].copy()
        body.columns = ["code", "raw"]
        body["code"] = pd.to_numeric(body["code"], errors="coerce")
        body = body.dropna(subset=["code"])
        body["code"] = body["code"].astype(int).astype(str)
        body["raw"] = body["raw"].astype(str).str.strip()
        (grade_rows if any(v in GRADE_HEADERS for v in lower) else total_rows).append(body)
    rows, method = (total_rows, "school total") if total_rows else (grade_rows, "sum of grades")
    if not rows:
        return pd.DataFrame(columns=["code", "enrollment", "suppressed", "method"])
    body = pd.concat(rows, ignore_index=True)
    body["enrollment"] = pd.to_numeric(body["raw"], errors="coerce")
    body["suppressed"] = body["raw"].eq("*").astype(int)
    out = body.groupby("code", as_index=False).agg(enrollment=("enrollment", lambda s: s.sum(min_count=1)), suppressed=("suppressed", "sum"))
    return out.assign(method=method)


def download_nevada(settings: dict, fall_years: List[int], session: requests.Session, cache: Path) -> pd.DataFrame:
    """Nevada school totals for the requested fall years that have a configured workbook."""
    frames = []
    files = {int(k): v for k, v in settings["school_enrollment"]["nevada_files"].items()}
    for year in fall_years:
        if year not in files:
            print(f"  no Nevada enrollment file configured for {year_label(year)}")
            continue
        sheets = pd.read_excel(io.BytesIO(_fetch(files[year], session, cache)), sheet_name=None, header=None, dtype=object)
        frames.append(nevada_totals(sheets).assign(fall_year=year, data_source=files[year]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["code", "enrollment", "suppressed", "method", "fall_year", "data_source"])


# --- Both states ---------------------------------------------------------------

def _code_key(state: str, code: str) -> str:
    code = str(code).strip()
    if state == "Nevada":
        return str(int(code)) if code.isdigit() else code
    return code


def build_enrollment(settings: dict, first_fall_year: int, last_fall_year: int,
                     session: Optional[requests.Session] = None,
                     california: Optional[pd.DataFrame] = None, nevada: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """One row per configured school and school year, in the School Enrollment layout plus review columns.

    california and nevada can be passed in (for tests); otherwise the files are downloaded.
    """
    years = list(range(first_fall_year, last_fall_year + 1))
    session = session or services.make_session()
    cache = outputs_dir(settings, "enrollment", "cache")
    schools = load_schools(settings)
    if california is None and (schools["state"] == "California").any():
        california = download_california(settings, years, session, cache)
    if nevada is None and (schools["state"] == "Nevada").any():
        nevada = download_nevada(settings, years, session, cache)

    rows = []
    for s in schools.itertuples():
        source = california if s.state == "California" else nevada
        for year in years:
            row = {"School_Name": s.school_name, "State": s.state, "Level_": s.level, "Year": year_label(year),
                   "Enrollment": None, "data_source": "", "school_id": None, "source_code": s.school_code, "note": ""}
            if not s.school_code:
                row.update(Enrollment=0, note="no state code (closed school); published as 0")
                rows.append(row)
                continue
            if source is None or source.empty:
                row["note"] = "no source file for this year"
                rows.append(row)
                continue
            match = source[(source["fall_year"] == year) & (source["code"].astype(str) == _code_key(s.state, s.school_code))]
            if s.state == "California":
                match = match[match["aggregate"] == (s.aggregate or "school")]
            if match.empty:
                row["note"] = "not found in source file"
            else:
                m = match.iloc[0]
                row.update(Enrollment=m["enrollment"], data_source=m["data_source"])
                notes = [f"type {m['enrollment_type']}" if "enrollment_type" in m and m["enrollment_type"] else "",
                         m["method"] if "method" in m and isinstance(m["method"], str) else "",
                         f"{int(m['suppressed'])} suppressed cells left out" if m.get("suppressed", 0) else ""]
                row["note"] = "; ".join(n for n in notes if n)
            rows.append(row)
    return pd.DataFrame(rows, columns=REVIEW_COLUMNS)


def compare_published(built: pd.DataFrame, published: pd.DataFrame) -> pd.DataFrame:
    """Built and published enrollment side by side by school and year."""
    keys = ["School_Name", "Year"]
    out = published[keys + ["Enrollment"]].rename(columns={"Enrollment": "published"}).merge(
        built[keys + ["Enrollment", "note"]].rename(columns={"Enrollment": "built"}), on=keys, how="outer", indicator=True)
    out["difference"] = out["built"] - out["published"]
    out["status"] = out["_merge"].map({"both": "in both", "left_only": "published only", "right_only": "new"}).astype(str)
    return out.drop(columns="_merge").sort_values(keys).reset_index(drop=True)


def split_new_rows(built: pd.DataFrame, published: pd.DataFrame) -> pd.DataFrame:
    """Rows for school years not yet published, in the School Enrollment layout."""
    have = set(zip(published["School_Name"], published["Year"]))
    new = built[[(n, y) not in have for n, y in zip(built["School_Name"], built["Year"])]]
    return new[new["Enrollment"].notna()][ENROLLMENT_COLUMNS]
