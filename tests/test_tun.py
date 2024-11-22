import pytest
from datetime import datetime, timedelta, time
import pandas as pd
import sqlite3

from conftest import TEST_USER, TEST_TZ
from utils.core.config import DATABASE_PATH, TZ
from utils.core.util_functions import format_norwegian_date, neste_fredag
from utils.services.tun_utils import (
    get_bookings,
    lagre_bestilling,
    hent_aktive_bestillinger_for_dag,
    vis_hyttegrend_aktivitet,
    oppdater_bestilling,
    tunbroyting_kommende_uke
)
from freezegun import freeze_time
from utils.db.db_utils import get_db_connection

@pytest.fixture
def test_bestilling_data():
    """Test data for bestillinger"""
    return {
        "user_id": "test_hytte",
        "ankomst_dato": datetime.now(TZ).date().isoformat(),
        "ankomst_tid": None,
        "avreise_dato": (datetime.now(TZ) + timedelta(days=1)).date().isoformat(),
        "avreise_tid": None,
        "abonnement_type": "Ukentlig ved bestilling"
    }

@pytest.fixture
def mock_db():
    """Setup test database connection"""
    db_path = DATABASE_PATH / "tunbroyting.db"
    conn = sqlite3.connect(str(db_path))
    
    # Opprett tabellen hvis den ikke eksisterer
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
            id INTEGER PRIMARY KEY,
            bruker TEXT,
            ankomst_dato DATE,
            ankomst_tid TIME,
            avreise_dato DATE,
            avreise_tid TIME,
            abonnement_type TEXT
        )
    """)
    conn.commit()
    
    yield conn
    
    # Cleanup
    conn.close()

def test_lagre_bestilling(mock_db, test_bestilling_data):
    """Test lagring av ny bestilling"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    # Bruk neste fredag som dato
    fremtidig_dato = neste_fredag()
    test_data = test_bestilling_data.copy()
    test_data.update({
        "bruker": "test_user_new_booking",
        "ankomst_dato": format_norwegian_date(fremtidig_dato),
        "avreise_dato": format_norwegian_date(fremtidig_dato + timedelta(days=1))
    })
    
    assert lagre_bestilling(**test_data)

def test_get_bookings(mock_db, test_bestilling_data):
    """Test henting av bestillinger"""
    # Lagre testdata først
    lagre_bestilling(**test_bestilling_data)
    
    bestillinger = get_bookings()
    assert isinstance(bestillinger, pd.DataFrame)
    assert len(bestillinger) > 0
    assert "bruker" in bestillinger.columns
    assert "ankomst_dato" in bestillinger.columns

def test_hent_aktive_bestillinger_for_dag(mock_db, test_bestilling_data):
    """Test henting av aktive bestillinger for en spesifikk dag"""
    # Lagre testdata først
    lagre_bestilling(**test_bestilling_data)
    
    dagens_dato = datetime.now(TEST_TZ).date()
    aktive_bestillinger = hent_aktive_bestillinger_for_dag(dagens_dato)
    
    assert isinstance(aktive_bestillinger, pd.DataFrame)
    assert len(aktive_bestillinger) > 0

