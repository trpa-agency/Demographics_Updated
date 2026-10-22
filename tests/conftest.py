"""Shared test data: a tiny fake basin with two tracts per county."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trpa_demographics.config import load_settings  # noqa: E402

COUNTIES = [("06", "017"), ("06", "061"), ("32", "005"), ("32", "031")]


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def tahoe():
    rows = []
    for state, county in COUNTIES:
        for t in ("000100", "000200"):
            geoid = f"{state}{county}{t}"
            rows.append({"YEAR": 2020, "STATE": state, "GEOGRAPHY": "Tract", "TRPAID": geoid + "2020",
                         "NEIGHBORHOOD": f"N{county}", "sample_level": "tract"})
    df = pd.DataFrame(rows)
    df["YEAR"] = df["YEAR"].astype("Int64")
    return df


def make_raw(values, moes=None, year=2023, dataset="acs/acs5", category="Age", names=None):
    """Build a raw long table. values maps variable_code to a value per tract (8 tracts)."""
    rows = []
    for code, per_tract in values.items():
        for i, ((state, county), t) in enumerate([(c, t) for c in COUNTIES for t in ("000100", "000200")]):
            geoid = f"{state}{county}{t}"
            rows.append({
                "GEO_ID": geoid, "value": per_tract[i] if isinstance(per_tract, list) else per_tract,
                "MarginOfError": (moes or {}).get(code, 10.0), "state": state, "county": county, "tract": t,
                "block_group": None, "variable_code": code, "variable_name": (names or {}).get(code, code),
                "variable_category": category, "year_sample": year, "sample_level": "tract", "dataset": dataset,
                "census_geom_year": 2020, "TRPAID": geoid + "2020", "NEIGHBORHOOD": f"N{county}",
            })
    return pd.DataFrame(rows)


@pytest.fixture
def raw_factory():
    return make_raw
