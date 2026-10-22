"""List what is already published in the TRPA demographic services.

Uses server-side summaries, so it runs in seconds instead of downloading
millions of rows. Read only.
"""
from __future__ import annotations

import pandas as pd

from . import services


def census_data_inventory(settings: dict, session=None) -> pd.DataFrame:
    """One row per variable, category, dataset, and sample level in the Census Data table,
    with record counts, first and last year, and the value range."""
    df = services.query_statistics(
        settings["services"]["census_data"],
        ["variable_code", "variable_name", "variable_category", "dataset", "sample_level"],
        [("count", "OBJECTID", "records"), ("min", "year_sample", "first_year"),
         ("max", "year_sample", "last_year"), ("min", "value", "min_value"), ("max", "value", "max_value")],
        session=session,
    )
    return df.sort_values(["variable_category", "variable_code", "sample_level"]).reset_index(drop=True)


def years_by_variable(settings: dict, session=None) -> pd.DataFrame:
    """Record counts for each variable and year, for spotting missing years."""
    return services.query_statistics(
        settings["services"]["census_data"],
        ["variable_code", "dataset", "sample_level", "year_sample"],
        [("count", "OBJECTID", "records")],
        session=session,
    )


def summary_inventory(settings: dict, session=None) -> pd.DataFrame:
    """One row per category, variable, and dataset in the Climate Resilience Dashboard Census Data table."""
    return services.query_statistics(
        settings["services"]["climate_dashboard_census_data"],
        ["Category", "variable_code", "variable_name", "dataset", "sample_level"],
        [("count", "OBJECTID", "records"), ("min", "year_sample", "first_year"), ("max", "year_sample", "last_year")],
        session=session,
    )


def service_duplicates(settings: dict, year: int = None, session=None) -> pd.DataFrame:
    """Keys that appear more than once in the Census Data table (optionally for one year)."""
    where = f"year_sample = {int(year)}" if year else "1=1"
    return services.query_statistics(
        settings["services"]["census_data"],
        ["TRPAID", "variable_code", "year_sample", "sample_level", "dataset"],
        [("count", "OBJECTID", "copies")],
        where=where, having="COUNT(OBJECTID) > 1", session=session,
    )


def registry_from_inventory(inventory: pd.DataFrame, year: int = None) -> pd.DataFrame:
    """Turn the service inventory into rows in the config/variables.csv format.

    Grouped rows (codes that contain a colon) are left out because the
    group step rebuilds them. Use this to seed or extend config/variables.csv.
    """
    inv = inventory[~inventory["variable_code"].astype(str).str.contains(":", regex=False)]
    if year:
        inv = inv[(inv["first_year"] <= year) & (inv["last_year"] >= year)]
    levels = inv.groupby(["variable_code", "dataset"])["sample_level"].agg(lambda s: ";".join(sorted(set(s)))).rename("sample_level")
    first = inv.drop_duplicates(["variable_code", "dataset"]).set_index(["variable_code", "dataset"])[["variable_name", "variable_category"]]
    out = first.join(levels).reset_index()
    out["aggregation"] = out["variable_name"].str.contains("median|average|mean|percent", case=False).map({True: "none", False: "sum"})
    out["active"] = "Y"
    out["notes"] = "Added from the published Census Data inventory"
    return out[["variable_code", "variable_name", "variable_category", "dataset", "sample_level", "aggregation", "active", "notes"]]
