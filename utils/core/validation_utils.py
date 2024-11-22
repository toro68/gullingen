"""
validation_utils.py - Sentralisert validering for Fjellbergsskardet
"""

import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import streamlit as st

from utils.core.config import (
    get_date_format,
    DATE_VALIDATION
)
from utils.core.logging_config import get_logger
from utils.db.connection import get_db_connection

logger = get_logger(__name__)


def validate_date(date_string: str) -> bool:
    """Validerer datoformat"""
    try:
        if not date_string:
            return False
        dt = datetime.strptime(date_string, get_date_format("database", "date"))
        year = dt.year
        return DATE_VALIDATION["min_year"] <= year <= DATE_VALIDATION["max_year"]
    except ValueError:
        return False


def validate_time(time_string: str) -> bool:
    """Validerer tidsformat (HH:MM)"""
    try:
        if not time_string:
            return False
        # Sjekk format HH:MM
        if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", time_string):
            return False
        return True
    except ValueError:
        return False


def validate_cabin_id(cabin_id: str) -> bool:
    """
    Validerer hyttenummer med alle spesialtilfeller
    """
    if not cabin_id:
        return False

    cabin_id = str(cabin_id).strip()

    # Enkeltsiffer validering (1-9)
    if cabin_id.isdigit() and len(cabin_id) == 1 and int(cabin_id) in [1, 5, 7, 9]:
        return True

    # Admin og spesialkontoer
    if cabin_id in ["999", "1111", "1112", "1113", "1114", "1115"]:
        return True

    # Parkeringsplasser
    if cabin_id in ["3A", "3B", "3C", "3D"]:
        return True

    # Vanlige hyttenummer
    if re.match(r"^\d+$", cabin_id):
        num = int(cabin_id)
        valid_ranges = [
            (1, 69),  # rode 5,6,7
            (142, 168),  # rode 1
            (169, 199),  # rode 2
            (210, 240),  # rode 3
            (269, 307),  # rode 4
        ]
        return any(start <= num <= end for start, end in valid_ranges)

    return False


def validate_customer_id(customer_id: str) -> bool:
    """
    Validerer bruker-ID (samme som cabin_id for nå)
    """
    return validate_cabin_id(customer_id)


