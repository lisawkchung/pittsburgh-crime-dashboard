"""Dash entrypoint: wires the data/analysis pipeline to the UI.

Run with: python app.py
Then open http://127.0.0.1:8053
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

METRIC_OPTIONS = [{"label": fig.METRIC_LABELS[m], "value": m} for m in an.METRICS]

CAVEAT_BANNER_ITEMS = [
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
]


def build_coverage_summary(coverage_audit, membership_summary):
    audit_by_status = coverage_audit.set_index("status")
    lines = [
        html.P(
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
        ),
        html.P(
            "Category incident counts (may overlap -- see caveats above): " +
            ", ".join(
                f"{row.category}: {row.incidents:,}"
                for row in membership_summary.itertuples()
                if row.category != d.ALL_STUDENT_RELEVANT_LABEL
            )
        ),
    ]
    return html.Div(lines, style={"fontSize": "0.85em", "color": "#444"})


def build_dash_app(rates_by_category, city_rates_by_category, geojson_data,
                    campus_scatter_fig, coverage_audit, membership_summary):
    app = dash.Dash(__name__)
    app.title = "Pittsburgh Neighborhood Safety Analytics Dashboard"

    app.layout = html.Div([
        html.H1("Pittsburgh Neighborhood Safety Analytics Dashboard"),
        html.P("Built with a CMU-student lens on campus-area awareness and housing decisions."),
        html.P(
            f"Shows reported police incidents, {fig.WINDOW_LABEL}, as reported incident counts "
            "and reported incident density (per square mile / per 1,000 residents). Descriptive "
            "analysis only -- not a prediction of crime and not an estimate of personal "
            "victimization risk. See README.md for full methodology and limitations."
        ),
        html.Ul([html.Li(item) for item in CAVEAT_BANNER_ITEMS]),

        html.Div([
            html.Label("Metric"),
            dcc.RadioItems(
                id="metric-selector",
                options=METRIC_OPTIONS,
                value=DEFAULT_METRIC,
                labelStyle={"display": "block"},
            ),
        ], style={"marginBottom": "1em"}),

        html.Div([
            html.Label("Category"),
            dcc.Dropdown(
                id="category-selector",
                options=[{"label": c, "value": c} for c in CATEGORY_OPTIONS],
                value=DEFAULT_CATEGORY,
                clearable=False,
            ),
        ], style={"marginBottom": "1em", "maxWidth": "500px"}),

        html.Div(dcc.Graph(id="choropleth", config={"scrollZoom": True}),
                  style={"display": "flex", "justifyContent": "center"}),
        html.Div(dcc.Graph(id="ranking"),
                  style={"display": "flex", "justifyContent": "center"}),

        html.Hr(),
        html.H2("Data coverage"),
        build_coverage_summary(coverage_audit, membership_summary),

        html.Hr(),
        html.H2("Campus area: nighttime incidents by hour"),
        html.P(
            "Cell counts here are often 1-2 incidents per neighborhood-hour; treat this "
            "animation as illustrative of where/when incidents cluster, not as precise "
            "hour-by-hour comparisons."
        ),
        html.Div(
            dcc.Graph(figure=campus_scatter_fig, config={"scrollZoom": True},
                      style={"height": "800px", "width": "80%"}),
            style={"display": "flex", "justifyContent": "center"},
        ),
    ], style={"maxWidth": "1200px", "margin": "0 auto", "padding": "1em"})

    @app.callback(
        Output("choropleth", "figure"),
        Output("ranking", "figure"),
        Input("metric-selector", "value"),
        Input("category-selector", "value"),
    )
    def update_figures(metric, category):
        table = rates_by_category[category]
        choropleth = fig.build_choropleth_figure(table, geojson_data, metric, category)
        city_rate = city_rates_by_category[category].get(metric)
        ranking = fig.build_ranking_figure(table, metric, category, city_overall_rate=city_rate)
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
    )
    app.run(debug=True, port=DASH_PORT)


if __name__ == "__main__":
    main()
