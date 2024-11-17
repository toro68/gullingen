import pandas as pd

from utils.core.logging_config import get_logger
from utils.db.db_utils import get_db_connection

logger = get_logger(__name__)


def import_customers_from_csv(csv_path: str) -> bool:
    try:
        df = pd.read_csv(csv_path)
        logger.info(f"Reading {len(df)} customers from CSV")

        with get_db_connection("customer") as conn:
            cursor = conn.cursor()

            # Tøm eksisterende data
            cursor.execute("DELETE FROM customer")

            # Importer nye data
            for _, row in df.iterrows():
                cursor.execute(
                    """
                    INSERT INTO customer (customer_id, lat, lon, subscription, type)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        str(row["Id"]),
                        float(row["Latitude"]),
                        float(row["Longitude"]),
                        row["Subscription"],
                        row["Type"],
                    ),
                )

            conn.commit()
            logger.info(f"Imported {len(df)} customers successfully")
            return True

    except Exception as e:
        logger.error(f"Error importing customers: {str(e)}")
        return False