def validate_user_input(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validerer generell brukerinput
    """
    validated = {}
    for key, value in input_data.items():
        if isinstance(value, str):
            validated[key] = sanitize_input(value, input_type="general")
        elif isinstance(value, (int, float)):
            validated[key] = value
        elif isinstance(value, dict):
            validated[key] = validate_user_input(value)
        elif isinstance(value, list):
            validated[key] = [
                (
                    validate_user_input(item)
                    if isinstance(item, dict)
                    else (
                        sanitize_input(item, input_type="general")
                        if isinstance(item, str)
                        else item
                    )
                )
                for item in value
            ]
        else:
            logger.warning(f"Ukjent datatype for {key}: {type(value)}")
            validated[key] = None
    return validated


def sanitize_input(input_str: str, input_type: str = "general") -> str:
    """
    Saniterer brukerinput basert på type

    Args:
        input_str: Strengen som skal saniteres
        input_type: Type input ('general', 'cabin_id', 'password', 'date', 'time')

    Returns:
        Sanitert streng
    """
    if not input_str:
        return ""

    input_str = str(input_str).strip()

    if input_type == "cabin_id":
        return re.sub(r"[^0-9A-D]", "", input_str)

    elif input_type == "password":
        return re.sub(r"[^a-zA-ZæøåÆØÅ0-9\s!]", "", input_str)

    elif input_type == "date":
        return re.sub(r"[^0-9\-]", "", input_str)

    elif input_type == "time":
        return re.sub(r"[^0-9:]", "", input_str)

    else:  # 'general'
        return re.sub(r"[^a-zA-Z0-9\s\-_.,]", "", input_str)


def validate_customers_and_passwords() -> bool:
    logger.info("Validering av kunder og passord")
    try:
        passwords = st.secrets.get("passwords", {})
        if not passwords:
            logger.error("Ingen passord funnet i secrets")
            return False

        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT customer_id FROM customer")
            customer_ids = {str(row[0]) for row in cursor.fetchall()}

        # Logg antall funnet
        logger.debug(f"Fant {len(customer_ids)} kunder og {len(passwords)} passord")

        # Valider at alle kunder har passord
        customers_without_pwd = customer_ids - set(passwords.keys())
        if customers_without_pwd:
            logger.error(f"Kunder uten passord: {customers_without_pwd}")
            return False

        # Valider at alle passord tilhører en kunde
        pwd_without_customer = set(passwords.keys()) - customer_ids
        if pwd_without_customer:
            logger.error(f"Passord uten kunde: {pwd_without_customer}")
            return False

        return True

    except Exception as e:
        logger.error(f"Feil i validate_customers_and_passwords: {str(e)}")
        return False


def validate_toml_structure(config: Dict[str, Any]) -> bool:
    """
    Validerer TOML konfigurasjonsfil struktur
    """
    required_sections = ["passwords", "api_keys", "mapbox"]
    if not all(section in config for section in required_sections):
        logger.error(
            f"Manglende seksjoner i TOML: {[s for s in required_sections if s not in config]}"
        )
        return False

    # Sjekk passwords
    passwords = config.get("passwords", {})
    for cabin_id, password in passwords.items():
        if not validate_cabin_id(cabin_id):
            logger.error(f"Ugyldig hyttenummer i passwords: {cabin_id}")
            return False
        if not isinstance(password, str) or len(password) < 6:
            logger.error(f"Ugyldig passord for hytte {cabin_id}")
            return False

    return True


# validerer bestilling i vis_rediger_bestilling
def validere_bestilling(data: Dict[str, Any]) -> bool:
    """
    Validerer en tunbrøytingsbestilling
    
    Args:
        data (Dict[str, Any]): Bestillingsdata med ankomst_dato og avreise_dato
        
    Returns:
        bool: True hvis bestillingen er gyldig
    """
    try:
        # Hvis avreisedato ikke er satt, er bestillingen gyldig
        if data.get("avreise_dato") is None:
            return True
            
        # Konverter datoer hvis de ikke allerede er datetime objekter
        ankomst = data["ankomst_dato"]
        if not isinstance(ankomst, datetime):
            ankomst = safe_to_datetime(ankomst)
            
        avreise = data["avreise_dato"]
        if not isinstance(avreise, datetime):
            avreise = safe_to_datetime(avreise)
            
        # Hvis vi ikke kan parse datoene, er bestillingen ugyldig
        if ankomst is None or avreise is None:
            logger.error("Kunne ikke konvertere datoer")
            return False
            
        # Sjekk at avreise er etter ankomst
        return avreise > ankomst
        
    except Exception as e:
        logger.error(f"Feil i validere_bestilling: {str(e)}")
        return False


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


def validate_feedback(feedback_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validerer feedback data"""
    try:
        required_fields = ["type", "comment", "customer_id"]

        # Sjekk påkrevde felt
        for field in required_fields:
            if not feedback_data.get(field):
                return False, f"Manglende påkrevd felt: {field}"

        # Valider type
        valid_types = ["Føreforhold", "Parkering", "Fasilitet", "Annet"]
        if feedback_data["type"] not in valid_types:
            return False, f"Ugyldig feedback type: {feedback_data['type']}"

        # Valider kommentarlengde
        if len(feedback_data["comment"]) > 1000:
            return False, "Kommentar er for lang (maks 1000 tegn)"

        # Valider customer_id
        if not validate_cabin_id(feedback_data["customer_id"]):
            return (
                False,
                f"Ugyldig hyttenummer for customer_id: {feedback_data['customer_id']}",
            )

        return True, None

    except Exception as e:
        logger.error(f"Feil i feedback validering: {str(e)}")
        return False, f"Systemfeil: {str(e)}"


def validate_user_id(user_id: str) -> bool:
    """
    Validerer bruker-ID (alias for validate_customer_id)
    """
    return validate_customer_id(user_id)
