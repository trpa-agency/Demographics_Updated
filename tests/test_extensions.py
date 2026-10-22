"""Tests for corrections and the modules ported from the original repository."""
import gzip
import json
import struct

import pandas as pd
import pytest

from trpa_demographics import census1990, corrections, curated, enrollment, inflation, jobs, lodes, services, summarize, tessellation
from trpa_demographics.comparison import comparison_url, download_comparison


# --- corrections ---------------------------------------------------------------

def test_clean_dataset(settings):
    valid = settings["valid_datasets"]
    assert corrections.clean_dataset("Prescence of Children: acs/acs5", valid) == "acs/acs5"
    assert corrections.clean_dataset("TRPA 5-year Age Categoriesacs/acs5", valid) == "acs/acs5"
    assert corrections.clean_dataset("Education Grouped:acs/acs5/subject", valid) == "acs/acs5/subject"
    assert corrections.clean_dataset("TRPA 10-year Age Categories Grouped: TRPA Census Age Categories Grouped: dec/sf3", valid) == "dec/sf3"
    assert corrections.clean_dataset("2010 Decennial Census", valid) == "2010 Decennial Census"


def test_apply_rules_relabels_spells_and_cleans(settings):
    rules = corrections.load_rules()
    published = pd.DataFrame({
        "OBJECTID": [1, 2, 3, 4],
        "variable_code": ["B25075_001E", "B25004_007E", "B25012_002E", "X_001E"],
        "variable_name": ["Median home value", "Vacant Housing Units: Other Vacant", "Total Owner Occupied Housholds by Presence of Children", "Untouched"],
        "variable_category": ["Home Value (Median)", "Housing Units", "Tenure by Prescence of Children", "Other"],
        "dataset": ["acs/acs5", "acs/acs5", "Prescence of Children: acs/acs5", "acs/acs5"],
    })
    fixed = corrections.apply_rules(published, "census_data", rules, settings)
    assert fixed.loc[0, "variable_category"] == "Home Value" and "A2" in fixed.loc[0, "reasons"]
    assert fixed.loc[1, "variable_name"] == "Vacant Housing Units: For migrant workers"
    assert fixed.loc[2, "variable_name"].endswith("Households by Presence of Children")
    assert fixed.loc[2, "variable_category"] == "Tenure by Presence of Children" and fixed.loc[2, "dataset"] == "acs/acs5"
    assert fixed.loc[3, "reasons"] == ""


def test_where_clause_covers_rules(settings):
    where = corrections.where_for_layer("census_data", corrections.load_rules(), settings)
    assert "B25075_001E" in where and "Tenure By Age Of Householder" in where and "NOT IN" in where


