import logging
import sqlite3
import unittest
from datetime import date, datetime, time, timedelta

from test_config import *
from utils.validation import validate_booking_dates

from utils.db.db_utils import get_db_connection
from utils.services.tun_utils import get_bookings, lagre_bestilling, validere_bestilling

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestIntegration(unittest.TestCase):
    def setUp(self):
        """Sett opp testmiljø"""
        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()
        self.create_test_tables()

        # Monkey patch database connection
        def mock_get_db_connection(*args, **kwargs):
            logger.debug("Using mock database connection")
            return self.conn

        # Patch i begge moduler
        import utils.db.db_utils as db_utils

        db_utils.get_db_connection = mock_get_db_connection

        import utils.services.tun_utils as tun_utils

        tun_utils.get_db_connection = mock_get_db_connection

    def tearDown(self):
        """Rydd opp etter tester"""
        self.conn.close()

    def create_test_tables(self):
        """Opprett testtabeller"""
        self.cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bruker TEXT NOT NULL,
            ankomst_dato DATE NOT NULL,
            ankomst_tid TIME,
            avreise_dato DATE,
            avreise_tid TIME,
            abonnement_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        )
        self.conn.commit()

    def test_full_booking_flow(self):
        """Test hele bestillingsflyten"""
        try:
            # Test validering
            self.assertTrue(validate_booking_dates("2024-03-14", "2024-03-15"))

            # Test lagring med fremtidige datoer
            success = lagre_bestilling(
                TEST_USER,
                "2024-03-14",
                "12:00",
                "2024-03-15",
                "12:00",
                "Ukentlig ved bestilling",
            )
            self.assertTrue(success)

            # Test henting
            bookings = get_bookings()
            logger.debug(f"Hentet bestillinger: {bookings}")
            self.assertGreater(len(bookings), 0)

        except Exception as e:
            logger.error(f"Test feilet: {str(e)}", exc_info=True)
            raise

    def test_invalid_booking_flow(self):
        """Test håndtering av ugyldige bestillinger"""
        # Test validering av datoer først
        with self.assertRaises(ValueError):
            validate_booking_dates("invalid-date", "2024-03-15")

        # Test bestilling med dato i fortiden
        past_date = datetime.now().date() - timedelta(days=1)
        booking_data = {
            "ankomst_dato": past_date,
            "ankomst_tid": time(12, 0),
            "avreise_dato": date.today() + timedelta(days=1),
            "avreise_tid": time(12, 0),
        }
        self.assertFalse(validere_bestilling(booking_data))

        # Test at bestilling med ugyldig dato ikke lagres
        success = lagre_bestilling(
            TEST_USER,
            past_date.isoformat(),
            "12:00",
            (date.today() + timedelta(days=1)).isoformat(),
            "12:00",
            "Ukentlig ved bestilling",
        )
        self.assertFalse(success, "Bestilling med dato i fortiden burde feile")

    def test_booking_update_flow(self):
        """Test oppdatering av eksisterende bestilling"""
        # Først lag en bestilling
        success = lagre_bestilling(
            TEST_USER,
            "2024-03-14",
            "12:00",
            "2024-03-15",
            "12:00",
            "Ukentlig ved bestilling",
        )
        self.assertTrue(success)

        # Hent bestillingen og sjekk detaljer
        bookings = get_bookings(user_id=TEST_USER)
        self.assertEqual(len(bookings), 1)
        self.assertEqual(bookings.iloc[0]["bruker"], TEST_USER)
        self.assertEqual(bookings.iloc[0]["abonnement_type"], "Ukentlig ved bestilling")

    def test_concurrent_booking_flow(self):
        """Test samtidig booking av samme tidspunkt"""
        # Siden SQLite har begrensninger på samtidighet,
        # tester vi bare at vi kan gjøre flere bestillinger etter hverandre
        success1 = lagre_bestilling(
            "test_user_1",
            "2024-03-14",
            "12:00",
            "2024-03-15",
            "12:00",
            "Ukentlig ved bestilling",
        )

        success2 = lagre_bestilling(
            "test_user_2",
            "2024-03-14",
            "12:00",
            "2024-03-15",
            "12:00",
            "Ukentlig ved bestilling",
        )

        self.assertTrue(success1)
        self.assertTrue(success2)

        # Verifiser at begge bestillingene ble lagret
        bookings = get_bookings()
        self.assertEqual(len(bookings), 2)

    def test_booking_deletion_flow(self):
        """Test sletting av bestilling"""
        # Først lag en bestilling
        success = lagre_bestilling(
            TEST_USER,
            "2024-03-14",
            "12:00",
            "2024-03-15",
            "12:00",
            "Ukentlig ved bestilling",
        )
        self.assertTrue(success)

        # Verifiser at bestillingen eksisterer
        bookings_before = get_bookings(user_id=TEST_USER)
        self.assertEqual(len(bookings_before), 1)

        # Slett direkte fra databasen siden slett_bestilling ikke er implementert ennå
        self.cursor.execute(
            """
            DELETE FROM tunbroyting_bestillinger 
            WHERE bruker = ? AND ankomst_dato = ?
        """,
            (TEST_USER, "2024-03-14"),
        )
        self.conn.commit()

        # Verifiser at bestillingen er slettet
        bookings_after = get_bookings(user_id=TEST_USER)
        self.assertEqual(len(bookings_after), 0)
