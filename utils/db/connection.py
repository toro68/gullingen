import sqlite3
import os
from utils.core.logging_config import get_logger
from utils.core.config import DATABASE_PATH
from contextlib import contextmanager
import time

logger = get_logger(__name__)

@contextmanager
def get_db_connection(db_name):
    conn = None
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries:
        try:
            db_file = os.path.join(DATABASE_PATH, f"{db_name}.db")
            conn = sqlite3.connect(
                db_file, 
                timeout=30.0,
                isolation_level=None  # Autocommit mode
            )
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=30000')
            
            yield conn
            
            if conn:
                conn.commit()
            return
            
        except sqlite3.OperationalError as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
                    
            if "database is locked" in str(e) and retry_count < max_retries - 1:
                retry_count += 1
                logger.warning(f"Database locked, retry {retry_count}/{max_retries}")
                time.sleep(1)
                continue
            logger.error(f"Database error: {str(e)}")
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"Error closing connection: {str(e)}")
    
    raise sqlite3.OperationalError("Could not acquire database lock after retries")