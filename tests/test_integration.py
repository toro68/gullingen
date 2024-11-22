import logging
import sqlite3
import pytest
from datetime import datetime, time, timedelta

from conftest import TEST_USER
from utils.core.validation_utils import validere_bestilling
from utils.services.tun_utils import (
    lagre_bestilling,
    get_bookings
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@pytest.fixture
def mock_db_connection():
    """Opprett testdatabase"""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    
    # Opprett testtabeller
    cursor.execute("""
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

    # Monkey patch database connection
    def mock_get_db_connection(*args, **kwargs):
        logger.debug("Using mock database connection")
        return conn

    # Patch begge moduler
    import utils.db.db_utils as db_utils
    import utils.services.tun_utils as tun_utils
    
    db_utils.get_db_connection = mock_get_db_connection
    tun_utils.get_db_connection = mock_get_db_connection
    
    yield conn
    conn.close()

def test_full_booking_flow(mock_db_connection):
    """Test hele bestillingsflyten"""
    booking_data = {
        "ankomst_dato": datetime.now().date(),
        "ankomst_tid": time(12, 0),
        "avreise_dato": (datetime.now() + timedelta(days=1)).date(),
        "avreise_tid": time(12, 0),
    }
    assert validere_bestilling(booking_data)

    success = lagre_bestilling(
        TEST_USER,
        "2024-03-14",
        "12:00",
        "2024-03-15",
        "12:00",
        "Ukentlig ved bestilling",
    )
    assert success

    bookings = get_bookings()
    assert len(bookings) > 0

def test_invalid_booking_flow(mock_db_connection):
    """Test håndtering av ugyldige bestillinger"""
    past_date = datetime.now().date() - timedelta(days=1)
    booking_data = {
        "ankomst_dato": past_date,
        "ankomst_tid": time(12, 0),
        "avreise_dato": datetime.now().date(),
        "avreise_tid": time(12, 0),
    }
    
    with mock_db_connection:  # Bruk context manager
        assert not validere_bestilling(booking_data)
        
        success = lagre_bestilling(
            TEST_USER,
            past_date.isoformat(),
            "12:00",
            datetime.now().date().isoformat(),
            "12:00",
            "Ukentlig ved bestilling"
        )
        assert not success
