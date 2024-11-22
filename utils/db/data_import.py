import pandas as pd
from pathlib import Path
from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection
from utils.core.config import (
    DATABASE_PATH
)

logger = get_logger(__name__)

def import_customers_from_csv() -> bool:
    """Importerer kundedata fra CSV-fil."""
    try:
        # Finn prosjektets rotmappe
        root_dir = Path(__file__).parent.parent.parent.absolute()
        logger.info(f"Project root directory: {root_dir}")
        
        # Finn CSV-filen
        csv_path = None
        possible_paths = [
            Path(DATABASE_PATH) / "customers.csv",
            root_dir / ".streamlit/customers.csv",
            root_dir / "data/customers.csv",
            root_dir / "customers.csv",
            Path(".streamlit/customers.csv"),
            Path("data/customers.csv"),
            Path("customers.csv")
        ]
        
        for path in possible_paths:
            if path.exists():
                csv_path = path
                logger.info(f"Found customer CSV at: {path.absolute()}")
                break
                
        if csv_path is None:
            logger.error("Customer CSV file not found")
            return False

        # Les CSV-filen
        try:
            df = pd.read_csv(csv_path, dtype={
                'customer_id': str,
                'Latitude': str,
                'Longitude': str,
                'Subscription': str,
                'Type': str
            }, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, dtype={
                'customer_id': str,
                'Latitude': str,
                'Longitude': str,
                'Subscription': str,
                'Type': str
            }, encoding='latin-1')

        logger.info(f"Read {len(df)} customers from CSV")

        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            for _, row in df.iterrows():
                cursor.execute("""
                    INSERT OR REPLACE INTO customer 
                    (customer_id, lat, lon, subscription, type)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    str(row['customer_id']),
                    row['Latitude'],
                    row['Longitude'],
                    str(row['Subscription']),
                    str(row['Type'])
                ))
            
            logger.info("Customer import completed successfully")
            return True
                
    except Exception as e:
        logger.error(f"Error importing customer data: {str(e)}")
        return False
