"""Dash entrypoint: wires the data/analysis pipeline to the UI.

Run with: python app.py
Then open http://127.0.0.1:8053

This module is UI/layout only. All metrics, taxonomy, counting rules, and
statistical calculations live in data.py / analysis.py and are untouched
by the visual redesign here.
"""

import dash
from dash import Input, Output, dcc, html

import analysis as an
import data as d
import figures as fig

DASH_PORT = 8053

CATEGORY_OPTIONS = list(d.STUDENT_CATEGORY_NAMES) + [d.ALL_STUDENT_RELEVANT_LABEL]
DEFAULT_CATEGORY = "High Threat"
DEFAULT_METRIC = an.METRIC_DENSITY_SQMI
DEFAULT_TOP_N = 15

METRIC_OPTIONS = [{"label": fig.METRIC_LABELS_CONTROL[m], "value": m} for m in an.METRICS]
TOP_N_OPTIONS = [
    {"label": "Top 15", "value": 15},
    {"label": "Top 25", "value": 25},
    {"label": "All", "value": 0},  # 0 is a sentinel for "no limit" (see update_figures)
]

GRAPH_CONFIG = {"scrollZoom": True, "displayModeBar": False}

METRIC_HELP_TEXT = (
    "Normalized metrics (per sq mi, per 1,000 residents) support cross-neighborhood comparison; "
    "raw counts do not -- see Methodology."
)
RANKING_CAPTION = "Dot = selected metric value · line = approximate 95% interval (not a significance test)."
CAMPUS_CAPTION = (
    "Low sample sizes: use this animation for exploratory patterns, not precise "
    "hour-to-hour comparisons."
)

METHODOLOGY_ITEMS = [
    "Shows reported incident density -- where incidents were reported, not personal risk.",
    "Per-square-mile density avoids the residential-population undercounting problem below, but "
    "it is not an exposure denominator: it does not adjust for foot traffic, land use, daytime "
    "population, or how many people are actually present in a neighborhood.",
    "Per-resident rates are distorted wherever daytime/transient population greatly exceeds "
    "residential population (e.g. Central Business District, Oakland, Strip District, South Side "
    "Flats) -- residential population undercounts who is actually present in those neighborhoods.",
    "Categories overlap: one incident can involve offenses in more than one category, so "
    "category-specific incident counts do not sum to the total.",
    "Uncertainty bars are approximate Poisson intervals describing count variability only -- "
    "overlap or non-overlap is not a formal statistical test.",
    "The campus-area nighttime animation often has just 1-2 incidents per neighborhood-hour; "
    "treat it as illustrative of where/when incidents cluster, not as precise hour-by-hour "
    "comparisons.",
]


def build_kpi_cards(coverage_audit, n_neighborhoods):
    audit_by_status = coverage_audit.set_index("status")
    total = int(coverage_audit["incidents"].sum())
    student_relevant = int(audit_by_status.loc["student_relevant", "incidents"])
    share_pct = audit_by_status.loc["student_relevant", "pct_of_window_incidents"]

    # Same underlying numbers as before (coverage_audit is untouched) --
    # student-relevant count and share are combined into one card, and the
    # freed slot shows the analysis window length.
    cards = [
        ("Total incidents", f"{total:,}", fig.WINDOW_LABEL_SHORT),
        ("Student-relevant incidents", f"{student_relevant:,} · {share_pct:.0f}%",
         f"of {total:,} incidents in the window"),
        ("Analysis window", f"{fig.ANALYSIS_MONTHS} months", fig.WINDOW_LABEL_SHORT),
        ("Neighborhoods analyzed", f"{n_neighborhoods}", "with a valid area (city-wide)"),
    ]
    return html.Div([
        html.Div([
            html.Div(label, className="kpi-label"),
            html.Div(value, className="kpi-value"),
            html.Div(note, className="kpi-note"),
        ], className="kpi-card")
        for label, value, note in cards
    ], className="kpi-row")


