"""Read-only access to TRPA ArcGIS REST services.

Uses plain HTTP requests so it runs in any Python environment.
There are no functions here that add, update, or delete records.
"""
from __future__ import annotations

import json
import time
from typing import Iterable, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def make_session() -> requests.Session:
    """Return an HTTP session that retries on rate limits and server errors."""
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get_json(session: requests.Session, url: str, params: dict, timeout: int = 120) -> dict:
    response = session.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"ArcGIS service error from {url}: {payload['error']}")
    return payload


def layer_info(url: str, session: Optional[requests.Session] = None) -> dict:
    """Return the layer or table definition (fields, maxRecordCount, and so on)."""
    return _get_json(session or make_session(), url, {"f": "json"})


def query_layer(
    url: str,
    where: str = "1=1",
    out_fields: str = "*",
    session: Optional[requests.Session] = None,
    order_by: str = "OBJECTID",
) -> pd.DataFrame:
    """Return every matching record from a layer or table as a DataFrame.

    Pages through results with resultOffset, so services with a 2,000 record limit
    return the full result.
    """
    session = session or make_session()
    page_size = int(layer_info(url, session).get("maxRecordCount", 1000))
    records, offset = [], 0
    while True:
        payload = _get_json(
            session,
            f"{url}/query",
            {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "false",
                "orderByFields": order_by,
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "json",
            },
        )
        features = payload.get("features", [])
        records.extend(f["attributes"] for f in features)
        if not features or (len(features) < page_size and not payload.get("exceededTransferLimit")):
            break
        offset += len(features)
        time.sleep(0.1)
    return pd.DataFrame(records)


def query_statistics(
    url: str,
    group_by: Iterable[str],
    statistics: list,
    where: str = "1=1",
    having: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """Run a server-side group-by summary and return one row per group.

    statistics is a list of (statistic_type, field, output_name) tuples,
    for example [("count", "OBJECTID", "n"), ("max", "year_sample", "last_year")].
    """
    session = session or make_session()
    group_by = list(group_by)
    out_stats = [
        {"statisticType": t, "onStatisticField": f, "outStatisticFieldName": n} for t, f, n in statistics
    ]
    params = {
        "where": where,
        "groupByFieldsForStatistics": ",".join(group_by),
        "outStatistics": json.dumps(out_stats),
        "orderByFields": ",".join(group_by),
        "f": "json",
    }
    if having:
        params["having"] = having
    records, offset = [], 0
    while True:
        payload = _get_json(session, f"{url}/query", {**params, "resultOffset": offset, "resultRecordCount": 2000})
        features = payload.get("features", [])
        records.extend(f["attributes"] for f in features)
        if len(features) < 2000:
            break
        offset += len(features)
    return pd.DataFrame(records)


def sql_in(values: Iterable) -> str:
    """Format values for a SQL IN clause, escaping single quotes."""
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values)
