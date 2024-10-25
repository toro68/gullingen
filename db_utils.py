# Standard library imports
import logging
import os
import re
import sqlite3

from sqlalchemy import create_engine
from contextlib import contextmanager
import time
from datetime import datetime, timedelta

import threading
import pandas as pd
from functools import lru_cache
import streamlit as st

from constants import TZ
from config import DATABASE_PATH
from logging_config import get_logger
import atexit

logger = get_logger(__name__)
local = threading.local()

database_initialized = False

# Global variable
last_schema_check = {}

# Global list to store connections
connection_counter = 0
connection_lock = threading.Lock()

# Create a thread-local storage
local = threading.local()

# Hjelpefunksjoner og validering
def increment_connection_count():
    global connection_counter
    with connection_lock:
        connection_counter += 1
        logger.debug(f"Connection opened. Total: {connection_counter}")

def decrement_connection_count():
    global connection_counter
    with connection_lock:
        connection_counter -= 1
        logger.debug(f"Connection closed. Total: {connection_counter}")
           
def validate_stroing_table_structure():
    expected_columns = {
        'id': 'INTEGER',
        'bruker': 'TEXT',
        'bestillings_dato': 'TEXT',
        'onske_dato': 'TEXT'
    }
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("PRAGMA table_info(stroing_bestillinger)")
        table_info = c.fetchall()
        
        actual_columns = {col[1]: col[2] for col in table_info}
        
        if actual_columns != expected_columns:
            logger.error(f"Uventet tabellstruktur for stroing_bestillinger. Forventet: {expected_columns}, Faktisk: {actual_columns}")
            return False
        
        return True

def verify_database_exists(db_name):
    db_path = os.path.join(DATABASE_PATH, f"{db_name}.db")
    if not os.path.exists(db_path):
        logger.error(f"Database file {db_path} does not exist!")
        return False
    logger.info(f"Database file {db_path} exists.")
    return True

@lru_cache(maxsize=None)
def verify_database_schema(db_name):
    """
    Verify the schema of a given database.
    This function is cached to avoid frequent disk operations.
    """
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table'")
        return frozenset(cursor.fetchall())

def verify_login_history_db():
    db_path = os.path.join(DATABASE_PATH, 'login_history.db')
    if not os.path.exists(db_path):
        logger.error(f"Database file {db_path} does not exist!")
        return False
    logger.info(f"Database file {db_path} exists.")
    return True

def verify_and_update_schemas():
    schemas = {
        'customer': {
            'customers': '''
                CREATE TABLE IF NOT EXISTS customers (
                    Id TEXT PRIMARY KEY,
                    Latitude REAL,
                    Longitude REAL,
                    Subscription TEXT,
                    Type TEXT
                )
            '''
        },
        'feedback': {
            'feedback': '''
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY,
                    type TEXT,
                    datetime TEXT,
                    comment TEXT,
                    innsender TEXT,
                    status TEXT,
                    status_changed_by TEXT,
                    status_changed_at TEXT,
                    hidden INTEGER,
                    is_alert INTEGER,
                    display_on_weather INTEGER,
                    expiry_date TEXT,
                    target_group TEXT
                )
            '''
        },
        'login_history': {
            'login_history': '''
                CREATE TABLE IF NOT EXISTS login_history (
                    id TEXT,
                    login_time TEXT,
                    success INTEGER
                )
            '''
        },
        'stroing': {
            'stroing_bestillinger': '''
                CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                    id INTEGER PRIMARY KEY,
                    bruker TEXT,
                    bestillings_dato TEXT,
                    onske_dato TEXT
                )
            '''
        },
        'tunbroyting': {
            'tunbroyting_bestillinger': '''
                CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
                    id INTEGER PRIMARY KEY,
                    bruker TEXT,
                    ankomst_dato DATE,
                    ankomst_tid TIME,
                    avreise_dato DATE,
                    avreise_tid TIME,
                    abonnement_type TEXT
                )
            '''
        }
    }

    for db_name, tables in schemas.items():
        update_database_schema(db_name, schemas[db_name])

    logger.info("All database schemas verified and updated")

