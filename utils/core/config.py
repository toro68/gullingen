# config.py
import logging
import os
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from utils.core.logging_config import get_logger, setup_logging

# Sett opp logging først
setup_logging()
logger = get_logger(__name__)

# Finn riktig prosjektmappe basert på kjørende script
current_dir = Path(__file__).parent.parent.parent
if "src" in str(current_dir):
    BASE_PATH = current_dir.parent
else:
    BASE_PATH = current_dir

# Sett database path
DATABASE_PATH = BASE_PATH / "database"
os.makedirs(DATABASE_PATH, exist_ok=True)

# Logging konfigurasjon
logger.info(f"Database path set to: {DATABASE_PATH}")

# Tidssone
TZ = ZoneInfo("Europe/Oslo")

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
