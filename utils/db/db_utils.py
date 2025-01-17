import os
import sqlite3
import time
from pathlib import Path
import pandas as pd
from functools import wraps
from typing import Any, Callable

from utils.core.config import (
    DATABASE_PATH,
    DB_CONFIG,
    DB_TIMEOUT,
    DB_RETRY_ATTEMPTS,
    DB_RETRY_DELAY
)
from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection
from utils.db.schemas import get_database_schemas

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
        
        # Mapping mellom database-navn og faktiske tabellnavn
        table_mapping = {
            "feedback": "feedback",
            "login_history": "login_history",
            "stroing": "stroing_bestillinger",
            "tunbroyting": "tunbroyting_bestillinger",
            "customer": "customer",
            "system": "schema_version"
        }
        
        for db_name, schema in schemas.items():
            logger.info(f"=== Creating tables for {db_name} database ===")
            logger.info(f"Database path: {DATABASE_PATH}")
            
            try:
                with get_db_connection(db_name) as conn:
                    cursor = conn.cursor()
                    
                    logger.info(f"Using schema: {schema}")
                    cursor.execute(schema)
                    
                    table_name = table_mapping.get(db_name)
                    if not table_name:
                        raise ValueError(f"No table mapping found for {db_name}")
                        
                    logger.info(f"Successfully created table {table_name}")
                    
                    # Opprett indekser
                    create_indexes(db_name)
                    
                    conn.commit()
                
            except Exception as e:
                logger.error(f"Unexpected error with database {db_name}: {str(e)}")
                raise
                
        return True
        
    except Exception as e:
        logger.error(f"Error creating tables: {str(e)}")
        return False


def verify_database_files():
    """Verifiserer at alle databasefiler eksisterer og er skrivbare"""
    logger.info("=== VERIFYING DATABASE FILES ===")
    for db_name in DB_CONFIG:
        db_path = Path(DB_CONFIG[db_name]["path"])
        logger.info(f"Checking database: {db_path}")
        
        if not db_path.exists():
            logger.error(f"Database file does not exist: {db_path}")
            continue
            
        try:
            # Test skrivetilgang
            with open(db_path, 'ab') as f:
                pass
            logger.info(f"Database {db_path} exists and is writable")
        except Exception as e:
            logger.error(f"Cannot write to database {db_path}: {str(e)}")

def initialize_database_system() -> bool:
    """
    Initialiserer hele databasesystemet inkludert tabeller, migrasjoner 
    og importerer kundedata hvis nødvendig.
    """
    try:
        logger.info("Starting complete database system initialization")
        
        # 1. Opprett tabeller først
        if not create_tables():
            logger.error("Failed to create tables")
            return False
            
        # 2. Kjør migrasjoner - lazy import
        from utils.db.migrations import run_migrations
        if not run_migrations():
            logger.error("Failed to run migrations")
            return False
            
        # 3. Verifiser skjemaene
        if not verify_database_schemas():
            logger.error("Failed to verify schemas")
            return False
            
        # Legg til denne nye sjekken her:
        if not verify_data_persistence():
            logger.error("Failed to verify data persistence")
            return False
            
        # 4. Sjekk og importer kundedata hvis nødvendig
        try:
            with get_db_connection("customer") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM customer")
                count = cursor.fetchone()[0]
                
                if count == 0:
                    logger.info("Customer table is empty, importing initial data")
                    
                    # Import kundedata
                    try:
                        # Les customers.csv
                        csv_path = Path('data/customers.csv')
                        if not csv_path.exists():
                            raise FileNotFoundError(f"customers.csv not found at {csv_path}")
                            
                        customers_df = pd.read_csv(csv_path)
                        cursor.execute("BEGIN TRANSACTION")
                        
                        for _, row in customers_df.iterrows():
                            cursor.execute("""
                                INSERT INTO customer (
                                    customer_id, lat, lon, subscription, type,
                                    created_at, last_updated
                                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            """, (
                                str(row['customer_id']), 
                                float(row['Latitude']), 
                                float(row['Longitude']),
                                row['Subscription'],
                                row['Type']
                            ))
                        
                        conn.commit()
                        logger.info(f"Successfully imported {len(customers_df)} customers from CSV")
                        
                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Error importing customers: {str(e)}")
                        raise
                        
                else:
                    logger.info(f"Customer database already contains {count} records")
                    
                # 5. Verifiser kritiske brukere
                cursor.execute("""
                    SELECT customer_id, type 
                    FROM customer 
                    WHERE type IN ('Admin', 'Superadmin')
                    AND customer_id IN ('199', '999', '22')
                """)
                admins = cursor.fetchall()
                found_admin_ids = [admin[0] for admin in admins]
                
                if not all(aid in found_admin_ids for aid in ['199', '999', '22']):
                    logger.warning("Missing critical admin users!")
                else:
                    logger.info("All critical admin users verified")
                    
        except Exception as e:
            logger.error(f"Error in customer data initialization: {str(e)}")
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

