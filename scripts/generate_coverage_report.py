"""Regenerate docs/category_coverage.md from live WPRDC data.

Run from the repo root: python scripts/generate_coverage_report.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pittsburgh-crime-dashboard"))

import analysis as an  # noqa: E402
import data as d  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "docs" / "category_coverage.md"


def main():
    raw = d.fetch_crime_data()
    d.validate_required_columns(raw, d.REQUIRED_CRIME_COLUMNS)
    raw = d.drop_records_without_report_number(raw)
    raw = d.normalize_offense_codes(raw)
    windowed = d.filter_analysis_window(raw)
    df = d.preprocess_crime_data(windowed)

    incidents = d.build_incident_table(df)
    bridge = d.build_incident_category_bridge(df)
    coverage_status = d.compute_incident_coverage_status(df)

    audit = an.compute_coverage_audit(coverage_status, len(incidents))
    membership = an.compute_category_membership_summary(bridge, coverage_status)

    lines = [
        "# Category Coverage Report",
        "",
        f"Generated from live WPRDC data. Analysis window: {d.ANALYSIS_START} to {d.ANALYSIS_END}.",
        f"Total incidents in window: {len(incidents):,}.",
        "",
        "## Coverage status (mutually exclusive, reconciles to 100%)",
        "",
        "| Status | Incidents | % of window incidents |",
        "|---|---:|---:|",
    ]
    for row in audit.itertuples():
        lines.append(f"| {row.status} | {row.incidents:,} | {row.pct_of_window_incidents:.1f}% |")

    lines += [
        "",
        "## Student-relevant category membership (overlapping -- rows need not sum to the total)",
        "",
        "| Category | Incidents | % of student-relevant incidents |",
        "|---|---:|---:|",
    ]
    for row in membership.itertuples():
        lines.append(f"| {row.category} | {row.incidents:,} | {row.pct_of_student_relevant:.1f}% |")

    lines += [
        "",
        "See README.md \"Methodology\" for the full taxonomy, exclusion rationale, and "
        "why category totals overlap.",
        "",
    ]

    OUTPUT_PATH.write_text("\n".join(lines))
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
