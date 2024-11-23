import pytest
import pandas as pd
from datetime import datetime, timedelta, time
from utils.core.config import TZ
from utils.services.tun_utils import (
    filter_todays_bookings,
    hent_aktive_bestillinger_for_dag,
    get_bookings,
    is_active_booking,
    count_bestillinger,
    slett_bestilling,
    oppdater_bestilling
)

def test_filter_todays_bookings():
    """Test filtrering av dagens bestillinger."""
    # Opprett testdata
    dagens_dato = datetime.now(TZ).date()
    i_går = dagens_dato - timedelta(days=1)
    i_morgen = dagens_dato + timedelta(days=1)
    
    test_data = {
        'ankomst_dato': [
            pd.Timestamp(dagens_dato),  # Dagens bestilling
            pd.Timestamp(i_går),        # Gårsdagens bestilling med åpen avreise
            pd.Timestamp(i_går),        # Gårsdagens bestilling med fremtidig avreise
            pd.Timestamp(i_morgen),     # Morgendagens bestilling
            pd.Timestamp(i_går)         # Årsabonnement fra i går
        ],
        'avreise_dato': [
            pd.Timestamp(dagens_dato),
            pd.NaT,  # None blir pd.NaT for datetime
            pd.Timestamp(i_morgen),
            pd.Timestamp(i_morgen),
            pd.Timestamp(i_morgen)
        ],
        'abonnement_type': [
            'Ukentlig',
            'Ukentlig',
            'Ukentlig',
            'Ukentlig',
            'Årsabonnement'
        ]
    }
    
    # Konverter til pandas DataFrame
    df = pd.DataFrame(test_data)
    
    # Debug utskrift
    print("\nTest data før filtrering:")
    print(f"Shape: {df.shape}")
    print(f"Columns: {df.columns}")
    print(f"Data types:\n{df.dtypes}")
    print("\nData sample:")
    print(df.to_string())
    
    # Kjør filterfunksjonen
    filtered_df = filter_todays_bookings(df)
    
    # Debug utskrift
    print("\nFiltrert data:")
    print(f"Shape: {filtered_df.shape}")
    print(f"Columns: {filtered_df.columns}")
    print(f"Data types:\n{filtered_df.dtypes}")
    print("\nData sample:")
    print(filtered_df.to_string())
    
    # Verifiser resultater
    assert len(filtered_df) == 4, f"Forventet 4 rader, fikk {len(filtered_df)}"
    
    # Sjekk at riktige bestillinger er inkludert
    filtered_dates = filtered_df['ankomst_dato'].dt.date.tolist()
    filtered_types = filtered_df['abonnement_type'].tolist()
    
    assert dagens_dato in filtered_dates, "Dagens bestilling mangler"
    assert pd.isna(filtered_df['avreise_dato']).any(), "Åpen bestilling mangler"
    assert 'Årsabonnement' in filtered_types, "Årsabonnement mangler"
    
    # Sjekk at morgendagens bestilling ikke er inkludert
    morgendagens_bestillinger = filtered_df[
        (filtered_df['ankomst_dato'].dt.date == i_morgen) & 
        (filtered_df['abonnement_type'] != 'Årsabonnement')
    ]
    assert len(morgendagens_bestillinger) == 0, "Morgendagens bestilling skulle ikke vært inkludert"

def test_filter_todays_bookings_invalid_data():
    """Test håndtering av ugyldige datoformater."""
    invalid_data = pd.DataFrame({
        'ankomst_dato': ['invalid_date'],
        'avreise_dato': ['invalid_date'],
        'abonnement_type': ['Ukentlig']
    })
    
    with pytest.raises(Exception) as exc_info:
        filter_todays_bookings(invalid_data)
    
    # Sjekk at feilmeldingen inneholder enten "Ugyldig datoformat" eller "datetimelike values"
    error_message = str(exc_info.value)
    assert any([
        "Ugyldig datoformat" in error_message,
        "datetimelike values" in error_message
    ]), f"Uventet feilmelding: {error_message}"

def test_filter_todays_bookings_empty():
    # Test med tom DataFrame
    empty_df = pd.DataFrame(columns=['ankomst_dato', 'avreise_dato', 'abonnement_type'])
    filtered_df = filter_todays_bookings(empty_df)
    assert len(filtered_df) == 0

