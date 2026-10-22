"""Roll tract and block group values up to larger geographies.

Summary levels (set in config/settings.json):
  Basin         every geography in the download
  County        the Tahoe Basin part of each county
  North/South   North Lake (Placer, Washoe) and South Lake (El Dorado, Douglas)
  State         the California and Nevada parts of the basin
  Neighborhood  the NEIGHBORHOOD field from the geography layer

Counts are added. When some tracts or block groups are blank, the sum of the
others is kept and the row is listed in a "partial" file, because a blank can
mean the Census Bureau published nothing for an area that has no households.
Margins of error are combined as the square root of the sum of squares and
written to a separate file. Medians, averages, and percentages cannot be added,
so they are skipped and listed. Use config/medians.csv to calculate a median
from count bins instead.
"""
from __future__ import annotations

import math
import re
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from .geography import add_geography_labels
from .grouping import combine_moe
from .tables import LAYER18_COLUMNS, SUMMARY_COLUMNS

LEVEL_FIELDS = {
    "Basin": None,
    "County": "county_name",
    "North/South": "north_south",
    "State": "state_name",
    "Neighborhood": "NEIGHBORHOOD",
}
VARIABLE_KEYS = ["variable_code", "variable_name", "variable_category", "year_sample", "dataset", "sample_level"]
NON_ADDITIVE_WORDS = re.compile(r"\b(?:median|mean|average|percent|rate|ratio|per capita)\b", re.IGNORECASE)


def non_additive_codes(variables: Optional[pd.DataFrame]) -> set:
    """Return (variable_code, dataset) pairs marked aggregation = none in config/variables.csv."""
    if variables is None or "aggregation" not in variables.columns:
        return set()
    v = variables[variables["aggregation"].astype(str).str.lower() == "none"]
    return set(zip(v["variable_code"], v["dataset"]))


def _levels(settings: dict, levels: Optional[List[str]]) -> List[str]:
    chosen = levels or settings.get("summary_levels", ["Basin", "County", "North/South", "State"])
    unknown = [lvl for lvl in chosen if lvl not in LEVEL_FIELDS]
    if unknown:
        raise ValueError(f"Unknown summary level(s): {unknown}. Choose from {list(LEVEL_FIELDS)}")
    return chosen


def _geography_name(settings: dict, field: Optional[str], key_value) -> str:
    return settings.get("basin_label", "Basin") if field is None else key_value


