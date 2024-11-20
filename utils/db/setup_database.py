import logging
import os
import sqlite3

from utils.core.config import (
    TZ,
    DATE_FORMATS,
    get_date_format,
    get_current_time,
    get_default_date_range,
    DATE_VALIDATION,
    DATABASE_PATH
)
from utils.core.logging_config import get_logger
from utils.db.db_utils import create_customer_table, get_db_connection
from utils.db.data_import import import_customers_from_csv

# Sett opp logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

try:
    from utils.db.db_utils import create_customer_table, insert_customer
except ImportError as e:
    logger.error(f"Error importing from db_utils: {e}")
    logger.info("Please make sure all required packages are installed.")
    logger.info("You can install them by running: pip install -r requirements.txt")
    exit(1)


def database_exists():
    return os.path.exists(DATABASE_PATH / "customer.db")


def table_exists(table_name):
    conn = sqlite3.connect(DATABASE_PATH / "customer.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None


def setup_database():
    """Setter opp hele databasesystemet"""
    try:
        logger.info(f"Setting up database system at {DATABASE_PATH}")

        # Initialiser databasesystemet
        from utils.db.db_utils import initialize_database_system

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
