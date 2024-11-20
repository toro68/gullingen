# config.py

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo
import pandas as pd
import logging

# Få logger instans direkte
logger = logging.getLogger(__name__)

# Tidssone konfigurasjon
TZ = ZoneInfo("Europe/Oslo")

# Dato- og tidsformater
DATE_FORMATS = {
    "display": {
        "date": "%d.%m.%Y",
        "time": "%H:%M",
        "datetime": "%d.%m.%Y %H:%M",
        "datetime_seconds": "%d.%m.%Y %H:%M:%S",
        "short_date": "%d.%m",
        "iso": "%Y-%m-%d",
        "iso_time": "%H:%M:%S",
        "iso_datetime": "%Y-%m-%dT%H:%M:%S"
    },
    "database": {
        "date": "%Y-%m-%d",
        "time": "%H:%M:%S",
        "datetime": "%Y-%m-%d %H:%M:%S",
        "timestamp": "%Y-%m-%dT%H:%M:%S%z"
    },
    "api": {
        "date": "%Y-%m-%d",
        "datetime": "%Y-%m-%dT%H:%M:%S",
        "timestamp": "%Y-%m-%dT%H:%M:%SZ"
    }
}

# Dato validering og standardverdier
DATE_VALIDATION = {
    "min_year": 2020,
    "max_year": datetime.now(TZ).year + 1,
    "default_time": "12:00",
    "default_date_range": 7,  # dager
    "max_future_booking": 365  # maks antall dager frem i tid for bestilling
}

# Dato parsing og formatering funksjoner
def get_date_format(format_type: str, format_name: str) -> str:
    """Henter datoformat basert på type og navn"""
    return DATE_FORMATS.get(format_type, {}).get(format_name)

def get_current_time() -> datetime:
    """Returnerer nåværende tid i riktig tidssone"""
    return datetime.now(TZ)

def get_default_date_range() -> tuple[datetime, datetime]:
    """Returnerer standard datoperiode"""
    now = get_current_time()
    return (
        now,
        now + timedelta(days=DATE_VALIDATION["default_date_range"])
    )

# Finn riktig prosjektmappe basert på kjørende script
current_dir = Path(__file__).parent.parent.parent

# Sjekk om vi kjører på Streamlit Cloud
IS_STREAMLIT_CLOUD = os.getenv('IS_STREAMLIT_CLOUD', 'false').lower() == 'true'

# Sett riktig databasesti basert på miljø
if IS_STREAMLIT_CLOUD:
    DATABASE_PATH = Path("/mount/src/gullingen/database")
else:
    DATABASE_PATH = current_dir / "database"

# Opprett databasemappen hvis den ikke eksisterer
DATABASE_PATH.mkdir(parents=True, exist_ok=True)

# Logging konfigurasjon
logger.info(f"Database path set to: {DATABASE_PATH}")

# Værdata konfigurasjon
STATION_ID = "SN46220"
API_URL = "https://frost.met.no/observations/v0.jsonld"
ELEMENTS = "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),wind_from_direction,max(wind_speed_of_gust PT1H),mean(wind_speed PT1H),surface_temperature,relative_humidity,dew_point_temperature"
TIME_RESOLUTION = "PT1H"

# GPS konfigurasjon
GPS_URL = "https://kart.irute.net/fjellbergsskardet_busses.json?_=1657373465172"

# Status mapping og farger
STATUS_MAPPING = {
    "Ny": 1,
    "Under behandling": 2,
    "Fullført": 3,
    "Kansellert": 4,
}

STATUS_COLORS = {
    "Ny": "#FF4136",
    "Under behandling": "#FF851B",
    "Løst": "#2ECC40",
    "Lukket": "#AAAAAA",
    "default": "#CCCCCC",
}

# UI ikoner
FEEDBACK_ICONS = {
    "Føreforhold": "🚗",
    "Parkering": "🅿️",
    "Fasilitet": "🏠",
    "Annet": "❓",
}

# Autentisering og sesjon
MAX_ATTEMPTS = 5
LOCKOUT_PERIOD = timedelta(minutes=15)
SESSION_TIMEOUT = 3600  # 1 time i sekunder

# Database timeouts og retry konfigurasjon
DB_TIMEOUT = 30
DB_RETRY_ATTEMPTS = 3
DB_RETRY_DELAY = 1  # sekunder

# Database configuration
DB_CONFIG = {
    "login_history": {
        "path": os.path.join(DATABASE_PATH, "login_history.db"),
        "timeout": DB_TIMEOUT,
        "version": 1,
        "schema": {"tables": ["login_history"]},
    },
    "customer": {
        "path": os.path.join(DATABASE_PATH, "customer.db"),
        "timeout": DB_TIMEOUT,
        "version": 1,
        "schema": {
            "tables": ["customer"],
            "required_columns": {
                "customer": [
                    "customer_id",
                    "lat",
                    "lon",
                    "subscription",
                    "type",
                    "created_at",
                ]
            },
        },
    },
    "stroing": {
        "path": os.path.join(DATABASE_PATH, "stroing.db"),
        "timeout": DB_TIMEOUT,
        "version": 1,
        "schema": {"tables": ["stroing_bestillinger"]},
    },
    "tunbroyting": {
        "path": os.path.join(DATABASE_PATH, "tunbroyting.db"),
        "timeout": DB_TIMEOUT,
        "version": 1,
        "schema": {"tables": ["tunbroyting_bestillinger"]},
    },
}

def safe_to_datetime(date_string: Optional[str]) -> Optional[datetime]:
    """
    Konverterer en streng til datetime med riktig tidssone
    """
    if date_string in [None, "", "None", "1"] or pd.isna(date_string):
        return None
    try:
        dt = pd.to_datetime(date_string)
        return dt.tz_localize(TZ) if dt.tzinfo is None else dt.astimezone(TZ)
    except ValueError:
        logger.error(f"Ugyldig datostreng: '{date_string}'")
        return None

def format_date(date_obj: Optional[datetime], format_type: str = "display", format_name: str = "datetime") -> str:
    """
    Formaterer en datetime til streng med standard format
    """
    if date_obj is None:
        return "Ikke satt"
    
    date_format = get_date_format(format_type, format_name)
    if not date_format:
        logger.warning(f"Ukjent datoformat: {format_type}/{format_name}")
        date_format = DATE_FORMATS["display"]["datetime"]
    
    return date_obj.strftime(date_format)

def combine_date_with_tz(date_obj, time_obj=None):
    """Kombinerer dato og tid med tidssone"""
    if time_obj is None:
        time_obj = datetime.min.time()
    return datetime.combine(date_obj, time_obj).replace(tzinfo=TZ)
