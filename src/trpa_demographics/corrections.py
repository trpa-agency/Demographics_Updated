"""Build append files that fix known errors in the published demographic tables.

The published services are append-only from this toolkit's point of view.
To fix a record, the corrections step writes:
  <layer>_append.csv   corrected copies of the records, in the layer's own columns
  <layer>_retire.csv   OBJECTIDs of the records the copies replace, with the reason
A person loads the append file, checks it, and then deletes (or flags with
delete_flag = 1) the retired records. Nothing here writes to a service or SDE.

What gets fixed is listed in config/corrections/:
  relabel.csv       wrong names and categories for specific codes (A2, A3, C2)
  spelling.csv      category, name, and geography spellings (B4)
  regroup.csv       grouped rows rebuilt from the published detail rows (A4)
  replacements.csv  correct Census codes to download for the same years (A2, A3)
  field_updates.csv fields in the curated polygon layer to refill (A3)
Dataset values with a grouping prefix, such as "Prescence of Children: acs/acs5",
are reset to the Census dataset name (B2) using valid_datasets in settings.json.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import census_api, geography, grouping, services, summarize
from .config import CONFIG_DIR, GROUPINGS_PATH, VARIABLES_PATH, outputs_dir
from .tables import RAW_COLUMNS, RAW_KEY, write_table

CORRECTIONS_DIR = CONFIG_DIR / "corrections"
SYSTEM_FIELDS = {"OBJECTID", "GlobalID", "created_user", "created_date", "last_edited_user", "last_edited_date",
                 "Shape", "SHAPE", "Shape.STArea()", "Shape.STLength()", "SHAPE.STArea()", "SHAPE.STLength()"}

# Field names in each published table.
LAYERS: Dict[str, dict] = {
    "census_data": {"code": "variable_code", "name": "variable_name", "category": "variable_category",
                    "dataset": "dataset", "year": "year_sample", "level": "sample_level", "geo": "TRPAID"},
    "demographic_summaries": {"code": "Code", "name": None, "category": "Category",
                              "dataset": "Source", "year": "Year", "level": None, "geo": "Geography"},
    "climate_dashboard_census_data": {"code": "variable_code", "name": "variable_name", "category": "Category",
                                      "dataset": "dataset", "year": "year_sample", "level": "sample_level", "geo": "Geography"},
}
DATASET_PATTERN = re.compile(r"((?:acs|dec)/[A-Za-z0-9/]+|cbp|zbp)\s*$")


def load_rules(folder: Path = CORRECTIONS_DIR) -> Dict[str, pd.DataFrame]:
    """Read every CSV in config/corrections as text."""
    return {p.stem: pd.read_csv(p, dtype=str).fillna("") for p in sorted(Path(folder).glob("*.csv"))}


def clean_dataset(value: str, valid: List[str]) -> str:
    """Return the Census dataset name at the end of a prefixed value.

    "Prescence of Children: acs/acs5" and "TRPA 5-year Age Categoriesacs/acs5" become "acs/acs5".
    Values that are already valid, or that hold no Census dataset name, are returned unchanged.
    """
    text = str(value)
    if text in valid:
        return text
    match = DATASET_PATTERN.search(text)
    return match.group(1) if match and match.group(1) in valid else text


def _sql_or(clauses: List[str]) -> str:
    return " OR ".join(f"({c})" for c in clauses if c) or "1=0"


def where_for_layer(layer: str, rules: Dict[str, pd.DataFrame], settings: dict) -> str:
    """Build one where clause that finds every record any rule could change in a layer."""
    f = LAYERS[layer]
    clauses = []
    relabel = rules.get("relabel", pd.DataFrame())
    for r in relabel[relabel.get("layer", pd.Series(dtype=str)) == layer].itertuples():
        parts = []
        if r.variable_code:
            parts.append(f"{f['code']} = '{r.variable_code}'")
        if r.match_name and f["name"]:
            parts.append(f"{f['name']} = {services.sql_in([r.match_name])}")
        if r.match_category:
            parts.append(f"{f['category']} = {services.sql_in([r.match_category])}")
        clauses.append(" AND ".join(parts))
    spelling = rules.get("spelling", pd.DataFrame())
    for r in spelling[spelling.get("layer", pd.Series(dtype=str)) == layer].itertuples():
        clauses.append(f"{r.field} = {services.sql_in([r.old_value])}")
    regroup = rules.get("regroup", pd.DataFrame())
    for r in regroup[regroup.get("layer", pd.Series(dtype=str)) == layer].itertuples():
        clauses.append(f"{f['category']} = {services.sql_in([r.old_variable_category])}")
    clauses.append(f"{f['dataset']} NOT IN ({services.sql_in(settings['valid_datasets'])}) AND {f['dataset']} LIKE '%/%'")
    return _sql_or(clauses)


def apply_rules(df: pd.DataFrame, layer: str, rules: Dict[str, pd.DataFrame], settings: dict) -> pd.DataFrame:
    """Apply relabel, dataset, and spelling rules to published records.

    Returns the records with corrected values and a 'reasons' column. Rows no rule
    changed have an empty 'reasons' value. Regroup rules are handled separately.
    """
    f = LAYERS[layer]
    out = df.copy()
    reasons = pd.Series([[] for _ in range(len(out))], index=out.index)

    def note(mask, text):
        for i in out.index[mask]:
            reasons[i].append(text)

    relabel = rules.get("relabel", pd.DataFrame())
    for r in relabel[relabel.get("layer", pd.Series(dtype=str)) == layer].itertuples():
        mask = pd.Series(True, index=out.index)
        if r.variable_code:
            mask &= out[f["code"]] == r.variable_code
        if r.dataset:
            mask &= out[f["dataset"]].map(lambda d: clean_dataset(d, settings["valid_datasets"])) == r.dataset
        if r.match_name and f["name"]:
            mask &= out[f["name"]] == r.match_name
        if r.match_category:
            mask &= out[f["category"]] == r.match_category
        if r.new_name and f["name"]:
            out.loc[mask, f["name"]] = r.new_name
        if r.new_category:
            out.loc[mask, f["category"]] = r.new_category
        note(mask, r.reason)

    cleaned = out[f["dataset"]].map(lambda d: clean_dataset(d, settings["valid_datasets"]))
    note(cleaned != out[f["dataset"]], "B2: dataset holds the Census dataset name only")
    out[f["dataset"]] = cleaned

    spelling = rules.get("spelling", pd.DataFrame())
    for r in spelling[spelling.get("layer", pd.Series(dtype=str)) == layer].itertuples():
        if r.field in out.columns:
            mask = out[r.field] == r.old_value
            out.loc[mask, r.field] = r.new_value
            note(mask, r.reason)

    out["reasons"] = reasons.map(lambda items: "; ".join(dict.fromkeys(items)))
    return out


def _append_columns(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c not in SYSTEM_FIELDS and c != "reasons"]


def regroup_census_data(published_raw: pd.DataFrame, old_grouped: pd.DataFrame, grouping_set: str,
                        settings: dict) -> pd.DataFrame:
    """Rebuild grouped rows for the years and levels of the old grouped rows, from published detail rows."""
    cfg = grouping.load_groupings(GROUPINGS_PATH)
    cfg = cfg[cfg["grouping_set"] == grouping_set]
    years = set(zip(old_grouped["year_sample"].astype(int), old_grouped["sample_level"]))
    raw = published_raw.copy()
    raw["year_sample"] = pd.to_numeric(raw["year_sample"]).astype(int)
    raw = raw[[(y, lvl) in years for y, lvl in zip(raw["year_sample"], raw["sample_level"])]]
    if "block_group" not in raw.columns and "block group" in raw.columns:
        raw = raw.rename(columns={"block group": "block_group"})
    for col in RAW_COLUMNS:
        if col not in raw.columns:
            raw[col] = pd.NA
    grouped, _ = grouping.apply_groupings(raw[RAW_COLUMNS], cfg, settings)
    return grouped


def build_corrections(settings: dict, session=None, download: bool = False, api_key: Optional[str] = None,
                      label: Optional[str] = None) -> Dict[str, Path]:
    """Read the published tables, apply every rule, and write append and retire files.

    Reads services only. download=True also downloads replacement codes from the
    Census API (needs an API key). Returns the paths written.
    """
    session = session or services.make_session()
    rules = load_rules()
    folder = outputs_dir(settings, "corrections", label or date.today().isoformat())
    written: Dict[str, Path] = {}
    summary_rows, conflicts = [], []
    new_census_rows = []

    for layer, f in LAYERS.items():
        url = settings["services"][layer]
        affected = services.query_layer(url, where=where_for_layer(layer, rules, settings), session=session)
        if affected.empty:
            continue
        regroup = rules.get("regroup", pd.DataFrame())
        regroup = regroup[regroup["layer"] == layer] if not regroup.empty else regroup
        regroup_mask = affected[f["category"]].isin(regroup["old_variable_category"]) if not regroup.empty else pd.Series(False, index=affected.index)
        fixed = apply_rules(affected[~regroup_mask], layer, rules, settings)
        changed = fixed[fixed["reasons"] != ""]
        retire = [changed[["OBJECTID"]].assign(reason=changed["reasons"])]
        appended = [changed[_append_columns(changed)].assign(**({"delete_flag": 0} if "delete_flag" in changed.columns else {}))]

        for r in regroup.itertuples() if not regroup.empty else []:
            old = affected[affected[f["category"]] == r.old_variable_category]
            if old.empty:
                continue
            retire.append(old[["OBJECTID"]].assign(reason=r.reason))
            members = grouping.load_groupings(GROUPINGS_PATH)
            codes = members.loc[members["grouping_set"] == r.grouping_set, "variable_code"].unique()
            raw = services.query_layer(settings["services"]["census_data"], session=session,
                                       where=f"variable_code IN ({services.sql_in(codes)})")
            if layer == "census_data":
                regrouped = regroup_census_data(raw, old, r.grouping_set, settings)
                new_census_rows.append(regrouped)
                appended.append(regrouped.assign(delete_flag=0))
            else:
                years = set(pd.to_numeric(old[f["year"]]).astype(int))
                level = settings["demographic_summaries_layout"]["sample_level"]
                pseudo = pd.DataFrame({"year_sample": sorted(years), "sample_level": level})
                regrouped = regroup_census_data(raw, pseudo, r.grouping_set, settings)
                summary, _, partial = summarize.summarize(regrouped, settings, levels=["Basin", "County", "North/South", "State"])
                appended.append(summarize.to_layer18(summary, settings, partial))

        append_df = pd.concat([a for a in appended if not a.empty], ignore_index=True) if any(not a.empty for a in appended) else pd.DataFrame()
        retire_df = pd.concat(retire, ignore_index=True).drop_duplicates("OBJECTID") if retire else pd.DataFrame()
        if not append_df.empty:
            written[f"{layer}_append"] = write_table(append_df, folder / f"{layer}_append.csv")
            written[f"{layer}_retire"] = write_table(retire_df, folder / f"{layer}_retire.csv")
            if layer == "census_data":
                conflicts.append(_conflicts(append_df, retire_df, url, session))
        for reason, n in retire_df["reason"].str.split("; ").explode().value_counts().items():
            summary_rows.append({"layer": layer, "reason": reason, "records_replaced": n})

    if download:
        replaced = _download_replacements(settings, session, api_key, rules)
        if not replaced.empty:
            written["census_data_replacements_append"] = write_table(replaced, folder / "census_data_replacements_append.csv", RAW_COLUMNS)
            summary_rows.append({"layer": "census_data", "reason": "replacement codes downloaded", "records_replaced": 0, "records_added": len(replaced)})

    updates = _curated_field_updates(settings, session, rules)
    if not updates.empty:
        written["tahoe_census_curated_field_updates"] = write_table(updates, folder / "tahoe_census_curated_field_updates.csv")
        summary_rows.append({"layer": "tahoe_census_curated", "reason": "field updates", "records_replaced": len(updates)})

    found = [c for c in conflicts if c is not None and not c.empty]
    conflict_df = pd.concat(found, ignore_index=True) if found else pd.DataFrame()
    if not conflict_df.empty:
        written["conflicts"] = write_table(conflict_df, folder / "conflicts.csv")
    written["summary"] = write_table(pd.DataFrame(summary_rows), folder / "corrections_summary.csv")
    (folder / "README.txt").write_text(LOAD_STEPS, encoding="utf-8")
    return written


def _conflicts(append_df: pd.DataFrame, retire_df: pd.DataFrame, url: str, session) -> pd.DataFrame:
    """Find appended Census Data rows whose key matches a published row that is not being retired."""
    keys = _normal_keys(append_df)
    internal = keys[keys.duplicated(keep=False)].assign(conflict="appears twice in the append file")
    frames = [internal]
    codes = sorted(append_df["variable_code"].dropna().unique())
    retired = set(retire_df["OBJECTID"].astype(int))
    for i in range(0, len(codes), 50):
        published = services.query_layer(url, session=session, out_fields="OBJECTID," + ",".join(RAW_KEY),
                                         where=f"variable_code IN ({services.sql_in(codes[i:i + 50])})")
        if published.empty:
            continue
        published = published[~published["OBJECTID"].astype(int).isin(retired)]
        clash = keys.merge(_normal_keys(published), on=RAW_KEY, how="inner")
        frames.append(clash.assign(conflict="matches a published record that is not retired"))
    return pd.concat(frames, ignore_index=True)


def _normal_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Key columns as text, with years written as whole numbers, so service and file rows compare."""
    keys = df[RAW_KEY].copy()
    keys["year_sample"] = pd.to_numeric(keys["year_sample"], errors="coerce").astype("Int64").astype(str)
    return keys.astype(str)


