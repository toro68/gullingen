# Standard library imports
import logging
import os
import re
import secrets
import smtplib
import string
import json
import time as pytime
import requests
import numpy as np
import pandas as pd
import hashlib
from datetime import datetime
from contextlib import contextmanager
from datetime import datetime, timedelta, date, time
from typing import Union, List, Optional
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from statsmodels.nonparametric.smoothers_lowess import lowess

# Third-party imports
import pandas as pd
import sqlite3
from dateutil.parser import parse

# Streamlit import
import streamlit as st

# Sett opp logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Definer TZ direkte i db_utils.py
TZ = ZoneInfo("Europe/Oslo")

# Constants
STATION_ID = "SN46220"
API_URL = "https://frost.met.no/observations/v0.jsonld"
ELEMENTS = "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),max_wind_speed(wind_from_direction PT1H),max(wind_speed_of_gust PT1H),min(wind_speed P1M),wind_speed,surface_temperature,relative_humidity,dew_point_temperature"
TIME_RESOLUTION = "PT1H"
GPS_URL = "https://kart.irute.net/fjellbergsskardet_busses.json?_=1657373465172"

# Global STATUS_MAPPING
STATUS_MAPPING = {
    "Venter": "Pending",
    "Utført": "Completed",
    "Kansellert": "Cancelled"
}

# Definer SESSION_TIMEOUT
SESSION_TIMEOUT = 3600  # 1 time

# Hjelpefunksjoner og validering
def validate_date(date_string: str) -> bool:
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_time(time_string: str) -> bool:
    time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')
    return bool(time_pattern.match(time_string))

def validate_username(username: str) -> bool:
    # Tillat numeriske verdier, bokstaver, og noen spesialtegn
    username_pattern = re.compile(r'^[a-zA-Z0-9_\-., ]{1,50}$')
    return bool(username_pattern.match(str(username)))

def validate_stroing_table_structure():
    expected_columns = {
        'id': 'INTEGER',
        'bruker': 'TEXT',
        'bestillings_dato': 'TEXT',
        'onske_dato': 'TEXT',
        'kommentar': 'TEXT',
        'status': 'TEXT'
    }
    
    with get_stroing_connection() as conn:
        c = conn.cursor()
        c.execute("PRAGMA table_info(stroing_bestillinger)")
        table_info = c.fetchall()
        
        actual_columns = {col[1]: col[2] for col in table_info}
        
        if actual_columns != expected_columns:
            logger.error(f"Uventet tabellstruktur for stroing_bestillinger. Forventet: {expected_columns}, Faktisk: {actual_columns}")
            return False
        
        return True

def get_date_range(period):
    try:
        now = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)

        choice_map = {
            "Siste 7 dager": timedelta(days=7),
            "Siste 12 timer": timedelta(hours=12),
            "Siste 24 timer": timedelta(days=1),
            "Siste 4 timer": timedelta(hours=4),
            "Siden sist fredag": timedelta(days=(now.weekday() - 4) % 7),
            "Siden sist søndag": timedelta(days=(now.weekday() + 1) % 7)
        }

        if period == "Egendefinert periode":
            col1, col2 = st.columns(2)
            with col1:
                date_start = st.date_input("Startdato", now.date() - timedelta(days=7), key="custom_start_date")
            with col2:
                date_end = st.date_input("Sluttdato", now.date(), key="custom_end_date")

            if date_end < date_start:
                st.error("Sluttdatoen må være etter startdatoen.")
                return None, None

            start_time = datetime.combine(date_start, datetime.min.time()).replace(tzinfo=TZ)
            end_time = datetime.combine(date_end, datetime.max.time()).replace(tzinfo=TZ)

        elif period in choice_map:
            delta = choice_map[period]
            start_time = now - delta
            end_time = now

        else:
            st.error(f"Ugyldig periodevalg: {period}")
            return None, None

        return start_time, end_time

    except Exception as e:
        st.error(f"Feil i get_date_range: {str(e)}")
        return None, None

def is_active_booking(booking, current_date):
    if booking is None:
        return False
    
    ankomst = booking['ankomst'].date()
    avreise = booking['avreise'].date() if pd.notnull(booking['avreise']) else None
    
    if booking['abonnement_type'] == "Årsabonnement":
        return current_date.weekday() == 4 or ankomst == current_date
    elif booking['abonnement_type'] == "Ukentlig ved bestilling":
        return ankomst == current_date
    else:
        if avreise:
            return ankomst <= current_date <= avreise
        else:
            return ankomst == current_date

    return False

def get_status_text(row, has_active_booking):
    if has_active_booking:
        return "Aktiv bestilling"
    elif row['icon'] == 'star_red':
        return "Ukentlig ved bestilling"
    elif row['icon'] == 'star_white':
        return "Årsabonnement"
    else:
        return "Ingen brøyting"

def get_marker_properties(booking_type, is_active):
    if is_active:
        return 'red', 'circle'  # Aktiv bestilling
    elif booking_type == "Ukentlig ved bestilling":
        return 'orange', 'circle'  # Ukentlig ved bestilling
    elif booking_type == "Årsabonnement":
        return 'blue', 'circle'  # Årsabonnement
    else:
        return 'gray', 'circle'  # Ingen brøyting

def find_username_by_cabin_id(cabin_id):
    customer_db = load_customer_database()
    customer = customer_db[customer_db["Id"] == cabin_id]
    if not customer.empty:
        return f"Hytte: {customer.iloc[0]['Id']}"
    return f"Hytte: {cabin_id}"  # Fallback hvis ID ikke finnes i databasen

def get_passwords():
    return st.secrets["passwords"]

def get_customer_info(user_id):
    db = load_customer_database()
    customer = db[db['Id'].astype(str) == str(user_id)]
    if not customer.empty:
        return customer.iloc[0].to_dict()
    return None

def get_status_display(db_status):
    return next((k for k, v in STATUS_MAPPING.items() if v == db_status), "Ukjent")

def format_norwegian_date(date):
    return date.strftime("%d.%m.%Y") # Format the date as DD.MM.YYYY

def categorize_direction(degree):
    if pd.isna(degree):
        return 'Ukjent'
    degree = float(degree)
    wind_directions = {
        'N': (337.5, 22.5),
        'NØ': (22.5, 67.5),
        'Ø': (67.5, 112.5),
        'SØ': (112.5, 157.5),
        'S': (157.5, 202.5),
        'SV': (202.5, 247.5),
        'V': (247.5, 292.5),
        'NV': (292.5, 337.5)
    }
    for direction, (min_deg, max_deg) in wind_directions.items():
        if min_deg <= degree < max_deg or (direction == 'N' and (degree >= 337.5 or degree < 22.5)):
            return direction
    return 'Ukjent'

def neste_fredag():
    today = datetime.now(TZ).date()
    days_ahead = 4 - today.weekday()  # Fredag er 4
    if days_ahead <= 0:  # Hvis det er fredag eller senere, gå til neste uke
        days_ahead += 7
    return today + timedelta(days=days_ahead)

def get_cabin_coordinates():
    
    customer_db = load_customer_database()
    return [
        {
            "cabin_id": row["Id"],
            "name": row["Name"],
            "latitude": float(row["Latitude"]) if pd.notnull(row["Latitude"]) else None,
            "longitude": float(row["Longitude"]) if pd.notnull(row["Longitude"]) else None,
            "subscription": row["Subscription"]
        }
        for _, row in customer_db.iterrows()
        if pd.notnull(row["Latitude"]) and pd.notnull(row["Longitude"])
    ]
