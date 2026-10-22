"""Commute flows and workplace jobs from LEHD LODES.

LODES (LEHD Origin-Destination Employment Statistics) counts jobs by the Census
block where people live and the block where they work. This module:
1. Downloads the California and Nevada origin-destination files (main and aux)
   and the workplace area characteristics files for a year.
2. Keeps rows where the home or the workplace is a basin block (from the Tahoe
   Census Geography layer, 2020 blocks).
3. Labels each row: live in Tahoe and work in Tahoe, live in Tahoe and work
   elsewhere, or live elsewhere and work in Tahoe.
4. Adds tract and block TRPAIDs and centroid coordinates from Census TIGERweb.
5. Runs the QA checks from the original notebook against the years already
   published, then writes append files for the LODES tables. It never writes to SDE.

Output layouts match LTinfo_Climate_Resilience_Dashboard MapServer/141 (origin
destination) and MapServer/142 (work locations).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import requests

from . import services
from .config import outputs_dir
from .qaqc import CheckResult

CATEGORY = {
    (True, True): "Live in Tahoe, work in Tahoe",
    (True, False): "Live in Tahoe, work elsewhere",
    (False, True): "Live elsewhere, work in Tahoe",
}
OD_FIELDS = ["w_geocode", "h_geocode", "S000", "SA01", "SA02", "SA03", "SE01", "SE02", "SE03", "SI01", "SI02", "SI03",
             "createdate", "Year", "work_in_basin", "home_in_basin", "category",
             "h_tract_TRPAID", "w_tract_TRPAID", "h_block_TRPAID", "w_block_TRPAID",
             "h_block_lat", "h_block_long", "w_block_lat", "w_block_long",
             "h_tract_lat", "h_tract_long", "w_tract_lat", "w_tract_long", "w_tract_id", "h_tract_id"]

# Columns of the published work locations table (MapServer/142). It has no CR06 field.
WAC_FIELDS = (["w_geocode", "C000", "CA01", "CA02", "CA03", "CE01", "CE02", "CE03"]
              + [f"CNS{i:02d}" for i in range(1, 21)]
              + ["CR01", "CR02", "CR03", "CR04", "CR05", "CR07", "CT01", "CT02", "CD01", "CD02", "CD03", "CD04",
                 "CS01", "CS02", "CFA01", "CFA02", "CFA03", "CFA04", "CFA05", "CFS01", "CFS02", "CFS03", "CFS04", "CFS05",
                 "createdate", "Year", "w_block_lat", "w_block_long", "w_tract_TRPAID", "w_tract_id"])


def lodes_file_url(settings: dict, state: str, kind: str, year: int, part: str = "main") -> str:
    """URL of a LODES file. kind is od or wac."""
    cfg = settings["lodes"]
    if kind == "od":
        name = f"{state}_od_{part}_{cfg['od_job_type']}_{year}.csv.gz"
    else:
        name = f"{state}_wac_{cfg['wac_segment']}_{cfg['wac_job_type']}_{year}.csv.gz"
    return f"{cfg['base_url']}/{state}/{kind}/{name}"


def read_lodes_file(url: str, cache_dir: Path, session: requests.Session) -> pd.DataFrame:
    """Download a LODES file once (cached) and read it with geocodes as text."""
    path = cache_dir / url.rsplit("/", 1)[-1]
    if not path.exists():
        response = session.get(url, timeout=600)
        response.raise_for_status()
        path.write_bytes(response.content)
    return pd.read_csv(path, compression="gzip", dtype={"w_geocode": str, "h_geocode": str, "createdate": str})


def basin_geography(settings: dict, session) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return basin 2020 blocks and tracts with GEOID (from TRPAID) and TRPAID."""
    year = settings["lodes"]["block_geometry_year"]
    geo = services.query_layer(settings["services"]["tahoe_geometry"], session=session,
                               out_fields="YEAR,GEOGRAPHY,TRPAID", where=f"YEAR = {year}")
    geo["GEOID"] = geo["TRPAID"].str[:-4]
    level = geo["GEOGRAPHY"].str.lower()
    return geo[level == "block"][["GEOID", "TRPAID"]], geo[level == "tract"][["GEOID", "TRPAID"]]


def centroids(url: str, geoids: List[str], session) -> pd.DataFrame:
    """Look up centroid latitude and longitude for Census GEOIDs from TIGERweb."""
    frames = []
    ids = sorted(set(geoids))
    for i in range(0, len(ids), 200):
        frames.append(services.query_layer(url, session=session, out_fields="GEOID,CENTLAT,CENTLON",
                                           where=f"GEOID IN ({services.sql_in(ids[i:i + 200])})", order_by="GEOID"))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["GEOID", "CENTLAT", "CENTLON"])
    df["CENTLAT"] = pd.to_numeric(df["CENTLAT"], errors="coerce")
    df["CENTLON"] = pd.to_numeric(df["CENTLON"], errors="coerce")
    return df.drop_duplicates("GEOID")


