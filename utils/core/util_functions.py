from datetime import datetime, timedelta
from typing import Tuple
import pytz
import pandas as pd
import streamlit as st

from utils.core.config import normalize_datetime, TZ, format_date, get_current_time
from utils.core.logging_config import get_logger
from utils.services.gps_utils import get_last_gps_activity

logger = get_logger(__name__)


def dump_secrets():
    logger.info("Dumping st.secrets content:")
    for key in st.secrets:
        if isinstance(st.secrets[key], dict):
            logger.info(f"Key: {key}")
            for subkey in st.secrets[key]:
                value = st.secrets[key][subkey]
                logger.info(
                    f"  Subkey: {subkey}, Value type: {type(value)}, Value preview: {str(value)[:50]}..."
                )
        else:
            value = st.secrets[key]
            logger.info(
                f"Key: {key}, Value type: {type(value)}, Value preview: {str(value)[:50]}..."
            )


def get_date_range(period):
    oslo_tz = pytz.timezone("Europe/Oslo")
    now = datetime.now(oslo_tz)

    if period == "Siste 12 timer":
        start_date = now - timedelta(hours=12)
        logger.debug("Siste 12 timer - Start: %s, Slutt: %s", start_date, now)
        return start_date, now
    elif period == "Siste 24 timer":
        return now - timedelta(hours=24), now
    elif period == "Siste 7 dager":
        return now - timedelta(days=7), now
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
        if "end_date" not in st.session_state:
            st.session_state.end_date = now.date()
        if "start_date" not in st.session_state:
            st.session_state.start_date = st.session_state.end_date - timedelta(days=7)

        def update_start_date():
            st.session_state.start_date = st.session_state.end_date - timedelta(days=7)

        col1, col2 = st.columns(2)
        with col2:
            end_date = st.date_input(
                "Sluttdato",
                value=st.session_state.end_date,
                key="end_date",
                on_change=update_start_date,
            )
        with col1:
            start_date = st.date_input(
                "Startdato",
                value=st.session_state.start_date,
                key="start_date",
                max_value=end_date,
            )

        if start_date > end_date:
            st.error("Startdato kan ikke være senere enn sluttdato")
            return None, None

        return oslo_tz.localize(
            datetime.combine(start_date, datetime.min.time())
        ), oslo_tz.localize(datetime.combine(end_date, datetime.max.time()))
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
    elif row["icon"] == "star_red":
        return "Ukentlig ved bestilling"
    elif row["icon"] == "star_white":
        return "Årsabonnement"
    else:
        return "Ingen brøyting"

def get_status_display(status):
    """
    Returnerer status-teksten direkte.
    
    Args:
        status: Status som skal vises
        
    Returns:
        str: Status-teksten eller 'Ukjent' hvis status er None
    """
    return status if status is not None else "Ukjent"


def format_norwegian_date(date):
    return date.strftime("%d.%m.%Y")  # Format the date as DD.MM.YYYY


def neste_fredag():
    today = datetime.now(TZ).date()
    days_ahead = 4 - today.weekday()  # Fredag er 4
    if days_ahead <= 0:  # Hvis det er fredag eller senere, gå til neste uke
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def parse_date(date_string):
    return datetime.strptime(date_string, "%Y-%m-%d").date() if date_string else None


def parse_time(time_string):
    return datetime.strptime(time_string, "%H:%M:%S").time() if time_string else None

# filtrerer bestillinger i bestill_tunbroyting
def filter_todays_bookings(bookings: pd.DataFrame) -> pd.DataFrame:
    """Filtrerer bestillinger for dagens dato"""
    logger.info("=== STARTER FILTER_TODAYS_BOOKINGS ===")
    try:
        if bookings.empty:
            return bookings
            
        today = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0)
        logger.info(f"Dagens dato (normalisert): {today}")
        
        # Konverter datoer til datetime med tidssone
        bookings['ankomst_dato'] = pd.to_datetime(bookings['ankomst_dato'])
        if 'avreise_dato' in bookings.columns:
            bookings['avreise_dato'] = pd.to_datetime(bookings['avreise_dato'])
            
        # Konverter til riktig tidssone hvis ikke allerede satt
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in bookings.columns:
                if bookings[col].dt.tz is None:
                    bookings[col] = bookings[col].dt.tz_localize('Europe/Oslo')
                else:
                    bookings[col] = bookings[col].dt.tz_convert('Europe/Oslo')
        
        # Filtrer basert på dato og abonnement_type
        mask = (
            # Vanlige bestillinger som starter i perioden
            (
                (bookings["abonnement_type"] != "Årsabonnement") &
                (bookings["ankomst_dato"].dt.normalize() == today)
            ) |
            # Årsabonnement som er aktive (ankomst passert og ikke utløpt)
            (
                (bookings["abonnement_type"] == "Årsabonnement") &
                (bookings["ankomst_dato"].dt.normalize() <= today) &
                (
                    bookings["avreise_dato"].isna() |
                    (bookings["avreise_dato"].dt.normalize() >= today)
                )
            )
        )
            
        return bookings[mask].copy()
        
    except Exception as e:
        logger.error(f"Feil i filter_todays_bookings: {str(e)}")
        return pd.DataFrame()
    