# Standard library imports
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from constants import TZ
from logging_config import get_logger

from logging_config import get_logger

logger = get_logger(__name__)

# Hjelpefunksjoner og validering           
def validate_stroing_table_structure():
    expected_columns = {
        'id': 'INTEGER',
        'bruker': 'TEXT',
        'bestillings_dato': 'TEXT',
        'onske_dato': 'TEXT',
        'kommentar': 'TEXT',
        'status': 'TEXT'
    }
    
    with get_stroing_connection() as conn:
        c = conn.cursor()
        c.execute("PRAGMA table_info(stroing_bestillinger)")
        table_info = c.fetchall()
        
        actual_columns = {col[1]: col[2] for col in table_info}
        
        if actual_columns != expected_columns:
            logger.error(f"Uventet tabellstruktur for stroing_bestillinger. Forventet: {expected_columns}, Faktisk: {actual_columns}")
            return False
        
        return True

def perform_database_maintenance():
    databases = ['tunbroyting', 'stroing', 'feedback']
    for db_name in databases:
        with get_db_connection(db_name) as conn:
            conn.execute("VACUUM")
    logger.info("Database maintenance (VACUUM) completed")

# Databasetilkoblinger og generelle spørringsfunksjoner
@contextmanager
def get_db_connection(db_name):
    conn = sqlite3.connect(f'{db_name}.db')
    try:
        yield conn
    finally:
        conn.close()
        
def create_customer_table():
    conn = None
    try:
        conn = sqlite3.connect('customer.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS customers
                     (Id TEXT PRIMARY KEY,
                      Latitude REAL,
                      Longitude REAL,
                      Subscription TEXT,
                      Type TEXT)''')
        conn.commit()
        logger.info("Customers table created or already exists")
        
        # Legg til indekser for bedre ytelse
        c.execute("CREATE INDEX IF NOT EXISTS idx_customer_subscription ON customers(Subscription)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_customer_type ON customers(Type)")
        conn.commit()
        logger.info("Indexes created for customers table")
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while creating customers table: {e}")
    except Exception as e:
        logger.error(f"Unexpected error occurred while creating customers table: {e}")
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed")

def get_tunbroyting_connection():
    return get_db_connection('tunbroyting')

def execute_query(db_name, query, params=None):
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            return cursor.rowcount  # Return the number of affected rows
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            conn.rollback()
            return 0  # Return 0 if there's an error

def fetch_data(db_name, query, params=None):
    with get_db_connection(db_name) as conn:
        if params:
            return pd.read_sql_query(query, conn, params=params)
        else:
            return pd.read_sql_query(query, conn)

def execute_many(db_name, query, params):
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, params)
        conn.commit()

def create_database_indexes():
    try:
        with get_db_connection('tunbroyting') as conn:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tunbroyting_bruker ON tunbroyting_bestillinger(bruker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tunbroyting_ankomst_dato ON tunbroyting_bestillinger(ankomst_dato)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tunbroyting_abonnement_type ON tunbroyting_bestillinger(abonnement_type)")
        
        with get_stroing_connection() as conn:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stroing_bruker ON stroing_bestillinger(bruker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stroing_onske_dato ON stroing_bestillinger(onske_dato)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stroing_status ON stroing_bestillinger(status)")
        
        with get_feedback_connection() as conn:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_datetime ON feedback(datetime)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)")
        
        logger.info("Database indexes created successfully")
    except sqlite3.OperationalError as e:
        logger.error(f"Error creating indexes: {str(e)}")
        # Her kan du legge til mer spesifikk feilhåndtering om nødvendig
    except Exception as e:
        logger.error(f"Unexpected error while creating indexes: {str(e)}")

# Database connection
@st.cache_resource
def get_stroing_connection():
    return sqlite3.connect('stroing.db', check_same_thread=False)

@st.cache_resource
def get_feedback_connection():
    return sqlite3.connect('feedback.db', check_same_thread=False)

def update_stroing_table_structure():
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        
        # Sjekk om tabellen eksisterer
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stroing_bestillinger'")
        if not cursor.fetchone():
            # Opprett tabellen hvis den ikke eksisterer
            cursor.execute('''CREATE TABLE stroing_bestillinger (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                bruker TEXT NOT NULL,
                                bestillings_dato TEXT NOT NULL,
                                onske_dato TEXT NOT NULL,
                                kommentar TEXT
                            )''')
            conn.commit()
            logger.info("Created 'stroing_bestillinger' table")
        
    logger.info("stroing_bestillinger table structure verified")

## initialiseringsfunksjonene 

def create_all_tables():
    tables = {
        'login_history': '''CREATE TABLE IF NOT EXISTS login_history
                            (id INTEGER PRIMARY KEY,
                             user_id TEXT,
                             login_time TEXT,
                             success INTEGER)''',
        'tunbroyting': '''CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger
                          (id INTEGER PRIMARY KEY,
                           bruker TEXT,
                           ankomst_dato TEXT,
                           ankomst_tid TEXT,
                           avreise_dato TEXT,
                           avreise_tid TEXT,
                           abonnement_type TEXT)''',
        'stroing': '''CREATE TABLE IF NOT EXISTS stroing_bestillinger
                      (id INTEGER PRIMARY KEY,
                       bruker TEXT,
                       bestillings_dato TEXT,
                       onske_dato TEXT,
                       kommentar TEXT,
                       status TEXT)'''
    }
    
    for db_name, query in tables.items():
        try:
            execute_query(db_name, query)
            logger.info(f"{db_name} table created or already exists.")
        except Exception as e:
            logger.error(f"Error creating {db_name} table: {str(e)}")
    
    logger.info("All tables have been created or verified.")

## initialiseringsfunksjonene 
def initialize_stroing_database():
    """Oppretter nødvendige tabeller for strøingsdatabasen."""
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bruker TEXT NOT NULL,
                bestillings_dato TEXT NOT NULL,
                onske_dato TEXT NOT NULL,
                utfort_dato TEXT,
                utfort_av TEXT
            )
        ''')
        conn.commit()
    logger.info("Strøingsdatabase initialisert")
    
