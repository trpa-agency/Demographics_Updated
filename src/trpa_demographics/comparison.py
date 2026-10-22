"""Download comparison geographies: whole counties, states, and metro areas.

TRPA charts often compare the basin with the full counties around it, Carson
City, California and Nevada, the Reno-Sparks and Sacramento metro areas, and
the San Francisco Bay Area. The list lives in comparison_geographies in
config/settings.json. Results use the summary layout (Geography, variable,
value) so they sit next to basin summaries.
"""
from __future__ import annotations

import time
from typing import List, Optional

import numpy as np
import pandas as pd
import requests

from .census_api import CensusApiError, _request, is_acs, moe_code, require_api_key
from .tables import SUMMARY_COLUMNS


def _number(text) -> float:
    """Convert an API value to a number. Missing or text values become NaN."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return np.nan


def comparison_url(base_url: str, year: int, dataset: str, fields: List[str], geo: dict, api_key: str) -> str:
    """Build the API URL for one comparison geography."""
    url = f"{base_url}/{year}/{dataset}?get={','.join(fields)}&for={geo['for'].replace(' ', '%20')}"
    if geo.get("in"):
        url += f"&in={geo['in'].replace(' ', '%20')}"
    return url + f"&key={api_key}"


def download_comparison(settings: dict, variables: pd.DataFrame, year: int, api_key: Optional[str],
                        session: requests.Session, geographies: Optional[List[str]] = None) -> pd.DataFrame:
    """Download variables for each comparison geography in one year.

    variables needs variable_code, variable_name, variable_category, and dataset.
    Returns the summary layout plus MarginOfError and a sample_level of county,
    state, MSA, or CSA.
    """
    require_api_key(api_key, settings)
    cfg = settings["census_api"]
    size = int(cfg["max_variables_per_request"])
    geos = [g for g in settings["comparison_geographies"]
            if (not geographies or g["name"] in geographies) and int(year) >= int(g.get("first_year", 0))]
    rows = []
    for dataset, group in variables.drop_duplicates(["variable_code", "dataset"]).groupby("dataset"):
        for start in range(0, len(group), size):
            batch = group.iloc[start:start + size]
            fields = []
            for code in batch["variable_code"]:
                fields += [code, moe_code(code)] if is_acs(dataset) else [code]
            for geo in geos:
                try:
                    payload = _request(session, comparison_url(cfg["base_url"], year, dataset, fields, geo, api_key), cfg["timeout_seconds"])
                except CensusApiError as exc:
                    print(f"  skipped {geo['name']} {dataset} {year}: {exc}")
                    continue
                if len(payload) < 2:
                    continue
                record = dict(zip(payload[0], payload[1]))
                for var in batch.itertuples():
                    value = _number(record.get(var.variable_code))
                    moe = _number(record.get(moe_code(var.variable_code))) if is_acs(dataset) else np.nan
                    rows.append({
                        "variable_code": var.variable_code, "variable_name": var.variable_name,
                        "value": np.nan if value < -99999999 else value,
                        "Geography": geo["name"], "year_sample": int(year), "dataset": dataset,
                        "sample_level": geo["level"], "Category": var.variable_category,
                        "MarginOfError": 0.0 if moe == -555555555 else (np.nan if moe < -99999999 else moe),
                    })
                time.sleep(cfg["pause_between_requests_seconds"])
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS + ["MarginOfError"])
