import time
from datetime import datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import streamlit as st

from utils.core.config import (
    LOCKOUT_PERIOD,
    MAX_ATTEMPTS,
    SESSION_TIMEOUT
)
from utils.core.logging_config import get_logger
from utils.db.db_utils import get_db_connection
from utils.services.customer_utils import get_customer_by_id
from utils.services.utils import get_passwords

logger = get_logger(__name__)


def check_rate_limit(customer_id: str) -> bool:
    try:
        with get_db_connection(
            "login_history"
        ) as conn:  # Bruk connection istedenfor engine
            cursor = conn.cursor()
            cutoff_time = (datetime.now() - LOCKOUT_PERIOD).isoformat()
            cursor.execute(
                """
                SELECT COUNT(*) FROM login_history 
                WHERE customer_id = ? AND success = 0 AND login_time > ?
            """,
                (customer_id, cutoff_time),
            )
            return cursor.fetchone()[0] < MAX_ATTEMPTS
    except Exception as e:
        logger.error(f"Error in check_rate_limit: {str(e)}")
        return True


def verify_password(customer_id: str, password: str) -> bool:
    """Verifiserer passord for en kunde"""
    try:
        passwords = get_passwords()  # Bruker get_passwords fra utils.services.utils
        if not passwords or customer_id not in passwords:
            logger.warning(f"No password found for customer {customer_id}")
            return False
            
        return passwords[customer_id] == password
        
    except Exception as e:
        logger.error(f"Error verifying password: {str(e)}")
        return False


def authenticate_user(customer_id: str, password: str) -> Tuple[bool, Optional[str]]:
    """Autentiserer en bruker"""
    try:
        logger.info(f"=== STARTING AUTHENTICATION FOR USER {customer_id} ===")
        
        # Verifiser passord
        if not verify_password(customer_id, password):
            logger.warning(f"Invalid password for user {customer_id}")
            log_login_attempt(customer_id, False)
            return False, "Feil hyttenummer eller passord"
            
        logger.info(f"Password verified for user {customer_id}")
        
        # Hent kundedata
        customer = get_customer_by_id(customer_id)
        if not customer:
            logger.error(f"Kunne ikke hente kundedata for {customer_id}")
            return False, "Kunne ikke hente brukerdata"
        
        # Logg vellykket innlogging
        log_login_attempt(customer_id, True)
        
        # Oppdater sesjonsinformasjon
        st.session_state.authenticated = True
        st.session_state.customer_id = customer_id
        st.session_state.authenticated_user = {
            "customer_id": customer_id,
            "type": customer.get("type", "Customer")
        }
        st.session_state.last_activity = time.time()
        
        logger.info(f"Bruker {customer_id} autentisert og sesjon oppdatert")
        logger.info(f"Session state etter autentisering: {dict(st.session_state)}")
        return True, None
        
    except Exception as e:
        logger.error(f"Autentiseringsfeil: {str(e)}")
        return False, "En feil oppstod under innlogging"


def check_session_timeout() -> bool:
    """Sjekker om sesjonen har utløpt"""
    if "last_activity" not in st.session_state:
        st.session_state.last_activity = time.time()
        return True

    current_time = time.time()
    if current_time - st.session_state.last_activity > SESSION_TIMEOUT:
        st.session_state.clear()
        st.error("Sesjonen har utløpt. Vennligst logg inn på nytt.")
        return False

    st.session_state.last_activity = time.time()  # Bruker time.time() direkte
    return True


def login_page():
    """Viser innloggingssiden"""
    st.title("Fjellbergsskardet Hyttegrend")
    
    with st.form("login_form"):
        user_id = st.text_input("Hyttenummer", key="login_id")
        password = st.text_input("Passord", type="password", key="login_password")
        submitted = st.form_submit_button("Logg inn")
        
        if submitted:
            success, error_msg = authenticate_user(user_id, password)
            
            if success:
                # Sjekk admin status
                customer = get_customer_by_id(user_id)
                if customer and customer.get("type") == "Superadmin":
                    st.session_state.is_admin = True

                st.success("Innlogging vellykket!")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(error_msg or "Feil ved innlogging")


def log_login_attempt(customer_id: str, success: bool):
    """Logger innloggingsforsøk"""
    try:
        with get_db_connection("login_history") as conn:
            cursor = conn.cursor()
            current_time = (
                datetime.now()
                .replace(tzinfo=ZoneInfo("Europe/Oslo"))
                .strftime("%Y-%m-%d %H:%M:%S")
            )
            cursor.execute(
                """
                INSERT INTO login_history (customer_id, login_time, success)
                VALUES (?, ?, ?)
            """,
                (customer_id, current_time, 1 if success else 0),
            )
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error logging login attempt: {str(e)}")
        return False


def can_manage_feedback(customer_id: str) -> bool:
    """Sjekker om bruker har tilgang til å administrere feedback"""
    try:
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT type FROM customer WHERE customer_id = ?", (customer_id,)
            )
            result = cursor.fetchone()
            return result and result[0] in ["Admin", "Superadmin"]
    except Exception as e:
        logger.error(f"Feil ved sjekk av feedback-tilgang: {str(e)}")
        return False


def verify_session_state():
    """Logger nåværende sesjonstilstand for debugging"""
    logger.info("=== Current Session State ===")
    logger.info(f"authenticated: {st.session_state.get('authenticated')}")
    logger.info(f"authenticated_user: {st.session_state.get('authenticated_user')}")
    logger.info(f"customer_id: {st.session_state.get('customer_id')}")
    logger.info("===========================")


def get_current_user_id() -> Optional[str]:
    """Henter gjeldende bruker-ID fra sesjonen"""
    return st.session_state.get("customer_id")
