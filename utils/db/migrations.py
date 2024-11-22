import time
from pathlib import Path
import pandas as pd
import streamlit as st
import os

from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection
from utils.db.schemas import get_database_schemas
from utils.core.config import (
    TZ,
    DATE_FORMATS,
    get_date_format,
    get_current_time,
    get_default_date_range,
    DATE_VALIDATION
)

logger = get_logger(__name__)

def run_migrations():
    """Kjører nødvendige databasemigrasjoner"""
    try:
        CURRENT_VERSION = "1.9"
        IS_CLOUD = os.getenv('IS_STREAMLIT_CLOUD', 'false').lower() == 'true'
        
        logger.info(f"Running migrations. Environment: {'Cloud' if IS_CLOUD else 'Local'}")
        
        # Opprett system-database og schema_version tabell først
        with get_db_connection("system") as conn:
            cursor = conn.cursor()
            
            # Opprett migrations_history tabell
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS migrations_history (
                    id INTEGER PRIMARY KEY,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success BOOLEAN NOT NULL,
                    error_message TEXT,
                    environment TEXT NOT NULL
                )
            """)
            
            # Kjør migrasjoner i rekkefølge
            for migration in MIGRATIONS:
                migration_name = migration['function'].__name__
                
                # Sjekk om migrasjonen allerede er kjørt
                cursor.execute("""
                    SELECT success FROM migrations_history 
                    WHERE name = ? AND version = ? AND environment = ?
                    ORDER BY executed_at DESC LIMIT 1
                """, (migration_name, migration['version'], 'cloud' if IS_CLOUD else 'local'))
                
                result = cursor.fetchone()
                
                if result and result[0]:
                    logger.info(f"Migration {migration_name} already executed successfully")
                    continue
                
                # Kjør migrasjonen
                try:
                    success = migration['function']()
                    error_msg = None
                except Exception as e:
                    success = False
                    error_msg = str(e)
                    logger.error(f"Error in migration {migration_name}: {error_msg}")
                
                # Logg resultatet
                cursor.execute("""
                    INSERT INTO migrations_history 
                    (version, name, success, error_message, environment)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    migration['version'],
                    migration_name,
                    success,
                    error_msg,
                    'cloud' if IS_CLOUD else 'local'
                ))
                conn.commit()
                
                if not success:
                    return False
            
            return True
            
    except Exception as e:
        logger.error(f"Error running migrations: {str(e)}", exc_info=True)
        return False

def migrate_feedback_table():
    """Migrerer feedback-tabellen"""
    try:
        with get_db_connection("feedback") as conn:
            cursor = conn.cursor()
            
            # Fjern eventuell eksisterende backup
            cursor.execute("DROP TABLE IF EXISTS feedback_backup")
            
            # Sjekk om feedback-tabellen eksisterer og lag backup
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'")
            if cursor.fetchone():
                cursor.execute("CREATE TABLE feedback_backup AS SELECT * FROM feedback")
                logger.info("Created backup of existing feedback table")
            
            # Dropp eksisterende tabell
            cursor.execute("DROP TABLE IF EXISTS feedback")
            
            # Opprett ny tabell med riktig skjema
            cursor.execute("""
                CREATE TABLE feedback (
                    id INTEGER PRIMARY KEY,
                    type TEXT,
                    customer_id TEXT,
                    datetime TEXT,
                    comment TEXT,
                    status TEXT,
                    status_changed_by TEXT,
                    status_changed_at TEXT,
                    hidden INTEGER DEFAULT 0,
                    is_alert INTEGER DEFAULT 0,
                    display_on_weather INTEGER DEFAULT 0,
                    expiry_date TEXT,
                    target_group TEXT
                )
            """)
            
            # Kopier data fra backup hvis den eksisterer
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback_backup'")
            if cursor.fetchone():
                try:
                    cursor.execute("""
                        INSERT INTO feedback (
                            id, type, customer_id, datetime, comment,
                            status, status_changed_by, status_changed_at,
                            hidden, is_alert, display_on_weather,
                            expiry_date, target_group
                        )
                        SELECT 
                            id, type, innsender, datetime, comment,
                            status, status_changed_by, status_changed_at,
                            hidden, is_alert, display_on_weather,
                            expiry_date, target_group
                        FROM feedback_backup
                    """)
                    logger.info("Data migrated from backup to new table")
                except Exception as e:
                    logger.error(f"Error migrating data: {str(e)}")
            
            # Opprett indekser
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_datetime ON feedback(datetime)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_customer_id ON feedback(customer_id)")
            
            # Fjern backup og commit
            cursor.execute("DROP TABLE IF EXISTS feedback_backup")
            conn.commit()
            
            logger.info("Successfully completed feedback table migration")
            return True
            
    except Exception as e:
        logger.error(f"Error in migrate_feedback_table: {str(e)}", exc_info=True)
        return False

