import sqlite3
import os
from utils.core.logging_config import get_logger
from utils.core.config import DATABASE_PATH

logger = get_logger(__name__)

def get_db_connection(db_name):
    try:
        db_file = os.path.join(DATABASE_PATH, f"{db_name}.db")
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"Error connecting to database {db_name}: {str(e)}")
        raise