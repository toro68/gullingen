import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

import streamlit as st

from utils.core.config import (
    DATABASE_PATH,
    LOCKOUT_PERIOD,
    MAX_ATTEMPTS,
    SESSION_TIMEOUT,
    TZ,
)
from utils.core.logging_config import get_logger
from utils.core.validation_utils import sanitize_input, validate_cabin_id, validate_user_id
from utils.db.db_utils import get_db_connection
from utils.services.customer_utils import get_customer_by_id
from utils.services.utils import get_passwords

logger = get_logger(__name__)


def check_rate_limit(user_id: str) -> bool:
    try:
        with get_db_connection(
            "login_history"
        ) as conn:  # Bruk connection istedenfor engine
            cursor = conn.cursor()
            cutoff_time = (datetime.now() - LOCKOUT_PERIOD).isoformat()
            cursor.execute(
                """
                SELECT COUNT(*) FROM login_history 
                WHERE user_id = ? AND success = 0 AND login_time > ?
            """,
                (user_id, cutoff_time),
            )
            return cursor.fetchone()[0] < MAX_ATTEMPTS
    except Exception as e:
        logger.error(f"Error in check_rate_limit: {str(e)}")
        return True


def authenticate_user(user_id: str, password: str) -> Tuple[bool, str]:
    try:
        logger.info(f"=== STARTING AUTHENTICATION FOR USER {user_id} ===")
        
        # Valider input
        if not validate_user_id(user_id):
            logger.warning(f"Invalid user ID format: {user_id}")
            return False, "Ugyldig hyttenummer"
            
        # Hent passord fra secrets
        passwords = get_passwords()
        correct_password = passwords.get(user_id)
        
        if not correct_password:
            logger.warning(f"No password found for user {user_id}")
            return False, "Bruker ikke funnet"
            
        # Sjekk passord
        if password == correct_password:
            logger.info(f"Password verified for user {user_id}")
            
            try:
                # Logg vellykket innlogging
                with get_db_connection("login_history") as login_conn:
                    login_cursor = login_conn.cursor()
                    login_cursor.execute(
                        """
                        INSERT INTO login_history (user_id, login_time, success) 
                        VALUES (?, datetime('now'), 1)
                        """,
                        (user_id,),
                    )
                    login_conn.commit()
                    logger.info(f"Successfully logged login for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to record login: {str(e)}", exc_info=True)
                
            return True, None
        else:
            logger.warning(f"Invalid password attempt for user {user_id}")
            return False, "Feil passord"

    except Exception as e:
        logger.error(f"Authentication error: {str(e)}", exc_info=True)
        return False, f"Systemfeil: {str(e)}"


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
        id = st.text_input("Hyttenummer", key="login_id")
        password = st.text_input("Passord", type="password", key="login_password")
        submitted = st.form_submit_button("Logg inn")

        if submitted:
            with st.spinner("Logger inn..."):
                success, error_msg = authenticate_user(id, password)

                if success:
                    st.session_state.authenticated = True
                    st.session_state.user_id = sanitize_input(id, input_type="cabin_id")
                    st.session_state.last_activity = time.time()

                    # Sjekk admin status
                    customer = get_customer_by_id(st.session_state.user_id)
                    if customer and customer.get("role") == "admin":
                        st.session_state.is_admin = True

                    st.success("Innlogging vellykket!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(error_msg or "Feil hyttenummer eller passord")


def log_login_attempt(user_id: str, success: bool):
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
                INSERT INTO login_history (user_id, login_time, success)
                VALUES (?, ?, ?)
            """,
                (user_id, current_time, 1 if success else 0),
            )
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error logging login attempt: {str(e)}")
        return False


def can_manage_feedback(user_id: str) -> bool:
    """Sjekker om bruker har tilgang til å administrere feedback"""
    try:
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT type FROM customer WHERE customer_id = ?", (user_id,)
            )
            result = cursor.fetchone()
            return result and result[0] in ["Admin", "Superadmin"]
    except Exception as e:
        logger.error(f"Feil ved sjekk av feedback-tilgang: {str(e)}")
        return False