def migrate_tunbroyting_table():
    """Migrerer tunbroyting-tabellen til forenklet skjema uten tidkolonner"""
    try:
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            
            # Backup eksisterende tabell
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger_backup 
                AS SELECT * FROM tunbroyting_bestillinger
            """)
            
            # Dropp original tabell
            cursor.execute("DROP TABLE IF EXISTS tunbroyting_bestillinger")
            
            # Opprett ny tabell med forenklet skjema
            cursor.execute("""
                CREATE TABLE tunbroyting_bestillinger (
                    id INTEGER PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    ankomst_dato DATE NOT NULL,
                    avreise_dato DATE,
                    abonnement_type TEXT NOT NULL,
                    FOREIGN KEY (customer_id) REFERENCES customer(customer_id)
                )
            """)
            
            # Kopier data fra backup, ignorer tidkolonnene
            cursor.execute("""
                INSERT INTO tunbroyting_bestillinger 
                (id, customer_id, ankomst_dato, avreise_dato, abonnement_type)
                SELECT 
                    id, 
                    customer_id, 
                    ankomst_dato,
                    avreise_dato,
                    abonnement_type
                FROM tunbroyting_bestillinger_backup
            """)
            
            # Opprett indekser
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tunbroyting_customer_id 
                ON tunbroyting_bestillinger(customer_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tunbroyting_ankomst 
                ON tunbroyting_bestillinger(ankomst_dato)
            """)
            
            # Fjern backup
            cursor.execute("DROP TABLE IF EXISTS tunbroyting_bestillinger_backup")
            
            conn.commit()
            logger.info("Successfully migrated tunbroyting table to simplified schema")
            return True
            
    except Exception as e:
        logger.error(f"Error migrating tunbroyting table: {str(e)}")
        return False