def build_methodology_section(coverage_audit, membership_summary):
    audit_by_status = coverage_audit.set_index("status")
    coverage_text = (
        f"Of {coverage_audit['incidents'].sum():,} reported incidents in the analysis window, "
        f"{audit_by_status.loc['student_relevant', 'incidents']:,} "
        f"({audit_by_status.loc['student_relevant', 'pct_of_window_incidents']:.1f}%) involve at "
        "least one student-relevant offense. "
        f"{audit_by_status.loc['out_of_scope', 'incidents']:,} "
        f"({audit_by_status.loc['out_of_scope', 'pct_of_window_incidents']:.1f}%) are validly "
        "reported offenses outside this product's scope (e.g. drugs, fraud). "
        f"{audit_by_status.loc['administrative', 'incidents']:,} "
        f"({audit_by_status.loc['administrative', 'pct_of_window_incidents']:.1f}%) are "
        "administrative/non-NIBRS records or unresolvable codes."
    )
    category_text = "Category incident counts (may overlap -- see below): " + ", ".join(
        f"{row.category}: {row.incidents:,}"
        for row in membership_summary.itertuples()
        if row.category != d.ALL_STUDENT_RELEVANT_LABEL
    )

    return html.Details([
        html.Summary("Methodology & limitations"),
        html.Div([
            html.P(
                f"Reported police incidents, {fig.WINDOW_LABEL}, shown as reported incident "
                "counts and reported incident density (per square mile / per 1,000 residents). "
                "Descriptive analysis only -- not a prediction of crime. See README.md for the "
                "full methodology."
            ),
            html.P(coverage_text),
            html.P(category_text),
            html.Ul([html.Li(item) for item in METHODOLOGY_ITEMS]),
        ], className="methodology-body"),
    ], className="methodology")


def build_dash_app(rates_by_category, city_rates_by_category, geojson_data,
                    campus_scatter_fig, coverage_audit, membership_summary, n_neighborhoods):
    app = dash.Dash(__name__)
    app.title = "Pittsburgh Neighborhood Safety Analytics Dashboard"

    app.layout = html.Div([
        html.Div([
            html.H1("Pittsburgh Neighborhood Safety Analytics Dashboard"),
            html.P(
                "Reported-incident density across Pittsburgh neighborhoods, normalized and "
                "uncertainty-aware.",
                className="subtitle",
            ),
            html.Div(
                "Reported incidents are not a measure of personal victimization risk.",
                className="disclaimer",
            ),
            build_methodology_section(coverage_audit, membership_summary),
        ], className="header"),

        build_kpi_cards(coverage_audit, n_neighborhoods),

        html.Div([
            html.H2("Neighborhood comparison"),
            html.P(
                "The map always shows all 90 Pittsburgh neighborhoods with a valid area; the "
                "ranking chart on the right can be limited to the highest-density subset.",
                className="section-intro",
            ),

            html.Div([
                html.Div([
                    html.Div([
                        html.Div("Metric", className="control-label"),
                        dcc.RadioItems(
                            id="metric-selector",
                            options=METRIC_OPTIONS,
                            value=DEFAULT_METRIC,
                            className="segmented",
                            inputClassName="segmented-input",
                            labelClassName="segmented-label",
                        ),
                    ], className="control-group"),
                    html.Div([
                        html.Div("Category", className="control-label"),
                        dcc.Dropdown(
                            id="category-selector",
                            options=[{"label": c, "value": c} for c in CATEGORY_OPTIONS],
                            value=DEFAULT_CATEGORY,
                            clearable=False,
                            className="category-select",
                        ),
                    ], className="control-group"),
                ], className="control-bar-row"),
                html.Div(METRIC_HELP_TEXT, className="control-hint"),
                html.Div("Affects both charts below", className="control-scope-note"),
            ], className="control-bar card"),

            html.Div([
                html.Div(
                    dcc.Graph(id="choropleth", config=GRAPH_CONFIG, style={"height": "560px"}),
                    className="card choropleth-card",
                ),
                html.Div([
                    html.Div([
                        dcc.RadioItems(
                            id="topn-selector",
                            options=TOP_N_OPTIONS,
                            value=DEFAULT_TOP_N,
                            className="segmented segmented-sm",
                            inputClassName="segmented-input",
                            labelClassName="segmented-label",
                        ),
                    ], className="ranking-card-header"),
                    dcc.Graph(id="ranking", config=GRAPH_CONFIG, style={"height": "560px", "flex": "1"}),
                    html.P(RANKING_CAPTION, className="chart-caption"),
                ], className="card ranking-card"),
            ], className="comparison-row"),
        ], className="section"),

        html.Div([
            html.H2("Campus area: nighttime incidents by hour"),
            html.P(CAMPUS_CAPTION, className="section-intro"),
            dcc.Graph(
                figure=campus_scatter_fig, config=GRAPH_CONFIG, style={"height": "560px"},
            ),
        ], className="section campus-section card"),
    ], className="page")

    @app.callback(
        Output("choropleth", "figure"),
        Output("ranking", "figure"),
        Input("metric-selector", "value"),
        Input("category-selector", "value"),
        Input("topn-selector", "value"),
    )
    def update_figures(metric, category, top_n):
        table = rates_by_category[category]
        choropleth = fig.build_choropleth_figure(table, geojson_data, metric, category)
        city_rate = city_rates_by_category[category].get(metric)
        top_n = None if not top_n else top_n  # 0 ("All") -> None -> no limit
        ranking = fig.build_ranking_figure(table, metric, category, city_overall_rate=city_rate, top_n=top_n)
        return choropleth, ranking

    return app


