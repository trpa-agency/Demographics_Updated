"""Jobs by ZIP code from County Business Patterns.

The Census Bureau publishes employees, establishments, and payroll by ZIP code
each year. From 2018 they are in the cbp dataset. Before that they are in the
ZIP Code Business Patterns dataset (zbp). Which ZIP codes count as Tahoe Basin,
their county and shore, and the years each ZIP code is used are set in
config/jobs_zip_codes.csv. The variables are in config/jobs_variables.csv.

Variable and flag names change between years, so the module reads each year's
variable list from the Census API first (this needs no key). It asks only for
the variables and flags that year publishes.

When a ZIP code's value was withheld to protect businesses, the Census Bureau
publishes 0 with a letter in the suppression flag. The toolkit leaves the value
blank and writes the withheld flag from settings ("D") in value_flag.

Output matches the Census_Jobs table (Demographics MapServer/35):
value, value_flag, zip_code, year, variable_name, State, County, Basin, CBP_Name.

replace_published builds append, retire, and comparison files that swap
published years (for example the 1998 to 2017 workbook values) for downloads.
It only reads the service.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from . import services
from .census_api import CensusApiError, _request, applies_to_year, require_api_key
from .config import REPO_ROOT

JOBS_COLUMNS = ["value", "value_flag", "zip_code", "year", "variable_name", "State", "County", "Basin", "CBP_Name"]
SELECTOR_PATTERN = re.compile(r"^(NAICS\d{4}|EMPSZES|LFO)$")


def dataset_for_year(settings: dict, year: int) -> dict:
    """Return the dataset and ZIP predicates to use for a year."""
    for entry in sorted(settings["jobs"]["datasets"], key=lambda e: e["first_year"], reverse=True):
        if year >= entry["first_year"]:
            return entry
    raise ValueError(f"No jobs dataset configured for {year}")


def load_zip_codes(settings: dict, year: Optional[int] = None) -> pd.DataFrame:
    """ZIP codes from config/jobs_zip_codes.csv, limited to those used in a year when year is given."""
    zips = pd.read_csv(REPO_ROOT / settings["jobs"]["zip_list"], dtype=str).fillna("")
    if year is not None and "years" in zips.columns:
        zips = zips[zips["years"].apply(lambda spec: applies_to_year(spec, year))]
    return zips


def dataset_variables(session, settings: dict, year: int, dataset: str) -> set:
    """Names of the variables a Census dataset publishes for a year (no key needed)."""
    url = f"{settings['census_api']['base_url']}/{year}/{dataset}/variables.json"
    response = session.get(url, timeout=settings["census_api"]["timeout_seconds"])
    if response.status_code != 200:
        raise CensusApiError(f"Could not read the variable list at {url} ({response.status_code})")
    return set(response.json().get("variables", {}))


def _first_present(options: str, available: set) -> str:
    for name in str(options or "").split(";"):
        if name.strip() and name.strip() in available:
            return name.strip()
    return ""


def fields_for_year(variables: pd.DataFrame, available: set) -> Tuple[List[str], Dict[str, dict], List[str]]:
    """Choose the value, flag, and selector fields a year publishes.

    Returns the fields to request, a map of variable code to its flag fields, and
    the selector fields (industry, size class, legal form) used to find the total row.
    """
    fields, flags = [], {}
    for v in variables.itertuples():
        if v.variable_code not in available:
            continue
        noise = _first_present(v.noise_flag_codes, available)
        withheld = _first_present(v.suppression_flag_code, available)
        flags[v.variable_code] = {"noise": noise, "withheld": withheld}
        fields += [v.variable_code] + [f for f in (noise, withheld) if f]
    selectors = sorted(name for name in available if SELECTOR_PATTERN.match(name))
    return list(dict.fromkeys(fields)), flags, selectors


def pick_total_row(payload: list, selectors: List[str], total_codes: Dict[str, List[str]]) -> Optional[dict]:
    """Return the all-industries, all-sizes row from a Census response.

    A ZIP code request can return one row per industry or size class. The total
    row has the codes listed in settings (jobs.total_codes) in each selector field.
    """
    if len(payload) < 2:
        return None
    rows = [dict(zip(payload[0], r)) for r in payload[1:]]
    for selector in selectors:
        key = "NAICS" if selector.startswith("NAICS") else selector
        codes = set(total_codes.get(key, []))
        if codes and any(selector in r for r in rows):
            rows = [r for r in rows if str(r.get(selector, "")).strip() in codes]
    if len(rows) != 1:
        raise CensusApiError(f"Expected one total row, found {len(rows)}. Check jobs.total_codes in settings.")
    return rows[0]


def _fetch_zip(session, settings, year, entry, zip_code, fields, selectors, api_key) -> Optional[dict]:
    cfg = settings["census_api"]
    get = ",".join(fields + selectors)
    for predicate in entry["zip_predicates"]:
        url = (f"{cfg['base_url']}/{year}/{entry['dataset']}?get={get}"
               f"&for={predicate.replace(' ', '%20')}:{zip_code}&key={api_key}")
        try:
            payload = _request(session, url, cfg["timeout_seconds"])
        except CensusApiError as exc:
            if "unknown variable" in str(exc).lower() or "key" in str(exc).lower():
                raise
            continue
        return pick_total_row(payload, selectors, settings["jobs"].get("total_codes", {}))
    return None


def download_jobs(settings: dict, years: List[int], api_key: Optional[str], session: requests.Session) -> pd.DataFrame:
    """Download jobs variables for every listed ZIP code and year.

    Variables and flags a year does not publish are skipped for that year.
    ZIP codes with no published data are skipped and noted in the console.
    """
    require_api_key(api_key, settings)
    variables = pd.read_csv(REPO_ROOT / settings["jobs"]["variables"], dtype=str).fillna("")
    withheld_flag = settings["jobs"].get("withheld_flag", "D")
    rows = []
    for year in years:
        entry = dataset_for_year(settings, year)
        available = dataset_variables(session, settings, year, entry["dataset"])
        fields, flags, selectors = fields_for_year(variables, available)
        missing = sorted(set(variables["variable_code"]) - set(flags))
        if missing:
            print(f"  {entry['dataset']} {year} does not publish {', '.join(missing)}")
        for z in load_zip_codes(settings, year).itertuples():
            record = _fetch_zip(session, settings, year, entry, z.zip_code, fields, selectors, api_key)
            if record is None:
                print(f"  no {entry['dataset']} data for ZIP {z.zip_code} in {year}")
                continue
            for v in variables.itertuples():
                if v.variable_code not in flags:
                    continue
                value = pd.to_numeric(record.get(v.variable_code), errors="coerce")
                flag = record.get(flags[v.variable_code]["noise"], "") if flags[v.variable_code]["noise"] else ""
                withheld = record.get(flags[v.variable_code]["withheld"], "") if flags[v.variable_code]["withheld"] else ""
                if str(withheld or "").strip():
                    value, flag = float("nan"), withheld_flag
                rows.append({
                    "value": value, "value_flag": flag or "",
                    "zip_code": z.zip_code, "year": int(year), "variable_name": v.variable_name,
                    "State": z.state, "County": z.county, "Basin": z.tahoe_basin,
                    "CBP_Name": z.name.split(",")[0].title(),
                })
            time.sleep(settings["census_api"]["pause_between_requests_seconds"])
    return pd.DataFrame(rows, columns=JOBS_COLUMNS)


def summarize_jobs(jobs: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Add up basin ZIP codes to Basin, North Lake, and South Lake totals by year and variable.

    withheld_zip_codes counts the ZIP codes left out of a total because their value was withheld.
    """
    zips = load_zip_codes(settings)[["zip_code", "north_south"]].drop_duplicates("zip_code")
    basin = jobs[jobs["Basin"] == "Y"].merge(zips, on="zip_code", how="left")
    basin = basin.assign(withheld=basin["value"].isna().astype(int))

    def roll(df, keys):
        return df.groupby(keys, as_index=False).agg(value=("value", lambda s: s.sum(min_count=1)), withheld_zip_codes=("withheld", "sum"))

    total = roll(basin, ["year", "variable_name"]).assign(Geography=settings.get("basin_label", "Basin"))
    shore = roll(basin, ["year", "variable_name", "north_south"]).rename(columns={"north_south": "Geography"})
    return pd.concat([total, shore], ignore_index=True)[["Geography", "year", "variable_name", "value", "withheld_zip_codes"]]


