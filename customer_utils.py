import sqlite3
import logging
import re
import os
import secrets
import string
import pandas as pd
from typing import Dict, Tuple, Any 
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import streamlit as st

from constants import TZ
from config import DATABASE_PATH
from utils import get_passwords

from logging_config import get_logger

logger = get_logger(__name__)

def get_customer_by_id(user_id):
    try:
        db_path = os.path.join(DATABASE_PATH, 'customer.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        query = "SELECT * FROM customers WHERE Id = ?"
        cursor.execute(query, (user_id,))
        
        result = cursor.fetchone()
        
        if result:
            columns = [column[0] for column in cursor.description]
            customer_dict = dict(zip(columns, result))
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
    # Ekstraherer numerisk del av customer_id
    numeric_part = re.findall(r'\d+', str(customer_id))
    if not numeric_part:
        return None
    
    customer_id = int(numeric_part[0])
    
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

def update_customer(customer_id: str, updates: Dict[str, Any]) -> bool:
    """
    Update customer information in the database.

    Args:
    customer_id (str): The ID of the customer to update.
    updates (Dict[str, Any]): A dictionary containing the fields to update and their new values.

    Returns:
    bool: True if the update was successful, False otherwise.
    """
    try:
        db_path = os.path.join(DATABASE_PATH, 'customer.db')
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Construct the SQL query dynamically based on the fields to update
            update_fields = ', '.join([f"{key} = ?" for key in updates.keys()])
            query = f"UPDATE customers SET {update_fields} WHERE Id = ?"

            # Prepare the values for the query
            values = list(updates.values()) + [customer_id]

            # Execute the update query
            cursor.execute(query, values)
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"Successfully updated customer with ID: {customer_id}")
                return True
            else:
                logger.warning(f"No customer found with ID: {customer_id}. No update performed.")
                return False

    except sqlite3.Error as e:
        logger.error(f"SQLite error occurred while updating customer with ID {customer_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error occurred while updating customer with ID {customer_id}: {e}")
        return False

def customer_edit_component():
    st.header("Rediger kundeinformasjon")

    # Input felt for kunde-ID
    customer_id = st.text_input("Skriv inn kunde-ID")

    if customer_id:
        # Hent eksisterende kundedata
        customer_data = get_customer_by_id(customer_id)

        if customer_data:
            st.subheader(f"Redigerer kunde: {customer_id}")

            # Opprett input-felter for hver kundeegenskap
            updates: Dict[str, Any] = {}
            
            updates['Latitude'] = st.number_input("Breddegrad", value=float(customer_data.get('Latitude', 0)), format="%.6f")
            updates['Longitude'] = st.number_input("Lengdegrad", value=float(customer_data.get('Longitude', 0)), format="%.6f")
            
            # Oppdaterte subscription-kategorier med hjelpetekst
            subscription_options = [
                'star_red (Ukentlig)',
                'star_white (Årsabonnement)',
                'dot_white (Ikke tunbrøyting)',
                'admin',
                'none'
            ]
            current_subscription = customer_data.get('Subscription', 'none')
            
            # Håndter tilfeller der eksisterende subscription ikke er i listen
            if current_subscription not in [opt.split()[0] for opt in subscription_options]:
                subscription_options.append(current_subscription)
                st.warning(f"Merk: Kunden har en uventet subscription-verdi: {current_subscription}")
            
            selected_subscription = st.selectbox(
                "Abonnement",
                options=subscription_options,
                index=next((i for i, opt in enumerate(subscription_options) if opt.startswith(current_subscription)), 0),
                format_func=lambda x: x  # Viser hele teksten inkludert hjelpetekst
            )
            updates['Subscription'] = selected_subscription.split()[0]  # Lagrer bare abonnementskoden
            
            # Oppdaterte type-kategorier
            type_options = ['Cabin', 'Customer', 'Admin', 'Other']
            current_type = customer_data.get('Type', 'Other')
            
            # Håndter tilfeller der eksisterende type ikke er i listen
            if current_type not in type_options:
                type_options.append(current_type)
                st.warning(f"Merk: Kunden har en uventet type-verdi: {current_type}")
            
            updates['Type'] = st.selectbox("Type", 
                                           options=type_options,
                                           index=type_options.index(current_type))

            # Legg til flere felt etter behov...

            if st.button("Oppdater kunde"):
                # Fjern uendrede verdier fra updates-dictionary
                updates = {k: v for k, v in updates.items() if v != customer_data.get(k)}
                
                if updates:
                    success = update_customer(customer_id, updates)
                    if success:
                        st.success(f"Kunde {customer_id} ble oppdatert vellykket!")
                    else:
                        st.error(f"Kunne ikke oppdatere kunde {customer_id}. Vennligst prøv igjen.")
                else:
                    st.info("Ingen endringer ble gjort.")
        else:
            st.error(f"Ingen kunde funnet med ID: {customer_id}")
               