def load_and_prepare_data():
    """Fetch, validate, clean, and model all incident-level data. Returns a
    dict of everything main() needs to build figures and the app."""
    raw = d.fetch_crime_data()
    d.validate_required_columns(raw, d.REQUIRED_CRIME_COLUMNS)
    raw = d.drop_records_without_report_number(raw)
    raw = d.normalize_offense_codes(raw)
    windowed = d.filter_analysis_window(raw)
    df = d.preprocess_crime_data(windowed)

    incidents = d.build_incident_table(df)
    bridge = d.build_incident_category_bridge(df)
    coverage_status = d.compute_incident_coverage_status(df)

    geojson_data = d.fetch_neighborhood_geojson()
    areas = d.extract_neighborhood_areas(geojson_data)
    population = d.fetch_neighborhood_population()

    rates_by_category = {}
    city_rates_by_category = {}
    for category in CATEGORY_OPTIONS:
        table = an.compute_full_rate_table(bridge, incidents, areas, population, category)
        rates_by_category[category] = table
        city_rates_by_category[category] = an.compute_city_overall_rates(table)

    coverage_audit = an.compute_coverage_audit(coverage_status, len(incidents))
    membership_summary = an.compute_category_membership_summary(bridge, coverage_status)

    campus_points = d.build_campus_nighttime_points(incidents, bridge)

    return {
        "rates_by_category": rates_by_category,
        "city_rates_by_category": city_rates_by_category,
        "geojson_data": geojson_data,
        "campus_points": campus_points,
        "coverage_audit": coverage_audit,
        "membership_summary": membership_summary,
        "n_neighborhoods": len(areas),
    }


def main():
    prepared = load_and_prepare_data()
    campus_scatter_fig = fig.build_campus_scatter_figure(prepared["campus_points"])

    app = build_dash_app(
        prepared["rates_by_category"],
        prepared["city_rates_by_category"],
        prepared["geojson_data"],
        campus_scatter_fig,
        prepared["coverage_audit"],
        prepared["membership_summary"],
        prepared["n_neighborhoods"],
    )
    app.run(debug=True, port=DASH_PORT)


if __name__ == "__main__":
    main()
