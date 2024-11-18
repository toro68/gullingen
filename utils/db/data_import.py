import csv
import os
import pandas as pd
from pathlib import Path
from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection

logger = get_logger(__name__)

def import_customers_from_csv():
    """Importerer kundedata fra CSV-fil."""
    try:
        # Sjekk først .streamlit/customers.csv
        csv_path = Path(".streamlit/customers.csv")
        if not csv_path.exists():
            logger.error(f"Customer data file not found at {csv_path}")
            return False
            
        logger.info(f"Reading customers from: {csv_path}")
        
        # Les CSV med eksplisitte datatyper
        df = pd.read_csv(
            csv_path,
            dtype={
                'Id': str,
                'Latitude': str,
                'Longitude': str,
                'Subscription': str,
                'Type': str
            }
        )
        
        logger.info(f"Read {len(df)} customers from CSV")

        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            
            for _, row in df.iterrows():
                try:
                    # Konverter koordinater til float, håndter '0' spesielt
                    lat = 0.0 if row['Latitude'] == '0' else float(row['Latitude'])
                    lon = 0.0 if row['Longitude'] == '0' else float(row['Longitude'])
                    
                    cursor.execute("""
                        INSERT INTO customer 
                        (customer_id, lat, lon, subscription, type)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        str(row['Id']).strip(),
                        lat,
                        lon,
                        str(row['Subscription']).strip(),
                        str(row['Type']).strip()
                    ))
                except Exception as row_error:
                    logger.error(f"Error importing row {row['Id']}: {str(row_error)}")
                    continue
                    
            conn.commit()
            logger.info("Successfully imported customer data")
            return True
        
    except Exception as e:
        logger.error(f"Error importing customer data: {str(e)}")
        return False