def test_oppdater_bestilling(mock_db, test_bestilling_data):
    """Test oppdatering av eksisterende bestilling"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    # Bruk neste fredag som dato
    fremtidig_dato = neste_fredag()
    test_data = test_bestilling_data.copy()
    test_data.update({
        "bruker": "test_user_update",
        "ankomst_dato": format_norwegian_date(fremtidig_dato),
        "avreise_dato": format_norwegian_date(fremtidig_dato + timedelta(days=1))
    })
    
    assert lagre_bestilling(**test_data)
    
    bestillinger = get_bookings()
    bestilling_id = bestillinger.iloc[0]["id"]
    
    nye_data = test_data.copy()
    nye_data["avreise_dato"] = format_norwegian_date(fremtidig_dato + timedelta(days=2))
    
    resultat = oppdater_bestilling(bestilling_id, nye_data)
    assert resultat == True

def test_duplicate_booking_prevention(mock_db, test_bestilling_data):
    """Test at samme bruker ikke kan bestille samme dato flere ganger"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    # Bruk en unik bruker og dato
    fremtidig_dato = (datetime.now(TEST_TZ) + timedelta(days=600))
    test_data = test_bestilling_data.copy()
    test_data.update({
        "user_id": "test_user_duplicate_unique",  # Bruk en helt unik bruker
        "ankomst_dato": fremtidig_dato.date().isoformat(),
        "avreise_dato": (fremtidig_dato + timedelta(days=1)).date().isoformat()
    })
    
    # Første bestilling skal lykkes
    assert lagre_bestilling(**test_data) == True
    
    # Andre bestilling på samme dato skal feile
    assert lagre_bestilling(**test_data) == False

def test_invalid_dates(mock_db):
    """Test håndtering av ugyldige datoer"""
    # Tøm databasen først
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    ugyldig_data = {
        "user_id": TEST_USER,
        "ankomst_dato": (datetime.now(TEST_TZ) - timedelta(days=1)).date().isoformat(),
        "ankomst_tid": None,
        "avreise_dato": datetime.now(TEST_TZ).date().isoformat(),
        "avreise_tid": None,
        "abonnement_type": "Ukentlig ved bestilling"
    }
    
    # Bestilling med dato i fortiden skal feile
    assert lagre_bestilling(**ugyldig_data) == False

def test_vis_hyttegrend_aktivitet(mock_db, test_bestilling_data, mocker):
    """Test visning av hyttegrend aktivitet"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    # Mock Streamlit
    for func in ['write', 'dataframe', 'bar_chart', 'title', 'header', 'markdown']:
        mocker.patch(f'streamlit.{func}', side_effect=Exception("Streamlit not initialized"))
    
    # Bruk neste fredag
    fremtidig_dato = neste_fredag()
    test_data = test_bestilling_data.copy()
    test_data.update({
        "bruker": "test_user_activity",
        "ankomst_dato": format_norwegian_date(fremtidig_dato),
        "avreise_dato": format_norwegian_date(fremtidig_dato + timedelta(days=1))
    })
    
    assert lagre_bestilling(**test_data)
    
    with pytest.raises(Exception) as exc_info:
        vis_hyttegrend_aktivitet()
    assert "Streamlit not initialized" in str(exc_info.value)

def test_aktive_bestillinger_filtrering(mock_db):
    """Test filtrering av aktive bestillinger"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    # Bruk neste fredag
    fremtidig_dato = neste_fredag()
    
    aktiv_bestilling = {
        "bruker": "test_user_filter",
        "ankomst_dato": format_norwegian_date(fremtidig_dato),
        "ankomst_tid": None,
        "avreise_dato": format_norwegian_date(fremtidig_dato + timedelta(days=1)),
        "avreise_tid": None,
        "abonnement_type": "Ukentlig ved bestilling"
    }
    
    assert lagre_bestilling(**aktiv_bestilling)
    aktive = hent_aktive_bestillinger_for_dag(fremtidig_dato)
    assert len(aktive) == 1

