import pytest
import pandas as pd
from datetime import datetime, timedelta
from utils.core.config import TZ
from utils.services.tun_utils import filter_todays_bookings

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