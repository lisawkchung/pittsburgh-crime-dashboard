"""Coverage auditing, normalized rates, and approximate uncertainty intervals.

All rate/interval functions operate on already-built incident and bridge
tables from data.py. See README.md "Methodology" for what these numbers mean
and, more importantly, what they do not mean.
"""

import numpy as np
import pandas as pd

from data import ALL_STUDENT_RELEVANT_LABEL, ANALYSIS_YEARS, STUDENT_CATEGORY_NAMES

# 95% two-sided normal quantile, used by the Byar's approximation below.
Z_95 = 1.959963985

METRIC_RAW_COUNT = "raw_count"
METRIC_DENSITY_SQMI = "density_sqmi"
METRIC_DENSITY_POP = "density_pop"
METRICS = (METRIC_DENSITY_SQMI, METRIC_DENSITY_POP, METRIC_RAW_COUNT)

COVERAGE_STATUSES = ("student_relevant", "out_of_scope", "administrative")


# ---------------------------------------------------------------------------
# Coverage audit
# ---------------------------------------------------------------------------


def compute_coverage_audit(coverage_status, window_incident_total):
    """Reconcile every in-window incident to exactly one of three mutually
    exclusive statuses: student_relevant / out_of_scope / administrative.
    Percentages sum to 100% of window_incident_total by construction.
    """
    counts = coverage_status.value_counts().reindex(COVERAGE_STATUSES, fill_value=0)
    pct = counts / window_incident_total * 100
    return pd.DataFrame({
        "status": counts.index,
        "incidents": counts.values,
        "pct_of_window_incidents": pct.values,
    }).reset_index(drop=True)


def compute_category_membership_summary(bridge, coverage_status):
    """Per-category incident counts as a share of student-relevant incidents.

    Category membership is intentionally overlapping (see
    data.build_incident_category_bridge), so these percentages are NOT
    expected to sum to 100%.
    """
    student_relevant_total = int((coverage_status == "student_relevant").sum())
    rows = []
    for category in STUDENT_CATEGORY_NAMES:
        n = bridge.loc[bridge["category"] == category, "Report_Number"].nunique()
        rows.append({
            "category": category,
            "incidents": n,
            "pct_of_student_relevant": n / student_relevant_total * 100 if student_relevant_total else np.nan,
        })
    all_relevant = bridge["Report_Number"].nunique()
    rows.append({
        "category": ALL_STUDENT_RELEVANT_LABEL,
        "incidents": all_relevant,
        "pct_of_student_relevant": all_relevant / student_relevant_total * 100 if student_relevant_total else np.nan,
    })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


def compute_neighborhood_incident_counts(bridge, incidents, category):
    """Unique-incident counts per neighborhood for one category, or for
    ALL_STUDENT_RELEVANT_LABEL (deduplicated across all categories)."""
    if category == ALL_STUDENT_RELEVANT_LABEL:
        report_numbers = bridge["Report_Number"].unique()
    else:
        report_numbers = bridge.loc[bridge["category"] == category, "Report_Number"].unique()

    subset = incidents[incidents["Report_Number"].isin(report_numbers)]
    return subset.groupby("Neighborhood")["Report_Number"].nunique().rename("incidents")


def compute_rates(counts, areas, population, years=ANALYSIS_YEARS):
    """Join incident counts onto every neighborhood with a valid area and
    compute area- and population-normalized rates.

    Neighborhoods with no incidents in this category get incidents=0 (not
    dropped). Neighborhoods with no population figure keep density_pop as
    NaN -- never imputed.
    """
    table = areas.merge(counts, on="Neighborhood", how="left")
    table = table.merge(population, on="Neighborhood", how="left")
    table["incidents"] = table["incidents"].fillna(0).astype(int)

    table["density_sqmi"] = table["incidents"] / table["sqmiles"] / years
    table["density_pop"] = np.where(
        table["population_2020"].notna() & (table["population_2020"] > 0),
        table["incidents"] / table["population_2020"] * 1000 / years,
        np.nan,
    )
    table["raw_count"] = table["incidents"].astype(float)
    return table


