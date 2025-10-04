import plotly.express as px
import dash
from dash import html, dcc
from dash.dependencies import Input, Output
import dash_leaflet as dl

# API for crime data

import requests
import pandas as pd

resource_id = "bd41992a-987a-4cca-8798-fbe1cd946b07"

# API
url = "https://data.wprdc.org/api/action/datastore_search"

all_records = []
offset = 0
limit = 1000

while True:
    params = {
        "resource_id": resource_id,
        "limit": limit,
        "offset": offset
    }
    r = requests.get(url, params=params).json()
    records = r["result"]["records"]

    if not records:
        break

    all_records.extend(records)
    offset += limit

df_crime = pd.DataFrame(all_records)

#print(f" {len(df_crime)} lens of the data")
#df_crime.head()

# top10 and map
df_crime['ReportedDateTime'] = pd.to_datetime(
    df_crime['ReportedDate'].astype(str) + " " + df_crime['ReportedTime'].astype(str),
    errors='coerce'
)

df_crime['Year'] = df_crime['ReportedDateTime'].dt.year
df_crime['XCOORD'] = pd.to_numeric(df_crime['XCOORD'], errors='coerce')
df_crime['YCOORD'] = pd.to_numeric(df_crime['YCOORD'], errors='coerce')

df_cmu_area = df_crime[
    df_crime['YCOORD'].between(40.440, 40.460) &
    df_crime['XCOORD'].between(-79.970, -79.930)
]


#-----------------------------------------------------------------------------------------
#                                    data preprocessing
#-----------------------------------------------------------------------------------------
# Make a copy for new df
df_lisa = df_crime.copy()

## Explore columns and basic info
# print("Shape:", df_lisa.shape)             # (rows, columns)
# print("Columns:", df_lisa.columns.tolist()) # list of column names
# print(df_lisa.head())                       # first 5 rows

## check data types
# print(df_lisa.dtypes)

# DataFrames used:
# 1. df_lisa: Full dataset with mapped Risk_Categories_for_Students
# 2. df_nearcampus_nighttime: Filtered subset (area: CMU neighborhoods, hour: 5pm–2am)

# New Category based on students' needs
mapping = {
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
    "23F THEFT FROM MOTOR VEHICLE": "Auto & Parking Risks"
}


# Map to dataframe
df_lisa["Risk_Categories_for_Students"] = df_lisa["NIBRS_Coded_Offense"].map(mapping).fillna("Other")


# Whole PGH area -> Only CMU neighborhoods
neighborhoods = [
    "Central Oakland", "East Liberty", "North Oakland", "Oakland", "Shadyside", "Squirrel Hill North", "Squirrel Hill South"
]


# new df: CMU neighborhood and custom time
df_nearcampus_nighttime = df_lisa[
    (df_lisa["Neighborhood"].isin(neighborhoods)) &
    ((df_lisa["Hour"].between(17,23)) |
    (df_lisa["Hour"].between(0,2)))
     ].copy()

# Hour_fixed: change 0,1,2 to 24,25,26
df_nearcampus_nighttime["Hour_fixed"] = df_nearcampus_nighttime["Hour"].apply(
    lambda x: x+24 if x in [0,1,2] else x
)

custom_order = list(range(17,27))

# sort df based on Hour_fixed
df_nearcampus_nighttime = df_nearcampus_nighttime.sort_values("Hour_fixed")


df_nearcampus_nighttime["Hour_fixed"] = pd.Categorical(
    df_nearcampus_nighttime["Hour_fixed"],
    categories=custom_order,
    ordered=True
)

#-----------------------------------------------------------------------------------------
#                                Plot 1: Scatter plot on map
#                campus neighborhood only & risk categories for students
#-----------------------------------------------------------------------------------------
fig_scatter_campusarea = px.scatter_mapbox(
    df_nearcampus_nighttime,
    lat = "YCOORD",
    lon = "XCOORD",
    color = "Risk_Categories_for_Students",
    hover_name = "NIBRS_Offense_Type",
    hover_data = {
        "Neighborhood": True,
        "ReportedDate": True,
        "ReportedTime": True,
        "YCOORD": False,
        "XCOORD": False,
        "Hour": False
    },
    animation_frame = "Hour_fixed",
    category_orders={"Hour_fixed": custom_order},
    zoom = 13,
    title = "Campus Safety Guide: Hourly Student Risk by Location",
    height=800,
    width=1200
)

