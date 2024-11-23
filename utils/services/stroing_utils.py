import sqlite3
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, Optional

import altair as alt
import pandas as pd
import streamlit as st

from utils.core.config import (
    TZ,
    get_date_format
)
from utils.core.logging_config import get_logger
from utils.core.validation_utils import validate_customer_id  
from utils.db.db_utils import get_db_connection
from utils.services.customer_utils import get_rode
from utils.core.auth_utils import get_current_user_id
logger = get_logger(__name__)

# Helper functions


def update_stroing_table_structure():
    with get_db_connection("stroing") as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE stroing_bestillinger_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id TEXT NOT NULL,
                    bestillings_dato TEXT NOT NULL,
                    onske_dato TEXT NOT NULL,
                    kommentar TEXT,
                    status TEXT
                )
            """
            )

            # Kopier data fra den gamle tabellen til den nye
            cursor.execute(
                """
                INSERT INTO stroing_bestillinger_new (id, customer_id, bestillings_dato, onske_dato)
                SELECT id, customer_id, bestillings_dato, onske_dato FROM stroing_bestillinger
            """
            )

            # Slett den gamle tabellen
            cursor.execute("DROP TABLE stroing_bestillinger")

            # Gi den nye tabellen det gamle navnet
            cursor.execute(
                "ALTER TABLE stroing_bestillinger_new RENAME TO stroing_bestillinger"
            )

            conn.commit()
            logger.info("Successfully updated stroing_bestillinger table structure")
            return True
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating stroing_bestillinger table structure: {e}")
            return False


# Create
def lagre_stroing_bestilling(customer_id: str, onske_dato: str, kommentar: str = None) -> bool:
    try:
        # Valider bruker-ID
        if not validate_customer_id(customer_id):
            logger.error(f"Ugyldig kunde-ID: {customer_id}")
            return False

        # Valider ønsket dato
        try:
            dato = datetime.fromisoformat(onske_dato)
            if dato.date() < datetime.now(TZ).date():
                logger.error(f"Ugyldig dato (i fortiden): {onske_dato}")
                return False
        except ValueError:
            logger.error(f"Ugyldig datoformat: {onske_dato}")
            return False

        with get_db_connection("stroing") as conn:
            c = conn.cursor()
            
            # Sjekk om bruker allerede har bestilling på denne datoen
            c.execute(
                """
                SELECT COUNT(*) FROM stroing_bestillinger 
                WHERE customer_id = ? AND date(onske_dato) = date(?)
                """,
                (customer_id, onske_dato)
            )
            
            if c.fetchone()[0] > 0:
                logger.warning(f"Bruker {customer_id} har allerede strøingsbestilling på {onske_dato}")
                return False

            bestillings_dato = datetime.now(TZ).isoformat()

            c.execute(
                """
                INSERT INTO stroing_bestillinger 
                (customer_id, bestillings_dato, onske_dato, kommentar)
                VALUES (?, ?, ?, ?)
                """,
                (customer_id, bestillings_dato, onske_dato, kommentar),
            )

            conn.commit()

        logger.info(f"Ny strøingsbestilling lagret for bruker: {customer_id}")
        return True

    except sqlite3.Error as e:
        logger.error(f"SQLite-feil ved lagring av strøingsbestilling: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Uventet feil ved lagring av strøingsbestilling: {str(e)}")
        return False


def bestill_stroing():
    try:
        st.title("Bestill Strøing")
        
        customer_id = get_current_user_id()
        if not customer_id:
            logger.error("Ingen customer_id funnet i sesjonen")
            st.error("Du må være logget inn for å bestille strøing")
            return
            
        # Informasjonstekst
        st.info(
            """
        Strøing av stikkveier i Fjellbergsskardet Hyttegrend - Sesong 2024/2025

        - Vi strør veiene når brøytekontakten vurderer det som nødvendig og effektivt ut fra værforholdene. 
        - Hovedveien (Gullingvegen-Tjernet) blir alltid prioritert. Resten strøs på bestilling.
        - Ønsker du strøing av stikkveien din, kan du bestille dette her. 
        - Priser: Du betaler 500 kroner for sesongen, pluss 150 kroner for hver gang det strøs. 
        
        Tips ved glatte forhold:
        - Bruk piggdekk/kjetting
        - Ha med litt strøsand, spade og tau i bilen. 
        - Bruk strøsandkassene. Må stroppes etter bruk!
        - Brodder til beina
        """
        )

        # Generer liste med dagens dato og de neste 4 dagene
        today = datetime.now(TZ).date()
        available_dates = [today + timedelta(days=i) for i in range(5)]

        onske_dato = st.selectbox(
            "Velg dato for strøing:",
            available_dates,
            format_func=lambda x: x.strftime("%d.%m.%Y (%A)"),  # Viser ukedag i parentes
        )

        if onske_dato == today:
            st.warning("Det tas forbehold om godkjenning fra brøytekontakten.")
        elif onske_dato.weekday() >= 5:  # Lørdag eller søndag
            st.warning("Det tas forbehold om godkjenning fra brøytekontakten.")

        if st.button("Bestill Strøing"):
            if lagre_stroing_bestilling(customer_id, onske_dato.isoformat()):
                st.success("Bestilling av strøing er registrert!")
                logger.info(f"Strøing order successfully registered for user {customer_id}")
                st.rerun()
            else:
                st.error(
                    f"Du har allerede en bestilling for {onske_dato.strftime('%d.%m.%Y')}. "
                    "Du kan ikke bestille strøing flere ganger på samme dato."
                )
                logger.error(f"Failed to register strøing order for user {customer_id}")

            st.info("Merk: Du vil bli fakturert kun hvis strøing utføres.")

        # Vis tidligere bestillinger
        display_stroing_bookings(customer_id, show_header=True)
            
    except Exception as e:
        logger.error(f"Feil i bestill_stroing: {str(e)}")
        st.error("Det oppstod en feil. Vennligst prøv igjen senere.")


# Read
@st.cache_data(ttl=60)  # Cache data for 60 sekunder
def hent_og_behandle_data():
    alle_bestillinger = hent_stroing_bestillinger()
    dagens_dato = datetime.now(TZ).date()
    sluttdato = dagens_dato + timedelta(days=4)
    daglig_aktivitet = {
        dagen.date(): 0 for dagen in pd.date_range(dagens_dato, sluttdato)
    }

    for _, bestilling in alle_bestillinger.iterrows():
        onske_dato = bestilling["onske_dato"].date()
        if onske_dato in daglig_aktivitet:
            daglig_aktivitet[onske_dato] += 1

    aktivitet_df = pd.DataFrame.from_dict(
        daglig_aktivitet, orient="index", columns=["Antall bestillinger"]
    )
    aktivitet_df.index = pd.to_datetime(aktivitet_df.index)
    aktivitet_df.index = aktivitet_df.index.strftime("%Y-%m-%d")
    aktivitet_df.index.name = "Dato"

    return aktivitet_df, alle_bestillinger


def hent_stroing_bestillinger():
    try:
        with get_db_connection("stroing") as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            ORDER BY onske_dato DESC, bestillings_dato DESC
            """
            df = pd.read_sql_query(query, conn)

        # Konverter dato-kolonner til datetime
        for col in ["bestillings_dato", "onske_dato"]:
            df[col] = pd.to_datetime(df[col])

        # Logg kolonnenavnene
        logger.info(f"Kolonner i stroing_bestillinger: {df.columns.tolist()}")

        return df
    except Exception as e:
        logger.error(f"Feil ved henting av strøing-bestillinger: {str(e)}")
        return pd.DataFrame()

