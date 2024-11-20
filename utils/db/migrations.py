import time
from pathlib import Path
import pandas as pd

from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection
from utils.db.schemas import get_database_schemas

logger = get_logger(__name__)

def run_migrations():
    """Kjører nødvendige databasemigrasjoner"""
    try:
        CURRENT_VERSION = "1.4"  # Økt versjonsnummer for å trigge nye migrasjoner
        
        # Sjekk/opprett versjonstabell først
        with get_db_connection("system") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Sjekk nåværende versjon
            cursor.execute("SELECT version FROM schema_version LIMIT 1")
            result = cursor.fetchone()
            
            if result and result[0] == CURRENT_VERSION:
                logger.info("Database already at current version")
                return True
                
            # Kjør migrasjoner
            migrate_feedback_table()
            migrate_tunbroyting_table()
            migrate_login_history_table()
            migrate_stroing_table()
            
            # Oppdater versjon
            if not result:
                cursor.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (CURRENT_VERSION,)
                )
            else:
                cursor.execute(
                    "UPDATE schema_version SET version = ?, updated_at = CURRENT_TIMESTAMP",
                    (CURRENT_VERSION,)
                )
            conn.commit()
            
        return True
        
    except Exception as e:
        logger.error(f"Error running migrations: {str(e)}", exc_info=True)
        return False

def migrate_feedback_table():
    """Migrerer feedback-tabellen for å legge til type-kolonne"""
    try:
        with get_db_connection("feedback") as conn:
            cursor = conn.cursor()
            
            # Sjekk om type-kolonnen eksisterer
            cursor.execute("PRAGMA table_info(feedback)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'type' not in columns:
                # Fjern eventuell eksisterende backup
                cursor.execute("DROP TABLE IF EXISTS feedback_backup")
                
                # Lag en backup av eksisterende data
                cursor.execute("CREATE TABLE feedback_backup AS SELECT * FROM feedback")
                
                # Dropp original tabell
                cursor.execute("DROP TABLE feedback")
                
                # Opprett ny tabell med oppdatert skjema
                cursor.execute("""
                    CREATE TABLE feedback (
                        id INTEGER PRIMARY KEY,
                        type TEXT,
                        datetime TEXT,
                        comment TEXT,
                        customer_id TEXT,
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
                
                # Kopier data tilbake med standardverdi for type
                cursor.execute("""
                    INSERT INTO feedback (
                        id, type, datetime, comment, customer_id,
                        status, status_changed_by, status_changed_at,
                        hidden, is_alert, display_on_weather, 
                        expiry_date, target_group
                    )
                    SELECT 
                        id, 'feedback', datetime, comment, customer_id,
                        status, status_changed_by, status_changed_at,
                        hidden, is_alert, display_on_weather,
                        expiry_date, target_group
                    FROM feedback_backup
                """)
                
                # Fjern backup-tabellen
                cursor.execute("DROP TABLE feedback_backup")
                
                conn.commit()
                logger.info("Successfully migrated feedback table with type column")
            else:
                logger.info("Feedback table already has type column")
                
            return True
            
    except Exception as e:
        logger.error(f"Error migrating feedback table: {str(e)}")
        return False

def migrate_tunbroyting_table():
    """Migrerer tunbroyting-tabellen fra bruker til customer_id"""
    try:
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            
            # Sjekk om bruker-kolonnen eksisterer
            cursor.execute("PRAGMA table_info(tunbroyting_bestillinger)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'bruker' in columns:
                # Lag en backup av eksisterende data
                cursor.execute("CREATE TABLE tunbroyting_backup AS SELECT * FROM tunbroyting_bestillinger")
                
                # Dropp original tabell
                cursor.execute("DROP TABLE tunbroyting_bestillinger")
                
                # Opprett ny tabell med riktig skjema
                cursor.execute("""
                    CREATE TABLE tunbroyting_bestillinger (
                        id INTEGER PRIMARY KEY,
                        customer_id TEXT,
                        ankomst_dato DATE,
                        ankomst_tid TIME,
                        avreise_dato DATE,
                        avreise_tid TIME,
                        abonnement_type TEXT
                    )
                """)
                
                # Kopier data tilbake, konverter bruker til customer_id
                cursor.execute("""
                    INSERT INTO tunbroyting_bestillinger 
                    SELECT id, bruker, ankomst_dato, ankomst_tid, 
                           avreise_dato, avreise_tid, abonnement_type 
                    FROM tunbroyting_backup
                """)
                
                # Fjern backup-tabellen
                cursor.execute("DROP TABLE tunbroyting_backup")
                
                conn.commit()
                logger.info("Successfully migrated tunbroyting table from bruker to customer_id")
            else:
                logger.info("Tunbroyting table already using customer_id")
            
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