def migrate_login_history_table():
    """Migrerer login_history-tabellen fra user_id til customer_id"""
    try:
        with get_db_connection("login_history") as conn:
            cursor = conn.cursor()
            
            # Sjekk om user_id-kolonnen eksisterer
            cursor.execute("PRAGMA table_info(login_history)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'user_id' in columns:
                # Lag en backup av eksisterende data
                cursor.execute("CREATE TABLE login_history_backup AS SELECT * FROM login_history")
                
                # Dropp original tabell
                cursor.execute("DROP TABLE login_history")
                
                # Opprett ny tabell med riktig skjema
                cursor.execute("""
                    CREATE TABLE login_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_id TEXT NOT NULL,
                        login_time TEXT NOT NULL,
                        success INTEGER NOT NULL DEFAULT 0
                    )
                """)
                
                # Kopier data tilbake, konverter user_id til customer_id
                cursor.execute("""
                    INSERT INTO login_history (id, customer_id, login_time, success)
                    SELECT id, user_id, login_time, success 
                    FROM login_history_backup
                """)
                
                # Opprett indekser
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_login_history_customer_id 
                    ON login_history(customer_id)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_login_history_login_time 
                    ON login_history(login_time)
                """)
                
                # Fjern backup-tabellen
                cursor.execute("DROP TABLE login_history_backup")
                
                conn.commit()
                logger.info("Successfully migrated login_history table from user_id to customer_id")
            else:
                logger.info("Login_history table already using customer_id")
            
            return True
            
    except Exception as e:
        logger.error(f"Error migrating login_history table: {str(e)}")
        return False

def migrate_stroing_table():
    """Migrerer stroing-tabellen fra bruker til customer_id"""
    try:
        with get_db_connection("stroing") as conn:
            cursor = conn.cursor()
            
            # Fjern eventuell eksisterende backup
            cursor.execute("DROP TABLE IF EXISTS stroing_bestillinger_backup")
            conn.commit()
            
            # Sjekk om bruker-kolonnen eksisterer
            cursor.execute("PRAGMA table_info(stroing_bestillinger)")
            columns = [row[1] for row in cursor.fetchall()]
            logger.info(f"Current stroing table columns: {columns}")
            
            if 'bruker' in columns:
                # Lag backup
                cursor.execute("CREATE TABLE stroing_bestillinger_backup AS SELECT * FROM stroing_bestillinger")
                conn.commit()
                
                # Dropp original tabell
                cursor.execute("DROP TABLE stroing_bestillinger")
                conn.commit()
                
                # Opprett ny tabell med riktig skjema
                cursor.execute("""
                    CREATE TABLE stroing_bestillinger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_id TEXT NOT NULL,
                        bestillings_dato TEXT NOT NULL,
                        onske_dato TEXT NOT NULL,
                        kommentar TEXT,
                        status TEXT
                    )
                """)
                conn.commit()
                
                # Kopier data og opprett indeks
                cursor.execute("""
                    INSERT INTO stroing_bestillinger (id, customer_id, bestillings_dato, onske_dato, kommentar, status)
                    SELECT id, bruker, bestillings_dato, onske_dato, kommentar, status 
                    FROM stroing_bestillinger_backup
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_stroing_customer_id 
                    ON stroing_bestillinger(customer_id)
                """)
                conn.commit()
                
                # Fjern backup og commit
                cursor.execute("DROP TABLE stroing_bestillinger_backup")
                conn.commit()
                
                logger.info("Successfully migrated stroing table from bruker to customer_id")
                return True
            else:
                logger.info("Stroing table already using customer_id")
                return True
                
    except Exception as e:
        logger.error(f"Error migrating stroing table: {str(e)}")
        return False

def migrate_customer_table():
    """Migrerer customer-tabellen med nye standardverdier"""
    try:
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            
            # Backup eksisterende tabell
            cursor.execute("CREATE TABLE IF NOT EXISTS customer_backup AS SELECT * FROM customer")
            
            # Dropp original tabell
            cursor.execute("DROP TABLE IF EXISTS customer")
            
            # Opprett ny tabell med oppdatert skjema
            cursor.execute("""
                CREATE TABLE customer (
                    customer_id TEXT PRIMARY KEY,
                    lat REAL DEFAULT NULL,
                    lon REAL DEFAULT NULL,
                    subscription TEXT DEFAULT 'star_red',
                    type TEXT DEFAULT 'Customer',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Kopier data fra backup
            cursor.execute("""
                INSERT INTO customer (
                    customer_id, lat, lon, subscription, type, created_at
                )
                SELECT 
                    customer_id,
                    COALESCE(lat, NULL),
                    COALESCE(lon, NULL),
                    COALESCE(subscription, 'star_red'),
                    COALESCE(type, 'Customer'),
                    COALESCE(created_at, CURRENT_TIMESTAMP)
                FROM customer_backup
            """)
            
            # Opprett indekser
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_id ON customer(customer_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscription ON customer(subscription)")
            
            # Fjern backup
            cursor.execute("DROP TABLE IF EXISTS customer_backup")
            
            conn.commit()
            logger.info("Successfully migrated customer table")
            return True
            
    except Exception as e:
        logger.error(f"Error migrating customer table: {str(e)}")
        return False

MIGRATIONS = [
    {
        'version': '1.8',
        'function': migrate_customer_table,
        'description': 'Migrerer customer-tabellen med nye standardverdier'
    },
    {
        'version': '1.8',
        'function': migrate_feedback_table,
        'description': 'Migrerer feedback-tabellen'
    },
    {
        'version': '1.9',
        'function': migrate_tunbroyting_table,
        'description': 'Migrerer tunbroyting-tabellen til forenklet skjema'
    },
    {
        'version': '1.9',
        'function': migrate_stroing_table,
        'description': 'Migrerer stroing-tabellen fra bruker til customer_id'
    }
]