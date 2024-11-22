import os
import re
import sqlite3
from typing import Any, Dict, Optional, Tuple
from datetime import datetime

import pandas as pd
import streamlit as st

from utils.core.config import (
    TZ,
    DATE_FORMATS,
    get_date_format,
    get_current_time,
    get_default_date_range,
    DATE_VALIDATION,
    DATABASE_PATH
)
from utils.core.logging_config import get_logger
from utils.db.db_utils import fetch_data, get_db_connection
from utils.db.data_import import import_customers_from_csv
from utils.services.utils import get_passwords

logger = get_logger(__name__)

__all__ = [
    'get_customer_by_id',
    'handle_customers',
    'customer_edit_component',
    'vis_arsabonnenter'
]

def setup_customer_data() -> bool:
    """Setter opp kundetabellen"""
    try:
        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            
            # Start transaksjon
            conn.execute("BEGIN TRANSACTION")
            
            try:
                # Sjekk om tabellen eksisterer og har data
                cursor.execute("SELECT COUNT(*) FROM customer")
                count = cursor.fetchone()[0]
                
                if count > 0:
                    logger.info(f"Customer database already contains {count} records")
                    conn.commit()
                    return True
                
                logger.info("Customer database is empty, importing initial data")
                success = import_customers_from_csv()
                
                if success:
                    conn.commit()
                    return True
                else:
                    conn.rollback()
                    return False
                    
            except Exception as e:
                conn.rollback()
                raise e
                
    except Exception as e:
        logger.error(f"Error setting up customer data: {str(e)}")
        return False

