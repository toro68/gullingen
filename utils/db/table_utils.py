from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection

logger = get_logger(__name__)

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
