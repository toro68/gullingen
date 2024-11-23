# utils/services/utils.py
import re
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
import toml

from utils.core.logging_config import get_logger

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
    """
    Henter passord fra Streamlit secrets på en sikker måte
    """
    try:
        logger.info("Attempting to load passwords from secrets")
        passwords = st.secrets.get("passwords", {})

        if not passwords:
            logger.error("No passwords found in secrets")
            return {}

        # Valider passordformat
        for cabin_id, password in passwords.items():
            if not isinstance(cabin_id, str) or not isinstance(password, str):
                logger.error(f"Invalid password format for cabin {cabin_id}")
                continue

            # Tillat spesialtilfeller som definert i validate_cabin_id
            if cabin_id in [
                "999",
                "1111",
                "1112",
                "1113",
                "1114",
                "1115",
                "3A",
                "3B",
                "3C",
                "3D",
            ]:
                continue

            # Tillat enkeltsifrede ID-er (1, 5, 7, 9)
            if cabin_id in ["1", "5", "7", "9"]:
                continue

            if not re.match(r"^\d{2,3}$", cabin_id):
                logger.error(f"Invalid cabin ID format: {cabin_id}")
                continue

        logger.info(f"Successfully loaded {len(passwords)} passwords")
        return passwords

    except Exception as e:
        logger.error(f"Error loading passwords: {str(e)}")
        return {}

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