# ---------------------------------------------------------------------------
# Approximate Poisson uncertainty intervals
#
# These describe sampling variability in the observed COUNT under a Poisson
# assumption. They are not a formal hypothesis test, and they do not capture
# reporting bias, spatial/temporal clustering (which tends to make true
# variability wider than a Poisson model implies), or measurement error.
# Overlapping intervals mean a difference is not well supported by the data
# -- they do not by themselves establish that two rates are "the same".
# ---------------------------------------------------------------------------


def poisson_ci(count, z=Z_95):
    """Byar's approximation to an (approximate) 95% Poisson confidence
    interval for an observed count. Returns (lower, upper) count-scale
    bounds. Accurate for count >= ~5; still a reasonable approximation
    below that. count == 0 uses the standard exact-Poisson zero-event bound.
    """
    if count == 0:
        return 0.0, 3.689
    lower = count * (1 - 1 / (9 * count) - z / (3 * np.sqrt(count))) ** 3
    upper = (count + 1) * (1 - 1 / (9 * (count + 1)) + z / (3 * np.sqrt(count + 1))) ** 3
    return max(lower, 0.0), upper


def add_rate_intervals(table, metric, count_col="incidents", denom_col=None, scale=1, years=ANALYSIS_YEARS):
    """Add {metric}_lower / {metric}_upper columns: the count-scale Poisson
    interval converted to the same units as `metric` (divided by the same
    denominator and year count used to compute the rate, and multiplied by
    the same `scale` -- e.g. 1000 for a per-1,000-residents metric). For
    raw_count, pass denom_col=None to leave the interval on the count scale.
    """
    bounds = table[count_col].apply(poisson_ci)
    lower = bounds.apply(lambda b: b[0])
    upper = bounds.apply(lambda b: b[1])

    if denom_col is not None:
        denom = table[denom_col]
        valid = denom.notna() & (denom > 0)
        lower = np.where(valid, lower / denom * scale / years, np.nan)
        upper = np.where(valid, upper / denom * scale / years, np.nan)

    table = table.copy()
    table[f"{metric}_lower"] = lower
    table[f"{metric}_upper"] = upper
    return table


# ---------------------------------------------------------------------------
# City baseline comparison (leave-one-out)
# ---------------------------------------------------------------------------


def compute_city_overall_rate(table, count_col="incidents", denom_col="sqmiles",
                               scale=1, years=ANALYSIS_YEARS, valid_mask=None):
    """A single city-wide rate (all included neighborhoods pooled), for use
    as a reference line. Not leave-one-out -- see compute_city_baseline_ratios
    for the per-neighborhood comparison. `scale` must match the scale used
    to compute the metric (e.g. 1000 for a per-1,000-residents metric), or
    this reference value will be on the wrong scale relative to the points
    it's drawn against.
    """
    pool = table if valid_mask is None else table[valid_mask]
    total_count = pool[count_col].sum()
    total_denom = pool[denom_col].sum()
    if total_denom <= 0:
        return np.nan
    return total_count / total_denom * scale / years


def compute_city_baseline_ratios(table, count_col="incidents", denom_col="sqmiles",
                                  scale=1, years=ANALYSIS_YEARS, valid_mask=None):
    """Add baseline_rate and rate_ratio columns: each neighborhood's rate
    compared against a leave-one-out city baseline (the rest of the city,
    excluding that neighborhood).

    If valid_mask is given (boolean array aligned to table), only rows where
    it is True participate in the baseline pool -- both as contributors to
    the pooled total and as neighborhoods eligible for a ratio. This is used
    to keep population-based baselines from being computed using
    neighborhoods that lack a population figure (their incidents/population
    are excluded from the pool entirely, not imputed).
    """
    table = table.copy()
    table["baseline_rate"] = np.nan
    table["rate_ratio"] = np.nan

    pool_mask = pd.Series(True, index=table.index) if valid_mask is None else pd.Series(valid_mask, index=table.index)
    city_total_count = table.loc[pool_mask, count_col].sum()
    city_total_denom = table.loc[pool_mask, denom_col].sum()

    for idx in table.index[pool_mask]:
        n_count = table.at[idx, count_col]
        n_denom = table.at[idx, denom_col]
        rest_count = city_total_count - n_count
        rest_denom = city_total_denom - n_denom
        if rest_denom <= 0 or pd.isna(n_denom) or n_denom <= 0:
            continue
        baseline = rest_count / rest_denom * scale / years
        own_rate = n_count / n_denom * scale / years
        table.at[idx, "baseline_rate"] = baseline
        table.at[idx, "rate_ratio"] = own_rate / baseline if baseline > 0 else np.nan

    return table