def test_bestillingsfrist(mock_db):
    """Test at bestillinger etter fristen avvises"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    # Sett opp en dato med frist som har passert
    ankomst_dato = neste_fredag()
    bestillingsfrist = datetime.combine(
        ankomst_dato - timedelta(days=1), 
        time(12, 0)
    ).replace(tzinfo=TEST_TZ)
    
    test_data = {
        "bruker": "test_user_frist",
        "ankomst_dato": format_norwegian_date(ankomst_dato),
        "ankomst_tid": None,
        "avreise_dato": format_norwegian_date(ankomst_dato + timedelta(days=1)),
        "avreise_tid": None,
        "abonnement_type": "Ukentlig ved bestilling"
    }
    
    # Bestilling etter fristen skal feile
    with freeze_time(bestillingsfrist + timedelta(hours=1)):
        assert lagre_bestilling(**test_data) == False

def test_arsabonnement_bestilling(mock_db):
    """Test bestilling med årsabonnement"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    ankomst_dato = neste_fredag()
    test_data = {
        "bruker": "test_user_arsabo",
        "ankomst_dato": format_norwegian_date(ankomst_dato),
        "ankomst_tid": None,
        "avreise_dato": format_norwegian_date(ankomst_dato + timedelta(days=365)),
        "avreise_tid": None,
        "abonnement_type": "Årsabonnement"
    }
    
    assert lagre_bestilling(**test_data) == True

def test_vis_aktivitetsoversikt(mock_db):
    """Test visning av aktivitetsoversikt over 7 dager"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    # Lag bestillinger for flere dager
    start_dato = neste_fredag()
    for i in range(3):
        test_data = {
            "bruker": f"test_user_aktivitet_{i}",
            "ankomst_dato": format_norwegian_date(start_dato + timedelta(days=i)),
            "ankomst_tid": None,
            "avreise_dato": format_norwegian_date(start_dato + timedelta(days=i+1)),
            "avreise_tid": None,
            "abonnement_type": "Ukentlig ved bestilling"
        }
        assert lagre_bestilling(**test_data)
    
    # Test at aktivitetsoversikten viser riktig antall
    df_aktivitet = vis_hyttegrend_aktivitet()
    assert df_aktivitet['antall'].sum() == 3

def test_sortering_bestillinger(mock_db):
    """Test sortering av bestillinger"""
    mock_db.execute("DELETE FROM tunbroyting_bestillinger")
    mock_db.commit()
    
    # Lag flere bestillinger med ulike datoer og brukere
    datoer = [neste_fredag() + timedelta(days=i) for i in range(3)]
    brukere = ["A_bruker", "B_bruker", "C_bruker"]
    
    for dato, bruker in zip(datoer, brukere):
        test_data = {
            "bruker": bruker,
            "ankomst_dato": format_norwegian_date(dato),
            "ankomst_tid": None,
            "avreise_dato": format_norwegian_date(dato + timedelta(days=1)),
            "avreise_tid": None,
            "abonnement_type": "Ukentlig ved bestilling"
        }
        assert lagre_bestilling(**test_data)
    
    # Test sortering etter bruker
    bestillinger = get_bookings().sort_values('bruker')
    assert list(bestillinger['bruker']) == sorted(brukere)

def test_database_initialization():
    """Test at databasen initialiseres korrekt"""
    with get_db_connection("tunbroyting") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='tunbroyting_bestillinger'
        """)
        assert cursor.fetchone() is not None

def test_table_schema():
    """Test at tabellskjemaet er korrekt"""
    with get_db_connection("tunbroyting") as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(tunbroyting_bestillinger)")
        columns = {row[1] for row in cursor.fetchall()}
        
        required_columns = {
            "id", "bruker", "ankomst_dato", "ankomst_tid",
            "avreise_dato", "avreise_tid", "abonnement_type"
        }
        assert required_columns.issubset(columns)

def test_tunbroyting_kommende_uke():
    test_data = pd.DataFrame({
        "bruker": ["test1", "test2", "test3"],
        "ankomst": pd.date_range(start=datetime.now(), periods=3),
        "avreise": pd.date_range(start=datetime.now() + timedelta(days=1), periods=3),
        "abonnement_type": ["Ukentlig ved bestilling", "Årsabonnement", "Ukentlig ved bestilling"]
    })
    
    test_data["ankomst"] = pd.to_datetime(test_data["ankomst"])
    test_data["avreise"] = pd.to_datetime(test_data["avreise"])
    
    filtrerte = tunbroyting_kommende_uke(test_data)
    assert isinstance(filtrerte, pd.DataFrame)
