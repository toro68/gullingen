import logging
from typing import Tuple, Optional
from datetime import datetime, timedelta
import pytz
import streamlit as st

from constants import TZ, STATUS_MAPPING
from gps_utils import get_last_gps_activity
from logging_config import get_logger

logger = get_logger(__name__)

def dump_secrets():
    logger.info("Dumping st.secrets content:")
    for key in st.secrets:
        if isinstance(st.secrets[key], dict):
            logger.info(f"Key: {key}")
            for subkey in st.secrets[key]:
                value = st.secrets[key][subkey]
                logger.info(f"  Subkey: {subkey}, Value type: {type(value)}, Value preview: {str(value)[:50]}...")
        else:
            value = st.secrets[key]
            logger.info(f"Key: {key}, Value type: {type(value)}, Value preview: {str(value)[:50]}...")

def get_date_range(period):
    oslo_tz = pytz.timezone('Europe/Oslo')
    now = datetime.now(oslo_tz)
    
    if period == "Siste 24 timer":
        return now - timedelta(hours=24), now
    elif period == "Siste 7 dager":
        return now - timedelta(days=7), now
    elif period == "Siste 12 timer":
        return now - timedelta(hours=12), now
    elif period == "Siste 4 timer":
        return now - timedelta(hours=4), now
    elif period == "Siden sist fredag":
        days_since_friday = (now.weekday() - 4) % 7
        last_friday = now - timedelta(days=days_since_friday)
        return last_friday.replace(hour=0, minute=0, second=0, microsecond=0), now
    elif period == "Siden sist søndag":
        days_since_sunday = (now.weekday() - 6) % 7
        last_sunday = now - timedelta(days=days_since_sunday)
        return last_sunday.replace(hour=0, minute=0, second=0, microsecond=0), now
    elif period == "Egendefinert periode":
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Startdato", value=now.date() - timedelta(days=7))
        with col2:
            end_date = st.date_input("Sluttdato", value=now.date())
        return oslo_tz.localize(datetime.combine(start_date, datetime.min.time())), oslo_tz.localize(datetime.combine(end_date, datetime.max.time()))
    elif period == "Siste GPS-aktivitet til nå":
        last_gps_activity = get_last_gps_activity()
        if last_gps_activity:
            return last_gps_activity, now
        else:
            st.warning("Ingen GPS-aktivitet funnet. Viser data for siste 24 timer.")
            return now - timedelta(hours=24), now
    else:
        st.error(f"Ugyldig periodevalg: {period}")
        return None, None

def get_status_text(row, has_active_booking):
    if has_active_booking:
        return "Aktiv bestilling"
    elif row['icon'] == 'star_red':
        return "Ukentlig ved bestilling"
    elif row['icon'] == 'star_white':
        return "Årsabonnement"
    else:
        return "Ingen brøyting"

def get_marker_properties(booking_type: str, is_active: bool, ankomst_dato: datetime, current_date: datetime = None) -> Tuple[str, str]:
    """
    Bestemmer markør-egenskaper basert på bestillingstype, aktivitetsstatus og ankomstdato.

    Args:
        booking_type (str): Typen bestilling ('Ukentlig ved bestilling', 'Årsabonnement', etc.)
        is_active (bool): Om bestillingen er aktiv eller ikke
        ankomst_dato (datetime): Ankomstdatoen for bestillingen
        current_date (datetime, optional): Dagens dato. Hvis ikke oppgitt, brukes nåværende dato.

    Returns:
        Tuple[str, str]: En tuple med farge og form for markøren
    """
    if current_date is None:
        current_date = datetime.now(TZ).date()
    else:
        current_date = current_date.date()

    ankomst_dato = ankomst_dato.date()
    days_until_arrival = (ankomst_dato - current_date).days

    if is_active:
        return 'red', 'circle'  # Aktiv bestilling
    elif booking_type == "Ukentlig ved bestilling":
        if 0 <= days_until_arrival <= 7:
            # Gradvis endring fra oransje til rød jo nærmere ankomstdatoen
            intensity = int(255 * (7 - days_until_arrival) / 7)
            return f'rgb(255, {255 - intensity}, 0)', 'circle'
        else:
            return 'orange', 'circle'  # Ukentlig ved bestilling, mer enn 7 dager til ankomst
    elif booking_type == "Årsabonnement":
        return 'blue', 'circle'  # Årsabonnement
    else:
        return 'gray', 'circle'  # Ingen brøyting

