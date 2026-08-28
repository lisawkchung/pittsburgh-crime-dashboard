import numpy as np
import pandas as pd
import pytest

import analysis as a
from data import ALL_STUDENT_RELEVANT_LABEL


# ---------------------------------------------------------------------------
# compute_coverage_audit
# ---------------------------------------------------------------------------


def test_compute_coverage_audit_reconciles_to_window_total():
    status = pd.Series(
        ["student_relevant", "student_relevant", "out_of_scope", "administrative"],
        index=["R1", "R2", "R3", "R4"],
    )
    audit = a.compute_coverage_audit(status, window_incident_total=4)
    assert audit["incidents"].sum() == 4
    assert audit.set_index("status").loc["student_relevant", "incidents"] == 2
    assert pytest.approx(audit["pct_of_window_incidents"].sum()) == 100.0


def test_compute_coverage_audit_includes_zero_count_status():
    status = pd.Series(["student_relevant"], index=["R1"])
    audit = a.compute_coverage_audit(status, window_incident_total=1)
    assert set(audit["status"]) == {"student_relevant", "out_of_scope", "administrative"}
    assert audit.set_index("status").loc["out_of_scope", "incidents"] == 0


# ---------------------------------------------------------------------------
# compute_category_membership_summary
# ---------------------------------------------------------------------------


def test_category_membership_summary_percentages_need_not_sum_to_100():
    bridge = pd.DataFrame({
        "Report_Number": ["R1", "R1", "R2"],
        "category": ["High Threat", "Everyday Risks", "Auto & Parking"],
    })
    status = pd.Series(["student_relevant", "student_relevant"], index=["R1", "R2"])
    summary = a.compute_category_membership_summary(bridge, status)
    per_category = summary[summary["category"] != ALL_STUDENT_RELEVANT_LABEL]
    assert per_category["pct_of_student_relevant"].sum() > 100.0  # R1 counted twice


def test_category_membership_summary_all_relevant_row_is_deduped():
    bridge = pd.DataFrame({
        "Report_Number": ["R1", "R1", "R2"],
        "category": ["High Threat", "Everyday Risks", "Auto & Parking"],
    })
    status = pd.Series(["student_relevant", "student_relevant"], index=["R1", "R2"])
    summary = a.compute_category_membership_summary(bridge, status)
    all_row = summary[summary["category"] == ALL_STUDENT_RELEVANT_LABEL].iloc[0]
    assert all_row["incidents"] == 2  # R1 + R2, not 3


# ---------------------------------------------------------------------------
# compute_neighborhood_incident_counts / compute_rates
# ---------------------------------------------------------------------------


def test_compute_neighborhood_incident_counts_single_category():
    bridge = pd.DataFrame({
        "Report_Number": ["R1", "R2", "R3"],
        "category": ["High Threat", "High Threat", "Auto & Parking"],
    })
    incidents = pd.DataFrame({
        "Report_Number": ["R1", "R2", "R3"],
        "Neighborhood": ["Oakland", "Oakland", "Oakland"],
    })
    counts = a.compute_neighborhood_incident_counts(bridge, incidents, "High Threat")
    assert counts["Oakland"] == 2


def test_compute_neighborhood_incident_counts_all_relevant_dedupes_overlap():
    bridge = pd.DataFrame({
        "Report_Number": ["R1", "R1"],
        "category": ["High Threat", "Auto & Parking"],
    })
    incidents = pd.DataFrame({"Report_Number": ["R1"], "Neighborhood": ["Oakland"]})
    counts = a.compute_neighborhood_incident_counts(bridge, incidents, ALL_STUDENT_RELEVANT_LABEL)
    assert counts["Oakland"] == 1  # not 2


def test_compute_rates_hand_computed_values():
    counts = pd.Series({"Oakland": 100}).rename("incidents").rename_axis("Neighborhood").reset_index()
    areas = pd.DataFrame({"Neighborhood": ["Oakland"], "sqmiles": [0.5]})
    population = pd.DataFrame({"Neighborhood": ["Oakland"], "population_2020": [2000]})
    table = a.compute_rates(counts, areas, population, years=2.0)
    row = table.iloc[0]
    assert row["density_sqmi"] == pytest.approx(100.0)  # 100 / 0.5 / 2
    assert row["density_pop"] == pytest.approx(25.0)     # 100 / 2000 * 1000 / 2