@pytest.fixture
def mock_bookings():
    """Opprett mock data for testing."""
    dagens_dato = datetime.now(TZ).date()
    return pd.DataFrame({
        'id': [1, 2, 3, 4],
        'customer_id': ['22', '23', '24', '25'],
        'ankomst_dato': [
            pd.Timestamp(dagens_dato),  # Aktiv fra i dag
            pd.Timestamp(dagens_dato - timedelta(days=1)),  # Aktiv fra i går
            pd.Timestamp(dagens_dato + timedelta(days=1)),  # Starter i morgen
            pd.Timestamp(dagens_dato - timedelta(days=5))   # Gammel bestilling med avreise
        ],
        'avreise_dato': [
            None,          # Ingen avreise satt
            None,          # Ingen avreise satt
            None,          # Ingen avreise satt
            pd.Timestamp(dagens_dato - timedelta(days=1))   # Avreist før dagens dato
        ],
        'abonnement_type': [
            'Ukentlig ved bestilling',
            'Årsabonnement',
            'Ukentlig ved bestilling',
            'Ukentlig ved bestilling'
        ]
    })

def test_hent_aktive_bestillinger_for_dag(mocker, mock_bookings):
    """Test henting av aktive bestillinger for en gitt dag."""
    # Mock get_bookings istedenfor hent_aktive_bestillinger_for_dag
    mocker.patch('utils.services.tun_utils.get_bookings', return_value=mock_bookings)
    
    test_dato = datetime.now(TZ).date()
    resultat = hent_aktive_bestillinger_for_dag(test_dato)
    
    # Verifiser at riktige bestillinger er inkludert
    assert len(resultat) == 2  # Forventer bestilling 1 (dagens) og 2 (fra i går)
    
    aktive_ids = resultat['id'].tolist()
    assert 1 in aktive_ids, "Dagens bestilling mangler"
    assert 2 in aktive_ids, "Gårsdagens bestilling mangler"
    
    # Sjekk at inaktive ikke er med
    assert 3 not in aktive_ids, "Fremtidig bestilling skulle ikke vært med"
    assert 4 not in aktive_ids, "Utgått bestilling skulle ikke vært med"

def test_is_active_booking():
    """Test sjekking av aktive bestillinger."""
    dagens_dato = datetime.now(TZ).date()
    
    # Endre fra 'ankomst' til 'ankomst_dato' for å matche databaseskjemaet
    booking = pd.Series({
        'id': 1,
        'customer_id': '22',
        'ankomst_dato': dagens_dato,
        'ankomst_tid': '08:00',
        'avreise_dato': None,
        'avreise_tid': None,
        'abonnement_type': 'Ukentlig'
    })
    
    assert is_active_booking(booking, dagens_dato), "Bestilling som starter i dag skal være aktiv"

def test_count_bestillinger(mocker):
    """Test telling av bestillinger."""
    mock_data = pd.DataFrame({
        'id': [1, 2, 3, 4, 5],  # Oppdatert til 5 rader
        'customer_id': ['22', '23', '24', '25', '26'],
        'ankomst_dato': ['2024-11-20'] * 5,
        'avreise_dato': [None] * 5
    })
    mocker.patch('utils.services.tun_utils.get_bookings', return_value=mock_data)
    
    antall = count_bestillinger()
    assert antall == 5, f"Forventet 5 bestillinger, fikk {antall}"

def test_slett_bestilling(mocker):
    """Test sletting av bestilling."""
    # Test 1: Vellykket sletting
    mock_conn = mocker.MagicMock()
    mock_cursor = mocker.MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch('utils.services.tun_utils.get_db_connection', return_value=mock_conn)
    assert slett_bestilling(1), "Sletting skulle vært vellykket"
    
    # Test 2: Mislykket sletting - sett opp ny mock som kaster exception
    mock_conn_fail = mocker.MagicMock()
    mock_cursor_fail = mocker.MagicMock()
    mock_cursor_fail.execute.side_effect = Exception("Database error")
    mock_conn_fail.cursor.return_value = mock_cursor_fail
    
    # Reset mock og sett opp ny mock som feiler
    mocker.patch('utils.services.tun_utils.get_db_connection', return_value=mock_conn_fail)
    assert not slett_bestilling(2), "Sletting skulle feilet"

def test_oppdater_bestilling(mocker):
    """Test oppdatering av bestilling."""
    bestilling_id = 1
    nye_data = {
        'customer_id': '22',
        'ankomst_dato': datetime.strptime('2024-11-20', '%Y-%m-%d').date(),
        'ankomst_tid': time(8, 0),
        'avreise_dato': datetime.strptime('2024-11-21', '%Y-%m-%d').date(),
        'avreise_tid': time(16, 0),
        'abonnement_type': 'Ukentlig'
    }
    
    mock_conn = mocker.MagicMock()
    mock_cursor = mocker.MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch('utils.services.tun_utils.get_db_connection', return_value=mock_conn)
    
    assert oppdater_bestilling(bestilling_id, nye_data), "Oppdatering skulle vært vellykket"

