import sqlite3
import pandas as pd

import pytest

from utils.db.db_utils import (
    execute_query, 
    fetch_data,
    verify_schema_version,
    verify_database_schemas,
    verify_stroing_database_state,
    verify_table_exists,
    verify_customer_database
)


def test_execute_query(mock_db):
    """Test utførelse av database-spørringer"""
    with mock_db:
        query = "INSERT INTO login_history (id, login_time, success) VALUES (?, ?, ?)"
        params = ("test_user", "2024-03-01 12:00:00", 1)
        result = execute_query("login_history", query, params)
        assert result == 1


def test_fetch_data(mock_db):
    """Test henting av data fra database"""
    with mock_db:
        cursor = mock_db.cursor()
        cursor.execute("""
            INSERT INTO tunbroyting_bestillinger 
            (bruker, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("test_user", "2024-03-01", "12:00", "2024-03-03", "12:00", "Ukentlig ved bestilling"))
        mock_db.commit()
        
        data = fetch_data("tunbroyting", "SELECT * FROM tunbroyting_bestillinger")
        assert isinstance(data, pd.DataFrame)
        assert len(data) == 1


def test_verify_database_exists(tmp_path):
    """Test verifisering av databaseeksistens"""
    # Opprett en midlertidig database
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.close()

    assert verify_database_exists(str(db_path)) == True
    assert verify_database_exists("nonexistent_db") == False
