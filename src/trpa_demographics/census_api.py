"""Download data and variable definitions from the Census Bureau API.

How a download works, in plain language:
1. Read the list of variables to download (config/variables.csv).
2. Ask the Census API for up to 24 variables at a time, once per county.
   ACS requests include each estimate (E) and its margin of error (M).
3. Keep only the tracts or block groups inside the Tahoe Basin.
4. Reshape the result to one row per geography and variable,
   in the same layout as the Census Data table on the TRPA server.
Each finished request is saved as a checkpoint file. If the Census API
drops the connection, rerunning the same command skips finished requests.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from . import geography
from .config import census_geom_year, county_table, outputs_dir
from .tables import RAW_COLUMNS, read_table, write_table

# Census annotation values that appear in place of real numbers.
# See https://www.census.gov/data/developers/data-sets/acs-1year/notes-on-acs-estimate-and-annotation-values.html
ESTIMATE_SENTINELS = {-999999999, -888888888, -666666666, -555555555, -333333333, -222222222}
MOE_CONTROLLED = -555555555  # estimate is controlled, so the margin of error is zero
MOE_SENTINELS = {-999999999, -888888888, -666666666, -333333333, -222222222}


class CensusApiError(RuntimeError):
    """Raised when the Census API rejects a request."""


def require_api_key(api_key: Optional[str], settings: dict) -> None:
    """Stop with a clear message when no Census API key is set.

    Since 2026 the Census API refuses data requests without a key. Variable
    definitions (labels and table lists) still work without one.
    """
    if not api_key:
        raise CensusApiError(
            f"No Census API key found. Set {settings['census_api']['api_key_env_var']} in a .env file "
            "in the repository folder or as an environment variable. See docs/setup.md."
        )


def is_acs(dataset: str) -> bool:
    return str(dataset).lower().startswith("acs/")


def moe_code(code: str) -> str:
    """Return the margin of error code for an ACS estimate code (B01001_001E becomes B01001_001M)."""
    return code[:-1] + "M" if code.endswith("E") else code + "M"


def table_id(code: str) -> str:
    """Return the Census table for a variable code (B01001_001E becomes B01001)."""
    return code.split("_")[0]


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(text)).strip("_")


def build_request_url(base_url: str, year: int, dataset: str, get_fields: List[str],
                      sample_level: str, state: str, county: str, api_key: Optional[str]) -> str:
    """Build a Census API URL for one county.

    Block groups and blocks must be requested inside tracts, so they add tract:*.
    """
    level = sample_level.replace(" ", "%20")
    inside = f"state:{state}%20county:{county}"
    if sample_level in ("block group", "block"):
        inside += "%20tract:*"
    url = f"{base_url}/{year}/{dataset}?get={','.join(get_fields)}&for={level}:*&in={inside}"
    return url + (f"&key={api_key}" if api_key else "")


def _request(session: requests.Session, url: str, timeout: int) -> list:
    response = session.get(url, timeout=timeout)
    if response.status_code == 204:
        return []
    if response.status_code != 200:
        raise CensusApiError(f"Census API returned {response.status_code}: {response.text[:300]}")
    if "Missing Key" in response.text[:2000] or "Invalid Key" in response.text[:2000]:
        raise CensusApiError("The Census API rejected the request because the API key is missing or invalid.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise CensusApiError(f"Census API returned a non-JSON response: {response.text[:300]}") from exc
    return payload if isinstance(payload, list) else []


def download_batch(session, settings, api_key, year, dataset, sample_level, codes) -> Tuple[pd.DataFrame, List[str]]:
    """Download a batch of variables for all configured counties.

    Returns the wide result and a list of codes the API did not recognize.
    If the API rejects the batch, each code is tried alone so one bad code
    does not stop the rest.
    """
    cfg = settings["census_api"]
    require_api_key(api_key, settings)
    fields = ["GEO_ID"]
    for code in codes:
        fields.append(code)
        if is_acs(dataset):
            fields.append(moe_code(code))
    frames = []
    for row in county_table(settings).itertuples():
        url = build_request_url(cfg["base_url"], year, dataset, fields, sample_level, row.state, row.county, api_key)
        try:
            payload = _request(session, url, cfg["timeout_seconds"])
        except CensusApiError as exc:
            rejected = "unknown variable" in str(exc).lower() or "error:" in str(exc).lower()
            if not rejected:
                raise
            if len(codes) == 1:
                return pd.DataFrame(), list(codes)
            return _download_one_by_one(session, settings, api_key, year, dataset, sample_level, codes)
        if len(payload) > 1:
            frames.append(pd.DataFrame(payload[1:], columns=payload[0]))
        time.sleep(cfg["pause_between_requests_seconds"])
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), []


_GEO_KEYS = ("GEO_ID", "state", "county", "tract", "block group", "block")


def _download_one_by_one(session, settings, api_key, year, dataset, sample_level, codes):
    """Retry a rejected batch one variable at a time and report the codes the API rejects."""
    merged, bad = None, []
    for code in codes:
        part, bad_one = download_batch(session, settings, api_key, year, dataset, sample_level, [code])
        bad += bad_one
        if bad_one or part.empty:
            continue
        keys = [c for c in _GEO_KEYS if c in part.columns]
        merged = part if merged is None else merged.merge(part, on=keys, how="outer")
    return (merged if merged is not None else pd.DataFrame()), bad


def wide_to_long(wide: pd.DataFrame, batch: pd.DataFrame, year: int, dataset: str, sample_level: str,
                 geom_year: int, tahoe: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Reshape a wide API result to one row per geography and variable, filtered to the basin.

    Returns the long table and a table of Census annotation values that were replaced with blanks.
    """
    if wide.empty:
        return pd.DataFrame(columns=RAW_COLUMNS), pd.DataFrame()
    wide = wide.copy()
    wide["GEO_ID"] = geography.strip_geo_id(wide["GEO_ID"])
    wide["TRPAID"] = geography.make_trpaid(wide["GEO_ID"], geom_year)
    basin = tahoe.loc[tahoe["YEAR"] == geom_year, ["TRPAID", "NEIGHBORHOOD"]].drop_duplicates("TRPAID")
    wide = wide.merge(basin, on="TRPAID", how="inner")
    rows, notes = [], []
    for var in batch.itertuples():
        if var.variable_code not in wide.columns:
            continue
        part = pd.DataFrame({
            "GEO_ID": wide["GEO_ID"],
            "value": pd.to_numeric(wide[var.variable_code], errors="coerce"),
            "MarginOfError": pd.to_numeric(wide[moe_code(var.variable_code)], errors="coerce")
            if is_acs(dataset) and moe_code(var.variable_code) in wide.columns else np.nan,
            "state": wide["state"], "county": wide["county"],
            "tract": wide.get("tract", pd.Series(pd.NA, index=wide.index)),
            "block_group": wide.get("block group", pd.Series(pd.NA, index=wide.index)),
            "variable_code": var.variable_code, "variable_name": var.variable_name,
            "variable_category": var.variable_category, "year_sample": int(year),
            "sample_level": sample_level, "dataset": dataset, "census_geom_year": int(geom_year),
            "TRPAID": wide["TRPAID"], "NEIGHBORHOOD": wide["NEIGHBORHOOD"],
        })
        flagged = part["value"].isin(ESTIMATE_SENTINELS)
        if flagged.any():
            notes.append(part.loc[flagged, ["TRPAID", "variable_code", "year_sample", "sample_level", "value"]]
                         .rename(columns={"value": "census_annotation"}))
            part.loc[flagged, "value"] = np.nan
        part.loc[part["MarginOfError"] == MOE_CONTROLLED, "MarginOfError"] = 0
        part.loc[part["MarginOfError"].isin(MOE_SENTINELS), "MarginOfError"] = np.nan
        rows.append(part)
    long = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=RAW_COLUMNS)
    return long[RAW_COLUMNS], (pd.concat(notes, ignore_index=True) if notes else pd.DataFrame())


