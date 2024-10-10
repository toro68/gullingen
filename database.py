# database.py

import sqlite3
from contextlib import contextmanager
from config import DATABASE_PATH  # Anta at du har en mappe-sti til databasene i config.py

@contextmanager
def get_db_connection(db_name):
    conn = sqlite3.connect(f'{DATABASE_PATH}/{db_name}.db')
    try:
        yield conn
    finally:
        conn.close()