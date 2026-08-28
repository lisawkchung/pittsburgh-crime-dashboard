from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import crime_dashboard as cd


def _mock_response(json_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.text = str(json_data)
    return mock


# ---------------------------------------------------------------------------
# map_risk_categories
# ---------------------------------------------------------------------------


def test_map_risk_categories_assigns_known_offenses():
    df = pd.DataFrame({"NIBRS_Coded_Offense": ["120 ROBBERY", "13B SIMPLE ASSAULT"]})
    result = cd.map_risk_categories(df)
    assert result["Risk_Categories_for_Students"].tolist() == [
        "High Threat Crimes",
        "Everyday Risks",
    ]


def test_map_risk_categories_unmapped_offense_becomes_other():
    df = pd.DataFrame({"NIBRS_Coded_Offense": ["999 SOME UNMAPPED OFFENSE"]})
    result = cd.map_risk_categories(df)
    assert result["Risk_Categories_for_Students"].tolist() == ["Other"]


def test_map_risk_categories_does_not_mutate_input():
    df = pd.DataFrame({"NIBRS_Coded_Offense": ["120 ROBBERY"]})
    cd.map_risk_categories(df)
    assert "Risk_Categories_for_Students" not in df.columns


# ---------------------------------------------------------------------------
# compute_hour_fixed
# ---------------------------------------------------------------------------


def test_compute_hour_fixed_shifts_early_morning_hours():
    hours = pd.Series([0, 1, 2, 17, 23])
    fixed = cd.compute_hour_fixed(hours)
    assert fixed.tolist() == [24, 25, 26, 17, 23]


# ---------------------------------------------------------------------------
# filter_campus_nighttime
# ---------------------------------------------------------------------------


def test_filter_campus_nighttime_keeps_only_campus_neighborhoods_and_nighttime_hours():
    df = pd.DataFrame({
        "Neighborhood": ["Oakland", "Oakland", "Squirrel Hill South", "Brookline"],
        "Hour": [18, 10, 1, 20],
    })
    result = cd.filter_campus_nighttime(df)
    assert set(result["Neighborhood"]) == {"Oakland", "Squirrel Hill South"}
    assert len(result) == 2


def test_filter_campus_nighttime_adds_ordered_hour_fixed_category():
    df = pd.DataFrame({"Neighborhood": ["Oakland"], "Hour": [1]})
    result = cd.filter_campus_nighttime(df)
    assert result["Hour_fixed"].iloc[0] == 25
    assert list(result["Hour_fixed"].cat.categories) == list(range(17, 27))


# ---------------------------------------------------------------------------
# validate_required_columns
# ---------------------------------------------------------------------------


def test_validate_required_columns_raises_on_missing():
    df = pd.DataFrame({"A": [1]})
    with pytest.raises(ValueError, match="B"):
        cd.validate_required_columns(df, ["A", "B"])


def test_validate_required_columns_passes_when_present():
    df = pd.DataFrame({"A": [1], "B": [2]})
    cd.validate_required_columns(df, ["A", "B"])  # should not raise


# ---------------------------------------------------------------------------
# aggregate_high_threat_by_neighborhood
# ---------------------------------------------------------------------------


def test_aggregate_high_threat_by_neighborhood_counts_only_high_threat():
    df = pd.DataFrame({
        "Neighborhood": ["Oakland", "Oakland", "Shadyside", "Oakland"],
        "Risk_Categories_for_Students": [
            "High Threat Crimes",
            "Everyday Risks",
            "High Threat Crimes",
            "High Threat Crimes",
        ],
    })
    result = cd.aggregate_high_threat_by_neighborhood(df, neighborhoods=["Oakland", "Shadyside"])
    counts = dict(zip(result["Neighborhood"], result["crime_count"]))
    assert counts == {"Oakland": 2, "Shadyside": 1}


# ---------------------------------------------------------------------------
# fetch_crime_data (requests mocked, no live API access)
# ---------------------------------------------------------------------------


def test_fetch_crime_data_paginates_and_stops_on_empty_page():
    page1 = {"success": True, "result": {"records": [{"_id": 1}, {"_id": 2}]}}
    page2 = {"success": True, "result": {"records": []}}
    with patch("crime_dashboard.requests.get", side_effect=[_mock_response(page1), _mock_response(page2)]) as mock_get:
        df = cd.fetch_crime_data(page_limit=2)
    assert len(df) == 2
    assert mock_get.call_count == 2


def test_fetch_crime_data_raises_on_http_error():
    with patch("crime_dashboard.requests.get", return_value=_mock_response({}, status_code=500)):
        with pytest.raises(RuntimeError, match="500"):
            cd.fetch_crime_data()


def test_fetch_crime_data_raises_on_api_level_failure():
    payload = {"success": False, "error": "bad resource_id"}
    with patch("crime_dashboard.requests.get", return_value=_mock_response(payload)):
        with pytest.raises(RuntimeError, match="failure"):
            cd.fetch_crime_data()


def test_fetch_crime_data_raises_on_empty_result():
    payload = {"success": True, "result": {"records": []}}
    with patch("crime_dashboard.requests.get", return_value=_mock_response(payload)):
        with pytest.raises(RuntimeError, match="no crime records"):
            cd.fetch_crime_data()


def test_fetch_crime_data_raises_if_pagination_never_terminates():
    page = {"success": True, "result": {"records": [{"_id": 1}]}}
    with patch("crime_dashboard.requests.get", return_value=_mock_response(page)):
        with pytest.raises(RuntimeError, match="max_pages"):
            cd.fetch_crime_data(max_pages=2)


def test_fetch_neighborhood_geojson_raises_on_http_error():
    with patch("crime_dashboard.requests.get", return_value=_mock_response({}, status_code=404)):
        with pytest.raises(RuntimeError, match="404"):
            cd.fetch_neighborhood_geojson()
