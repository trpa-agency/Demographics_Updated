"""Command line entry point.

Run from the repository folder in the ArcGIS Pro Python environment:

    python -m trpa_demographics <command> [options]

Commands
  find        search Census variables and add them to config/variables.csv
  download    download variables for one or more years
  group       combine detailed variables into TRPA categories
  summarize   roll values up to Basin, County, North/South, and State
  qaqc        run quality checks and write an HTML report
  inventory   list what is already published in the TRPA services
  run         download, group, summarize, and check one or more years
  export-gdb  copy a reviewed CSV into a file geodatabase table
  corrections build append and retire files that fix published errors (reads only)
  comparison  download whole counties, states, and metro areas for comparison
  jobs        download jobs by ZIP code (County Business Patterns)
  lodes       build LODES commute and workplace append files for a year
  curated     build a wide map layer table (Tahoe Census Curated, TDC values)
  tessellation spread block group values onto the hexagon grid (ArcGIS Pro)
  import-1990 read 1990 STF3 DBF files
  enrollment  build school enrollment by school for California and Nevada
  inflate     convert dollar values to one year's dollars

Add --help after any command for its options.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import pandas as pd

from . import census_api, geography, grouping, inventory, qaqc, services, summarize
from .config import (GROUPINGS_PATH, MEDIANS_PATH, VARIABLES_PATH, get_api_key, load_settings, outputs_dir)
from .tables import LAYER18_COLUMNS, RAW_COLUMNS, SUMMARY_COLUMNS, read_table, write_table


def _years(args) -> List[int]:
    end = args.year_end or args.year
    return list(range(args.year, end + 1))


def _stem(paths: List[str]) -> str:
    return Path(paths[0]).stem if len(paths) == 1 else f"{Path(paths[0]).stem}_and_{len(paths) - 1}_more"


def _metadata_for(df: pd.DataFrame, settings: dict, session) -> pd.DataFrame:
    """Fetch Census table definitions for the ACS and DHC tables in a table. Returns empty on failure."""
    frames = []
    raw = df[~df["variable_code"].astype(str).str.contains(":", regex=False)]
    for (year, dataset), part in raw.groupby(["year_sample", "dataset"]):
        for table in sorted({census_api.table_id(c) for c in part["variable_code"]}):
            try:
                frames.append(census_api.table_metadata(settings, session, int(year), dataset, table))
            except Exception as exc:  # metadata is optional; the check is skipped when it is missing
                print(f"  could not read Census definitions for {table} {year} {dataset}: {exc}")
    return pd.concat(frames, ignore_index=True).drop_duplicates("variable_code") if frames else pd.DataFrame()


def cmd_find(args, settings):
    session = services.make_session()
    found = census_api.search_variables(settings, session, args.year, args.dataset, text=args.search, table=args.table)
    if found.empty:
        print("No variables matched.")
        return
    rows = census_api.draft_variable_rows(found, args.dataset, args.category or "", args.level)
    out = outputs_dir(settings, "variable_search") / f"search_{args.table or args.search}".replace(" ", "_")
    path = write_table(rows, out.with_suffix(".csv"))
    print(rows[["variable_code", "variable_name"]].to_string(index=False, max_rows=60))
    print(f"\n{len(rows)} variables written to {path}")
    if args.add:
        current = pd.read_csv(VARIABLES_PATH, dtype=str)
        new = rows[~rows.set_index(["variable_code", "dataset"]).index.isin(current.set_index(["variable_code", "dataset"]).index)]
        pd.concat([current, new.astype(str)], ignore_index=True).to_csv(VARIABLES_PATH, index=False)
        print(f"Added {len(new)} new rows to {VARIABLES_PATH}. Review the names and categories before downloading.")


def cmd_download(args, settings):
    session = services.make_session()
    variables = census_api.expand_variable_list(pd.read_csv(args.variables, dtype=str), args.dataset,
                                                args.category, active_only=not args.include_inactive)
    if variables.empty:
        sys.exit("No variables match those filters in the variable list.")
    print(f"{variables['variable_code'].nunique()} variables, levels: {sorted(variables['sample_level'].unique())}")
    key = get_api_key(settings)
    census_api.require_api_key(key, settings)
    tahoe = geography.get_tahoe_geometry(settings, session)
    results = []
    for year in _years(args):
        print(f"Year {year}")
        results.append(census_api.download_year(settings, variables, year, tahoe, key, session, args.label))
        print(f"  saved {results[-1]['rows']:,} rows to {results[-1]['data']}")
        for extra in ("annotations", "unknown_variables"):
            if extra in results[-1]:
                print(f"  see {results[-1][extra]}")
    return results


def cmd_group(args, settings):
    raw = read_table(args.input)
    grouped, gaps = grouping.apply_groupings(raw, grouping.load_groupings(args.groupings), settings, args.sets)
    folder = outputs_dir(settings, "grouped")
    path = write_table(grouped, folder / f"grouped_{_stem(args.input)}.csv", RAW_COLUMNS)
    print(f"{len(grouped):,} grouped rows written to {path}")
    if not gaps.empty:
        gp = write_table(gaps, folder / f"grouped_{_stem(args.input)}_partial.csv")
        print(f"{len(gaps):,} grouped values add up fewer members than the group lists (a member was blank). See {gp}")
    return path


def cmd_summarize(args, settings):
    raw = read_table(args.input)
    variables = pd.read_csv(VARIABLES_PATH, dtype=str)
    summary, skipped, partial = summarize.summarize(raw, settings, variables, args.levels)
    folder = outputs_dir(settings, "summaries")
    stem = _stem(args.input)
    if not args.no_medians:
        medians = summarize.compute_medians(raw, summarize.load_medians(MEDIANS_PATH), settings, args.levels)
        if not medians.empty:
            summary = pd.concat([summary, medians[SUMMARY_COLUMNS + ["MarginOfError"]]], ignore_index=True)
            notes = medians[medians["note"] != ""]
            if not notes.empty:
                write_table(notes, folder / f"summary_{stem}_median_notes.csv")
                print(f"{len(notes)} medians have notes (open-ended bin or blank bins). See summary_{stem}_median_notes.csv")
    path = write_table(summary, folder / f"summary_{stem}.csv", SUMMARY_COLUMNS)
    write_table(summary, folder / f"summary_{stem}_margins_of_error.csv", SUMMARY_COLUMNS + ["MarginOfError"])
    write_table(summarize.to_layer18(summary, settings, partial), folder / f"summary_{stem}_demographic_summaries.csv", LAYER18_COLUMNS)
    print(f"{len(summary):,} summary rows written to {path}")
    print("  also written: margins of error, and the same values in the Demographic Summaries (layer 18) layout")
    if not skipped.empty:
        write_table(skipped, folder / f"summary_{stem}_skipped.csv")
        print(f"{len(skipped)} variables were skipped because they cannot be added (medians, averages, percentages).")
    if not partial.empty:
        write_table(partial, folder / f"summary_{stem}_partial.csv")
        print(f"{len(partial):,} summary values add up only the tracts or block groups that had values. See summary_{stem}_partial.csv")
    return path


def cmd_qaqc(args, settings):
    session = services.make_session()
    results, sources = [], []
    variables = pd.read_csv(VARIABLES_PATH, dtype=str)
    if args.config:
        groupings = grouping.load_groupings(GROUPINGS_PATH)
        meta = pd.DataFrame()
        if not args.no_census_metadata:
            decennial_years = {"dec/dhc": 2020, "dec/sf1": 2010, "dec/sf3": 2000}
            codes = groupings[["variable_code", "dataset"]].copy()
            codes["year_sample"] = codes["dataset"].map(decennial_years).fillna(args.metadata_year).astype(int)
            meta = _metadata_for(codes, settings, session)
        results += qaqc.check_groupings(groupings, variables, meta)
        sources.append("config/groupings.csv")
    if args.input:
        raw = read_table(args.input)
        try:
            tahoe = geography.get_tahoe_geometry(settings, session)
        except Exception as exc:  # the geography checks are skipped when the service cannot be reached
            print(f"  could not read the Tahoe Census Geography layer, skipping basin checks: {exc}")
            tahoe = None
        meta = pd.DataFrame() if args.no_census_metadata else _metadata_for(raw, settings, session)
        results += qaqc.check_raw(raw, settings, tahoe, variables, meta)
        if args.compare_service:
            results += qaqc.compare_with_service(raw, settings, session)
        sources += args.input
    if args.summary:
        results += qaqc.check_summary(read_table(args.summary), settings)
        sources += args.summary
    if args.service:
        dups = inventory.service_duplicates(settings, args.service_year, session)
        results.append(qaqc.CheckResult("service_duplicate_records", "fail",
                                        "No record in the published Census Data table repeats another record's key.", dups))
        inv = inventory.census_data_inventory(settings, session)
        names = inv.groupby("variable_code").agg(n_names=("variable_name", "nunique"), n_categories=("variable_category", "nunique"),
                                                 names=("variable_name", lambda s: " | ".join(sorted(set(map(str, s))))),
                                                 categories=("variable_category", lambda s: " | ".join(sorted(set(map(str, s)))))).reset_index()
        results.append(qaqc.CheckResult("service_inconsistent_labels", "warn",
                                        "Each published variable_code has one name and one category.",
                                        names[(names["n_names"] > 1) | (names["n_categories"] > 1)]))
        neg = inv[inv["min_value"] < 0]
        results.append(qaqc.CheckResult("service_negative_values", "fail",
                                        "No published value is negative (Census annotation codes stored as data).", neg))
        sources.append(settings["services"]["census_data"])
    if not results:
        sys.exit("Nothing to check. Use --input, --summary, --config, or --service.")
    folder = outputs_dir(settings, "qaqc", args.label or (_stem(args.input) if args.input else "config_and_service"))
    report = qaqc.write_report(results, folder, "Demographics QAQC report", "; ".join(map(str, sources)))
    print(qaqc.results_table(results).to_string(index=False))
    print(f"\nReport: {report}")
    failed = [r for r in results if r.severity == "fail" and not r.passed]
    return report, failed


def cmd_inventory(args, settings):
    session = services.make_session()
    folder = outputs_dir(settings, "inventory")
    inv = inventory.census_data_inventory(settings, session)
    write_table(inv, folder / "census_data_inventory.csv")
    write_table(inventory.years_by_variable(settings, session), folder / "census_data_years.csv")
    write_table(inventory.summary_inventory(settings, session), folder / "climate_dashboard_inventory.csv")
    print(f"{len(inv):,} variable rows. Files in {folder}")
    if args.registry_year:
        reg = inventory.registry_from_inventory(inv, args.registry_year)
        path = write_table(reg, folder / f"variables_from_service_{args.registry_year}.csv")
        print(f"{len(reg)} variables in config/variables.csv format written to {path}")


def cmd_run(args, settings):
    for result in cmd_download(args, settings):
        raw_path = str(result["data"])
        ns = argparse.Namespace(input=[raw_path], groupings=GROUPINGS_PATH, sets=None)
        grouped_path = cmd_group(ns, settings)
        combined = read_table([raw_path, str(grouped_path)])
        combined_path = write_table(combined, Path(raw_path).with_name(Path(raw_path).stem + "_with_groups.csv"), RAW_COLUMNS)
        summary_path = cmd_summarize(argparse.Namespace(input=[str(combined_path)], levels=None, no_medians=False), settings)
        cmd_qaqc(argparse.Namespace(input=[str(combined_path)], summary=[str(summary_path)], config=False, service=False,
                                    compare_service=args.compare_service, no_census_metadata=False, metadata_year=None,
                                    service_year=None, label=Path(raw_path).stem), settings)


def cmd_export_gdb(args, settings):
    from .gdb import to_file_gdb
    df = read_table(args.input)
    print(f"Wrote {len(df):,} rows to {to_file_gdb(df, args.gdb, args.table, overwrite=args.overwrite)}")


def cmd_corrections(args, settings):
    from . import corrections
    key = get_api_key(settings) if args.download else None
    written = corrections.build_corrections(settings, download=args.download, api_key=key, label=args.label)
    for name, path in written.items():
        print(f"  {name}: {path}")
    print("Nothing was applied. Read README.txt in the output folder before loading anything.")


def cmd_comparison(args, settings):
    from .comparison import download_comparison
    variables = census_api.expand_variable_list(pd.read_csv(VARIABLES_PATH, dtype=str), args.dataset, args.category)
    session, key = services.make_session(), get_api_key(settings)
    frames = []
    for year in _years(args):
        year_vars = variables[variables["years"].map(lambda spec: census_api.applies_to_year(spec, year))] if "years" in variables else variables
        frames.append(download_comparison(settings, year_vars, year, key, session, args.geographies))
    result = pd.concat(frames, ignore_index=True)
    path = write_table(result, outputs_dir(settings, "comparison") / f"comparison_{args.year}_{args.year_end or args.year}.csv", SUMMARY_COLUMNS)
    write_table(result, path.with_name(path.stem + "_margins_of_error.csv"), SUMMARY_COLUMNS + ["MarginOfError"])
    print(f"{len(result):,} rows written to {path}")


def cmd_jobs(args, settings):
    from .jobs import JOBS_COLUMNS, download_jobs, replace_published, summarize_jobs
    years = _years(args)
    session = services.make_session()
    jobs = download_jobs(settings, years, get_api_key(settings), session)
    folder = outputs_dir(settings, "jobs")
    label = f"{years[0]}_{years[-1]}"
    path = write_table(jobs, folder / f"census_jobs_{label}_append.csv", JOBS_COLUMNS)
    write_table(summarize_jobs(jobs, settings), folder / f"census_jobs_{label}_summary.csv")
    print(f"{len(jobs):,} rows written to {path}, with Basin and shore totals beside it")
    if args.replace_published:
        files = replace_published(jobs, settings, years, session)
        write_table(files["retire"], folder / f"census_jobs_{label}_retire.csv")
        write_table(files["comparison"], folder / f"census_jobs_{label}_comparison.csv")
        print(f"{len(files['retire']):,} published rows to retire. Review census_jobs_{label}_comparison.csv before loading.")


def cmd_lodes(args, settings):
    from .lodes import build_year
    for year in _years(args):
        result = build_year(settings, year)
        print(f"{year}: {result['origin_destination']}\n      {result['work_locations']}\n      report {result['report']}")
        if result["failed"]:
            print(f"      QA failures, do not load until fixed: {', '.join(result['failed'])}")


def cmd_curated(args, settings):
    from .curated import build_curated, to_feature_class
    if args.input:
        long = read_table(args.input)
    elif args.year is None:
        sys.exit("Give --input files or --year (and --year-end) to read published Census Data.")
    else:
        long = services.query_layer(settings["services"]["census_data"], session=services.make_session(),
                                    where=f"year_sample >= {args.year} AND year_sample <= {args.year_end or args.year}")
        long["state"] = long["state"].astype(str).str.zfill(2)
        long["county"] = long["county"].astype(str).str.zfill(3)
    wide, problems = build_curated(long, args.layer, settings)
    folder = outputs_dir(settings, "curated")
    path = write_table(wide, folder / f"{args.layer}.csv")
    print(f"{len(wide):,} rows written to {path}")
    if not problems.empty:
        write_table(problems, folder / f"{args.layer}_problems.csv")
        print(problems.to_string(index=False))
    if args.feature_class:
        print(f"Feature class: {to_feature_class(wide, settings, args.feature_class, args.layer)}")


def cmd_tessellation(args, settings):
    from .tessellation import run
    census = services.query_layer(settings["services"]["census_data"], session=services.make_session(),
                                  where=f"year_sample >= {args.year} AND year_sample <= {args.year_end or args.year}")
    census["value"] = pd.to_numeric(census["value"], errors="coerce")
    census["year_sample"] = pd.to_numeric(census["year_sample"]).astype(int)
    print(run(settings, census, _years(args)))


def cmd_import_1990(args, settings):
    from .census1990 import import_folder
    tahoe = geography.get_tahoe_geometry(settings, services.make_session())
    data = import_folder(args.folder, pd.read_csv(VARIABLES_PATH, dtype=str).fillna(""), tahoe)
    path = write_table(data, outputs_dir(settings, "downloads", 1990) / "census_data_1990.csv", RAW_COLUMNS)
    print(f"{len(data):,} rows written to {path}")


def cmd_enrollment(args, settings):
    from .enrollment import ENROLLMENT_COLUMNS, build_enrollment, compare_published, split_new_rows
    first, last = args.year, args.year_end or args.year
    built = build_enrollment(settings, first, last)
    folder = outputs_dir(settings, "enrollment")
    label = f"{first}_{last}"
    write_table(built, folder / f"school_enrollment_{label}_review.csv")
    published = services.query_layer(settings["services"]["school_enrollment"])
    write_table(compare_published(built, published), folder / f"school_enrollment_{label}_comparison.csv")
    new = split_new_rows(built, published)
    path = write_table(new, folder / f"school_enrollment_{label}_append.csv", ENROLLMENT_COLUMNS)
    print(f"{len(built):,} school years built; {len(new):,} not yet published written to {path}")


def cmd_inflate(args, settings):
    from .inflation import adjust
    df = read_table(args.input)
    out = adjust(df, settings, args.to_year, codes=args.codes)
    path = Path(args.input[0]).with_name(Path(args.input[0]).stem + f"_in_{args.to_year or settings['inflation']['base_year']}_dollars.csv")
    out.to_csv(path, index=False)
    print(f"Written to {path}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m trpa_demographics", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("find", help="search Census variables")
    f.add_argument("--table", help="Census table code, for example B25003")
    f.add_argument("--search", help="words that must appear in the label or concept")
    f.add_argument("--year", type=int, default=2023)
    f.add_argument("--dataset", default="acs/acs5")
    f.add_argument("--category", help="TRPA category for the draft rows")
    f.add_argument("--level", default="tract;block group", help="sample levels for the draft rows")
    f.add_argument("--add", action="store_true", help="append new rows to config/variables.csv")
    f.set_defaults(func=cmd_find)

    for name, func, helptext in (("download", cmd_download, "download variables"), ("run", cmd_run, "full pipeline")):
        d = sub.add_parser(name, help=helptext)
        d.add_argument("--year", type=int, required=True)
        d.add_argument("--year-end", type=int, help="last year when downloading a range")
        d.add_argument("--dataset", help="only this dataset, for example acs/acs5 or dec/dhc")
        d.add_argument("--category", nargs="*", help="only these variable categories")
        d.add_argument("--variables", default=str(VARIABLES_PATH), help="variable list CSV")
        d.add_argument("--include-inactive", action="store_true")
        d.add_argument("--label", help="text added to the output file name")
        if name == "run":
            d.add_argument("--compare-service", action="store_true", help="also compare with the published Census Data table")
        d.set_defaults(func=func)

    g = sub.add_parser("group", help="apply config/groupings.csv")
    g.add_argument("--input", nargs="+", required=True)
    g.add_argument("--groupings", default=str(GROUPINGS_PATH))
    g.add_argument("--sets", nargs="*", help="only these grouping sets")
    g.set_defaults(func=cmd_group)

    s = sub.add_parser("summarize", help="roll up to summary geographies")
    s.add_argument("--input", nargs="+", required=True)
    s.add_argument("--levels", nargs="*", help="Basin County North/South State Neighborhood")
    s.add_argument("--no-medians", action="store_true")
    s.set_defaults(func=cmd_summarize)

    q = sub.add_parser("qaqc", help="quality checks")
    q.add_argument("--input", nargs="*", help="raw or grouped table(s) in the Census Data layout")
    q.add_argument("--summary", nargs="*", help="summary table(s)")
    q.add_argument("--config", action="store_true", help="check config/groupings.csv")
    q.add_argument("--service", action="store_true", help="check the published Census Data table")
    q.add_argument("--service-year", type=int, help="limit --service duplicate check to one year")
    q.add_argument("--compare-service", action="store_true", help="compare --input with published records")
    q.add_argument("--no-census-metadata", action="store_true", help="skip checks that need Census table definitions")
    q.add_argument("--metadata-year", type=int, default=2023, help="year of Census definitions used by --config")
    q.add_argument("--label", help="name of the report folder")
    q.set_defaults(func=cmd_qaqc)

    i = sub.add_parser("inventory", help="list published variables")
    i.add_argument("--registry-year", type=int, help="also write a variables.csv style list for this year")
    i.set_defaults(func=cmd_inventory)

    e = sub.add_parser("export-gdb", help="copy a CSV to a file geodatabase table")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--gdb", required=True, help="path to a .gdb folder")
    e.add_argument("--table", required=True)
    e.add_argument("--overwrite", action="store_true")
    e.set_defaults(func=cmd_export_gdb)

    c = sub.add_parser("corrections", help="build append and retire files for published errors")
    c.add_argument("--download", action="store_true", help="also download replacement Census codes (needs an API key)")
    c.add_argument("--label", help="name of the output folder (default: today's date)")
    c.set_defaults(func=cmd_corrections)

    def years(parser, required=True):
        parser.add_argument("--year", type=int, required=required)
        parser.add_argument("--year-end", type=int, help="last year of a range")

    cp = sub.add_parser("comparison", help="download comparison geographies")
    years(cp)
    cp.add_argument("--dataset", default="acs/acs5")
    cp.add_argument("--category", nargs="*", help="only these variable categories")
    cp.add_argument("--geographies", nargs="*", help="only these comparison geography names")
    cp.set_defaults(func=cmd_comparison)

    j = sub.add_parser("jobs", help="jobs by ZIP code")
    years(j)
    j.add_argument("--replace-published", action="store_true",
                   help="also write retire and comparison files for the published rows in these years (reads only)")
    j.set_defaults(func=cmd_jobs)

    lo = sub.add_parser("lodes", help="LODES commute and workplace files")
    years(lo)
    lo.set_defaults(func=cmd_lodes)

    cu = sub.add_parser("curated", help="wide map layer table")
    cu.add_argument("--layer", default="tahoe_census_curated", help="layer name in config/curated_layers.csv")
    cu.add_argument("--input", nargs="*", help="long table(s); without this, published Census Data is read")
    years(cu, required=False)
    cu.add_argument("--feature-class", help="also write a file geodatabase feature class (ArcGIS Pro)")
    cu.set_defaults(func=cmd_curated, year=None)

    t = sub.add_parser("tessellation", help="hexagon grid estimates (ArcGIS Pro)")
    years(t)
    t.set_defaults(func=cmd_tessellation)

    n = sub.add_parser("import-1990", help="read 1990 STF3 DBF files")
    n.add_argument("--folder", required=True, help="folder with stf3*.dbf files")
    n.set_defaults(func=cmd_import_1990)

    en = sub.add_parser("enrollment", help="school enrollment for each basin school, California and Nevada")
    years(en)
    en.set_defaults(func=cmd_enrollment)

    inf = sub.add_parser("inflate", help="convert dollar values")
    inf.add_argument("--input", nargs="+", required=True)
    inf.add_argument("--codes", nargs="*", help="only these variable codes")
    inf.add_argument("--to-year", type=int, help="target year (default: base year in settings)")
    inf.set_defaults(func=cmd_inflate)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args, load_settings())


if __name__ == "__main__":
    main()
