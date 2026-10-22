import json

import numpy as np
import pandas as pd
import pytest

from trpa_demographics import census_api, grouping, qaqc, summarize
from trpa_demographics.config import GROUPINGS_PATH, MEDIANS_PATH, VARIABLES_PATH, census_geom_year
from trpa_demographics.geography import make_trpaid, strip_geo_id


# --- geography ---------------------------------------------------------------

def test_trpaid_and_geom_year(settings):
    assert strip_geo_id(pd.Series(["1400000US06017030201"]))[0] == "06017030201"
    assert make_trpaid(pd.Series(["06017030201"]), 2020)[0] == "060170302012020"
    assert census_geom_year(2024, settings) == 2020
    assert census_geom_year(2019, settings) == 2010
    assert census_geom_year(2000, settings) == 2000


# --- census api helpers --------------------------------------------------------

def test_request_url_block_group_includes_tract():
    url = census_api.build_request_url("https://api.census.gov/data", 2023, "acs/acs5",
                                       ["GEO_ID", "B01001_001E", "B01001_001M"], "block group", "06", "017", None)
    assert "for=block%20group:*" in url and "in=state:06%20county:017%20tract:*" in url and "key=" not in url


def test_wide_to_long_filters_basin_and_cleans_sentinels(tahoe):
    wide = pd.DataFrame({
        "GEO_ID": ["1400000US06017000100", "1400000US06017999999"],
        "B19013_001E": ["-666666666", "50000"], "B19013_001M": ["-555555555", "100"],
        "state": ["06", "06"], "county": ["017", "017"], "tract": ["000100", "999999"],
    })
    batch = pd.DataFrame({"variable_code": ["B19013_001E"], "variable_name": ["Median"], "variable_category": ["Income"]})
    long, notes = census_api.wide_to_long(wide, batch, 2023, "acs/acs5", "tract", 2020, tahoe)
    assert len(long) == 1  # the tract outside the basin is dropped
    assert np.isnan(long["value"].iloc[0]) and long["MarginOfError"].iloc[0] == 0
    assert notes["census_annotation"].iloc[0] == -666666666


def test_expand_variable_list_splits_levels():
    v = pd.DataFrame({"variable_code": ["A_001E", "B_001E"], "variable_name": ["a", "b"], "variable_category": ["x", "x"],
                      "dataset": ["acs/acs5", "acs/acs5"], "sample_level": ["tract;block group", "tract"], "active": ["Y", "N"]})
    out = census_api.expand_variable_list(v)
    assert sorted(out["sample_level"]) == ["block group", "tract"]


def test_download_year_with_fake_api(settings, tahoe, tmp_path, monkeypatch):
    settings = {**settings, "outputs_folder": str(tmp_path), "census_api": {**settings["census_api"], "pause_between_requests_seconds": 0}}
    monkeypatch.setattr("trpa_demographics.config.REPO_ROOT", tmp_path)

    class FakeResponse:
        def __init__(self, payload, status=200):
            self.payload, self.status_code, self.text = payload, status, json.dumps(payload)

        def json(self):
            return self.payload

    class FakeSession:
        calls = 0

        def get(self, url, timeout=None):
            FakeSession.calls += 1
            state = url.split("state:")[1][:2]
            county = url.split("county:")[1][:3]
            if "BAD_001E" in url:
                return FakeResponse("error: unknown variable 'BAD_001E'", 400)
            header = ["GEO_ID", "B01001_001E", "B01001_001M", "state", "county", "tract"]
            return FakeResponse([header, [f"1400000US{state}{county}000100", "100", "5", state, county, "000100"]])

    variables = census_api.expand_variable_list(pd.DataFrame({
        "variable_code": ["B01001_001E", "BAD_001E"], "variable_name": ["Total", "Bad"], "variable_category": ["Age", "Age"],
        "dataset": ["acs/acs5", "acs/acs5"], "sample_level": ["tract", "tract"], "active": ["Y", "Y"]}))
    result = census_api.download_year(settings, variables, 2023, tahoe, "test-key", FakeSession())
    data = pd.read_csv(result["data"], dtype=str)
    assert len(data) == 4 and set(data["variable_code"]) == {"B01001_001E"}
    assert pd.read_csv(result["unknown_variables"])["variable_code"].tolist() == ["BAD_001E"]
    calls = FakeSession.calls
    census_api.download_year(settings, variables, 2023, tahoe, "test-key", FakeSession())
    assert FakeSession.calls == calls  # second run reuses the checkpoint


