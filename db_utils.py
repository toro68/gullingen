# Standard library imports
import logging
import os
import sqlite3
from sqlalchemy import create_engine
from contextlib import contextmanager
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from constants import TZ
from config import DATABASE_PATH
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

def verify_database_exists(db_name):
    db_path = f"{db_name}.db"
    if not os.path.exists(db_path):
        logger.error(f"Database file {db_path} does not exist!")
        return False
    logger.info(f"Database file {db_path} exists.")
    return True

def verify_login_history_db():
    db_path = 'login_history.db'
    if not os.path.exists(db_path):
        logger.error(f"Database file {db_path} does not exist!")
        return False
    logger.info(f"Database file {db_path} exists.")
    return True

# db_utils.py

def ensure_login_history_table_exists():
    create_query = '''
    CREATE TABLE IF NOT EXISTS login_history (
        id TEXT,
        login_time TEXT,
        success INTEGER
    )
    '''
    execute_query('login_history', create_query)
    
    # Verify table structure
    columns_query = "PRAGMA table_info(login_history)"
    columns_df = fetch_data('login_history', columns_query)
    
    actual_columns = set(columns_df['name'])
    expected_columns = {'id', 'login_time', 'success'}
    
    if not expected_columns == actual_columns:
        # Drop the existing table and recreate it
        drop_query = "DROP TABLE IF EXISTS login_history"
        execute_query('login_history', drop_query)
        execute_query('login_history', create_query)
        logger.info("Recreated login_history table with correct structure")
    else:
        logger.info("login_history table structure is correct")
   
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
    logger.info(f"Opening connection to database: {db_name}.db")
    try:
        yield conn
    finally:
        conn.close()
        logger.info(f"Closed connection to database: {db_name}.db")
        
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

def create_login_history_db():
    db_path = 'login_history.db'
    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.close()
        logger.info(f"Created {db_path}")
    ensure_login_history_table_exists()
    
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
            affected_rows = cursor.rowcount
            logger.info(f"Query executed successfully on {db_name}.db. Rows affected: {affected_rows}")
            return affected_rows
        except sqlite3.Error as e:
            logger.error(f"Database error in execute_query on {db_name}.db: {e}")
            logger.error(f"Query: {query}")
            if params:
                logger.error(f"Parameters: {params}")
            conn.rollback()
            return 0

logger.info("Updated execute_query function in db_utils.py")
        
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

def get_db_engine(db_name='login_history.db'):
    try:
        logger.info(f"DATABASE_PATH: {DATABASE_PATH}")
        db_path = os.path.join(DATABASE_PATH, db_name)
        logger.info(f"Full database path: {db_path}")
        logger.info("Attempting to create database engine...")
        engine = create_engine(f'sqlite:///{db_path}')
        logger.info(f"Database engine created successfully for {db_name}")
        return engine
    except ImportError as ie:
        logger.error(f"ImportError: {str(ie)}. Make sure sqlalchemy is installed.", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Failed to create database engine for {db_name}: {str(e)}", exc_info=True)
        raise
    
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
    verify_database_exists('login_history')
    create_login_history_db()
    ensure_login_history_table_exists()
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
        ensure_login_history_table_exists()
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
    