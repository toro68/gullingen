import os
import pandas as pd
from pathlib import Path
from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection

logger = get_logger(__name__)

def import_customers_from_csv() -> bool:
    """Importerer kundedata fra CSV-fil."""
    try:
        # Sjekk først .streamlit/customers.csv
        csv_path = Path(".streamlit/customers.csv")
        if not csv_path.exists():
            # Prøv data/customers.csv som backup
            csv_path = Path("data/customers.csv")
            if not csv_path.exists():
                logger.error("Customer CSV file not found in .streamlit/ or data/")
                return False
        
        logger.info(f"Reading customers from: {csv_path}")
        df = pd.read_csv(csv_path)
        logger.info(f"Read {len(df)} customers from CSV")

        with get_db_connection("customer") as conn:
            cursor = conn.cursor()

            # Tøm eksisterende data
            cursor.execute("DELETE FROM customer")
            
            # Importer nye data
            for _, row in df.iterrows():
                cursor.execute(
                    """
                    INSERT INTO customer 
                    (customer_id, lat, lon, subscription, type)
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
            logger.info(f"Successfully imported {len(df)} customers")
            return True

    except Exception as e:
        logger.error(f"Error importing customers: {str(e)}")
        return False
