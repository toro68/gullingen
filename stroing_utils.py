import sqlite3
import pandas as pd
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import streamlit as st

from db_utils import (
    get_stroing_connection,
    initialize_stroing_database
)
from constants import TZ

from logging_config import get_logger

logger = get_logger(__name__)

# Helper functions
def validate_date(date_string: str) -> bool:
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except ValueError:
        return False

# Create
def lagre_stroing_bestilling(user_id: str, onske_dato: str) -> bool:
    """
    Lagrer en ny strøingsbestilling i databasen.

    Args:
        user_id (str): ID-en til brukeren som bestiller
        onske_dato (str): Ønsket dato for strøing i format 'YYYY-MM-DD'

    Returns:
        bool: True hvis bestillingen ble lagret, False ellers
    """
    try:
        logger.info(f"Forsøker å lagre strøingsbestilling for bruker {user_id} på dato {onske_dato}")
        
        if not validate_date(onske_dato):
            logger.error(f"Ugyldig datoformat for strøingsbestilling: {onske_dato}")
            return False
        
        with get_stroing_connection() as conn:
            c = conn.cursor()
            bestillings_dato = datetime.now(TZ).isoformat()
            
            c.execute('''
            INSERT INTO stroing_bestillinger 
            (bruker, bestillings_dato, onske_dato)
            VALUES (?, ?, ?)
            ''', (user_id, bestillings_dato, onske_dato))
            
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
    Hovedveien (Gullingvegen-kryss Kalvaknutvegen) blir alltid prioritert. 
    - Ønsker du strøing av stikkveien din, kan du bestille dette mot et gebyr.  
    I tillegg til prisen per bestilling betaler du en fast egenandel for sesongen. 
    - Strøing av stikkveier utføres kun etter godkjenning fra brøytekontakten.
    
    Tips ved glatte forhold:
    - Bruk piggdekk/kjetting
    - Ha med litt strøsand, spade og tau i bilen. 
    - Bruk strøsandkassene. Må stroppes etter bruk!
    - Brodder til beina
    """
    )

    # Radioknapper for bestillingstype
    bestilling_type = st.radio(
        "Velg bestillingstype:", ("Stikkvei kommende helg", "Mandag-fredag")
    )

    if bestilling_type == "Stikkvei kommende helg":
        # Beregn neste helg
        today = datetime.now(TZ).date()
        days_until_weekend = (5 - today.weekday()) % 7
        next_saturday = today + timedelta(days=days_until_weekend)
        next_sunday = next_saturday + timedelta(days=1)

        st.write(
            f"Bestilling for helgen {next_saturday.strftime('%d.%m.%Y')} - {next_sunday.strftime('%d.%m.%Y')}"
        )

        # Sjekk om fristen har gått ut
        if today.weekday() >= 3 and datetime.now(TZ).hour >= 12:
            st.warning(
                "Fristen for bestilling denne helgen har gått ut (torsdag kl. 12:00)."
            )
        else:
            st.success("Du kan bestille strøing for kommende helg.")

        onske_dato = next_saturday
    else:  # Mandag-fredag
        available_dates = [
            datetime.now(TZ).date() + timedelta(days=i) for i in range(4)
        ]
        onske_dato = st.selectbox(
            "Velg dato for strøing:",
            available_dates,
            format_func=lambda x: x.strftime("%d.%m.%Y"),
        )

        if onske_dato == datetime.now(TZ).date():
            st.info(
                "Du har valgt strøing for i dag. Merk at dette er med forbehold om godkjenning fra brøytekontakten."
            )

    if st.button("Bestill Strøing"):
        #st.info(f"Forsøker å lagre bestilling for bruker {st.session_state.user_id} på dato {onske_dato.isoformat()}")
        result = lagre_stroing_bestilling(st.session_state.user_id, onske_dato.isoformat())
        if result:
            st.success("Bestilling av strøing er registrert!")
            logger.info(f"Strøing order successfully registered for user {st.session_state.user_id}")
        else:
            st.error("Det oppstod en feil ved registrering av bestillingen. Vennligst prøv igjen senere.")
            logger.error(f"Failed to register strøing order for user {st.session_state.user_id}")

        st.info("Merk: Du vil bli fakturert kun hvis strøing utføres.")


    # Vis tidligere bestillinger én gang, med overskrift
    display_stroing_bookings(st.session_state.user_id, show_header=True)

# Read
def hent_stroing_bestillinger():
    try:
        with get_stroing_connection() as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            ORDER BY onske_dato DESC, bestillings_dato DESC
            """
            df = pd.read_sql_query(query, conn)
        
        # Konverter dato-kolonner til datetime
        for col in ['bestillings_dato', 'onske_dato']:
            df[col] = pd.to_datetime(df[col])
        
        return df
    except Exception as e:
        logger.error(f"Feil ved henting av strøing-bestillinger: {str(e)}")
        return pd.DataFrame()
    
