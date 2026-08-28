"""Data fetching, cleaning, and incident-modeling for the crime dashboard.

Turns raw WPRDC police-blotter offense rows into two clean tables:

- an incident table (one row per Report_Number)
- an incident-category bridge table (one row per Report_Number x category)

See README.md for the full methodology and its limitations.
"""

import warnings

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CRIME_RESOURCE_ID = "bd41992a-987a-4cca-8798-fbe1cd946b07"
POPULATION_RESOURCE_ID = "a8414ed5-c50f-417e-bb67-82b734660da6"
DATASTORE_SEARCH_URL = "https://data.wprdc.org/api/action/datastore_search"
NEIGHBORHOODS_GEOJSON_URL = (
    "https://data.wprdc.org/dataset/e672f13d-71c4-4a66-8f38-710e75ed80a4/"
    "resource/4af8e160-57e9-4ebf-a501-76ca1b42fc99/download/"
    "pittsburghpaneighborhoods-.geojson"
)

PAGE_LIMIT = 1000
MAX_PAGES = 1000  # safety net against a runaway/looping pagination, not an expected limit
REQUEST_TIMEOUT_SECONDS = 30

# Fixed 24-month analysis window. Kept fixed (not "most recent N months") so
# results are reproducible across runs. See README.md "Methodology".
ANALYSIS_START = "2024-07-01"
ANALYSIS_END = "2026-06-30"
ANALYSIS_YEARS = 2.0

REQUIRED_CRIME_COLUMNS = [
    "_id",
    "Report_Number",
    "ReportedDate",
    "ReportedTime",
    "Hour",
    "Zone",
    "XCOORD",
    "YCOORD",
    "NIBRS_Offense_Code",
    "NIBRS_Coded_Offense",
    "Neighborhood",
]

REQUIRED_POPULATION_COLUMNS = ["Neighborhood", "2020_Total_Population"]

# ---------------------------------------------------------------------------
# Offense-code normalization
#
# NIBRS_Offense_Code is a cleaner join key than the free-text
# NIBRS_Coded_Offense description: 58 distinct raw values, verified 1:1 with
# descriptions, versus a handful of truncated/blank variants. This map fixes
# those known truncations; anything still null becomes "UNKNOWN".
# ---------------------------------------------------------------------------

OFFENSE_CODE_FIXES = {
    "DIS": "90C",   # Disorderly Conduct
    "SIM": "13B",   # Simple Assault
    "THE": "23G",   # Theft of Motor Vehicle Parts or Accessories
    "Veh": "9999",  # Vehicle Offense (Not NIBRS Reportable)
    "999": "9999",  # Vehicle Offense (Not NIBRS Reportable)
}

UNKNOWN_OFFENSE_CODE = "UNKNOWN"

# ---------------------------------------------------------------------------
# Student-oriented offense taxonomy (heuristic, not an official NIBRS
# severity classification -- see README.md "Methodology").
# ---------------------------------------------------------------------------

CATEGORY_CODES = {
    "High Threat": {
        "09A", "09B",              # murder, negligent manslaughter
        "11A", "11B", "11C", "11D",  # forcible sex offenses
        "36A", "36B",              # incest, statutory rape
        "64A", "64B",              # commercial sex acts, involuntary servitude
        "100",                     # kidnapping/abduction
        "120",                     # robbery
        "13A",                     # aggravated assault
        "520",                     # weapon law violations
    },
    "Property & Theft": {
        "220",  # burglary/breaking and entering
        "23D",  # theft from buildings
        "290",  # destruction/damage/vandalism of property
        "200",  # arson
        "23H",  # all other larceny (a broad NIBRS catch-all category, not
                # necessarily residential -- see README.md "Methodology")
        "210",  # extortion/blackmail
    },
    "Everyday Risks": {
        "13B", "13C",       # simple assault, intimidation
        "23A", "23B",       # pocket picking, purse snatching
        "90C", "90E",       # disorderly conduct, drunkenness
        "90J",               # trespass of real property
    },
    "Auto & Parking": {
        "240",  # motor vehicle theft
        "23F",  # theft from motor vehicle
        "23G",  # theft of motor vehicle parts or accessories
    },
}