fig_scatter_campusarea.update_layout(
    mapbox_style="carto-positron",
    mapbox_center={"lat": 40.447766, "lon": -79.937054},
    mapbox_zoom=13,
    dragmode="zoom",  #drag zoom
    hovermode="closest",
    uirevision=True,
    mapbox={"accesstoken": None},   #scroll zoom
    newshape=dict(line_color="cyan"),
    legend=dict(
        orientation="h",  # horizontal
        yanchor="top",
        y=1.05,  # just below the title
        xanchor="center",
        x=0.5
    ),
    margin={"r":0,"t":80,"l":0,"b":20},   # b(아래) 줄여서 슬라이더 위로 당김
    sliders=[dict(pad=dict(b=20, t=0))]   # pad.b 줄이면 지도에 더 붙음
)

# fig_scatter_campusarea.update_layout(mapbox_style="open-street-map")

# "High Threat Crimes" as default
for trace in fig_scatter_campusarea.data:
    if trace.name != "High Threat Crimes":
        trace.visible = "legendonly"

# fig_scatter_campusarea.show()


#-----------------------------------------------------------------------------------------
#                                Plot 2: Choropleth Map
#-----------------------------------------------------------------------------------------

# Get GeoJSON data
url_geojson = "https://data.wprdc.org/dataset/e672f13d-71c4-4a66-8f38-710e75ed80a4/resource/4af8e160-57e9-4ebf-a501-76ca1b42fc99/download/pittsburghpaneighborhoods-.geojson"
geojson_data = requests.get(url_geojson).json()

# Expanded neighborhoods for choropleth
neighborhoods_choroplethmap = [
    "Central Oakland", "North Oakland", "South Oakland", "West Oakland",
    "Shadyside", "Squirrel Hill North", "Squirrel Hill South",
    "Point Breeze", "Bloomfield", "Garfield", "East Liberty",
    "Greenfield", "Polish Hill", "Upper Hill", "Strip District", "Bluff",
    "Bedford Dwellings", "Middle Hill", "Crawford-Roberts",
    "Terrace Village", "Central Business District",
    "Central Lawrenceville", "Friendship", "Lower Lawrenceville",
    "Larimer", "Homewood West", "Homewood North", "Homewood South",
    "Point Breeze North", "Hazelwood", "Glen Hazel"
]

# Filter only High Threat Crimes in those neighborhoods
df_high_threat = df_lisa[
    (df_lisa["Risk_Categories_for_Students"] == "High Threat Crimes") &
    (df_lisa["Neighborhood"].isin(neighborhoods_choroplethmap))
]

# Count crimes by neighborhood
df_counts_high_threat = (
    df_high_threat.groupby("Neighborhood")
    .size()
    .reset_index(name="crime_count")
)

# Choropleth map
fig_choro_high_threat = px.choropleth_mapbox(
    df_counts_high_threat,
    geojson=geojson_data,
    locations="Neighborhood",
    featureidkey="properties.hood",
    color="crime_count",
    color_continuous_scale="Reds",
    mapbox_style="carto-positron",
    center={"lat": 40.44, "lon": -79.95},
    zoom=12,
    opacity=1.0,
    title="Housing Guide: High-Threat Crime Density by Neighborhood",
)

## To show in Jupyter
#fig_choro_high_threat.show()


#-----------------------------------------------------------------------------------------
#                      Dash to show dashboards on the browser
#-----------------------------------------------------------------------------------------
# Dash app
app = dash.Dash(__name__)

# Layout with the figure
app.layout = html.Div([
    html.H1("Pittsburgh Crime Risk Dashboard: CMU Student View"),

    # First plot
    html.Div(
        dcc.Graph(
            figure=fig_scatter_campusarea,
            config = {"scrollZoom": True},
            style = {"height": "800px", "width": "80%"},
    ),
    style={"display": "flex", "justifyContent": "center"}
    ),

    # Second plot
    html.Div(
        dcc.Graph(
            figure=fig_choro_high_threat,
            style={"height": "800px", "width": "80%"}
        ),
        style={"display": "flex", "justifyContent": "center"}
    )
])

# Run server (open in browser at http://127.0.0.1:8053)
if __name__ == "__main__":
    app.run(debug=True, port=8053)


#-----------------------------------------------------------------------------------------