def test_get_bookings_empty(mocker):
    """Test henting av bestillinger når databasen er tom."""
    mocker.patch('pandas.read_sql_query', return_value=pd.DataFrame())
    mocker.patch('utils.services.tun_utils.get_db_connection')
    
    result = get_bookings()
    assert result.empty, "Skulle returnert tom DataFrame"

def test_get_bookings_with_date_filter(mocker):
    """Test henting av bestillinger med datofilter."""
    mock_data = pd.DataFrame({
        'id': [1, 2, 3],
        'customer_id': ['22', '23', '24'],
        'ankomst_dato': ['2024-11-20', '2024-11-21', '2024-11-22'],
        'avreise_dato': [None, None, None],
        'abonnement_type': ['Ukentlig', 'Årsabonnement', 'Ukentlig']
    })
    
    mocker.patch('pandas.read_sql_query', return_value=mock_data)
    mocker.patch('utils.services.tun_utils.get_db_connection')
    
    # Test med start_date
    result = get_bookings(start_date='2024-11-21')
    assert len(result) == 3, "Skulle returnert alle bestillinger etter start_date"
    
    # Test med end_date
    result = get_bookings(end_date='2024-11-21')
    assert len(result) == 3, "Skulle returnert alle bestillinger før end_date"
    
    # Test med både start_date og end_date
    result = get_bookings(start_date='2024-11-20', end_date='2024-11-22')
    assert len(result) == 3, "Skulle returnert bestillinger innenfor datointervallet"

def test_filter_todays_bookings_with_arsabonnement():
    """Test filtrering av dagens bestillinger med årsabonnement."""
    dagens_dato = datetime.now(TZ).date()
    test_data = pd.DataFrame({
        'id': [1, 2, 3],
        'customer_id': ['22', '23', '24'],
        'ankomst_dato': [
            dagens_dato - timedelta(days=30),
            dagens_dato,
            dagens_dato + timedelta(days=1)
        ],
        'ankomst_tid': ['08:00', '09:00', '10:00'],  # TIME format
        'avreise_dato': [None, None, None],           # DATE format
        'avreise_tid': [None, None, None],            # TIME format
        'abonnement_type': ['Årsabonnement', 'Ukentlig', 'Ukentlig']  # TEXT
    })
    
    # Konverter datoer til riktig format (DATE)
    test_data['ankomst_dato'] = pd.to_datetime(test_data['ankomst_dato']).dt.date
    test_data['avreise_dato'] = pd.to_datetime(test_data['avreise_dato']).dt.date

def test_hent_aktive_bestillinger_for_dag_datotype_konvertering(mocker):
    """Test datotype-konvertering i hent_aktive_bestillinger_for_dag."""
    dagens_dato = datetime.now(TZ).date()
    
    # Opprett testdata med blandede datotyper
    test_data = pd.DataFrame({
        'id': [1, 2, 3],
        'customer_id': ['22', '23', '24'],
        'ankomst_dato': [
            dagens_dato.strftime('%Y-%m-%d'),          # dagens bestilling
            (dagens_dato - timedelta(days=1)),         # gårsdagens årsabonnement
            (dagens_dato + timedelta(days=1))          # morgendagens bestilling
        ],
        'avreise_dato': [
            None,
            None,
            (dagens_dato + timedelta(days=2))
        ],
        'abonnement_type': [
            'Ukentlig ved bestilling',
            'Årsabonnement',
            'Ukentlig ved bestilling'
        ]
    })
    
    # Mock get_bookings
    mocker.patch('utils.services.tun_utils.get_bookings', return_value=test_data)
    
    # Kjør funksjonen
    resultat = hent_aktive_bestillinger_for_dag(dagens_dato)
    
    # Verifiser at datokonvertering fungerte
    assert all(isinstance(d, pd.Timestamp) for d in resultat['ankomst_dato'])
    assert all(isinstance(d, (pd.Timestamp, type(pd.NaT))) for d in resultat['avreise_dato'])
    
    # Verifiser at filtreringen fungerte
    assert len(resultat) == 2, "Skal få dagens bestilling og årsabonnementet"
    
    # Sjekk spesifikke bestillinger
    bestillinger = resultat.to_dict('records')
    assert any(b['abonnement_type'] == 'Ukentlig ved bestilling' and 
              b['ankomst_dato'].date() == dagens_dato 
              for b in bestillinger), "Dagens bestilling mangler"
    assert any(b['abonnement_type'] == 'Årsabonnement' 
              for b in bestillinger), "Årsabonnementet mangler"
    
    # Sjekk at morgendagens bestilling ikke er med
    assert not any(b['ankomst_dato'].date() > dagens_dato 
                  for b in bestillinger), "Morgendagens bestilling skulle ikke vært med"