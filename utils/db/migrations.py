import os

from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection   
from utils.db.table_utils import get_existing_tables
from utils.db.db_utils import get_current_db_version
from utils.core.config import DB_CONFIG
logger = get_logger(__name__)

def run_migrations():
    """Kjører nødvendige databasemigrasjoner"""
    try:
        CURRENT_VERSION = "1.9.4"
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

# File: utils/db/migrations.py
# Category: Database Migrations

def migrate_feedback_table():
    """
    Migrerer feedback-tabellen fra gammel til ny struktur.
    
    Endringer:
    - Konverterer 'innsender' kolonne til 'customer_id'
    - Legger til nye kolonner med standardverdier
    - Oppretter indekser for bedre ytelse
    
    Returns:
        bool: True hvis migreringen var vellykket, False hvis ikke
    """
    try:
        with get_db_connection("feedback") as conn:
            cursor = conn.cursor()
            
            # 1. Sjekk om feedback-tabellen eksisterer
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'")
            table_exists = cursor.fetchone() is not None
            
            if table_exists:
                # 2. Ta backup og logg
                logger.info("Creating backup of existing feedback table")
                cursor.execute("DROP TABLE IF EXISTS feedback_backup")
                cursor.execute("CREATE TABLE feedback_backup AS SELECT * FROM feedback")
                
                # 3. Analyser eksisterende kolonner
                cursor.execute("PRAGMA table_info(feedback_backup)")
                existing_columns = {col[1]: col for col in cursor.fetchall()}
                logger.info(f"Existing columns: {list(existing_columns.keys())}")
                
                # 4. Velg riktig ID-kolonne og valider
                id_column = None
                if "innsender" in existing_columns:
                    id_column = "innsender"
                elif "customer_id" in existing_columns:
                    id_column = "customer_id"
                    
                if not id_column:
                    raise ValueError("Neither 'innsender' nor 'customer_id' column found")
                
                logger.info(f"Using {id_column} as identifier column")
                
                # 5. Dropp original tabell
                cursor.execute("DROP TABLE IF EXISTS feedback")
            
            # 6. Opprett ny tabell med oppdatert skjema og indekser
            cursor.execute("""
                CREATE TABLE feedback (
                    id INTEGER PRIMARY KEY,
                    type TEXT,
                    customer_id TEXT NOT NULL,
                    datetime TIMESTAMP NOT NULL,
                    comment TEXT,
                    status TEXT DEFAULT 'new',
                    status_changed_by TEXT,
                    status_changed_at TIMESTAMP,
                    hidden INTEGER DEFAULT 0,
                    is_alert INTEGER DEFAULT 0,
                    display_on_weather INTEGER DEFAULT 0,
                    expiry_date TEXT,
                    target_group TEXT
                )
            """)
            
            # Opprett indekser for bedre ytelse
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_customer_id ON feedback(customer_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_datetime ON feedback(datetime)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)")
            
            if table_exists:
                # 7. Kopier data med NULL-håndtering
                insert_sql = f"""
                    INSERT INTO feedback (
                        id, type, customer_id, datetime, comment,
                        status, status_changed_by, status_changed_at,
                        hidden, is_alert, display_on_weather,
                        expiry_date, target_group
                    )
                    SELECT 
                        id,
                        COALESCE(type, 'general'),
                        {id_column},
                        COALESCE(datetime, CURRENT_TIMESTAMP),
                        comment,
                        COALESCE(status, 'new'),
                        status_changed_by,
                        status_changed_at,
                        COALESCE(hidden, 0),
                        COALESCE(is_alert, 0),
                        COALESCE(display_on_weather, 0),
                        expiry_date,
                        target_group
                    FROM feedback_backup
                """
                cursor.execute(insert_sql)
                
                # 8. Verifiser migrering
                cursor.execute("SELECT COUNT(*) FROM feedback")
                new_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM feedback_backup")
                old_count = cursor.fetchone()[0]
                
                if new_count != old_count:
                    raise ValueError(f"Data count mismatch: {old_count} rows in backup, {new_count} in new table")
            
            conn.commit()
            logger.info("Successfully completed feedback table migration")
            return True
            
    except Exception as e:
        logger.error(f"Error migrating feedback table: {str(e)}", exc_info=True)
        return False

def migrate_tunbroyting_table():
    """Migrerer tunbroyting-tabellen"""
    try:
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            logger.info("Starting tunbroyting table migration")
            
            # Backup eksisterende tabell
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger_backup 
                AS SELECT * FROM tunbroyting_bestillinger
            """)
            
            # Dropp original tabell
            cursor.execute("DROP TABLE IF EXISTS tunbroyting_bestillinger")
            
            # Opprett ny tabell med oppdatert skjema
            cursor.execute("""
                CREATE TABLE tunbroyting_bestillinger (
                    id INTEGER PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    ankomst_dato TEXT NOT NULL,
                    avreise_dato TEXT,
                    abonnement_type TEXT NOT NULL,
                    FOREIGN KEY (customer_id) REFERENCES customer(customer_id)
                )
            """)
            
            # Kopier data fra backup
            cursor.execute("""
                INSERT INTO tunbroyting_bestillinger (
                    id, customer_id, ankomst_dato, avreise_dato, abonnement_type
                )
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
            
            conn.commit()
            logger.info("Successfully completed tunbroyting table migration")
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

def verify_migration_versions():
    """Verifiser at migrasjonsversjoner matcher DB_CONFIG"""
    for db_name, config in DB_CONFIG.items():
        expected_version = config["version"]
        current_version = get_current_db_version(db_name)
        if expected_version != current_version:
            logger.error(f"Versjonskonflikt i {db_name}: Forventet {expected_version}, fant {current_version}")
            return False
    return True

def verify_all_schemas():
    """Verifiser at alle databaseskjemaer matcher konfigurasjonen"""
    for db_name, config in DB_CONFIG.items():
        expected_tables = config["schema"]["tables"]
        actual_tables = get_existing_tables(db_name)
        if not set(expected_tables).issubset(set(actual_tables)):
            logger.error(f"Manglende tabeller i {db_name}: {set(expected_tables) - set(actual_tables)}")
            return False
    return True

MIGRATIONS = [
    {
        'version': '1.9.1',
        'function': migrate_customer_table,
        'description': 'Migrerer customer-tabellen med nye standardverdier'
    },
    {
        'version': '1.9.2',
        'function': migrate_tunbroyting_table,
        'description': 'Migrerer tunbroyting-tabellen uten tid-kolonner'
    },
    {
        'version': '1.9.3',
        'function': migrate_feedback_table,
        'description': 'Migrerer feedback-tabellen'
    },
    {
        'version': '1.9.4',
        'function': migrate_stroing_table,
        'description': 'Migrerer stroing-tabellen'
    }
]