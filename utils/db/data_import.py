import csv
import os
import pandas as pd
from pathlib import Path
from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection
from utils.core.config import DATABASE_PATH

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
                'Id': str,
                'Latitude': str,
                'Longitude': str,
                'Subscription': str,
                'Type': str
            }, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, dtype={
                'Id': str,
                'Latitude': str,
                'Longitude': str,
                'Subscription': str,
                'Type': str
            }, encoding='latin-1')

        logger.info(f"Read {len(df)} customers from CSV")

        # Hent eksisterende kunde-IDer
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT customer_id FROM customer")
            existing_ids = {row[0] for row in cursor.fetchall()}
            
            # Behandle hver rad
            for _, row in df.iterrows():
                try:
                    customer_id = str(row['Id']).strip()
                    
                    # Hopp over hvis kunde-ID allerede eksisterer
                    if customer_id in existing_ids:
                        logger.debug(f"Skipping existing customer: {customer_id}")
                        continue
                        
                    lat = 0.0 if row['Latitude'] == '0' else float(row['Latitude'])
                    lon = 0.0 if row['Longitude'] == '0' else float(row['Longitude'])
                    
                    cursor.execute("""
                        INSERT INTO customer 
                        (customer_id, lat, lon, subscription, type)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        customer_id,
                        lat,
                        lon,
                        str(row['Subscription']).strip(),
                        str(row['Type']).strip()
                    ))
                    
                except Exception as e:
                    logger.error(f"Error importing customer {row['Id']}: {str(e)}")
                    continue
                    
            conn.commit()
            logger.info("Successfully imported new customer data")
            return True

    except Exception as e:
        logger.error(f"Error importing customer data: {str(e)}")
        return False