def hent_bruker_stroing_bestillinger(user_id):
    try:
        with get_stroing_connection() as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            WHERE bruker = ? 
            ORDER BY bestillings_dato DESC
            """
            df = pd.read_sql_query(query, conn, params=(user_id,))
        
        # Konverter dato-kolonner til datetime
        for col in ['bestillings_dato', 'onske_dato']:
            df[col] = pd.to_datetime(df[col])
        
        return df
    except Exception as e:
        logger.error(f"Feil ved henting av strøing-bestillinger for bruker {user_id}: {str(e)}")
        return pd.DataFrame()

def hent_stroing_bestilling(bestilling_id: int) -> Optional[Dict[str, Any]]:
    try:
        with get_stroing_connection() as conn:
            query = "SELECT * FROM stroing_bestillinger WHERE id = ?"
            cursor = conn.cursor()
            cursor.execute(query, (bestilling_id,))
            result = cursor.fetchone()
            if result:
                return dict(zip([column[0] for column in cursor.description], result))
            return None
    except Exception as e:
        logger.error(f"Feil ved henting av strøingsbestilling {bestilling_id}: {str(e)}")
        return None

def hent_utforte_stroingsbestillinger() -> pd.DataFrame:
    try:
        with get_stroing_connection() as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            WHERE utfort_dato IS NOT NULL
            ORDER BY utfort_dato DESC
            """
            df = pd.read_sql_query(query, conn)
        
        for col in ['bestillings_dato', 'onske_dato', 'utfort_dato']:
            df[col] = pd.to_datetime(df[col])
        
        return df
    except Exception as e:
        logger.error(f"Feil ved henting av utførte strøingsbestillinger: {str(e)}")
        return pd.DataFrame()
        
def count_stroing_bestillinger():
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stroing_bestillinger")
        return cursor.fetchone()[0]