def applies_to_year(spec: str, year: int) -> bool:
    """Read the years column of config/variables.csv.

    Blank means every year. "2020" means only 2020. "2015-" means 2015 and later.
    "-2014" means 2014 and earlier. "2011-2014" is a range. Separate several with semicolons.
    """
    spec = str(spec or "").strip()
    if not spec or spec.lower() == "nan":
        return True
    for part in spec.split(";"):
        part = part.strip()
        if "-" in part:
            start, end = (p.strip() for p in part.split("-", 1))
            if (not start or year >= int(start)) and (not end or year <= int(end)):
                return True
        elif part and int(part) == int(year):
            return True
    return False


def expand_variable_list(variables: pd.DataFrame, dataset: Optional[str] = None,
                         categories: Optional[List[str]] = None, active_only: bool = True,
                         year: Optional[int] = None) -> pd.DataFrame:
    """Expand config/variables.csv to one row per variable and sample level, with optional filters.

    When year is given, rows whose years column excludes that year are dropped.
    """
    v = variables.copy()
    if year is not None and "years" in v.columns:
        v = v[v["years"].map(lambda spec: applies_to_year(spec, year))]
    if active_only and "active" in v.columns:
        v = v[v["active"].astype(str).str.upper().str.startswith("Y")]
    if dataset:
        v = v[v["dataset"] == dataset]
    if categories:
        v = v[v["variable_category"].isin(categories)]
    v = v.assign(sample_level=v["sample_level"].astype(str).str.split(";")).explode("sample_level")
    v["sample_level"] = v["sample_level"].str.strip().str.lower()
    return v.reset_index(drop=True)


