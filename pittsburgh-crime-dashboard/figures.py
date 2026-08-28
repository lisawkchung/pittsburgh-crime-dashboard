"""Plotly figure builders for the crime dashboard.

Deliberately avoids the word "risk" in any user-facing string: these
figures show where incidents were reported, not a measure of personal
danger. See README.md "Methodology" and "Limitations".

Visual styling only in this module -- no analytical logic. Metrics,
taxonomy, counting rules, and statistical calculations all live in
data.py / analysis.py and are untouched here.
"""

from datetime import datetime

import plotly.express as px
import plotly.graph_objects as go

from data import ANALYSIS_END, ANALYSIS_START, NIGHTTIME_HOUR_RANGES

METRIC_LABELS = {
    "density_sqmi": "Reported incidents per square mile per year",
    "density_pop": "Reported incidents per 1,000 residents per year",
    "raw_count": "Raw incident count (not comparable across neighborhoods)",
}

# Short forms for chart subtitles: "per sq mi/year" rather than the full
# METRIC_LABELS sentence.
METRIC_LABELS_SHORT = {
    "density_sqmi": "per sq mi/year",
    "density_pop": "per 1,000 residents/year",
    "raw_count": "raw count",
}

# Compact labels for the Metric selector control itself (app.py).
METRIC_LABELS_CONTROL = {
    "density_sqmi": "Per sq mi / year",
    "density_pop": "Per 1,000 residents / year",
    "raw_count": "Raw count",
}

# Very short unit for the choropleth colorbar title.
METRIC_UNIT_SHORT = {
    "density_sqmi": "per sq mi/yr",
    "density_pop": "per 1k/yr",
    "raw_count": "count",
}

WINDOW_LABEL = f"{ANALYSIS_START} to {ANALYSIS_END}"
_START_DT = datetime.strptime(ANALYSIS_START, "%Y-%m-%d")
_END_DT = datetime.strptime(ANALYSIS_END, "%Y-%m-%d")
WINDOW_LABEL_SHORT = f"{_START_DT.strftime('%b %Y')}–{_END_DT.strftime('%b %Y')}"
ANALYSIS_MONTHS = (_END_DT.year - _START_DT.year) * 12 + (_END_DT.month - _START_DT.month) + 1


def _format_hour(hour_24):
    """12-hour clock label for a plain 0-23 hour, e.g. 17 -> '5 PM'."""
    period = "AM" if hour_24 < 12 else "PM"
    display_hour = hour_24 % 12 or 12
    return f"{display_hour} {period}"


def _format_hour_fixed_label(hour_fixed):
    """Human-readable label for a data.compute_hour_fixed() value (17..26).
    Never expose the raw Hour_fixed integer or column name in the UI."""
    return _format_hour(hour_fixed % 24)

# Token-free MapLibre basemap style (no Mapbox account/token involved at all,
# unlike the legacy *_mapbox trace family).
MAP_STYLE = "carto-positron"

FONT_FAMILY = "Inter, system-ui, -apple-system, Segoe UI, Arial, sans-serif"

# Consistent category colors wherever categories are color-encoded.
CATEGORY_COLORS = {
    "High Threat": "#b23b3b",
    "Property & Theft": "#c98a2c",
    "Everyday Risks": "#3b6ea5",
    "Auto & Parking": "#5a8f5a",
}


def _apply_shared_layout(fig, **extra_layout):
    layout = dict(
        font=dict(family=FONT_FAMILY, color="#1f2328"),
        title_font=dict(family=FONT_FAMILY, size=18),
        margin={"l": 20, "r": 20, "t": 70, "b": 20},
    )
    layout.update(extra_layout)
    fig.update_layout(**layout)
    return fig


def _chart_title(main, subtitle):
    return f"{main}<br><span style='font-size:13px;color:#57606a'>{subtitle}</span>"


def build_choropleth_figure(rate_table, geojson_data, metric, category):
    """City-wide choropleth of a normalized rate (or raw count) for one
    category, across every neighborhood with a valid area."""
    hover_data = {"sqmiles": ":.2f", "population_2020": ":.0f", metric: ":.2f"}
    if metric != "raw_count":
        # raw_count IS incidents (see analysis.compute_rates); showing both
        # would render the same value twice under two different labels.
        hover_data = {"incidents": True, **hover_data}

    fig = px.choropleth_map(
        rate_table,
        geojson=geojson_data,
        locations="Neighborhood",
        featureidkey="properties.hood",
        color=metric,
        color_continuous_scale="Reds",
        map_style=MAP_STYLE,
        center={"lat": 40.44, "lon": -79.97},
        zoom=10.3,
        opacity=0.85,
        hover_name="Neighborhood",
        hover_data=hover_data,
        labels={metric: METRIC_LABELS.get(metric, metric)},
    )
    _apply_shared_layout(
        fig,
        title=_chart_title("Neighborhood incident density",
                            f"{category} · {METRIC_LABELS_SHORT.get(metric, metric)} · {WINDOW_LABEL_SHORT}"),
        margin={"l": 0, "r": 0, "t": 70, "b": 0},
        coloraxis_colorbar=dict(
            title=dict(text=METRIC_UNIT_SHORT.get(metric, ""), side="right", font=dict(size=11)),
            len=0.75,
            thickness=14,
            xpad=8,
            tickfont=dict(size=10),
        ),
    )
    return fig


