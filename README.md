# Pittsburgh Crime Risk Dashboard: CMU Student View

An interactive [Dash](https://dash.plotly.com/) app that visualizes **reported
police incidents** in Pittsburgh, regrouped into a heuristic, student-oriented
set of categories and focused on the neighborhoods around Carnegie Mellon
University.

> **What this is:** a descriptive visualization of reported-incident data,
> built to explore patterns in *when* and *where* incidents are reported near
> campus.
>
> **What this is not:** a prediction of crime, a measure of the probability
> that any individual will be a victim, or a validated risk score. See
> [Limitations](#limitations) below before drawing conclusions from it.

## What it does

- Pulls all records from the City of Pittsburgh's police blotter dataset via
  the [WPRDC](https://data.wprdc.org/) open-data API.
- Regroups raw NIBRS offense codes into three custom, student-oriented
  buckets (`High Threat Crimes`, `Everyday Risks`, `Auto & Parking Risks`)
  plus `Other`.
- Renders two maps in a single-page Dash app:
  1. **Animated scatter map** — incidents reported in the CMU-adjacent
     neighborhoods between 5pm and 2am, with an hour-by-hour animation slider.
  2. **Choropleth map** — a city-wide count of `High Threat Crimes` incidents
     per neighborhood.

## Screenshots

_Add screenshots or a short screen recording of the running app here._

## Data source

- **Incidents:** [Pittsburgh Police Blotter (Reported Crime Data)](https://data.wprdc.org/),
  resource ID `bd41992a-987a-4cca-8798-fbe1cd946b07`, queried via the
  `datastore_search` API action. This dataset begins in 2024.
- **Neighborhood boundaries:** Pittsburgh neighborhood GeoJSON, also hosted on
  WPRDC.

Both sources are fetched live over HTTP each time the app starts; there is no
local copy or cache of the data in this repository.

## Architecture / workflow

Everything lives in `pittsburgh-crime-dashboard/crime_dashboard.py`, organized
as a small pipeline of functions (no classes, no framework beyond Dash/Plotly
— deliberately kept simple):

```
fetch_crime_data()              -- paginated HTTP pull from the WPRDC API
  -> validate_required_columns()-- fail fast with a clear error if the schema changes
  -> preprocess_crime_data()    -- parse timestamps, coerce coordinate dtypes
  -> map_risk_categories()      -- apply the heuristic offense -> category mapping
  -> filter_campus_nighttime()  -- subset to CMU-adjacent neighborhoods + nighttime hours
  -> build_campus_scatter_figure()

fetch_neighborhood_geojson()    -- separate HTTP pull for neighborhood boundaries
  -> aggregate_high_threat_by_neighborhood()
  -> build_choropleth_figure()

build_dash_app(scatter_fig, choropleth_fig)  -- assembles the Dash layout
main()                                       -- runs the pipeline above, then app.run()
```

Network requests only happen inside `main()` (via `load_and_prepare_data()`
and `fetch_neighborhood_geojson()`) — importing the module does not trigger
any HTTP calls, which keeps it testable.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running the app

```bash
cd pittsburgh-crime-dashboard
python crime_dashboard.py
```

Then open http://127.0.0.1:8053 in a browser. Startup takes roughly 20-30
seconds while the full incident dataset is downloaded and processed.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests cover the pure data-transformation logic (category mapping, the
0/1/2am hour-shift, campus/nighttime filtering, schema validation, and
aggregation) plus the API-fetching functions with `requests` mocked — no test
depends on the live API.

## Methodology

- **Offense categories are a custom heuristic, not an official
  classification.** `OFFENSE_CATEGORY_MAP` in `crime_dashboard.py` is a
  manually authored regrouping of specific NIBRS offense codes into
  `High Threat Crimes`, `Everyday Risks`, and `Auto & Parking Risks`, chosen
  to reflect what a student might reasonably care about (e.g., grouping
  robbery and weapons violations together). It is **not** a NIBRS severity
  classification, has not been validated against any external standard, and
  any offense code not explicitly listed falls into `Other`.
- **The nighttime scatter map and the choropleth use intentionally different
  neighborhood scopes.** The scatter map is restricted to 7 neighborhoods
  immediately adjacent to CMU (`CAMPUS_NEIGHBORHOODS`); the choropleth covers
  a much wider set of 31 neighborhoods across the city (`CHOROPLETH_NEIGHBORHOODS`).
  This is a carry-over from the original exploratory version of this project
  and has not been reconciled — treat the two maps as answering different
  questions ("what does a campus-adjacent night look like?" vs. "where in
  the city are high-threat incidents reported most often?"), not as two
  views of the same scope.
- **The choropleth shows raw incident counts, not a density or rate.** Counts
  are not normalized by neighborhood population, area, or any exposure
  measure, so neighborhoods are **not directly comparable** on this map — a
  neighborhood with more reported incidents is not necessarily more
  dangerous per resident or per visit; it may simply be larger, denser, or
  more heavily trafficked.
- **"Hour" is taken directly from the source dataset**, not derived from the
  report timestamp in this code.

## Limitations

- **Reported incidents, not actual crime or risk.** This dashboard visualizes
  *reported* police incidents. It says nothing about unreported incidents,
  and it is **not** a measure of the probability that any individual —
  student or otherwise — will experience a crime at a given place or time.
- **No statistical validation.** Patterns shown (e.g., which hours or
  neighborhoods have more incidents) have not been tested for statistical
  significance and may reflect small sample sizes, reporting patterns, or
  seasonal effects rather than an underlying risk difference.
- **No normalization.** As noted above, the choropleth's raw counts are not
  adjusted for population, foot traffic, or area, so cross-neighborhood
  comparisons should not be treated as apples-to-apples.
- **No predictive modeling.** This is a descriptive visualization, not a
  forecast or risk score.
- **Live, uncached, single-snapshot data.** Each run re-downloads the entire
  dataset; there is no historical versioning, scheduled refresh, or offline
  fallback if the WPRDC API is unavailable.
- **Schema dependency on the upstream dataset.** The app assumes the raw API
  response includes specific columns (see `REQUIRED_CRIME_COLUMNS` in
  `crime_dashboard.py`); if WPRDC changes its schema, the app will fail fast
  with a validation error rather than silently producing wrong output.

These normalization, statistical-inference, and predictive-modeling gaps are
intentionally out of scope for this phase of the project and are being
addressed as a separate follow-up.

## License

MIT — see [LICENSE](LICENSE).
