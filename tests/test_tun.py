import sqlite3
import unittest
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytz

# Import funksjoner som skal testes
from utils.services.tun_utils import (
    filter_bookings_for_period,
    filter_todays_bookings,
    hent_bestillinger,
    hent_bruker_bestillinger,
    lagre_bestilling,
)


class TestTunUtils(unittest.TestCase):
    def setUp(self):
        """Sett opp testmiljø med en in-memory database"""
        # Opprett en in-memory database connection
        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()

        # Opprett testdatabase med samme schema som tunbroyting.db
        self.cursor.execute(
            """
            CREATE TABLE tunbroyting_bestillinger (
                id INTEGER PRIMARY KEY,
                bruker TEXT,
                ankomst_dato DATE,
                ankomst_tid TIME,
                avreise_dato DATE,
                avreise_tid TIME,
                abonnement_type TEXT
            )
        """
        )

        # Monkey patch get_db_connection i tun_utils
        from utils.services.tun_utils import (
            get_db_connection as original_get_db_connection,
        )

        def mock_get_db_connection(*args, **kwargs):
            return self.conn

        import utils.services.tun_utils as tun_utils

        tun_utils.get_db_connection = mock_get_db_connection

        # Sett opp noen testdata
        self.test_user = "TEST123"
        self.tz = ZoneInfo("Europe/Oslo")
        self.today = datetime.now(self.tz).date()

    def tearDown(self):
        """Rydd opp etter testene"""
        self.conn.close()

    def test_lagre_bestilling(self):
        """Test at bestillinger lagres korrekt"""
        # Test lagring av ukentlig bestilling
        success = lagre_bestilling(
            self.test_user,
            self.today.isoformat(),
            time(12, 0).isoformat(),
            None,
            None,
            "Ukentlig ved bestilling",
        )
        self.assertTrue(success)

        # Verifiser at bestillingen ble lagret
        self.cursor.execute(
            "SELECT * FROM tunbroyting_bestillinger WHERE bruker = ?", (self.test_user,)
        )
        result = self.cursor.fetchone()
        self.assertIsNotNone(result)
        self.assertEqual(result[1], self.test_user)

    def test_hent_bestillinger(self):
        """Test at alle bestillinger hentes korrekt"""
        # Legg inn testdata først
        self.cursor.execute(
            """
            INSERT INTO tunbroyting_bestillinger 
            (bruker, ankomst_dato, ankomst_tid, abonnement_type)
            VALUES (?, ?, ?, ?)
        """,
            (
                self.test_user,
                self.today.isoformat(),
                "12:00",
                "Ukentlig ved bestilling",
            ),
        )
        self.conn.commit()

        # Hent bestillinger
        bestillinger = hent_bestillinger()

        # Sjekk at dataene er returnert som forventet
        self.assertFalse(bestillinger.empty)
        self.assertEqual(len(bestillinger), 1)
        self.assertEqual(bestillinger.iloc[0]["bruker"], self.test_user)

    def test_filter_todays_bookings(self):
        """Test filtering av dagens bestillinger"""
        # Opprett testdata for i dag
        today_data = pd.DataFrame(
            {
                "bruker": [self.test_user],
                "ankomst": [pd.Timestamp.now(self.tz)],
                "avreise": [pd.Timestamp.now(self.tz) + pd.Timedelta(days=1)],
                "abonnement_type": ["Ukentlig ved bestilling"],
            }
        )

        # Test filtering
        filtered = filter_todays_bookings(today_data)

        # Sjekk at dagens bestilling er med i resultatet
        self.assertFalse(filtered.empty)
        self.assertEqual(len(filtered), 1)

        # Test at årsabonnement vises på fredager
        if datetime.now(self.tz).weekday() == 4:  # Fredag
            yearly_data = pd.DataFrame(
                {
                    "bruker": [self.test_user],
                    "ankomst": [pd.Timestamp.now(self.tz)],
                    "avreise": [pd.Timestamp.now(self.tz) + pd.Timedelta(days=1)],
                    "abonnement_type": ["Årsabonnement"],
                }
            )
            filtered = filter_todays_bookings(yearly_data)
            self.assertEqual(len(filtered), 1)

    def test_filter_bookings_for_period(self):
        """Test filtering av bestillinger for en periode"""
        start_date = self.today
        end_date = self.today + timedelta(days=7)

        # Opprett testdata
        test_data = pd.DataFrame(
            {
                "bruker": [self.test_user],
                "ankomst": [pd.Timestamp(start_date, tz=self.tz)],
                "avreise": [pd.Timestamp(end_date, tz=self.tz)],
                "abonnement_type": ["Ukentlig ved bestilling"],
            }
        )

        filtered = filter_bookings_for_period(test_data, start_date, end_date)
        self.assertFalse(filtered.empty)
        self.assertEqual(len(filtered), 1)

    def test_hent_bruker_bestillinger(self):
        """Test henting av bestillinger for spesifikk bruker"""
        # Legg inn testdata
        self.cursor.execute(
            """
            INSERT INTO tunbroyting_bestillinger 
            (bruker, ankomst_dato, ankomst_tid, abonnement_type)
            VALUES (?, ?, ?, ?)
        """,
            (
                self.test_user,
                self.today.isoformat(),
                "12:00",
                "Ukentlig ved bestilling",
            ),
        )
        self.conn.commit()

        # Hent brukerens bestillinger
        bestillinger = hent_bruker_bestillinger(self.test_user)

        # Verifiser resultatet
        self.assertFalse(bestillinger.empty)
        self.assertEqual(len(bestillinger), 1)
        self.assertEqual(bestillinger.iloc[0]["bruker"], self.test_user)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