STUDENT_CATEGORY_NAMES = tuple(CATEGORY_CODES)
ALL_STUDENT_RELEVANT_LABEL = "All student-relevant incidents"

ALL_CATEGORY_CODES = set().union(*CATEGORY_CODES.values())

# Not valid crime observations: administrative/non-NIBRS records or codes we
# could not resolve to a description.
EXCLUDED_ADMINISTRATIVE_CODES = {
    "9999",  # Vehicle Offense (Not NIBRS Reportable) -- administrative, non-NIBRS
    "90Z",   # All Other Offenses -- uninterpretable catch-all
    UNKNOWN_OFFENSE_CODE,
}

# Real, validly reported offenses that are deliberately outside this
# product's student-safety scope. These are NOT administrative/invalid
# records -- see README.md "Methodology" for the exclusion rationale.
OUT_OF_SCOPE_CODES = {
    "35A", "35B",                                   # drug/narcotic offenses
    "40A", "40B", "370",                             # vice
    "26A", "26B", "26C", "26D", "26G", "250", "270", "280", "510",  # fraud/financial
    "23C", "23E",                                    # shoplifting, coin-op device theft
    "90A", "90B", "90D", "90F", "90G", "90H",        # other Group B offenses
}

# ---------------------------------------------------------------------------
# Neighborhoods immediately around CMU, used only for the campus-focused
# nighttime scatter map (not the city-wide choropleth).
# ---------------------------------------------------------------------------

CAMPUS_NEIGHBORHOODS = [
    "Central Oakland",
    "North Oakland",
    "South Oakland",
    "West Oakland",
    "East Liberty",
    "Shadyside",
    "Squirrel Hill North",
    "Squirrel Hill South",
]

NIGHTTIME_HOUR_RANGES = ((17, 23), (0, 2))

# ---------------------------------------------------------------------------
# Neighborhood name aliases. WPRDC's crime, geography, and population
# resources spell a handful of neighborhoods differently (including two
# neighborhoods that appear with both an en dash and a hyphen within the
# crime dataset itself). Canonical form is the crime dataset's spelling.
# ---------------------------------------------------------------------------

NEIGHBORHOOD_ALIASES = {
    "Mt. Oliver": "Mount Oliver",
    "Central Business District (Downtown)": "Central Business District",
    "Spring Hill-City": "Spring Hill-City View",
    "Lincoln–Lemington–Belmar": "Lincoln-Lemington-Belmar",  # en dash variant
    "Spring Hill–City View": "Spring Hill-City View",             # en dash variant
}


def canonicalize_neighborhood_names(series):
    """Apply NEIGHBORHOOD_ALIASES to a Neighborhood column. Idempotent."""
    return series.replace(NEIGHBORHOOD_ALIASES)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _fetch_datastore_records(resource_id, context, api_url=DATASTORE_SEARCH_URL,
                              page_limit=PAGE_LIMIT, max_pages=MAX_PAGES,
                              timeout=REQUEST_TIMEOUT_SECONDS):
    """Fetch all records for a WPRDC CKAN datastore resource via paginated requests.

    Raises RuntimeError on network failure, a non-200 response, an API-level
    failure, or if pagination does not terminate within max_pages (a safety
    net, not an expected code path). Returns a list of record dicts.
    """
    all_records = []
    offset = 0

    for _ in range(max_pages):
        params = {"resource_id": resource_id, "limit": page_limit, "offset": offset}
        try:
            response = requests.get(api_url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to reach {context} at {api_url}: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"{context} returned HTTP {response.status_code} for offset {offset}: "
                f"{response.text[:200]}"
            )

        payload = response.json()
        if not payload.get("success", False):
            raise RuntimeError(f"{context} reported failure: {payload.get('error', payload)}")

        records = payload["result"]["records"]
        if not records:
            break

        all_records.extend(records)
        offset += page_limit
    else:
        raise RuntimeError(
            f"Reached max_pages={max_pages} while paginating {context} without the "
            "result set ending; aborting instead of returning incomplete data."
        )

    return all_records


