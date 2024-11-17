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
                datetime TEXT,
                comment TEXT,
                innsender TEXT,
                status TEXT,
                status_changed_by TEXT,
                status_changed_at TEXT,
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
                user_id TEXT NOT NULL,
                login_time TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0
            )
        """,
        "stroing": """
            CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bruker TEXT,
                bestillings_dato TEXT,
                onske_dato TEXT,
                kommentar TEXT,
                status TEXT
            )
        """,
        "tunbroyting": """
            CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
                id INTEGER PRIMARY KEY,
                bruker TEXT,
                ankomst_dato DATE,
                ankomst_tid TIME,
                avreise_dato DATE,
                avreise_tid TIME,
                abonnement_type TEXT
            )
        """,
        "customer": """
            CREATE TABLE IF NOT EXISTS customer (
                customer_id TEXT PRIMARY KEY,
                lat REAL,
                lon REAL,
                subscription TEXT,
                type TEXT DEFAULT 'Customer',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
    }
    logger.debug(f"Available schemas: {list(schemas.keys())}")
    return schemas
