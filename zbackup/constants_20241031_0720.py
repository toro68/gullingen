from zoneinfo import ZoneInfo
from datetime import timedelta

LOCKOUT_PERIOD = timedelta(minutes=15)

# Tidssone
TZ = ZoneInfo("Europe/Oslo")

# Værdata
STATION_ID = "SN46220"
API_URL = "https://frost.met.no/observations/v0.jsonld"
ELEMENTS = "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),max_wind_speed(wind_from_direction PT1H),max(wind_speed_of_gust PT1H),min(wind_speed P1M),wind_speed,surface_temperature,relative_humidity,dew_point_temperature"
TIME_RESOLUTION = "PT1H"

# GPS-data
GPS_URL = "https://kart.irute.net/fjellbergsskardet_busses.json?_=1657373465172"

# Status mapping for strøing
STATUS_MAPPING = {
    "Ny": 1,
    "Under behandling": 2,
    "Fullført": 3,
    "Kansellert": 4,
}

# Farger for feedback status
STATUS_COLORS = {
    "Ny": "#FF4136",
    "Under behandling": "#FF851B",
    "Løst": "#2ECC40",
    "Lukket": "#AAAAAA",
    "default": "#CCCCCC",
}

# Ikoner for feedback type
icons = {"Føreforhold": "🚗", "Parkering": "🅿️", "Fasilitet": "🏠", "Annet": "❓"}

# Maksimalt antall påloggingsforsøk
MAX_ATTEMPTS = 5
# Utestengningsperiode etter for mange mislykkede påloggingsforsøk
LOCKOUT_PERIOD = timedelta(minutes=15)
# Timeout for sesjon
SESSION_TIMEOUT = 3600  # 1 time