def label_flows(od: pd.DataFrame, blocks: pd.DataFrame, tracts: pd.DataFrame) -> pd.DataFrame:
    """Keep flows with a basin home or workplace and add category and TRPAIDs."""
    basin_blocks = set(blocks["GEOID"])
    df = od[od["w_geocode"].isin(basin_blocks) | od["h_geocode"].isin(basin_blocks)].copy()
    df["work_in_basin"] = df["w_geocode"].isin(basin_blocks)
    df["home_in_basin"] = df["h_geocode"].isin(basin_blocks)
    df["category"] = [CATEGORY[(h, w)] for h, w in zip(df["home_in_basin"], df["work_in_basin"])]
    df["w_tract"] = df["w_geocode"].str[:11]
    df["h_tract"] = df["h_geocode"].str[:11]
    tract_ids = dict(zip(tracts["GEOID"], tracts["TRPAID"]))
    block_ids = dict(zip(blocks["GEOID"], blocks["TRPAID"]))
    for side in ("h", "w"):
        df[f"{side}_tract_TRPAID"] = df[f"{side}_tract"].map(tract_ids).fillna("Outside Basin")
        df[f"{side}_block_TRPAID"] = df[f"{side}_geocode"].map(block_ids).fillna("Outside Basin")
    return df


def add_centroids(df: pd.DataFrame, settings: dict, session) -> pd.DataFrame:
    """Add block centroids for basin blocks and tract centroids for every tract."""
    block_xy = centroids(settings["services"]["tigerweb_2020_blocks"],
                         list(df.loc[df["home_in_basin"], "h_geocode"]) + list(df.loc[df["work_in_basin"], "w_geocode"]), session)
    tract_xy = centroids(settings["services"]["tigerweb_2020_tracts"], list(df["h_tract"]) + list(df["w_tract"]), session)
    lat_b, lon_b = dict(zip(block_xy["GEOID"], block_xy["CENTLAT"])), dict(zip(block_xy["GEOID"], block_xy["CENTLON"]))
    lat_t, lon_t = dict(zip(tract_xy["GEOID"], tract_xy["CENTLAT"])), dict(zip(tract_xy["GEOID"], tract_xy["CENTLON"]))
    for side in ("h", "w"):
        df[f"{side}_block_lat"] = df[f"{side}_geocode"].map(lat_b)
        df[f"{side}_block_long"] = df[f"{side}_geocode"].map(lon_b)
        df[f"{side}_tract_lat"] = df[f"{side}_tract"].map(lat_t)
        df[f"{side}_tract_long"] = df[f"{side}_tract"].map(lon_t)
    return df


