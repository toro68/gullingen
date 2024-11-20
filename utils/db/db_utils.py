import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Optional

from utils.core.config import (
    TZ,
    DATE_FORMATS,
    get_date_format,
    get_current_time,
    get_default_date_range,
    DATE_VALIDATION,
    DATABASE_PATH
)
from utils.core.logging_config import get_logger, setup_logging
from utils.db.connection import get_db_connection
from utils.db.schemas import get_database_schemas
from utils.db.data_import import import_customers_from_csv
from utils.db.migrations import run_migrations

# Sett opp logging
logger = get_logger(__name__)


def retry_on_db_error(retries: int = 3, delay: float = 0.1) -> Callable:
    """Decorator for å retry database operasjoner"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_error = None
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.Error as e:
                    last_error = e
                    if attempt < retries - 1:  # ikke vent etter siste forsøk
                        time.sleep(delay * (2**attempt))  # exponential backoff
                    logger.warning(f"Database retry {attempt + 1}/{retries}: {str(e)}")
            logger.error(f"All database retries failed: {str(last_error)}")
            raise last_error

        return wrapper

    return decorator

def create_tables():
    """Oppretter alle nødvendige databasetabeller."""
    try:
        schemas = get_database_schemas()
        
        for db_name, schema in schemas.items():
            logger.info(f"=== Creating tables for {db_name} database ===")
            logger.info(f"Database path: {DATABASE_PATH}")
            
            try:
                with get_db_connection(db_name) as conn:
                    cursor = conn.cursor()
                    
                    logger.info(f"Using schema: {schema}")
                    cursor.execute(schema)
                    logger.info(f"Successfully created table {db_name}")
                    
                    # Opprett indekser hvis nødvendig
                    if db_name == "login_history":
                        cursor.execute("""
                            CREATE INDEX IF NOT EXISTS idx_login_history_customer_id 
                            ON login_history(customer_id)
                        """)
                        cursor.execute("""
                            CREATE INDEX IF NOT EXISTS idx_login_history_login_time 
                            ON login_history(login_time)
                        """)
                    
                    conn.commit()
                    logger.info(f"Successfully created indexes for {db_name} database")
                
            except Exception as e:
                logger.error(f"Unexpected error with database {db_name}: {str(e)}")
                raise
                
        return True
        
    except Exception as e:
        logger.error(f"Error creating tables: {str(e)}")
        return False


def initialize_database_system() -> bool:
    """Initialiserer hele databasesystemet."""
    try:
        logger.info("Starting complete database system initialization")
        
        # Opprett tabeller først
        if not create_tables():
            logger.error("Failed to create tables")
            return False
            
        # Deretter kjør migrasjoner
        if not run_migrations():
            logger.error("Failed to run migrations")
            return False
            
        # Til slutt verifiser skjemaene
        if not verify_database_schemas():
            logger.error("Failed to verify schemas")
            return False
        
        logger.info("Database system initialization completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Critical database initialization error: {str(e)}")
        return False


def verify_schema_version(expected_version: str) -> bool:
    """Verifiser at databaseskjemaene har riktig versjon"""
    try:
        with get_db_connection("system") as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            cursor.execute("SELECT version FROM schema_version LIMIT 1")
            result = cursor.fetchone()

            if not result:
                cursor.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (expected_version,),
                )
                conn.commit()
                return True

            current_version = result[0]
            return current_version == expected_version

    except Exception as e:
        logger.error(f"Error verifying schema version: {str(e)}")
        return False


def get_existing_tables(db_name: str) -> list:
    """Hent liste over eksisterende tabeller i databasen"""
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('sqlite_sequence')"
            )
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting tables for {db_name}: {str(e)}")
        return []


def create_indexes(db_name: str) -> bool:
    """Opprett indekser for alle databaser"""
    try:
        # Spesialhåndtering for customer-tabellen
        if db_name == "customer":
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_id ON customer(customer_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_type ON customer(type)")
                conn.commit()
                logger.info(f"Successfully created indexes for {db_name} database")
                return True

        # Spesialhåndtering for feedback-tabellen
        if db_name == "feedback":
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_customer_id ON feedback(customer_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_datetime ON feedback(datetime)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)")
                conn.commit()
                logger.info(f"Successfully created indexes for {db_name} database")
                return True

        # For stroing og tunbroyting
        if db_name in ["stroing", "tunbroyting"]:
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{db_name}_customer_id ON {db_name}_bestillinger(customer_id)")
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{db_name}_dato ON {db_name}_bestillinger(bestillings_dato)")
                conn.commit()
                logger.info(f"Successfully created indexes for {db_name} database")
                return True

        # For login_history
        if db_name == "login_history":
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_customer_id ON login_history(customer_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_time ON login_history(login_time)")
                conn.commit()
                logger.info(f"Successfully created indexes for {db_name} database")
                return True

        return True

    except Exception as e:
        logger.error(f"Error creating indexes for {db_name}: {str(e)}")
        return False


def execute_schema_updates(cursor, statements):
    """Kjør SQL-statements én etter én"""
    for statement in statements.split(";"):
        if statement.strip():
            cursor.execute(statement.strip())


def execute_query(db_name: str, query: str, params: tuple = None) -> bool:
    """Utfør en database spørring"""
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error(f"Error executing query on {db_name}: {str(e)}")
        return False


def fetch_data(db_name: str, query: str, params: tuple = None) -> list:
    """Hent data fra databasen"""
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Error fetching data from {db_name}: {str(e)}")
        return []


def verify_database_schemas() -> bool:
    """Verifiser at alle databaseskjemaer er korrekt"""
    try:
        logger.info("=== VERIFYING DATABASE SCHEMAS ===")
        schemas = get_database_schemas()
        verification_results = {}

        for db_name, schema in schemas.items():
            try:
                with get_db_connection(db_name) as conn:
                    cursor = conn.cursor()
                    table_name = (
                        f"{db_name}_bestillinger" 
                        if db_name in ["stroing", "tunbroyting"] 
                        else db_name
                    )
                    
                    # Sjekk om tabellen eksisterer
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", 
                        (table_name,)
                    )
                    
                    if not cursor.fetchone():
                        verification_results[db_name] = False
                        logger.error(f"Table {table_name} does not exist in {db_name} database")
                        continue

                    # Verifiser kolonner
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    existing_columns = {row[1] for row in cursor.fetchall()}
                    
                    verification_results[db_name] = True
                    logger.info(f"Schema verified for {db_name}: {table_name}")
                    
            except Exception as e:
                verification_results[db_name] = False
                logger.error(f"Error verifying {db_name} database: {str(e)}")
                
        success = all(verification_results.values())
        if not success:
            logger.error("Failed to verify schemas")
        return success

    except Exception as e:
        logger.error(f"Error in database schema verification: {str(e)}")
        return False


def close_all_connections():
    """Lukk alle aktive databasetilkoblinger"""
    try:
        logger.info("Starting to close all database connections")
        databases = ["login_history", "stroing", "tunbroyting", "customer", "feedback"]

        for db_name in databases:
            try:
                with get_db_connection(db_name) as conn:
                    conn.close()
            except Exception as e:
                logger.error(f"Error closing connection for {db_name}: {str(e)}")

        logger.info("Finished closing all database connections and cleaning up files")
        return True
    except Exception as e:
        logger.error(f"Error in close_all_connections: {str(e)}")
        return False


def verify_stroing_database() -> bool:
    """Verifiser stroing database"""
    try:
        with get_db_connection("stroing") as conn:
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA table_info(stroing_bestillinger)")
            columns = {row[1] for row in cursor.fetchall()}
            
            required_columns = {
                "id",
                "customer_id",
                "bestillings_dato",
                "onske_dato",
                "kommentar",
                "status",
            }

            if not required_columns.issubset(columns):
                missing = required_columns - columns
                logger.error(f"Missing columns in stroing_bestillinger: {missing}")
                return False

            logger.info("Stroing database structure verified successfully")
            return True

    except Exception as e:
        logger.error(f"Error verifying stroing database: {str(e)}")
        return False


def create_database_tables(db_name: str) -> bool:
    """Opprett tabeller basert på skjemaer"""
    try:
        logger.info(f"=== Creating tables for {db_name} database ===")
        logger.info(f"Database path: {DATABASE_PATH}")

        schemas = get_database_schemas()
        if db_name not in schemas:
            logger.error(f"No schema found for database: {db_name}")
            return False

        schema = schemas[db_name]
        logger.info(f"Using schema: {schema}")

        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            logger.info(f"Executing schema creation for {db_name}")
            cursor.execute(schema)
            conn.commit()

            # Bestem riktig tabellnavn basert på database
            table_name = {
                "customer": "customer",
                "login_history": "login_history",
                "feedback": "feedback",
            }.get(db_name, f"{db_name}_bestillinger")

            cursor.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
            )
            if not cursor.fetchone():
                logger.error(f"Table {table_name} was not created successfully")
                return False

            logger.info(f"Successfully created table {table_name}")
            return True

    except Exception as e:
        logger.error(f"Error creating tables for {db_name}: {str(e)}", exc_info=True)
        return False


def verify_table_exists(db_name: str, table_name: str) -> bool:
    """Sjekk om en tabell eksisterer i databasen"""
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """,
                (table_name,),
            )
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error(f"Error verifying table {table_name} in {db_name}: {str(e)}")
        return False


