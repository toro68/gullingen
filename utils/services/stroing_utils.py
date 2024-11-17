import math
import sqlite3
import traceback
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import altair as alt
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from utils.core.config import TZ
from utils.core.logging_config import get_logger
from utils.core.validation_utils import validate_user_id
from utils.db.db_utils import get_db_connection
from utils.services.customer_utils import get_rode
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
                    bruker TEXT NOT NULL,
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
                INSERT INTO stroing_bestillinger_new (id, bruker, bestillings_dato, onske_dato)
                SELECT id, bruker, bestillings_dato, onske_dato FROM stroing_bestillinger
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
def lagre_stroing_bestilling(user_id: str, onske_dato: str, kommentar: str = None) -> bool:
    try:
        # Valider bruker-ID
        if not validate_user_id(user_id):
            logger.error(f"Ugyldig bruker-ID: {user_id}")
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
                WHERE bruker = ? AND date(onske_dato) = date(?)
                """,
                (user_id, onske_dato)
            )
            
            if c.fetchone()[0] > 0:
                logger.warning(f"Bruker {user_id} har allerede strøingsbestilling på {onske_dato}")
                return False

            bestillings_dato = datetime.now(TZ).isoformat()

            c.execute(
                """
                INSERT INTO stroing_bestillinger 
                (bruker, bestillings_dato, onske_dato, kommentar, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, bestillings_dato, onske_dato, kommentar, "Pending"),
            )

            conn.commit()

        logger.info(f"Ny strøingsbestilling lagret for bruker: {user_id}")
        return True

    except sqlite3.Error as e:
        logger.error(f"SQLite-feil ved lagring av strøingsbestilling: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Uventet feil ved lagring av strøingsbestilling: {str(e)}")
        return False


def bestill_stroing():
    if "title" not in st.session_state:
        st.session_state["title"] = "Bestill Strøing"
    st.title(st.session_state["title"])

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
        result = lagre_stroing_bestilling(
            st.session_state.user_id, onske_dato.isoformat()
        )
        if result:
            st.success("Bestilling av strøing er registrert!")
            logger.info(
                f"Strøing order successfully registered for user {st.session_state.user_id}"
            )
        else:
            st.error(
                f"Du har allerede en bestilling for {onske_dato.strftime('%d.%m.%Y')}. "
                "Du kan ikke bestille strøing flere ganger på samme dato."
            )
            logger.error(
                f"Failed to register strøing order for user {st.session_state.user_id}"
            )

        st.info("Merk: Du vil bli fakturert kun hvis strøing utføres.")

    # Vis tidligere bestillinger én gang, med overskrift
    display_stroing_bookings(st.session_state.user_id, show_header=True)


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
            WHERE bruker = ? 
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


# def hent_utforte_stroingsbestillinger() -> pd.DataFrame:
#     try:
#         with get_db_connection('stroing') as conn:
#             query = """
#             SELECT * FROM stroing_bestillinger
#             WHERE utfort_dato IS NOT NULL
#             ORDER BY utfort_dato DESC
#             """
#             df = pd.read_sql_query(query, conn)

#         for col in ['bestillings_dato', 'onske_dato', 'utfort_dato']:
#             df[col] = pd.to_datetime(df[col])

#         return df
#     except Exception as e:
#         logger.error(f"Feil ved henting av utførte strøingsbestillinger: {str(e)}")
#         return pd.DataFrame()


def count_stroing_bestillinger():
    with get_db_connection("stroing") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stroing_bestillinger")
        return cursor.fetchone()[0]


# Delete
# def slett_stroingsbestilling(bestilling_id):
#     try:
#         query = "DELETE FROM stroing_bestillinger WHERE id = ?"
#         with get_db_connection('stroing') as conn:
#             cursor = conn.cursor()
#             cursor.execute(query, (bestilling_id,))
#             conn.commit()
#         logger.info(f"Strøingsbestilling med ID {bestilling_id} ble slettet.")
#         return True
#     except Exception as e:
#         logger.error(f"Feil ved sletting av strøingsbestilling {bestilling_id}: {str(e)}")
#         return False


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
                aktive_bestillinger['rode'] = aktive_bestillinger['bruker'].apply(get_rode)
                
                # Formater visningsdata
                visning_df = aktive_bestillinger.copy()
                visning_df['Dato'] = visning_df['onske_dato'].dt.strftime('%d.%m.%Y')
                visning_df['Ukedag'] = visning_df['onske_dato'].dt.strftime('%A').map({
                    'Monday': 'Mandag', 'Tuesday': 'Tirsdag', 'Wednesday': 'Onsdag',
                    'Thursday': 'Torsdag', 'Friday': 'Fredag', 'Saturday': 'Lørdag', 
                    'Sunday': 'Søndag'
                })
                
                # Velg og sorter kolonner
                visning_df = visning_df[['Dato', 'Ukedag', 'rode', 'bruker']]
                visning_df = visning_df.rename(columns={'bruker': 'Hytte'})
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
                    "bruker": "Bruker",
                    "bestillings_dato": "Bestilt",
                    "onske_dato": "Ønsket dato",
                    "kommentar": "Kommentar",
                    "status": "Status"
                }
            )

    except Exception as e:
        logger.error(f"Feil i admin_stroing_page: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved håndtering av strøingsbestillinger")


# Database initialization and maintenance
def verify_stroing_data():
    with get_db_connection("stroing") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stroing_bestillinger")
        data = cursor.fetchall()
        logger.info(f"Current entries in stroing_bestillinger: {len(data)}")
        for row in data:
            logger.info(f"Row: {row}")


# Visninger
def display_stroing_bookings(user_id, show_header=False, show_stats=False):
    """
    Viser strøingsbestillinger for en bruker
    
    Args:
        user_id: Bruker-ID
        show_header: Om overskrift skal vises
        show_stats: Om statistikk skal vises
    """
    if show_header:
        st.subheader("Dine tidligere strøing-bestillinger")

    previous_bookings = hent_bruker_stroing_bestillinger(user_id)

    if previous_bookings.empty:
        st.info("Du har ingen tidligere strøing-bestillinger.")
        return

    # Vis bestillinger
    for _, booking in previous_bookings.iterrows():
        with st.expander(f"Bestilling - Ønsket dato: {booking['onske_dato'].strftime('%Y-%m-%d')}"):
            st.write(f"Bestilt: {booking['bestillings_dato'].strftime('%Y-%m-%d %H:%M')}")
            st.write(f"Ønsket dato: {booking['onske_dato'].date()}")
            if pd.notnull(booking.get('kommentar')):
                st.write(f"Kommentar: {booking['kommentar']}")
            if pd.notnull(booking.get('status')):
                st.write(f"Status: {booking['status']}")

    # Vis statistikk hvis ønsket
    if show_stats:
        st.subheader("Statistikk")
        total = len(previous_bookings)
        st.info(f"Du har totalt {total} strøingsbestilling{'er' if total != 1 else ''}")

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

        # Valider bruker-IDer
        df = df[df["bruker"].apply(lambda x: validate_user_id(str(x)))]

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

            # Opprett versjonstabell
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Opprett hovedtabell med oppdatert skjema
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS stroing_bestillinger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bruker TEXT,
                    bestillings_dato TEXT,
                    onske_dato TEXT,
                    kommentar TEXT,
                    status TEXT
                )
            """
            )

    except Exception as e:
        logger.error(f"Feil ved initialisering av strøing-databasen: {str(e)}")

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