def to_od_layout(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Format flows like the published origin-destination table.

    Published years store true and false as TRUE and FALSE, tract ids without the
    leading zero, and geocodes as numbers. New rows follow the same convention.
    """
    out = df.copy()
    out["Year"] = int(year)
    for col in ("work_in_basin", "home_in_basin"):
        out[col] = out[col].map({True: "TRUE", False: "FALSE"})
    out["w_tract_id"] = out["w_tract"].astype("int64").astype(str)
    out["h_tract_id"] = out["h_tract"].astype("int64").astype(str)
    out["w_geocode"] = out["w_geocode"].astype("float64")
    out["h_geocode"] = out["h_geocode"].astype("float64")
    return out[OD_FIELDS]


def qa_checks(od: pd.DataFrame, inputs: Dict[str, pd.DataFrame], published: pd.DataFrame, year: int, settings: dict) -> List[CheckResult]:
    """QA checks from the original LODES notebook, as QAQC report rows.

    published has Year, category, and S000 totals from the published table.
    """
    cfg = settings["lodes"]
    results = []
    new = od.groupby("category")["S000"].sum()
    prev = published[published["Year"] == year - 1].set_index("category")["S000"]
    pct = (new / prev - 1).reindex(prev.index)
    home = od["home_in_basin"] == "TRUE"
    work = od["work_in_basin"] == "TRUE"
    unmatched = pd.concat([od.loc[home & (od["h_tract_TRPAID"] == "Outside Basin"), "h_tract_id"],
                           od.loc[work & (od["w_tract_TRPAID"] == "Outside Basin"), "w_tract_id"]])

    def add(name, severity, message, bad_rows):
        results.append(CheckResult(name, severity, message, bad_rows if isinstance(bad_rows, pd.DataFrame) else pd.DataFrame(bad_rows)))

    add("lodes_all_inputs_loaded", "fail", "All four origin-destination files loaded.",
        [{"file": k} for k, v in inputs.items() if v.empty])
    add("lodes_same_release", "fail", "All input files come from the same LODES release (createdate).",
        [] if pd.concat(inputs.values())["createdate"].nunique() <= 1 else [{"createdates": ", ".join(sorted(pd.concat(inputs.values())["createdate"].unique()))}])
    add("lodes_year_not_published", "fail", f"No {year} rows are already published.",
        [] if year not in set(published["Year"]) else [{"Year": year}])
    add("lodes_previous_year_published", "warn", f"{year - 1} is published for comparison.",
        [] if len(prev) == 3 else [{"Year": year - 1, "categories": len(prev)}])
    add("lodes_no_duplicate_pairs", "fail", "No origin-destination pair appears twice.",
        od[od.duplicated(["w_geocode", "h_geocode"], keep=False)][["w_geocode", "h_geocode"]])
    add("lodes_tract_centroids", "fail", "Every row has tract centroids.",
        od[od[["h_tract_lat", "h_tract_long", "w_tract_lat", "w_tract_long"]].isna().any(axis=1)][["h_tract_id", "w_tract_id"]])
    add("lodes_basin_block_ids", "fail", "Basin homes and workplaces have block TRPAIDs and centroids.",
        od[(home & ((od["h_block_TRPAID"] == "Outside Basin") | od["h_block_lat"].isna()))
           | (work & ((od["w_block_TRPAID"] == "Outside Basin") | od["w_block_lat"].isna()))][["h_geocode", "w_geocode"]])
    add("lodes_boundary_tracts", "warn", "Basin blocks without a basin tract are only in the known boundary tracts.",
        pd.DataFrame({"tract_id": sorted(set(unmatched) - set(cfg["known_boundary_tracts"]))}))
    low, high = cfg["total_jobs_range"]
    add("lodes_total_jobs_range", "warn", f"Total jobs between {low:,} and {high:,}.",
        [] if low <= new.sum() <= high else [{"total_jobs": int(new.sum())}])
    add("lodes_category_change", "warn", f"Each category within {cfg['category_change_warning']:.0%} of {year - 1}.",
        pct[pct.abs() > cfg["category_change_warning"]].rename("change").reset_index())
    return results


def build_year(settings: dict, year: int, session=None) -> Dict[str, object]:
    """Run the whole LODES workflow for one year and write append files and a QA report."""
    from .qaqc import write_report  # local import keeps module import light

    session = session or services.make_session()
    cache = outputs_dir(settings, "cache", "lodes")
    folder = outputs_dir(settings, "lodes", year)
    inputs = {}
    for state in settings["lodes"]["states"]:
        for part in ("main", "aux"):
            inputs[f"{state}_{part}"] = read_lodes_file(lodes_file_url(settings, state, "od", year, part), cache, session)
    od = pd.concat(inputs.values(), ignore_index=True)
    blocks, tracts = basin_geography(settings, session)
    flows = add_centroids(label_flows(od, blocks, tracts), settings, session)
    od_out = to_od_layout(flows, year)
    published = services.query_statistics(settings["services"]["lodes_origin_destination"], ["Year", "category"],
                                          [("sum", "S000", "S000")], session=session)
    results = qa_checks(od_out, inputs, published, year, settings)
    od_path = folder / f"lodes_origin_destination_{year}_append.csv"
    od_out.to_csv(od_path, index=False)

    wac = pd.concat([read_lodes_file(lodes_file_url(settings, s, "wac", year), cache, session) for s in settings["lodes"]["states"]], ignore_index=True)
    wac = wac[wac["w_geocode"].isin(set(blocks["GEOID"]))].copy()
    wac["Year"] = int(year)
    wac["w_tract"] = wac["w_geocode"].str[:11]
    wac["w_tract_TRPAID"] = wac["w_tract"].map(dict(zip(tracts["GEOID"], tracts["TRPAID"]))).fillna("Outside Basin")
    wac["w_tract_id"] = wac["w_tract"].astype("int64").astype(str)
    xy = centroids(settings["services"]["tigerweb_2020_blocks"], list(wac["w_geocode"]), session)
    wac["w_block_lat"] = wac["w_geocode"].map(dict(zip(xy["GEOID"], xy["CENTLAT"])))
    wac["w_block_long"] = wac["w_geocode"].map(dict(zip(xy["GEOID"], xy["CENTLON"])))
    wac["w_geocode"] = wac["w_geocode"].astype("float64")
    wac_path = folder / f"lodes_work_locations_{year}_append.csv"
    wac.reindex(columns=WAC_FIELDS).to_csv(wac_path, index=False)

    for side, label in (("w", "work"), ("h", "home")):
        points = (flows.groupby([f"{side}_geocode", "category"], as_index=False)
                  .agg(S000=("S000", "sum"), lat=(f"{side}_tract_lat", "first"), long=(f"{side}_tract_long", "first")))
        points.dropna(subset=["lat", "long"]).to_csv(folder / f"{label}_locations_{year}.csv", index=False)
    report = write_report(results, folder / "qaqc", f"LODES {year} QAQC report", "LODES files and published LODES tables")
    return {"origin_destination": od_path, "work_locations": wac_path, "report": report,
            "failed": [r.check for r in results if r.severity == "fail" and not r.passed]}
