import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytz

from app import initialize_app, validate_user_input
from utils.db.db_utils import get_db_connection
from utils.services.tun_utils import filter_todays_bookings, get_bookings


class TestApp(unittest.TestCase):
    def setUp(self):
        """Kjører før hver test"""
        self.test_tz = pytz.timezone("Europe/Oslo")

    def test_validate_user_input(self):
        """Test validering av brukerinput"""
        test_input = {
            "name": 'Test <script>alert("xss")</script>',
            "age": 25,
            "items": ["item1", '<script>alert("xss")</script>'],
            "nested": {"key": '<script>alert("xss")</script>'},
        }

        validated = validate_user_input(test_input)

        self.assertNotIn("<script>", validated["name"])
        self.assertEqual(validated["age"], 25)
        self.assertNotIn("<script>", validated["items"][1])
        self.assertNotIn("<script>", validated["nested"]["key"])

    @patch("db_utils.get_db_connection")
    def test_get_bookings(self, mock_db):
        """Test henting av bestillinger"""
        # Mock data
        mock_data = pd.DataFrame(
            {
                "id": [1, 2],
                "bruker": ["user1", "user2"],
                "ankomst_dato": ["2024-03-14", "2024-03-15"],
                "ankomst_tid": ["12:00:00", "14:00:00"],
                "avreise_dato": ["2024-03-16", "2024-03-17"],
                "avreise_tid": ["10:00:00", "12:00:00"],
                "abonnement_type": ["Ukentlig", "Årsabonnement"],
            }
        )

        # Sett opp mock for fetch_data
        with patch("tun_utils.fetch_data", return_value=mock_data):
            result = get_bookings()
            self.assertIsInstance(result, pd.DataFrame)
            self.assertEqual(len(result), 2)

    def test_filter_todays_bookings(self):
        """Test filtrering av dagens bestillinger"""
        today = datetime.now(self.test_tz).date()

        # Opprett testdata med riktig format og tidssone
        test_data = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "bruker": ["user1", "user2", "user3"],
                "ankomst": [
                    pd.Timestamp(today).tz_localize(self.test_tz),
                    pd.Timestamp(today + timedelta(days=1)).tz_localize(self.test_tz),
                    pd.Timestamp(today).tz_localize(self.test_tz),
                ],
                "abonnement_type": [
                    "Ukentlig ved bestilling",
                    "Ukentlig ved bestilling",
                    "Årsabonnement",
                ],
            }
        )

        # Legg til debugging
        print(f"Test data:\n{test_data}")
        filtered = filter_todays_bookings(test_data)
        print(f"Filtered data:\n{filtered}")

        # Sjekk at filtreringen fungerer
        self.assertTrue(len(filtered) > 0)

        # Sjekk at bare dagens bestillinger er med
        for idx, row in filtered.iterrows():
            self.assertTrue(
                (row["abonnement_type"] == "Årsabonnement" and today.weekday() == 4)
                or (
                    row["abonnement_type"] == "Ukentlig ved bestilling"
                    and pd.Timestamp(row["ankomst"]).date() == today
                )
            )

    @patch("app.verify_and_update_schemas")
    @patch("app.initialize_database")
    @patch("app.ensure_login_history_table_exists")
    def test_initialize_app(self, mock_login, mock_init, mock_verify):
        """Test initialisering av applikasjonen"""
        try:
            initialize_app()
            mock_verify.assert_called_once()
            mock_init.assert_called_once()
            mock_login.assert_called_once()
        except Exception as e:
            self.fail(f"initialize_app raised {type(e)} unexpectedly!")


if __name__ == "__main__":
    unittest.main()
