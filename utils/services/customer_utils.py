import os
import re
import sqlite3
from typing import Any, Dict, Optional, Tuple
from datetime import datetime

import pandas as pd
import streamlit as st

from utils.core.config import DATABASE_PATH, TZ
from utils.core.logging_config import get_logger
from utils.db.db_utils import fetch_data, get_db_connection
from utils.services.utils import get_passwords

logger = get_logger(__name__)


def insert_customer(
    customer_id: str, lat: float, lon: float, subscription: str, type: str
) -> bool:
    """Legger til eller oppdaterer en kunde i databasen"""
    try:
        conn = get_db_connection("customer")
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO customer 
            (customer_id, lat, lon, subscription, type)
            VALUES (?, ?, ?, ?, ?)
        """,
            (customer_id, lat, lon, subscription, type),
        )

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"Error inserting customer: {str(e)}")
        return False


def get_cabin_coordinates() -> Dict[str, Tuple[float, float]]:
    """
    Henter koordinater for alle hytter fra customer-databasen.
    """
    try:
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT customer_id, lat, lon FROM customer")
            results = cursor.fetchall()

            coordinates = {}
            for row in results:
                cabin_id, lat, lon = row
                if (
                    lat is not None
                    and lon is not None
                    and not (pd.isna(lat) or pd.isna(lon))
                ):
                    coordinates[str(cabin_id)] = (float(lat), float(lon))

            logger.debug(f"Hentet koordinater for {len(coordinates)} hytter")
            return coordinates

    except Exception as e:
        logger.error(f"Feil ved henting av hytte-koordinater: {str(e)}")
        return {}


def load_customer_database():
    """
    Laster kundedata fra databasen
    """
    try:
        query = """
            SELECT customer_id, lat, lon, subscription, type, created_at
            FROM customer
        """
        with get_db_connection() as conn:
            df = pd.read_sql_query(query, conn)
            
        logger.info(f"Lastet {len(df)} kunder fra databasen")
        logger.debug(f"Kolonner i kundedatabasen: {df.columns.tolist()}")
        
        # Sjekk påkrevde kolonner
        required_columns = ["customer_id", "subscription"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            logger.error(f"Manglende påkrevde kolonner i kundedatabasen: {', '.join(missing_columns)}")
            return pd.DataFrame()
            
        return df
        
    except Exception as e:
        logger.error(f"Feil ved lasting av kundedatabase: {str(e)}")
        return pd.DataFrame()


def get_bookings(start_date=None, end_date=None):
    try:
        # Først hent kundedata for å få subscription type
        customer_query = """
        SELECT customer_id, subscription 
        FROM customer
        WHERE subscription IN ('star_white', 'star_red')
        """
        
        with get_db_connection("customer") as conn:
            customer_df = pd.read_sql_query(customer_query, conn)
            
        # Map subscription types
        customer_df['abonnement_type'] = customer_df['subscription'].map({
            'star_white': 'Årsabonnement',
            'star_red': 'Ukentlig ved bestilling'
        })
        
        # Så hent bestillinger og koble med kundedata
        with get_db_connection("tunbroyting") as conn:
            booking_query = """
            SELECT id, bruker, ankomst_dato, ankomst_tid, 
                   avreise_dato, avreise_tid
            FROM tunbroyting_bestillinger
            """
            if start_date and end_date:
                booking_query += """
                WHERE (
                    (ankomst_dato BETWEEN ? AND ?) OR
                    (abonnement_type = 'Årsabonnement' AND 
                     (ankomst_dato <= ? OR avreise_dato >= ?))
                )
                """
            
            bookings_df = pd.read_sql_query(booking_query, conn, 
                params=[start_date, end_date, end_date, start_date] if start_date and end_date else None)
            
            # Koble med kundedata
            result_df = pd.merge(
                bookings_df,
                customer_df[['customer_id', 'abonnement_type']],
                left_on='bruker',
                right_on='customer_id',
                how='left'
            )
            
            return result_df

    except Exception as e:
        logger.error(f"Error in get_bookings: {str(e)}", exc_info=True)
        return pd.DataFrame()


def customer_edit_component(customer_id: str = None):
    try:
        st.subheader("Rediger kundeinformasjon")

        customer = None
        if customer_id:
            customer = get_customer_by_id(customer_id)

        if customer:
            with st.form("customer_edit_form"):
                id = st.text_input("Hytte/Kunde ID", value=customer["customer_id"])
                lat = st.number_input(
                    "Breddegrad",
                    value=float(customer["lat"]) if customer.get("lat") else 0.0,
                    format="%.6f",
                )
                lon = st.number_input(
                    "Lengdegrad",
                    value=float(customer["lon"]) if customer.get("lon") else 0.0,
                    format="%.6f",
                )
                icon = st.selectbox(
                    "Abonnement",
                    options=["star_red", "star_white", "dot_white", "admin", "none"],
                    index=0 if customer.get("icon") == "star_red" else 1,
                )
                role = st.selectbox(
                    "Type",
                    options=["Customer", "Admin", "Other"],
                    index=(
                        0
                        if not customer
                        else ["Customer", "Admin", "Other"].index(
                            customer.get("role", "Customer")
                        )
                    ),
                )

                if st.form_submit_button("Lagre"):
                    if insert_customer(id, lat, lon, icon, role):
                        st.success("Kunde oppdatert")
                    else:
                        st.error("Feil ved oppdatering av kunde")
        else:
            st.error(f"Ingen kunde funnet med ID: {customer_id}")

    except Exception as e:
        logger.error(f"Error in customer_edit_component: {str(e)}")
        st.error("En feil oppstod ved redigering av kunde")


def get_rode(customer_id):
    # Ekstraherer numerisk del av customer_id
    numeric_part = re.findall(r"\d+", str(customer_id))
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


def vis_arsabonnenter():
    """Viser liste over kunder med årsabonnement (Hvit stjerne)"""
    try:
        # Hent kundedata fra customer-databasen
        with get_db_connection("customer") as conn_customer:
            query_customers = """
                SELECT customer_id, subscription, type
                FROM customer
                WHERE subscription = 'star_white'  -- Kun hvit stjerne (årsabonnement)
                ORDER BY customer_id
            """
            df_customers = pd.read_sql_query(query_customers, conn_customer)
        
        # Hent bestillingsdata fra tunbroyting-databasen
        with get_db_connection("tunbroyting") as conn_tun:
            query_bookings = """
                SELECT bruker, ankomst_dato, avreise_dato, abonnement_type
                FROM tunbroyting_bestillinger
                WHERE abonnement_type = 'Årsabonnement'
            """
            df_bookings = pd.read_sql_query(query_bookings, conn_tun)
            
            # Konverter datoer til datetime
            df_bookings['ankomst_dato'] = pd.to_datetime(df_bookings['ankomst_dato'])
            df_bookings['avreise_dato'] = pd.to_datetime(df_bookings['avreise_dato'])
            
            # Sjekk om bestillingen er aktiv
            dagens_dato = pd.Timestamp.now(tz=TZ).date()
            df_bookings['er_aktiv'] = df_bookings.apply(
                lambda row: (
                    pd.notnull(row['ankomst_dato']) and 
                    pd.notnull(row['avreise_dato']) and
                    row['ankomst_dato'].date() <= dagens_dato <= row['avreise_dato'].date()
                ),
                axis=1
            )
            
            # Lag visningsversjon av dataframe
            visning_df = pd.DataFrame()
            visning_df["Hytte"] = df_customers["customer_id"].astype(str)
            visning_df["Rode"] = visning_df["Hytte"].apply(get_rode)
            visning_df["Type"] = "Årsabonnement"
            
            # Sjekk aktiv status mot bestillinger
            visning_df["Status"] = "Ikke aktiv"  # Standard status
            for idx, row in visning_df.iterrows():
                hytte_bestillinger = df_bookings[df_bookings['bruker'] == row['Hytte']]
                if not hytte_bestillinger.empty and hytte_bestillinger['er_aktiv'].any():
                    visning_df.at[idx, "Status"] = "Aktiv"
            
            # Sorter etter rode og hyttenummer
            def extract_numeric_part(hytte_nr):
                match = re.match(r'(\d+)', str(hytte_nr))
                return int(match.group(1)) if match else float('inf')
            
            visning_df["sort_key"] = visning_df["Hytte"].apply(extract_numeric_part)
            visning_df = visning_df.sort_values(["Rode", "sort_key"])
            visning_df = visning_df.drop("sort_key", axis=1)
            
            # Vis dataframe
            st.subheader("Kunder med årsabonnement")
            st.dataframe(
                visning_df,
                hide_index=True
            )
            
    except Exception as e:
        logger.error(f"Feil ved visning av årsabonnenter: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise årsabonnenter")


def setup_customer_data() -> bool:
    """Setter opp kundetabellen"""
    try:
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()

            # Sjekk om tabellen eksisterer og har data
            cursor.execute("SELECT COUNT(*) FROM customer")
            count = cursor.fetchone()[0]
            logger.info(f"Found {count} existing customers in database")

            if count > 0:
                logger.info("Customer database already initialized")
                return True
            else:
                logger.info("Customer database is empty, attempting to import from CSV")
                csv_path = ".streamlit/customers.csv"

                if not os.path.exists(csv_path):
                    logger.error(f"Customer CSV file not found at: {csv_path}")
                    return False

                try:
                    df = pd.read_csv(csv_path)
                    logger.info(f"Read {len(df)} customers from CSV")

                    for _, row in df.iterrows():
                        cursor.execute(
                            """
                            INSERT INTO customer 
                            (customer_id, lat, lon, subscription, type)
                            VALUES (?, ?, ?, ?, ?)
                        """,
                            (
                                str(row["Id"]),
                                float(row["Latitude"]),
                                float(row["Longitude"]),
                                row["Subscription"],
                                row["Type"],
                            ),
                        )

                    conn.commit()
                    logger.info(f"Successfully imported {len(df)} customers from CSV")
                    return True

                except Exception as csv_error:
                    logger.error(f"Failed to import from CSV: {str(csv_error)}")
                    return False

    except Exception as e:
        logger.error(f"Error checking customer data: {str(e)}", exc_info=True)
        return False


def get_customer_by_id(customer_id):
    try:
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            # Først, la oss se på tabellstrukturen
            cursor.execute("PRAGMA table_info(customer)")
            columns = cursor.fetchall()
            logger.info(f"Customer table columns: {columns}")
            
            cursor.execute(
                """
                SELECT customer_id, lat, lon, subscription, type, created_at 
                FROM customer 
                WHERE customer_id = ?
                """, 
                (customer_id,)
            )
            row = cursor.fetchone()
            
            if row:
                customer_data = {
                    "customer_id": row[0],
                    "lat": row[1],
                    "lon": row[2],
                    "subscription": row[3],
                    "Type": row[4],
                    "created_at": row[5]
                }
                logger.info(f"Retrieved customer data: {customer_data}")
                return customer_data
                
            logger.warning(f"No customer found with ID {customer_id}")
            return None
            
    except Exception as e:
        logger.error(f"Error getting customer {customer_id}: {str(e)}")
        return None