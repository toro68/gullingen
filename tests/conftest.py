import os
import sqlite3
from datetime import datetime

import pytest
import streamlit as st


@pytest.fixture
def mock_db():
    """Opprett en midlertidig testdatabase i minnet"""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Opprett nødvendige tabeller
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS login_history (
            id TEXT,
            login_time TEXT,
            success INTEGER
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
            id INTEGER PRIMARY KEY,
            bruker TEXT,
            ankomst_dato TEXT,
            ankomst_tid TEXT,
            avreise_dato TEXT,
            avreise_tid TEXT,
            abonnement_type TEXT
        )
    """
    )

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