# ---------------------------------------------------------------------------
# Orchestration: one full rate table (all metrics, intervals, and baselines)
# per category
# ---------------------------------------------------------------------------

# (denom_col, scale) per metric. scale must match the scale applied to the
# point estimate in compute_rates -- e.g. density_pop is incidents per 1,000
# residents, so its denominator-derived values (intervals, city rate,
# baseline) must also be multiplied by 1000, or they end up on the wrong
# scale relative to the point estimate they're drawn against.
_METRIC_DENOM_SPECS = {
    METRIC_DENSITY_SQMI: ("sqmiles", 1),
    METRIC_DENSITY_POP: ("population_2020", 1000),
    METRIC_RAW_COUNT: (None, 1),
}


def compute_full_rate_table(bridge, incidents, areas, population, category, years=ANALYSIS_YEARS):
    """Assemble the full per-neighborhood table for one category: incident
    counts, all three metrics, their approximate uncertainty intervals, and
    leave-one-out city-baseline comparisons for the two normalized metrics
    (raw_count has no baseline -- comparing raw counts across neighborhoods
    is exactly what normalization exists to avoid).
    """
    counts = compute_neighborhood_incident_counts(bridge, incidents, category)
    table = compute_rates(counts, areas, population, years=years)

    for metric, (denom_col, scale) in _METRIC_DENOM_SPECS.items():
        table = add_rate_intervals(table, metric, denom_col=denom_col, scale=scale, years=years)

    sqmi_denom, sqmi_scale = _METRIC_DENOM_SPECS[METRIC_DENSITY_SQMI]
    sqmi_baseline = compute_city_baseline_ratios(table, denom_col=sqmi_denom, scale=sqmi_scale, years=years)
    table["density_sqmi_baseline"] = sqmi_baseline["baseline_rate"]
    table["density_sqmi_ratio"] = sqmi_baseline["rate_ratio"]

    pop_denom, pop_scale = _METRIC_DENOM_SPECS[METRIC_DENSITY_POP]
    pop_valid = table["population_2020"].notna()
    pop_baseline = compute_city_baseline_ratios(
        table, denom_col=pop_denom, scale=pop_scale, years=years, valid_mask=pop_valid
    )
    table["density_pop_baseline"] = pop_baseline["baseline_rate"]
    table["density_pop_ratio"] = pop_baseline["rate_ratio"]

    return table


def compute_city_overall_rates(table, years=ANALYSIS_YEARS):
    """Single-number city-wide reference rate per metric (for the ranking
    chart's dashed reference line). raw_count has no meaningful single
    reference value."""
    pop_valid = table["population_2020"].notna()
    sqmi_denom, sqmi_scale = _METRIC_DENOM_SPECS[METRIC_DENSITY_SQMI]
    pop_denom, pop_scale = _METRIC_DENOM_SPECS[METRIC_DENSITY_POP]
    return {
        METRIC_DENSITY_SQMI: compute_city_overall_rate(table, denom_col=sqmi_denom, scale=sqmi_scale, years=years),
        METRIC_DENSITY_POP: compute_city_overall_rate(
            table, denom_col=pop_denom, scale=pop_scale, years=years, valid_mask=pop_valid
        ),
        METRIC_RAW_COUNT: np.nan,
    }
