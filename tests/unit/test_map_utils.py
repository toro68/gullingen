import pandas as pd
import plotly.graph_objects as go
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from utils.services.map_utils import (
    vis_dagens_tunkart,
    vis_stroingskart_kommende,
    create_map,
    add_stroing_to_map
)
from utils.core.util_functions import get_date_range

TZ = ZoneInfo("Europe/Oslo")
GULLINGEN_LAT = 59.39210
GULLINGEN_LON = 6.43016

@pytest.fixture
def test_bestillinger():
    """Test data for kartvisning"""
    return pd.DataFrame([
        {
            "customer_id": "test_hytte",
            "ankomst_dato": datetime.now(TZ).date(),
            "avreise_dato": (datetime.now(TZ) + timedelta(days=2)).date(),
            "abonnement_type": "Ukentlig ved bestilling",
            "Latitude": 59.39111,
            "Longitude": 6.42755
        }
    ])

def test_create_map():
    """Test oppretting av basiskart"""
    test_data = [{
        'lat': [59.39111, 59.39222],
        'lon': [6.42755, 6.42866],
        'mode': 'markers',
        'type': 'scattermapbox'
    }]
    
    fig = create_map(test_data, 'test_token', 'Test Kart')
    assert isinstance(fig, go.Figure)
    assert fig.layout.mapbox.style == 'streets'
    assert fig.layout.mapbox.center.lat == GULLINGEN_LAT
    assert fig.layout.mapbox.center.lon == GULLINGEN_LON

def test_vis_stroingskart_kommende(test_bestillinger):
    """Test generering av strøingskart"""
    test_bestillinger['onske_dato'] = datetime.now(TZ).date()
    test_bestillinger['dager_til'] = [0]
    
    fig = vis_stroingskart_kommende(test_bestillinger, 'test_token', 'Test Strøingskart')
    
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0
    assert fig.data[0].marker.color == 'red'

def test_vis_dagens_tunkart(test_bestillinger, mocker):
    """Test visning av dagens tunkart"""
    mock_figure = go.Figure()
    
    # Mock funksjoner
    mocker.patch('utils.services.map_utils.create_map', return_value=mock_figure)
    mocker.patch('utils.services.map_utils.get_cabin_coordinates', 
                return_value={'test_hytte': (59.39111, 6.42755)})
    mocker.patch('utils.services.tun_utils.hent_aktive_bestillinger_for_dag',
                return_value=test_bestillinger)
    
    fig = vis_dagens_tunkart(test_bestillinger, 'test_token', 'Test Kart')
    assert isinstance(fig, go.Figure)