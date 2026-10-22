"""Tahoe Basin geography: the TRPAID key and geography labels.

TRPAID is the Census GEOID plus the Census boundary year, stored as text.
Example: tract 06017030201 on 2020 boundaries is TRPAID 060170302012020.
The Tahoe Census Geography layer (Demographics MapServer/27) lists every
TRPAID inside the basin. Filtering a download to that list keeps only
Tahoe geographies.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import requests

from . import services
from .config import county_table

# Layer 27 stores GEOGRAPHY in title case. Downloads use the Census API spelling.
_GEOGRAPHY_TO_LEVEL = {"tract": "tract", "block group": "block group", "block": "block", "zip code": "ZIP CODE"}


def get_tahoe_geometry(settings: dict, session: Optional[requests.Session] = None) -> pd.DataFrame:
    """Return the basin geography list: YEAR, STATE, GEOGRAPHY, TRPAID, NEIGHBORHOOD, sample_level.

    The layer's GEOID field is a number and has lost leading zeros,
    so only TRPAID is used for joins.
    """
    df = services.query_layer(
        settings["services"]["tahoe_geometry"],
        out_fields="YEAR,STATE,GEOGRAPHY,TRPAID,NEIGHBORHOOD",
        session=session,
    )
    df["YEAR"] = pd.to_numeric(df["YEAR"], errors="coerce").astype("Int64")
    for col in ("STATE", "GEOGRAPHY", "TRPAID", "NEIGHBORHOOD"):
        df[col] = df[col].astype("string").str.strip()
    df["sample_level"] = df["GEOGRAPHY"].str.lower().map(_GEOGRAPHY_TO_LEVEL)
    return df


def make_trpaid(geo_id: pd.Series, geom_year: int) -> pd.Series:
    """Build TRPAID from a Census GEO_ID and the boundary year."""
    return geo_id.astype(str) + str(int(geom_year))


def strip_geo_id(api_geo_id: pd.Series) -> pd.Series:
    """Turn an API GEO_ID such as 1400000US06017030201 into 06017030201."""
    return api_geo_id.astype(str).str.split("US").str[-1]


def add_geography_labels(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Add county_name, state_name, and north_south from the state and county FIPS codes."""
    lookup = county_table(settings)
    out = df.copy()
    out["state"] = out["state"].astype(str).str.zfill(2)
    out["county"] = out["county"].astype(str).str.zfill(3)
    out = out.drop(columns=[c for c in ("county_name", "state_name", "north_south") if c in out.columns])
    return out.merge(lookup, on=["state", "county"], how="left")
