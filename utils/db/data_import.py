import csv
import os
from pathlib import Path
from utils.core.logging_config import get_logger
from utils.db.db_utils import get_db_connection

logger = get_logger(__name__)

def import_customers_from_csv():
    try:
        # Finn CSV-filen i data-mappen
        data_dir = Path(__file__).parent.parent.parent / "data"
        csv_path = data_dir / "customers.csv"
        
        if not csv_path.exists():
            logger.error(f"Customer data file not found at {csv_path}")
            return False
            
        conn = get_db_connection("customer")
        cursor = conn.cursor()
        
        with open(csv_path, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            for row in csv_reader:
                cursor.execute("""
                    INSERT INTO customers (customer_id, password_hash, type)
                    VALUES (?, ?, ?)
                """, (row['customer_id'], row['password_hash'], row['type']))
                
        conn.commit()
        conn.close()
        logger.info("Successfully imported customer data")
        return True
        
    except Exception as e:
        logger.error(f"Error importing customer data: {str(e)}")
        return False
