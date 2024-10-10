import sqlite3
import logging
import secrets
import string
import pandas as pd
from typing import Dict, Tuple 
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import streamlit as st
from constants import TZ
from utils import get_passwords

from logging_config import get_logger

logger = get_logger(__name__)

def get_customer_name(user_id):
    db = load_customer_database()
    user = db.get(str(user_id))
    if user:
        return user['Name']
    return None

def get_customer_by_id(user_id):
    try:
        conn = sqlite3.connect('customer.db')
        cursor = conn.cursor()
        
        query = "SELECT Id, Latitude, Longitude, Subscription, Type FROM customers WHERE Id = ?"
        cursor.execute(query, (user_id,))
        
        result = cursor.fetchone()
        
        if result:
            customer_dict = {
                'Id': result[0],
                'Latitude': result[1],
                'Longitude': result[2],
                'Subscription': result[3],
                'Type': result[4]
            }
            
            logger.info(f"Successfully retrieved customer with ID: {user_id}")
            return customer_dict
        else:
            logger.warning(f"No customer found with ID: {user_id}")
            return None
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while retrieving customer with ID {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error occurred while retrieving customer with ID {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def validate_customers_and_passwords():
    logger.info("Validating customers and passwords")
    try:
        passwords = get_passwords()

        if not passwords:
            logger.warning("No passwords found")
            return

        conn = sqlite3.connect('customer.db')
        cursor = conn.cursor()

        # Hent alle kunde-IDer fra databasen
        cursor.execute("SELECT Id FROM customers")
        customer_ids = set(str(row[0]) for row in cursor.fetchall())

        if not customer_ids:
            logger.warning("Customer database is empty")
            return

        # Sjekk for kunder uten passord
        for customer_id in customer_ids:
            if customer_id not in passwords:
                logger.warning(f"Customer ID {customer_id} does not have a corresponding password")

        # Sjekk for passord uten tilsvarende kunde
        for password_id in passwords:
            if password_id not in customer_ids:
                logger.warning(f"Password ID {password_id} does not have a corresponding customer")

        logger.info("Customer and password validation complete")

    except sqlite3.Error as e:
        logger.error(f"SQLite error in validate_customers_and_passwords: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in validate_customers_and_passwords: {str(e)}")
    finally:
        if conn:
            conn.close()

def get_customer_id(identifier):
    try:
        conn = sqlite3.connect('customer.db')
        cursor = conn.cursor()
        
        query = "SELECT Id FROM customers WHERE Name = ?"
        cursor.execute(query, (identifier,))
        
        result = cursor.fetchone()
        
        if result:
            customer_id = result[0]
            logger.info(f"Successfully retrieved customer ID for name: {identifier}")
            return customer_id
        else:
            logger.warning(f"No customer found with name: {identifier}")
            return None
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while retrieving customer ID for name {identifier}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error occurred while retrieving customer ID for name {identifier}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_user_subscription(user_id):
    try:
        conn = sqlite3.connect('customer.db')
        cursor = conn.cursor()
        
        # Konverter user_id til string for å sikre kompatibilitet
        user_id = str(user_id)
        
        query = "SELECT Subscription FROM customers WHERE Id = ?"
        cursor.execute(query, (user_id,))
        
        result = cursor.fetchone()
        
        if result:
            subscription = result[0]
            logger.info(f"Successfully retrieved subscription for user with ID: {user_id}")
            return subscription
        else:
            logger.warning(f"No user found with ID: {user_id}")
            return "Ingen abonnement"
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while retrieving subscription for user with ID {user_id}: {e}")
        return "Ingen abonnement"
    except Exception as e:
        logger.error(f"Unexpected error occurred while retrieving subscription for user with ID {user_id}: {e}")
        return "Ingen abonnement"
    finally:
        if conn:
            conn.close()

def get_customer_details(user_id):
    try:
        conn = sqlite3.connect('customer.db')
        cursor = conn.cursor()
        
        # Convert user_id to string to ensure compatibility
        user_id = str(user_id)
        
        query = "SELECT * FROM customers WHERE Id = ?"
        cursor.execute(query, (user_id,))
        
        result = cursor.fetchone()
        
        if result:
            # Get column names
            columns = [description[0] for description in cursor.description]
            
            # Create a dictionary with column names as keys
            customer_dict = dict(zip(columns, result))
            
            # Add additional information
            customer_dict['rode'] = get_rode(user_id)
            customer_dict['subscription'] = get_user_subscription(user_id)
            
            logger.info(f"Successfully retrieved detailed information for customer with ID: {user_id}")
            return customer_dict
        else:
            logger.warning(f"No customer found with ID: {user_id}")
            return None
        
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while retrieving customer details for ID {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error occurred while retrieving customer details for ID {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_cabin_coordinates() -> Dict[str, Tuple[float, float]]:
    """
    Henter koordinater for alle hytter fra kundedatabasen.

    Returns:
        Dict[str, Tuple[float, float]]: En dictionary med hytte-ID som nøkkel og (breddegrad, lengdegrad) som verdi.
    """
    try:
        conn = sqlite3.connect('customer.db')
        cursor = conn.cursor()
        
        query = "SELECT Id, Latitude, Longitude FROM customers"
        cursor.execute(query)
        
        results = cursor.fetchall()
        
        coordinates = {}
        for row in results:
            cabin_id, lat, lon = row
            if lat is not None and lon is not None:
                coordinates[str(cabin_id)] = (float(lat), float(lon))
        
        return coordinates
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while retrieving cabin coordinates: {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error occurred while retrieving cabin coordinates: {e}")
        return {}
    finally:
        if conn:
            conn.close()
            
def check_cabin_user_consistency():
    try:
        passwords = get_passwords()
        
        if not passwords:
            logger.warning("No passwords found")
            return

        conn = sqlite3.connect('customer.db')
        cursor = conn.cursor()

        # Hent alle kunde-IDer fra databasen
        cursor.execute("SELECT Id FROM customers")
        customer_ids = set(str(row[0]) for row in cursor.fetchall())

        if not customer_ids:
            logger.warning("Customer database is empty")
            return

        # Sjekk for kunder uten passord
        for customer_id in customer_ids:
            if customer_id not in passwords:
                logger.warning(f"Kunde-ID: {customer_id} har ikke et passord")

        # Sjekk for passord uten tilsvarende kunde
        for user_id in passwords:
            if user_id not in customer_ids:
                logger.warning(f"Passord funnet for ID {user_id}, men ingen tilsvarende kunde i databasen")

        logger.info("Konsistenssjekk fullført")

    except sqlite3.Error as e:
        logger.error(f"SQLite error in check_cabin_user_consistency: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in check_cabin_user_consistency: {str(e)}")
    finally:
        if conn:
            conn.close()
 
def generate_credentials(customer):
    # Generer brukernavn basert på Id
    user_id = f"user{customer['Id']}"
    
    # Generer midlertidig passord
    alphabet = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(alphabet) for i in range(12))
    
    return user_id, temp_password

def send_credentials_email(customer, user_id, temp_password):
    try:
        sender_email = st.secrets["email"]["sender_address"]
        sender_password = st.secrets["email"]["sender_password"]

        message = MIMEMultipart("alternative")
        message["Subject"] = "Dine påloggingsdetaljer for Fjellbergsskardet-appen"
        message["From"] = sender_email
        message["To"] = customer['Email']

        text = f"""\
        Hei {customer['Name']},

        Her er dine påloggingsdetaljer for Fjellbergsskardet-appen:

        Brukernavn: {user_id}
        Midlertidig passord: {temp_password}

        Vennligst logg inn og endre passordet ditt ved første pålogging.

        Hvis du har spørsmål, ta kontakt.

        Mvh Fjellbergsskardet Drift 
        """

        part = MIMEText(text, "plain")
        message.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer['Email'], message.as_string())
        
        logger.info(f"E-post sendt til {customer['Email']} for bruker {user_id}")
        return True
    except Exception as e:
        logger.error(f"Feil ved sending av e-post til {customer['Email']}: {str(e)}")
        return False
       
def get_rode(customer_id):
    customer_id = int(customer_id)
    
    if 142 <= customer_id <= 168:
        return "1"
    elif 169 <= customer_id <= 199:
        return "2"
    elif 210 <= customer_id <= 240:
        return "3"
    elif 269 <= customer_id <= 307:
        return "4"
    elif 1 <= customer_id <= 13:
        return "5"
    elif 14 <= customer_id <= 50:
        return "6"
    elif 51 <= customer_id <= 69:
        return "7"
    else:
        return None

def load_customer_database():
    try:
        conn = sqlite3.connect('customer.db')
        query = "SELECT * FROM customers"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Konverter kolonner til riktig datatype
        if 'Id' in df.columns:
            df['Id'] = df['Id'].astype(str)
        if 'Latitude' in df.columns:
            df['Latitude'] = pd.to_numeric(df['Latitude'], errors='coerce')
        if 'Longitude' in df.columns:
            df['Longitude'] = pd.to_numeric(df['Longitude'], errors='coerce')
        
        logger.info(f"Successfully loaded {len(df)} customers from database")
        return df
    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while loading customer database: {e}")
        return pd.DataFrame()  # Return an empty DataFrame in case of error
    except pd.io.sql.DatabaseError as e:
        logger.error(f"Pandas SQL error occurred while loading customer database: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Unexpected error occurred while loading customer database: {e}")
        return pd.DataFrame()
    