# def get_marker_properties(booking_type: str, is_active: bool) -> Tuple[str, str]:
#     """
#     Bestemmer markør-egenskaper basert på bestillingstype og aktivitetsstatus.

#     Args:
#         booking_type (str): Typen bestilling ('Ukentlig ved bestilling', 'Årsabonnement', etc.)
#         is_active (bool): Om bestillingen er aktiv eller ikke

#     Returns:
#         Tuple[str, str]: En tuple med farge og form for markøren
#     """
#     if is_active:
#         return 'red', 'circle'  # Aktiv bestilling
#     elif booking_type == "Ukentlig ved bestilling":
#         return 'orange', 'circle'  # Ukentlig ved bestilling
#     elif booking_type == "Årsabonnement":
#         return 'blue', 'circle'  # Årsabonnement
#     else:
#         return 'gray', 'circle'  # Ingen brøyting

# Denne fungerte med tunkartet...    
# def get_marker_properties(booking_type, is_active):
#     if is_active:
#         return 'red', 'circle'  # Aktiv bestilling
#     elif booking_type == "Ukentlig ved bestilling":
#         return 'orange', 'circle'  # Ukentlig ved bestilling
#     elif booking_type == "Årsabonnement":
#         return 'blue', 'circle'  # Årsabonnement
#     else:
#         return 'gray', 'circle'  # Ingen brøyting

def get_status_display(db_status):
    return next((k for k, v in STATUS_MAPPING.items() if v == db_status), "Ukjent")

def format_norwegian_date(date):
    return date.strftime("%d.%m.%Y")  # Format the date as DD.MM.YYYY

def neste_fredag():
    today = datetime.now(TZ).date()
    days_ahead = 4 - today.weekday()  # Fredag er 4
    if days_ahead <= 0:  # Hvis det er fredag eller senere, gå til neste uke
        days_ahead += 7
    return today + timedelta(days=days_ahead)

def parse_date(date_string):
    return datetime.strptime(date_string, '%Y-%m-%d').date() if date_string else None

def parse_time(time_string):
    return datetime.strptime(time_string, '%H:%M:%S').time() if time_string else None

def dump_debug_info():
    logger.info("Dumping debug info")
    conn = None
    try:
        from db_utils import get_db_connection
        conn = get_db_connection('customer')
        if conn is None:
            logger.error("Failed to establish database connection")
            return

        cursor = conn.cursor()

        # Hent totalt antall kunder
        cursor.execute("SELECT COUNT(*) FROM customers")
        total_customers = cursor.fetchone()[0]
        logger.info(f"Total number of customers: {total_customers}")

        # Hent kolonner i kundedatabasen
        cursor.execute("PRAGMA table_info(customers)")
        columns = [column[1] for column in cursor.fetchall()]
        logger.info(f"Columns in customer database: {columns}")

        # Sjekk om 'Type' kolonne eksisterer og hent kundetyper
        if 'Type' in columns:
            cursor.execute("SELECT Type, COUNT(*) FROM customers GROUP BY Type")
            type_counts = dict(cursor.fetchall())
            logger.info(f"Customer types: {type_counts}")
        else:
            logger.warning("'Type' column not found in customer database")

        # Hent første kunde for å vise eksempel på data
        cursor.execute("SELECT * FROM customers LIMIT 1")
        first_customer = cursor.fetchone()
        if first_customer:
            logger.info(f"Example customer data: {dict(zip(columns, first_customer))}")
        else:
            logger.warning("No customers found in the database")

        # Logg passordinformasjon
        logger.info("Passwords:")
        passwords = st.secrets.get("passwords", {})
        for user_id, password in passwords.items():
            logger.info(f"  User {user_id}: {password}")

        # Sjekk konsistens mellom kunder og passord
        cursor.execute("SELECT Id FROM customers")
        customer_ids = set(str(row[0]) for row in cursor.fetchall())
        password_ids = set(passwords.keys())

        customers_without_password = customer_ids - password_ids
        passwords_without_customer = password_ids - customer_ids

        if customers_without_password:
            logger.warning(f"Customers without passwords: {customers_without_password}")
        if passwords_without_customer:
            logger.warning(f"Passwords without corresponding customers: {passwords_without_customer}")

    except Exception as e:
        logger.error(f"Unexpected error in dump_debug_info: {str(e)}", exc_info=True)
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed")

# Add any other utility functions here as needed