def _download_replacements(settings, session, api_key, rules) -> pd.DataFrame:
    """Download replacement codes for every year and level where a wrong code was published."""
    repl = rules.get("replacements", pd.DataFrame())
    if repl.empty:
        return pd.DataFrame()
    census_api.require_api_key(api_key, settings)
    url = settings["services"]["census_data"]
    variables = pd.read_csv(VARIABLES_PATH, dtype=str).fillna("")
    tahoe = geography.get_tahoe_geometry(settings, session)
    frames = []
    for r in repl.itertuples():
        combos = services.query_statistics(url, ["year_sample", "sample_level"], [("count", "OBJECTID", "n")],
                                           where=f"variable_code = '{r.wrong_code}'", session=session)
        have = services.query_statistics(url, ["year_sample", "sample_level"], [("count", "OBJECTID", "n")],
                                         where=f"variable_code = '{r.replacement_code}'", session=session)
        have_set = set(zip(have.get("year_sample", []), have.get("sample_level", [])))
        meta = variables[(variables["variable_code"] == r.replacement_code) & (variables["dataset"] == r.dataset)]
        if meta.empty:
            raise ValueError(f"{r.replacement_code} is not in config/variables.csv")
        for c in combos.itertuples():
            if (c.year_sample, c.sample_level) in have_set:
                continue
            batch = meta.assign(sample_level=c.sample_level)
            result = census_api.download_year(settings, batch, int(c.year_sample), tahoe, api_key, session,
                                              label=f"replacement_{r.replacement_code}")
            frames.append(pd.read_csv(result["data"], dtype=str))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _curated_field_updates(settings, session, rules) -> pd.DataFrame:
    """List field updates for the Tahoe Census Curated polygons, keyed on OBJECTID.

    The curated layer holds shapes, so it is fixed by updating a field in place
    (or rebuilding it with the curated command), not by appending rows.
    """
    upd = rules.get("field_updates", pd.DataFrame())
    if upd.empty:
        return pd.DataFrame()
    frames = []
    for r in upd.itertuples():
        levels = [lvl.strip() for lvl in r.sample_levels.split(";") if lvl.strip()]
        layer = services.query_layer(settings["services"][r.layer], session=session,
                                     out_fields=f"OBJECTID,trpaid,year_sample,sample_level,{r.field}",
                                     where=f"sample_level IN ({services.sql_in(levels)})")
        source = services.query_layer(settings["services"]["census_data"], session=session,
                                      out_fields="TRPAID,year_sample,sample_level,value",
                                      where=f"variable_code = '{r.variable_code}' AND dataset = '{r.dataset}'")
        if layer.empty:
            continue
        source = source.rename(columns={"TRPAID": "trpaid", "value": "new_value"})
        merged = layer.merge(source, on=["trpaid", "year_sample", "sample_level"], how="left")
        merged = merged.rename(columns={r.field: "old_value"}).assign(field=r.field, reason=r.reason)
        merged["status"] = np.where(merged["new_value"].isna(), f"{r.variable_code} not published yet for this year and level; run corrections with --download first", "ready")
        frames.append(merged[["OBJECTID", "trpaid", "year_sample", "sample_level", "field", "old_value", "new_value", "status", "reason"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


LOAD_STEPS = """How to load these corrections (nothing here has been applied)

1. Open corrections_summary.csv to see what each file fixes.
2. If conflicts.csv exists, resolve every row before loading. A conflict means an
   appended record would duplicate a published record that is not being retired.
3. For each <layer>_append.csv: load it into a file geodatabase table
   (python -m trpa_demographics export-gdb), review it in ArcGIS Pro, then append
   it to the matching SDE table.
4. After the append is checked, delete the records listed in <layer>_retire.csv
   (or set delete_flag = 1 in the Census Data table).
5. census_data_replacements_append.csv (only with --download) holds the correct
   Census codes for the years where wrong codes were published. Append it like step 3.
6. tahoe_census_curated_field_updates.csv lists field values to change in the
   Tahoe Census Curated layer, keyed on OBJECTID. Rows marked "ready" can be applied
   with a field calculation or join. Or rebuild the layer with the curated command.
7. Rerun python -m trpa_demographics qaqc --service to confirm the fixes.
"""
