"""Quality checks (QAQC) for downloads, groupings, and summaries.

Every check returns a row with:
  check      short name
  severity   fail (fix before publishing), warn (review), or info
  passed     True when nothing was found
  found      number of rows or groups the check flagged
  message    plain-language description of what the check looks for
and an optional detail table listing what it found.

write_report() saves an HTML page and one CSV per check under outputs/qaqc/.
Nothing here changes the data. Checks only report.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import services
from .config import census_geom_year
from .geography import add_geography_labels
from .summarize import non_additive_codes
from .tables import RAW_COLUMNS, RAW_KEY, SUMMARY_KEY

TRPAID_LENGTH = {"tract": 15, "block group": 16, "block": 19}


@dataclass
class CheckResult:
    check: str
    severity: str
    message: str
    details: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def found(self) -> int:
        return int(len(self.details))

    @property
    def passed(self) -> bool:
        return self.found == 0

    def as_row(self) -> dict:
        return {"check": self.check, "severity": self.severity, "passed": self.passed,
                "found": self.found, "message": self.message}


def _is_grouped(code: pd.Series) -> pd.Series:
    return code.astype(str).str.contains(":", regex=False)


# ---------------------------------------------------------------------------
# Raw (tract and block group) tables
# ---------------------------------------------------------------------------

def check_raw(df: pd.DataFrame, settings: dict, tahoe: Optional[pd.DataFrame] = None,
              variables: Optional[pd.DataFrame] = None, metadata: Optional[pd.DataFrame] = None) -> List[CheckResult]:
    """Run every check that applies to a long table in the Census Data layout."""
    results = []
    missing_cols = [c for c in RAW_COLUMNS if c not in df.columns]
    results.append(CheckResult("required_columns", "fail",
                               "Every Census Data column is present.",
                               pd.DataFrame({"missing_column": missing_cols})))
    if missing_cols:
        return results
    d = df.copy()
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d["MarginOfError"] = pd.to_numeric(d["MarginOfError"], errors="coerce")
    q = settings["qaqc"]

    dup = d[d.duplicated(RAW_KEY, keep=False)].sort_values(RAW_KEY)
    results.append(CheckResult("duplicate_records", "fail",
                               "No geography has the same variable twice for one year, sample level, and dataset.",
                               dup[RAW_KEY + ["value"]]))

    expected_len = d["sample_level"].map(TRPAID_LENGTH)
    expected_geom = d["year_sample"].map(lambda y: census_geom_year(int(y), settings) if pd.notna(y) else np.nan)
    bad_id = d[(d["TRPAID"].astype(str) != d["GEO_ID"].astype(str) + d["census_geom_year"].astype(str))
               | (expected_len.notna() & (d["TRPAID"].astype(str).str.len() != expected_len))
               | (d["census_geom_year"].astype(float) != expected_geom.astype(float))]
    results.append(CheckResult("trpaid_format", "fail",
                               "TRPAID equals GEO_ID plus the boundary year, has the right length for its level, and uses the boundary year that matches the data year.",
                               bad_id[["TRPAID", "GEO_ID", "sample_level", "year_sample", "census_geom_year"]].drop_duplicates()))

    if tahoe is not None:
        outside = d[~d["TRPAID"].isin(tahoe["TRPAID"])]
        results.append(CheckResult("inside_basin", "fail",
                                   "Every TRPAID is in the Tahoe Census Geography layer.",
                                   outside[["TRPAID", "sample_level", "year_sample"]].drop_duplicates()))
        expected = tahoe.groupby(["YEAR", "sample_level"])["TRPAID"].nunique().rename("expected").reset_index()
        found = d[~_is_grouped(d["variable_code"])].groupby(
            ["census_geom_year", "sample_level", "year_sample", "dataset", "variable_code"])["TRPAID"].nunique().rename("found").reset_index()
        cov = found.merge(expected, left_on=["census_geom_year", "sample_level"], right_on=["YEAR", "sample_level"], how="left")
        short = cov[cov["found"] < cov["expected"]].drop(columns="YEAR")
        results.append(CheckResult("geography_coverage", "warn",
                                   "Each variable has a value row for every basin tract or block group in the geography layer.",
                                   short))

    blanks = d[d["value"].isna()].groupby(["variable_code", "variable_name", "year_sample", "sample_level", "dataset"]).size().rename("blank_rows").reset_index()
    results.append(CheckResult("blank_values", "warn",
                               "Values are not blank. Blank values usually mean the Census Bureau suppressed or did not publish the estimate at that level.",
                               blanks))

    neg = d[d["value"] < 0]
    results.append(CheckResult("negative_values", "fail",
                               "No negative values. Negative numbers such as -666666666 are Census annotation codes, not data.",
                               neg[["TRPAID", "variable_code", "year_sample", "sample_level", "value"]]))

    acs = d[d["dataset"].astype(str).str.contains("acs/", regex=False) & ~_is_grouped(d["variable_code"])]
    no_moe = acs[acs["MarginOfError"].isna() & acs["value"].notna()].groupby(["variable_code", "year_sample", "sample_level"]).size().rename("rows").reset_index()
    results.append(CheckResult("missing_margin_of_error", "warn",
                               "ACS estimates have a margin of error.", no_moe))

    rel = acs[(acs["value"] > 0) & acs["MarginOfError"].notna()].copy()
    rel["cv"] = rel["MarginOfError"] / 1.645 / rel["value"]
    low = rel[rel["cv"] > q["cv_medium_reliability_max"]].groupby(["variable_code", "variable_name", "year_sample", "sample_level"]).agg(
        low_reliability_rows=("cv", "size"), median_cv=("cv", "median")).reset_index()
    results.append(CheckResult("low_reliability_estimates", "info",
                               f"Estimates with a coefficient of variation above {q['cv_medium_reliability_max']:.0%} are unreliable at that level. Summing to larger areas usually helps.",
                               low))

    names = d.groupby("variable_code").agg(names=("variable_name", lambda s: " | ".join(sorted(set(s.dropna().astype(str))))),
                                           categories=("variable_category", lambda s: " | ".join(sorted(set(s.dropna().astype(str))))),
                                           n_names=("variable_name", "nunique"), n_categories=("variable_category", "nunique")).reset_index()
    results.append(CheckResult("inconsistent_labels", "warn",
                               "Each variable_code has one variable_name and one variable_category across all years.",
                               names[(names["n_names"] > 1) | (names["n_categories"] > 1)]))

    cats = pd.Series(d["variable_category"].dropna().unique())
    case_dupes = cats.groupby(cats.str.lower().str.replace(r"\s+", " ", regex=True)).agg(list)
    results.append(CheckResult("category_spelling", "warn",
                               "Category names that differ only by capitalization or spacing are the same category.",
                               pd.DataFrame({"variants": [" | ".join(v) for v in case_dupes if len(v) > 1]})))

    if variables is not None:
        blocked = non_additive_codes(variables)
        flagged = d[[(c, ds) in blocked for c, ds in zip(d["variable_code"], d["dataset"])]]
        results.append(CheckResult("non_additive_variables_present", "info",
                                   "These variables are medians or averages. They are fine in the raw table but must never be summed.",
                                   flagged[["variable_code", "variable_name", "dataset"]].drop_duplicates()))

    if metadata is not None and not metadata.empty:
        results.append(check_table_totals(d, metadata))

    labelled = add_geography_labels(d[~_is_grouped(d["variable_code"])], settings)
    basin = labelled.groupby(["variable_code", "year_sample", "dataset", "sample_level"])["value"].sum(min_count=1).unstack("sample_level")
    if {"tract", "block group"}.issubset(basin.columns):
        both = basin.dropna(subset=["tract", "block group"])
        both = both[both["tract"] > 0]
        diff = ((both["block group"] - both["tract"]).abs() / both["tract"]).rename("relative_difference")
        bad = both.join(diff)[diff > q["tract_vs_block_group_tolerance"]].reset_index()
        results.append(CheckResult("tract_vs_block_group_totals", "warn",
                                   f"Basin totals from block groups are within {q['tract_vs_block_group_tolerance']:.0%} of totals from tracts. Large gaps mean the two geography lists cover different areas.",
                                   bad))

    yearly = labelled.groupby(["variable_code", "dataset", "sample_level", "year_sample"])["value"].sum(min_count=1).reset_index().sort_values("year_sample")
    yearly["previous"] = yearly.groupby(["variable_code", "dataset", "sample_level"])["value"].shift()
    yearly["change"] = (yearly["value"] - yearly["previous"]) / yearly["previous"].replace(0, np.nan)
    jumps = yearly[yearly["change"].abs() > q["year_over_year_change_warning"]]
    results.append(CheckResult("year_over_year_jumps", "warn",
                               f"Basin totals change by less than {q['year_over_year_change_warning']:.0%} from one year to the next. Jumps can be real, but they also appear when a boundary year or variable definition changes.",
                               jumps))
    return results


def _children(metadata: pd.DataFrame) -> Dict[str, List[str]]:
    """Map each Census variable to its direct children using the label hierarchy.

    Census labels are paths, such as Estimate!!Total:!!Male:!!Under 5 years.
    A variable is a direct child of another when its label adds exactly one level.
    """
    m = metadata[["variable_code", "label", "table"]].copy()
    m["path"] = m["label"].str.replace(":", "", regex=False).str.split("!!")
    m["depth"] = m["path"].str.len()
    m["key"] = m["path"].str.join("!!")
    lookup = {(t, k): c for t, k, c in zip(m["table"], m["key"], m["variable_code"])}
    kids: Dict[str, List[str]] = {}
    for row in m.itertuples():
        parent_key = "!!".join(row.path[:-1])
        parent = lookup.get((row.table, parent_key))
        if parent:
            kids.setdefault(parent, []).append(row.variable_code)
    return kids


def check_table_totals(d: pd.DataFrame, metadata: pd.DataFrame) -> CheckResult:
    """Check that each total equals the sum of its parts, where every part was downloaded."""
    kids = _children(metadata)
    present = set(d["variable_code"])
    wide = d[~_is_grouped(d["variable_code"])].pivot_table(index=["TRPAID", "year_sample", "sample_level"],
                                                          columns="variable_code", values="value", aggfunc="first")
    bad = []
    for parent, children in kids.items():
        if parent in present and all(c in present for c in children):
            diff = wide[parent] - wide[children].sum(axis=1, min_count=len(children))
            off = diff[diff.abs() > 1].dropna()
            for idx, gap in off.items():
                bad.append(dict(zip(["TRPAID", "year_sample", "sample_level"], idx), parent=parent, children=", ".join(children), difference=gap))
    return CheckResult("table_totals_add_up", "warn",
                       "Where a total and all of its parts were downloaded, the parts add up to the total.",
                       pd.DataFrame(bad))


# ---------------------------------------------------------------------------
# Grouping configuration
# ---------------------------------------------------------------------------

def check_groupings(groupings: pd.DataFrame, variables: pd.DataFrame,
                    metadata: Optional[pd.DataFrame] = None) -> List[CheckResult]:
    """Check config/groupings.csv for double counting and for codes that cannot be downloaded."""
    results = []
    multi = groupings[groupings.duplicated(["grouping_set", "dataset", "variable_code"], keep=False)]
    results.append(CheckResult("code_in_two_groups", "fail",
                               "Within one grouping set, each Census variable belongs to one group only.",
                               multi[["grouping_set", "dataset", "variable_code", "group_name"]].sort_values(["grouping_set", "variable_code"])))
    known = set(zip(variables["variable_code"], variables["dataset"]))
    unknown = groupings[[(c, ds) not in known for c, ds in zip(groupings["variable_code"], groupings["dataset"])]]
    results.append(CheckResult("group_member_not_in_variables", "warn",
                               "Every group member is listed in config/variables.csv, so the download step fetches it.",
                               unknown[["grouping_set", "dataset", "variable_code", "group_name"]]))
    blocked = non_additive_codes(variables)
    medians_in = groupings[[(c, ds) in blocked for c, ds in zip(groupings["variable_code"], groupings["dataset"])]]
    results.append(CheckResult("non_additive_group_member", "fail",
                               "Groups do not add medians, averages, or percentages.",
                               medians_in[["grouping_set", "variable_code", "group_name"]]))
    if metadata is not None and not metadata.empty:
        kids = _children(metadata)
        descendants: Dict[str, set] = {}

        def all_desc(code):
            if code not in descendants:
                descendants[code] = set()
                for k in kids.get(code, []):
                    descendants[code] |= {k} | all_desc(k)
            return descendants[code]

        overlaps = []
        for (gset, ds, name), members in groupings.groupby(["grouping_set", "dataset", "group_name"]):
            codes = set(members["variable_code"])
            for code in codes:
                inside = sorted(all_desc(code) & codes)
                if inside:
                    overlaps.append({"grouping_set": gset, "group_name": name, "total_variable": code,
                                     "parts_also_in_group": ", ".join(inside)})
        results.append(CheckResult("group_double_counts", "fail",
                                   "A group does not contain both a total and one of its parts. That counts the same people or households twice.",
                                   pd.DataFrame(overlaps)))
    return results


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

def check_summary(summary: pd.DataFrame, settings: dict) -> List[CheckResult]:
    """Check that summary rows are unique and that parts add up to the basin total."""
    results = []
    dup = summary[summary.duplicated(SUMMARY_KEY, keep=False)]
    results.append(CheckResult("duplicate_summary_rows", "fail",
                               "Each geography has one row per variable, year, sample level, dataset, and category.",
                               dup))
    basin_label = settings.get("basin_label", "Basin")
    counties = {c["county_name"] for c in settings["counties"]}
    shores = {c["north_south"] for c in settings["counties"]}
    states = {c["state_name"] for c in settings["counties"]}
    keys = ["variable_code", "year_sample", "dataset", "sample_level"]
    basin = summary[summary["Geography"] == basin_label].set_index(keys)["value"]
    for name, members in (("counties_add_to_basin", counties), ("shores_add_to_basin", shores), ("states_add_to_basin", states)):
        parts = summary[summary["Geography"].isin(members)].groupby(keys)["value"].sum(min_count=1)
        joined = pd.concat([basin.rename("basin"), parts.rename("sum_of_parts")], axis=1).dropna()
        off = joined[(joined["basin"] - joined["sum_of_parts"]).abs() > 0.5].reset_index()
        results.append(CheckResult(name, "fail", f"The {name.split('_')[0]} add up to the basin total.", off))
    return results


# ---------------------------------------------------------------------------
# Comparison with the published service (read only)
# ---------------------------------------------------------------------------

def compare_with_service(df: pd.DataFrame, settings: dict, session=None) -> List[CheckResult]:
    """Compare a new raw table with records already in the Census Data service.

    Rows whose key already exists would become duplicates if appended.
    Rows whose value differs from the published value need a decision.
    This reads the service only. It never changes it.
    """
    url = settings["services"]["census_data"]
    session = session or services.make_session()
    frames = []
    for year, part in df.groupby("year_sample"):
        codes = sorted(part["variable_code"].dropna().unique())
        for i in range(0, len(codes), 50):
            where = f"year_sample = {int(year)} AND variable_code IN ({services.sql_in(codes[i:i + 50])})"
            frames.append(services.query_layer(url, where=where, session=session,
                                               out_fields="TRPAID,variable_code,year_sample,sample_level,dataset,value"))
    published = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=RAW_KEY + ["value"])
    if published.empty:
        return [CheckResult("already_published", "warn", "None of these rows exist in the Census Data service yet.", pd.DataFrame()),
                CheckResult("published_value_differs", "warn", "Values match the published values.", pd.DataFrame())]
    published["year_sample"] = pd.to_numeric(published["year_sample"]).astype("Int64")
    new = df.copy()
    new["year_sample"] = pd.to_numeric(new["year_sample"]).astype("Int64")
    both = new.merge(published, on=RAW_KEY, how="inner", suffixes=("", "_published"))
    differs = both[(both["value"] - both["value_published"]).abs() > 0.5]
    return [
        CheckResult("already_published", "warn",
                    "These rows already exist in the Census Data service. Appending them would create duplicates.",
                    both[RAW_KEY]),
        CheckResult("published_value_differs", "warn",
                    "These rows exist in the service with a different value.",
                    differs[RAW_KEY + ["value", "value_published"]]),
    ]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def results_table(results: List[CheckResult]) -> pd.DataFrame:
    return pd.DataFrame([r.as_row() for r in results])


def write_report(results: List[CheckResult], folder: Path, title: str, source: str) -> Path:
    """Write qaqc_report.html, qaqc_summary.csv, and one CSV per check that found something."""
    folder.mkdir(parents=True, exist_ok=True)
    table = results_table(results)
    table.to_csv(folder / "qaqc_summary.csv", index=False)
    sections = []
    for r in results:
        if not r.passed:
            r.details.to_csv(folder / f"{r.check}.csv", index=False)
        badge = "pass" if r.passed else r.severity
        body = "" if r.passed else r.details.head(25).to_html(index=False, border=0, classes="detail", na_rep="")
        more = f"<p class='more'>Showing 25 of {r.found:,}. Full list: {r.check}.csv</p>" if r.found > 25 else ""
        sections.append(f"<section><h3><span class='badge {badge}'>{badge}</span> {html.escape(r.check)}"
                        f" <small>{r.found:,} found</small></h3><p>{html.escape(r.message)}</p>{body}{more}</section>")
    counts = table.assign(status=np.where(table["passed"], "pass", table["severity"]))["status"].value_counts()
    tiles = "".join(f"<div class='tile {k}'><b>{v}</b>{k}</div>" for k, v in counts.items())
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{font-family:'Open Sans',Segoe UI,sans-serif;color:#003B71;margin:0;background:#f5f5f5}}
header{{background:#003B71;color:#fff;padding:16px 24px}} header h1{{margin:0;font-size:22px}}
main{{max-width:1100px;margin:0 auto;padding:16px 24px}} .tiles{{display:flex;gap:12px;margin:12px 0}}
.tile{{background:#fff;border-top:4px solid #0072CE;padding:10px 16px;border-radius:6px;text-transform:capitalize}}
.tile b{{display:block;font-size:24px}} .tile.fail{{border-color:#9C3E27}} .tile.warn{{border-color:#E87722}} .tile.pass{{border-color:#4A6118}}
section{{background:#fff;border-radius:6px;padding:8px 16px;margin:10px 0}} h3{{font-size:16px}} small{{color:#555;font-weight:400}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;color:#fff;font-size:12px;text-transform:uppercase}}
.badge.pass{{background:#4A6118}} .badge.fail{{background:#9C3E27}} .badge.warn{{background:#9a4f00}} .badge.info{{background:#0068A8}}
table.detail{{border-collapse:collapse;font-size:12px;width:100%;overflow-x:auto;display:block}} table.detail td,table.detail th{{border-bottom:1px solid #ddd;padding:3px 6px;text-align:left}}
.more{{font-size:12px;color:#555}}
</style></head><body><header><div>Tahoe Regional Planning Agency</div><h1>{html.escape(title)}</h1></header>
<main><p>Source: {html.escape(source)}</p><div class="tiles">{tiles}</div>{''.join(sections)}</main></body></html>"""
    path = folder / "qaqc_report.html"
    path.write_text(page, encoding="utf-8")
    return path