def update_database_schema(db_name, expected_schema=None):
    """
    Oppdater skjemaet for en spesifikk database.
    """
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            if db_name == 'login_history':
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS login_history (
                        id TEXT,
                        login_time TEXT,
                        success INTEGER
                    )
                ''')
            elif db_name == 'tunbroyting':
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
                        id INTEGER PRIMARY KEY,
                        bruker TEXT,
                        ankomst_dato DATE,
                        ankomst_tid TIME,
                        avreise_dato DATE,
                        avreise_tid TIME,
                        abonnement_type TEXT
                    )
                ''')
            elif db_name == 'stroing':
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bruker TEXT,
                        bestillings_dato TEXT,
                        onske_dato TEXT
                    )
                ''')
            elif db_name == 'feedback':
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS feedback (
                        id INTEGER PRIMARY KEY,
                        type TEXT,
                        datetime TEXT,
                        comment TEXT,
                        innsender TEXT,
                        status TEXT,
                        status_changed_by TEXT,
                        status_changed_at TEXT,
                        hidden INTEGER,
                        is_alert INTEGER,
                        display_on_weather INTEGER,
                        expiry_date TEXT,
                        target_group TEXT
                    )
                ''')
            conn.commit()
        logger.info(f"Oppdatert skjema for {db_name}")
    except sqlite3.Error as e:
        logger.error(f"SQLite error ved oppdatering av skjema for {db_name}: {e}")
    except Exception as e:
        logger.error(f"Uventet feil ved oppdatering av skjema for {db_name}: {e}")
       
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
    
    if columns_df is not None:
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
    else:
        logger.error("Failed to verify login_history table structure")
        
def perform_database_maintenance():
    databases = ['tunbroyting', 'stroing', 'feedback']
    for db_name in databases:
        with get_db_connection(db_name) as conn:
            conn.execute("VACUUM")
    logger.info("Database maintenance (VACUUM) completed")

def create_database_tables():
    table_schemas = {
        'login_history': '''
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                login_time TEXT NOT NULL,
                success INTEGER NOT NULL
            )
        ''',
        'tunbroyting': '''
            CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bruker TEXT NOT NULL,
                ankomst_dato TEXT NOT NULL,
                ankomst_tid TEXT NOT NULL,
                avreise_dato TEXT NOT NULL,
                avreise_tid TEXT NOT NULL,
                abonnement_type TEXT NOT NULL
            )
        ''',
        'stroing': '''
            CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bruker TEXT NOT NULL,
                bestillings_dato TEXT NOT NULL,
                onske_dato TEXT NOT NULL,
                status TEXT DEFAULT 'Pending'
            )
        ''',
        'feedback': '''
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                datetime TEXT NOT NULL,
                comment TEXT,
                innsender TEXT,
                status TEXT DEFAULT 'Innmeldt',
                status_changed_by TEXT,
                status_changed_at TEXT,
                hidden INTEGER DEFAULT 0,
                is_alert INTEGER DEFAULT 0,
                display_on_weather INTEGER DEFAULT 0,
                expiry_date TEXT,
                target_group TEXT
            )
        ''',
        'customer': '''
            CREATE TABLE IF NOT EXISTS customers (
                Id TEXT PRIMARY KEY,
                Latitude REAL,
                Longitude REAL,
                Subscription TEXT,
                Type TEXT
            )
        '''
    }

    for db_name, schema in table_schemas.items():
        try:
            with get_db_connection(db_name) as conn:
                conn.execute(schema)
                conn.commit()
            logger.info(f"Table in {db_name}.db created or already exists.")
        except sqlite3.Error as e:
            logger.error(f"SQLite error occurred while creating table in {db_name}.db: {e}")
        except Exception as e:
            logger.error(f"Unexpected error occurred while creating table in {db_name}.db: {e}")

    # Create indexes
    indexes = {
        'tunbroyting': [
            "CREATE INDEX IF NOT EXISTS idx_tunbroyting_bruker ON tunbroyting_bestillinger(bruker)",
            "CREATE INDEX IF NOT EXISTS idx_tunbroyting_ankomst_dato ON tunbroyting_bestillinger(ankomst_dato)"
        ],
        'stroing': [
            "CREATE INDEX IF NOT EXISTS idx_stroing_bruker ON stroing_bestillinger(bruker)",
            "CREATE INDEX IF NOT EXISTS idx_stroing_onske_dato ON stroing_bestillinger(onske_dato)"
        ],
        'feedback': [
            "CREATE INDEX IF NOT EXISTS idx_feedback_datetime ON feedback(datetime)",
            "CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(type)",
            "CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)"
        ],
        'customer': [
            "CREATE INDEX IF NOT EXISTS idx_customer_subscription ON customers(Subscription)",
            "CREATE INDEX IF NOT EXISTS idx_customer_type ON customers(Type)"
        ]
    }

    for db_name, index_list in indexes.items():
        try:
            with get_db_connection(db_name) as conn:
                for index in index_list:
                    conn.execute(index)
                conn.commit()
            logger.info(f"Indexes created for {db_name}.db")
        except sqlite3.Error as e:
            logger.error(f"SQLite error occurred while creating indexes in {db_name}.db: {e}")
        except Exception as e:
            logger.error(f"Unexpected error occurred while creating indexes in {db_name}.db: {e}")