def test_build_corrections_with_fake_services(settings, tmp_path, monkeypatch):
    settings = {**settings, "outputs_folder": str(tmp_path)}
    raw_b25012 = []
    for t in ("06017000100", "32005000100"):
        for code, value in (("B25012_003E", 10), ("B25012_009E", 20), ("B25012_011E", 5), ("B25012_017E", 7)):
            raw_b25012.append({"OBJECTID": len(raw_b25012) + 100, "GEO_ID": t, "value": value, "MarginOfError": 1, "state": t[:2], "county": t[2:5],
                               "tract": t[5:], "block_group": None, "variable_code": code, "variable_name": code, "variable_category": "Tenure by Prescence of Children",
                               "year_sample": 2023, "sample_level": "tract", "dataset": "acs/acs5", "census_geom_year": 2020, "TRPAID": t + "2020", "NEIGHBORHOOD": "N",
                               "Data_Scale": None, "delete_flag": 0})
    census_affected = pd.DataFrame([
        {**raw_b25012[0], "OBJECTID": 1, "variable_code": "B25075_001E", "variable_name": "Median home value", "variable_category": "Home Value (Median)"},
        {**raw_b25012[0], "OBJECTID": 2, "variable_code": "Prescence of Children: B25012_009E", "variable_name": "Owner Occupied Households With No Children ",
         "variable_category": "Tenure by Prescence of Children Grouped", "dataset": "Prescence of Children: acs/acs5"},
    ])
    summaries = pd.DataFrame([{"OBJECTID": 7, "Category": "Home Value (Median)", "Code": "B25075_001E", "Value": 14932.0, "Year": 2023, "Source": "acs/acs5", "Notes": None, "Geography": "Basin"}])
    curated_rows = pd.DataFrame([{"OBJECTID": 9, "trpaid": "060170001002020", "year_sample": 2023, "sample_level": "tract", "vacant_housing_units_other_vacant": 0}])
    other_vacant = pd.DataFrame([{"TRPAID": "060170001002020", "year_sample": 2023, "sample_level": "tract", "value": 42}])

    def fake_query(url, where="1=1", out_fields="*", session=None, order_by="OBJECTID"):
        if url.endswith("/28"):
            if "variable_code IN ('B25012" in where:
                return pd.DataFrame(raw_b25012)
            if "B25004_008E" in where:
                return other_vacant
            if out_fields.startswith("OBJECTID,TRPAID"):
                return pd.DataFrame(columns=["OBJECTID", "TRPAID", "variable_code", "year_sample", "sample_level", "dataset"])
            return census_affected
        if url.endswith("/18"):
            return summaries
        if url.endswith("/3"):
            return curated_rows
        return pd.DataFrame()

    monkeypatch.setattr(services, "query_layer", fake_query)
    written = corrections.build_corrections(settings, session=object(), label="test")
    census_append = pd.read_csv(written["census_data_append"], dtype=str)
    assert "Home Value" in set(census_append["variable_category"])
    regrouped = census_append[census_append["variable_category"] == "Tenure by Presence of Children Grouped"]
    assert len(regrouped) == 8 and set(regrouped["dataset"]) == {"acs/acs5"}
    retire = pd.read_csv(written["census_data_retire"])
    assert set(retire["OBJECTID"]) == {1, 2}
    s18 = pd.read_csv(written["demographic_summaries_append"])
    assert s18.loc[0, "Category"] == "Home Value" and s18.loc[0, "Value"] == 14932.0
    updates = pd.read_csv(written["tahoe_census_curated_field_updates"])
    assert updates.loc[0, "new_value"] == 42 and updates.loc[0, "status"] == "ready"
    assert (tmp_path / "corrections" / "test" / "README.txt").exists()


# --- layer 18 writer -----------------------------------------------------------

def test_to_layer18_uses_one_level_and_flags_partial(settings):
    summary = pd.DataFrame({"variable_code": ["A_001E"] * 2, "variable_name": ["Total"] * 2, "value": [10, 12], "Geography": ["Basin"] * 2,
                            "year_sample": [2023] * 2, "dataset": ["acs/acs5"] * 2, "sample_level": ["tract", "block group"], "Category": ["C"] * 2})
    partial = pd.DataFrame({"Geography": ["Basin"], "variable_code": ["A_001E"], "year_sample": [2023], "dataset": ["acs/acs5"],
                            "sample_level": ["tract"], "geographies": [31], "blank_values": [2]})
    out = summarize.to_layer18(summary, settings, partial)
    assert len(out) == 1 and out.loc[0, "Value"] == 10 and "partial: 2 of 31" in out.loc[0, "Notes"]


# --- comparison and jobs -------------------------------------------------------

class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.text = payload, status, json.dumps(payload)

    def json(self):
        return self.payload


def test_comparison_download(settings):
    class Session:
        urls = []

        def get(self, url, timeout=None):
            Session.urls.append(url)
            return FakeResponse([["B01003_001E", "B01003_001M", "state"], ["1000", "-555555555", "06"]])

    settings = {**settings, "census_api": {**settings["census_api"], "pause_between_requests_seconds": 0}}
    variables = pd.DataFrame({"variable_code": ["B01003_001E"], "variable_name": ["Total Population"], "variable_category": ["Population"], "dataset": ["acs/acs5"]})
    out = download_comparison(settings, variables, 2023, "k", Session(), geographies=["CA", "Reno-Sparks MSA"])
    assert set(out["Geography"]) == {"CA", "Reno-Sparks MSA"} and (out["MarginOfError"] == 0).all()
    assert "metropolitan%20statistical%20area/micropolitan%20statistical%20area:39900" in Session.urls[1]
    assert comparison_url("b", 2023, "acs/acs5", ["X"], {"for": "county:017", "in": "state:06"}, "k") == "b/2023/acs/acs5?get=X&for=county:017&in=state:06&key=k"