def summarize(raw: pd.DataFrame, settings: dict, variables: Optional[pd.DataFrame] = None,
              levels: Optional[List[str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (summary, skipped, partial).

    summary  one row per geography, variable, year, sample level, and dataset,
             with a MarginOfError column (written to its own file by the CLI)
    skipped  variables left out because they cannot be added
    partial  summary rows where some tracts or block groups were blank
    """
    data = add_geography_labels(raw, settings)
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data["MarginOfError"] = pd.to_numeric(data["MarginOfError"], errors="coerce")
    blocked = non_additive_codes(variables)
    by_config = pd.Series([p in blocked for p in zip(data["variable_code"], data["dataset"])], index=data.index)
    by_name = (data["variable_name"].fillna("").str.contains(NON_ADDITIVE_WORDS)
               | data["variable_category"].fillna("").str.contains(NON_ADDITIVE_WORDS))
    skip = by_config | by_name
    reason = np.where(by_config, "aggregation is none in variables.csv",
                      "name or category says median, mean, average, percent, rate, or ratio")
    id_cols = ["variable_code", "variable_name", "variable_category", "dataset"]
    skipped = data.loc[skip, id_cols].assign(reason=reason[skip.values]).drop_duplicates(id_cols)
    data = data.loc[~skip]
    frames, partial = [], []
    for level in _levels(settings, levels):
        field = LEVEL_FIELDS[level]
        subset = data if field is None else data[data[field].notna() & (data[field].astype(str) != "")]
        keys = VARIABLE_KEYS + ([field] if field else [])
        agg = subset.groupby(keys, dropna=False).agg(
            value=("value", lambda s: s.sum(min_count=1)),
            MarginOfError=("MarginOfError", combine_moe),
            geographies=("TRPAID", "nunique"),
            blank_values=("value", lambda s: int(s.isna().sum())),
        ).reset_index()
        agg["Geography"] = settings.get("basin_label", "Basin") if field is None else agg[field]
        flagged = agg["blank_values"] > 0
        if flagged.any():
            partial.append(agg.loc[flagged, ["Geography"] + VARIABLE_KEYS + ["geographies", "blank_values"]])
        agg["Category"] = agg["variable_category"]
        frames.append(agg[SUMMARY_COLUMNS + ["MarginOfError"]])
    summary = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SUMMARY_COLUMNS + ["MarginOfError"])
    partial_table = pd.concat(partial, ignore_index=True) if partial else pd.DataFrame()
    return summary.reset_index(drop=True), skipped.reset_index(drop=True), partial_table


# ---------------------------------------------------------------------------
# Medians from count bins
# ---------------------------------------------------------------------------

def load_medians(path) -> pd.DataFrame:
    """Read config/medians.csv. A blank bin_upper marks the open-ended top bin.

    first_year and last_year limit a row to the years when that bin existed.
    """
    df = pd.read_csv(path, dtype=str).fillna("")
    for col in ("bin_lower", "bin_upper", "design_factor", "first_year", "last_year"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].replace("", np.nan), errors="coerce")
    return df


def _bounds_at(bins: pd.DataFrame, percent: float) -> float:
    """Interpolate the value at a cumulative percent of a binned distribution."""
    total = bins["count"].sum()
    cum_below = 0.0
    for row in bins.itertuples():
        share = row.count / total * 100.0
        if cum_below + share >= percent and share > 0:
            if pd.isna(row.bin_upper):
                return np.nan
            return (percent - cum_below) / share * (row.bin_upper - row.bin_lower) + row.bin_lower
        cum_below += share
    return np.nan


def interpolate_median(bins: pd.DataFrame, design_factor: float = np.nan,
                       settings: Optional[dict] = None) -> Tuple[float, float, str]:
    """Return (median, margin_of_error, note) for binned counts.

    bins needs columns bin_lower, bin_upper, and count, one row per bin.
    The median is the point where half the total falls below. Inside the bin
    that holds that point, values are assumed to be spread evenly.

    The margin of error follows the Census Bureau's design factor method:
      SE(50 percent) = design factor x sqrt((99 / (5 x total)) x 50 squared)
      the values at 50 minus and 50 plus that percent are interpolated,
      SE(median) = half the distance between them, MOE = 1.645 x SE(median).
    It is left blank when either bound falls in the open-ended top bin,
    which is how the Census Bureau reports it ("***").
    """
    cfg = (settings or {}).get("medians", {})
    b = bins.sort_values("bin_lower").reset_index(drop=True)
    total = b["count"].sum()
    if not np.isfinite(total) or total <= 0:
        return np.nan, np.nan, "no counts"
    cumulative = b["count"].cumsum()
    idx = int(np.argmax(cumulative.values >= total / 2.0))
    below = cumulative.iloc[idx] - b["count"].iloc[idx]
    lower, upper, count = b.loc[idx, "bin_lower"], b.loc[idx, "bin_upper"], b.loc[idx, "count"]
    if pd.isna(upper):
        return float(lower), np.nan, "median falls in the open-ended top bin; value is the bin's lower edge"
    median = float(lower + (total / 2.0 - below) / count * (upper - lower))
    moe, note = np.nan, ""
    if pd.notna(design_factor) and design_factor > 0:
        numerator = cfg.get("moe_constant_numerator", 99)
        years = cfg.get("moe_constant_years", 5)
        se50 = design_factor * math.sqrt((numerator / (years * total)) * 50 ** 2)
        low_bound = _bounds_at(b, max(50 - se50, 0.0))
        high_bound = _bounds_at(b, min(50 + se50, 100.0))
        if np.isnan(low_bound) or np.isnan(high_bound):
            note = "margin of error not calculated: a bound falls in the open-ended top bin"
        else:
            moe = cfg.get("z_value", 1.645) * 0.5 * (high_bound - low_bound)
    return median, moe, note


def _bins_for_year(cfg: pd.DataFrame, year: int) -> pd.DataFrame:
    keep = (cfg["first_year"].isna() | (cfg["first_year"] <= year)) & (cfg["last_year"].isna() | (cfg["last_year"] >= year))
    return cfg[keep]


def compute_medians(raw: pd.DataFrame, medians: pd.DataFrame, settings: dict,
                    levels: Optional[List[str]] = None) -> pd.DataFrame:
    """Calculate medians from count bins at each summary level.

    Returns summary rows plus MarginOfError and note columns.
    Bins whose values are blank are left out of the count and noted.
    """
    data = add_geography_labels(raw, settings)
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    rows = []
    for (mset, dataset), cfg in medians.groupby(["median_set", "dataset"], sort=False):
        tables = sorted({c.split("_")[0] for c in cfg["variable_code"]})
        design_factor = cfg["design_factor"].dropna().iloc[0] if "design_factor" in cfg and cfg["design_factor"].notna().any() else np.nan
        source = data[(data["dataset"] == dataset) & data["variable_code"].isin(cfg["variable_code"])]
        for year, year_data in source.groupby("year_sample"):
            bins = _bins_for_year(cfg, int(year))[["variable_code", "bin_lower", "bin_upper"]]
            subset = year_data.merge(bins, on="variable_code")
            if subset.empty:
                continue
            for level in _levels(settings, levels):
                field = LEVEL_FIELDS[level]
                keys = ["sample_level"] + ([field] if field else [])
                for key, part in subset.groupby(keys, dropna=False):
                    key = key if isinstance(key, tuple) else (key,)
                    if field and (pd.isna(key[1]) or str(key[1]) == ""):
                        continue
                    blanks = int(part["value"].isna().sum())
                    per_bin = part.groupby(["bin_lower", "bin_upper"], dropna=False)["value"].sum(min_count=1).fillna(0).reset_index().rename(columns={"value": "count"})
                    value, moe, note = interpolate_median(per_bin, design_factor, settings)
                    if blanks:
                        note = "; ".join(n for n in (note, f"{blanks} blank bin values left out") if n)
                    rows.append({
                        "variable_code": f"{mset}: " + ", ".join(tables),
                        "variable_name": cfg["output_name"].iloc[0],
                        "value": value,
                        "Geography": _geography_name(settings, field, key[1] if field else None),
                        "year_sample": int(year),
                        "dataset": dataset,
                        "sample_level": key[0],
                        "Category": cfg["output_category"].iloc[0],
                        "MarginOfError": moe,
                        "note": note,
                    })
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS + ["MarginOfError", "note"])


# ---------------------------------------------------------------------------
# Demographic Summaries layout (layer 18)
# ---------------------------------------------------------------------------

def to_layer18(summary: pd.DataFrame, settings: dict, partial: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Convert summary rows to the Demographic Summaries layout so both tables stay in sync.

    Layer 18 has no sample level field, so only rows from the level set in
    settings (demographic_summaries_layout.sample_level) are kept. The variable
    name goes in Notes, followed by a partial flag when some areas were blank.
    """
    level = settings.get("demographic_summaries_layout", {}).get("sample_level", "tract")
    s = summary[summary["sample_level"] == level].copy()
    s["Notes"] = s["variable_name"].fillna("")
    if partial is not None and not partial.empty:
        p = partial[partial["sample_level"] == level]
        flags = {(r.Geography, r.variable_code, r.year_sample, r.dataset): f"partial: {r.blank_values} of {r.geographies} {level}s blank"
                 for r in p.itertuples()}
        extra = [flags.get((g, c, y, d), "") for g, c, y, d in zip(s["Geography"], s["variable_code"], s["year_sample"], s["dataset"])]
        s["Notes"] = [f"{n}; {e}" if e else n for n, e in zip(s["Notes"], extra)]
    out = pd.DataFrame({
        "Category": s["Category"], "Code": s["variable_code"], "Value": s["value"], "Year": s["year_sample"],
        "Source": s["dataset"], "Notes": s["Notes"].str.slice(0, 1000), "Geography": s["Geography"],
    })
    return out[LAYER18_COLUMNS].reset_index(drop=True)