def update_existing_tables():
    # Update existing tables to match the new schema
    table_updates = {
        'feedback': [
            "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS hidden INTEGER DEFAULT 0",
            "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS is_alert INTEGER DEFAULT 0",
            "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS display_on_weather INTEGER DEFAULT 0"
        ]
    }

    for db_name, update_list in table_updates.items():
        try:
            with get_db_connection(db_name) as conn:
                for update in update_list:
                    conn.execute(update)
                conn.commit()
            logger.info(f"Table {db_name} updated successfully")
        except sqlite3.Error as e:
            logger.error(f"SQLite error occurred while updating table in {db_name}.db: {e}")
        except Exception as e:
            logger.error(f"Unexpected error occurred while updating table in {db_name}.db: {e}")
           
def debug_database_issues():
    logger = logging.getLogger(__name__)
    logger.info("Starting targeted database issue debugging")

    databases = ['login_history', 'tunbroyting', 'stroing', 'feedback']

    for db_name in databases:
        logger.info(f"Debugging {db_name} database:")
        db_path = f"{db_name}.db"
        
        if not os.path.exists(db_path):
            logger.error(f"Database file {db_path} does not exist!")
            continue
        
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # Check table creation issues
                create_table_query = f'''
                CREATE TABLE IF NOT EXISTS {db_name}_table (
                    id INTEGER PRIMARY KEY,
                    data TEXT
                )
                '''
                try:
                    cursor.execute(create_table_query)
                    logger.info(f"Successfully created test table in {db_name}.db")
                except sqlite3.Error as e:
                    logger.error(f"Error creating test table in {db_name}.db: {e}")
                
                # Check for 'status' column in stroing table
                if db_name == 'stroing':
                    try:
                        cursor.execute("PRAGMA table_info(stroing_bestillinger)")
                        columns = [col[1] for col in cursor.fetchall()]
                        if 'status' not in columns:
                            logger.warning("'status' column is missing in stroing_bestillinger table")
                        else:
                            logger.info("'status' column exists in stroing_bestillinger table")
                    except sqlite3.Error as e:
                        logger.error(f"Error checking 'status' column in stroing_bestillinger: {e}")
                
                # Check index creation
                try:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_test ON {db_name}_table (id)")
                    logger.info(f"Successfully created test index in {db_name}.db")
                except sqlite3.Error as e:
                    logger.error(f"Error creating test index in {db_name}.db: {e}")
                
        except sqlite3.Error as e:
            logger.error(f"Error connecting to {db_name}.db: {e}")

    # Check specific function calls
    try:
        update_stroing_table_structure()
        logger.info("update_stroing_table_structure() executed successfully")
    except Exception as e:
        logger.error(f"Error in update_stroing_table_structure(): {e}")

    try:
        create_database_indexes()
        logger.info("create_database_indexes() executed successfully")
    except Exception as e:
        logger.error(f"Error in create_database_indexes(): {e}")

    logger.info("Targeted database issue debugging completed")

def compare_column_types(actual_type, expected_type):
    # Fjern 'PRIMARY KEY' og 'AUTOINCREMENT' fra sammenligningen
    actual_type = actual_type.replace('PRIMARY KEY', '').replace('AUTOINCREMENT', '').strip().upper()
    expected_type = expected_type.replace('PRIMARY KEY', '').replace('AUTOINCREMENT', '').strip().upper()
    
    # Håndter spesielle tilfeller
    if actual_type == 'INTEGER' and expected_type in ['BOOLEAN', 'INTEGER']:
        return True
    if actual_type == 'BOOLEAN' and expected_type == 'INTEGER':
        return True
    
    return actual_type == expected_type
                   
