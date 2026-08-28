"""Plotly figure builders for the crime dashboard.

Deliberately avoids the word "risk" in any user-facing string: these
figures show where incidents were reported, not a measure of personal
danger. See README.md "Methodology" and "Limitations".
"""

import plotly.express as px
import plotly.graph_objects as go

from data import ANALYSIS_END, ANALYSIS_START, NIGHTTIME_HOUR_RANGES

METRIC_LABELS = {
    "density_sqmi": "Reported incidents per square mile per year",
    "density_pop": "Reported incidents per 1,000 residents per year",
    "raw_count": "Raw incident count (not comparable across neighborhoods)",
}

WINDOW_LABEL = f"{ANALYSIS_START} to {ANALYSIS_END}"


def build_choropleth_figure(rate_table, geojson_data, metric, category):
    """City-wide choropleth of a normalized rate (or raw count) for one
    category, across every neighborhood with a valid area."""
    hover_data = {"sqmiles": ":.2f", "population_2020": ":.0f", metric: ":.2f"}
    if metric != "raw_count":
        # raw_count IS incidents (see analysis.compute_rates); showing both
        # would render the same value twice under two different labels.
        hover_data = {"incidents": True, **hover_data}

    fig = px.choropleth_mapbox(
        rate_table,
        geojson=geojson_data,
        locations="Neighborhood",
        featureidkey="properties.hood",
        color=metric,
        color_continuous_scale="Reds",
        mapbox_style="carto-positron",
        center={"lat": 40.44, "lon": -79.97},
        zoom=10.3,
        opacity=1.0,
        hover_name="Neighborhood",
        hover_data=hover_data,
        labels={metric: METRIC_LABELS.get(metric, metric)},
    )
    fig.update_layout(
        title=f"Reported Incident Density — {category}<br>"
              f"<sup>{METRIC_LABELS.get(metric, metric)} · {WINDOW_LABEL}</sup>",
        margin={"r": 0, "t": 80, "l": 0, "b": 0},
    )
    return fig


def build_ranking_figure(rate_table, metric, category, city_overall_rate=None):
    """Horizontal dot plot of neighborhoods ranked by `metric`, with
    approximate Poisson uncertainty bars and an optional city-wide
    reference line. Uncertainty bars are NOT a formal significance test --
    see README.md "Methodology"."""
    lower_col = f"{metric}_lower"
    upper_col = f"{metric}_upper"

    plot_table = rate_table.dropna(subset=[metric]).sort_values(metric, ascending=True)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=plot_table[metric],
        y=plot_table["Neighborhood"],
        mode="markers",
        error_x=dict(
            type="data",
            symmetric=False,
            array=plot_table[upper_col] - plot_table[metric],
            arrayminus=plot_table[metric] - plot_table[lower_col],
            thickness=1,
            width=0,
        ),
        marker=dict(size=6, color="#b23b3b"),
        name=category,
    ))

    if city_overall_rate is not None and city_overall_rate == city_overall_rate:  # not NaN
        fig.add_vline(
            x=city_overall_rate,
            line_dash="dash",
            line_color="gray",
            annotation_text="city-wide rate",
            annotation_position="top",
        )

    fig.update_layout(
        title=f"Neighborhood Ranking with Approximate Uncertainty — {category}<br>"
              f"<sup>{METRIC_LABELS.get(metric, metric)} · bars are approximate Poisson "
              f"intervals, not a significance test</sup>",
        xaxis_title=METRIC_LABELS.get(metric, metric),
        yaxis_title=None,
        height=max(400, 16 * len(plot_table)),
        margin={"l": 160, "t": 90, "b": 40},
    )
    return fig


def build_campus_scatter_figure(df_nighttime):
    """Animated scatter map of campus-area nighttime incidents by hour.

    One point per (Report_Number, category) -- built from the incident table
    and incident-category bridge, not raw offense rows, so this view uses
    the same overlapping-category counting model as the rest of the
    dashboard: an incident with two same-category offenses is one point; an
    incident spanning two categories is one point per category.
    """
    custom_order = list(df_nighttime["Hour_fixed"].cat.categories)

    fig = px.scatter_mapbox(
        df_nighttime,
        lat="YCOORD",
        lon="XCOORD",
        color="category",
        hover_name="Neighborhood",
        hover_data={
            "Report_Number": True,
            "ReportedDate": True,
            "ReportedTime": True,
            "n_offenses": True,
            "YCOORD": False,
            "XCOORD": False,
            "Hour": False,
        },
        animation_frame="Hour_fixed",
        category_orders={"Hour_fixed": custom_order},
        zoom=13,
        title=f"Campus Area: Reported Incidents by Hour and Location "
              f"({NIGHTTIME_HOUR_RANGES[0][0]}:00–{NIGHTTIME_HOUR_RANGES[1][1]}:00)",
        height=800,
        width=1200,
    )

    fig.update_layout(
        mapbox_style="carto-positron",
        mapbox_center={"lat": 40.447766, "lon": -79.937054},
        mapbox_zoom=13,
        dragmode="zoom",
        hovermode="closest",
        uirevision=True,
        mapbox={"accesstoken": None},
        newshape=dict(line_color="cyan"),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=1.05,
            xanchor="center",
            x=0.5,
        ),
        margin={"r": 0, "t": 80, "l": 0, "b": 20},
        sliders=[dict(pad=dict(b=20, t=0))],
    )

    for trace in fig.data:
        if trace.name != "High Threat":
            trace.visible = "legendonly"

    return fig
