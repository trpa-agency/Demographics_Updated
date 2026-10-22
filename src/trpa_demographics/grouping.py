"""Combine detailed Census variables into TRPA categories.

config/groupings.csv lists, for each grouping set, which Census variables
add up to each TRPA category. Example: the "TRPA Grouped" set adds 16 age
variables (male and female, under 5 through 15 to 17) into Age_Under_18.

Rules this module follows:
- Values are added within one geography, year, sample level, and dataset.
- Margins of error are combined as the square root of the sum of squares,
  the Census Bureau's standard approximation for a sum of estimates.
- If a member variable is missing or blank for a geography, the other members
  are still added and the geography is listed in a "partial" file. A blank can
  be real: the Census Bureau publishes nothing for some empty areas.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from .tables import RAW_COLUMNS

GROUP_KEYS = ["TRPAID", "year_sample", "sample_level", "dataset"]
GEOGRAPHY_COLUMNS = ["GEO_ID", "state", "county", "tract", "block_group", "census_geom_year", "NEIGHBORHOOD"]


def load_groupings(path) -> pd.DataFrame:
    """Read config/groupings.csv."""
    df = pd.read_csv(path, dtype=str).fillna("")
    df["group_order"] = pd.to_numeric(df["group_order"], errors="coerce")
    df["group_name"] = df["group_name"].str.strip()
    return df


def grouped_code(grouping_set: str, codes: List[str], max_length: int) -> str:
    """Build the legacy grouped variable_code, such as 'TRPA Grouped: B01001_003E, B01001_004E'.

    The published Census Data table stores grouped rows this way.
    Long member lists are cut to the field length limit (255 characters).
    """
    text = f"{grouping_set}: " + ", ".join(codes)
    return text if len(text) <= max_length else text[: max_length - 3] + "..."


def combine_moe(moe: pd.Series) -> float:
    """Combine margins of error for a sum: square root of the sum of squares."""
    if moe.isna().all():
        return np.nan
    return float(np.sqrt((moe.fillna(0) ** 2).sum()))


def apply_groupings(raw: pd.DataFrame, groupings: pd.DataFrame, settings: dict,
                    sets: Optional[List[str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return grouped rows in the Census Data layout plus a table of partial groups.

    raw is a long table from a download or from the Census Data service.
    sets limits the run to some grouping sets. None runs all of them.
    """
    max_len = int(settings.get("grouped_code_max_length", 255))
    cfg = groupings if not sets else groupings[groupings["grouping_set"].isin(sets)]
    data = raw.copy()
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data["MarginOfError"] = pd.to_numeric(data["MarginOfError"], errors="coerce")
    out, gaps = [], []
    for (gset, dataset, group_name), members in cfg.groupby(["grouping_set", "dataset", "group_name"], sort=False):
        codes = list(dict.fromkeys(members["variable_code"]))
        subset = data[(data["dataset"] == dataset) & (data["variable_code"].isin(codes))]
        if subset.empty:
            continue
        template = members["output_category"].iloc[0]
        agg = subset.groupby(GROUP_KEYS, dropna=False).agg(
            value=("value", lambda s: s.sum(min_count=1)),
            MarginOfError=("MarginOfError", combine_moe),
            members_found=("value", lambda s: int(s.notna().sum())),
            source_category=("variable_category", "first"),
            **{col: (col, "first") for col in GEOGRAPHY_COLUMNS if col in subset.columns},
        ).reset_index()
        incomplete = agg["members_found"] < len(codes)
        if incomplete.any():
            g = agg.loc[incomplete, GROUP_KEYS + ["members_found"]].copy()
            g["grouping_set"], g["group_name"], g["members_expected"] = gset, group_name, len(codes)
            gaps.append(g)
        agg["variable_code"] = grouped_code(gset, codes, max_len)
        agg["variable_name"] = group_name
        agg["variable_category"] = agg["source_category"].map(lambda c: template.replace("{source_category}", str(c)))
        out.append(agg)
    grouped = pd.concat(out, ignore_index=True)[RAW_COLUMNS] if out else pd.DataFrame(columns=RAW_COLUMNS)
    gap_table = pd.concat(gaps, ignore_index=True) if gaps else pd.DataFrame()
    return grouped, gap_table
