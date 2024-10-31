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
        if 'end_date' not in st.session_state:
            st.session_state.end_date = now.date()
        if 'start_date' not in st.session_state:
            st.session_state.start_date = st.session_state.end_date - timedelta(days=7)
            
        def update_start_date():
            st.session_state.start_date = st.session_state.end_date - timedelta(days=7)
            
        col1, col2 = st.columns(2)
        with col2:
            end_date = st.date_input(
                "Sluttdato", 
                value=st.session_state.end_date,
                key="end_date",
                on_change=update_start_date
            )
        with col1:
            start_date = st.date_input(
                "Startdato", 
                value=st.session_state.start_date,
                key="start_date",
                max_value=end_date
            )
            
        if start_date > end_date:
            st.error("Startdato kan ikke være senere enn sluttdato")
            return None, None
            
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