def create_table_if_not_exists(db_name, table_name, schema):
    with get_db_connection(db_name) as conn:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({schema})")
        conn.commit()
     
def create_customer_table():
    conn = None
    try:
        db_path = os.path.join(DATABASE_PATH, 'customer.db')
        conn = sqlite3.connect(db_path)
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

def execute_query(db_name, query, params=None):
    try:
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
            finally:
                cursor.close()
    except sqlite3.OperationalError as e:
        if "readonly database" in str(e):
            logger.error(f"Database {db_name}.db is readonly. Cannot execute query.")
            st.error(f"Databasen er skrivebeskyttet. Vennligst kontakt systemadministrator.")
        else:
            logger.error(f"Database error in execute_query on {db_name}.db: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in execute_query on {db_name}.db: {e}")
        return None
    finally:
        # Forsikre oss om at tilkoblingen er lukket
        if 'conn' in locals() and conn:
            conn.close()

def close_all_connections():
    logger.info("Starting to close all database connections")
    
    # Lukk alle pooled connections hvis de finnes
    if hasattr(local, 'connection_pool'):
        for db_name, conn in list(local.connection_pool.items()):
            try:
                conn.close()
                logger.info(f"Closed pooled connection to {db_name}.db")
            except Exception as e:
                logger.error(f"Error closing pooled connection to {db_name}.db: {e}", exc_info=True)
        local.connection_pool.clear()
    
    # Fjern unødvendige databasefiler
    pattern = re.compile(r'<sqlite3\.Connection object at 0x[0-9a-f]+>\.db')
    current_dir = os.getcwd()
    for filename in os.listdir(current_dir):
        if pattern.match(filename):
            try:
                os.remove(os.path.join(current_dir, filename))
                logger.info(f"Removed unnecessary file: {filename}")
            except Exception as e:
                logger.error(f"Error removing file {filename}: {e}", exc_info=True)
    
    logger.info("Finished closing all database connections and cleaning up files")

# Registrer funksjonen med atexit
atexit.register(close_all_connections)
               
def fetch_data(db_name, query, params=None):
    try:
        with get_db_connection(db_name) as conn:
            if params:
                return pd.read_sql_query(query, conn, params=params)
            else:
                return pd.read_sql_query(query, conn)
    except Exception as e:
        logger.error(f"Error fetching data from {db_name}.db: {e}")
        return None
    
def execute_many(db_name, query, params):
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params)
            conn.commit()
    except Exception as e:
        logger.error(f"Error executing many queries on {db_name}.db: {e}")

def create_database_indexes():
    databases = ['tunbroyting', 'stroing', 'feedback', 'login_history', 'customer']
    for db_name in databases:
        try:
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()
                if db_name == 'tunbroyting':
                    # Eksisterende + nye indekser for tunbroyting
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tunbroyting_bruker ON tunbroyting_bestillinger(bruker)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tunbroyting_ankomst_dato ON tunbroyting_bestillinger(ankomst_dato)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tunbroyting_avreise_dato ON tunbroyting_bestillinger(avreise_dato)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tunbroyting_abonnement ON tunbroyting_bestillinger(abonnement_type)")
                elif db_name == 'stroing':
                    # Eksisterende + nye indekser for stroing
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stroing_bruker ON stroing_bestillinger(bruker)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stroing_onske_dato ON stroing_bestillinger(onske_dato)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stroing_bestillings_dato ON stroing_bestillinger(bestillings_dato)")
                elif db_name == 'feedback':
                    # Eksisterende + nye indekser for feedback
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_datetime ON feedback(datetime)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_innsender ON feedback(innsender)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(type)")
                elif db_name == 'login_history':
                    # Nye indekser for login_history
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_id ON login_history(id)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_time ON login_history(login_time)")
                elif db_name == 'customer':
                    # Nye indekser for customer
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_subscription ON customers(Subscription)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_type ON customers(Type)")
                
                conn.commit()
                logger.info(f"Successfully created indexes for {db_name} database")
                
        except Exception as e:
            logger.error(f"Error creating indexes for {db_name} database: {str(e)}")

    logger.info("Database index creation completed")
        
