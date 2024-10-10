import hashlib
import os
import hmac
import logging
import sqlite3
import string
import secrets
from datetime import datetime
import time as pytime
import streamlit as st
from constants import TZ, SESSION_TIMEOUT, LOCKOUT_PERIOD, MAX_ATTEMPTS

from logging_config import get_logger

from customer_utils import get_customer_by_id   

from logging_config import get_logger

logger = get_logger(__name__)

def authenticate_user(user_id, password):
    try:
        conn = sqlite3.connect('customer.db')
        cursor = conn.cursor()
        
        query = "SELECT Id FROM customers WHERE Id = ?"
        cursor.execute(query, (user_id,))
        
        result = cursor.fetchone()
        
        if result:
            passwords = st.secrets["passwords"]
            if str(user_id) in passwords and passwords[str(user_id)] == password:
                logger.info(f"User {user_id} authenticated successfully")
                return True
            else:
                logger.warning(f"Authentication failed for user {user_id}: Invalid password")
        else:
            logger.warning(f"Authentication failed: No user found with ID {user_id}")
        
        return False
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred during authentication for user {user_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error occurred during authentication for user {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def generate_secure_code():
    return hashlib.sha256(os.urandom(32)).hexdigest()[:8]

def validate_code(stored_code, provided_code):
    return hmac.compare_digest(stored_code, provided_code)

def check_session_timeout():
    if 'last_activity' in st.session_state:
        if pytime.time() - st.session_state.last_activity > SESSION_TIMEOUT:
            st.session_state.authenticated = False
            st.session_state.user_id = None
            st.warning("Din sesjon har utløpt. Vennligst logg inn på nytt.")
    st.session_state.last_activity = pytime.time()

def generate_credentials(customer):
    # Generer brukernavn basert på Id
    user_id = f"user{customer['Id']}"
    
    # Generer midlertidig passord
    alphabet = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(alphabet) for i in range(12))
    
    return user_id, temp_password

def login_page():
    st.title("Logg inn")
    user_id = st.text_input("Skriv inn bruker-ID", key="login_user_id")
    password = st.text_input("Skriv inn passord", type="password", key="login_password")
    if st.button("Logg inn", key="login_button"):
        if authenticate_user(user_id, password):
            customer = get_customer_by_id(user_id)
            if customer is not None:
                st.session_state.authenticated = True
                st.session_state.user_id = user_id
                st.success(f"Innlogget som {user_id}")
                st.rerun()
            else:
                st.error("Brukerinformasjon ikke funnet. Kontakt administrator.")
        else:
            st.error("Ugyldig bruker-ID eller passord")
            log_failed_attempt(user_id)

def log_login(user_id, success=True):
    try:
        login_time = datetime.now(TZ).isoformat()
        query = "INSERT INTO login_history (user_id, login_time, success) VALUES (?, ?, ?)"
        execute_query('login_history', query, (user_id, login_time, 1 if success else 0))
        logger.info(f"{'Vellykket' if success else 'Mislykket'} innlogging for bruker: {user_id}")
    except Exception as e:
        logger.error(f"Feil ved logging av innlogging: {str(e)}")

def log_failed_attempt(user_id):
    try:
        current_time = datetime.now(TZ).isoformat()
        query = "INSERT INTO login_history (user_id, login_time, success) VALUES (?, ?, ?)"
        execute_query('login_history', query, (user_id, current_time, 0))
        logger.warning(f"Failed login attempt for user: {user_id}")
    except Exception as e:
        logger.error(f"Error logging failed login attempt: {str(e)}")

def log_successful_attempt(user_id):
    try:
        current_time = datetime.now(TZ).isoformat()
        query = "INSERT INTO login_history (user_id, login_time, success) VALUES (?, ?, ?)"
        execute_query('login_history', query, (user_id, current_time, 1))
        logger.info(f"Successful login for user: {user_id}")
    except Exception as e:
        logger.error(f"Error logging successful login: {str(e)}")

def check_rate_limit(code):
    now = datetime.now()
    if code in failed_attempts:
        attempts, last_attempt = failed_attempts[code]
        if now - last_attempt < LOCKOUT_PERIOD:
            if attempts >= MAX_ATTEMPTS:
                return False
        else:
            attempts = 0
    else:
        attempts = 0

    failed_attempts[code] = (attempts + 1, now)
    return True

def reset_rate_limit(code):
    if code in failed_attempts:
        del failed_attempts[code]

def get_login_history(start_date, end_date):
    with get_db_connection('login_history') as conn:
        query = "SELECT * FROM login_history WHERE login_time BETWEEN ? AND ? ORDER BY login_time DESC"
        df = pd.read_sql_query(query, conn, params=(start_date.isoformat(), end_date.isoformat()))
    
    # Lokaliser tidsstemplene til UTC før konvertering
    df['login_time'] = pd.to_datetime(df['login_time']).dt.tz_localize('UTC').dt.tz_convert(TZ)
    return df