def initialize_database():
    initialize_stroing_database()
    update_stroing_table_structure()
    create_database_indexes()
    # Legg til initialisering for andre databaser her hvis nødvendig
    logger.info("Alle databaser initialisert")
    
def insert_customer(id, latitude, longitude, subscription, type):
    conn = sqlite3.connect('customer.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?, ?)",
              (id, latitude, longitude, subscription, type))
    conn.commit()
    conn.close()

def ensure_stroing_table_exists():
    with get_stroing_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS stroing_bestillinger 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      bruker TEXT NOT NULL,
                      bestillings_dato TEXT NOT NULL,
                      onske_dato TEXT NOT NULL,
                      kommentar TEXT,
                      status TEXT NOT NULL DEFAULT '1')''')
        conn.commit()
              
def update_stroing_database_schema():
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stroing_status_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bestilling_id INTEGER,
                old_status TEXT,
                new_status TEXT,
                changed_by TEXT,
                changed_at TEXT,
                FOREIGN KEY (bestilling_id) REFERENCES stroing_bestillinger(id)
            )
        ''')
        conn.commit()

def update_stroing_bestillinger_table():
    try:
        with get_stroing_connection() as conn:
            cursor = conn.cursor()
            
            # Execute the SQL commands
            cursor.executescript('''
                -- Create backup
                CREATE TABLE IF NOT EXISTS stroing_bestillinger_backup AS SELECT * FROM stroing_bestillinger;

                -- Drop existing table
                DROP TABLE IF EXISTS stroing_bestillinger;

                -- Create new table
                CREATE TABLE stroing_bestillinger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bruker TEXT NOT NULL,
                    bestillings_dato TEXT NOT NULL,
                    onske_dato TEXT NOT NULL,
                    kommentar TEXT,
                    utfort_dato TEXT,
                    utfort_av TEXT,
                    fakturert BOOLEAN DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                -- Copy data from backup
                INSERT INTO stroing_bestillinger (
                    bruker, bestillings_dato, onske_dato, kommentar, 
                    utfort_dato, utfort_av, fakturert, created_at, updated_at
                )
                SELECT 
                    bruker, bestillings_dato, onske_dato, kommentar,
                    NULL, NULL, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM stroing_bestillinger_backup;

                -- Create indexes
                CREATE INDEX idx_stroing_bruker ON stroing_bestillinger(bruker);
                CREATE INDEX idx_stroing_onske_dato ON stroing_bestillinger(onske_dato);
            ''')
            
            conn.commit()
            logger.info("stroing_bestillinger table updated successfully")
            return True
    except Exception as e:
        logger.error(f"Error updating stroing_bestillinger table: {str(e)}")
        return False
    
def update_login_history_table():
    try:
        query = "PRAGMA table_info(login_history)"
        columns = fetch_data('login_history', query)
        
        # Sjekk om 'success' kolonnen eksisterer
        if not any(col['name'] == 'success' for col in columns):
            alter_query = "ALTER TABLE login_history ADD COLUMN success INTEGER"
            execute_query('login_history', alter_query)
            logger.info("Added 'success' column to login_history table")
    except Exception as e:
        logger.error(f"Error updating login_history table: {str(e)}")
        
# Datavalidering og -henting:
def update_database_schema():
    with get_db_connection('tunbroyting') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger
                     (id INTEGER PRIMARY KEY,
                      bruker TEXT,
                      ankomst_dato DATE,
                      ankomst_tid TIME,
                      avreise_dato DATE,
                      avreise_tid TIME,
                      abonnement_type TEXT)''')
        conn.commit()

    logger.info("Database schemas updated successfully.")
       
# Call this function when the application starts
if __name__ == "__main__":
    initialize_database()
    