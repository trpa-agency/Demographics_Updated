"""Build wide "one row per geography and year" tables from the long Census Data layout.

Map layers such as Tahoe Census Curated (Demographics MapServer/3) and the TDC
block group layers hold one row per tract or block group and year, with one
column per variable. config/curated_layers.csv lists each layer's columns and
where each value comes from: a Census variable code, or a TRPA group
(grouping_set and group_name from config/groupings.csv).

build_curated() returns a table. to_feature_class() joins it to the basin
shapes and writes a file geodatabase feature class (needs ArcGIS Pro).
"""
from __future__ import annotations

from typing import Tuple

import pandas as pd

from .config import CONFIG_DIR, county_table

CURATED_PATH = CONFIG_DIR / "curated_layers.csv"
ID_COLUMNS = ["trpaid", "year_sample", "sample_level"]


def load_fields(layer: str, path=CURATED_PATH) -> pd.DataFrame:
    """Read the column list for one curated layer."""
    fields = pd.read_csv(path, dtype=str).fillna("")
    fields = fields[fields["layer"] == layer]
    if fields.empty:
        raise ValueError(f"No fields for layer '{layer}' in {path}")
    return fields


def select_field_rows(long: pd.DataFrame, field: pd.Series) -> pd.DataFrame:
    """Rows of the long table that feed one curated column."""
    if field["variable_code"]:
        return long[long["variable_code"] == field["variable_code"]]
    prefix = f"{field['grouping_set']}:"
    return long[long["variable_code"].astype(str).str.startswith(prefix) & (long["variable_name"].astype(str).str.strip() == field["group_name"])]


def build_curated(long: pd.DataFrame, layer: str, settings: dict, path=CURATED_PATH) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (wide table, problems).

    problems lists columns with no source rows and geographies where a column
    had more than one source row (the first is kept).
    """
    fields = load_fields(layer, path)
    parts, problems = [], []
    for _, field in fields.iterrows():
        rows = select_field_rows(long, field)
        if rows.empty:
            problems.append({"field": field["field_name"], "problem": "no source rows"})
            continue
        dupes = rows.duplicated(["TRPAID", "year_sample", "sample_level"], keep=False)
        if dupes.any():
            problems.append({"field": field["field_name"], "problem": f"{int(dupes.sum())} rows share a geography and year; the first was kept"})
        part = rows.drop_duplicates(["TRPAID", "year_sample", "sample_level"])[["TRPAID", "year_sample", "sample_level", "value", "state", "county"]]
        parts.append(part.assign(field=field["field_name"]))
    if not parts:
        return pd.DataFrame(), pd.DataFrame(problems)
    stacked = pd.concat(parts, ignore_index=True)
    wide = stacked.pivot_table(index=["TRPAID", "year_sample", "sample_level"], columns="field", values="value", aggfunc="first").reset_index()
    wide.columns.name = None
    geo = stacked.drop_duplicates("TRPAID")[["TRPAID", "state", "county"]]
    geo = geo.assign(state=geo["state"].astype(str).str.zfill(2), county=geo["county"].astype(str).str.zfill(3))
    labels = county_table(settings)[["state", "county", "county_short", "state_abbr", "north_south"]]
    geo = geo.merge(labels, on=["state", "county"], how="left").rename(columns={"county_short": "county_name", "state_abbr": "state_name"})
    wide = wide.merge(geo[["TRPAID", "state_name", "county_name", "north_south"]], on="TRPAID", how="left").rename(columns={"TRPAID": "trpaid"})
    ordered = ID_COLUMNS + [f for f in fields["field_name"] if f in wide.columns] + ["state_name", "county_name", "north_south"]
    return wide[ordered], pd.DataFrame(problems)


def field_aliases(layer: str, path=CURATED_PATH) -> dict:
    fields = load_fields(layer, path)
    return dict(zip(fields["field_name"], fields["alias"]))


def to_feature_class(wide: pd.DataFrame, settings: dict, output_fc: str, layer: str,
                     path=CURATED_PATH) -> str:
    """Join the wide table to basin shapes and write a file geodatabase feature class.

    Needs the arcgis and arcpy packages from ArcGIS Pro. Refuses SDE paths.
    """
    if ".sde" in output_fc.lower():
        raise PermissionError("Write curated layers to a file geodatabase. Loading SDE stays a manual, reviewed step.")
    import arcpy  # noqa: F401  (ArcGIS Pro only)
    from arcgis.features import FeatureLayer

    shapes = pd.DataFrame.spatial.from_layer(FeatureLayer(settings["services"]["tahoe_geometry"]))
    shapes = shapes[shapes["TRPAID"].isin(wide["trpaid"])][["TRPAID", "SHAPE"]].rename(columns={"TRPAID": "trpaid"})
    sdf = wide.merge(shapes, on="trpaid", how="left")
    sdf.spatial.set_geometry("SHAPE")
    sdf.spatial.to_featureclass(location=output_fc, overwrite=True, sanitize_columns=False)
    for name, alias in field_aliases(layer, path).items():
        if alias and name in wide.columns:
            arcpy.management.AlterField(output_fc, name, new_field_alias=alias)
    return output_fc