# --- grouping ------------------------------------------------------------------

def test_grouping_sums_and_combines_moe(settings, raw_factory):
    raw = raw_factory({"B01001_003E": 10, "B01001_027E": 20}, moes={"B01001_003E": 3.0, "B01001_027E": 4.0})
    cfg = pd.DataFrame({"grouping_set": ["TRPA Grouped"] * 2, "output_category": ["TRPA Grouped: {source_category}"] * 2,
                        "group_name": ["Under 5"] * 2, "group_order": [1, 1], "variable_code": ["B01001_003E", "B01001_027E"],
                        "dataset": ["acs/acs5"] * 2, "notes": ["", ""]})
    grouped, gaps = grouping.apply_groupings(raw, cfg, settings)
    assert len(grouped) == 8 and gaps.empty
    assert grouped["value"].eq(30).all() and np.allclose(grouped["MarginOfError"], 5.0)
    assert grouped["variable_code"].iloc[0] == "TRPA Grouped: B01001_003E, B01001_027E"
    assert grouped["variable_category"].iloc[0] == "TRPA Grouped: Age"


def test_grouping_keeps_partial_sums_and_flags_them(settings, raw_factory):
    raw = raw_factory({"A_001E": 10, "A_002E": [5, None, 5, 5, 5, 5, 5, 5]})
    cfg = pd.DataFrame({"grouping_set": ["S", "S"], "output_category": ["S", "S"], "group_name": ["G", "G"], "group_order": [1, 1],
                        "variable_code": ["A_001E", "A_002E"], "dataset": ["acs/acs5"] * 2, "notes": ["", ""]})
    grouped, partial = grouping.apply_groupings(raw, cfg, settings)
    assert grouped["value"].isna().sum() == 0 and sorted(grouped["value"].unique()) == [10, 15]
    assert len(partial) == 1 and partial["members_found"].iloc[0] == 1


# --- summaries -----------------------------------------------------------------

def test_summary_levels_add_up(settings, raw_factory):
    raw = raw_factory({"B01003_001E": 100}, moes={"B01003_001E": 10.0})
    summary, skipped, gaps = summarize.summarize(raw, settings)
    basin = summary[summary["Geography"] == "Basin"]
    assert basin["value"].iloc[0] == 800 and np.isclose(basin["MarginOfError"].iloc[0], np.sqrt(8 * 100))
    assert summary[summary["Geography"] == "North Lake"]["value"].iloc[0] == 400
    assert summary[summary["Geography"] == "Douglas County (Tahoe Basin)"]["value"].iloc[0] == 200
    assert set(summary["Geography"]) >= {"California", "Nevada", "South Lake"}
    assert all(r.passed for r in qaqc.check_summary(summary, settings))


def test_summary_skips_medians(settings, raw_factory):
    raw = raw_factory({"B19013_001E": 50000}, names={"B19013_001E": "Median Household Income"})
    variables = pd.read_csv(VARIABLES_PATH, dtype=str)
    summary, skipped, _ = summarize.summarize(raw, settings, variables)
    assert summary.empty and skipped["variable_code"].tolist() == ["B19013_001E"]


def test_interpolated_median():
    bins = pd.DataFrame({"bin_lower": [0, 10, 20], "bin_upper": [10, 20, np.nan], "count": [20, 60, 20]})
    value, moe, note = summarize.interpolate_median(bins)
    assert value == pytest.approx(15.0) and note == "" and np.isnan(moe)
    top = pd.DataFrame({"bin_lower": [0, 10], "bin_upper": [10, np.nan], "count": [1, 9]})
    value, moe, note = summarize.interpolate_median(top)
    assert value == 10 and "open-ended" in note


def test_median_margin_of_error_matches_hand_calculation(settings):
    # 2,068 households, design factor 1.5 (California Department of Finance worked example layout)
    bins = pd.DataFrame({"bin_lower": [0, 25000, 50000, 75000], "bin_upper": [25000, 50000, 75000, np.nan], "count": [500, 600, 568, 400]})
    value, moe, _ = summarize.interpolate_median(bins, 1.5, settings)
    se50 = 1.5 * np.sqrt((99 / (5 * 2068)) * 50 ** 2)
    total = 2068.0

    def at(p):
        cum = 0.0
        for lo, hi, n in [(0, 25000, 500), (25000, 50000, 600), (50000, 75000, 568)]:
            share = n / total * 100
            if cum + share >= p:
                return (p - cum) / share * (hi - lo) + lo
            cum += share

    expected = 1.645 * 0.5 * (at(50 + se50) - at(50 - se50))
    assert moe == pytest.approx(expected)
    assert value == pytest.approx(25000 + (1034 - 500) / 600 * 25000)