def create_customer_table() -> bool:
    """Opprett customer-tabellen"""
    try:
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            cursor.execute(get_database_schemas()["customer"])
            conn.commit()
            logger.info("Created customer table successfully")
            return True
    except sqlite3.Error as e:
        logger.error(f"Error creating customer table: {str(e)}")
        return False

def verify_customer_database() -> bool:
    """Verifiser customer database"""
    try:
        logger.info("=== VERIFYING CUSTOMER DATABASE ===")
        logger.info(f"Process ID: {os.getpid()}")

        with get_db_connection("customer") as conn:
            cursor = conn.cursor()

            # Sjekk om tabellen eksisterer
            logger.info("Checking if customer table exists")
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='customer'"
            )
            if not cursor.fetchone():
                logger.error("Customer table does not exist")
                return False

            # Sjekk kolonnestruktur
            logger.info("Verifying customer table columns")
            cursor.execute("PRAGMA table_info(customer)")
            columns = {row[1] for row in cursor.fetchall()}
            required_columns = {
                "customer_id",
                "lat",
                "lon",
                "subscription",
                "type",
                "created_at",
            }

            missing_columns = required_columns - columns
            if missing_columns:
                logger.error(f"Missing required columns: {missing_columns}")
                return False

            logger.info("Customer table structure verified successfully")
            return True

    except Exception as e:
        logger.error(f"Customer database verification failed: {str(e)}", exc_info=True)
        return False