# Databasetilkoblinger og generelle spørringsfunksjoner
@contextmanager
def get_db_connection(db_name):
    conn = sqlite3.connect(f'{db_name}.db')
    try:
        yield conn
    finally:
        conn.close()

def get_feedback_connection():
    return get_db_connection('feedback')

def get_tunbroyting_connection():
    return get_db_connection('tunbroyting')

@contextmanager
def get_stroing_connection():
    conn = sqlite3.connect('stroing.db')
    try:
        yield conn
    finally:
        conn.close()

def execute_query(db_name, query, params=None):
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        conn.commit()
        return cursor

def fetch_data(db_name, query, params=None):
    with get_db_connection(db_name) as conn:
        if params:
            return pd.read_sql_query(query, conn, params=params)
        else:
            return pd.read_sql_query(query, conn)

def execute_many(db_name, query, params):
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, params)
        conn.commit()

## initialiseringsfunksjonene øverst i db_utils.py
def initialize_database():
    initialize_stroing_database()
    # Legg til initialisering for andre databaser her hvis nødvendig
    logger.info("Alle databaser initialisert")

def create_all_tables():
    tables = {
        'login_history': '''CREATE TABLE IF NOT EXISTS login_history
                            (id INTEGER PRIMARY KEY,
                             username TEXT,
                             login_time TEXT,
                             success INTEGER)''',
        'tunbroyting': '''CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger
                          (id INTEGER PRIMARY KEY,
                           bruker TEXT,
                           ankomst_dato TEXT,
                           ankomst_tid TEXT,
                           avreise_dato TEXT,
                           avreise_tid TEXT,
                           abonnement_type TEXT)''',
        'stroing': '''CREATE TABLE IF NOT EXISTS stroing_bestillinger
                      (id INTEGER PRIMARY KEY,
                       bruker TEXT,
                       bestillings_dato TEXT,
                       onske_dato TEXT,
                       kommentar TEXT,
                       status TEXT)'''
    }
    
    for db_name, query in tables.items():
        try:
            execute_query(db_name, query)
            logger.info(f"{db_name} table created or already exists.")
        except Exception as e:
            logger.error(f"Error creating {db_name} table: {str(e)}")
    
    logger.info("All tables have been created or verified.")

def initialize_stroing_database():
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                id INTEGER PRIMARY KEY,
                bruker TEXT NOT NULL,
                bestillings_dato TEXT NOT NULL,
                onske_dato TEXT NOT NULL
            )
        ''')
        conn.commit()
    logger.info("Stroing database er initialisert med ny struktur")
    
def ensure_stroing_table_exists():
    with get_stroing_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS stroing_bestillinger 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      bruker TEXT NOT NULL,
                      bestillings_dato TEXT NOT NULL,
                      onske_dato TEXT NOT NULL,
                      kommentar TEXT,
                      status TEXT NOT NULL DEFAULT 'Pending')''')
        conn.commit()
        
def update_stroing_database_schema():
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stroing_status_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bestilling_id INTEGER,
                old_status TEXT,
                new_status TEXT,
                changed_by TEXT,
                changed_at TEXT,
                FOREIGN KEY (bestilling_id) REFERENCES stroing_bestillinger(id)
            )
        ''')
        conn.commit()

def update_stroing_bestillinger_table():
    try:
        with get_stroing_connection() as conn:
            cursor = conn.cursor()
            
            # Execute the SQL commands
            cursor.executescript('''
                -- Create backup
                CREATE TABLE IF NOT EXISTS stroing_bestillinger_backup AS SELECT * FROM stroing_bestillinger;

                -- Drop existing table
                DROP TABLE IF EXISTS stroing_bestillinger;

                -- Create new table
                CREATE TABLE stroing_bestillinger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bruker TEXT NOT NULL,
                    bestillings_dato TEXT NOT NULL,
                    onske_dato TEXT NOT NULL,
                    kommentar TEXT,
                    status TEXT NOT NULL DEFAULT 'Pending',
                    utfort_dato TEXT,
                    utfort_av TEXT,
                    fakturert BOOLEAN DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                -- Copy data from backup
                INSERT INTO stroing_bestillinger (
                    bruker, bestillings_dato, onske_dato, kommentar, status, 
                    utfort_dato, utfort_av, fakturert, created_at, updated_at
                )
                SELECT 
                    bruker, bestillings_dato, onske_dato, kommentar, status,
                    NULL, NULL, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM stroing_bestillinger_backup;

                -- Create indexes
                CREATE INDEX idx_stroing_bruker ON stroing_bestillinger(bruker);
                CREATE INDEX idx_stroing_onske_dato ON stroing_bestillinger(onske_dato);
                CREATE INDEX idx_stroing_status ON stroing_bestillinger(status);
            ''')
            
            conn.commit()
            logger.info("stroing_bestillinger table updated successfully")
            return True
    except Exception as e:
        logger.error(f"Error updating stroing_bestillinger table: {str(e)}")
        return False

def update_login_history_table():
    try:
        query = "PRAGMA table_info(login_history)"
        columns = fetch_data('login_history', query)
        
        # Sjekk om 'success' kolonnen eksisterer
        if not any(col['name'] == 'success' for col in columns):
            alter_query = "ALTER TABLE login_history ADD COLUMN success INTEGER"
            execute_query('login_history', alter_query)
            logger.info("Added 'success' column to login_history table")
    except Exception as e:
        logger.error(f"Error updating login_history table: {str(e)}")
        
# Bruker- og autentiseringsrelaterte funksjoner
def load_customer_database():
    try:
        customer_data = st.secrets["customer_database"]["data"]
        logger.info("Raw customer data retrieved from secrets")
        
        try:
            decoded_data = json.loads(customer_data)
        except json.JSONDecodeError as e:
            # Forsøk å reparere JSON-dataen
            fixed_data = customer_data.replace('",\n    "', '": null,\n    "')
            decoded_data = json.loads(fixed_data)
            logger.warning(f"Fixed JSON decode error: {str(e)}")
        
        df = pd.DataFrame(decoded_data)
        logger.info(f"DataFrame created. Columns: {df.columns.tolist()}")
        
        # Konverter 'Id' til string for å sikre konsistens
        df['Id'] = df['Id'].astype(str)
        
        # Konverter 'Latitude' og 'Longitude' til float, med NaN for ugyldige verdier
        df['Latitude'] = pd.to_numeric(df['Latitude'], errors='coerce')
        df['Longitude'] = pd.to_numeric(df['Longitude'], errors='coerce')
        
        logger.info(f"Total number of customers: {len(df)}")
        return df

    except Exception as e:
        logger.error(f"Error in load_customer_database: {str(e)}", exc_info=True)
        return pd.DataFrame({'Id': [], 'Name': [], 'Type': []})  # Return a DataFrame with expected columns

def get_customer_name(user_id):
    db = load_customer_database()
    user = db[db['Id'].astype(str) == str(user_id)]
    if not user.empty:
        return user.iloc[0]['Name']
    return None

def get_customer_id(identifier):
    customer_db = load_customer_database()
    if identifier in customer_db['Id'].values:
        return identifier
    customer = customer_db[customer_db['Name'] == identifier]
    if not customer.empty:
        return customer.iloc[0]['Id']
    return None

def authenticate_user(user_id, password):
    passwords = st.secrets["passwords"]
    if str(user_id) in passwords and passwords[str(user_id)] == password:
        return True
    return False

def get_user_subscription(user_id):
    db = load_customer_database()
    user = db[db['Id'].astype(str) == str(user_id)]
    if not user.empty:
        return user.iloc[0]['Subscription']
    return "Ingen abonnement"

def get_customer_by_id(user_id):
    customer_db = load_customer_database()
    
    # Sjekk om 'Id' eksisterer, hvis ikke, prøv 'id'
    id_column = 'Id' if 'Id' in customer_db.columns else 'id'
    
    if id_column not in customer_db.columns:
        logger.error(f"Kunne ikke finne 'Id' eller 'id' kolonne i kundedatabasen")
        return None
    
    customer = customer_db[customer_db[id_column].astype(str) == str(user_id)]
    if not customer.empty:
        return customer.iloc[0].to_dict()
    return None
    
def generate_credentials(customer):
    # Generer brukernavn basert på Id
    username = f"user{customer['Id']}"
    
    # Generer midlertidig passord
    alphabet = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(alphabet) for i in range(12))
    
    return username, temp_password

# Sikkerhetsfunksjoner
def generate_secure_code():
    return hashlib.sha256(os.urandom(32)).hexdigest()[:8]

def validate_code(stored_code, provided_code):
    return hmac.compare_digest(stored_code, provided_code)

def check_session_timeout():
    if 'last_activity' in st.session_state:
        if pytime.time() - st.session_state.last_activity > SESSION_TIMEOUT:
            st.session_state.authenticated = False
            st.session_state.username = None
            st.warning("Din sesjon har utløpt. Vennligst logg inn på nytt.")
    st.session_state.last_activity = pytime.time()
 
# Datavalidering og -henting:
def get_customer_name(cabin_id):
    customer_db = load_customer_database()
    customer = customer_db[customer_db['Id'] == str(cabin_id)]
    if not customer.empty:
        return customer.iloc[0]['Name']
    return "Unknown"

def send_credentials_email(customer, username, temp_password):
    try:
        sender_email = st.secrets["email"]["sender_address"]
        sender_password = st.secrets["email"]["sender_password"]

        message = MIMEMultipart("alternative")
        message["Subject"] = "Dine påloggingsdetaljer for Fjellbergsskardet-appen"
        message["From"] = sender_email
        message["To"] = customer['Email']

        text = f"""\
        Hei {customer['Name']},

        Her er dine påloggingsdetaljer for Fjellbergsskardet-appen:

        Brukernavn: {username}
        Midlertidig passord: {temp_password}

        Vennligst logg inn og endre passordet ditt ved første pålogging.

        Hvis du har spørsmål, ta kontakt.

        Mvh Fjellbergsskardet Drift 
        """

        part = MIMEText(text, "plain")
        message.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer['Email'], message.as_string())
        
        logger.info(f"E-post sendt til {customer['Email']} for bruker {username}")
        return True
    except Exception as e:
        logger.error(f"Feil ved sending av e-post til {customer['Email']}: {str(e)}")
        return False

# Databaseadministrasjon og vedlikehold
# def reset_stroing_database():
#     with get_stroing_connection() as conn:
#         cursor = conn.cursor()
#         # Slett alle eksisterende data
#         cursor.execute("DELETE FROM stroing_bestillinger")
#         # Nullstill auto-increment teller
#         cursor.execute("DELETE FROM sqlite_sequence WHERE name='stroing_bestillinger'")
#         conn.commit()
#     logger.info("Stroing database has been reset")

def update_database_schema():
    with get_db_connection('tunbroyting') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger
                     (id INTEGER PRIMARY KEY,
                      bruker TEXT,
                      ankomst_dato DATE,
                      ankomst_tid TIME,
                      avreise_dato DATE,
                      avreise_tid TIME,
                      abonnement_type TEXT)''')
        conn.commit()

    logger.info("Database schemas updated successfully.")