def get_current_db_version(db_name: str) -> str:
    """Henter gjeldende databaseversjon fra system-databasen"""
    try:
        with get_db_connection("system") as conn:
            cursor = conn.cursor()
            
            # Opprett versjonstabell hvis den ikke eksisterer
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    db_name TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    environment TEXT
                )
            """)
            
            # Hent gjeldende versjon
            cursor.execute(
                "SELECT version FROM schema_version WHERE db_name = ?",
                (db_name,)
            )
            result = cursor.fetchone()
            
            if result:
                logger.info(f"Fant versjon {result[0]} for database {db_name}")
                return result[0]
            
            # Hvis ingen versjon er registrert, bruk standardversjon fra DB_CONFIG
            default_version = DB_CONFIG.get(db_name, {}).get("version", "1.0.0")
            
            # Registrer standardversjon
            cursor.execute(
                """
                INSERT INTO schema_version (db_name, version, environment) 
                VALUES (?, ?, ?)
                """,
                (db_name, default_version, os.getenv('ENVIRONMENT', 'development'))
            )
            conn.commit()
            
            logger.info(f"Registrerte standardversjon {default_version} for {db_name}")
            return default_version
            
    except Exception as e:
        logger.error(f"Feil ved henting av databaseversjon for {db_name}: {str(e)}")
        return "0.0.0"  # Returner sikker standardversjon ved feil

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
        # Mapping av indekser per database
        index_mapping = {
            "customer": [
                ("idx_customer_id", "customer(customer_id)"),
                ("idx_customer_type", "customer(type)")
            ],
            "feedback": [
                ("idx_feedback_customer", "feedback(customer_id)"),
                ("idx_feedback_datetime", "feedback(datetime)")
            ],
            "login_history": [
                ("idx_login_history_customer_id", "login_history(customer_id)"),
                ("idx_login_history_login_time", "login_history(login_time)")
            ],
            "stroing": [
                ("idx_stroing_customer", "stroing_bestillinger(customer_id)"),
                ("idx_stroing_dato", "stroing_bestillinger(onske_dato)")
            ],
            "tunbroyting": [
                ("idx_tunbroyting_customer", "tunbroyting_bestillinger(customer_id)"),
                ("idx_tunbroyting_ankomst", "tunbroyting_bestillinger(ankomst_dato)")
            ]
        }
        
        if db_name not in index_mapping:
            return True
            
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            for idx_name, idx_def in index_mapping[db_name]:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}")
            conn.commit()
            
        logger.info(f"Successfully created indexes for {db_name} database")
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
        
        # Mapping mellom database-navn og faktiske tabellnavn
        table_mapping = {
            "feedback": "feedback",
            "login_history": "login_history",
            "stroing": "stroing_bestillinger",
            "tunbroyting": "tunbroyting_bestillinger",
            "customer": "customer",
            "system": "schema_version"
        }
        
        for db_name, schema in schemas.items():
            table_name = table_mapping.get(db_name)
            if not table_name:
                logger.error(f"No table mapping found for database: {db_name}")
                return False
                
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                if cursor.fetchone():
                    logger.info(f"Schema verified for {db_name}: {table_name}")
                else:
                    logger.error(f"Table {table_name} does not exist in {db_name} database")
                    return False
                    
        return True
        
    except Exception as e:
        logger.error(f"Failed to verify schemas: {str(e)}")
        return False


def close_all_connections():
    """Lukk alle aktive databasetilkoblinger"""
    try:
        logger.info("Starting to close all database connections")
        databases = [
            "login_history", 
            "stroing", 
            "tunbroyting", 
            "customer", 
            "feedback",
            "system"
        ]

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

def verify_tunbroyting_database() -> bool:
    """Verifiser tunbroyting database"""
    try:
        logger.info("=== VERIFISERER TUNBRØYTING DATABASE ===")
        
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            
            # Sjekk om tabellen eksisterer
            logger.info("Sjekker om tunbroyting_bestillinger tabellen eksisterer")
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tunbroyting_bestillinger'"
            )
            if not cursor.fetchone():
                logger.error("tunbroyting_bestillinger tabellen eksisterer ikke")
                return False
            
            # Sjekk kolonnestruktur
            logger.info("Verifiserer kolonnestruktur")
            cursor.execute("PRAGMA table_info(tunbroyting_bestillinger)")
            columns = {row[1] for row in cursor.fetchall()}
            required_columns = {
                "id",
                "customer_id",
                "ankomst_dato",
                "avreise_dato",
                "abonnement_type"
            }
            
            missing_columns = required_columns - columns
            if missing_columns:
                logger.error(f"Mangler påkrevde kolonner: {missing_columns}")
                return False
                
            # Sjekk data integritet
            logger.info("Sjekker data integritet")
            cursor.execute("SELECT COUNT(*) FROM tunbroyting_bestillinger")
            total_rows = cursor.fetchone()[0]
            logger.info(f"Totalt antall rader: {total_rows}")
            
            # Sjekk for ugyldige datoer
            cursor.execute("""
                SELECT COUNT(*) FROM tunbroyting_bestillinger 
                WHERE ankomst_dato IS NULL 
                OR ankomst_dato = '' 
                OR ankomst_dato = 'None'
            """)
            invalid_dates = cursor.fetchone()[0]
            if invalid_dates > 0:
                logger.warning(f"Fant {invalid_dates} rader med ugyldige datoer")
            
            logger.info("Tunbrøyting database struktur verifisert")
            return True
            
    except Exception as e:
        logger.error(f"Feil ved verifisering av tunbrøyting database: {str(e)}", exc_info=True)
        return False

@retry_on_db_error(retries=3)
def verify_data_persistence():
    """Verifiserer at databasen kan lagre og hente data persistent"""
    logger.info("=== VERIFYING DATA PERSISTENCE ===")
    try:
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            
            # Sjekk antall rader før
            cursor.execute("SELECT COUNT(*) FROM tunbroyting_bestillinger")
            count_before = cursor.fetchone()[0]
            logger.info(f"Antall rader før test: {count_before}")
            
            # Test innsetting
            test_data = {
                'customer_id': 'TEST',
                'ankomst_dato': '2024-01-01',
                'avreise_dato': '2024-01-02',
                'abonnement_type': 'test'
            }
            
            cursor.execute("""
                INSERT INTO tunbroyting_bestillinger 
                (customer_id, ankomst_dato, avreise_dato, abonnement_type)
                VALUES (?, ?, ?, ?)
            """, (
                test_data['customer_id'],
                test_data['ankomst_dato'],
                test_data['avreise_dato'],
                test_data['abonnement_type']
            ))
            conn.commit()
            
            # Verifiser innsetting
            cursor.execute("SELECT COUNT(*) FROM tunbroyting_bestillinger")
            count_after = cursor.fetchone()[0]
            logger.info(f"Antall rader etter test: {count_after}")
            
            # Fjern testdata
            cursor.execute("DELETE FROM tunbroyting_bestillinger WHERE customer_id = 'TEST'")
            conn.commit()
            
            return count_after > count_before
            
    except Exception as e:
        logger.error(f"Feil i verify_data_persistence: {str(e)}")
        return False