def fetch_crime_data(resource_id=CRIME_RESOURCE_ID, **kwargs):
    """Fetch all police-blotter offense records. Raises RuntimeError if empty."""
    records = _fetch_datastore_records(resource_id, context="WPRDC crime data API", **kwargs)
    if not records:
        raise RuntimeError("WPRDC API returned no crime records.")
    return pd.DataFrame(records)


def fetch_neighborhood_population(resource_id=POPULATION_RESOURCE_ID, **kwargs):
    """Fetch 2020 Census neighborhood population. Raises RuntimeError if empty."""
    records = _fetch_datastore_records(
        resource_id, context="WPRDC neighborhood population API", **kwargs
    )
    if not records:
        raise RuntimeError("WPRDC API returned no neighborhood population records.")
    df = pd.DataFrame(records)
    validate_required_columns(df, REQUIRED_POPULATION_COLUMNS, context="neighborhood population data")
    df = df[["Neighborhood", "2020_Total_Population"]].rename(
        columns={"2020_Total_Population": "population_2020"}
    )
    df["Neighborhood"] = canonicalize_neighborhood_names(df["Neighborhood"])
    df["population_2020"] = pd.to_numeric(df["population_2020"], errors="coerce")
    return df.drop_duplicates(subset="Neighborhood")


def fetch_neighborhood_geojson(url=NEIGHBORHOODS_GEOJSON_URL, timeout=REQUEST_TIMEOUT_SECONDS):
    """Fetch the Pittsburgh neighborhood boundary GeoJSON."""
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to reach neighborhood GeoJSON source at {url}: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(f"GeoJSON request returned HTTP {response.status_code}: {url}")

    return response.json()


def extract_neighborhood_areas(geojson_data):
    """Extract (Neighborhood, sqmiles) from the neighborhood GeoJSON's properties.

    Also canonicalizes `properties.hood` on each feature IN PLACE (mutating
    geojson_data), since figures.build_choropleth_figure later matches
    rate-table neighborhood names against this same GeoJSON object via
    `featureidkey="properties.hood"`. Without this, any aliased neighborhood
    (e.g. "Mt. Oliver") would have a canonical name in the rate table but a
    raw spelling in the GeoJSON, and its polygon would silently fail to
    render.
    """
    for feature in geojson_data["features"]:
        hood = feature["properties"]["hood"]
        feature["properties"]["hood"] = NEIGHBORHOOD_ALIASES.get(hood, hood)

    rows = [
        (feature["properties"]["hood"], feature["properties"]["sqmiles"])
        for feature in geojson_data["features"]
    ]
    areas = pd.DataFrame(rows, columns=["Neighborhood", "sqmiles"])
    return areas.drop_duplicates(subset="Neighborhood")


def validate_required_columns(df, required_columns, context="data"):
    """Raise ValueError with a useful message if any required column is missing."""
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"{context} is missing required column(s): {missing}. "
            f"Available columns: {list(df.columns)}"
        )


# ---------------------------------------------------------------------------
# Cleaning / windowing
# ---------------------------------------------------------------------------


def preprocess_crime_data(df):
    """Parse report timestamp/coordinates into usable dtypes, and canonicalize
    Neighborhood spellings (the crime dataset itself carries both an en dash
    and a hyphen variant for at least two neighborhoods -- see
    NEIGHBORHOOD_ALIASES). Without this, those rows fail to join against the
    canonicalized area/population tables in compute_rates and are silently
    dropped from every downstream rate. Returns a copy.
    """
    df = df.copy()
    df["ReportedDateTime"] = pd.to_datetime(
        df["ReportedDate"].astype(str) + " " + df["ReportedTime"].astype(str),
        errors="coerce",
    )
    df["XCOORD"] = pd.to_numeric(df["XCOORD"], errors="coerce")
    df["YCOORD"] = pd.to_numeric(df["YCOORD"], errors="coerce")
    df["Neighborhood"] = canonicalize_neighborhood_names(df["Neighborhood"])
    return df


