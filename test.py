import unittest
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import app  # Import your main application file

class TestWeatherApp(unittest.TestCase):
    def setUp(self):
        # Set up test database connections
        self.conn_feedback = sqlite3.connect(':memory:')
        self.conn_tunbroyting = sqlite3.connect(':memory:')
        self.conn_stroing = sqlite3.connect(':memory:')
        
        # Create necessary tables
        app.create_feedback_table(self.conn_feedback)
        app.create_tables(self.conn_tunbroyting)
        app.create_stroing_table(self.conn_stroing)

        # Replace the get_connection functions with our test connections
        app.get_db_connection = lambda: self.conn_feedback
        app.get_db_connection = lambda: self.conn_tunbroyting
        app.get_stroing_connection = lambda: self.conn_stroing

    def tearDown(self):
        # Close database connections
        self.conn_feedback.close()
        self.conn_tunbroyting.close()
        self.conn_stroing.close()

    def test_save_feedback(self):
        result = app.save_feedback("Test Type", "2023-09-22T12:00:00+02:00", "Test Comment", "Test User", self.conn_feedback)
        self.assertTrue(result)
        
        # Verify the feedback was saved
        c = self.conn_feedback.cursor()
        c.execute("SELECT * FROM feedback")
        feedback = c.fetchall()
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0][1], "Test Type")

    def test_authenticate_user(self):
        # Add a test user to the secrets
        app.st.secrets = {
            "auth_codes": {
                "users": {
                    "Test User": "test_code"
                }
            }
        }
        
        self.assertEqual(app.authenticate_user("test_code"), "Test User")
        self.assertIsNone(app.authenticate_user("invalid_code"))

    def test_lagre_bestilling(self):
        app.lagre_bestilling("Test User", "2023-09-22", "12:00", "2023-09-23", "12:00", "Ukentlig", self.conn_tunbroyting)
        
        # Verify the booking was saved
        df = pd.read_sql_query("SELECT * FROM tunbroyting_bestillinger", self.conn_tunbroyting)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['bruker'], "Test User")
    
    def test_lagre_stroing_bestilling(self):
        app.lagre_stroing_bestilling("Test User", "2023-09-22", "Test Comment", self.conn_stroing)
        
        # Verify the strøing booking was saved
        df = pd.read_sql_query("SELECT * FROM stroing_bestillinger", self.conn_stroing)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['bruker'], "Test User")

    def test_update_stroing_status(self):
        # First, add a test booking
        app.lagre_stroing_bestilling("Test User", "2023-09-22", "Test Comment", self.conn_stroing)
        
        # Update the status
        app.update_stroing_status(1, "Completed", self.conn_stroing)
        
        # Verify the status was updated
        df = pd.read_sql_query("SELECT * FROM stroing_bestillinger WHERE id = 1", self.conn_stroing)
        self.assertEqual(df.iloc[0]['status'], "Completed")

    def test_fetch_gps_data(self):
        # Mock the requests.get function to return a predefined response
        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code

            def json(self):
                return self.json_data

            def raise_for_status(self):
                if self.status_code != 200:
                    raise Exception("API error")

        def mock_requests_get(*args, **kwargs):
            return MockResponse({
                "features": [
                    {
                        "properties": {
                            "BILNR": "Test1",
                            "Date": "12:00:00 22.09.2023"
                        }
                    }
                ]
            }, 200)

        # Replace the real requests.get with our mock version
        app.requests.get = mock_requests_get

        gps_data = app.fetch_gps_data()
        self.assertEqual(len(gps_data), 1)
        self.assertEqual(gps_data[0]['BILNR'], "Test1")

if __name__ == '__main__':
    unittest.main()