def update_stroing_info(bestilling_id: int, utfort_av: str) -> Tuple[bool, str]:
    """
    Oppdaterer informasjon om en strøingsbestilling når den er utført.

    Args:
        bestilling_id (int): ID-en til bestillingen som skal oppdateres
        utfort_av (str): Navnet eller ID-en til personen som utførte strøingen

    Returns:
        Tuple[bool, str]: En tuple hvor første element er True hvis oppdateringen var vellykket,
                          False ellers. Andre element er en statusmelding.
    """
    try:
        with get_stroing_connection() as conn:
            cursor = conn.cursor()
            
            # Sjekk om bestillingen eksisterer
            cursor.execute("SELECT id FROM stroing_bestillinger WHERE id = ?", (bestilling_id,))
            if not cursor.fetchone():
                logger.warning(f"Strøingsbestilling med ID {bestilling_id} ble ikke funnet")
                return False, "Bestilling ikke funnet"
            
            current_time = datetime.now(TZ).isoformat()
            
            # Oppdater bestillingen
            cursor.execute("""
                UPDATE stroing_bestillinger 
                SET utfort_dato = ?,
                    utfort_av = ?
                WHERE id = ?
            """, (current_time, utfort_av, bestilling_id))
            
            # Logg endringen
            cursor.execute("""
                INSERT INTO stroing_status_log (bestilling_id, old_status, new_status, changed_by, changed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (bestilling_id, "Ikke utført", "Utført", utfort_av, current_time))
            
            conn.commit()
            
            logger.info(f"Strøingsbestilling {bestilling_id} oppdatert som utført av {utfort_av}")
            return True, "Bestilling oppdatert som utført"
    except sqlite3.Error as e:
        logger.error(f"SQLite-feil ved oppdatering av strøingsbestilling {bestilling_id}: {str(e)}")
        return False, f"Databasefeil: {str(e)}"
    except Exception as e:
        logger.error(f"Uventet feil ved oppdatering av strøingsbestilling {bestilling_id}: {str(e)}")
        return False, f"Uventet feil: {str(e)}"

# Delete
def slett_stroingsbestilling(bestilling_id):
    try:
        query = "DELETE FROM stroing_bestillinger WHERE id = ?"
        with get_stroing_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (bestilling_id,))
            conn.commit()
        logger.info(f"Strøingsbestilling med ID {bestilling_id} ble slettet.")
        return True
    except Exception as e:
        logger.error(f"Feil ved sletting av strøingsbestilling {bestilling_id}: {str(e)}")
        return False

def admin_stroing_page():
    st.title("Administrer Strøing")

    # Sett opp datovelgere
    today = datetime.now(TZ).date()
    default_end_date = today + timedelta(days=7)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=today)
    with col2:
        end_date = st.date_input("Til dato", value=default_end_date, min_value=start_date)

    # Vis valgt periode
    st.write(f"Viser bestillinger fra {start_date} til {end_date}")

    try:
        # Hent alle strøingsbestillinger
        all_bestillinger = hent_stroing_bestillinger()

        # Logg originale datatyper
        logger.info(f"Original datatypes: {all_bestillinger.dtypes}")

        # Konverter kolonner til Arrow-kompatible datatyper
        all_bestillinger['id'] = all_bestillinger['id'].astype('int32')
        all_bestillinger['bruker'] = all_bestillinger['bruker'].astype('string')
        all_bestillinger['bestillings_dato'] = all_bestillinger['bestillings_dato'].dt.tz_localize(None)

        all_bestillinger['onske_dato'] = pd.to_datetime(all_bestillinger['onske_dato'], errors='coerce')

        # Logg konverterte datatyper
        logger.info(f"Converted datatypes: {all_bestillinger.dtypes}")

        # Sjekk gyldighet av datoer i onske_dato-kolonnen
        invalid_dates = all_bestillinger[all_bestillinger['onske_dato'].isna()]
        if not invalid_dates.empty:
            logger.warning(f"Found {len(invalid_dates)} invalid dates in onske_dato column")
            st.warning(f"Fant {len(invalid_dates)} ugyldige datoer i ønsket dato-kolonnen. Disse vil bli ekskludert fra visningen.")
            
            # Vis problematiske datoer
            st.subheader("Bestillinger med ugyldige datoer:")
            st.dataframe(invalid_dates[['id', 'bruker', 'bestillings_dato', 'onske_dato']])
        
        # Fjern rader med ugyldige datoer
        valid_bestillinger = all_bestillinger.dropna(subset=['onske_dato'])
        logger.info(f"Removed {len(all_bestillinger) - len(valid_bestillinger)} rows with invalid dates")

        # Filtrer bestillinger for den valgte perioden
        bestillinger = valid_bestillinger[
            (valid_bestillinger['onske_dato'].dt.date >= start_date) &
            (valid_bestillinger['onske_dato'].dt.date <= end_date)
        ]

        if bestillinger.empty:
            st.warning(f"Ingen gyldige strøingsbestillinger funnet for perioden {start_date} til {end_date}.")
        else:
            # Beregn 'dager_til'
            bestillinger['dager_til'] = (bestillinger['onske_dato'] - pd.to_datetime(today)).dt.days.astype('int32')


            # Vis daglig oppsummering
            st.subheader("Daglig oppsummering")
            daily_summary = bestillinger.groupby(bestillinger["onske_dato"].dt.date).size().reset_index(name="antall")
            for _, row in daily_summary.iterrows():
                st.write(f"{row['onske_dato']}: {row['antall']} bestilling(er)")

            # Vis detaljert oversikt over bestillinger
            st.subheader("Detaljert oversikt over strøingsbestillinger")
            for _, row in bestillinger.iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                with col1:
                    st.write(f"Hytte: {row['bruker']}")
                with col2:
                    st.write(f"Bestilt: {row['bestillings_dato'].date()}")
                with col3:
                    st.write(f"Ønsket dato: {row['onske_dato'].date()}")
                with col4:
                    if st.button("Slett", key=f"slett_{row['id']}"):
                        if slett_stroingsbestilling(row["id"]):
                            st.success(f"Bestilling for hytte {row['bruker']} er slettet.")
                            st.rerun()
                        else:
                            st.error(f"Kunne ikke slette bestilling for hytte {row['bruker']}.")

            # Legg til mulighet for å laste ned bestillinger som CSV
            csv = bestillinger[['id', 'bruker', 'bestillings_dato', 'onske_dato', 'dager_til']].to_csv(index=False)
            st.download_button(
                label="Last ned som CSV",
                data=csv,
                file_name=f"stroingsbestillinger_{start_date}_{end_date}.csv",
                mime="text/csv",
            )

    except Exception as e:
        st.error(f"En feil oppstod: {str(e)}")
        st.write("Feilsøkingsinformasjon:")
        st.write(f"Start dato: {start_date}")
        st.write(f"Slutt dato: {end_date}")
        st.write(f"Feiltype: {type(e).__name__}")
        st.write(f"Feilmelding: {str(e)}")
        st.write("\nStack trace:")
        st.code(traceback.format_exc())

        # Vis datatyper for debugging
        if 'bestillinger' in locals():
            st.subheader("Datatyper for debugging:")
            st.write(bestillinger.dtypes)

        logger.error(f"Error in admin_stroing_page: {str(e)}", exc_info=True)
 
# Database initialization and maintenance
def verify_stroing_data():
    with get_stroing_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stroing_bestillinger")
        data = cursor.fetchall()
        logger.info(f"Current entries in stroing_bestillinger: {len(data)}")
        for row in data:
            logger.info(f"Row: {row}")

def initialize_stroing():
    """Initialiserer strøingsdatabasen og verifiserer data."""
    try:
        initialize_stroing_database()
        verify_stroing_data()
        logger.info("Strøingsdatabase initialisert og verifisert")
    except Exception as e:
        logger.error(f"Feil ved initialisering av strøingsdatabase: {str(e)}")

if __name__ == "__main__":
    initialize_stroing()
    
# Visninger
def display_stroing_bookings(user_id, show_header=False):
    if show_header:
        st.subheader("Dine tidligere strøing-bestillinger")

    previous_bookings = hent_bruker_stroing_bestillinger(user_id)

    if previous_bookings.empty:
        st.info("Du har ingen tidligere strøing-bestillinger.")
    else:
        for _, booking in previous_bookings.iterrows():
            with st.expander(
                f"Bestilling - Ønsket dato: {booking['onske_dato'].strftime('%Y-%m-%d')}"
            ):
                st.write(
                    f"Bestilt: {booking['bestillings_dato'].strftime('%Y-%m-%d %H:%M')}"
                )
                st.write(f"Ønsket dato: {booking['onske_dato'].strftime('%Y-%m-%d')}")
                if "status" in booking:
                    st.write(f"Status: {booking['status']}")

def vis_tidligere_stroingsbestillinger(bruker_id):
    bestillinger = hent_bruker_stroing_bestillinger(bruker_id)
    
    if bestillinger.empty:
        st.info("Du har ingen tidligere strøing-bestillinger.")
    else:
        st.subheader("Dine tidligere strøing-bestillinger")
        
        for _, bestilling in bestillinger.iterrows():
            with st.expander(f"Bestilling - Ønsket dato: {bestilling['onske_dato'].date()}"):
                st.write(f"Bestilt: {bestilling['bestillings_dato'].strftime('%Y-%m-%d %H:%M')}")
                st.write(f"Ønsket dato: {bestilling['onske_dato'].date()}")

