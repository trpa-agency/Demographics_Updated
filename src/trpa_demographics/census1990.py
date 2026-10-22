"""Import 1990 Census Summary Tape File 3 (STF3) tables from DBF files.

The Census API does not serve 1990 data, so 1990 values come from the STF3 DBF
files (one file per table segment and state, such as stf301ca.dbf). This module
reads those files without extra packages, keeps basin tracts, and returns rows in
the Census Data layout with dataset dec/sf3 and year 1990, the same as the 1990
rows already published.

Tract numbers in the DBF files leave off a "00" suffix: TRACTBNA 9502 is tract
950200, while 950198 already has six digits. Short values get "00" added.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Iterable, List

import numpy as np
import pandas as pd

from .tables import RAW_COLUMNS


def read_dbf(path, columns: Iterable[str] = None) -> pd.DataFrame:
    """Read a dBase III table into a DataFrame of text columns.

    Only the columns asked for are kept (all when columns is None).
    Deleted records are skipped.
    """
    with open(path, "rb") as f:
        header = f.read(32)
        n_records, header_len, record_len = struct.unpack("<IHH", header[4:12])
        fields = []
        while True:
            desc = f.read(32)
            if desc[0] == 0x0D:
                break
            name = desc[:11].split(b"\x00")[0].decode("ascii").strip()
            fields.append((name, desc[16]))
        f.seek(header_len)
        wanted = set(columns) if columns else None
        rows = []
        for _ in range(n_records):
            record = f.read(record_len)
            if not record or record[0:1] == b"*":
                continue
            pos, row = 1, {}
            for name, length in fields:
                if wanted is None or name in wanted:
                    row[name] = record[pos:pos + length].decode("latin-1").strip()
                pos += length
            rows.append(row)
    return pd.DataFrame(rows)


def tract_trpaid(state: pd.Series, county: pd.Series, tractbna: pd.Series) -> pd.Series:
    """Build 1990 tract TRPAIDs: state + county + six-digit tract + 1990."""
    text = tractbna.astype(str).str.replace(".", "", regex=False).str.strip()
    tract = text.where(text.str.len() > 4, text.str.zfill(4) + "00").str.zfill(6)
    return state.astype(str).str.zfill(2) + county.astype(str).str.zfill(3) + tract + "1990"


def import_folder(folder, variables: pd.DataFrame, tahoe: pd.DataFrame) -> pd.DataFrame:
    """Read every .dbf in a folder and return basin tract rows for the listed variables.

    variables is config/variables.csv; rows with dataset dec/sf3 and years 1990 are used.
    """
    wanted = variables[(variables["dataset"] == "dec/sf3") & (variables["years"].astype(str).str.strip() == "1990")]
    if wanted.empty:
        raise ValueError("No 1990 variables in config/variables.csv (dataset dec/sf3, years 1990).")
    basin = tahoe[tahoe["YEAR"] == 1990][["TRPAID", "NEIGHBORHOOD"]]
    frames: List[pd.DataFrame] = []
    keys = ["SUMLEV", "STATEFP", "CNTY", "TRACTBNA"]
    for path in sorted(Path(folder).glob("*.dbf")):
        table = read_dbf(path, keys + list(wanted["variable_code"]))
        codes = [c for c in wanted["variable_code"] if c in table.columns]
        if table.empty or not codes:
            continue
        table = table[table["SUMLEV"] == "140"].copy()
        table["TRPAID"] = tract_trpaid(table["STATEFP"], table["CNTY"], table["TRACTBNA"])
        table = table.merge(basin, on="TRPAID", how="inner")
        long = table.melt(id_vars=keys + ["TRPAID", "NEIGHBORHOOD"], value_vars=codes, var_name="variable_code", value_name="value")
        frames.append(long)
    if not frames:
        return pd.DataFrame(columns=RAW_COLUMNS)
    data = pd.concat(frames, ignore_index=True).merge(wanted[["variable_code", "variable_name", "variable_category"]], on="variable_code")
    out = pd.DataFrame({
        "GEO_ID": data["TRPAID"].str[:-4], "value": pd.to_numeric(data["value"], errors="coerce"), "MarginOfError": np.nan,
        "state": data["STATEFP"].str.zfill(2), "county": data["CNTY"].str.zfill(3), "tract": data["TRPAID"].str[5:11],
        "block_group": pd.NA, "variable_code": data["variable_code"], "variable_name": data["variable_name"],
        "variable_category": data["variable_category"], "year_sample": 1990, "sample_level": "tract",
        "dataset": "dec/sf3", "census_geom_year": 1990, "TRPAID": data["TRPAID"], "NEIGHBORHOOD": data["NEIGHBORHOOD"],
    })
    return out[RAW_COLUMNS].drop_duplicates(["TRPAID", "variable_code"])