def test_compute_rates_neighborhood_with_no_incidents_gets_zero_not_dropped():
    counts = pd.DataFrame({"Neighborhood": [], "incidents": []})
    areas = pd.DataFrame({"Neighborhood": ["Oakland"], "sqmiles": [1.0]})
    population = pd.DataFrame({"Neighborhood": ["Oakland"], "population_2020": [1000]})
    table = a.compute_rates(counts, areas, population, years=2.0)
    assert table.iloc[0]["incidents"] == 0
    assert table.iloc[0]["density_sqmi"] == 0.0


def test_compute_rates_missing_population_yields_nan_not_inf():
    counts = pd.DataFrame({"Neighborhood": ["Oakland"], "incidents": [10]})
    areas = pd.DataFrame({"Neighborhood": ["Oakland"], "sqmiles": [1.0]})
    population = pd.DataFrame({"Neighborhood": [], "population_2020": []})
    table = a.compute_rates(counts, areas, population, years=2.0)
    assert pd.isna(table.iloc[0]["density_pop"])
    assert not np.isinf(table.iloc[0]["density_pop"])


# ---------------------------------------------------------------------------
# poisson_ci
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 5, 50, 500])
def test_poisson_ci_brackets_the_count(count):
    lower, upper = a.poisson_ci(count)
    assert lower < count < upper


def test_poisson_ci_zero_uses_standard_bound():
    lower, upper = a.poisson_ci(0)
    assert lower == 0.0
    assert upper == pytest.approx(3.689, abs=0.01)


def test_poisson_ci_relative_width_shrinks_as_count_grows():
    def relative_width(count):
        lower, upper = a.poisson_ci(count)
        return (upper - lower) / count

    assert relative_width(500) < relative_width(50) < relative_width(5)


def test_poisson_ci_matches_published_byar_reference_values():
    # Reference values commonly cited for Byar's approximation at count=10.
    lower, upper = a.poisson_ci(10)
    assert lower == pytest.approx(4.795, abs=0.05)
    assert upper == pytest.approx(18.39, abs=0.05)


# ---------------------------------------------------------------------------
# add_rate_intervals
# ---------------------------------------------------------------------------


def test_add_rate_intervals_brackets_the_rate():
    table = pd.DataFrame({"incidents": [10], "sqmiles": [2.0]})
    table = a.add_rate_intervals(table, "density_sqmi", denom_col="sqmiles", years=1.0)
    rate = table.iloc[0]["incidents"] / table.iloc[0]["sqmiles"]
    assert table.iloc[0]["density_sqmi_lower"] < rate < table.iloc[0]["density_sqmi_upper"]


def test_add_rate_intervals_raw_count_has_no_denominator():
    table = pd.DataFrame({"incidents": [10]})
    table = a.add_rate_intervals(table, "raw_count", count_col="incidents", denom_col=None)
    assert table.iloc[0]["raw_count_lower"] < 10 < table.iloc[0]["raw_count_upper"]


def test_add_rate_intervals_brackets_the_rate_with_scale():
    # Regression test: density_pop's point estimate is incidents/population*1000/years
    # (see compute_rates), so its interval must apply the same *1000 scale or
    # the bounds end up ~1000x smaller than the rate they're supposed to bracket.
    table = pd.DataFrame({"incidents": [100], "population_2020": [5000.0]})
    table = a.add_rate_intervals(table, "density_pop", denom_col="population_2020", scale=1000, years=2.0)
    point_estimate = 100 / 5000 * 1000 / 2  # == 10.0, matches compute_rates' density_pop formula
    assert table.iloc[0]["density_pop_lower"] < point_estimate < table.iloc[0]["density_pop_upper"]


# ---------------------------------------------------------------------------
# compute_city_overall_rate / compute_city_baseline_ratios
# ---------------------------------------------------------------------------


def test_city_overall_rate_pools_all_neighborhoods():
    table = pd.DataFrame({"incidents": [10, 20], "sqmiles": [1.0, 1.0]})
    rate = a.compute_city_overall_rate(table, years=1.0)
    assert rate == pytest.approx(15.0)  # (10+20)/(1+1)


def test_city_overall_rate_applies_scale():
    # Regression test: a per-1,000-residents reference line must be computed
    # on the same *1000 scale as the points it's drawn against.
    table = pd.DataFrame({"incidents": [10, 20], "population_2020": [1000.0, 1000.0]})
    rate = a.compute_city_overall_rate(table, denom_col="population_2020", scale=1000, years=1.0)
    assert rate == pytest.approx(15.0)  # (10+20)/(1000+1000)*1000


