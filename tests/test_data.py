from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import data as d


def _mock_response(json_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.text = str(json_data)
    return mock


# ---------------------------------------------------------------------------
# Taxonomy structure
# ---------------------------------------------------------------------------


def test_category_sets_are_pairwise_disjoint():
    sets = list(d.CATEGORY_CODES.values()) + [d.OUT_OF_SCOPE_CODES, d.EXCLUDED_ADMINISTRATIVE_CODES]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            assert not (sets[i] & sets[j]), f"sets {i} and {j} overlap: {sets[i] & sets[j]}"


def test_categorize_offense_code_known_and_unknown():
    assert d.categorize_offense_code("120") == "High Threat"
    assert d.categorize_offense_code("220") == "Property & Theft"
    assert d.categorize_offense_code("13B") == "Everyday Risks"
    assert d.categorize_offense_code("240") == "Auto & Parking"
    assert d.categorize_offense_code("9999") is None
    assert d.categorize_offense_code("35A") is None


def test_classify_offense_scope():
    assert d.classify_offense_scope("120") == "student_relevant"
    assert d.classify_offense_scope("35A") == "out_of_scope"
    assert d.classify_offense_scope("9999") == "administrative"
    assert d.classify_offense_scope(d.UNKNOWN_OFFENSE_CODE) == "administrative"


def test_classify_offense_scope_warns_on_unrecognized_code():
    with pytest.warns(UserWarning):
        result = d.classify_offense_scope("ZZZZZ")
    assert result == "administrative"


# ---------------------------------------------------------------------------
# normalize_offense_codes
# ---------------------------------------------------------------------------


def test_normalize_offense_codes_fixes_known_truncations():
    df = pd.DataFrame({"NIBRS_Offense_Code": ["DIS", "SIM", "THE", "Veh", "999", "120", None]})
    result = d.normalize_offense_codes(df)
    assert result["OffenseCode"].tolist() == ["90C", "13B", "23G", "9999", "9999", "120", "UNKNOWN"]


# ---------------------------------------------------------------------------
# filter_analysis_window
# ---------------------------------------------------------------------------


def test_filter_analysis_window_keeps_only_in_window_rows():
    df = pd.DataFrame({
        "ReportedDate": ["2024-06-30", "2024-07-01", "2025-06-15", "2026-06-30", "2026-07-01"],
    })
    result = d.filter_analysis_window(df, start="2024-07-01", end="2026-06-30")
    assert result["ReportedDate"].tolist() == ["2024-07-01", "2025-06-15", "2026-06-30"]


# ---------------------------------------------------------------------------
# drop_records_without_report_number
# ---------------------------------------------------------------------------


def test_drop_records_without_report_number():
    df = pd.DataFrame({"Report_Number": ["A1", None, "A2"], "x": [1, 2, 3]})
    with pytest.warns(UserWarning):
        result = d.drop_records_without_report_number(df)
    assert result["Report_Number"].tolist() == ["A1", "A2"]


# ---------------------------------------------------------------------------
# compute_incident_coverage_status
# ---------------------------------------------------------------------------


def test_coverage_status_student_relevant_takes_priority():
    # One incident with both a student-relevant offense and an out-of-scope offense
    # should be "student_relevant".
    df = pd.DataFrame({
        "Report_Number": ["R1", "R1"],
        "OffenseCode": ["120", "35A"],
    })
    status = d.compute_incident_coverage_status(df)
    assert status["R1"] == "student_relevant"


def test_coverage_status_out_of_scope_when_no_student_relevant_offense():
    df = pd.DataFrame({
        "Report_Number": ["R1", "R1"],
        "OffenseCode": ["35A", "9999"],
    })
    status = d.compute_incident_coverage_status(df)
    assert status["R1"] == "out_of_scope"


def test_coverage_status_administrative_when_only_administrative_offenses():
    df = pd.DataFrame({
        "Report_Number": ["R1"],
        "OffenseCode": ["9999"],
    })
    status = d.compute_incident_coverage_status(df)
    assert status["R1"] == "administrative"


def test_coverage_status_reconciles_to_all_incidents():
    df = pd.DataFrame({
        "Report_Number": ["R1", "R2", "R3"],
        "OffenseCode": ["120", "35A", "9999"],
    })
    status = d.compute_incident_coverage_status(df)
    assert set(status.index) == {"R1", "R2", "R3"}
    assert status["R1"] == "student_relevant"
    assert status["R2"] == "out_of_scope"
    assert status["R3"] == "administrative"


# ---------------------------------------------------------------------------
# build_incident_table
# ---------------------------------------------------------------------------


def _offense_row(report_number, dt, neighborhood, xcoord=None, ycoord=None, _id=1,
                  date=None, time="12:00", hour=12, zone="Zone 1"):
    return {
        "Report_Number": report_number,
        "ReportedDateTime": pd.Timestamp(dt),
        "ReportedDate": date or pd.Timestamp(dt).strftime("%Y-%m-%d"),
        "ReportedTime": time,
        "Hour": hour,
        "Zone": zone,
        "Neighborhood": neighborhood,
        "XCOORD": xcoord,
        "YCOORD": ycoord,
        "_id": _id,
    }


def test_build_incident_table_dedupes_to_one_row_per_report_number():
    df = pd.DataFrame([
        _offense_row("R1", "2025-01-01 10:00", "Oakland", -80.0, 40.0, _id=1),
        _offense_row("R1", "2025-01-01 10:00", "Oakland", -80.0, 40.0, _id=2),
    ])
    incidents = d.build_incident_table(df)
    assert len(incidents) == 1
    assert incidents.iloc[0]["Report_Number"] == "R1"
    assert incidents.iloc[0]["n_offenses"] == 2


def test_build_incident_table_uses_earliest_row_as_canonical():
    df = pd.DataFrame([
        _offense_row("R1", "2025-01-23 10:33", "East Liberty", -79.9, 40.45, _id=2),
        _offense_row("R1", "2025-01-04 22:33", "East Liberty", -79.9, 40.45, _id=1),
    ])
    incidents = d.build_incident_table(df)
    assert incidents.iloc[0]["ReportedDateTime"] == pd.Timestamp("2025-01-04 22:33")


def test_build_incident_table_ties_broken_by_lowest_id():
    df = pd.DataFrame([
        _offense_row("R1", "2025-01-01 10:00", "Oakland", -80.0, 40.0, _id=5),
        _offense_row("R1", "2025-01-01 10:00", "Shadyside", -79.9, 40.4, _id=2),
    ])
    incidents = d.build_incident_table(df)
    assert incidents.iloc[0]["Neighborhood"] == "Shadyside"


def test_build_incident_table_fills_missing_canonical_coords_from_same_neighborhood_row():
    df = pd.DataFrame([
        _offense_row("R1", "2025-01-01 10:00", "Oakland", None, None, _id=1),
        _offense_row("R1", "2025-01-02 10:00", "Oakland", -80.0, 40.0, _id=2),
    ])
    incidents = d.build_incident_table(df)
    assert incidents.iloc[0]["Neighborhood"] == "Oakland"
    assert incidents.iloc[0]["XCOORD"] == -80.0
    assert incidents.iloc[0]["YCOORD"] == 40.0


def test_build_incident_table_does_not_borrow_coords_from_different_neighborhood():
    df = pd.DataFrame([
        _offense_row("R1", "2025-01-01 10:00", "Oakland", None, None, _id=1),
        _offense_row("R1", "2025-01-02 10:00", "Downtown", -80.0, 40.0, _id=2),
    ])
    incidents = d.build_incident_table(df)
    assert incidents.iloc[0]["Neighborhood"] == "Oakland"
    assert pd.isna(incidents.iloc[0]["XCOORD"])
    assert pd.isna(incidents.iloc[0]["YCOORD"])


def test_build_incident_table_keeps_canonical_coords_over_later_rows():
    df = pd.DataFrame([
        _offense_row("R1", "2025-01-01 10:00", "Oakland", -80.5, 40.5, _id=1),
        _offense_row("R1", "2025-01-02 10:00", "Oakland", -80.0, 40.0, _id=2),
    ])
    incidents = d.build_incident_table(df)
    assert incidents.iloc[0]["XCOORD"] == -80.5
    assert incidents.iloc[0]["YCOORD"] == 40.5


# ---------------------------------------------------------------------------
# build_incident_category_bridge
# ---------------------------------------------------------------------------


def test_bridge_produces_one_row_per_category_present():
    df = pd.DataFrame({
        "Report_Number": ["R1", "R1"],
        "OffenseCode": ["13B", "120"],  # Everyday Risks + High Threat
    })
    bridge = d.build_incident_category_bridge(df)
    assert set(bridge["category"]) == {"Everyday Risks", "High Threat"}
    assert len(bridge) == 2


def test_bridge_excludes_out_of_scope_and_administrative_offenses():
    df = pd.DataFrame({
        "Report_Number": ["R1", "R2"],
        "OffenseCode": ["35A", "9999"],
    })
    bridge = d.build_incident_category_bridge(df)
    assert bridge.empty


def test_bridge_dedupes_repeated_offenses_in_same_category():
    df = pd.DataFrame({
        "Report_Number": ["R1", "R1", "R1"],
        "OffenseCode": ["13B", "13C", "13B"],  # all Everyday Risks
    })
    bridge = d.build_incident_category_bridge(df)
    assert len(bridge) == 1
    assert bridge.iloc[0]["category"] == "Everyday Risks"


def test_bridge_category_totals_can_exceed_deduped_total():
    df = pd.DataFrame({
        "Report_Number": ["R1", "R1", "R2"],
        "OffenseCode": ["13B", "120", "220"],  # R1: Everyday+HighThreat, R2: Property
    })
    bridge = d.build_incident_category_bridge(df)
    cat_sum = bridge.groupby("category")["Report_Number"].nunique().sum()
    deduped_total = bridge["Report_Number"].nunique()
    assert cat_sum > deduped_total


# ---------------------------------------------------------------------------
# preprocess_crime_data
# ---------------------------------------------------------------------------


def test_preprocess_crime_data_parses_datetime_and_coords():
    df = pd.DataFrame({
        "ReportedDate": ["2025-01-01"], "ReportedTime": ["18:30"],
        "XCOORD": ["-80.0"], "YCOORD": ["40.0"], "Neighborhood": ["Oakland"],
    })
    result = d.preprocess_crime_data(df)
    assert result["ReportedDateTime"].iloc[0] == pd.Timestamp("2025-01-01 18:30")
    assert result["XCOORD"].iloc[0] == -80.0
    assert result["YCOORD"].iloc[0] == 40.0


def test_preprocess_crime_data_canonicalizes_neighborhood():
    # Regression test: the crime dataset itself carries both an en dash and
    # a hyphen spelling for some neighborhoods. Without canonicalizing here,
    # those rows fail to join against the canonicalized area/population
    # tables in analysis.compute_rates and are silently dropped from every
    # rate for that neighborhood.
    df = pd.DataFrame({
        "ReportedDate": ["2025-01-01", "2025-01-02"],
        "ReportedTime": ["18:30", "19:00"],
        "XCOORD": ["-80.0", "-80.0"], "YCOORD": ["40.0", "40.0"],
        "Neighborhood": ["Lincoln–Lemington–Belmar", "Lincoln-Lemington-Belmar"],
    })
    result = d.preprocess_crime_data(df)
    assert set(result["Neighborhood"]) == {"Lincoln-Lemington-Belmar"}


# ---------------------------------------------------------------------------
# compute_hour_fixed / build_campus_nighttime_points
# ---------------------------------------------------------------------------


def test_compute_hour_fixed_shifts_early_morning_hours():
    hours = pd.Series([0, 1, 2, 17, 23])
    fixed = d.compute_hour_fixed(hours)
    assert fixed.tolist() == [24, 25, 26, 17, 23]


def test_build_campus_nighttime_points_filters_neighborhood_and_hour():
    incidents = pd.DataFrame({
        "Report_Number": ["R1", "R2", "R3", "R4"],
        "Neighborhood": ["Oakland", "Oakland", "Squirrel Hill South", "Brookline"],
        "Hour": [18, 10, 1, 20],
    })
    bridge = pd.DataFrame({
        "Report_Number": ["R1", "R2", "R3", "R4"],
        "category": ["High Threat", "High Threat", "High Threat", "High Threat"],
    })
    result = d.build_campus_nighttime_points(incidents, bridge, neighborhoods=["Oakland", "Squirrel Hill South"])
    # R2 dropped (daytime hour), R4 dropped (not a campus neighborhood).
    assert set(result["Report_Number"]) == {"R1", "R3"}
    assert len(result) == 2


def test_build_campus_nighttime_points_excludes_incidents_not_in_bridge():
    # An incident with no student-relevant category never appears in the
    # bridge, so it must not appear in the campus points either.
    incidents = pd.DataFrame({"Report_Number": ["R1"], "Neighborhood": ["Oakland"], "Hour": [18]})
    bridge = pd.DataFrame({"Report_Number": [], "category": []})
    result = d.build_campus_nighttime_points(incidents, bridge, neighborhoods=["Oakland"])
    assert result.empty


def test_build_campus_nighttime_points_adds_ordered_hour_fixed_category():
    incidents = pd.DataFrame({"Report_Number": ["R1"], "Neighborhood": ["Oakland"], "Hour": [1]})
    bridge = pd.DataFrame({"Report_Number": ["R1"], "category": ["High Threat"]})
    result = d.build_campus_nighttime_points(incidents, bridge, neighborhoods=["Oakland"])
    assert result["Hour_fixed"].iloc[0] == 25
    assert list(result["Hour_fixed"].cat.categories) == list(range(17, 27))


def test_campus_nighttime_points_follow_the_overlapping_category_counting_model():
    """End-to-end from raw offense rows: same-category duplicate offenses on
    one incident collapse to a single point; an incident spanning two
    categories produces one point per category. This is the same counting
    model used by build_incident_category_bridge everywhere else."""
    def offense(report_number, _id, code):
        return _offense_row(report_number, "2025-01-01 18:00", "Oakland", -80.0, 40.0, _id=_id,
                             hour=18) | {"OffenseCode": code}

    raw = pd.DataFrame([
        offense("R1", 1, "13B"),  # Everyday Risks
        offense("R1", 2, "13C"),  # Everyday Risks (same category, same incident)
        offense("R2", 3, "120"),  # High Threat
        offense("R2", 4, "240"),  # Auto & Parking (different category, same incident)
    ])
    incidents = d.build_incident_table(raw)
    bridge = d.build_incident_category_bridge(raw)
    points = d.build_campus_nighttime_points(incidents, bridge, neighborhoods=["Oakland"])

    r1_points = points[points["Report_Number"] == "R1"]
    assert len(r1_points) == 1
    assert r1_points.iloc[0]["category"] == "Everyday Risks"

    r2_points = points[points["Report_Number"] == "R2"]
    assert len(r2_points) == 2
    assert set(r2_points["category"]) == {"High Threat", "Auto & Parking"}


# ---------------------------------------------------------------------------
# canonicalize_neighborhood_names
# ---------------------------------------------------------------------------


def test_canonicalize_neighborhood_names_applies_known_aliases():
    s = pd.Series(["Mt. Oliver", "Central Business District (Downtown)", "Oakland"])
    result = d.canonicalize_neighborhood_names(s)
    assert result.tolist() == ["Mount Oliver", "Central Business District", "Oakland"]


def test_canonicalize_neighborhood_names_is_idempotent():
    s = pd.Series(["Mt. Oliver"])
    once = d.canonicalize_neighborhood_names(s)
    twice = d.canonicalize_neighborhood_names(once)
    assert once.tolist() == twice.tolist()


# ---------------------------------------------------------------------------
# extract_neighborhood_areas
# ---------------------------------------------------------------------------


def test_extract_neighborhood_areas_reads_hood_and_sqmiles():
    geojson = {"features": [
        {"properties": {"hood": "Oakland", "sqmiles": 1.23}},
        {"properties": {"hood": "Mt. Oliver", "sqmiles": 0.5}},
    ]}
    areas = d.extract_neighborhood_areas(geojson)
    assert set(areas["Neighborhood"]) == {"Oakland", "Mount Oliver"}  # aliased


def test_extract_neighborhood_areas_canonicalizes_geojson_in_place():
    # Regression test: figures.build_choropleth_figure matches rate-table
    # neighborhood names against this same geojson dict via
    # featureidkey="properties.hood". If the dict itself isn't canonicalized,
    # an aliased neighborhood's polygon silently fails to render even though
    # the returned areas DataFrame looks correct.
    geojson = {"features": [{"properties": {"hood": "Mt. Oliver", "sqmiles": 0.5}}]}
    d.extract_neighborhood_areas(geojson)
    assert geojson["features"][0]["properties"]["hood"] == "Mount Oliver"


# ---------------------------------------------------------------------------
# validate_required_columns
# ---------------------------------------------------------------------------


def test_validate_required_columns_raises_on_missing():
    df = pd.DataFrame({"A": [1]})
    with pytest.raises(ValueError, match="B"):
        d.validate_required_columns(df, ["A", "B"])


# ---------------------------------------------------------------------------
# fetch_crime_data / fetch_neighborhood_population (requests mocked)
# ---------------------------------------------------------------------------


def test_fetch_crime_data_paginates_and_stops_on_empty_page():
    page1 = {"success": True, "result": {"records": [{"_id": 1}, {"_id": 2}]}}
    page2 = {"success": True, "result": {"records": []}}
    with patch("data.requests.get", side_effect=[_mock_response(page1), _mock_response(page2)]) as mock_get:
        df = d.fetch_crime_data(page_limit=2)
    assert len(df) == 2
    assert mock_get.call_count == 2


def test_fetch_crime_data_raises_on_http_error():
    with patch("data.requests.get", return_value=_mock_response({}, status_code=500)):
        with pytest.raises(RuntimeError, match="500"):
            d.fetch_crime_data()


def test_fetch_crime_data_raises_on_empty_result():
    payload = {"success": True, "result": {"records": []}}
    with patch("data.requests.get", return_value=_mock_response(payload)):
        with pytest.raises(RuntimeError, match="no crime records"):
            d.fetch_crime_data()


def test_fetch_crime_data_raises_if_pagination_never_terminates():
    page = {"success": True, "result": {"records": [{"_id": 1}]}}
    with patch("data.requests.get", return_value=_mock_response(page)):
        with pytest.raises(RuntimeError, match="max_pages"):
            d.fetch_crime_data(max_pages=2)


def test_fetch_neighborhood_population_renames_and_aliases():
    records = [
        {"Neighborhood": "Oakland", "2020_Total_Population": "100"},
        {"Neighborhood": "Mt. Oliver", "2020_Total_Population": "200"},
    ]
    payload = {"success": True, "result": {"records": records}}
    empty = {"success": True, "result": {"records": []}}
    with patch("data.requests.get", side_effect=[_mock_response(payload), _mock_response(empty)]):
        pop = d.fetch_neighborhood_population()
    assert set(pop["Neighborhood"]) == {"Oakland", "Mount Oliver"}
    assert pop.loc[pop.Neighborhood == "Oakland", "population_2020"].iloc[0] == 100


def test_fetch_neighborhood_geojson_raises_on_http_error():
    with patch("data.requests.get", return_value=_mock_response({}, status_code=404)):
        with pytest.raises(RuntimeError, match="404"):
            d.fetch_neighborhood_geojson()
