"""Pittsburgh Crime Risk Dashboard: CMU Student View.

Fetches reported police-incident data from the WPRDC open-data API, buckets
offenses into heuristic "student risk" categories, and renders two Plotly
maps (an animated nighttime scatter map and a city-wide incident-count
choropleth) inside a Dash app.

See README.md for data-source details, methodology, and known limitations.
"""

import dash
import pandas as pd
import plotly.express as px
import requests
from dash import dcc, html

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CRIME_RESOURCE_ID = "bd41992a-987a-4cca-8798-fbe1cd946b07"
CRIME_API_URL = "https://data.wprdc.org/api/action/datastore_search"
NEIGHBORHOODS_GEOJSON_URL = (
    "https://data.wprdc.org/dataset/e672f13d-71c4-4a66-8f38-710e75ed80a4/"
    "resource/4af8e160-57e9-4ebf-a501-76ca1b42fc99/download/"
    "pittsburghpaneighborhoods-.geojson"
)

PAGE_LIMIT = 1000
MAX_PAGES = 1000  # safety net against a runaway/looping pagination, not an expected limit
REQUEST_TIMEOUT_SECONDS = 30
DASH_PORT = 8053

# Columns the rest of this module reads directly from the raw API response.
# "Hour" is provided by the source dataset itself and is not derived locally.
REQUIRED_CRIME_COLUMNS = [
    "ReportedDate",
    "ReportedTime",
    "Hour",
    "XCOORD",
    "YCOORD",
    "NIBRS_Coded_Offense",
    "NIBRS_Offense_Type",
    "Neighborhood",
]

# Heuristic, student-oriented regrouping of NIBRS offense codes.
# This is a custom categorization for this dashboard, not an official NIBRS
# severity classification. See README.md "Methodology" for rationale.
OFFENSE_CATEGORY_MAP = {
    # High Threat Crimes
    "09A MURDER & NON-NEGLIGENT MANSLAUGHTER": "High Threat Crimes",
    "09B MANSLAUGHTER BY NEGLIGENCE": "High Threat Crimes",
    "11A FORCIBLE RAPE": "High Threat Crimes",
    "11B FORCIBLE SODOMY": "High Threat Crimes",
    "11C SEXUAL ASSAULT WITH AN OBJECT": "High Threat Crimes",
    "11D FORCIBLE FONDLING": "High Threat Crimes",
    "36A INCEST": "High Threat Crimes",
    "36B STATUTORY RAPE": "High Threat Crimes",
    "64A COMMERCIAL SEX ACTS": "High Threat Crimes",
    "64B INVOLUNTARY SERVITUDE": "High Threat Crimes",
    "100 KIDNAPPING/ABDUCTION": "High Threat Crimes",
    "120 ROBBERY": "High Threat Crimes",
    "520 WEAPON LAW VIOLATIONS": "High Threat Crimes",
    # Everyday Risks
    "13A AGGRAVATED ASSAULT": "Everyday Risks",
    "13B SIMPLE ASSAULT": "Everyday Risks",
    "13C INTIMIDATION": "Everyday Risks",
    "23A POCKET PICKING": "Everyday Risks",
    "23B PURSE SNATCHING": "Everyday Risks",
    "90C DISORDERLY CONDUCT": "Everyday Risks",
    "90E DRUNKENNESS": "Everyday Risks",
    # Auto & Parking Risks
    "240 MOTOR VEHICLE THEFT": "Auto & Parking Risks",
    "23G THEFT OF MOTOR VEHICLE PARTS OR ACCESSORIES": "Auto & Parking Risks",
    "23F THEFT FROM MOTOR VEHICLE": "Auto & Parking Risks",
}

# Neighborhoods immediately around CMU, used for the nighttime scatter map.
CAMPUS_NEIGHBORHOODS = [
    "Central Oakland",
    "East Liberty",
    "North Oakland",
    "Oakland",
    "Shadyside",
    "Squirrel Hill North",
    "Squirrel Hill South",
]