def test_city_baseline_ratios_baseline_rate_applies_scale():
    # Regression test: baseline_rate must be on the same scale as the
    # neighborhood's own rate, or it is not comparable to it.
    table = pd.DataFrame({
        "Neighborhood": ["A", "B"],
        "incidents": [10, 10],
        "population_2020": [1000.0, 1000.0],
    })
    result = a.compute_city_baseline_ratios(
        table, denom_col="population_2020", scale=1000, years=1.0
    )
    # B's baseline is A's rate alone: 10/1000*1000/1 = 10.0, not 0.01.
    assert result.loc[result.Neighborhood == "B", "baseline_rate"].iloc[0] == pytest.approx(10.0)


def test_city_baseline_ratios_rate_ratio_is_scale_invariant():
    # The bug report on the missing *1000 factor specifically noted that
    # rate_ratio (own_rate / baseline_rate) is unaffected by the scale bug
    # because the same missing factor cancels out of both the numerator and
    # denominator. Confirm that explicitly: scale=1 and scale=1000 must
    # produce identical ratios even though baseline_rate itself differs.
    table = pd.DataFrame({
        "Neighborhood": ["A", "B", "C"],
        "incidents": [20, 10, 10],
        "population_2020": [1000.0, 1000.0, 1000.0],
    })
    unscaled = a.compute_city_baseline_ratios(table, denom_col="population_2020", scale=1, years=1.0)
    scaled = a.compute_city_baseline_ratios(table, denom_col="population_2020", scale=1000, years=1.0)
    pd.testing.assert_series_equal(
        unscaled["rate_ratio"], scaled["rate_ratio"], check_exact=False
    )
    # But the absolute baseline_rate values are NOT the same -- that's the
    # part of the bug that actually mattered (the ranking chart renders
    # baseline_rate/density_pop directly, not rate_ratio alone).
    assert not unscaled["baseline_rate"].equals(scaled["baseline_rate"])


def test_city_baseline_ratios_uniform_city_gives_ratio_one():
    table = pd.DataFrame({
        "Neighborhood": ["A", "B", "C"],
        "incidents": [10, 10, 10],
        "sqmiles": [1.0, 1.0, 1.0],
    })
    result = a.compute_city_baseline_ratios(table, years=1.0)
    assert result["rate_ratio"].round(6).tolist() == [1.0, 1.0, 1.0]


def test_city_baseline_ratios_double_rate_neighborhood():
    table = pd.DataFrame({
        "Neighborhood": ["A", "B", "C"],
        "incidents": [20, 10, 10],
        "sqmiles": [1.0, 1.0, 1.0],
    })
    result = a.compute_city_baseline_ratios(table, years=1.0)
    # A's baseline is the average of B and C (10/1 each) = 10; A's own rate is 20.
    assert result.loc[result.Neighborhood == "A", "rate_ratio"].iloc[0] == pytest.approx(2.0)


def test_city_baseline_ratios_leave_one_out_excludes_self():
    # If baseline included the focal neighborhood, a single huge outlier
    # would inflate its own comparator and pull the ratio toward 1.
    table = pd.DataFrame({
        "Neighborhood": ["Huge", "Small"],
        "incidents": [1000, 10],
        "sqmiles": [1.0, 1.0],
    })
    result = a.compute_city_baseline_ratios(table, years=1.0)
    huge_baseline = result.loc[result.Neighborhood == "Huge", "baseline_rate"].iloc[0]
    assert huge_baseline == pytest.approx(10.0)  # baseline = Small's rate alone


def test_city_baseline_ratios_respects_valid_mask_for_population():
    # Neighborhoods without a population figure must not contribute to the
    # pool, and must not receive a ratio themselves.
    table = pd.DataFrame({
        "Neighborhood": ["HasPop1", "HasPop2", "NoPop"],
        "incidents": [10, 10, 999],
        "population_2020": [1000.0, 1000.0, np.nan],
    })
    valid_mask = table["population_2020"].notna()
    result = a.compute_city_baseline_ratios(
        table, count_col="incidents", denom_col="population_2020", years=1.0, valid_mask=valid_mask
    )
    assert pd.isna(result.loc[result.Neighborhood == "NoPop", "rate_ratio"].iloc[0])
    # HasPop1's baseline should reflect only HasPop2 (rate 10/1000), not the
    # NoPop row's huge incident count leaking into the pool.
    has_pop1_baseline = result.loc[result.Neighborhood == "HasPop1", "baseline_rate"].iloc[0]
    assert has_pop1_baseline == pytest.approx(10 / 1000)


# ---------------------------------------------------------------------------
# compute_full_rate_table / compute_city_overall_rates
# ---------------------------------------------------------------------------


