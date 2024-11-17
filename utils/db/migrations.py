import time

from utils.core.logging_config import get_logger
from utils.db.db_utils import create_database_tables, create_indexes, get_db_connection
from utils.db.schemas import get_database_schemas

logger = get_logger(__name__)


def run_migrations():
    """Kjører nødvendige databasemigrasjoner"""
    try:
        CURRENT_VERSION = "1.0"
        schemas = get_database_schemas()

        # Sjekk/opprett versjonstabell
        with get_db_connection("system") as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            cursor.execute("SELECT version FROM schema_version LIMIT 1")
            result = cursor.fetchone()

            if not result:
                cursor.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (CURRENT_VERSION,),
                )
                conn.commit()
            elif result[0] != CURRENT_VERSION:
                logger.error(
                    f"Schema version mismatch. Expected {CURRENT_VERSION}, found {result[0]}"
                )
                return False

        # Kjør migrasjoner for hver database
        for db_name, schema in schemas.items():
            logger.info(f"Running migrations for {db_name}")
            if not create_database_tables(db_name):
                return False
            time.sleep(0.1)
            create_indexes(db_name)

        return True

    except Exception as e:
        logger.error(f"Error running migrations: {str(e)}", exc_info=True)
        return False
