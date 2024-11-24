import pandas as pd
from datetime import datetime
from freezegun import freeze_time
from utils.core.util_functions import filter_todays_bookings
from utils.core.config import TZ

def test_filter_todays_bookings():
    # Setup test data
    test_data = {
        'id': [1, 2, 3, 4],
        'customer_id': ['101', '102', '103', '104'],
        'ankomst_dato': [
            '2024-02-19 00:00:00+01:00',  # Vanlig bestilling, starter før i dag
            '2024-02-23 00:00:00+01:00',  # Vanlig bestilling, starter i dag
            '2024-02-22 00:00:00+01:00',  # Årsabonnement, startet i går
            '2024-02-24 00:00:00+01:00'   # Vanlig bestilling, starter i morgen
        ],
        'avreise_dato': [
            '2024-02-25 00:00:00+01:00',  # ID 1: ikke aktiv (starter ikke i dag)
            '2024-02-24 00:00:00+01:00',  # ID 2: aktiv (starter i dag)
            None,                          # ID 3: aktiv (årsabonnement)
            '2024-02-26 00:00:00+01:00'   # ID 4: ikke aktiv (starter i morgen)
        ],
        'abonnement_type': [
            'Ukentlig ved bestilling',
            'Ukentlig ved bestilling',
            'Årsabonnement',
            'Ukentlig ved bestilling'
        ]
    }
    df = pd.DataFrame(test_data)
    
    # Test 1: Tom DataFrame
    assert filter_todays_bookings(pd.DataFrame()).empty
    
    # Test 2: Bestillinger på 23. februar
    with freeze_time("2024-02-23 12:00:00+01:00"):
        filtered = filter_todays_bookings(df.copy())
        assert len(filtered) == 2  # Bare ID 2 (starter i dag) og ID 3 (årsabonnement)
        assert sorted(filtered['id'].tolist()) == [2, 3]
    
    # Test 3: Bestillinger på 24. februar
    with freeze_time("2024-02-24 12:00:00+01:00"):
        filtered = filter_todays_bookings(df.copy())
        assert len(filtered) == 2  # Bare ID 4 (starter i dag) og ID 3 (årsabonnement)
        assert sorted(filtered['id'].tolist()) == [3, 4]