def download_year(settings: dict, variables: pd.DataFrame, year: int, tahoe: pd.DataFrame,
                  api_key: Optional[str], session: requests.Session, label: Optional[str] = None) -> dict:
    """Download every variable in a variable list for one year.

    Writes these files under outputs/downloads/<year>/:
      census_data_<year>.csv      the combined long table, ready for QAQC
      annotations_<year>.csv      Census annotation values replaced with blanks
      unknown_variables_<year>.csv codes the Census API did not recognize
    Returns a dictionary with the paths and row counts.
    """
    folder = outputs_dir(settings, "downloads", year)
    checkpoints = outputs_dir(settings, "downloads", year, "_checkpoints")
    size = int(settings["census_api"]["max_variables_per_request"])
    geom_year = census_geom_year(year, settings)
    parts, notes, unknown = [], [], []
    if "years" in variables.columns:
        variables = variables[variables["years"].map(lambda spec: applies_to_year(spec, year))]
    for (dataset, level), group in variables.groupby(["dataset", "sample_level"], sort=False):
        group = group.drop_duplicates("variable_code")
        for start in range(0, len(group), size):
            batch = group.iloc[start:start + size]
            digest = hashlib.md5(",".join(sorted(batch["variable_code"])).encode()).hexdigest()[:10]
            ckpt = checkpoints / f"{_slug(dataset)}_{_slug(level)}_{digest}.csv"
            if ckpt.exists():
                print(f"  skip (already downloaded): {dataset} {level} batch {start // size + 1}")
                parts.append(read_table(ckpt))
                continue
            print(f"  downloading {len(batch)} variables: {dataset} {level} batch {start // size + 1}")
            wide, bad = download_batch(session, settings, api_key, year, dataset, level, list(batch["variable_code"]))
            unknown += [{"variable_code": b, "dataset": dataset, "sample_level": level, "year_sample": year} for b in bad]
            long, note = wide_to_long(wide, batch, year, dataset, level, geom_year, tahoe)
            write_table(long, ckpt, RAW_COLUMNS)
            parts.append(long)
            if not note.empty:
                notes.append(note)
    combined = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=RAW_COLUMNS)
    name = f"census_data_{year}" + (f"_{_slug(label)}" if label else "")
    out = {"data": write_table(combined, folder / f"{name}.csv", RAW_COLUMNS), "rows": len(combined)}
    if notes:
        out["annotations"] = write_table(pd.concat(notes), folder / f"annotations_{year}.csv")
    if unknown:
        out["unknown_variables"] = write_table(pd.DataFrame(unknown), folder / f"unknown_variables_{year}.csv")
    return out


