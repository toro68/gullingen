# config.py

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
import pandas as pd

# Få logger instans direkte
logger = logging.getLogger(__name__)

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

# Tidssone konfigurasjon
TZ = ZoneInfo("Europe/Oslo")
# Dato- og tidsformater
DATE_FORMATS = {
    "database": {
        "date": "%Y-%m-%d",
        "time": "%H:%M",
        "datetime": "%Y-%m-%d %H:%M:%S"
    },
    "display": {
        "date": "%d.%m.%Y",
        "time": "%H:%M",
        "datetime": "%d.%m.%Y %H:%M"
    },
    "parse": {
        "date": "%d.%m.%Y",
        "time": "%H:%M",
        "datetime": "%d.%m.%Y %H:%M"
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
# Standardverdier for datohåndtering
DATE_DEFAULTS = {
    "normalize_dates": True,  # Om datoer skal normaliseres (fjerne klokkeslett)
    "include_time": False,    # Om tid skal inkluderes i datosammenligninger
    "store_timezone": False,  # Om tidssone skal lagres i databasen
    "comparison_precision": "day"  # day/hour/minute/second
}
# Datotype-konfigurasjon for database
DB_DATE_TYPES = {
    "tunbroyting_bestillinger": {
        "ankomst_dato": "DATE",
        "avreise_dato": "DATE"
    }
}
# Konverteringsregler for datoer
DATE_CONVERSION = {
    "to_db": {
        "DATE": lambda x: x.strftime(DATE_FORMATS["database"]["date"]) if x is not None else None,
        "TIME": lambda x: x.strftime(DATE_FORMATS["database"]["time"]) if x is not None else None,
        "DATETIME": lambda x: x.strftime(DATE_FORMATS["database"]["datetime"]) if x is not None else None
    },
    "from_db": {
        "DATE": lambda x: safe_to_datetime(x).date() if x is not None else None,
        "TIME": lambda x: datetime.strptime(x, DATE_FORMATS["database"]["time"]).time() if x is not None else None,
        "DATETIME": lambda x: safe_to_datetime(x)
    }
}


# Database timeouts og retry konfigurasjon
DB_TIMEOUT = 30
DB_RETRY_ATTEMPTS = 3
DB_RETRY_DELAY = 1  # sekunder

# Database configuration
DB_CONFIG = {
    "login_history": {
        "path": str(DATABASE_PATH.joinpath("login_history.db")),
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


# === DATO FUNKSJONER ===
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

def format_date(date_value: Any, format_type: str = "display", date_type: str = "date") -> Optional[str]:
    """
    Formaterer dato til ønsket format.
    
    Args:
        date_value: Datoverdi som skal formateres
        format_type: Type format ('database', 'display', 'parse')
        date_type: Type dato ('date', 'time', 'datetime')
        
    Returns:
        Formatert datostreng eller None ved feil
    """
    try:
        if pd.isna(date_value):
            return None
            
        date_obj = safe_to_datetime(date_value)
        if not date_obj:
            return None
            
        date_format = DATE_FORMATS.get(format_type, {}).get(date_type)
        if not date_format:
            logger.error(f"Ugyldig format: {format_type}/{date_type}")
            return None
            
        return date_obj.strftime(date_format)
        
    except Exception as e:
        logger.error(f"Feil i format_date: {str(e)}")
        return None

def combine_date_with_tz(date_obj, time_obj=None):
    """Kombinerer dato og tid med tidssone"""
    if time_obj is None:
        time_obj = datetime.min.time()
    return datetime.combine(date_obj, time_obj).replace(tzinfo=TZ)

def parse_date(date_str: str, format_type: str = "display") -> datetime:
    """Parser datostrengen med riktig format og tidssone"""
    try:
        return pd.to_datetime(
            date_str, 
            format=DATE_FORMATS["parse"]["date"], 
            dayfirst=True
        ).tz_localize(TZ)
    except Exception as e:
        logger.error(f"Feil ved parsing av dato {date_str}: {str(e)}")
        return None

def normalize_datetime(dt):
    """Normaliserer datetime til midnatt i riktig tidssone"""
    try:
        if isinstance(dt, str):
            dt = parse_date(dt)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.tz_localize(TZ)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    except Exception as e:
        logger.error(f"Feil i normalize_datetime: {str(e)}")
        return None

def convert_for_db(value: Any, column_type: str, table: str) -> Any:
    """Konverterer en verdi til riktig format for databasen"""
    if value is None:
        return None
        
    if table in DB_DATE_TYPES and column_type in DATE_CONVERSION["to_db"]:
        return DATE_CONVERSION["to_db"][column_type](value)
    
    return value


# Dato parsing og formatering funksjoner
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

def get_date_format(format_type: str, format_name: str) -> Optional[str]:
    """
    Henter datoformat fra DATE_FORMATS.
    
    Args:
        format_type: Type format ('database', 'display', 'parse')
        format_name: Navn på format ('date', 'time', 'datetime')
        
    Returns:
        Datoformat-streng eller None hvis ikke funnet
    """
    return DATE_FORMATS.get(format_type, {}).get(format_name)