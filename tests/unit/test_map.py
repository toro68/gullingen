import pytest
from map_utils import vis_dagens_tunkart

def test_map_marker_generation(sample_booking_data):
    """Test at kartmarkører genereres korrekt"""
    markers = vis_dagens_tunkart([sample_booking_data], 'test_token', 'Test Kart')
    
    assert len(markers) > 0
    assert 'latitude' in markers[0]
    assert 'longitude' in markers[0]
    assert markers[0]['color'] is not None

def test_map_empty_bookings():
    """Test karthåndtering uten bookinger"""
    markers = vis_dagens_tunkart([], 'test_token', 'Test Kart')
    assert len(markers) == 0