def insert_customer(
    customer_id: str, 
    lat: float, 
    lon: float, 
    subscription: str, 
    type: str
) -> bool:
    """Legger til eller oppdaterer en kunde i databasen"""
    try:
        # Valider input
        if not all([customer_id, subscription, type]):
            logger.error("Manglende påkrevde felter")
            return False

        with get_db_connection("customer") as conn:
            cursor = conn.cursor()
            
            # Sjekk om kunden eksisterer
            cursor.execute(
                "SELECT created_at FROM customer WHERE customer_id = ?", 
                (customer_id,)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Oppdater eksisterende kunde
                query = """
                UPDATE customer 
                SET lat = ?, lon = ?, subscription = ?, type = ?
                WHERE customer_id = ?
                """
                params = (lat, lon, subscription, type, customer_id)
            else:
                # Sett inn ny kunde
                query = """
                INSERT INTO customer 
                (customer_id, lat, lon, subscription, type, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """
                params = (customer_id, lat, lon, subscription, type)

            cursor.execute(query, params)
            conn.commit()
            
            logger.info(f"{'Oppdaterte' if existing else 'La til'} kunde {customer_id}")
            return True

    except Exception as e:
        logger.error(f"Feil ved {'oppdatering' if existing else 'innsetting'} av kunde: {str(e)}")
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
        with get_db_connection("customer") as conn:
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
    """Komponent for redigering av kundeinformasjon"""
    try:
        st.subheader("Rediger kundeinformasjon")

        if not customer_id:
            logger.warning("Ingen kunde-ID oppgitt")
            st.error("Kunde-ID er påkrevd")
            return

        customer = get_customer_by_id(customer_id)
        if not customer:
            logger.error(f"Ingen kunde funnet med ID: {customer_id}")
            st.error(f"Ingen kunde funnet med ID: {customer_id}")
            return

        with st.form("customer_edit_form"):
            # Input-felt med validering
            id = st.text_input(
                "Hytte/Kunde ID", 
                value=customer["customer_id"],
                disabled=True  # Ikke tillat endring av ID
            )
            
            lat = st.number_input(
                "Breddegrad",
                value=float(customer["lat"]) if customer.get("lat") else 0.0,
                format="%.6f",
                min_value=-90.0,
                max_value=90.0
            )
            
            lon = st.number_input(
                "Lengdegrad",
                value=float(customer["lon"]) if customer.get("lon") else 0.0,
                format="%.6f",
                min_value=-180.0,
                max_value=180.0
            )
            
            subscription = st.selectbox(
                "Abonnement",
                options=["star_red", "star_white", "dot_white", "admin", "none"],
                index=["star_red", "star_white", "dot_white", "admin", "none"].index(
                    customer.get("subscription", "none")
                )
            )
            
            type = st.selectbox(
                "Type",
                options=["Customer", "Admin", "Superadmin"],
                index=["Customer", "Admin", "Superadmin"].index(
                    customer.get("type", "Customer")
                )
            )

            if st.form_submit_button("Lagre"):
                if insert_customer(id, lat, lon, subscription, type):
                    st.success("Kunde oppdatert")
                    # Bruk den nye rerun() metoden istedenfor experimental_rerun()
                    st.rerun()
                else:
                    st.error("Feil ved oppdatering av kunde")

    except Exception as e:
        logger.error(f"Feil i customer_edit_component: {str(e)}", exc_info=True)
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
                SELECT customer_id, ankomst_dato, avreise_dato, abonnement_type
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
                hytte_bestillinger = df_bookings[df_bookings['customer_id'] == row['Hytte']]
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

def get_customer_by_id(customer_id):
    """Henter kundeinformasjon fra databasen"""
    try:
        if not customer_id:
            logger.error("Ingen customer_id oppgitt")
            return None
            
        logger.info(f"Forsøker å hente kunde med ID: {customer_id}")
        with get_db_connection("customer") as conn:
            query = """
                SELECT 
                    customer_id,
                    lat,
                    lon,
                    subscription,
                    type,
                    created_at
                FROM customer 
                WHERE customer_id = ?
            """
            cursor = conn.cursor()
            cursor.execute(query, (customer_id,))
            result = cursor.fetchone()
            
            if result:
                logger.info(f"Fant kundedata: {result}")
                return {
                    "customer_id": result[0],
                    "lat": result[1],
                    "lon": result[2],
                    "subscription": result[3],
                    "type": result[4],
                    "created_at": result[5]
                }
            
            logger.warning(f"Ingen kunde funnet med ID: {customer_id}")
            return None
            
    except Exception as e:
        logger.error(f"Feil ved henting av kunde med ID {customer_id}: {str(e)}", exc_info=True)
        return None

def handle_customers():
    """Administrasjonsfunksjon for å håndtere kunder"""
    try:
        st.title("Kundehåndtering")
        logger.info("Starting customer management page")

        # Last kundedata
        with get_db_connection("customer") as conn:
            query = """
                SELECT 
                    customer_id,
                    lat,
                    lon,
                    subscription,
                    type,
                    created_at
                FROM customer
                ORDER BY customer_id
            """
            df = pd.read_sql_query(query, conn)
            
        if df.empty:
            st.warning("Ingen kunder funnet i databasen")
            return

        # Vis statistikk
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Totalt antall kunder", len(df))
        with col2:
            st.metric("Årsabonnenter", len(df[df['subscription'] == 'star_white']))
        with col3:
            st.metric("Administratorer", len(df[df['type'].isin(['Admin', 'Superadmin'])]))

        # Filtreringsmuligheter
        st.subheader("Filtrer kunder")
        col1, col2 = st.columns(2)
        with col1:
            selected_types = st.multiselect(
                "Velg kundetype",
                options=sorted(df['type'].unique()),
                default=[]
            )
        with col2:
            selected_subscriptions = st.multiselect(
                "Velg abonnement",
                options=sorted(df['subscription'].unique()),
                default=[]
            )

        # Filtrer dataframe
        filtered_df = df.copy()
        if selected_types:
            filtered_df = filtered_df[filtered_df['type'].isin(selected_types)]
        if selected_subscriptions:
            filtered_df = filtered_df[filtered_df['subscription'].isin(selected_subscriptions)]

        # Vis kundetabell
        st.subheader("Kundeoversikt")
        st.dataframe(
            filtered_df,
            hide_index=True,
            column_config={
                "customer_id": "Kunde ID",
                "lat": "Breddegrad",
                "lon": "Lengdegrad",
                "subscription": "Abonnement",
                "type": "Type",
                "created_at": "Opprettet"
            }
        )

        # Rediger kunde
        st.subheader("Rediger kunde")
        kunde_id = st.text_input("Skriv inn kunde-ID for redigering")
        if kunde_id:
            customer_edit_component(kunde_id)

        # Vis årsabonnenter
        if st.checkbox("Vis detaljert oversikt over årsabonnenter"):
            vis_arsabonnenter()
            
    except Exception as e:
        logger.error(f"Feil i handle_customers: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved håndtering av kunder")