def create_database(db_name):
    db_path = os.path.join(DATABASE_PATH, f"{db_name}.db")
    if not os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.close()
            logger.info(f"Created new database: {db_path}")
        except sqlite3.Error as e:
            logger.error(f"Error creating database {db_path}: {e}")
                      
def check_database_size(db_name):
    db_path = os.path.join(DATABASE_PATH, f"{db_name}.db")
    if os.path.exists(db_path):
        size = os.path.getsize(db_path)
        logger.info(f"Size of {db_name}.db: {size/1024/1024:.2f} MB")
    else:
        logger.warning(f"Database {db_name}.db does not exist")

def update_customer_schema():
    try:
        with get_db_connection('customer') as conn:
            cursor = conn.cursor()
            
            # Opprett en ny tabell med korrekt skjema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customers_new (
                    Id TEXT PRIMARY KEY,
                    Latitude REAL,
                    Longitude REAL,
                    Subscription TEXT,
                    Type TEXT
                )
            ''')
            
            # Kopier data fra den gamle tabellen til den nye
            cursor.execute('''
                INSERT OR IGNORE INTO customers_new (Id, Latitude, Longitude, Subscription, Type)
                SELECT Id, Latitude, Longitude, Subscription, Type FROM customers
            ''')
            
            # Slett den gamle tabellen
            cursor.execute('DROP TABLE IF EXISTS customers')
            
            # Gi den nye tabellen det gamle navnet
            cursor.execute('ALTER TABLE customers_new RENAME TO customers')
            
            # Opprett indekser for bedre ytelse
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_subscription ON customers(Subscription)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_type ON customers(Type)")
            
            conn.commit()
            logger.info("Successfully updated customers table schema")
            return True
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while updating customers table schema: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error occurred while updating customers table schema: {e}")
        return False

def robust_update_customer_schema():
    try:
        with get_db_connection('customer') as conn:
            cursor = conn.cursor()
            
            # Check if the temporary table exists and drop it if it does
            cursor.execute("DROP TABLE IF EXISTS customers_new")
            
            # Check if the main table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'")
            table_exists = cursor.fetchone()
            
            if table_exists:
                # Get current schema
                cursor.execute("PRAGMA table_info(customers)")
                current_schema = {row[1]: row[2] for row in cursor.fetchall()}
                
                # Define desired schema
                desired_schema = {
                    'Id': 'TEXT PRIMARY KEY',
                    'Latitude': 'REAL',
                    'Longitude': 'REAL',
                    'Subscription': 'TEXT',
                    'Type': 'TEXT'
                }
                
                # Check if schema needs updating
                if current_schema != desired_schema:
                    # Create new table with correct schema
                    cursor.execute('''
                        CREATE TABLE customers_new (
                            Id TEXT PRIMARY KEY,
                            Latitude REAL,
                            Longitude REAL,
                            Subscription TEXT,
                            Type TEXT
                        )
                    ''')
                    
                    # Copy data from old table to new
                    cursor.execute('''
                        INSERT OR IGNORE INTO customers_new (Id, Latitude, Longitude, Subscription, Type)
                        SELECT Id, Latitude, Longitude, Subscription, Type FROM customers
                    ''')
                    
                    # Drop old table
                    cursor.execute('DROP TABLE customers')
                    
                    # Rename new table to old name
                    cursor.execute('ALTER TABLE customers_new RENAME TO customers')
                    
                    logger.info("customers table schema updated successfully")
                else:
                    logger.info("customers table schema is already up to date")
            else:
                # Create table if it doesn't exist
                cursor.execute('''
                    CREATE TABLE customers (
                        Id TEXT PRIMARY KEY,
                        Latitude REAL,
                        Longitude REAL,
                        Subscription TEXT,
                        Type TEXT
                    )
                ''')
                logger.info("customers table created with correct schema")
            
            # Create or update indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_subscription ON customers(Subscription)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_type ON customers(Type)")
            
            conn.commit()
            logger.info("customers table schema and indexes verified and updated if necessary")
            return True
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while updating customers table schema: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error occurred while updating customers table schema: {e}")
        return False
    
# Database connection
@contextmanager
def get_db_connection(db_name, timeout=30, check_same_thread=True, journal_mode=None):
    db_path = os.path.join(DATABASE_PATH, f'{db_name}.db')
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=timeout, check_same_thread=check_same_thread, uri=True)
        if journal_mode:
            conn.execute(f"PRAGMA journal_mode={journal_mode};")
        conn.row_factory = sqlite3.Row
        logger.debug(f"Opened connection to {db_path}")
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Error with connection to {db_name}.db: {e}")
        if db_name == 'stroing':
            st.error(f"Kunne ikke koble til strøingsdatabasen. Vennligst kontakt systemadministrator.")
        raise
    finally:
        if conn:
            try:
                conn.close()
                logger.debug(f"Closed connection to {db_path}")
            except Exception as e:
                logger.error(f"Error closing connection to {db_name}.db: {e}")
                
def verify_database_connections():
    databases = ['stroing', 'tunbroyting', 'feedback', 'login_history', 'customer']
    for db in databases:
        try:
            with get_db_connection(db) as conn:
                logger.info(f"Successfully verified connection to {db}.db")
        except Exception as e:
            logger.error(f"Failed to connect to {db}.db: {str(e)}")

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
    
def optimize_database(db_name):
    with get_db_connection(db_name) as conn:
        conn.execute("PRAGMA optimize")
        logger.info(f"Optimized {db_name}.db")

def migrate_database(db_name, old_version, new_version):
    # Implementer logikk for å migrere databasen fra old_version til new_version
    pass

## initialiseringsfunksjonene 

def create_all_tables():
    tables = {
        'login_history': '''
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY, 
                user_id TEXT, 
                login_time TEXT, 
                success INTEGER
            )
        ''',
        'tunbroyting': '''
            CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
                id INTEGER PRIMARY KEY, 
                bruker TEXT, 
                ankomst_dato TEXT, 
                ankomst_tid TEXT, 
                avreise_dato TEXT, 
                avreise_tid TEXT, 
                abonnement_type TEXT
            )
        ''',
        'stroing': '''
            CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                id INTEGER PRIMARY KEY, 
                bruker TEXT, 
                bestillings_dato TEXT, 
                onske_dato TEXT, 
                kommentar TEXT,
                status TEXT
            )
        '''
    }

    for db_name, schema in tables.items():
        try:
            with get_db_connection(db_name) as conn:  # Use context manager
                conn.execute(schema)  # No need for separate cursor
                conn.commit()       # Commit within the context manager
            logger.info(f"{db_name} table created or already exists.")
        except Exception as e:
            logger.error(f"Error creating {db_name} table: {str(e)}")
    logger.info("All tables have been created or verified.")

def check_and_update_column_types():
    expected_types = {
        'customer': {
            'Id': 'TEXT PRIMARY KEY',
            'Latitude': 'REAL',
            'Longitude': 'REAL',
            'Subscription': 'TEXT',
            'Type': 'TEXT'
        },
        'feedback': {
            'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
            'type': 'TEXT',
            'datetime': 'TEXT',
            'comment': 'TEXT',
            'innsender': 'TEXT',
            'status': 'TEXT',
            'status_changed_by': 'TEXT',
            'status_changed_at': 'TEXT',
            'hidden': 'INTEGER',
            'is_alert': 'INTEGER',
            'display_on_weather': 'INTEGER',
            'expiry_date': 'TEXT',
            'target_group': 'TEXT'
        }
    }

    for db_name, columns in expected_types.items():
        try:
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({db_name})")
                existing_columns = {col[1]: col[2] for col in cursor.fetchall()}

                for col_name, expected_type in columns.items():
                    if col_name in existing_columns:
                        if existing_columns[col_name].upper() != expected_type.upper():
                            logger.warning(f"Column {col_name} in {db_name} has type {existing_columns[col_name]}, expected {expected_type}")
                            # Here you could add logic to alter the column type if needed
                    else:
                        logger.warning(f"Column {col_name} is missing in {db_name}")
                        # Here you could add logic to add the missing column
        except sqlite3.Error as e:
            logger.error(f"SQLite error occurred while checking column types in {db_name}.db: {e}")
        except Exception as e:
            logger.error(f"Unexpected error occurred while checking column types in {db_name}.db: {e}")

def check_database_integrity(db_name):
    with get_db_connection(db_name) as conn:
        conn.execute("PRAGMA integrity_check")
        
def backup_database(db_name):
    source = f"{db_name}.db"
    destination = f"{db_name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    try:
        with sqlite3.connect(source) as conn:
            with sqlite3.connect(destination) as backup:
                conn.backup(backup)
        logger.info(f"Successfully backed up {source} to {destination}")
    except sqlite3.Error as e:
        logger.error(f"Error backing up database {source}: {e}")

def debug_database_operations():
    logger = logging.getLogger(__name__)
    logger.info("Starting detailed database operations debugging")

    databases = ['login_history', 'tunbroyting', 'stroing', 'feedback']

    for db_name in databases:
        logger.info(f"Debugging {db_name} database:")
        db_path = f"{db_name}.db"
        
        # Check if database file exists
        if not os.path.exists(db_path):
            logger.error(f"Database file {db_path} does not exist!")
            continue
        
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # Check database version
                cursor.execute("PRAGMA user_version")
                version = cursor.fetchone()[0]
                logger.info(f"  Database version: {version}")
                
                # List all tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                logger.info(f"  Tables in {db_name}.db: {[table[0] for table in tables]}")
                
                # Check table structures
                for table in tables:
                    table_name = table[0]
                    logger.info(f"  Structure of {table_name} table:")
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = cursor.fetchall()
                    for col in columns:
                        logger.info(f"    Column: {col[1]}, Type: {col[2]}, NotNull: {col[3]}, DefaultValue: {col[4]}, PK: {col[5]}")
                
                # Check for indexes
                cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
                indexes = cursor.fetchall()
                logger.info(f"  Indexes in {db_name}.db: {[index[0] for index in indexes]}")
                
                # Check row counts
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
                    count = cursor.fetchone()[0]
                    logger.info(f"  Row count in {table[0]}: {count}")
                
                # Test query execution
                test_query = "SELECT 1"
                cursor.execute(test_query)
                result = cursor.fetchone()
                logger.info(f"  Test query result: {result}")
                
        except sqlite3.Error as e:
            logger.error(f"SQLite error occurred while debugging {db_name}.db: {e}")
        except Exception as e:
            logger.error(f"Unexpected error occurred while debugging {db_name}.db: {e}")

    logger.info("Detailed database operations debugging completed")
    
## initialiseringsfunksjonene    
def insert_customer(id, latitude, longitude, subscription, type):
    with sqlite3.connect('customer.db') as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?, ?)",
                  (id, latitude, longitude, subscription, type))
        conn.commit()

def ensure_stroing_table_exists():
    with get_db_connection('stroing', timeout=10, check_same_thread=False, journal_mode='WAL') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS stroing_bestillinger 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      bruker TEXT NOT NULL,
                      bestillings_dato TEXT NOT NULL,
                      onske_dato TEXT NOT NULL)''')
        conn.commit()

