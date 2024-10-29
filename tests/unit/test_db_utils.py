import pytest
import sqlite3
from db_utils import execute_query, fetch_data, verify_database_exists

def test_execute_query(mock_db):
    """Test utførelse av database-spørringer"""
    query = "INSERT INTO login_history (id, login_time, success) VALUES (?, ?, ?)"
    params = ("test_user", "2024-03-01 12:00:00", 1)
    
    result = execute_query("login_history", query, params)
    assert result is not None  # Sjekk at resultatet ikke er None
    assert result == 1  # En rad påvirket
    
    # Verifiser at dataene ble lagt til
    cursor = mock_db.cursor()
    cursor.execute("SELECT * FROM login_history")
    row = cursor.fetchone()
    assert row[0] == "test_user"
    assert row[2] == 1

def test_fetch_data(mock_db):
    """Test henting av data fra database"""
    # Legg til testdata
    cursor = mock_db.cursor()
    cursor.execute("""
        DELETE FROM tunbroyting_bestillinger
    """)
    cursor.execute("""
        INSERT INTO tunbroyting_bestillinger 
        (bruker, ankomst_dato, avreise_dato, abonnement_type)
        VALUES (?, ?, ?, ?)
    """, ("test_user", "2024-03-01", "2024-03-03", "Ukentlig"))
    mock_db.commit()
    
    query = "SELECT * FROM tunbroyting_bestillinger"
    data = fetch_data("tunbroyting", query)
    
    assert not data.empty
    assert len(data) == 1  # Forvent en rad
    assert data.iloc[0]['bruker'] == "test_user"

def test_verify_database_exists(tmp_path):
    """Test verifisering av databaseeksistens"""
    # Opprett en midlertidig database
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    
    assert verify_database_exists(str(db_path)) == True
    assert verify_database_exists("nonexistent_db") == False