def _jobs_session(variables, payload_for):
    class Session:
        urls = []

        def get(self, url, timeout=None):
            Session.urls.append(url)
            if url.endswith("variables.json"):
                return FakeResponse({"variables": {v: {} for v in variables}})
            zip_code = url.rsplit(":", 1)[1].split("&")[0]
            return FakeResponse(payload_for(url, zip_code))
    return Session


def test_jobs_download_and_summary(settings):
    Session = _jobs_session(["EMP", "ESTAB", "PAYQTR1", "PAYANN", "EMP_N_F", "NAICS2017"],
                            lambda url, z: [["EMP", "EMP_N_F", "ESTAB", "PAYQTR1", "PAYANN", "NAICS2017", "zip code"],
                                            ["10", "G", "2", "5", "20", "00", z], ["4", "G", "1", "2", "8", "72", z]])
    settings = {**settings, "census_api": {**settings["census_api"], "pause_between_requests_seconds": 0}}
    out = jobs.download_jobs(settings, [2021], "k", Session())
    assert set(out.columns) == set(jobs.JOBS_COLUMNS)
    emp = out[out["variable_name"] == "Total Employees"]
    assert emp["value"].eq(10).all() and emp["value_flag"].eq("G").all()  # total row picked, noise flag kept
    assert "PAYQTR1_N_F" not in Session.urls[1]  # flags the year does not publish are not requested
    summary = jobs.summarize_jobs(out, settings)
    basin_emp = summary[(summary["Geography"] == "Basin") & (summary["variable_name"] == "Total Employees")]["value"].iloc[0]
    assert basin_emp == 10 * 16  # 16 basin ZIP codes used from 2018 in config/jobs_zip_codes.csv
    assert jobs.dataset_for_year(settings, 2015)["dataset"] == "zbp"


def test_jobs_older_years_withheld_values_and_replacement(settings):
    def payload(url, z):
        flag = "A" if z == "96142" else ""
        return [["EMP", "EMP_F", "ESTAB", "PAYQTR1", "PAYQTR1_F", "PAYANN", "PAYANN_F", "zipcode"],
                ["0" if flag else "50", flag, "3", "7", flag, "30", flag, z]]
    Session = _jobs_session(["EMP", "EMP_F", "ESTAB", "PAYQTR1", "PAYQTR1_F", "PAYANN", "PAYANN_F"], payload)
    settings = {**settings, "census_api": {**settings["census_api"], "pause_between_requests_seconds": 0}}
    out = jobs.download_jobs(settings, [2005], "k", Session())
    assert out["zip_code"].nunique() == 24  # the four South Lake Tahoe PO box ZIP codes are used through 2017
    withheld = out[(out["zip_code"] == "96142") & (out["variable_name"] == "Total Employees")].iloc[0]
    assert pd.isna(withheld["value"]) and withheld["value_flag"] == "D"
    summary = jobs.summarize_jobs(out, settings)
    basin = summary[(summary["Geography"] == "Basin") & (summary["variable_name"] == "Total Employees")].iloc[0]
    assert basin["value"] == 50 * 19 and basin["withheld_zip_codes"] == 1

    published = pd.DataFrame({"OBJECTID": [1, 2, 3], "value": [40.0, 9.0, 99.0], "value_flag": [None] * 3,
                              "zip_code": [89402.0, 96142.0, 96999.0], "year": [2005.0, 2005.0, 2005.0],
                              "variable_name": ["Total Employees"] * 3, "State": ["NV", "CA", "CA"],
                              "County": ["WASHOE", "EL DORADO", "X"], "Basin": ["Y"] * 3, "CBP_Name": ["a", "b", "c"]})
    files = jobs.replace_published(out, settings, [2005], published=published)
    assert files["retire"]["OBJECTID"].tolist() == [1, 2, 3]
    cmp_ = files["comparison"].set_index(["zip_code", "variable_name"])
    assert cmp_.loc[("89402", "Total Employees"), "difference"] == 10
    assert cmp_.loc[("96999", "Total Employees"), "status"] == "published only"
    assert list(files["append"].columns) == jobs.JOBS_COLUMNS