# ---------------------------------------------------------------------------
# Variable definitions (labels, concepts, and table structure)
# ---------------------------------------------------------------------------

def _cache_path(settings: dict, year: int, dataset: str, name: str) -> Path:
    return outputs_dir(settings, "cache", "census_metadata") / f"{year}_{_slug(dataset)}_{name}.json"


def _cached_json(session, settings, url: str, cache: Path) -> dict:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    response = session.get(url, timeout=settings["census_api"]["timeout_seconds"] * 3)
    if response.status_code != 200:
        raise CensusApiError(f"Could not read {url}: {response.status_code}")
    cache.write_text(response.text, encoding="utf-8")
    return response.json()


def _metadata_frame(payload: dict) -> pd.DataFrame:
    rows = []
    for name, info in payload.get("variables", {}).items():
        rows.append({
            "variable_code": name,
            "label": info.get("label", ""),
            "concept": info.get("concept", ""),
            "table": info.get("group", ""),
            "predicate_type": info.get("predicateType", ""),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Drop annotation and margin of error entries and API keywords such as "for" and "NAME".
    df = df[~df["variable_code"].str.match(r".*(EA|MA|M|PM)$") & ~df["table"].isin(["", "N/A"])]
    df["label_plain"] = df["label"].str.replace("Estimate!!", "", regex=False).str.replace("!!", ": ", regex=False).str.replace("::", ":", regex=False)
    return df.sort_values("variable_code").reset_index(drop=True)


def table_metadata(settings, session, year: int, dataset: str, table: str) -> pd.DataFrame:
    """Return the variables in one Census table with labels and concept."""
    url = f"{settings['census_api']['base_url']}/{year}/{dataset}/groups/{table}.json"
    return _metadata_frame(_cached_json(session, settings, url, _cache_path(settings, year, dataset, table)))


def all_metadata(settings, session, year: int, dataset: str) -> pd.DataFrame:
    """Return every variable in a dataset. The first call downloads a large file and caches it."""
    url = f"{settings['census_api']['base_url']}/{year}/{dataset}/variables.json"
    return _metadata_frame(_cached_json(session, settings, url, _cache_path(settings, year, dataset, "all")))


def search_variables(settings, session, year: int, dataset: str, text: Optional[str] = None,
                     table: Optional[str] = None) -> pd.DataFrame:
    """Find Census variables by table code or by words in the label or concept.

    Every word in text must appear in the label or concept (case does not matter).
    """
    meta = table_metadata(settings, session, year, dataset, table.upper()) if table else all_metadata(settings, session, year, dataset)
    if text:
        haystack = (meta["label"] + " " + meta["concept"]).str.lower()
        for word in text.lower().split():
            meta = meta[haystack.loc[meta.index].str.contains(word, regex=False)]
    return meta.reset_index(drop=True)


def draft_variable_rows(found: pd.DataFrame, dataset: str, category: str, sample_level: str) -> pd.DataFrame:
    """Turn search results into rows in the config/variables.csv format, ready to review and paste."""
    names = found["label_plain"].str.replace(r"^Total:\s*", "", regex=True).str.rstrip(":").replace("", "Total")
    return pd.DataFrame({
        "variable_code": found["variable_code"],
        "variable_name": names,
        "variable_category": category,
        "dataset": dataset,
        "sample_level": sample_level,
        "aggregation": np.where(found["label"].str.contains("median|mean|average|aggregate|percent|ratio", case=False), "none", "sum"),
        "active": "Y",
        "notes": "Census concept: " + found["concept"].str.title(),
    })
