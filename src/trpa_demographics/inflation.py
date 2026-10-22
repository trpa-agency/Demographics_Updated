"""Convert dollar values between years.

config/inflation_adjustments.csv holds the annual average R-CPI-U-RS price index
for each year. The Census Bureau uses this index to compare incomes across years.
The values come from the Bureau of Labor Statistics file listed in
config/settings.json (inflation.source_url). Add a row each spring when BLS
publishes the year before.

A value in year Y becomes target-year dollars as: value x index[target] / index[Y].
The default target is base_year in config/settings.json.
"""
from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from .config import REPO_ROOT


def load_index(settings: dict) -> pd.Series:
    """Annual average index by year."""
    df = pd.read_csv(REPO_ROOT / settings["inflation"]["factors"])
    return df.set_index("year")["annual_average_index"].astype(float)


def adjust(df: pd.DataFrame, settings: dict, target_year: Optional[int] = None, value_col: str = "value",
           year_col: str = "year_sample", codes: Optional[Iterable[str]] = None, code_col: str = "variable_code") -> pd.DataFrame:
    """Return a copy with dollar values converted to target-year dollars.

    Only rows whose code is in codes are converted (all rows when codes is None).
    Rows whose year is missing from the index table are left blank and noted in
    a column named inflation_note.
    """
    index = load_index(settings)
    target = int(target_year or settings["inflation"]["base_year"])
    if target not in index.index:
        raise ValueError(f"No R-CPI-U-RS value for {target}. Add it to config/inflation_adjustments.csv.")
    out = df.copy()
    rows = out[code_col].isin(list(codes)) if codes is not None else pd.Series(True, index=out.index)
    year_index = out[year_col].astype(int).map(index)
    out["inflation_note"] = ""
    out.loc[rows & year_index.isna(), "inflation_note"] = "no index value for this year"
    out.loc[rows, value_col] = out.loc[rows, value_col] * index[target] / year_index[rows]
    return out
