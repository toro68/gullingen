import pandas as pd
import plotly.graph_objects as go
import pytest

from utils.services.map_utils import vis_dagens_tunkart


def test_vis_dagens_tunkart():
    """Test visning av dagens tunkart"""
    test_data = pd.DataFrame(
        [
            {
                "bruker": "test_hytte",
                "ankomst": "2024-03-01",
                "avreise": "2024-03-03",
                "abonnement_type": "Ukentlig ved bestilling",
            }
        ]
    )

    mapbox_token = "test_token"
    title = "Test Kart"

    fig = vis_dagens_tunkart(test_data, mapbox_token, title)

    assert isinstance(fig, go.Figure)  # Forvent en Plotly-figur
    assert len(fig.data) > 0  # Sjekk at det er data i figuren

    # Sjekk at markørene har riktig farge og størrelse
    for trace in fig.data:
        assert isinstance(trace, go.Scattermapbox)
        assert len(trace.lat) > 0
        assert len(trace.lon) > 0
        assert all(isinstance(size, int) for size in trace.marker.size)
        assert all(isinstance(color, str) for color in trace.marker.color)
