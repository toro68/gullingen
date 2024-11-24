from utils.core.logging_config import get_logger

logger = get_logger(__name__)


def get_database_schemas():
    """Returner databaseskjemaer for alle tabeller"""
    logger.info("Getting database schemas")
    schemas = {
        "feedback": """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY,
                type TEXT,
                customer_id TEXT,
                datetime TIMESTAMP,
                comment TEXT,
                status TEXT,
                status_changed_by TEXT,
                status_changed_at TIMESTAMP,
                hidden INTEGER DEFAULT 0,
                is_alert INTEGER DEFAULT 0,
                display_on_weather INTEGER DEFAULT 0,
                expiry_date TEXT,
                target_group TEXT
            )
        """,
        "login_history": """
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                login_time TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0
            )
        """,
        "stroing": """
            CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                bestillings_dato TEXT NOT NULL,
                onske_dato TEXT NOT NULL,
                kommentar TEXT,
                status TEXT
            )
        """,
        "tunbroyting": """
            CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                ankomst_dato TEXT NOT NULL,
                avreise_dato TEXT,
                abonnement_type TEXT NOT NULL
            )
        """,
        "customer": """
            CREATE TABLE IF NOT EXISTS customer (
                customer_id TEXT PRIMARY KEY,
                lat REAL DEFAULT NULL,
                lon REAL DEFAULT NULL,
                subscription TEXT DEFAULT 'star_red',
                type TEXT DEFAULT 'Customer',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "system": """
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                environment TEXT
            )
        """
    }
    logger.debug(f"Available schemas: {list(schemas.keys())}")
    return schemas
