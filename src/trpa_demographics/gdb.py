"""Optional: copy a reviewed CSV into a file geodatabase table for loading in ArcGIS Pro.

This needs arcpy, so it only runs in the ArcGIS Pro Python environment.
It refuses to write to enterprise geodatabases (.sde connections).
Loading data into SDE stays a manual step that a person reviews and approves.
"""
from __future__ import annotations

import os
from typing import List, Optional

import numpy as np
import pandas as pd


def to_file_gdb(df: pd.DataFrame, gdb_path: str, table_name: str,
                double_fields: Optional[List[str]] = None, integer_fields: Optional[List[str]] = None,
                overwrite: bool = False) -> str:
    """Write a DataFrame to a table in a file geodatabase and return the table path."""
    if ".sde" in str(gdb_path).lower():
        raise PermissionError("Writing to an SDE connection is not allowed from this toolkit. Write to a file geodatabase and load it by hand after review.")
    if not str(gdb_path).lower().endswith(".gdb"):
        raise ValueError(f"Expected a file geodatabase path ending in .gdb, got {gdb_path}")
    import arcpy  # imported here so the rest of the toolkit runs without ArcGIS Pro

    double_fields = double_fields or ["value", "MarginOfError"]
    integer_fields = integer_fields or ["year_sample", "census_geom_year"]
    out = df.copy()
    dtype = []
    for col in out.columns:
        if col in double_fields:
            out[col] = pd.to_numeric(out[col], errors="coerce")
            dtype.append((col, np.float64))
        elif col in integer_fields:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(-1).astype(np.int32)
            dtype.append((col, np.int32))
        else:
            out[col] = out[col].fillna("").astype(str)
            dtype.append((col, f"U{max(int(out[col].str.len().max() or 1), 1)}"))
    array = np.array([tuple(r) for r in out.itertuples(index=False)], dtype=dtype)
    target = os.path.join(gdb_path, table_name)
    if arcpy.Exists(target):
        if not overwrite:
            raise FileExistsError(f"{target} already exists. Pass overwrite=True to replace it.")
        arcpy.management.Delete(target)
    arcpy.da.NumPyArrayToTable(array, target)
    return target