def hent_bruker_stroing_bestillinger(user_id):
    try:
        with get_db_connection("stroing") as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            WHERE customer_id = ? 
            ORDER BY bestillings_dato DESC
            """
            df = pd.read_sql_query(query, conn, params=(user_id,))

        # Konverter dato-kolonner til datetime
        for col in ["bestillings_dato", "onske_dato"]:
            df[col] = pd.to_datetime(df[col])

        return df
    except Exception as e:
        logger.error(
            f"Feil ved henting av strøing-bestillinger for bruker {user_id}: {str(e)}"
        )
        return pd.DataFrame()

def hent_stroing_bestilling(bestilling_id: int) -> Optional[Dict[str, Any]]:
    try:
        with get_db_connection("stroing") as conn:
            query = "SELECT * FROM stroing_bestillinger WHERE id = ?"
            cursor = conn.cursor()
            cursor.execute(query, (bestilling_id,))
            result = cursor.fetchone()
            if result:
                return dict(zip([column[0] for column in cursor.description], result))
            return None
    except Exception as e:
        logger.error(
            f"Feil ved henting av strøingsbestilling {bestilling_id}: {str(e)}"
        )
        return None

def count_stroing_bestillinger():
    with get_db_connection("stroing") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stroing_bestillinger")
        return cursor.fetchone()[0]

def admin_stroing_page():
    try:
        st.title("Håndter strøing")
        
        # Hent og behandle data
        aktivitet_df, alle_bestillinger = hent_og_behandle_data()
        
        if alle_bestillinger.empty:
            st.warning("Ingen strøingsbestillinger funnet.")
            return

        # Opprett faner i ny rekkefølge
        tab1, tab2, tab3 = st.tabs(["📅 Aktivitet", "📊 Oversikt", "📋 Alle bestillinger"])

        with tab1:
            st.info(
                """
                Strøing utføres basert på bestillinger og værforhold.
                Hovedveien til kryss Kalvaknutvegen prioriteres alltid, mens stikkveier strøs ved bestilling. 
                """
            )
            
            # Konverter datoer og fjern timezone
            alle_bestillinger['onske_dato'] = pd.to_datetime(alle_bestillinger['onske_dato']).dt.tz_localize(None)
            
            dagens_dato = pd.Timestamp.now(TZ).normalize().tz_localize(None)
            sluttdato = dagens_dato + pd.Timedelta(days=7)
            
            # Filtrer bestillinger for perioden
            mask = (alle_bestillinger['onske_dato'].dt.normalize() >= dagens_dato) & \
                   (alle_bestillinger['onske_dato'].dt.normalize() <= sluttdato)
            aktive_bestillinger = alle_bestillinger[mask].copy()
            
            if not aktive_bestillinger.empty:
                # Legg til rode informasjon
                aktive_bestillinger['rode'] = aktive_bestillinger['customer_id'].apply(get_rode)
                
                # Formater visningsdata
                visning_df = aktive_bestillinger.copy()
                visning_df['Dato'] = visning_df['onske_dato'].dt.strftime('%d.%m.%Y')
                visning_df['Ukedag'] = visning_df['onske_dato'].dt.strftime('%A').map({
                    'Monday': 'Mandag', 'Tuesday': 'Tirsdag', 'Wednesday': 'Onsdag',
                    'Thursday': 'Torsdag', 'Friday': 'Fredag', 'Saturday': 'Lørdag', 
                    'Sunday': 'Søndag'
                })
                
                # Velg og sorter kolonner
                visning_df = visning_df[['Dato', 'Ukedag', 'rode', 'customer_id']]
                visning_df = visning_df.rename(columns={'customer_id': 'Hytte'})
                visning_df = visning_df.sort_values(['Dato', 'rode', 'Hytte'])
                
                # Vis dataframe
                st.dataframe(
                    visning_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Dato": st.column_config.TextColumn(
                            "Dato",
                            width="medium",
                        ),
                        "Ukedag": st.column_config.TextColumn(
                            "Ukedag",
                            width="small",
                        ),
                        "rode": st.column_config.TextColumn(
                            "Rode",
                            width="small",
                        ),
                        "Hytte": st.column_config.TextColumn(
                            "Hytte",
                            width="small",
                        ),
                    }
                )
                
                st.write(f"Totalt antall strøingsbestillinger i perioden: {len(aktive_bestillinger)}")
            else:
                st.info("Ingen planlagte strøinger de neste 7 dagene.")

        with tab2:
            # Datovelgere
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("Fra dato", value=datetime.now(TZ).date())
            with col2:
                end_date = st.date_input(
                    "Til dato", 
                    value=datetime.now(TZ).date() + timedelta(days=7),
                    min_value=start_date
                )

            if start_date > end_date:
                st.error("Sluttdato må være etter startdato")
                return

            # Vis daglig oversikt
            st.subheader("Daglig oversikt over strøingsbestillinger")
            st.table(aktivitet_df)

            # Vis graf
            st.subheader("Daglige strøingsbestillinger")
            chart = lag_stroing_graf(aktivitet_df)
            st.altair_chart(chart, use_container_width=True)

        with tab3:
            st.subheader("Alle strøingsbestillinger")
            
            # Filtrer bestillinger basert på dato
            mask = (alle_bestillinger["onske_dato"].dt.date >= start_date) & (
                alle_bestillinger["onske_dato"].dt.date <= end_date
            )
            filtered_bestillinger = alle_bestillinger[mask]

            if filtered_bestillinger.empty:
                st.info(f"Ingen bestillinger funnet for perioden {start_date} til {end_date}")
                return

            # Legg til nedlastingsknapper
            st.subheader("Last ned data")
            col1, col2 = st.columns(2)
            
            # Lag en kopi for eksport og konverter datoer
            export_data = filtered_bestillinger.copy()
            
            # Konverter datetime-kolonner til timezone-naive
            datetime_columns = export_data.select_dtypes(include=['datetime64[ns, UTC]']).columns
            for col in datetime_columns:
                logger.debug(f"Konverterer {col} fra {export_data[col].dtype}")
                export_data[col] = pd.to_datetime(export_data[col]).dt.tz_localize(None)
                logger.debug(f"Ny dtype for {col}: {export_data[col].dtype}")

            with col1:
                csv = export_data.to_csv(index=False)
                st.download_button(
                    label="📥 Last ned som CSV",
                    data=csv,
                    file_name=f"stroingsbestillinger_{start_date}_{end_date}.csv",
                    mime="text/csv",
                )

            with col2:
                buffer = BytesIO()
                with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                    try:
                        export_data.to_excel(writer, sheet_name="Strøingsbestillinger", index=False)
                        logger.debug("Excel-fil generert vellykket")
                    except Exception as excel_error:
                        logger.error(f"Feil ved Excel-generering: {str(excel_error)}")
                        raise
                        
                st.download_button(
                    label="📊 Last ned som Excel",
                    data=buffer.getvalue(),
                    file_name=f"stroingsbestillinger_{start_date}_{end_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            # Vis bestillingstabell
            st.subheader("Bestillingsoversikt")
            st.dataframe(
                filtered_bestillinger,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "customer_id": "Bruker",
                    "bestillings_dato": "Bestilt",
                    "onske_dato": "Ønsket dato",
                    "kommentar": "Kommentar",
                    "status": "Status"
                }
            )

    except Exception as e:
        logger.error(f"Feil i admin_stroing_page: {str(e)}")
        st.error("Det oppstod en feil ved lasting av strøingsoversikten")

# Database initialization and maintenance
def verify_stroing_data():
    """Verifiser integritet av strøingsdata"""
    try:
        with get_db_connection("stroing") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stroing_bestillinger")
            
            columns = [description[0] for description in cursor.description]
            results = cursor.fetchall()
            
            if not results:
                logger.info("Ingen strøingsbestillinger å verifisere")
                return True
                
            df = pd.DataFrame(results, columns=columns)
            validation_errors = []
            
            # Valider datoformater
            for col in ['bestillings_dato', 'onske_dato']:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                invalid_dates = df[df[col].isna()]
                if not invalid_dates.empty:
                    validation_errors.append(
                        f"Ugyldige datoer i {col}: {invalid_dates.index.tolist()}"
                    )
            
            # Valider kunde-IDer
            invalid_customers = df[~df['customer_id'].apply(validate_customer_id)]
            if not invalid_customers.empty:
                validation_errors.append(
                    f"Ugyldige kunde-IDer: {invalid_customers['customer_id'].tolist()}"
                )
            
            if validation_errors:
                for error in validation_errors:
                    logger.error(error)
                return False
                
            logger.info("Strøingsdata verifisert uten feil")
            return True
            
    except Exception as e:
        logger.error(f"Feil ved verifisering av strøingsdata: {str(e)}", exc_info=True)
        return False

# Visninger
def display_stroing_bookings(customer_id: str, show_header: bool = False):
    try:
        if show_header:
            st.header("Dine strøingsbestillinger")
            
        bookings = hent_bruker_stroing_bestillinger(customer_id)
        if bookings.empty:
            st.info("Du har ingen aktive strøingsbestillinger")
            return
            
        date_format = get_date_format("display", "date")
        datetime_format = get_date_format("display", "datetime")
        
        for _, booking in bookings.iterrows():
            with st.expander(
                f"Bestilling for {booking['onske_dato'].strftime(date_format)}"
            ):
                st.write(f"Bestilt: {booking['bestillings_dato'].strftime(datetime_format)}")
                if booking.get('kommentar'):
                    st.write(f"Kommentar: {booking['kommentar']}")
                st.write(f"Status: {booking.get('status', 'Venter')}")
                
    except Exception as e:
        logger.error(f"Feil ved visning av strøingsbestillinger: {str(e)}")
        st.error("Kunne ikke vise dine bestillinger. Vennligst prøv igjen senere.")

def validate_stroing_data(data: pd.DataFrame) -> pd.DataFrame:
    """Validerer og renser strøingsdata"""
    try:
        # Kopier dataframe for å unngå advarsler
        df = data.copy()

        # Konverter datokolonner
        for col in ["bestillings_dato", "onske_dato"]:
            df[col] = pd.to_datetime(df[col], errors="coerce")

        # Fjern ugyldige datoer
        df = df.dropna(subset=["bestillings_dato", "onske_dato"])

        # Valider kunde-IDer
        df = df[df["customer_id"].apply(lambda x: validate_customer_id(str(x)))]

        return df

    except Exception as e:
        logger.error(f"Feil ved validering av strøingsdata: {str(e)}")
        return pd.DataFrame()

def log_stroing_activity(action: str, user_id: str, details: dict):
    """Logger strøingsaktivitet med detaljer"""
    try:
        log_entry = {
            "timestamp": datetime.now(TZ).isoformat(),
            "action": action,
            "user_id": user_id,
            "details": details,
        }
        logger.info(f"Strøingsaktivitet: {log_entry}")

    except Exception as e:
        logger.error(f"Feil ved logging av strøingsaktivitet: {str(e)}")


def initialize_stroing_database():
    """Initialiserer strøing-databasen med versjonskontroll"""
    try:
        with get_db_connection("stroing") as conn:
            cursor = conn.cursor()

            # Opprett hovedtabell med oppdatert skjema
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id TEXT NOT NULL,
                    bestillings_dato TEXT NOT NULL,
                    onske_dato TEXT NOT NULL,
                    kommentar TEXT,
                    status TEXT
                )
            """
            )
            
            # Opprett indeks
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_stroing_customer_id 
                ON stroing_bestillinger(customer_id)
            """)

            conn.commit()
            logger.info("Stroing database initialized successfully")
            return True

    except Exception as e:
        logger.error(f"Feil ved initialisering av strøing-databasen: {str(e)}")
        return False

def lag_stroing_graf(df):
    """Lager graf over strøingsbestillinger"""
    return alt.Chart(df.reset_index()).mark_bar().encode(
        x=alt.X('Dato:T', title='Dato', axis=alt.Axis(format='%d.%m', labelAngle=-45)),
        y=alt.Y('Antall bestillinger:Q', title='Antall bestillinger'),
        tooltip=['Dato', 'Antall bestillinger']
    ).properties(
        width=600,
        height=400,
        title='Daglige strøingsbestillinger'
    )

def get_stroing_bestillinger(start_date=None, end_date=None):
    try:
        query = "SELECT * FROM stroing_bestillinger WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND bestillings_dato >= ?"
            params.append(start_date)
            
        if end_date:
            query += " AND bestillings_dato <= ?"
            params.append(end_date)
            
        df = pd.read_sql_query(query, get_db_connection("stroing"), params=params)
        
        # Konverter datokolonner
        for col in ['bestillings_dato', 'onske_dato']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
                
        return df
        
    except Exception as e:
        logger.error(f"Error in get_stroing_bestillinger: {str(e)}", exc_info=True)
        return pd.DataFrame()