def vis_arsabonnenter():
    st.subheader("Kunder med årsabonnement")

    # Last inn kundedatabasen
    kunder_df = load_customer_database()

    # Logg kolonnenavn for feilsøking
    logger.info(f"Kolonner i kundedatabasen: {kunder_df.columns.tolist()}")

    # Sjekk om nødvendige kolonner eksisterer
    required_columns = ['Id', 'Subscription']
    name_column = next((col for col in kunder_df.columns if col.lower() == 'name'), None)
    email_column = next((col for col in kunder_df.columns if col.lower() == 'email'), None)
    phone_column = next((col for col in kunder_df.columns if col.lower() == 'phone'), None)

    missing_columns = [col for col in required_columns if col not in kunder_df.columns]
    if missing_columns:
        st.error(f"Manglende påkrevde kolonner i kundedatabasen: {', '.join(missing_columns)}")
        logger.error(f"Manglende påkrevde kolonner i kundedatabasen: {', '.join(missing_columns)}")
        return

    # Filtrer ut kunder med årsabonnement
    arsabonnenter = kunder_df[kunder_df['Subscription'].isin(['star_white', 'star_gold'])]

    # Legg til rode-kolonne
    arsabonnenter['Rode'] = arsabonnenter['Id'].apply(lambda x: get_rode(x))

    # Sorter etter kundenavn hvis kolonnen eksisterer
    if name_column:
        arsabonnenter = arsabonnenter.sort_values(name_column)

    # Opprett en kollapsbar seksjon
    with st.expander("Vis kunder med årsabonnement"):
        if arsabonnenter.empty:
            st.write("Ingen kunder med årsabonnement funnet.")
        else:
            # Vis antall årsabonnenter
            st.write(f"Totalt antall årsabonnenter: {len(arsabonnenter)}")

            # Forbered kolonner for visning
            display_columns = ['Id', 'Subscription', 'Rode']
            column_config = {
                'Id': 'Kunde-ID',
                'Subscription': 'Abonnement',
                'Rode': 'Rode'
            }

            if name_column:
                display_columns.insert(1, name_column)
                column_config[name_column] = 'Navn'
            if email_column:
                display_columns.append(email_column)
                column_config[email_column] = 'E-post'
            if phone_column:
                display_columns.append(phone_column)
                column_config[phone_column] = 'Telefon'

            # Erstatt 'star_white' og 'star_gold' med 'Årsabonnement'
            arsabonnenter['Subscription'] = arsabonnenter['Subscription'].replace({'star_white': 'Årsabonnement', 'star_gold': 'Årsabonnement'})

            # Vis tabell med tilgjengelige kolonner
            st.dataframe(arsabonnenter[display_columns], 
                         hide_index=True,
                         column_config=column_config)

            # Legg til mulighet for å laste ned som CSV
            csv = arsabonnenter.to_csv(index=False)
            st.download_button(
                label="Last ned som CSV",
                data=csv,
                file_name="arsabonnenter.csv",
                mime="text/csv",
            )
          
# Helper function
def extract_numeric_id(customer_id):
    """Ekstraherer numerisk del av customer_id."""
    numeric_part = re.findall(r'\d+', str(customer_id))
    return int(numeric_part[0]) if numeric_part else None

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
    