def test_pick_total_row_needs_one_match():
    payload = [["EMP", "NAICS2012", "EMPSZES"], ["5", "00", "001"], ["3", "00", "212"], ["2", "44", "001"]]
    row = jobs.pick_total_row(payload, ["EMPSZES", "NAICS2012"], {"NAICS": ["00"], "EMPSZES": ["001"]})
    assert row["EMP"] == "5"
    with pytest.raises(Exception):
        jobs.pick_total_row(payload, ["NAICS2012"], {"NAICS": ["00"]})


# --- LODES ---------------------------------------------------------------------

def test_lodes_labels_and_layout(settings):
    blocks = pd.DataFrame({"GEOID": ["060170302011000"], "TRPAID": ["0601703020110002020"]})
    tracts = pd.DataFrame({"GEOID": ["06017030201"], "TRPAID": ["060170302012020"]})
    od = pd.DataFrame({"w_geocode": ["060170302011000", "320310001001000", "060170302011000"],
                       "h_geocode": ["060170302011000", "060170302011000", "999999999999999"],
                       "S000": [5, 3, 2], "createdate": ["20240101"] * 3})
    flows = lodes.label_flows(od, blocks, tracts)
    assert list(flows["category"]) == ["Live in Tahoe, work in Tahoe", "Live in Tahoe, work elsewhere", "Live elsewhere, work in Tahoe"]
    assert flows.loc[1, "w_tract_TRPAID"] == "Outside Basin"
    for col in ("h_block_lat", "h_block_long", "w_block_lat", "w_block_long", "h_tract_lat", "h_tract_long", "w_tract_lat", "w_tract_long",
                "SA01", "SA02", "SA03", "SE01", "SE02", "SE03", "SI01", "SI02", "SI03"):
        flows[col] = 1.0
    out = lodes.to_od_layout(flows, 2023)
    assert list(out.columns) == lodes.OD_FIELDS and out.loc[0, "w_tract_id"] == "6017030201" and out.loc[0, "home_in_basin"] == "TRUE"
    published = pd.DataFrame({"Year": [2022] * 3, "category": list(lodes.CATEGORY.values()), "S000": [5, 3, 2]})
    results = {r.check: r for r in lodes.qa_checks(out, {"ca_main": od}, published, 2023, settings)}
    assert results["lodes_no_duplicate_pairs"].passed and results["lodes_year_not_published"].passed
    assert not results["lodes_total_jobs_range"].passed
    assert lodes.lodes_file_url(settings, "ca", "od", 2023, "aux").endswith("/ca/od/ca_od_aux_JT01_2023.csv.gz")


def test_lodes_reads_cached_gzip(tmp_path):
    path = tmp_path / "ca_od_main_JT01_2023.csv.gz"
    with gzip.open(path, "wt") as f:
        f.write("w_geocode,h_geocode,S000,createdate\n060170302011000,060170302011000,4,20240101\n")
    df = lodes.read_lodes_file("https://x/ca/od/ca_od_main_JT01_2023.csv.gz", tmp_path, session=None)
    assert df.loc[0, "w_geocode"] == "060170302011000"


# --- curated layers ------------------------------------------------------------

def test_build_curated(settings, raw_factory):
    raw = raw_factory({"B01003_001E": 100, "B25004_008E": 3})
    grouped = raw_factory({"TRPA Grouped: B01001_003E, B01001_004E": 7}, names={"TRPA Grouped: B01001_003E, B01001_004E": "Age_Under_18"})
    wide, problems = curated.build_curated(pd.concat([raw, grouped]), "tahoe_census_curated", settings)
    assert len(wide) == 8 and wide["total_population"].eq(100).all() and wide["age_under_18"].eq(7).all()
    assert wide["vacant_housing_units_other_vacant"].eq(3).all()
    assert set(wide["county_name"]) == {"El Dorado County", "Placer County", "Douglas County", "Washoe County"}
    assert "total_households" in set(problems["field"])


# --- tessellation math ---------------------------------------------------------