def normalize_offense_codes(df):
    """Add an OffenseCode column: NIBRS_Offense_Code with known truncations
    fixed and nulls set to UNKNOWN_OFFENSE_CODE."""
    df = df.copy()
    code = df["NIBRS_Offense_Code"].replace(OFFENSE_CODE_FIXES)
    df["OffenseCode"] = code.fillna(UNKNOWN_OFFENSE_CODE)
    return df


def filter_analysis_window(df, start=ANALYSIS_START, end=ANALYSIS_END):
    """Filter to reports dated within the fixed analysis window (inclusive)."""
    report_date = pd.to_datetime(df["ReportedDate"], errors="coerce")
    mask = report_date.between(pd.Timestamp(start), pd.Timestamp(end))
    return df[mask].copy()


def drop_records_without_report_number(df):
    """Drop offense rows with a missing Report_Number.

    A small number of raw records (2 of 101,562 as of this writing) have no
    Report_Number. Since Report_Number is the primary key for every
    incident-level operation in this module (dedup, grouping, joins), these
    rows cannot be attributed to an incident and must be dropped rather than
    silently grouped together by pandas' NaN-key handling, which would
    fabricate a phantom "incident" out of unrelated offenses.
    """
    missing = df["Report_Number"].isna()
    if missing.any():
        warnings.warn(
            f"Dropping {missing.sum()} offense row(s) with a missing Report_Number; "
            "these cannot be attributed to an incident."
        )
    return df[~missing].copy()


# ---------------------------------------------------------------------------
# Offense classification
# ---------------------------------------------------------------------------


def categorize_offense_code(code):
    """Return the single student-oriented category name for a code, or None
    if the code is not in any category (excluded or out of scope)."""
    for name, codes in CATEGORY_CODES.items():
        if code in codes:
            return name
    return None


def classify_offense_scope(code):
    """Classify a single offense code into one of three mutually exclusive
    scopes: "student_relevant", "out_of_scope", or "administrative"."""
    if code in ALL_CATEGORY_CODES:
        return "student_relevant"
    if code in OUT_OF_SCOPE_CODES:
        return "out_of_scope"
    if code in EXCLUDED_ADMINISTRATIVE_CODES:
        return "administrative"
    warnings.warn(f"Unrecognized offense code {code!r}; treating as administrative.")
    return "administrative"


_SCOPE_PRIORITY = {"student_relevant": 0, "out_of_scope": 1, "administrative": 2}


def compute_incident_coverage_status(df):
    """Compute one mutually exclusive coverage status per Report_Number:

    "student_relevant"  -- at least one offense belongs to an included category
    "out_of_scope"       -- no student-relevant offense, but at least one
                             validly reported out-of-scope offense
    "administrative"     -- neither of the above (administrative/unknown only)

    This status is for the coverage audit only. It must not be used to
    restrict or dedupe category-specific analyses, which count a
    Report_Number once per category independently (see
    build_incident_category_bridge).
    """
    scope = df["OffenseCode"].map(classify_offense_scope)
    working = df.assign(_scope=scope, _priority=scope.map(_SCOPE_PRIORITY))
    working = working.sort_values("_priority")
    status = working.groupby("Report_Number")["_scope"].first()
    return status.rename("coverage_status")


# ---------------------------------------------------------------------------
# Incident-level data model
# ---------------------------------------------------------------------------


