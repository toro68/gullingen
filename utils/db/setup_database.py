import logging
import os

from utils.core.config import (
    DATABASE_PATH
)
from utils.db.db_utils import get_db_connection, initialize_database_system

# Sett opp logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def database_exists():
    """Sjekk om databasefilene eksisterer"""
    return all(
        os.path.exists(DATABASE_PATH / f"{db}.db")
        for db in ["customer", "feedback", "login_history", "stroing", "tunbroyting", "system"]
    )

def table_exists(db_name: str, table_name: str) -> bool:
    """Sjekk om en spesifikk tabell eksisterer"""
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", 
                (table_name,)
            )
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking table existence: {str(e)}")
        return False

def setup_database():
    """Setter opp hele databasesystemet"""
    try:
        logger.info(f"Setting up database system at {DATABASE_PATH}")

        if not initialize_database_system():
            logger.error("Failed to initialize database system")
            return False

        logger.info("Database system setup completed successfully")
        return True

    except Exception as e:
        logger.error(f"Error setting up database system: {str(e)}")
        return False

if __name__ == "__main__":
    if setup_database():
        print("Database setup complete")
    else:
        print("Database setup failed")
