"""Load settings, file paths, and the Census API key.

All service URLs, county lists, and thresholds live in config/settings.json.
Code reads them from here so nothing is hardcoded in scripts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
VARIABLES_PATH = CONFIG_DIR / "variables.csv"
GROUPINGS_PATH = CONFIG_DIR / "groupings.csv"
MEDIANS_PATH = CONFIG_DIR / "medians.csv"
ENV_PATH = REPO_ROOT / ".env"


def load_settings(path: Optional[Path] = None) -> dict:
    """Read settings.json and return it as a dictionary."""
    with open(path or SETTINGS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _read_env_file(path: Path) -> dict:
    """Read simple KEY=VALUE lines from a .env file. Lines starting with # are ignored."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_api_key(settings: dict) -> Optional[str]:
    """Return the Census API key from the environment or the repo .env file.

    The key is never stored in code or in settings.json. Returns None when no
    key is set; data downloads then stop with a message (census_api.require_api_key).
    """
    var = settings["census_api"]["api_key_env_var"]
    return os.environ.get(var) or _read_env_file(ENV_PATH).get(var) or None


def outputs_dir(settings: dict, *parts: str) -> Path:
    """Return a folder under the outputs folder, creating it if needed."""
    folder = REPO_ROOT / settings.get("outputs_folder", "outputs")
    for part in parts:
        folder = folder / str(part)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def county_table(settings: dict) -> pd.DataFrame:
    """Return the county lookup (state, county, county_name, state_name, north_south) as strings."""
    return pd.DataFrame(settings["counties"]).astype(str)


def census_geom_year(data_year: int, settings: dict) -> int:
    """Return the Census boundary vintage used by a data year.

    ACS 5-year 2020 and later use 2020 boundaries.
    2010 to 2019 use 2010 boundaries.
    """
    vintages = sorted(settings["geometry_vintages"], key=lambda v: v["first_data_year"], reverse=True)
    for v in vintages:
        if int(data_year) >= v["first_data_year"]:
            return int(v["census_geom_year"])
    raise ValueError(f"No geometry vintage configured for data year {data_year}")