def build_incident_table(df):
    """Build one row per Report_Number from offense-level rows.

    Canonical record = earliest ReportedDateTime for that Report_Number
    (ties broken by lowest _id). Neighborhood/date/time/hour/zone come from
    the canonical row.

    Coordinates: the canonical row's coordinates if present; otherwise the
    earliest later row for the same Report_Number that shares the canonical
    Neighborhood and has non-null coordinates; otherwise left missing.
    Coordinates are never taken from a row in a different neighborhood than
    the canonical one, since that would relocate the incident.
    """
    # NOTE: GroupBy.first() takes the first *non-null value per column*
    # independently, not the literal first row -- with sparse coordinate
    # data that silently mixes fields from different offense rows of the
    # same incident. drop_duplicates(keep="first") on a presorted frame
    # gives unambiguous "first row per group" semantics instead.
    ordered = df.sort_values(["Report_Number", "ReportedDateTime", "_id"])
    canonical = ordered.drop_duplicates(subset="Report_Number", keep="first")

    canonical_hoods = canonical[["Report_Number", "Neighborhood"]].rename(
        columns={"Neighborhood": "_canonical_neighborhood"}
    )
    merged = ordered.merge(canonical_hoods, on="Report_Number")
    same_hood_with_coords = merged[
        (merged["Neighborhood"] == merged["_canonical_neighborhood"])
        & merged["XCOORD"].notna()
        & merged["YCOORD"].notna()
    ]
    fallback_coords = (
        same_hood_with_coords.drop_duplicates(subset="Report_Number", keep="first")
        [["Report_Number", "XCOORD", "YCOORD"]]
        .rename(columns={"XCOORD": "_fallback_x", "YCOORD": "_fallback_y"})
    )

    n_offenses = df.groupby("Report_Number").size().rename("n_offenses")

    incidents = canonical.merge(fallback_coords, on="Report_Number", how="left")
    incidents["XCOORD"] = incidents["XCOORD"].where(incidents["XCOORD"].notna(), incidents["_fallback_x"])
    incidents["YCOORD"] = incidents["YCOORD"].where(incidents["YCOORD"].notna(), incidents["_fallback_y"])
    incidents = incidents.merge(n_offenses, on="Report_Number")

    keep = [
        "Report_Number", "Neighborhood", "ReportedDate", "ReportedTime",
        "ReportedDateTime", "Hour", "Zone", "XCOORD", "YCOORD", "n_offenses",
    ]
    return incidents[keep].reset_index(drop=True)


def compute_hour_fixed(hour_series):
    """Shift 0/1/2 AM hours to 24/25/26 so a 5pm-2am nighttime window sorts contiguously."""
    return hour_series.apply(lambda h: h + 24 if h in (0, 1, 2) else h)


def build_incident_category_bridge(df):
    """Build the incident-category bridge: one row per (Report_Number, category)
    for every student-relevant category present among that incident's
    offenses. An incident with offenses in two categories produces two rows
    here -- category membership is intentionally overlapping. Category
    totals from this table are not expected to sum to the total number of
    incidents.
    """
    category = df["OffenseCode"].map(categorize_offense_code)
    in_scope = df.assign(category=category)
    in_scope = in_scope[in_scope["category"].notna()]
    bridge = in_scope[["Report_Number", "category"]].drop_duplicates().reset_index(drop=True)
    return bridge


def build_campus_nighttime_points(incidents, bridge, neighborhoods=CAMPUS_NEIGHBORHOODS):
    """One point per (Report_Number, category) for the campus-area nighttime
    scatter map, built from the incident table and incident-category bridge
    -- the same overlapping-category counting model used everywhere else in
    this module, not raw offense rows. Concretely: multiple offenses from
    the same incident within the same category collapse to a single point;
    an incident spanning multiple categories contributes one point per
    represented category. Adds an ordered `Hour_fixed` column (17..26) for
    animation-frame ordering.
    """
    points = bridge.merge(incidents, on="Report_Number", how="inner")

    (start1, end1), (start2, end2) = NIGHTTIME_HOUR_RANGES
    nighttime_mask = points["Hour"].between(start1, end1) | points["Hour"].between(start2, end2)
    filtered = points[points["Neighborhood"].isin(neighborhoods) & nighttime_mask].copy()

    filtered["Hour_fixed"] = compute_hour_fixed(filtered["Hour"])
    custom_order = list(range(start1, end2 + 24 + 1))
    filtered = filtered.sort_values("Hour_fixed")
    filtered["Hour_fixed"] = pd.Categorical(
        filtered["Hour_fixed"], categories=custom_order, ordered=True
    )
    return filtered