def check_cabin_user_consistency():
    logger.info("Sjekker konsistens mellom customer_database og passwords")
    
    customer_db = load_customer_database()
    passwords = st.secrets["passwords"]
    
    if customer_db.empty:
        logger.warning("Customer database is empty")
        return

    for user_id in passwords:
        if user_id not in customer_db['Id'].values:
            logger.warning(f"Passord funnet for ID {user_id}, men ingen tilsvarende kunde i databasen")
    
    for _, customer in customer_db.iterrows():
        if str(customer['Id']) not in passwords:
            logger.warning(f"Kunde-ID: {customer['Id']} har ikke et passord")

    logger.info("Konsistenssjekk fullført")

def validate_customers_and_passwords():
    customer_db = load_customer_database()
    passwords = st.secrets["passwords"]
    
    logger.info("Validating customers and passwords")
    
    for user_id, password in passwords.items():
        if user_id not in customer_db['Id'].values:
            logger.warning(f"Password found for ID {user_id}, but no corresponding customer in database")
    
    for _, customer in customer_db.iterrows():
        if customer['Id'] not in passwords:
            logger.warning(f"Customer found with ID {customer['Id']}, but no corresponding password")

    logger.info("Customer and password validation complete")

# Logging og statusendringer
def log_status_change(bestilling_id, old_status, new_status, changed_by):
    try:
        query = """
        INSERT INTO stroing_status_log (bestilling_id, old_status, new_status, changed_by, changed_at)
        VALUES (?, ?, ?, ?, ?)
        """
        params = (bestilling_id, old_status, new_status, changed_by, datetime.now(TZ).isoformat())
        execute_query('stroing', query, params)
        logger.info(f"Status endret for bestilling {bestilling_id} fra {old_status} til {new_status} av {changed_by}")
    except Exception as e:
        logger.error(f"Feil ved logging av statusendring: {str(e)}")
        
def log_failed_attempt(user_id):
    try:
        current_time = datetime.now(TZ).isoformat()
        query = "INSERT INTO login_history (username, login_time, success) VALUES (?, ?, ?)"
        execute_query('login_history', query, (user_id, current_time, 0))
        logger.warning(f"Failed login attempt for user: {user_id}")
    except Exception as e:
        logger.error(f"Error logging failed login attempt: {str(e)}")

def log_successful_attempt(user_id):
    try:
        current_time = datetime.now(TZ).isoformat()
        query = "INSERT INTO login_history (username, login_time, success) VALUES (?, ?, ?)"
        execute_query('login_history', query, (user_id, current_time, 1))
        logger.info(f"Successful login for user: {user_id}")
    except Exception as e:
        logger.error(f"Error logging successful login: {str(e)}")

# Login History - create
def log_login(username, success=True):
    try:
        login_time = datetime.now(TZ).isoformat()
        query = "INSERT INTO login_history (username, login_time, success) VALUES (?, ?, ?)"
        execute_query('login_history', query, (username, login_time, 1 if success else 0))
        logger.info(f"{'Vellykket' if success else 'Mislykket'} innlogging for bruker: {username}")
    except Exception as e:
        logger.error(f"Feil ved logging av innlogging: {str(e)}")

def get_login_history(start_date, end_date):
    with get_db_connection('login_history') as conn:
        query = "SELECT * FROM login_history WHERE login_time BETWEEN ? AND ? ORDER BY login_time DESC"
        df = pd.read_sql_query(query, conn, params=(start_date.isoformat(), end_date.isoformat()))
    df['login_time'] = pd.to_datetime(df['login_time']).dt.tz_convert(TZ)
    return df

