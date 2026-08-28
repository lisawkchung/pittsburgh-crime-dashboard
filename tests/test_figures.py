import pandas as pd

import figures as fg


def _sample_rate_table():
    return pd.DataFrame({
        "Neighborhood": ["Oakland"],
        "incidents": [10],
        "sqmiles": [1.0],
        "population_2020": [1000.0],
        "density_sqmi": [5.0],
        "density_pop": [5.0],
        "raw_count": [10.0],
    })


def _sample_geojson():
    return {"features": [{
        "properties": {"hood": "Oakland", "sqmiles": 1.0},
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
    }]}


def test_choropleth_raw_count_hover_omits_redundant_incidents_field():
    # Regression test: raw_count IS incidents (see analysis.compute_rates),
    # so showing both in the hover tooltip renders the same value twice.
    fig = fg.build_choropleth_figure(_sample_rate_table(), _sample_geojson(), "raw_count", "High Threat")
    assert "incidents" not in fig.data[0].hovertemplate.lower()


def test_choropleth_density_hover_includes_incidents_for_context():
    fig = fg.build_choropleth_figure(_sample_rate_table(), _sample_geojson(), "density_sqmi", "High Threat")
    assert "incidents" in fig.data[0].hovertemplate.lower()