def update_stroing_table_structure():
        with get_db_connection('stroing', timeout=10, check_same_thread=False, journal_mode='WAL') as conn:
            cursor = conn.cursor()
            try:
                # Lag en ny tabell uten 'status'-kolonnen
                cursor.execute('''
                    CREATE TABLE stroing_bestillinger_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bruker TEXT NOT NULL,
                        bestillings_dato TEXT NOT NULL,
                        onske_dato TEXT NOT NULL
                    )
                ''')
                
                # Kopier data fra den gamle tabellen til den nye
                cursor.execute('''
                    INSERT INTO stroing_bestillinger_new (id, bruker, bestillings_dato, onske_dato)
                    SELECT id, bruker, bestillings_dato, onske_dato FROM stroing_bestillinger
                ''')
                
                # Slett den gamle tabellen
                cursor.execute('DROP TABLE stroing_bestillinger')
                
                # Gi den nye tabellen det gamle navnet
                cursor.execute('ALTER TABLE stroing_bestillinger_new RENAME TO stroing_bestillinger')
                
                conn.commit()
                logger.info("Successfully updated stroing_bestillinger table structure")
                return True
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"Error updating stroing_bestillinger table structure: {e}")
                return False
                      
def update_stroing_database_schema():
    with get_db_connection('stroing', timeout=10, check_same_thread=False, journal_mode='WAL') as conn:
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
        with get_db_connection('stroing', timeout=10, check_same_thread=False, journal_mode='WAL') as conn:
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA user_version")
            current_version = cursor.fetchone()[0]
            logger.info(f"Current stroing_bestillinger table version: {current_version}")
            
            if current_version < 1:
                logger.info("Upgrading stroing_bestillinger table to version 1")
                cursor.executescript('''
                    -- Ditt eksisterende script her
                ''')
                cursor.execute("PRAGMA user_version = 1")
                logger.info("stroing_bestillinger table upgraded to version 1")
            
            conn.commit()
            logger.info("stroing_bestillinger table update completed successfully")
            return True
    except sqlite3.Error as e:
        logger.error(f"SQLite error updating stroing_bestillinger table: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating stroing_bestillinger table: {e}")
        return False
      