def build_ranking_figure(rate_table, metric, category, city_overall_rate=None, top_n=15):
    """Horizontal dot plot of neighborhoods ranked by `metric`, with
    approximate Poisson uncertainty bars and an optional city-wide
    reference line. Uncertainty bars are NOT a formal significance test --
    see README.md "Methodology".

    top_n limits how many neighborhoods are PLOTTED here (None = all).
    This is a display choice only -- the choropleth always shows every
    neighborhood regardless of top_n, and no underlying rate, interval, or
    baseline value is altered by this slicing.
    """
    lower_col = f"{metric}_lower"
    upper_col = f"{metric}_upper"

    ranked = rate_table.dropna(subset=[metric]).sort_values(metric, ascending=False)
    if top_n is not None:
        ranked = ranked.head(top_n)
    plot_table = ranked.sort_values(metric, ascending=True)

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
        marker=dict(size=7, color=CATEGORY_COLORS.get(category, "#b23b3b")),
        name=category,
        showlegend=False,
    ))

    if city_overall_rate is not None and city_overall_rate == city_overall_rate:  # not NaN
        # Line only here (no annotation_text) -- the label is added separately
        # below, pinned INSIDE the plot's paper bounds so it can never
        # collide with the title/subtitle above the plot.
        fig.add_vline(x=city_overall_rate, line_dash="dash", line_color="#9aa3ab")
        fig.add_annotation(
            x=city_overall_rate,
            xref="x",
            y=0.98,
            yref="paper",
            yanchor="top",
            xanchor="left",
            text="City average",
            showarrow=False,
            font=dict(size=10, color="#6b7280"),
            bgcolor="rgba(255,255,255,0.85)",
            borderpad=2,
        )

    n_shown = len(plot_table)
    scope_label = "all neighborhoods" if top_n is None else f"top {n_shown}"
    _apply_shared_layout(
        fig,
        title=_chart_title("Neighborhood ranking",
                            f"{category} · {METRIC_LABELS_SHORT.get(metric, metric)} · {scope_label}"),
        xaxis_title=METRIC_LABELS_SHORT.get(metric, metric),
        yaxis=dict(automargin=True, ticksuffix="  "),
        margin={"l": 20, "r": 20, "t": 70, "b": 40},
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
    # Hour_fixed is an internal wraparound-ordering field (data.py) and must
    # never surface in the UI. Build a human-readable time label column and
    # animate on that instead -- this also fixes the animation frame/slider
    # labels and the "currentvalue" indicator, which otherwise default to
    # the raw column name and integer values (e.g. "Hour_fixed=17").
    hour_fixed_order = list(df_nighttime["Hour_fixed"].cat.categories)
    label_by_hour_fixed = {h: _format_hour_fixed_label(h) for h in hour_fixed_order}
    time_order = [label_by_hour_fixed[h] for h in hour_fixed_order]

    plot_df = df_nighttime.copy()
    plot_df["Time of day"] = plot_df["Hour_fixed"].map(label_by_hour_fixed)

    fig = px.scatter_map(
        plot_df,
        lat="YCOORD",
        lon="XCOORD",
        color="category",
        color_discrete_map=CATEGORY_COLORS,
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
        animation_frame="Time of day",
        category_orders={"Time of day": time_order},
        map_style=MAP_STYLE,
        center={"lat": 40.447766, "lon": -79.937054},
        zoom=13,
    )

    start_label = _format_hour(NIGHTTIME_HOUR_RANGES[0][0])
    end_label = _format_hour(NIGHTTIME_HOUR_RANGES[1][1])
    _apply_shared_layout(
        fig,
        title=_chart_title(
            "Campus area incidents by hour",
            f"{start_label}–{end_label} · CMU-adjacent neighborhoods",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.18,
            xanchor="center",
            x=0.5,
        ),
        margin={"l": 0, "r": 0, "t": 130, "b": 10},
        dragmode="zoom",
        hovermode="closest",
        uirevision=True,
    )
    fig.update_layout(sliders=[dict(currentvalue=dict(prefix="Time: "), pad=dict(b=10, t=10))])

    for trace in fig.data:
        if trace.name != "High Threat":
            trace.visible = "legendonly"

    return fig
