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
        
        # Sjekk alle mulige stier for CSV-filen
        possible_paths = [
            Path(DATABASE_PATH) / "customers.csv",
            root_dir / ".streamlit/customers.csv",
            root_dir / "data/customers.csv",
            root_dir / "customers.csv",
            Path(".streamlit/customers.csv"),
            Path("data/customers.csv"),
            Path("customers.csv")
        ]
        
        # Logg alle stier som sjekkes
        csv_path = None
        for path in possible_paths:
            try:
                logger.info(f"Checking for CSV at: {path.absolute()}")
                if path.exists():
                    logger.info(f"Found customer CSV file at: {path.absolute()}")
                    csv_path = path
                    break
            except Exception as e:
                logger.error(f"Error checking path {path}: {str(e)}")
                continue
                
        if csv_path is None:
            logger.error(f"Customer CSV file not found in any of: {[str(p) for p in possible_paths]}")
            return False
            
        logger.info(f"Reading customers from: {csv_path}")
        
        # Les CSV med eksplisitte datatyper og håndter encoding
        try:
            df = pd.read_csv(
                csv_path,
                dtype={
                    'Id': str,
                    'Latitude': str,
                    'Longitude': str,
                    'Subscription': str,
                    'Type': str
                },
                encoding='utf-8'
            )
        except UnicodeDecodeError:
            df = pd.read_csv(
                csv_path,
                dtype={
                    'Id': str,
                    'Latitude': str,
                    'Longitude': str,
                    'Subscription': str,
                    'Type': str
                },
                encoding='latin-1'
            )
        
        logger.info(f"Read {len(df)} customers from CSV")

        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            
            for _, row in df.iterrows():
                try:
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
