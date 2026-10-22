"""Column layouts and CSV helpers shared by every step.

RAW_COLUMNS matches the Census Data table (Demographics MapServer/28),
without OBJECTID, Data_Scale, and delete_flag, which the database assigns.
SUMMARY_COLUMNS matches the Climate Resilience Dashboard Census Data table
(LTinfo_Climate_Resilience_Dashboard MapServer/135). Margins of error for
summaries are written to a separate file because that table has no field for them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Union

import pandas as pd

RAW_COLUMNS = [
    "GEO_ID", "value", "MarginOfError", "state", "county", "tract", "block_group",
    "variable_code", "variable_name", "variable_category", "year_sample", "sample_level",
    "dataset", "census_geom_year", "TRPAID", "NEIGHBORHOOD",
]

SUMMARY_COLUMNS = [
    "variable_code", "variable_name", "value", "Geography",
    "year_sample", "dataset", "sample_level", "Category",
]

# Demographic Summaries (Demographics MapServer/18), kept in sync with the dashboard table.
LAYER18_COLUMNS = ["Category", "Code", "Value", "Year", "Source", "Notes", "Geography"]

# One row per geography, variable, year, level, and dataset.
RAW_KEY = ["TRPAID", "variable_code", "year_sample", "sample_level", "dataset"]
SUMMARY_KEY = ["Geography", "variable_code", "year_sample", "sample_level", "dataset", "Category"]

TEXT_COLUMNS = [
    "GEO_ID", "state", "county", "tract", "block_group", "variable_code", "variable_name",
    "variable_category", "sample_level", "dataset", "TRPAID", "NEIGHBORHOOD", "Geography", "Category",
    "Code", "Source", "Notes", "trpaid", "zip_code",
]


def read_table(paths: Union[str, Path, Iterable[Union[str, Path]]]) -> pd.DataFrame:
    """Read one or more CSV files with FIPS and ID columns kept as text.

    Reading FIPS codes as numbers drops leading zeros (06 becomes 6),
    which breaks TRPAID joins. This reader prevents that.
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    frames = []
    for p in paths:
        df = pd.read_csv(p, dtype={c: str for c in TEXT_COLUMNS}, keep_default_na=True)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    for col in ("value", "MarginOfError"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("year_sample", "census_geom_year"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def write_table(df: pd.DataFrame, path: Union[str, Path], columns: list = None) -> Path:
    """Write a table to CSV in a fixed column order and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if columns:
        for col in columns:
            if col not in out.columns:
                out[col] = pd.NA
        out = out[columns]
    out.to_csv(path, index=False)
    return path