## CRUD Operations for hver tabell
# Tunbrøyting - create
def lagre_bestilling(username: str, ankomst_dato: str, ankomst_tid: str, 
                     avreise_dato: str, avreise_tid: str, abonnement_type: str) -> bool:
    # Konverter username til string hvis det ikke allerede er det
    username = str(username)
    
    # Valider input
    if not validate_username(username):
        logger.error(f"Ugyldig brukernavn for tunbrøyting bestilling: {username}")
        return False
    
    # Konverter og valider datoer og tider
    try:
        ankomst_dato = pd.to_datetime(ankomst_dato).date()
        ankomst_tid = pd.to_datetime(ankomst_tid).time()
        
        if avreise_dato:
            avreise_dato = pd.to_datetime(avreise_dato).date()
        else:
            avreise_dato = None
        
        if avreise_tid:
            avreise_tid = pd.to_datetime(avreise_tid).time()
        else:
            avreise_tid = None
    except ValueError as e:
        logger.error(f"Ugyldig dato eller tid format for tunbrøyting bestilling: {str(e)}")
        return False
    
    if abonnement_type not in ["Årsabonnement", "Ukentlig ved bestilling"]:
        logger.error(f"Ugyldig abonnement type: {abonnement_type}")
        return False

    try:
        with get_tunbroyting_connection() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO tunbroyting_bestillinger 
                         (bruker, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type)
                         VALUES (?, ?, ?, ?, ?, ?)''', 
                      (username, 
                       ankomst_dato.isoformat(), 
                       ankomst_tid.isoformat() if ankomst_tid else None,
                       avreise_dato.isoformat() if avreise_dato else None, 
                       avreise_tid.isoformat() if avreise_tid else None, 
                       abonnement_type))
            conn.commit()
        logger.info(f"Ny tunbrøyting bestilling lagret for bruker: {username}")
        return True
    except Exception as e:
        logger.error(f"Feil ved lagring av tunbrøyting bestilling for bruker {username}: {str(e)}")
        return False

def save_booking(customer, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type):
    try:
        if lagre_bestilling(
            customer['Id'],
            ankomst_dato.isoformat(), 
            ankomst_tid.isoformat(),
            avreise_dato.isoformat() if avreise_dato else None,
            avreise_tid.isoformat() if avreise_tid else None,
            abonnement_type
        ):
            st.success("Bestilling av tunbrøyting er registrert!")
        else:
            st.error("Det oppstod en feil ved lagring av bestillingen. Vennligst prøv igjen senere.")
    except Exception as e:
        st.error(f"En uventet feil oppstod: {str(e)}")
        logger.error(f"Feil ved lagring av bestilling for bruker {customer['Id']}: {str(e)}")

# Tunbrøyting - read
def hent_tunbroyting_bestillinger():
    query = "SELECT * FROM tunbroyting_bestillinger"
    return fetch_data('tunbroyting', query)

def hent_bruker_bestillinger(username):
    with get_tunbroyting_connection() as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE bruker = ? 
        ORDER BY ankomst_dato DESC, ankomst_tid DESC
        """
        df = pd.read_sql_query(query, conn, params=(username,))
    return df

def filter_tunbroyting_bestillinger(bestillinger, filters):
    filtered = bestillinger.copy()
    current_date = datetime.now(TZ).date()
    
    if filters.get('vis_type') == 'today':
        filtered = filtered[
            ((filtered['abonnement_type'] == "Årsabonnement") & 
             ((current_date.weekday() == 4) | (filtered['ankomst_dato'].dt.date == current_date))) |
            ((filtered['abonnement_type'] == "Ukentlig ved bestilling") & 
             (filtered['ankomst_dato'].dt.date == current_date))
        ]
    elif filters.get('vis_type') == 'active':
        filtered = filtered[
            (filtered['abonnement_type'] == "Årsabonnement") |
            ((filtered['abonnement_type'] == "Ukentlig ved bestilling") & 
             (filtered['ankomst_dato'].dt.date >= current_date))
        ]
    
    # Resten av filtreringen forblir uendret
    if filters.get('start_date'):
        filtered = filtered[filtered['ankomst_dato'].dt.date >= filters['start_date']]
    
    if filters.get('end_date'):
        filtered = filtered[filtered['ankomst_dato'].dt.date <= filters['end_date']]
    
    if filters.get('abonnement_type'):
        filtered = filtered[filtered['abonnement_type'].isin(filters['abonnement_type'])]
    
    if filters.get('rode'):
        filtered = filtered[filtered['rode'].isin(filters['rode'])]
        st.write(f"Totalt antall bestillinger: {len(bestillinger)}")
        st.write(f"Antall filtrerte bestillinger: {len(filtered_bestillinger)}")
        st.write(f"Antall dagens bestillinger: {len(dagens_bestillinger)}")
        st.write(f"Antall aktive bestillinger: {len(aktive_bestillinger)}")
    
    return filtered

def get_booking_status(user_id, bestillinger):
    if user_id in bestillinger['bruker'].astype(str).values:
        booking = bestillinger[bestillinger['bruker'].astype(str) == str(user_id)].iloc[0]
        return booking['abonnement_type'], booking['ankomst_dato']
    return None, None

def hent_dagens_bestillinger():
    today = datetime.now(TZ).date()
    with get_tunbroyting_connection() as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE date(ankomst_dato) = ? OR (date(ankomst_dato) <= ? AND date(avreise_dato) >= ?)
        """
        df = pd.read_sql_query(query, conn, params=(today, today, today))
    
    df['ankomst_dato'] = pd.to_datetime(df['ankomst_dato'])
    df['avreise_dato'] = pd.to_datetime(df['avreise_dato'])
    
    return df

def count_bestillinger():
    try:
        with get_tunbroyting_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tunbroyting_bestillinger")
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Feil ved telling av bestillinger: {str(e)}")
        return 0

def get_max_bestilling_id():
    try:
        with get_tunbroyting_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(id) FROM tunbroyting_bestillinger")
            max_id = cursor.fetchone()[0]
            return max_id if max_id is not None else 0
    except Exception as e:
        logger.error(f"Feil ved henting av maksimum bestillings-ID: {str(e)}")
        return 0

def hent_bestillinger():
    try:
        with get_tunbroyting_connection() as conn:
            query = "SELECT * FROM tunbroyting_bestillinger"
            df = pd.read_sql_query(query, conn)
        
        if df.empty:
            logger.warning("Ingen bestillinger funnet i databasen.")
            return pd.DataFrame()

        logger.info(f"Hentet {len(df)} bestillinger fra databasen.")

        # Konverter dato- og tidskolonner
        for col in ['ankomst_dato', 'avreise_dato']:
            df[col] = pd.to_datetime(df[col], errors='coerce')

        for col in ['ankomst_tid', 'avreise_tid']:
            df[col] = pd.to_datetime(df[col], format='%H:%M:%S', errors='coerce').dt.time

        # Kombiner dato og tid til datetime-objekter
        df['ankomst'] = df.apply(lambda row: pd.Timestamp.combine(row['ankomst_dato'], row['ankomst_tid']) if pd.notnull(row['ankomst_dato']) and pd.notnull(row['ankomst_tid']) else pd.NaT, axis=1)
        df['avreise'] = df.apply(lambda row: pd.Timestamp.combine(row['avreise_dato'], row['avreise_tid']) if pd.notnull(row['avreise_dato']) and pd.notnull(row['avreise_tid']) else pd.NaT, axis=1)

        # Sett tidssone
        for col in ['ankomst', 'avreise']:
            df[col] = df[col].dt.tz_localize(TZ, ambiguous='NaT', nonexistent='NaT')

        logger.info("Bestillinger behandlet og returnert.")
        return df

    except Exception as e:
        logger.error(f"Feil ved henting av bestillinger: {str(e)}", exc_info=True)
        return pd.DataFrame()

def hent_dagens_bestillinger():
    today = datetime.now(TZ).date()
    with get_tunbroyting_connection() as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE date(ankomst_dato) = ? OR (date(ankomst_dato) <= ? AND date(avreise_dato) >= ?)
        """
        df = pd.read_sql_query(query, conn, params=(today, today, today))
    
    df['ankomst_dato'] = pd.to_datetime(df['ankomst_dato'])
    df['avreise_dato'] = pd.to_datetime(df['avreise_dato'])
    
    return df

def hent_aktive_bestillinger():
    today = datetime.now(TZ).date()
    with get_tunbroyting_connection() as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE date(ankomst_dato) >= ? OR (date(ankomst_dato) <= ? AND date(avreise_dato) >= ?)
        OR (abonnement_type = 'Årsabonnement')
        """
        df = pd.read_sql_query(query, conn, params=(today, today, today))
    
    df['ankomst_dato'] = pd.to_datetime(df['ankomst_dato'])
    df['avreise_dato'] = pd.to_datetime(df['avreise_dato'])
    
    return df

def hent_bestilling(bestilling_id):
    try:
        with get_tunbroyting_connection() as conn:
            query = "SELECT * FROM tunbroyting_bestillinger WHERE id = ?"
            df = pd.read_sql_query(query, conn, params=(bestilling_id,))
        
        if df.empty:
            logger.warning(f"Ingen bestilling funnet med ID {bestilling_id}")
            return None

        bestilling = df.iloc[0]

        # Konverter dato- og tidskolonner
        for col in ['ankomst_dato', 'avreise_dato']:
            bestilling[col] = pd.to_datetime(bestilling[col], errors='coerce')

        for col in ['ankomst_tid', 'avreise_tid']:
            bestilling[col] = pd.to_datetime(bestilling[col], format='%H:%M:%S', errors='coerce').time()

        logger.info(f"Hentet bestilling med ID {bestilling_id}")
        return bestilling

    except Exception as e:
        logger.error(f"Feil ved henting av bestilling {bestilling_id}: {str(e)}", exc_info=True)
        return None
    
# Tunbrøyting - update
def rediger_bestilling(bestilling_id, nye_data):
    try:
        query = '''UPDATE tunbroyting_bestillinger 
                   SET bruker = ?, ankomst_dato = ?, ankomst_tid = ?, 
                       avreise_dato = ?, avreise_tid = ?, abonnement_type = ?
                   WHERE id = ?'''
        
        # Safely convert date and time values
        ankomst_dato = nye_data['ankomst_dato'].isoformat() if isinstance(nye_data['ankomst_dato'], datetime) else nye_data['ankomst_dato']
        ankomst_tid = nye_data['ankomst_tid'].isoformat() if isinstance(nye_data['ankomst_tid'], time) else nye_data['ankomst_tid']
        avreise_dato = nye_data['avreise_dato'].isoformat() if isinstance(nye_data['avreise_dato'], datetime) else nye_data['avreise_dato']
        avreise_tid = nye_data['avreise_tid'].isoformat() if isinstance(nye_data['avreise_tid'], time) else nye_data['avreise_tid']
        
        params = (nye_data['bruker'], 
                  ankomst_dato, 
                  ankomst_tid, 
                  avreise_dato, 
                  avreise_tid, 
                  nye_data['abonnement_type'], 
                  bestilling_id)
        
        execute_query('tunbroyting', query, params)
        logger.info(f"Tunbrøyting bestilling {bestilling_id} oppdatert")
        return True
    except Exception as e:
        logger.error(f"Feil ved oppdatering av tunbrøyting bestilling {bestilling_id}: {str(e)}")
        return False

def oppdater_bestilling_i_database(bestilling_id, nye_data):
    try:
        query = '''UPDATE tunbroyting_bestillinger 
                   SET bruker = ?, ankomst_dato = ?, ankomst_tid = ?, 
                       avreise_dato = ?, avreise_tid = ?, abonnement_type = ?
                   WHERE id = ?'''
        params = (nye_data['bruker'], 
                  nye_data['ankomst_dato'].isoformat(), 
                  nye_data['ankomst_tid'].isoformat(),
                  nye_data['avreise_dato'].isoformat() if nye_data['avreise_dato'] else None, 
                  nye_data['avreise_tid'].isoformat() if nye_data['avreise_tid'] else None, 
                  nye_data['abonnement_type'], 
                  bestilling_id)
        execute_query('tunbroyting', query, params)
        logger.info(f"Bestilling {bestilling_id} oppdatert")
        return True
    except Exception as e:
        logger.error(f"Feil ved oppdatering av bestilling {bestilling_id}: {str(e)}")
        return False
    
# Tunbrøyting - delete
def slett_bestilling(bestilling_id):
    try:
        query = "DELETE FROM tunbroyting_bestillinger WHERE id = ?"
        execute_query('tunbroyting', query, (bestilling_id,))
        logger.info(f"Slettet bestilling med id: {bestilling_id}")
        return True
    except Exception as e:
        logger.error(f"Error deleting bestilling with id {bestilling_id}: {str(e)}")
        return False

# Strøing - create
def lagre_stroing_bestilling(username: str, onske_dato: str) -> bool:
    try:
        username = str(username)
        
        if not validate_username(username):
            logger.error(f"Ugyldig brukernavn for strøing bestilling: {username}")
            return False
        
        if not validate_date(onske_dato):
            logger.error(f"Ugyldig dato format for strøing bestilling: {onske_dato}")
            return False
        
        with get_stroing_connection() as conn:
            c = conn.cursor()
            bestillings_dato = datetime.now(TZ).isoformat()
            
            c.execute('''
            INSERT INTO stroing_bestillinger 
            (bruker, bestillings_dato, onske_dato)
            VALUES (?, ?, ?)
            ''', (username, bestillings_dato, onske_dato))
            
            conn.commit()
        
        logger.info(f"Ny strøing bestilling lagret for bruker: {username}")
        return True
    except Exception as e:
        logger.error(f"Feil ved lagring av strøing bestilling: {str(e)}")
        return False

# Strøing - read
def hent_stroing_bestillinger():
    try:
        with get_stroing_connection() as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            ORDER BY onske_dato DESC, bestillings_dato DESC
            """
            df = pd.read_sql_query(query, conn)
        
        # Konverter dato-kolonner til datetime
        for col in ['bestillings_dato', 'onske_dato']:
            df[col] = pd.to_datetime(df[col])
        
        return df
    except Exception as e:
        logger.error(f"Feil ved henting av strøing-bestillinger: {str(e)}")
        return pd.DataFrame()

def hent_bruker_stroing_bestillinger(username):
    try:
        with get_stroing_connection() as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            WHERE bruker = ? 
            ORDER BY bestillings_dato DESC
            """
            df = pd.read_sql_query(query, conn, params=(username,))
        
        # Konverter dato-kolonner til datetime
        for col in ['bestillings_dato', 'onske_dato']:
            df[col] = pd.to_datetime(df[col])
        
        return df
    except Exception as e:
        logger.error(f"Feil ved henting av strøing-bestillinger for bruker {username}: {str(e)}")
        return pd.DataFrame()

def hent_stroing_bestilling(bestilling_id):
    try:
        with get_stroing_connection() as conn:
            query = "SELECT * FROM stroing_bestillinger WHERE id = ?"
            df = pd.read_sql_query(query, conn, params=(bestilling_id,))
        
        if len(df) == 1:
            return df.iloc[0]
        else:
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error retrieving stroing booking with id {bestilling_id}: {str(e)}")
        return pd.DataFrame()

def count_stroing_bestillinger():
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stroing_bestillinger")
        return cursor.fetchone()[0] # Returner antall rader i tabellen
       
# Strøing - update
def update_stroing_status(bestilling_id, new_status, utfort_av=None):
    try:
        with get_stroing_connection() as conn:
            cursor = conn.cursor()
            
            # Hent gjeldende status
            cursor.execute("SELECT status FROM stroing_bestillinger WHERE id = ?", (bestilling_id,))
            current_status = cursor.fetchone()[0]
            
            # Oppdater status
            db_status = STATUS_MAPPING.get(new_status)
            if db_status is None:
                return False, "Ugyldig status"
            
            current_time = datetime.now(TZ).isoformat()
            
            cursor.execute("""
                UPDATE stroing_bestillinger 
                SET status = ?, 
                    updated_at = ?, 
                    utfort_dato = CASE WHEN ? = 'Completed' THEN ? ELSE utfort_dato END,
                    utfort_av = CASE WHEN ? = 'Completed' THEN ? ELSE utfort_av END
                WHERE id = ?
            """, (db_status, current_time, db_status, current_time, db_status, utfort_av, bestilling_id))
            
            # Logg statusendring
            cursor.execute("""
                INSERT INTO stroing_status_log (bestilling_id, old_status, new_status, changed_by, changed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (bestilling_id, current_status, db_status, utfort_av, current_time))
            
            conn.commit()
            
            return True, "Status oppdatert vellykket"
    except Exception as e:
        return False, str(e)

# Strøing - delete
def slett_stroing_bestilling(bestilling_id):
    try:
        with get_stroing_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stroing_bestillinger WHERE id = ?", (bestilling_id,))
            affected_rows = cursor.rowcount
            conn.commit()
        
        if affected_rows > 0:
            logger.info(f"Slettet strøingsbestilling med id: {bestilling_id}")
            return True
        else:
            logger.warning(f"Ingen strøingsbestilling funnet med id: {bestilling_id}")
            return False
    except Exception as e:
        logger.error(f"Feil ved sletting av strøingsbestilling med id {bestilling_id}: {str(e)}")
        return False

def verify_stroing_data():
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stroing_bestillinger")
        data = cursor.fetchall()
        logger.info(f"Current entries in stroing_bestillinger: {len(data)}")
        for row in data:
            logger.info(f"Row: {row}")

# Feedback - create ??

# Feedback - read
def get_feedback(start_date, end_date, include_hidden=False, cabin_identifier=None):
    try:
        query = """
        SELECT id, type, datetime, comment, innsender, status, status_changed_by, status_changed_at, hidden
        FROM feedback 
        WHERE 1=1
        """
        params = []
        
        if start_date and end_date:
            query += " AND datetime BETWEEN ? AND ?"
            params.extend([start_date, end_date])
        
        if not include_hidden:
            query += " AND hidden = 0"
        
        if cabin_identifier:
            query += " AND innsender = ?"
            params.append(cabin_identifier)
        
        query += " ORDER BY datetime DESC"
        
        # st.write(f"Debug: get_feedback query: {query}")
        # st.write(f"Debug: params: {params}")
        
        df = fetch_data('feedback', query, params=params)
        
        # st.write(f"Debug: Fetched {len(df)} rows from feedback database")
        
        # Convert datetime columns
        df['datetime'] = pd.to_datetime(df['datetime'], utc=True).dt.tz_convert(TZ)
        if 'status_changed_at' in df.columns:
            df['status_changed_at'] = pd.to_datetime(df['status_changed_at'], utc=True).dt.tz_convert(TZ)
        
        logger.info(f"Successfully fetched {len(df)} feedback entries")
        return df
    except Exception as e:
        logger.error(f"Error in get_feedback: {str(e)}", exc_info=True)
        st.write(f"Debug: Error in get_feedback: {str(e)}")
        return pd.DataFrame()  # Return an empty DataFrame on error

# Feedback - update
def hide_feedback(feedback_id):
    try:
        query = "UPDATE feedback SET hidden = 1 WHERE id = ?"
        execute_query('feedback', query, (feedback_id,))
        logger.info(f"Skjulte feedback med id: {feedback_id}")
        return True
    except Exception as e:
        logger.error(f"Feil ved skjuling av feedback: {str(e)}")
        return False

def update_feedback_status(feedback_id, new_status, changed_by):
    try:
        query = """UPDATE feedback 
                   SET status = ?, status_changed_by = ?, status_changed_at = ? 
                   WHERE id = ?"""
        changed_at = datetime.now(TZ).isoformat()
        params = (new_status, changed_by, changed_at, feedback_id)
        execute_query('feedback', query, params)
        
        logger.info(f"Status updated for feedback {feedback_id}: {new_status}")
        return True
    except Exception as e:
        logger.error(f"Error updating feedback status: {str(e)}", exc_info=True)
        return False

# Feedback - delete    
def delete_feedback(feedback_id):
    try:
        query = "DELETE FROM feedback WHERE id = ?"
        result = execute_query('feedback', query, (feedback_id,))
        if result:
            affected_rows = result.rowcount
            if affected_rows > 0:
                logger.info(f"Deleted feedback with id: {feedback_id}")
                return True
            else:
                logger.warning(f"No feedback found with id: {feedback_id}")
                return "not_found"
        else:
            logger.warning(f"No result returned when deleting feedback with id: {feedback_id}")
            return False
    except Exception as e:
        logger.error(f"Error deleting feedback with id {feedback_id}: {str(e)}")
        return False

# Advarsler - create
def save_alert(alert_type: str, message: str, expiry_date: Optional[str], 
               target_group: List[str], created_by: str) -> bool:
    if not all([validate_username(created_by), 
                expiry_date is None or validate_date(expiry_date)]):
        logger.error(f"Ugyldig input for alert opprettelse av: {created_by}")
        return False
    
    if len(message) > 1000:  # Eksempel på lengdebegrensning
        logger.error(f"Alert melding for lang, opprettet av: {created_by}")
        return False
    
    if not target_group or not all(isinstance(group, str) for group in target_group):
        logger.error(f"Ugyldig målgruppe for alert, opprettet av: {created_by}")
        return False

    query = """
    INSERT INTO feedback (type, comment, datetime, innsender, status, is_alert, display_on_weather, expiry_date, target_group)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        f"Admin varsel: {alert_type}", 
        message, 
        datetime.now(TZ), 
        created_by, 
        "Aktiv", 
        1, 
        1, 
        expiry_date, 
        ','.join(target_group)
    )
    try:
        execute_query('feedback', query, params)
        logger.info(f"Alert saved successfully by {created_by}")
        return True
    except Exception as e:
        logger.error(f"An error occurred while saving the alert: {e}")
        return False

# Advarsler - read
def get_alerts(start_date=None, end_date=None, include_expired=False):
    query = """
    SELECT * FROM feedback 
    WHERE is_alert = 1
    """
    params = []
    
    if start_date:
        query += " AND datetime >= ?"
        params.append(start_date)
    
    if end_date:
        query += " AND datetime <= ?"
        params.append(end_date)
    
    if not include_expired:
        query += " AND (expiry_date IS NULL OR expiry_date >= ?)"
        params.append(datetime.now(TZ).isoformat())
    
    query += " ORDER BY datetime DESC"
    
    return fetch_data('feedback', query, params)

# Advarsler - update
def update_alert_status(alert_id, new_status, updated_by):
    query = "UPDATE feedback SET status = ? WHERE id = ? AND is_alert = 1"
    try:
        execute_query('feedback', query, (new_status, alert_id))
        logger.info(f"Alert {alert_id} status updated to {new_status} by {updated_by}")
        return True
    except Exception as e:
        logger.error(f"An error occurred while updating alert status: {e}")
        return False
    
# Advarsler - delete
def delete_alert(alert_id):
    query = "DELETE FROM feedback WHERE id = ? AND is_alert = 1"
    try:
        execute_query('feedback', query, (alert_id,))
        logger.info(f"Alert {alert_id} deleted successfully")
        return True
    except Exception as e:
        logger.error(f"An error occurred while deleting the alert: {e}")
        return False

# GPS og koordinatrelaterte funksjoner     
def get_gps_coordinates(user_id):
    customer = get_customer_by_id(user_id)
    if customer is not None:
        return customer['Latitude'], customer['Longitude']
    return None, None

def fetch_gps_data():
    try:
        response = requests.get(GPS_URL)
        response.raise_for_status()
        gps_data = response.json()
        all_eq_dicts = gps_data.get('features', [])
        
        gps_entries = []
        for eq_dict in all_eq_dicts:
            date_str = eq_dict['properties'].get('Date')
            if date_str:
                try:
                    gps_entry = {
                        'BILNR': eq_dict['properties'].get('BILNR'),
                        'Date': datetime.strptime(date_str, '%H:%M:%S %d.%m.%Y').replace(tzinfo=TZ)
                    }
                    gps_entries.append(gps_entry)
                except ValueError as e:
                    logger.error(f"Date parsing error: {e}")
        
        return gps_entries
    except requests.RequestException as e:
        logger.error(f"Error fetching GPS data: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error in fetch_gps_data: {e}")
        return []

def fetch_and_process_data(client_id, date_start, date_end):
    try:
        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start}/{date_end}"
        }
        response = requests.get(API_URL, params=params, auth=(client_id, ""))
        response.raise_for_status()
        data = response.json()

        if not data or not data.get('data'):
            raise ValueError("Ingen data returnert fra API-et")

        df = pd.DataFrame([
            {
                'timestamp': datetime.fromisoformat(item['referenceTime'].rstrip('Z')),
                'air_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'air_temperature'), np.nan),
                'precipitation_amount': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'sum(precipitation_amount PT1H)'), np.nan),
                'surface_snow_thickness': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_snow_thickness'), np.nan),
                'wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'wind_speed'), np.nan),
                'max_wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'max(wind_speed_of_gust PT1H)'), np.nan),
                'min_wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'min(wind_speed P1M)'), np.nan),
                'wind_from_direction': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'max_wind_speed(wind_from_direction PT1H)'), np.nan),
                'surface_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_temperature'), np.nan),
                'relative_humidity': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'relative_humidity'), np.nan),
                'dew_point_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'dew_point_temperature'), np.nan)
            }
            for item in data['data']
        ]).set_index('timestamp')

        # Resten av databehandlingen...

        return {'df': df}

    except Exception as e:
        logger.error(f"Feil i fetch_and_process_data: {str(e)}")
        return {'error': str(e)}
    
def get_weather_data_for_period(client_id, start_date, end_date):
    return fetch_and_process_data(client_id, start_date, end_date)

# Funksjoner relatert til værdatainnhenting og -prosessering:
def fetch_and_process_data(client_id, date_start, date_end):
    try:
        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start}/{date_end}"
        }
        response = requests.get(API_URL, params=params, auth=(client_id, ""))
        response.raise_for_status()  # Dette vil reise en HTTPError for dårlige statuskoder
        data = response.json()

        if not data or not data.get('data'):
            raise ValueError("Ingen data returnert fra API-et")

        df = pd.DataFrame([
            {
                'timestamp': datetime.fromisoformat(item['referenceTime'].rstrip('Z')),
                'air_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'air_temperature'), np.nan),
                'precipitation_amount': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'sum(precipitation_amount PT1H)'), np.nan),
                'surface_snow_thickness': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_snow_thickness'), np.nan),
                'wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'wind_speed'), np.nan),
                'max_wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'max(wind_speed_of_gust PT1H)'), np.nan),
                'min_wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'min(wind_speed P1M)'), np.nan),
                'wind_from_direction': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'max_wind_speed(wind_from_direction PT1H)'), np.nan),
                'surface_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_temperature'), np.nan),
                'relative_humidity': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'relative_humidity'), np.nan),
                'dew_point_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'dew_point_temperature'), np.nan)
            }
            for item in data['data']
        ]).set_index('timestamp')

        if df.empty:
            raise ValueError("Ingen data kunne konverteres til DataFrame")

        df.index = pd.to_datetime(df.index).tz_localize(TZ, nonexistent='shift_forward', ambiguous='NaT')

        processed_data = {}
        for column in df.columns:
            processed_data[column] = pd.to_numeric(df[column], errors='coerce')
            processed_data[column] = validate_data(processed_data[column])
            processed_data[column] = handle_missing_data(df.index, processed_data[column], method='time')

        processed_df = pd.DataFrame(processed_data, index=df.index)
        processed_df['snow_precipitation'] = calculate_snow_precipitations(
            processed_df['air_temperature'].values,
            processed_df['precipitation_amount'].values,
            processed_df['surface_snow_thickness'].values
        )

        processed_df = calculate_snow_drift_alarms(processed_df)
        processed_df = calculate_slippery_road_alarms(processed_df)
        
        smoothed_data = {}
        for column in processed_df.columns:
            if column not in ['snow_drift_alarm', 'slippery_road_alarm', 'snow_precipitation']:
                smoothed_data[column] = smooth_data(processed_df[column].values)
            else:
                smoothed_data[column] = processed_df[column]
        
        smoothed_df = pd.DataFrame(smoothed_data, index=processed_df.index)
        smoothed_df['wind_direction_category'] = smoothed_df['wind_from_direction'].apply(categorize_direction)

        return {'df': smoothed_df}

    except requests.RequestException as e:
        error_message = f"Nettverksfeil ved henting av data: {str(e)}"
        if isinstance(e, requests.ConnectionError):
            error_message = "Kunne ikke koble til værdata-serveren. Sjekk internettforbindelsen din."
        elif isinstance(e, requests.Timeout):
            error_message = "Forespørselen tok for lang tid. Prøv igjen senere."
        elif isinstance(e, requests.HTTPError):
            if e.response.status_code == 401:
                error_message = "Ugyldig API-nøkkel. Kontakt systemadministrator."
            elif e.response.status_code == 404:
                error_message = "Værdata-ressursen ble ikke funnet. Sjekk stasjonsnummeret."
            else:
                error_message = f"HTTP-feil {e.response.status_code}: {e.response.reason}"
        logger.error(error_message)
        return {'error': error_message}

    except ValueError as e:
        error_message = f"Feil i databehandling: {str(e)}"
        logger.error(error_message)
        return {'error': error_message}

    except Exception as e:
        error_message = f"Uventet feil ved datahenting eller -behandling: {str(e)}"
        logger.error(error_message, exc_info=True)
        return {'error': error_message}

def calculate_snow_drift_alarms(df):
    df['snow_depth_change'] = df['surface_snow_thickness'].diff()
    conditions = [
        df['wind_speed'] > 6,
        df['air_temperature'] <= -1,
        ((df['precipitation_amount'] <= 0.1) & (df['surface_snow_thickness'].diff().fillna(0).abs() >= 1)) | 
        ((df['precipitation_amount'] > 0.1) & (df['surface_snow_thickness'].diff().fillna(0) <= -0.5))
    ]
    df['snow_drift_alarm'] = (conditions[0] & conditions[1] & conditions[2]).astype(int)
    return df

def calculate_slippery_road_alarms(df):
    conditions = [
        df['air_temperature'] > 0,
        df['precipitation_amount'] > 1.5,
        df['surface_snow_thickness'] >= 20,
        df['surface_snow_thickness'].diff().fillna(0) < 0
    ]
    df['slippery_road_alarm'] = np.all(conditions, axis=0).astype(int)
    return df

def validate_data(data):
    data = np.array(data, dtype=float)
    if np.all(np.isnan(data)):
        return data
    median = np.nanmedian(data)
    std = np.nanstd(data)
    lower_bound = median - 5 * std
    upper_bound = median + 5 * std
    data[(data < lower_bound) | (data > upper_bound)] = np.nan
    return data

def smooth_data(data):
    if np.all(np.isnan(data)):
        return data
    timestamps = np.arange(len(data))
    valid_indices = ~np.isnan(data)
    if np.sum(valid_indices) < 2:
        return data
    smoothed = lowess(data[valid_indices], timestamps[valid_indices], frac=0.1, it=0)
    result = np.full_like(data, np.nan)
    result[valid_indices] = smoothed[:, 1]
    return result

def handle_missing_data(timestamps, data, method='time'):
    data_series = pd.Series(data, index=timestamps)
    if method == 'time':
        interpolated = data_series.interpolate(method='time')
    elif method == 'linear':
        interpolated = data_series.interpolate(method='linear')
    else:
        interpolated = data_series.interpolate(method='nearest')
    return interpolated.to_numpy()

# Funksjoner relatert til værdatainnhenting og -prosessering:
def fetch_and_process_data(client_id, date_start, date_end):
    try:
        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start}/{date_end}"
        }
        response = requests.get(API_URL, params=params, auth=(client_id, ""))
        response.raise_for_status()  # Dette vil reise en HTTPError for dårlige statuskoder
        data = response.json()

        if not data or not data.get('data'):
            raise ValueError("Ingen data returnert fra API-et")

        df = pd.DataFrame([
            {
                'timestamp': datetime.fromisoformat(item['referenceTime'].rstrip('Z')),
                'air_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'air_temperature'), np.nan),
                'precipitation_amount': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'sum(precipitation_amount PT1H)'), np.nan),
                'surface_snow_thickness': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_snow_thickness'), np.nan),
                'wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'wind_speed'), np.nan),
                'max_wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'max(wind_speed_of_gust PT1H)'), np.nan),
                'min_wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'min(wind_speed P1M)'), np.nan),
                'wind_from_direction': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'max_wind_speed(wind_from_direction PT1H)'), np.nan),
                'surface_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_temperature'), np.nan),
                'relative_humidity': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'relative_humidity'), np.nan),
                'dew_point_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'dew_point_temperature'), np.nan)
            }
            for item in data['data']
        ]).set_index('timestamp')

        if df.empty:
            raise ValueError("Ingen data kunne konverteres til DataFrame")

        df.index = pd.to_datetime(df.index).tz_localize(TZ, nonexistent='shift_forward', ambiguous='NaT')

        processed_data = {}
        for column in df.columns:
            processed_data[column] = pd.to_numeric(df[column], errors='coerce')
            processed_data[column] = validate_data(processed_data[column])
            processed_data[column] = handle_missing_data(df.index, processed_data[column], method='time')

        processed_df = pd.DataFrame(processed_data, index=df.index)
        processed_df['snow_precipitation'] = calculate_snow_precipitations(
            processed_df['air_temperature'].values,
            processed_df['precipitation_amount'].values,
            processed_df['surface_snow_thickness'].values
        )

        processed_df = calculate_snow_drift_alarms(processed_df)
        processed_df = calculate_slippery_road_alarms(processed_df)
        
        smoothed_data = {}
        for column in processed_df.columns:
            if column not in ['snow_drift_alarm', 'slippery_road_alarm', 'snow_precipitation']:
                smoothed_data[column] = smooth_data(processed_df[column].values)
            else:
                smoothed_data[column] = processed_df[column]
        
        smoothed_df = pd.DataFrame(smoothed_data, index=processed_df.index)
        smoothed_df['wind_direction_category'] = smoothed_df['wind_from_direction'].apply(categorize_direction)

        return {'df': smoothed_df}

    except requests.RequestException as e:
        error_message = f"Nettverksfeil ved henting av data: {str(e)}"
        if isinstance(e, requests.ConnectionError):
            error_message = "Kunne ikke koble til værdata-serveren. Sjekk internettforbindelsen din."
        elif isinstance(e, requests.Timeout):
            error_message = "Forespørselen tok for lang tid. Prøv igjen senere."
        elif isinstance(e, requests.HTTPError):
            if e.response.status_code == 401:
                error_message = "Ugyldig API-nøkkel. Kontakt systemadministrator."
            elif e.response.status_code == 404:
                error_message = "Værdata-ressursen ble ikke funnet. Sjekk stasjonsnummeret."
            else:
                error_message = f"HTTP-feil {e.response.status_code}: {e.response.reason}"
        logger.error(error_message)
        return {'error': error_message}

    except ValueError as e:
        error_message = f"Feil i databehandling: {str(e)}"
        logger.error(error_message)
        return {'error': error_message}

    except Exception as e:
        error_message = f"Uventet feil ved datahenting eller -behandling: {str(e)}"
        logger.error(error_message, exc_info=True)
        return {'error': error_message}

def calculate_snow_drift_alarms(df):
    df['snow_depth_change'] = df['surface_snow_thickness'].diff()
    conditions = [
        df['wind_speed'] > 6,
        df['air_temperature'] <= -1,
        ((df['precipitation_amount'] <= 0.1) & (df['surface_snow_thickness'].diff().fillna(0).abs() >= 1)) | 
        ((df['precipitation_amount'] > 0.1) & (df['surface_snow_thickness'].diff().fillna(0) <= -0.5))
    ]
    df['snow_drift_alarm'] = (conditions[0] & conditions[1] & conditions[2]).astype(int)
    return df

def calculate_slippery_road_alarms(df):
    conditions = [
        df['air_temperature'] > 0,
        df['precipitation_amount'] > 1.5,
        df['surface_snow_thickness'] >= 20,
        df['surface_snow_thickness'].diff().fillna(0) < 0
    ]
    df['slippery_road_alarm'] = np.all(conditions, axis=0).astype(int)
    return df

def calculate_snow_precipitations(temperatures, precipitations, snow_depths):
    snow_precipitations = np.zeros_like(temperatures)
    for i in range(len(temperatures)):
        if temperatures[i] is not None and not np.isnan(temperatures[i]):
            condition1 = temperatures[i] <= 1.5 and i > 0 and not np.isnan(snow_depths[i]) and not np.isnan(snow_depths[i-1]) and snow_depths[i] > snow_depths[i-1]
            condition2 = temperatures[i] <= 0 and not np.isnan(precipitations[i]) and precipitations[i] > 0
            if condition1 or condition2:
                snow_precipitations[i] = precipitations[i] if not np.isnan(precipitations[i]) else 0
    return snow_precipitations

# Call this function when the application starts
if __name__ == "__main__":
    initialize_database()
    