def _sample_bridge_incidents_denominators():
    bridge = pd.DataFrame({
        "Report_Number": ["R1", "R2", "R3"],
        "category": ["High Threat", "High Threat", "Auto & Parking"],
    })
    incidents = pd.DataFrame({
        "Report_Number": ["R1", "R2", "R3"],
        "Neighborhood": ["A", "B", "A"],
    })
    areas = pd.DataFrame({"Neighborhood": ["A", "B"], "sqmiles": [1.0, 2.0]})
    population = pd.DataFrame({"Neighborhood": ["A"], "population_2020": [1000.0]})  # B missing
    return bridge, incidents, areas, population


def test_compute_full_rate_table_has_all_expected_columns():
    bridge, incidents, areas, population = _sample_bridge_incidents_denominators()
    table = a.compute_full_rate_table(bridge, incidents, areas, population, "High Threat", years=1.0)
    for col in [
        "density_sqmi", "density_sqmi_lower", "density_sqmi_upper",
        "density_sqmi_baseline", "density_sqmi_ratio",
        "density_pop", "density_pop_lower", "density_pop_upper",
        "density_pop_baseline", "density_pop_ratio",
        "raw_count", "raw_count_lower", "raw_count_upper",
    ]:
        assert col in table.columns


def test_compute_full_rate_table_missing_population_has_no_pop_baseline():
    bridge, incidents, areas, population = _sample_bridge_incidents_denominators()
    table = a.compute_full_rate_table(bridge, incidents, areas, population, "High Threat", years=1.0)
    row_b = table[table.Neighborhood == "B"].iloc[0]
    assert pd.isna(row_b["density_pop"])
    assert pd.isna(row_b["density_pop_ratio"])
    # but area-based metrics are unaffected by the population gap
    assert not pd.isna(row_b["density_sqmi"])


def test_compute_full_rate_table_density_pop_interval_brackets_point_estimate():
    # Regression test (production code path): without the *1000 scale fix,
    # density_pop_lower/upper end up ~1000x smaller than density_pop itself,
    # which breaks the ranking chart's error bars for this metric.
    bridge, incidents, areas, population = _sample_bridge_incidents_denominators()
    table = a.compute_full_rate_table(bridge, incidents, areas, population, "High Threat", years=1.0)
    row_a = table[table.Neighborhood == "A"].iloc[0]
    assert row_a["density_pop_lower"] < row_a["density_pop"] < row_a["density_pop_upper"]


def test_density_pop_point_estimate_interval_city_rate_and_baseline_share_units():
    """All four population-normalized quantities the UI renders together --
    the point estimate, its interval, the city-wide reference rate, and the
    leave-one-out baseline -- must be expressed in the same "per 1,000
    residents per year" units. Uses a uniform per-capita rate across three
    equal-population neighborhoods, where a correct implementation collapses
    all four to the same number; the *1000 scale bug would instead put the
    city rate and baseline ~1000x below the point estimate.
    """
    bridge = pd.DataFrame({
        "Report_Number": [f"R{i}" for i in range(30)],
        "category": ["High Threat"] * 30,
    })
    incidents = pd.DataFrame({
        "Report_Number": [f"R{i}" for i in range(30)],
        "Neighborhood": ["A"] * 10 + ["B"] * 10 + ["C"] * 10,
    })
    areas = pd.DataFrame({"Neighborhood": ["A", "B", "C"], "sqmiles": [1.0, 1.0, 1.0]})
    population = pd.DataFrame({
        "Neighborhood": ["A", "B", "C"], "population_2020": [1000.0, 1000.0, 1000.0],
    })

    table = a.compute_full_rate_table(bridge, incidents, areas, population, "High Threat", years=1.0)
    city_rates = a.compute_city_overall_rates(table, years=1.0)

    row = table[table.Neighborhood == "A"].iloc[0]
    expected = 10 / 1000 * 1000 / 1  # == 10.0, per compute_rates' density_pop formula

    assert row["density_pop"] == pytest.approx(expected)
    assert row["density_pop_lower"] < row["density_pop"] < row["density_pop_upper"]
    assert row["density_pop_baseline"] == pytest.approx(expected)
    assert city_rates[a.METRIC_DENSITY_POP] == pytest.approx(expected)


def test_compute_city_overall_rates_raw_count_is_nan():
    bridge, incidents, areas, population = _sample_bridge_incidents_denominators()
    table = a.compute_full_rate_table(bridge, incidents, areas, population, "High Threat", years=1.0)
    city_rates = a.compute_city_overall_rates(table, years=1.0)
    assert pd.isna(city_rates[a.METRIC_RAW_COUNT])
    assert not pd.isna(city_rates[a.METRIC_DENSITY_SQMI])
