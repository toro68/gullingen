"""
utils.py

Dette modulet inneholder hjelpefunksjoner for Fjellbergsskardet-applikasjonen,
inkludert funksjonalitet for å mappe hytter til brukere basert på en TOML-konfigurasjonsfil.
"""

import re
from typing import Any, Dict, Optional
import pandas as pd
from datetime import datetime

import toml
import streamlit as st

from menu_utils import create_menu
from logging_config import get_logger

logger = get_logger(__name__)

def map_cabins_to_users(toml_file_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Mapper hytter til brukere basert på en TOML-konfigurasjonsfil.

    Args:
        toml_file_path (str): Filbanen til TOML-konfigurasjonsfilen.

    Returns:
        Dict[str, Dict[str, Any]]: Et dictionary med brukernavn som nøkler og hytte-informasjon som verdier.
    """
    try:
        with open(toml_file_path, "r", encoding="utf-8") as file:
            config = toml.load(file)
    except FileNotFoundError:
        logger.error("Konfigurasjonsfil ikke funnet: %s", toml_file_path)
        return {}
    except toml.TomlDecodeError:
        logger.error("Konfigurasjonsfil ikke funnet: %s", toml_file_path)
        return {}

    logger.info("Starter mapping av hytter til brukere fra fil: %s", toml_file_path)

    cabin_coordinates = config.get("cabin_coordinates", {})
    users = config.get("auth_codes", {}).get("users", {})
    if not cabin_coordinates or not users:
        logger.warning("Manglende nødvendig konfigurasjon i TOML-filen")
        return {}

    cabin_user_map = {}
    for username, _ in users.items():
        match = re.match(r"^(\d+),", username)
        if match:
            cabin_number = match.group(1)
            cabin_user_map[cabin_number] = username

    result = {}
    for cabin_id, coordinates in cabin_coordinates.items():
        user = cabin_user_map.get(cabin_id)
        if user:
            result[user] = {
                "cabin_number": cabin_id,
                "latitude": coordinates.get("latitude"),
                "longitude": coordinates.get("longitude"),
                "rode": coordinates.get("rode"),
                "icon": coordinates.get("icon"),
            }
        else:
            logger.warning("Ingen bruker funnet for hytte %s", cabin_id)

    logger.info("Fullført mapping av %s hytter til brukere", len(result))
    return result

def get_passwords():
    try:
        logger.info("Attempting to load passwords from secrets")
        passwords = st.secrets["passwords"]
        logger.info(f"Successfully loaded passwords. Number of entries: {len(passwords)}")
        return passwords
    except Exception as e:
        logger.error(f"Unexpected error loading passwords: {str(e)}")
        return {}

def validate_toml_structure(config: Dict[str, Any]) -> bool:
    """
    Validerer strukturen til den innlastede TOML-konfigurasjonen.

    Args:
        config (Dict[str, Any]): Den innlastede TOML-konfigurasjonen.

    Returns:
        bool: True hvis strukturen er gyldig, False ellers.
    """
    required_keys = ["cabin_coordinates", "auth_codes"]
    for key in required_keys:
        if key not in config:
            logger.error("Manglende nøkkel i TOML-konfigurasjon: %s", key)
            return False

    if "users" not in config["auth_codes"]:
        logger.error("Manglende 'users' nøkkel i 'auth_codes' seksjon")
        return False

    return True

def is_active_booking(
    booking: Optional[pd.Series], current_date: datetime.date
) -> bool:
    """
    Sjekker om en bestilling er aktiv på en gitt dato.

    Args:
        booking (Optional[pd.Series]): En serie med bestillingsdata
        current_date (datetime.date): Datoen å sjekke mot

    Returns:
        bool: True hvis bestillingen er aktiv, False ellers
    """
    if booking is None:
        return False

    ankomst = booking["ankomst"].date()
    avreise = booking["avreise"].date() if pd.notnull(booking["avreise"]) else None

    if booking["abonnement_type"] == "Årsabonnement":
        return current_date.weekday() == 4 or ankomst == current_date
    elif booking["abonnement_type"] == "Ukentlig ved bestilling":
        return ankomst == current_date
    else:
        if avreise:
            return ankomst <= current_date <= avreise
        else:
            return ankomst == current_date

# Example usage:
# toml_file_path = 'path/to/your/config.toml'
# cabin_user_data = map_cabins_to_users(toml_file_path)
# if cabin_user_data:
#     for user, data in cabin_user_data.items():
#         print(f"User: {user}")
#         print(f"Cabin: {data['cabin_number']}")
#         print(f"Coordinates: {data['latitude']}, {data['longitude']}")
#         print(f"Rode: {data['rode']}")
#         print(f"Icon: {data['icon']}")
#         print("---")
# else:
#     print("Ingen data tilgjengelig eller feil i prosessering.")
