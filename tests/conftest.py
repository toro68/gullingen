import os
import sys
import sqlite3
from datetime import datetime, timedelta
from typing import Generator
from zoneinfo import ZoneInfo
from unittest.mock import patch

import pandas as pd
import pytest
import streamlit as st

# Prosjektets rotmappe
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# Test konfigurasjon
TEST_USER = "test_user"
TEST_TZ = ZoneInfo("Europe/Oslo")
TEST_DB = ":memory:"

@pytest.fixture
def mock_db() -> Generator[sqlite3.Connection, None, None]:
    """Opprett en midlertidig testdatabase i minnet"""
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()

    # Opprett nødvendige tabeller
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_history (
            id TEXT,
            login_time TEXT,
            success INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
            id INTEGER PRIMARY KEY,
            bruker TEXT,
            ankomst_dato TEXT,
            ankomst_tid TEXT,
            avreise_dato TEXT,
            avreise_tid TEXT,
            abonnement_type TEXT
        )
    """)

    yield conn
    conn.close()

@pytest.fixture
def mock_streamlit():
    """Mock Streamlit session state"""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    if "last_activity" not in st.session_state:
        st.session_state.last_activity = datetime.now().timestamp()
    return st

@pytest.fixture
def test_data() -> pd.DataFrame:
    """Opprett test data for bestillinger"""
    today = datetime.now(TEST_TZ).date()
    return pd.DataFrame({
        "id": [1, 2, 3],
        "bruker": [TEST_USER] * 3,
        "ankomst_dato": [
            today.isoformat(),
            (today + timedelta(days=1)).isoformat(),
            today.isoformat()
        ],
        "ankomst_tid": ["12:00", "14:00", "09:00"],
        "avreise_dato": [
            (today + timedelta(days=1)).isoformat(),
            (today + timedelta(days=2)).isoformat(),
            (today + timedelta(days=7)).isoformat()
        ],
        "avreise_tid": ["12:00", "14:00", "09:00"],
        "abonnement_type": [
            "Ukentlig ved bestilling",
            "Ukentlig ved bestilling", 
            "Årsabonnement"
        ]
    })

@pytest.fixture
def mock_db_with_data(mock_db: sqlite3.Connection, test_data: pd.DataFrame) -> sqlite3.Connection:
    """Database med forhåndslastet testdata"""
    cursor = mock_db.cursor()
    for _, row in test_data.iterrows():
        cursor.execute("""
            INSERT INTO tunbroyting_bestillinger 
            (id, bruker, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, tuple(row))
    mock_db.commit()
    return mock_db

@pytest.fixture
def patch_db_connections(mock_db):
    """Patch database connections for both db_utils and tun_utils"""
    with patch("utils.db.db_utils.get_db_connection", return_value=mock_db), \
         patch("utils.services.tun_utils.get_db_connection", return_value=mock_db):
        yield mock_db

@pytest.fixture
def sample_booking_data():
    """Test data for kart-markører"""
    return pd.DataFrame({
        "bruker": ["test1", "test2"],
        "ankomst_dato": ["2024-03-14", "2024-03-15"],
        "avreise_dato": ["2024-03-15", "2024-03-16"],
        "abonnement_type": ["Ukentlig ved bestilling", "Årsabonnement"]
    })

@pytest.fixture
def mock_db_connection(mock_db):
    """Alias for mock_db fixture"""
    return mock_db