def test_tessellation_math():
    census = pd.DataFrame({
        "TRPAID": ["BG1"] * 5, "variable_code": ["B25002_003E", "B25002_002E", "B25004_006E", "B01003_001E", "X_001E"],
        "value": [20, 80, 10, 200, 40], "year_sample": [2023] * 5, "sample_level": ["block group"] * 5})
    occ = tessellation.occupancy_rates(census, 2023)
    assert occ.loc[0, "occupancy_rate"] == pytest.approx(0.8) and occ.loc[0, "population_per_unit"] == pytest.approx(2.0)
    config = pd.DataFrame({"name": ["Zero_Vehicle"], "type": ["Household"], "variable_code": ["X_001E"], "sample_level": ["block group"]})
    rates = tessellation.variable_rates(census, config, 2023)
    parcels = pd.DataFrame({"BLOCK_GROUP": ["BG1", "BG1"], "TRACT": ["T1", "T1"], "Residential_Units": [10, 30],
                            "EXISTING_LANDUSE": ["Single Family Residential", "Multi-Family Residential"], "GRID_ID": ["H1", "H2"]})
    est = tessellation.parcel_estimates(parcels, occ, rates)
    assert est["occupied_units"].tolist() == [8, 24] and est["Zero_Vehicle_count"].tolist() == [4, 12]
    hexes = tessellation.aggregate_to_polygons(est, "GRID_ID", rates).assign(year_sample=2023)
    factors = tessellation.adjustment_factors(census.assign(sample_level="block group"), hexes)
    assert factors.loc[0, "pop_adj_factor"] == pytest.approx(200 / 80)
    flagged = tessellation.add_quartile_flags(hexes)
    assert "occupied_units_top_quartile" in flagged and flagged["top_quartile_sum"].max() >= 1


# --- 1990 import ---------------------------------------------------------------

def _write_dbf(path, fields, rows):
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(length for _, length in fields)
    with open(path, "wb") as f:
        f.write(struct.pack("<BBBBIHH20x", 3, 90, 1, 1, len(rows), header_len, record_len))
        for name, length in fields:
            f.write(name.encode().ljust(11, b"\x00") + b"C" + b"\x00" * 4 + bytes([length]) + b"\x00" * 15)
        f.write(b"\x0D")
        for row in rows:
            f.write(b" " + b"".join(str(v).ljust(length).encode() for v, (_, length) in zip(row, fields)))
        f.write(b"\x1A")


def test_read_dbf_and_import(tmp_path):
    fields = [("SUMLEV", 3), ("STATEFP", 2), ("CNTY", 3), ("TRACTBNA", 6), ("P014A001", 9)]
    _write_dbf(tmp_path / "stf302ca.dbf", fields, [("140", "06", "017", "0003", "12"), ("050", "06", "017", "", "99")])
    assert census1990.read_dbf(tmp_path / "stf302ca.dbf").shape == (2, 5)
    ids = census1990.tract_trpaid(pd.Series(["06", "32"]), pd.Series(["017", "001"]), pd.Series(["0003", "950198"]))
    assert ids.tolist() == ["060170003001990", "320019501981990"]
    variables = pd.DataFrame({"variable_code": ["P014A001"], "variable_name": ["Under 1 year"], "variable_category": ["Age"], "dataset": ["dec/sf3"], "years": ["1990"]})
    tahoe = pd.DataFrame({"YEAR": [1990], "TRPAID": ["060170003001990"], "NEIGHBORHOOD": ["N"]})
    out = census1990.import_folder(tmp_path, variables, tahoe)
    assert len(out) == 1 and out.loc[0, "value"] == 12 and out.loc[0, "tract"] == "000300"


# --- enrollment and inflation --------------------------------------------------

def test_california_totals_both_layouts():
    old = pd.DataFrame({"ACADEMIC_YEAR": ["2021-22"] * 4, "CDS_CODE": ["31669446031306"] * 3 + ["09619030000001"],
                        "ENR_TYPE": ["P", "C", "C", "C"], "RACE_ETHNICITY": ["5", "5", "7", "7"], "GENDER": ["F"] * 4,
                        "ENR_TOTAL": ["100", "110", "50", "20"]})
    t = enrollment.california_totals(old, "C").set_index(["aggregate", "code"])
    assert t.loc[("school", "31669446031306"), "enrollment"] == 160  # combined rows only, summed over groups
    assert t.loc[("district", "0961903"), "enrollment"] == 20
    new = pd.DataFrame({"AcademicYear": ["2024-25"] * 4, "AggregateLevel": ["S", "S", "D", "D"],
                        "CountyCode": ["31", "31", "09", "09"], "DistrictCode": ["66944", "66944", "61903", "61903"],
                        "SchoolCode": ["6031306", "6031306", "0000000", "0000000"], "Charter": ["N", "N", "All", "Y"],
                        "ReportingCategory": ["TA", "GN_F", "TA", "TA"], "TOTAL_ENR": ["390", "190", "3600", "200"]})
    t = enrollment.california_totals(new).set_index(["aggregate", "code"])
    assert t.loc[("school", "31669446031306"), "enrollment"] == 390 and t.loc[("district", "0961903"), "enrollment"] == 3600
    assert enrollment.fall_year("201920") == 2019 and enrollment.year_label(2024) == "2024-2025"


