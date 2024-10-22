import hashlib
import os
import hmac
import sqlite3
import base64
import string
import secrets
import pandas as pd
from sqlalchemy import text
from datetime import datetime
import time as pytime
import streamlit as st

from constants import TZ, SESSION_TIMEOUT, LOCKOUT_PERIOD, MAX_ATTEMPTS
from config import DATABASE_PATH
from validation_utils import sanitize_input
from db_utils import verify_login_history_db, execute_query, get_db_engine, get_db_connection

from customer_utils import get_customer_by_id

from logging_config import get_logger

logger = get_logger(__name__)
    
def authenticate_user(user_id, password):
    try:
        sanitized_user_id = sanitize_input(user_id)
        
        with get_db_connection('customer') as conn:
            cursor = conn.cursor()
            query = "SELECT Id FROM customers WHERE Id = ?"
            cursor.execute(query, (sanitized_user_id,))
            result = cursor.fetchone()
            
            if result:
                try:
                    passwords = st.secrets["passwords"]
                    if str(sanitized_user_id) in passwords and passwords[str(sanitized_user_id)] == password:
                        logger.info(f"User {sanitized_user_id} authenticated successfully")
                        return True
                    else:
                        logger.warning(f"Authentication failed for user {sanitized_user_id}: Invalid password")
                except KeyError as e:
                    logger.error(f"Missing passwords in secrets for user {sanitized_user_id}")
                    return False
            else:
                logger.warning(f"Authentication failed: No user found with ID {sanitized_user_id}")
            
            return False
            
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred during authentication for user {sanitized_user_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error occurred during authentication for user {sanitized_user_id}: {e}")
        return False

def get_base64(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def set_background(png_file):
    bin_str = get_base64(png_file)
    page_bg_img = '''
    <style>
    .stApp {
        background-image: url("data:image/png;base64,%s");
        background-size: cover;
    }
    </style>
    ''' % bin_str
    st.markdown(page_bg_img, unsafe_allow_html=True)
    
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

# auth_utils.py

def login_page():
    st.title("Fjellbergsskardet Hyttegrend")
    
    id = st.text_input("Skriv inn ID", key="login_id")
    password = st.text_input("Skriv inn passord", type="password", key="login_password")
    
    if st.button("Logg inn", key="login_button"):
        logger.info(f"Login attempt for ID: {id}")
        if check_rate_limit(id):
            if authenticate_user(id, password):
                customer = get_customer_by_id(id)
                if customer is not None:
                    st.session_state.authenticated = True
                    st.session_state.user_id = id
                    if log_login(id, success=True):
                        logger.info(f"Successful login and logging for ID: {id}")
                        st.success(f"Innlogget som {id}")
                        reset_rate_limit(id)
                        st.rerun()
                    else:
                        logger.warning(f"Login successful but logging failed for ID: {id}")
                        st.warning("Innlogging vellykket, men logging feilet. Kontakt administrator.")
                else:
                    logger.warning(f"Authentication successful but customer info not found for ID: {id}")
                    st.error("Brukerinformasjon ikke funnet. Kontakt administrator.")
                    log_login(id, success=False)
            else:
                logger.warning(f"Failed login attempt for ID: {id}")
                st.error("Ugyldig ID eller passord")
                log_login(id, success=False)
        else:
            st.error("For mange mislykkede innloggingsforsøk. Vennligst prøv igjen senere.")
         
def log_login(id, success=True):
    try:
        if not verify_login_history_db():
            logger.error("Unable to log login attempt: login_history database does not exist")
            return False
        
        if not success and not check_rate_limit(id):
            logger.warning(f"Login attempt rejected due to rate limiting for user: {id}")
            return False

        login_time = datetime.now(TZ).isoformat()
        query = "INSERT INTO login_history (id, login_time, success) VALUES (?, ?, ?)"
        affected_rows = execute_query('login_history', query, (id, login_time, 1 if success else 0))
        
        if affected_rows > 0:
            logger.info(f"{'Successful' if success else 'Failed'} login for ID: {id}")
            return True
        else:
            logger.warning(f"No rows affected when logging {'successful' if success else 'failed'} login for ID: {id}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error logging login attempt: {str(e)}")
        return False
    
def check_rate_limit(user_id):
    try:
        engine = get_db_engine('login_history.db')
        now = datetime.now(TZ)
        lockout_start = now - LOCKOUT_PERIOD

        query = text("""
            SELECT COUNT(*) as attempt_count, MAX(login_time) as last_attempt
            FROM login_history
            WHERE id = :user_id AND success = 0 AND login_time > :lockout_start
        """)

        with engine.connect() as connection:
            result = connection.execute(query, {"user_id": user_id, "lockout_start": lockout_start}).fetchone()

        if result:
            attempt_count, last_attempt = result
            if attempt_count >= MAX_ATTEMPTS:
                if now - last_attempt < LOCKOUT_PERIOD:
                    logger.warning(f"User {user_id} is locked out due to too many failed attempts")
                    return False
                else:
                    reset_rate_limit(user_id)

        logger.info(f"Rate limit check passed for user {user_id}")
        return True

    except Exception as e:
        logger.error(f"Error in check_rate_limit: {str(e)}", exc_info=True)
        return True  # Allow login attempt if there's an error checking the rate limit

def reset_rate_limit(user_id):
    try:
        engine = get_db_engine('login_history.db')
        query = text("""
            DELETE FROM login_history
            WHERE id = :user_id AND success = 0
        """)
        
        with engine.connect() as connection:
            connection.execute(query, {"user_id": user_id})
            connection.commit()
        
        logger.info(f"Rate limit reset for user {user_id}")
    except Exception as e:
        logger.error(f"Error in reset_rate_limit: {str(e)}", exc_info=True)

def get_login_history(start_datetime, end_datetime):
    try:
        df = fetch_login_data_from_db(start_datetime, end_datetime)
        
        if not df.empty and 'login_time' in df.columns:
            # Sort the DataFrame by login_time
            df = df.sort_values('login_time', ascending=False)
        else:
            logger.warning("No login data to process in get_login_history")
        
        return df
    except Exception as e:
        logger.error(f"Error in get_login_history: {str(e)}", exc_info=True)
        return pd.DataFrame()

def fetch_login_data_from_db(start_datetime, end_datetime):
    """
    Fetches login data from the database for a specified date range.
    """
    try:
        engine = get_db_engine('login_history.db')
        
        query = text("""
            SELECT 
                id,
                login_time,
                success
            FROM 
                login_history
            WHERE 
                login_time BETWEEN :start_date AND :end_date
            ORDER BY 
                login_time DESC
        """)
        
        with engine.connect() as connection:
            result = connection.execute(query, {
                'start_date': start_datetime.isoformat(),
                'end_date': end_datetime.isoformat()
            })
            
            df = pd.DataFrame(result.fetchall(), columns=result.keys())
            
            if not df.empty and 'login_time' in df.columns:
                df['login_time'] = pd.to_datetime(df['login_time'])
            else:
                logger.warning("No login data found or 'login_time' column is missing")
            
            return df
    
    except Exception as e:
        logger.error(f"Error fetching login data: {str(e)}", exc_info=True)
        return pd.DataFrame()
    
    except Exception as e:
        logger.error(f"Error fetching login data: {str(e)}")
        return pd.DataFrame()