def replace_published(downloaded: pd.DataFrame, settings: dict, years: List[int],
                      session=None, published: Optional[pd.DataFrame] = None) -> Dict[str, pd.DataFrame]:
    """Build files that replace published Census_Jobs years with downloaded values.

    Returns three tables:
      append      the downloaded rows, in the Census_Jobs layout
      retire      OBJECTIDs of every published row in those years, with the reason
      comparison  published and downloaded values side by side for each ZIP code, year, and variable

    Reads the published table only. Nothing is written to the service.
    """
    if published is None:
        where = f"year >= {min(years)} AND year <= {max(years)}"
        published = services.query_layer(settings["services"]["census_jobs"], where=where, session=session)
    published = published.copy()
    published["zip_code"] = pd.to_numeric(published["zip_code"], errors="coerce").astype("Int64").astype(str).str.zfill(5)
    published["year"] = pd.to_numeric(published["year"], errors="coerce").astype(int)
    published = published[published["year"].isin(years)]
    reason = f"replaced by {settings['jobs'].get('replacement_source', 'Census Business Patterns download')}"
    retire = published[["OBJECTID"]].assign(reason=reason)

    keys = ["zip_code", "year", "variable_name"]
    down = downloaded.assign(zip_code=downloaded["zip_code"].astype(str).str.zfill(5), year=downloaded["year"].astype(int))
    comparison = published[keys + ["value", "CBP_Name"]].rename(columns={"value": "published_value", "CBP_Name": "published_name"}).merge(
        down[keys + ["value", "value_flag", "CBP_Name"]].rename(columns={"value": "downloaded_value", "CBP_Name": "downloaded_name"}),
        on=keys, how="outer", indicator=True)
    comparison["difference"] = comparison["downloaded_value"] - comparison["published_value"]
    comparison["percent_difference"] = (comparison["difference"] / comparison["published_value"].where(comparison["published_value"] != 0) * 100).round(1)
    comparison["status"] = comparison["_merge"].map({"both": "in both", "left_only": "published only", "right_only": "downloaded only"}).astype(str)
    comparison = comparison.drop(columns="_merge").sort_values(keys).reset_index(drop=True)
    return {"append": down[JOBS_COLUMNS], "retire": retire, "comparison": comparison}