def test_compute_medians_from_config(settings, raw_factory):
    medians = summarize.load_medians(MEDIANS_PATH)
    income = medians[medians["median_set"] == "TRPA Median Household Income"]
    values = {code: 0 for code in income["variable_code"]}
    values["B19001_011E"] = 10  # every household in the $50,000 to $59,999 bin
    out = summarize.compute_medians(raw_factory(values, category="Household Income"), income, settings, ["Basin"])
    assert out["value"].iloc[0] == pytest.approx(55000)


# --- qaqc ----------------------------------------------------------------------

def test_qaqc_flags_duplicates_and_negatives(settings, tahoe, raw_factory):
    raw = raw_factory({"B01003_001E": [100, -666666666, 100, 100, 100, 100, 100, 100]})
    raw = pd.concat([raw, raw.iloc[[0]]])
    results = {r.check: r for r in qaqc.check_raw(raw, settings, tahoe)}
    assert results["duplicate_records"].found == 2
    assert results["negative_values"].found == 1
    assert results["trpaid_format"].passed and results["inside_basin"].passed


def test_group_double_count_check():
    meta = pd.DataFrame({"variable_code": ["T_003E", "T_004E", "T_008E"],
                         "label": ["Estimate!!Total:!!Owner:!!With related children", "Estimate!!Total:!!Owner:!!With related children!!With own children",
                                   "Estimate!!Total:!!Owner:!!With related children!!No own children"],
                         "table": ["T"] * 3})
    cfg = pd.DataFrame({"grouping_set": ["S"] * 3, "dataset": ["acs/acs5"] * 3, "group_name": ["With children"] * 3,
                        "variable_code": ["T_003E", "T_004E", "T_008E"]})
    variables = pd.DataFrame({"variable_code": ["T_003E", "T_004E", "T_008E"], "dataset": ["acs/acs5"] * 3, "aggregation": ["sum"] * 3})
    results = {r.check: r for r in qaqc.check_groupings(cfg, variables, meta)}
    assert results["group_double_counts"].found == 1


def test_table_totals_check(raw_factory):
    raw = raw_factory({"T_001E": 30, "T_002E": 10, "T_003E": 15})
    meta = pd.DataFrame({"variable_code": ["T_001E", "T_002E", "T_003E"],
                         "label": ["Estimate!!Total:", "Estimate!!Total:!!A", "Estimate!!Total:!!B"], "table": ["T"] * 3})
    assert qaqc.check_table_totals(raw, meta).found == 8


def test_report_writes(tmp_path, settings, tahoe, raw_factory):
    results = qaqc.check_raw(raw_factory({"B01003_001E": 100}), settings, tahoe)
    path = qaqc.write_report(results, tmp_path, "Test", "unit test")
    assert path.exists() and "duplicate_records" in path.read_text()


# --- configuration files -------------------------------------------------------

def test_config_files_are_consistent(settings):
    variables = pd.read_csv(VARIABLES_PATH, dtype=str).fillna("")
    assert not variables.duplicated(["variable_code", "dataset"]).any()
    assert set(variables["aggregation"]) <= {"sum", "none"}
    assert set(variables["active"]) <= {"Y", "N"}
    for spec in variables["years"]:
        census_api.applies_to_year(spec, 2020)  # every years value parses
    groupings = grouping.load_groupings(GROUPINGS_PATH)
    assert {"grouping_set", "output_category", "group_name", "variable_code", "dataset"} <= set(groupings.columns)
    assert not groupings.duplicated(["grouping_set", "dataset", "variable_code"]).any()
    medians = summarize.load_medians(MEDIANS_PATH)
    for (mset, _), m in medians.groupby(["median_set", "dataset"]):
        for year in (2012, 2023):
            bins = summarize._bins_for_year(m, year).drop_duplicates(["bin_lower", "bin_upper"]).sort_values("bin_lower")
            assert np.allclose(bins["bin_upper"].iloc[:-1].values, bins["bin_lower"].iloc[1:].values), (mset, year)
            assert pd.isna(bins["bin_upper"].iloc[-1]), (mset, year)