# Broader set of neighborhoods used for the city-wide choropleth. Intentionally
# wider than CAMPUS_NEIGHBORHOODS -- see README.md "Methodology".
CHOROPLETH_NEIGHBORHOODS = [
    "Central Oakland", "North Oakland", "South Oakland", "West Oakland",
    "Shadyside", "Squirrel Hill North", "Squirrel Hill South",
    "Point Breeze", "Bloomfield", "Garfield", "East Liberty",
    "Greenfield", "Polish Hill", "Upper Hill", "Strip District", "Bluff",
    "Bedford Dwellings", "Middle Hill", "Crawford-Roberts",
    "Terrace Village", "Central Business District",
    "Central Lawrenceville", "Friendship", "Lower Lawrenceville",
    "Larimer", "Homewood West", "Homewood North", "Homewood South",
    "Point Breeze North", "Hazelwood", "Glen Hazel",
]

# Nighttime window for the campus scatter map: 5pm-11pm and midnight-2am.
NIGHTTIME_HOUR_RANGES = ((17, 23), (0, 2))


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def fetch_crime_data(
    resource_id=CRIME_RESOURCE_ID,
    api_url=CRIME_API_URL,
    page_limit=PAGE_LIMIT,
    max_pages=MAX_PAGES,
    timeout=REQUEST_TIMEOUT_SECONDS,
):
    """Fetch all records for a WPRDC datastore resource via paginated requests.

    Raises RuntimeError on network failure, a non-200 response, an API-level
    failure, an empty result set, or if pagination does not terminate within
    max_pages (a safety net, not an expected code path).
    """
    all_records = []
    offset = 0

    for _ in range(max_pages):
        params = {"resource_id": resource_id, "limit": page_limit, "offset": offset}
        try:
            response = requests.get(api_url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to reach WPRDC API at {api_url}: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"WPRDC API returned HTTP {response.status_code} for offset {offset}: "
                f"{response.text[:200]}"
            )

        payload = response.json()
        if not payload.get("success", False):
            raise RuntimeError(f"WPRDC API reported failure: {payload.get('error', payload)}")

        records = payload["result"]["records"]
        if not records:
            break

        all_records.extend(records)
        offset += page_limit
    else:
        raise RuntimeError(
            f"Reached max_pages={max_pages} while paginating WPRDC API without the "
            "result set ending; aborting instead of returning incomplete data."
        )

    if not all_records:
        raise RuntimeError("WPRDC API returned no crime records.")

    return pd.DataFrame(all_records)


def fetch_neighborhood_geojson(url=NEIGHBORHOODS_GEOJSON_URL, timeout=REQUEST_TIMEOUT_SECONDS):
    """Fetch the Pittsburgh neighborhood boundary GeoJSON used by the choropleth."""
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to reach neighborhood GeoJSON source at {url}: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(f"GeoJSON request returned HTTP {response.status_code}: {url}")

    return response.json()


def validate_required_columns(df, required_columns, context="crime data"):
    """Raise ValueError with a useful message if any required column is missing."""
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"{context} is missing required column(s): {missing}. "
            f"Available columns: {list(df.columns)}"
        )


# ---------------------------------------------------------------------------
# Preprocessing / categorization
# ---------------------------------------------------------------------------


def preprocess_crime_data(df):
    """Parse report timestamp/coordinates into usable dtypes. Returns a copy."""
    df = df.copy()
    df["ReportedDateTime"] = pd.to_datetime(
        df["ReportedDate"].astype(str) + " " + df["ReportedTime"].astype(str),
        errors="coerce",
    )
    df["Year"] = df["ReportedDateTime"].dt.year
    df["XCOORD"] = pd.to_numeric(df["XCOORD"], errors="coerce")
    df["YCOORD"] = pd.to_numeric(df["YCOORD"], errors="coerce")
    return df


def map_risk_categories(df, category_map=OFFENSE_CATEGORY_MAP):
    """Add a Risk_Categories_for_Students column. Unmapped offenses become "Other"."""
    df = df.copy()
    df["Risk_Categories_for_Students"] = df["NIBRS_Coded_Offense"].map(category_map).fillna("Other")
    return df


def compute_hour_fixed(hour_series):
    """Shift 0/1/2 AM hours to 24/25/26 so a 5pm-2am nighttime window sorts contiguously."""
    return hour_series.apply(lambda h: h + 24 if h in (0, 1, 2) else h)