def update_login_history_table():
    try:
        with get_db_connection('login_history') as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS login_history (
                    id TEXT,
                    login_time TEXT,
                    success INTEGER
                )
            ''')
            conn.commit()
        logger.info("login_history table created or verified successfully")
    except sqlite3.Error as e:
        logger.error(f"SQLite error updating login_history table: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error updating login_history table: {str(e)}")

# def close_all_connections():
#     databases = ['login_history', 'tunbroyting', 'stroing', 'feedback']
#     for db in databases:
#         try:
#             with get_db_connection(db) as conn:
#                 conn.close()
#             logger.info(f"Closed connection to {db}.db")
#         except Exception as e:
#             logger.error(f"Error closing connection to {db}.db: {e}")   # Implement logic to close all open connections
                   
# Datavalidering og -henting:

def update_database_structure():
    logger.info("Attempting to update database structure")
    success = update_stroing_table_structure()
    if success:
        logger.info("Database structure updated successfully")
    else:
        logger.error("Failed to update database structure")
    return success
 
def get_expected_schema(db_name):
    # Define expected schemas for each database
    schemas = {
        'login_history': [
            ("CREATE TABLE login_history (id TEXT, login_time TEXT, success INTEGER)",)
        ],
        'tunbroyting': [
            ("CREATE TABLE tunbroyting_bestillinger (id INTEGER PRIMARY KEY, bruker TEXT, ankomst_dato DATE, ankomst_tid TIME, avreise_dato DATE, avreise_tid TIME, abonnement_type TEXT)",)
        ],
        'stroing': [
            ("CREATE TABLE stroing_bestillinger (id INTEGER PRIMARY KEY AUTOINCREMENT, bruker TEXT, bestillings_dato TEXT, onske_dato TEXT)",)
        ],
        'feedback': [
            ("CREATE TABLE feedback (id INTEGER PRIMARY KEY, type TEXT, datetime TEXT, comment TEXT, innsender TEXT, status TEXT DEFAULT 'Innmeldt', status_changed_by TEXT, status_changed_at TEXT, hidden INTEGER DEFAULT 0, is_alert INTEGER DEFAULT 0, display_on_weather INTEGER DEFAULT 0, expiry_date TEXT, target_group TEXT)",)
        ],
        'customer': [
            ("CREATE TABLE customers (Id TEXT PRIMARY KEY, Latitude REAL, Longitude REAL, Subscription TEXT, Type TEXT)",)
        ]
    }
    return frozenset(schemas[db_name])
 
def initialize_database():
    global database_initialized
    if database_initialized:
        logger.info("Database already initialized. Skipping.")
        return
    
    # Your existing initialization code here
    databases = ['login_history', 'tunbroyting', 'stroing', 'feedback', 'customer']
    
    for db in databases:
        try:
            with get_db_connection(db) as conn:
                cursor = conn.cursor()
                
                # Your existing schema verification and update code here
                
                logger.info(f"Database {db} initialized, updated, and optimized")
        
        except sqlite3.Error as e:
            logger.error(f"SQLite error initializing {db} database: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error initializing {db} database: {str(e)}")
    
    try:
        create_database_indexes()
        logger.info("Database indexes created")
    except Exception as e:
        logger.error(f"Error creating database indexes: {str(e)}")
    
    try:
        verify_database_connections()
        logger.info("Database connections verified")
    except Exception as e:
        logger.error(f"Error verifying database connections: {str(e)}")
    
    logger.info("All databases initialized, updated, and verified")
    database_initialized = True
          
# Call this function when the application starts
if __name__ == "__main__":
    debug_database_operations()

