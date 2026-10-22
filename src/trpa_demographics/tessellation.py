"""Spread block group Census values onto the Tahoe hexagon grid using parcels.

Block groups are large and uneven. To map demographics on the even hexagon grid
(Demographics_Tessellation, Demographics MapServer/2), each year:
1. Parcels are matched to the block group they sit in.
2. Block group rates are calculated, such as the share of housing units that are
   occupied and the share of households with no vehicle (config/tessellation_variables.csv).
3. Each parcel gets an estimate: residential units times the rates.
4. Parcel estimates are added up inside each hexagon.
5. Hexagon totals are scaled each year so they add up to the Census block group
   totals for the basin (population and occupied units).

Reads parcels and hexagons from SDE (read only) and writes to a file geodatabase.
The spatial steps need ArcGIS Pro (arcpy and the arcgis package). The math steps
are plain pandas and are tested without ArcGIS.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

OCCUPANCY_CODES = {
    "vacant_units": "B25002_003E",
    "occupied_units": "B25002_002E",
    "seasonal_units": "B25004_006E",
    "bg_population": "B01003_001E",
}
POP_CODE, HOUSEHOLD_CODE = "B01003_001E", "B25002_002E"

# Output fields that match Tahoe Census Curated (MapServer/3) and how each is scaled.
HEX_OUTPUT = {
    "age_under_18": ("Age_Under_18", "pop"),
    "age_65_and_over": ("Age_65_and_Over", "pop"),
    "bipoc": ("BIPOC", "pop"),
    "total_population_hispanic_or_latino": ("Total population:  Hispanic or Latino", "pop"),
    "not_well_not_at_all": ("Speak_English_Not_Well_Not_at_All", "pop"),
    "below_poverty_status_individuals_": ("Below_Poverty_Individual", "pop"),
    "no_vehicle_available": ("Vehicle_Available_0", "hh"),
    "poverty_status_of_households_below_poverty_level": ("Below_Poverty_Household", "hh"),
    "occupied_housing_units_owner_occupied": ("Owner_Occupied", "hh"),
    "occupied_housing_units_renter_occupied": ("Renter_Occupied", "hh"),
    "vacant_housing_units_for_rent": ("Vacant_For_Rent", "hh"),
    "vacant_housing_units_rented_not_occupied": ("Vacant_Rented_Not_Occupied", "hh"),
    "vacant_housing_units_for_sale_only": ("Vacant_For_Sale", "hh"),
    "vacant_housing_units_sold_not_occupied": ("Vacant_Sold_Not_Occupied", "hh"),
}


def safe_col(name: str) -> str:
    """Column-name prefix for a variable name (spaces become underscores)."""
    return name.strip().replace(" ", "_")


def occupancy_rates(census_bg: pd.DataFrame, year: int) -> pd.DataFrame:
    """Occupied share, seasonal share, and population per housing unit for each block group.

    Uses the nearest year with data when the requested year has none.
    Negative Census annotation values are treated as blank.
    """
    codes = list(OCCUPANCY_CODES.values())
    df = census_bg[census_bg["variable_code"].isin(codes)]
    years = df["year_sample"].astype(int)
    if (years == year).any():
        df = df[years == year]
    elif not df.empty:
        nearest = years.iloc[(years - year).abs().argmin()]
        df = df[years == nearest]
    wide = df.pivot_table(index="TRPAID", columns="variable_code", values="value", aggfunc="first")
    wide = wide.rename(columns={v: k for k, v in OCCUPANCY_CODES.items()})
    for col in OCCUPANCY_CODES:
        if col not in wide.columns:
            wide[col] = np.nan
    wide = wide.where(wide >= 0)
    wide["total_units"] = wide["vacant_units"] + wide["occupied_units"]
    total = wide["total_units"].replace(0, np.nan)
    wide["occupancy_rate"] = wide["occupied_units"] / total
    wide["seasonal_rate"] = wide["seasonal_units"] / total
    wide["population_per_unit"] = wide["bg_population"] / total
    return wide.reset_index()


def variable_rates(census: pd.DataFrame, config: pd.DataFrame, year: int) -> Dict[str, Tuple[pd.DataFrame, str, str]]:
    """Rate of each configured variable per occupied housing unit, by TRPAID.

    Returns {name: (rates, sample_level, type)} where type is Household or Individual.
    """
    out = {}
    for row in config.itertuples():
        level = row.sample_level.strip().lower()
        df = census[(census["sample_level"] == level) & (census["year_sample"].astype(int) == year)
                    & census["variable_code"].isin([row.variable_code, HOUSEHOLD_CODE])]
        wide = df.pivot_table(index="TRPAID", columns="variable_code", values="value", aggfunc="first")
        numerator = wide.get(row.variable_code, pd.Series(np.nan, index=wide.index))
        denominator = wide.get(HOUSEHOLD_CODE, pd.Series(np.nan, index=wide.index)).replace(0, np.nan)
        out[row.name] = ((numerator / denominator).rename("rate").reset_index(), level, row.type.strip())
    return out


def parcel_estimates(parcels: pd.DataFrame, occupancy: pd.DataFrame, rates: Dict[str, Tuple[pd.DataFrame, str, str]]) -> pd.DataFrame:
    """Apply block group and tract rates to parcels.

    parcels needs BLOCK_GROUP and TRACT (TRPAIDs), Residential_Units, and EXISTING_LANDUSE.
    Household variables scale with occupied units. Individual variables scale with residents.
    """
    p = parcels.copy()
    occ = occupancy.set_index("TRPAID")
    p["occupied_rate"] = p["BLOCK_GROUP"].map(occ["occupancy_rate"])
    p["seasonal_rate"] = p["BLOCK_GROUP"].map(occ["seasonal_rate"])
    p["population_per_unit"] = p["BLOCK_GROUP"].map(occ["population_per_unit"])
    p["MULTIFAMILY_UNITS"] = np.where(p["EXISTING_LANDUSE"] == "Multi-Family Residential", p["Residential_Units"], 0)
    p["occupied_units"] = p["occupied_rate"] * p["Residential_Units"]
    p["seasonal_units"] = p["seasonal_rate"] * p["Residential_Units"]
    p["num_of_residents"] = p["population_per_unit"] * p["Residential_Units"]
    for name, (rate_df, level, kind) in rates.items():
        key = "BLOCK_GROUP" if level == "block group" else "TRACT"
        rate = p[key].map(dict(zip(rate_df["TRPAID"], rate_df["rate"])))
        base = p["occupied_units"] if kind == "Household" else p["num_of_residents"]
        p[f"{safe_col(name)}_count"] = base * rate
    return p


def aggregate_to_polygons(parcels: pd.DataFrame, polygon_id: str, rates: dict) -> pd.DataFrame:
    """Add parcel estimates within each polygon and compute polygon rates."""
    spec = {c: "sum" for c in ("occupied_units", "seasonal_units", "num_of_residents", "MULTIFAMILY_UNITS", "Residential_Units")}
    for name in rates:
        spec[f"{safe_col(name)}_count"] = "sum"
    for col in ("CommercialFloorArea_SqFt", "TouristAccommodation_Units"):
        if col in parcels.columns:
            spec[col] = "sum"
    g = parcels.groupby(polygon_id).agg(spec).reset_index()
    total = (g["occupied_units"] + g["seasonal_units"]).replace(0, np.nan)
    g["total_units"] = g["occupied_units"] + g["seasonal_units"]
    g["occupied_unit_rate"] = g["occupied_units"] / total
    g["seasonal_unit_rate"] = g["seasonal_units"] / total
    g["multifamily_rate"] = g["MULTIFAMILY_UNITS"] / total
    for name, (_, _, kind) in rates.items():
        col = safe_col(name)
        denom = g["occupied_units"] if kind == "Household" else g["num_of_residents"]
        g[f"{col}_rate"] = g[f"{col}_count"] / denom.replace(0, np.nan)
    return g


def add_quartile_flags(df: pd.DataFrame, exclude=("year_sample",)) -> pd.DataFrame:
    """Add '<column>_top_quartile' (True or False as text) for each numeric column, and their count."""
    out = df.copy()
    numeric = [c for c in out.select_dtypes(include="number").columns if c not in exclude]
    for col in numeric:
        out[f"{col}_top_quartile"] = np.where(out[col] >= out[col].quantile(0.75), "True", "False")
    out["top_quartile_sum"] = (out[[f"{c}_top_quartile" for c in numeric]] == "True").sum(axis=1)
    return out


def adjustment_factors(census_bg: pd.DataFrame, hexes: pd.DataFrame) -> pd.DataFrame:
    """Per-year factors that scale hexagon totals to the block group totals for the basin."""
    totals = (census_bg[census_bg["variable_code"].isin([POP_CODE, HOUSEHOLD_CODE])]
              .groupby(["year_sample", "variable_code"])["value"].sum().unstack("variable_code")
              .rename(columns={POP_CODE: "census_population", HOUSEHOLD_CODE: "census_households"}).reset_index())
    totals["year_sample"] = totals["year_sample"].astype(int)
    hex_totals = hexes.groupby("year_sample")[["num_of_residents", "occupied_units"]].sum().reset_index()
    adj = totals.merge(hex_totals, on="year_sample", how="inner")
    adj["pop_adj_factor"] = adj["census_population"] / adj["num_of_residents"].replace(0, np.nan)
    adj["household_adj_factor"] = adj["census_households"] / adj["occupied_units"].replace(0, np.nan)
    return adj[["year_sample", "pop_adj_factor", "household_adj_factor"]]


def to_curated_hex_layout(hexes: pd.DataFrame, factors: pd.DataFrame, polygon_id: str) -> pd.DataFrame:
    """Scale hexagon estimates and name columns like Tahoe Census Curated (sample_level Hex Grid)."""
    h = hexes.merge(factors, on="year_sample", how="left")
    out = pd.DataFrame({"trpaid": h[polygon_id], "year_sample": h["year_sample"], "sample_level": "Hex Grid"})
    for field, (name, scale) in HEX_OUTPUT.items():
        col = f"{safe_col(name)}_count"
        if col in h.columns:
            factor = h["pop_adj_factor"] if scale == "pop" else h["household_adj_factor"]
            out[field] = (pd.to_numeric(h[col], errors="coerce") * factor).round(0)
    out["total_population"] = (h["num_of_residents"] * h["pop_adj_factor"]).round(0)
    out["total_households"] = (h["occupied_units"] * h["household_adj_factor"]).round(0)
    out["total_housing_units_occupied"] = out["total_households"]
    out["total_housing_units"] = h["Residential_Units"].round(0)
    out["vacant_housing_units_seasonal_recreational_or_occasional_use"] = (h["seasonal_units"] * h["household_adj_factor"]).round(0)
    out["total_housing_units_vacant"] = (out["total_housing_units"] - out["total_housing_units_occupied"]).clip(lower=0)
    return out


# ---------------------------------------------------------------------------
# ArcGIS steps (need ArcGIS Pro)
# ---------------------------------------------------------------------------

def _spatial_join(points_sdf, polygons_sdf, polygon_field: str):
    """Assign each parcel the polygon its center falls in (arcpy Spatial Join, HAVE_THEIR_CENTER_IN)."""
    import arcpy

    for name in ("memory/tess_parcels", "memory/tess_polygons", "memory/tess_join"):
        if arcpy.Exists(name):
            arcpy.management.Delete(name)
    points_sdf.spatial.to_featureclass("memory/tess_parcels")
    polygons_sdf.spatial.to_featureclass("memory/tess_polygons")
    arcpy.analysis.SpatialJoin("memory/tess_parcels", "memory/tess_polygons", "memory/tess_join",
                               "JOIN_ONE_TO_ONE", "KEEP_ALL", "", "HAVE_THEIR_CENTER_IN")
    values = [r[0] for r in arcpy.da.SearchCursor("memory/tess_join", [polygon_field])]
    out = points_sdf.copy().reset_index(drop=True)
    out[polygon_field] = values
    return out


def _read_feature_class(path: str, where: str = None):
    import arcpy

    fields = [f.name for f in arcpy.ListFields(path) if f.type != "Geometry"] + ["SHAPE@"]
    rows = list(arcpy.da.SearchCursor(path, fields, where_clause=where))
    df = pd.DataFrame(rows, columns=fields[:-1] + ["SHAPE"])
    df.spatial.set_geometry("SHAPE")
    return df


def run(settings: dict, census: pd.DataFrame, years, output_name: str = "Tessellation_Output") -> Dict[str, str]:
    """Run the full workflow for a range of years and write two feature classes.

    census is the long Census Data table (raw and grouped rows) for the years.
    Writes <output_name> (one row per hexagon and year, all rates and quartile flags)
    and <output_name>_curated_hex (Tahoe Census Curated fields, 2020 and later).
    """
    import arcpy
    from arcgis.features import FeatureLayer

    from .config import REPO_ROOT

    cfg = settings["tessellation"]
    for path in (cfg["output_gdb"],):
        if ".sde" in path.lower():
            raise PermissionError("Tessellation outputs go to a file geodatabase only.")
    arcpy.env.overwriteOutput = True
    config = pd.read_csv(REPO_ROOT / cfg["variables"], dtype=str)
    polygon_id = cfg["polygon_id"]
    hexes = _read_feature_class(cfg["tessellation_feature_class"])
    block_groups = pd.DataFrame.spatial.from_layer(FeatureLayer(settings["services"]["tahoe_geometry"]))
    block_groups = block_groups[block_groups["GEOGRAPHY"].str.lower() == "block group"]
    census_bg = census[census["sample_level"] == "block group"]
    results = []
    for year in years:
        parcels = _read_feature_class(cfg["parcel_feature_class"], where=f"YEAR = {int(year)}")
        if parcels.empty:
            print(f"  no parcels for {year}")
            continue
        vintage = 2010 if year < 2020 else 2020
        parcels = _spatial_join(parcels, block_groups[block_groups["YEAR"] == vintage][["TRPAID", "SHAPE"]], "TRPAID")
        parcels = parcels.rename(columns={"TRPAID": "BLOCK_GROUP"})
        parcels["TRACT"] = parcels["BLOCK_GROUP"].str[:11] + parcels["BLOCK_GROUP"].str[12:]
        rates = variable_rates(census, config, int(year))
        parcels = parcel_estimates(parcels, occupancy_rates(census_bg, int(year)), rates)
        parcels = _spatial_join(parcels, hexes[[polygon_id, "SHAPE"]], polygon_id)
        grid = hexes[[polygon_id]].drop_duplicates().merge(aggregate_to_polygons(parcels, polygon_id, rates), on=polygon_id, how="left")
        grid = add_quartile_flags(grid)
        grid["year_sample"] = int(year)
        results.append(grid)
    combined = pd.concat(results, ignore_index=True)
    factors = adjustment_factors(census_bg, combined)
    full = combined.merge(hexes[[polygon_id, "SHAPE"]], on=polygon_id, how="left")
    full.spatial.set_geometry("SHAPE")
    out_all = f"{cfg['output_gdb']}\\{output_name}"
    full.spatial.to_featureclass(location=out_all, overwrite=True)
    curated = to_curated_hex_layout(combined[combined["year_sample"] >= 2020], factors, polygon_id)
    curated = curated.merge(hexes[[polygon_id, "SHAPE"]].rename(columns={polygon_id: "trpaid"}), on="trpaid", how="left")
    curated.spatial.set_geometry("SHAPE")
    out_hex = f"{cfg['output_gdb']}\\{output_name}_curated_hex"
    curated.spatial.to_featureclass(location=out_hex, overwrite=True)
    return {"tessellation": out_all, "curated_hex": out_hex}