def filter_campus_nighttime(df, neighborhoods=CAMPUS_NEIGHBORHOODS):
    """Filter to campus-area neighborhoods during the nighttime hour window.

    Adds an ordered categorical Hour_fixed column (17..26) for animation-frame
    ordering. Returns a copy; does not mutate df.
    """
    (start1, end1), (start2, end2) = NIGHTTIME_HOUR_RANGES
    nighttime_mask = df["Hour"].between(start1, end1) | df["Hour"].between(start2, end2)

    filtered = df[df["Neighborhood"].isin(neighborhoods) & nighttime_mask].copy()
    filtered["Hour_fixed"] = compute_hour_fixed(filtered["Hour"])

    custom_order = list(range(start1, end2 + 24 + 1))
    filtered = filtered.sort_values("Hour_fixed")
    filtered["Hour_fixed"] = pd.Categorical(
        filtered["Hour_fixed"], categories=custom_order, ordered=True
    )
    return filtered


def aggregate_high_threat_by_neighborhood(df, neighborhoods=CHOROPLETH_NEIGHBORHOODS):
    """Count "High Threat Crimes" incidents per neighborhood (raw counts, not normalized)."""
    high_threat = df[
        (df["Risk_Categories_for_Students"] == "High Threat Crimes")
        & (df["Neighborhood"].isin(neighborhoods))
    ]
    return high_threat.groupby("Neighborhood").size().reset_index(name="crime_count")


# ---------------------------------------------------------------------------
# Figure construction
# ---------------------------------------------------------------------------


def build_campus_scatter_figure(df_nighttime):
    """Animated scatter map of campus-area nighttime incidents by hour."""
    custom_order = list(df_nighttime["Hour_fixed"].cat.categories)

    fig = px.scatter_mapbox(
        df_nighttime,
        lat="YCOORD",
        lon="XCOORD",
        color="Risk_Categories_for_Students",
        hover_name="NIBRS_Offense_Type",
        hover_data={
            "Neighborhood": True,
            "ReportedDate": True,
            "ReportedTime": True,
            "YCOORD": False,
            "XCOORD": False,
            "Hour": False,
        },
        animation_frame="Hour_fixed",
        category_orders={"Hour_fixed": custom_order},
        zoom=13,
        title="Campus Safety Guide: Reported Incidents by Hour and Location",
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

    # "High Threat Crimes" shown by default; other categories togglable via legend.
    for trace in fig.data:
        if trace.name != "High Threat Crimes":
            trace.visible = "legendonly"

    return fig


def build_choropleth_figure(counts_df, geojson_data):
    """Choropleth of raw high-threat incident counts by neighborhood (not normalized)."""
    return px.choropleth_mapbox(
        counts_df,
        geojson=geojson_data,
        locations="Neighborhood",
        featureidkey="properties.hood",
        color="crime_count",
        color_continuous_scale="Reds",
        mapbox_style="carto-positron",
        center={"lat": 40.44, "lon": -79.95},
        zoom=12,
        opacity=1.0,
        title="High-Threat Incident Counts by Neighborhood (raw counts, not population-normalized)",
    )


# ---------------------------------------------------------------------------
# Dash app
# ---------------------------------------------------------------------------


def build_dash_app(scatter_fig, choropleth_fig):
    app = dash.Dash(__name__)

    app.layout = html.Div([
        html.H1("Pittsburgh Crime Risk Dashboard: CMU Student View"),
        html.Div(
            dcc.Graph(
                figure=scatter_fig,
                config={"scrollZoom": True},
                style={"height": "800px", "width": "80%"},
            ),
            style={"display": "flex", "justifyContent": "center"},
        ),
        html.Div(
            dcc.Graph(
                figure=choropleth_fig,
                style={"height": "800px", "width": "80%"},
            ),
            style={"display": "flex", "justifyContent": "center"},
        ),
    ])

    return app


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def load_and_prepare_data():
    """Fetch, validate, and transform crime data. Returns (df, df_nighttime)."""
    raw = fetch_crime_data()
    validate_required_columns(raw, REQUIRED_CRIME_COLUMNS)

    df = preprocess_crime_data(raw)
    df = map_risk_categories(df)
    df_nighttime = filter_campus_nighttime(df)
    return df, df_nighttime


def main():
    df, df_nighttime = load_and_prepare_data()

    scatter_fig = build_campus_scatter_figure(df_nighttime)

    geojson_data = fetch_neighborhood_geojson()
    counts_df = aggregate_high_threat_by_neighborhood(df)
    choropleth_fig = build_choropleth_figure(counts_df, geojson_data)

    app = build_dash_app(scatter_fig, choropleth_fig)
    app.run(debug=True, port=DASH_PORT)


if __name__ == "__main__":
    main()