def test_nevada_totals_layouts():
    total_sheet = pd.DataFrame([["2024-2025 School Year", None, None], ["School Code", "School Name", "Total"],
                                ["03502", "Whittell HS", 139], ["16309", "Incline MS", "*"]])
    grade_sheet = pd.DataFrame([["School Code", "School Name", "Grade", "Total"], ["03502", "Whittell HS", "9", 50]])
    t = enrollment.nevada_totals({"a": total_sheet, "b": grade_sheet}).set_index("code")
    assert t.loc["3502", "enrollment"] == 139 and t.loc["3502", "method"] == "school total"
    assert t.loc["16309", "suppressed"] == 1
    district_style = pd.DataFrame([["Douglas County School District", None, None], ["ID", "Group", "NTotal"],
                                   ["03502", "Whittell HS", 208], [None, "Gender: F", 100]])
    grades_only = pd.DataFrame([["School Code", "School Name", "Grade", "Total"], ["03202", "Zephyr", "1", 10], ["03202", "Zephyr", "2", 12]])
    assert enrollment.nevada_totals({"d": district_style}).set_index("code").loc["3502", "enrollment"] == 208
    g = enrollment.nevada_totals({"g": grades_only}).iloc[0]
    assert g["enrollment"] == 22 and g["method"] == "sum of grades"


def test_build_enrollment_and_new_rows(settings, tmp_path):
    settings = {**settings, "outputs_folder": str(tmp_path)}
    ca = pd.DataFrame({"fall_year": [2024, 2024], "aggregate": ["school", "district"], "code": ["31669446031306", "0961903"],
                       "enrollment": [390, 3600], "enrollment_type": ["census day"] * 2, "suppressed": [0, 0], "data_source": ["ca.txt"] * 2})
    nv = pd.DataFrame({"code": ["3502"], "enrollment": [139], "suppressed": [0], "method": ["school total"], "fall_year": [2024], "data_source": ["nv.xlsx"]})
    built = enrollment.build_enrollment(settings, 2024, 2024, session=object(), california=ca, nevada=nv)
    b = built.set_index("School_Name")
    assert b.loc["Kings Beach Elementary", "Enrollment"] == 390 and b.loc["Lake Tahoe Unified Combined", "Enrollment"] == 3600
    assert b.loc["George Whittell High School", "Enrollment"] == 139 and b.loc["Kingsbury Middle School", "Enrollment"] == 0
    assert "not found" in b.loc["Incline High School", "note"]
    published = pd.DataFrame({"School_Name": ["Kings Beach Elementary"], "Year": ["2024-2025"], "Enrollment": [380]})
    new = enrollment.split_new_rows(built, published)
    assert "Kings Beach Elementary" not in set(new["School_Name"]) and list(new.columns) == enrollment.ENROLLMENT_COLUMNS
    cmp_ = enrollment.compare_published(built, published).set_index("School_Name")
    assert cmp_.loc["Kings Beach Elementary", "difference"] == 10


def test_inflation_adjust(settings):
    df = pd.DataFrame({"variable_code": ["B19013_001E", "B01003_001E"], "value": [100.0, 100.0], "year_sample": [2010, 2010]})
    out = inflation.adjust(df, settings, 2021, codes=["B19013_001E"])
    assert out.loc[0, "value"] == pytest.approx(100 * 399.173 / 319.8) and out.loc[1, "value"] == 100
    out = inflation.adjust(df, settings, 2024, codes=["B19013_001E"])
    assert out.loc[0, "value"] == pytest.approx(100 * 462.511 / 319.8)
    with pytest.raises(ValueError):
        inflation.adjust(df, settings, 1980)
