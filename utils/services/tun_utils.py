import os
import sqlite3
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.core.config import (
    TZ,
    DATE_FORMATS,
    get_date_format,
    get_current_time,
    get_default_date_range,
    DATE_VALIDATION,
    DATABASE_PATH,
    safe_to_datetime,
    format_date,
    combine_date_with_tz,
    normalize_datetime,
    convert_for_db,
    DB_DATE_TYPES
)
from utils.core.logging_config import get_logger
from utils.core.util_functions import neste_fredag
from utils.core.validation_utils import validere_bestilling
from utils.db.db_utils import fetch_data, get_db_connection
from utils.services.map_utils import vis_dagens_tunkart, verify_map_configuration, debug_map_data
from utils.services.customer_utils import (
    customer_edit_component,
    get_customer_by_id,
    get_rode,
    load_customer_database,
    vis_arsabonnenter,
)
from utils.services.utils import is_active_booking

logger = get_logger(__name__)


# CREATE - hovedfunksjon i app.py
def bestill_tunbroyting():
    try:
        st.title("Bestill Tunbrøyting")
        # Informasjonstekst
        st.info(
            """
        Tunbrøyting i Fjellbergsskardet - Vintersesongen 2024/2025

        Årsabonnement:
        - Tunet ditt brøytes automatisk fredager, når brøytefirma vurderer at det trengs.  
        - Hvis du ønsker brøyting på andre dager, må du legge inn bestilling. 
        - Traktor kjører aldri opp for å rydde bare 1 hyttetun, det ryddes samtidig med veinettet.
        Bestill derfor i god tid, og legg inn f.eks perioden lørdag-torsdag 
        for å være sikker på brøytet tun på en torsdag. 
        - Hvis du ønsker brøyting hver gang veinettet brøytes, legg inn bestilling fra 1. november til 1. mai.
        
        Ukentlig ved bestilling: 
        - Brøyting kun fredager. Bestilling kreves. 
        - Det faktureres minimum 5 brøytinger (minstepris).
        
        Gjelder alle:
        - Brøytefirma kan utføre vedlikeholdsbrøyting for å unngå gjengroing hvis de ser behov for det.
        """
        )
    
        # Sjekk både customer_id og authenticated i sesjonen
        if not st.session_state.get("authenticated"):
            logger.error("Bruker er ikke autentisert")
            st.error("Du må være logget inn for å bestille tunbrøyting")
            return
            
        # Hent customer_id fra authenticated_user hvis den finnes
        customer_id = st.session_state.get("authenticated_user", {}).get("customer_id")
        if not customer_id:
            logger.error("Ingen customer_id funnet i authenticated_user")
            st.error("Du må være logget inn for å bestille tunbrøyting")
            return
            
        customer = get_customer_by_id(customer_id)
        
        if customer is None:
            logger.error(f"Kunne ikke hente kundedata for ID: {customer_id}")
            st.error("Kunne ikke hente brukerinformasjon. Vennligst logg inn på nytt.")
            st.button("Logg inn på nytt", on_click=lambda: st.session_state.clear())
            return

        logger.info(f"Using customer_id: {customer_id}")
        user_subscription = customer.get("subscription") or customer.get("icon")

        if user_subscription not in ["star_white", "star_red"]:
            st.warning(
                "Du har ikke et aktivt tunbrøytingsabonnement og kan derfor ikke bestille tunbrøyting."
            )
            return

        naa = get_current_time()
        tomorrow = naa.date() + timedelta(days=1)

        abonnement_type = (
            "Årsabonnement"
            if user_subscription == "star_white"
            else "Ukentlig ved bestilling"
        )
        st.write(f"Ditt abonnement: {abonnement_type}")

        col1, col2 = st.columns(2)

        with col1:
            if abonnement_type == "Ukentlig ved bestilling":
                ankomst_dato = neste_fredag()
                st.write(
                    f"Ankomstdato (neste fredag): {ankomst_dato.strftime('%d.%m.%Y')}"
                )
            else:  # Årsabonnement
                ankomst_dato = st.date_input(
                    "Velg ankomstdato",
                    min_value=tomorrow,
                    value=tomorrow,
                    format="DD.MM.YYYY",
                )

        avreise_dato = None
        if abonnement_type == "Årsabonnement":
            with col2:
                avreise_dato = st.date_input(
                    "Velg avreisedato",
                    min_value=ankomst_dato,
                    value=ankomst_dato + timedelta(days=1),
                    format="DD.MM.YYYY",
                )

        bestillingsfrist = combine_date_with_tz(
            ankomst_dato - timedelta(days=1), 
            time(12, 0)
        )

        if st.button("Bestill Tunbrøyting"):
            if naa >= bestillingsfrist:
                st.error(
                    f"Beklager, fristen for å bestille tunbrøyting for {ankomst_dato.strftime('%d.%m.%Y')} var {bestillingsfrist.strftime('%d.%m.%Y kl. %H:%M')}. "
                )
            else:
                resultat = lagre_bestilling(
                    customer_id,
                    ankomst_dato.isoformat(),
                    None,  # ankomst_tid settes til None
                    avreise_dato.isoformat() if avreise_dato else None,
                    None,  # avreise_tid settes til None
                    abonnement_type,
                )
                if resultat:
                    st.success("Bestilling av tunbrøyting er registrert!")
                else:
                    st.error(
                        f"Du har allerede en bestilling for {ankomst_dato.strftime('%d.%m.%Y')}. "
                        "Du kan ikke bestille tunbrøyting flere ganger på samme dato."
                    )

        st.info(
            f"Merk: Frist for bestilling er kl. 12:00 dagen før ønsket ankomstdato. For valgt dato ({ankomst_dato.strftime('%d.%m.%Y')}) er fristen {bestillingsfrist.strftime('%d.%m.%Y kl. %H:%M')}."
        )

        # Logging for bestillinger
        logger.info("Attempting to fetch user bookings")
        bruker_bestillinger = hent_bruker_bestillinger(customer_id)
        logger.info(
            f"Retrieved bookings data shape: {bruker_bestillinger.shape if not bruker_bestillinger.empty else 'Empty DataFrame'}"
        )
        logger.info(
            f"Bookings columns: {bruker_bestillinger.columns.tolist() if not bruker_bestillinger.empty else 'No columns'}"
        )

        st.subheader("Dine tidligere bestillinger")
        if not bruker_bestillinger.empty:
            logger.info("Processing non-empty bookings")
            for idx, bestilling in bruker_bestillinger.iterrows():
                logger.info(f"Processing booking {idx}: {bestilling.to_dict()}")
                try:
                    with st.expander(
                        f"Bestilling - {pd.to_datetime(bestilling['ankomst_dato']).strftime('%d.%m.%Y')}"
                    ):
                        st.write(
                            f"Ankomst: {pd.to_datetime(bestilling['ankomst_dato']).strftime('%d.%m.%Y')}"
                        )
                        if pd.notna(bestilling["avreise_dato"]):
                            st.write(
                                f"Avreise: {pd.to_datetime(bestilling['avreise_dato']).strftime('%d.%m.%Y')}"
                            )
                        st.write(f"Type: {bestilling['abonnement_type']}")
                except Exception as e:
                    logger.error(
                        f"Error processing booking {idx}: {str(e)}", exc_info=True
                    )
        else:
            logger.info("No bookings found for user")
            st.info("Du har ingen tidligere bestillinger.")

        st.write("---")
        logger.info("Completed bestill_tunbroyting() successfully")

    except Exception as e:
        logger.error(f"Error in bestill_tunbroyting: {str(e)}", exc_info=True)
        st.error(
            "Det oppstod en feil ved lasting av bestillinger. Vennligst prøv igjen senere."
        )


# CREATE - lagre i bestill_tunbroyting
def lagre_bestilling(
    customer_id: str,
    ankomst_dato: str,
    ankomst_tid: str,
    avreise_dato: str,
    avreise_tid: str,
    abonnement_type: str,
) -> bool:
    try:
        # Sjekk om bruker allerede har bestilling på denne datoen
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM tunbroyting_bestillinger 
                WHERE customer_id = ? AND ankomst_dato = ?
            """,
                (customer_id, ankomst_dato),
            )

            if cursor.fetchone()[0] > 0:
                logger.warning(
                    f"Bruker {customer_id} har allerede bestilling på {ankomst_dato}"
                )
                return False

            # Valider input - fjernet ankomst_tid fra valideringen
            if not all([customer_id, ankomst_dato, abonnement_type]):
                logger.error("Manglende påkrevde felter i bestilling")
                return False

            # SQL-spørring med eksplisitte kolonnenavn
            query = """
            INSERT INTO tunbroyting_bestillinger 
            (customer_id, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """

            cursor.execute(
                query,
                (
                    str(customer_id),
                    str(ankomst_dato),
                    None,  # ankomst_tid
                    str(avreise_dato) if avreise_dato else None,
                    None,  # avreise_tid
                    str(abonnement_type),
                ),
            )

            conn.commit()
            return True

    except Exception as e:
        logger.error(f"Uventet feil ved lagring av bestilling: {str(e)}", exc_info=True)
        return False


# READ
def hent_bruker_bestillinger(customer_id):
    """Henter brukerens bestillinger"""
    try:
        with get_db_connection("tunbroyting") as conn:
            query = """
            SELECT DISTINCT * FROM tunbroyting_bestillinger 
            WHERE customer_id = ? 
            ORDER BY ankomst_dato DESC, ankomst_tid DESC
            """
            df = pd.read_sql_query(query, conn, params=(customer_id,))

        logger.info(f"Hentet {len(df)} unike bestillinger for bruker {customer_id}")
        return df

    except Exception as e:
        logger.error(f"Feil ved henting av bestillinger: {str(e)}")
        return pd.DataFrame()


def hent_bestillinger_for_periode(start_date, end_date):
    """
    Henter bestillinger for en gitt periode.
    
    Args:
        start_date: Startdato (datetime eller str)
        end_date: Sluttdato (datetime eller str)
        
    Returns:
        pd.DataFrame: DataFrame med bestillinger for perioden
    """
    try:
        # Konverter og normaliser datoer
        start_dt = normalize_datetime(safe_to_datetime(start_date))
        end_dt = normalize_datetime(safe_to_datetime(end_date))
        
        if not all([start_dt, end_dt]):
            logger.error("Ugyldig start- eller sluttdato")
            return pd.DataFrame()
            
        logger.info(
            f"Henter bestillinger fra {format_date(start_dt)} til {format_date(end_dt)}"
        )

        # Konverter datoer til databaseformat
        start_db = convert_for_db(start_dt, "DATE", "tunbroyting_bestillinger")
        end_db = convert_for_db(end_dt, "DATE", "tunbroyting_bestillinger")

        with get_db_connection("tunbroyting") as conn:
            query = """
            SELECT id, customer_id, ankomst_dato, ankomst_tid, 
                   avreise_dato, avreise_tid, abonnement_type
            FROM tunbroyting_bestillinger 
            WHERE 
                -- Bestillinger som er aktive i den valgte perioden
                (
                    -- Vanlige bestillinger
                    (abonnement_type != 'Årsabonnement' AND
                     ankomst_dato >= ? AND ankomst_dato <= ?)
                    OR
                    -- Årsabonnement som er aktive i perioden
                    (abonnement_type = 'Årsabonnement' AND
                     ankomst_dato <= ? AND 
                     (avreise_dato IS NULL OR avreise_dato >= ?))
                )
            ORDER BY ankomst_dato
            """

            params = [
                start_db, end_db,    # For vanlige bestillinger
                end_db, start_db     # For årsabonnement
            ]

            logger.info(f"Executing query with params: {params}")
            df = pd.read_sql_query(query, conn, params=params)
            
            if df.empty:
                logger.info("Ingen bestillinger funnet for perioden")
                return df
            
            # Konverter datokolonner til datetime med tidssone
            for col in ['ankomst_dato', 'avreise_dato']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col]).dt.tz_localize(TZ)
                    # Formater datoer for visning
                    df[f"{col}_formatted"] = df[col].apply(
                        lambda x: format_date(x, "display", "date")
                    )
            
            # Fjern tidkolonner siden de ikke brukes
            df = df.drop(['ankomst_tid', 'avreise_tid'], axis=1, errors='ignore')
            
            # Lag en visningsversjon av dataframe for logging
            display_df = df.copy()
            # Bruk formaterte datokolonner for visning
            for col in ['ankomst_dato', 'avreise_dato']:
                if f"{col}_formatted" in display_df.columns:
                    display_df[col] = display_df[f"{col}_formatted"]
                    display_df = display_df.drop(f"{col}_formatted", axis=1)
            
            # Logg resultater
            logger.info(f"Hentet {len(df)} bestillinger")
            logger.info("Bestillinger for perioden:")
            logger.info("\n" + display_df.to_string(
                index=False,
                max_colwidth=20,
                justify='left'
            ))
            
            # Fjern de formaterte kolonner før retur
            return df.drop([col for col in df.columns if col.endswith('_formatted')], 
                         axis=1)

    except Exception as e:
        logger.error(f"Error i hent_bestillinger_for_periode: {str(e)}", exc_info=True)
        return pd.DataFrame()


def hent_statistikk_data(bestillinger: pd.DataFrame) -> Dict[str, Any]:
    """
    Henter grunnleggende statistikkdata for tunbrøytingsbestillinger.

    Args:
        bestillinger (pd.DataFrame): DataFrame med alle bestillinger

    Returns:
        Dict[str, Any]: En dictionary med grunnleggende statistikkdata
    """
    if bestillinger.empty:
        return {}

    bestillinger["ankomst_dato"] = pd.to_datetime(
        bestillinger["ankomst_dato"], errors="coerce"
    ).dt.date

    return {
        "bestillinger": bestillinger,
        "total_bestillinger": len(bestillinger),
        "unike_brukere": bestillinger["customer_id"].nunique(),
        "abonnement_counts": bestillinger["abonnement_type"].value_counts().to_dict(),
        "rode_counts": (
            bestillinger["rode"].value_counts().to_dict()
            if "rode" in bestillinger.columns
            else {}
        ),
    }


def hent_aktive_bestillinger():
    today = datetime.now(TZ).date()
    with get_db_connection("tunbroyting") as conn:
        query = """
        SELECT id, customer_id, ankomst_dato, avreise_dato, abonnement_type
        FROM tunbroyting_bestillinger 
        WHERE date(ankomst_dato) >= ? OR (date(ankomst_dato) <= ? AND date(avreise_dato) >= ?)
        OR (abonnement_type = 'Årsabonnement')
        """
        df = pd.read_sql_query(query, conn, params=(today, today, today))

    df["ankomst_dato"] = pd.to_datetime(df["ankomst_dato"])
    df["avreise_dato"] = pd.to_datetime(df["avreise_dato"])

    return df


def hent_bestilling(bestilling_id):
    try:
        with get_db_connection("tunbroyting") as conn:
            query = "SELECT * FROM tunbroyting_bestillinger WHERE id = ?"
            df = pd.read_sql_query(query, conn, params=(bestilling_id,))

        if df.empty:
            logger.warning("Ingen bestilling funnet med ID %s", bestilling_id)
            return None

        bestilling = df.iloc[0].copy()

        # Konverter dato-kolonner med safe_to_datetime
        for col in ["ankomst_dato", "avreise_dato"]:
            bestilling[col] = safe_to_datetime(bestilling[col])

        # Fjern tid-konvertering siden disse er satt til None
        bestilling["ankomst_tid"] = None
        bestilling["avreise_tid"] = None

        logger.info("Hentet bestilling med ID %s", bestilling_id)
        return bestilling

    except Exception as e:
        logger.error(
            "Feil ved henting av bestilling %s: %s",
            bestilling_id,
            str(e),
            exc_info=True
        )
        return None


def get_max_bestilling_id():
    try:
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(id) FROM tunbroyting_bestillinger")
            max_id = cursor.fetchone()[0]
            return max_id if max_id is not None else 0
    except Exception as e:
        logger.error("Feil ved henting av maksimum bestillings-ID: %s", str(e))
        return 0


# update
def oppdater_bestilling(bestilling_id: int, nye_data: Dict[str, Any]) -> bool:
    try:
        query = """UPDATE tunbroyting_bestillinger
                   SET customer_id = ?, ankomst_dato = ?, avreise_dato = ?, abonnement_type = ?
                   WHERE id = ?"""
        params = (
            nye_data["customer_id"],
            nye_data["ankomst_dato"].isoformat() if nye_data["ankomst_dato"] else None,
            nye_data["avreise_dato"].isoformat() if nye_data["avreise_dato"] else None,
            nye_data["abonnement_type"],
            bestilling_id,
        )
        
        with get_db_connection("tunbroyting") as conn:
            c = conn.cursor()
            c.execute(query, params)
            conn.commit()
            
        logger.info("Bestilling %s oppdatert", bestilling_id)
        return True
        
    except Exception as e:
        logger.error(
            "Feil ved oppdatering av bestilling %s: %s", bestilling_id, str(e),
            exc_info=True
        )
        return False


# delete
def slett_bestilling(bestilling_id: int) -> bool:
    try:
        with get_db_connection("tunbroyting") as conn:
            c = conn.cursor()
            c.execute(
                "DELETE FROM tunbroyting_bestillinger WHERE id = ?", (bestilling_id,)
            )
            conn.commit()
        logger.info("Slettet bestilling med id: %s", bestilling_id)
        return True
    except sqlite3.Error as e:
        logger.error(
            "Database error ved sletting av bestilling med id %s: %s",
            bestilling_id,
            str(e),
        )
        return False
    except Exception as e:
        logger.error(
            "Uventet feil ved sletting av bestilling med id %s: %s",
            bestilling_id,
            str(e),
        )
        return False


# hjelpefunksjoner


# teller bestillinger i handle_tun
def count_bestillinger():
    try:
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tunbroyting_bestillinger")
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Feil ved telling av bestillinger: {str(e)}")
        return 0


# viser bestillinger i handle_tun
def vis_rediger_bestilling():
    """Viser og håndterer redigering av bestillinger"""
    try:
        st.header("Rediger bestilling")
        bestilling_id = st.number_input(
            "Skriv inn ID på bestillingen du vil redigere", 
            min_value=1
        )
        
        eksisterende_data = hent_bestilling(bestilling_id)
        if eksisterende_data is not None:
            with st.form("rediger_bestilling"):
                nye_data = {
                    # Behold eksisterende customer_id
                    "customer_id": eksisterende_data["customer_id"]
                }
                
                # Konverter datoer til datetime med tidssone
                ankomst = safe_to_datetime(eksisterende_data["ankomst_dato"])
                avreise = safe_to_datetime(eksisterende_data["avreise_dato"])
                
                nye_data["ankomst_dato"] = st.date_input(
                    "Ankomstdato",
                    value=ankomst.date() if ankomst else None,
                    min_value=datetime.now(TZ).date()
                )
                
                nye_data["avreise_dato"] = st.date_input(
                    "Avreisedato",
                    value=avreise.date() if avreise else None,
                    min_value=nye_data["ankomst_dato"]
                )
                
                nye_data["abonnement_type"] = st.selectbox(
                    "Abonnementstype",
                    options=["Ukentlig ved bestilling", "Årsabonnement"],
                    index=["Ukentlig ved bestilling", "Årsabonnement"].index(
                        eksisterende_data["abonnement_type"]
                    )
                )
                
                submitted = st.form_submit_button("Oppdater bestilling")
                
                if submitted:
                    # Konverter datoer til datetime med tidssone
                    nye_data["ankomst_dato"] = combine_date_with_tz(
                        nye_data["ankomst_dato"]
                    )
                    nye_data["avreise_dato"] = combine_date_with_tz(
                        nye_data["avreise_dato"]
                    ) if nye_data["avreise_dato"] else None
                    
                    # Valider datoene før oppdatering
                    if validere_bestilling(nye_data):
                        if oppdater_bestilling(bestilling_id, nye_data):
                            st.success(f"Bestilling {bestilling_id} er oppdatert!")
                        else:
                            st.error("Det oppstod en feil under oppdatering av bestillingen.")
                    else:
                        st.error("Ugyldig bestilling. Sjekk at avreisedato er etter ankomstdato.")
                        
    except Exception as e:
        logger.error(f"Feil i vis_rediger_bestilling: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved redigering av bestilling")

# oppdaterer bestilling i Admin-panelet
def handle_tun():
    st.title("Håndter tunbestillinger")
    st.info("Her kan Fjellbergsskardet Drift redigere og slette bestillinger.")

    # Vis statistikk
    total_bestillinger = count_bestillinger()
    st.write(f"Totalt antall bestillinger: {total_bestillinger}")

    # Legg til en ekspanderende seksjon for statistikk og visualiseringer
    with st.expander("Vis statistikk og visualiseringer", expanded=False):
        vis_tunbroyting_statistikk()

    # Rediger bestilling
    vis_rediger_bestilling()

    # Slett bestilling
    st.header("Slett bestilling")

    slett_id = st.number_input(
        "Skriv inn ID på bestillingen du vil slette", min_value=1, key="slett_id"
    )
    if st.button("Slett bestilling", key="slett_id_button"):
        if slett_bestilling(slett_id):
            st.success(f"Bestilling {slett_id} er slettet.")
        else:
            st.error(
                "Kunne ikke slette bestillingen. Vennligst sjekk ID og prøv igjen."
            )
    # Kunderedigeringskomponent
    customer_edit_component()

def hent_aktive_bestillinger_for_dag(dato):
    """Henter aktive bestillinger for en gitt dato."""
    try:
        dato_dt = safe_to_datetime(dato)
        if dato_dt is None:
            logger.error(f"Ugyldig datoformat: {dato}")
            return pd.DataFrame()
            
        dato_normalized = normalize_datetime(dato_dt)
        
        alle_bestillinger = get_bookings()
        if alle_bestillinger.empty:
            return pd.DataFrame()
            
        aktive_bestillinger = alle_bestillinger[
            (alle_bestillinger['abonnement_type'] == 'Årsabonnement') |
            (alle_bestillinger['ankomst_dato'].apply(normalize_datetime) == dato_normalized) |
            (
                (alle_bestillinger['ankomst_dato'].apply(normalize_datetime) <= dato_normalized) &
                (alle_bestillinger['avreise_dato'].isna() | 
                 (alle_bestillinger['avreise_dato'].apply(normalize_datetime) >= dato_normalized))
            )
        ]
        
        return aktive_bestillinger
        
    except Exception as e:
        logger.error(f"Feil i hent_aktive_bestillinger_for_dag: {str(e)}")
        return pd.DataFrame()
# filtrerer bestillinger i bestill_tunbroyting
def filter_tunbroyting_bestillinger(bestillinger: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    filtered = bestillinger.copy()
    
    # Standardiser kolonnenavn
    if 'ankomst' in filtered.columns:
        filtered = filtered.rename(columns={
            'ankomst': 'ankomst_dato',
            'avreise': 'avreise_dato'
        })
    
    current_date = datetime.now(TZ).date()
    
    if filters.get("vis_type") == "today":
        filtered = filtered[
            (filtered["abonnement_type"] == "Årsabonnement") |
            (
                (filtered["abonnement_type"] == "Ukentlig ved bestilling") &
                (
                    (filtered["ankomst_dato"].dt.date <= current_date) &
                    (
                        (filtered["avreise_dato"].isnull()) |
                        (filtered["avreise_dato"].dt.date >= current_date)
                    )
                )
            )
        ]
    elif filters.get("vis_type") == "active":
        end_date = current_date + timedelta(days=7)
        filtered = filtered[
            (filtered["abonnement_type"] == "Årsabonnement")
            | (
                (filtered["abonnement_type"] == "Ukentlig ved bestilling")
                & (
                    (filtered["ankomst_dato"].dt.date <= end_date)
                    & (
                        (filtered["avreise_dato"].isnull())
                        | (filtered["avreise_dato"].dt.date >= current_date)
                    )
                )
            )
        ]
    else:
        if filters.get("start_date"):
            filtered = filtered[
                (filtered["ankomst_dato"].dt.date >= filters["start_date"])
                | (
                    (filtered["ankomst_dato"].dt.date < filters["start_date"])
                    & (
                        (filtered["avreise_dato"].isnull())
                        | (filtered["avreise_dato"].dt.date >= filters["start_date"])
                    )
                )
            ]
        if filters.get("end_date"):
            filtered = filtered[filtered["ankomst_dato"].dt.date <= filters["end_date"]]

    if filters.get("abonnement_type"):
        filtered = filtered[
            filtered["abonnement_type"].isin(filters["abonnement_type"])
        ]

    return filtered

def filter_todays_bookings(bookings_df):
    """Filtrerer bookinger for  finne dagens aktive bestillinger."""
    try:
        logger.info("Starter filtrering av dagens bestillinger")
        
        if bookings_df.empty:
            return pd.DataFrame()
            
        result = bookings_df.copy()
        dagens_dato = normalize_datetime(get_current_time())
        
        # Filtrer basert på dato og abonnement_type
        mask = (
            (result['abonnement_type'] == 'Årsabonnement') |
            (
                (result['ankomst_dato'].apply(normalize_datetime) <= dagens_dato) & 
                (
                    result['avreise_dato'].isnull() |
                    (result['avreise_dato'].apply(normalize_datetime) >= dagens_dato)
                )
            )
        )
        
        filtered_df = result[mask].copy()
        
        # Formater datoer for visning
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in filtered_df.columns:
                filtered_df[col] = filtered_df[col].dt.strftime(DATE_FORMATS["display"]["date"])
        
        return filtered_df
        
    except Exception as e:
        logger.error(f"Feil i filter_todays_bookings: {str(e)}")
        return pd.DataFrame()


def tunbroyting_kommende_uke(bestillinger):
    current_date = get_current_time()
    end_date = current_date + timedelta(days=7)
    
    # Sikre at datoene er i riktig timezone
    current_date = current_date.astimezone(TZ)
    end_date = end_date.astimezone(TZ)

    return bestillinger[
        (
            (bestillinger["ankomst_dato"].dt.tz_convert(TZ) >= current_date) 
            & (bestillinger["ankomst_dato"].dt.tz_convert(TZ) <= end_date)
        )
        |
        (
            (bestillinger["ankomst_dato"].dt.tz_convert(TZ) < current_date)
            & (
                (bestillinger["avreise_dato"].isnull())
                | (bestillinger["avreise_dato"].dt.tz_convert(TZ) >= current_date)
            )
        )
        |
        (bestillinger["abonnement_type"] == "Årsabonnement")
    ]


# Visninger for tunbrøyting
def vis_tunbroyting_statistikk(bookings_func=None):
    """
    Viser statistikk for tunbrøytingsbestillinger.
    
    Args:
        bookings_func (callable, optional): Funksjon for å hente bestillinger
    """
    try:
        # Hent bestillinger
        bestillinger = bookings_func() if bookings_func else get_bookings()
        
        if bestillinger.empty:
            st.info("Ingen bestillinger å vise statistikk for.")
            return
            
        # Konverter datokolonner til datetime med tidssone
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in bestillinger.columns:
                bestillinger[col] = bestillinger[col].apply(safe_to_datetime)
                
        # Normaliser datoer for sammenligning
        current_date = normalize_datetime(get_current_time())
        
        # Filtrer aktive bestillinger
        aktive_bestillinger = bestillinger[
            (bestillinger['abonnement_type'] == 'Årsabonnement') |
            (
                (bestillinger['ankomst_dato'].apply(normalize_datetime) <= current_date) &
                (
                    bestillinger['avreise_dato'].isna() |
                    (bestillinger['avreise_dato'].apply(normalize_datetime) >= current_date)
                )
            )
        ]
        
        # Vis statistikk
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric(
                "Totalt antall bestillinger", 
                len(bestillinger)
            )
            st.metric(
                "Aktive bestillinger", 
                len(aktive_bestillinger)
            )
            
        with col2:
            st.metric(
                "Årsabonnementer", 
                len(bestillinger[bestillinger['abonnement_type'] == 'Årsabonnement'])
            )
            st.metric(
                "Ukentlige bestillinger",
                len(bestillinger[bestillinger['abonnement_type'] == 'Ukentlig ved bestilling'])
            )
            
        # Vis tidslinje over bestillinger
        if not bestillinger.empty:
            start_date = bestillinger['ankomst_dato'].min()
            end_date = bestillinger['avreise_dato'].max()
            
            if pd.notna(start_date) and pd.notna(end_date):
                dato_range = pd.date_range(
                    start=normalize_datetime(start_date),
                    end=normalize_datetime(end_date),
                    freq='D',
                    tz=TZ
                )
                
                fig = px.bar(
                    dato_range,
                    x=dato_range,
                    y=[len(bestillinger[bestillinger['ankomst_dato'].dt.date == dato.date()]) for dato in dato_range],
                    labels={'x': 'Dato', 'y': 'Antall bestillinger'},
                    title='Tunbrøytingsaktivitet neste uke'
                )
                
                st.plotly_chart(fig, use_container_width=True, key="fig_today")
        
    except Exception as e:
        logger.error(f"Feil i vis_tunbroyting_statistikk: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise statistikk for tunbrøyting")


# tun_utils.py
# Kategori: View Functions

def vis_tunbestillinger_for_periode():
    """Viser tunbrøytingsbestillinger for valgt periode med formatert visning"""
    st.subheader("Tunbrøyting i valgt periode")
    
    # Hent standardperiode fra config
    default_start, default_end = get_default_date_range()
    
    # Datovelgere
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Fra dato", 
            value=default_start.date(),
            min_value=datetime.now(TZ).date() - timedelta(days=DATE_VALIDATION["default_date_range"]),
            max_value=datetime.now(TZ).date() + timedelta(days=DATE_VALIDATION["max_future_booking"]),
            format=get_date_format("display", "date").replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
        )
    with col2:
        end_date = st.date_input(
            "Til dato", 
            value=default_end.date(),
            min_value=start_date,
            max_value=start_date + timedelta(days=DATE_VALIDATION["max_future_booking"]),
            format=get_date_format("display", "date").replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
        )
        
    if start_date <= end_date:
        # Konverter datoer til datetime med tidssone
        periode_start = combine_date_with_tz(start_date)
        periode_slutt = combine_date_with_tz(end_date)
        
        bestillinger = hent_bestillinger_for_periode(periode_start, periode_slutt)
        
        if not bestillinger.empty:
            try:
                # Konverter datokolonner til riktig format
                for col in ['ankomst_dato', 'avreise_dato']:
                    if col in bestillinger.columns:
                        bestillinger[col] = bestillinger[col].apply(safe_to_datetime)
                
                # Lag visnings-DataFrame
                visnings_df = pd.DataFrame({
                    "rode": bestillinger["customer_id"].apply(get_rode),
                    "Hytte": bestillinger["customer_id"],
                    "Type": bestillinger["abonnement_type"],
                    "Ankomst": bestillinger["ankomst_dato"].apply(
                        lambda x: format_date(x, "display", "date")
                    ),
                    "Avreise": bestillinger["avreise_dato"].apply(
                        lambda x: format_date(x, "display", "date") if pd.notnull(x) else "Ikke satt"
                    )
                })
                
                # Sorter og vis
                visnings_df = visnings_df.sort_values(["rode", "Hytte"])
                
                # Vis statistikk
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Antall bestillinger", len(visnings_df))
                with col2:
                    st.metric("Antall unike hytter", visnings_df["Hytte"].nunique())
                
                # Vis dataframe
                st.dataframe(
                    visnings_df,
                    column_config={
                        "rode": st.column_config.NumberColumn("Rode", format="%d"),
                        "Hytte": "Hytte",
                        "Type": "Type",
                        "Ankomst": "Ankomst",
                        "Avreise": "Avreise"
                    },
                    hide_index=True
                )
                
                # Last ned som CSV
                periode_str = f"{format_date(periode_start, 'api', 'date')}_{format_date(periode_slutt, 'api', 'date')}"
                csv = visnings_df.to_csv(index=False)
                st.download_button(
                    label="Last ned som CSV",
                    data=csv,
                    file_name=f"tunbroyting_bestillinger_{periode_str}.csv",
                    mime="text/csv",
                    help="Last ned bestillingene som CSV-fil"
                )
                
            except Exception as e:
                logger.error(f"Feil ved visning av bestillinger: {str(e)}", exc_info=True)
                st.error("Kunne ikke vise bestillingene. Vennligst prøv igjen senere.")
        else:
            st.info("Ingen bestillinger funnet for valgt periode")

# liste for tunkart-siden
def vis_dagens_bestillinger():
    """Viser dagens aktive bestillinger i en tabell"""
    dagens_dato = get_current_time().date()
    logger.info(f"Viser bestillinger for dato: {dagens_dato}")
    
    try:
        dagens_bestillinger = hent_aktive_bestillinger_for_dag(dagens_dato)
        logger.info(f"Dagens aktive bestillinger: {dagens_bestillinger.to_string()}")

        if not dagens_bestillinger.empty:
            # Lag en ny DataFrame for visning
            visnings_df = pd.DataFrame()
            
            # Legg til 'rode' informasjon
            visnings_df["rode"] = dagens_bestillinger["customer_id"].apply(get_rode)
            
            # Kopier og rename kolonner
            visnings_df["hytte"] = dagens_bestillinger["customer_id"]
            visnings_df["abonnement_type"] = dagens_bestillinger["abonnement_type"]
            
            # Formater dato og tid
            # Formater dato og tid
            visnings_df["ankomst"] = dagens_bestillinger["ankomst_dato"].apply(
                lambda x: format_date(x, "display", "datetime")
            )
            visnings_df["avreise"] = dagens_bestillinger["avreise_dato"].apply(
                lambda x: format_date(x, "display", "datetime") if pd.notnull(x) else "Ikke satt"
            )
            # Vis DataFrame
            st.dataframe(
                visnings_df,
                column_config={
                    "rode": "Rode",
                    "hytte": "Hytte",
                    "abonnement_type": "Type",
                    "ankomst": "Ankomst",
                    "avreise": "Avreise"
                },
                hide_index=True
            )
        else:
            st.info("Ingen aktive bestillinger i dag.")
            
    except Exception as e:
        logger.error(f"Feil i vis_dagens_bestillinger: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise dagens bestillinger. Vennligst prøv igjen senere.")


def print_dataframe_info(df, name):
    print(f"\n--- {name} ---")
    print(f"Shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"Data types:\n{df.dtypes}")
    print(f"First few rows:\n{df.head()}")
    print("---\n")


# File: app.py
# Category: View Functions


def vis_tunbroyting_oversikt():
    """
    Viser oversikt over tunbrøytingsbestillinger med kart og lister.
    Bruker config.py for standardisert dato- og tidshåndtering.
    """
    st.title("Oversikt over tunbestillinger")
    
    try:
        # Hent bestillinger
        bestillinger = get_bookings()
        
        if bestillinger.empty:
            st.write("Ingen bestillinger å vise.")
            return

        # Konverter datokolonner til riktig format og tidssone
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in bestillinger.columns:
                bestillinger[col] = bestillinger[col].apply(safe_to_datetime)

        # Hent Mapbox token
        try:
            mapbox_token = st.secrets["mapbox"]["access_token"]
        except Exception as e:
            st.error("Kunne ikke hente Mapbox token. Vennligst sjekk konfigurasjonen.")
            logger.error(f"Mapbox token error: {str(e)}")
            return

        # --- Vis kart for dagens bestillinger ---
        current_time = get_current_time()
        dagens_bestillinger = filter_todays_bookings(bestillinger)
        
        if not dagens_bestillinger.empty:
            st.subheader(f"Kart over tunbrøytinger {format_date(current_time, 'display', 'date')}")
            
            # Verifiser kartkonfigurasjon
            is_valid, error_msg = verify_map_configuration(dagens_bestillinger, mapbox_token)
            
            if is_valid:
                debug_map_data(dagens_bestillinger)  # Logger debug info
                
                fig_today = vis_dagens_tunkart(
                    dagens_bestillinger, 
                    mapbox_token, 
                    f"Tunbrøyting {format_date(current_time, 'display', 'date')}"
                )
                
                if fig_today:
                    st.plotly_chart(fig_today, use_container_width=True, key="fig_today")
                else:
                    st.warning("Kunne ikke generere kart for dagens tunbrøytinger")
            else:
                st.warning(f"Kunne ikke vise kart: {error_msg}")
        
        # --- Vis dagens bestillinger som liste ---
        st.subheader(f"Tunbrøytinger {format_date(current_time, 'display', 'date')}")
        vis_dagens_bestillinger()
        st.write("---")
        
        # --- Vis bestillinger for valgt periode ---
        st.subheader("Tunbrøyting i valgt periode")
        
        # Bruk standardiserte datofunksjoner fra config
        default_start, default_end = get_default_date_range()
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Fra dato",
                value=default_start.date(),
                min_value=datetime.now(TZ).date() - timedelta(days=DATE_VALIDATION["default_date_range"]),
                max_value=datetime.now(TZ).date() + timedelta(days=DATE_VALIDATION["max_future_booking"]),
                format=get_date_format("display", "date").replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
            )
        
        with col2:
            end_date = st.date_input(
                "Til dato",
                value=default_end.date(),
                min_value=start_date,
                max_value=start_date + timedelta(days=DATE_VALIDATION["max_future_booking"]),
                format=get_date_format("display", "date").replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
            )
        
        # Konverter datoer til datetime med tidssone
        periode_start = combine_date_with_tz(start_date)
        periode_slutt = combine_date_with_tz(end_date)
        
        periode_bestillinger = hent_bestillinger_for_periode(periode_start, periode_slutt)
        if not periode_bestillinger.empty:
            for col in ['ankomst_dato', 'avreise_dato']:
                if col in periode_bestillinger.columns:
                    periode_bestillinger[col] = periode_bestillinger[col].apply(safe_to_datetime)
            
            # Vis oversikt
            st.dataframe(
                periode_bestillinger,
                column_config={
                    "customer_id": "Hytte",
                    "ankomst_dato": st.column_config.DatetimeColumn(
                        "Ankomst",
                        format="DD.MM.YYYY"
                    ),
                    "avreise_dato": st.column_config.DatetimeColumn(
                        "Avreise",
                        format="DD.MM.YYYY"
                    ),
                    "abonnement_type": "Type"
                }
            )
        else:
            st.info("Ingen bestillinger funnet for valgt periode.")
        
        # --- Vis hytter med årsabonnement ---
        st.write("---")
        vis_arsabonnenter()

    except Exception as e:
        logger.error(f"Feil i vis_tunbroyting_oversikt: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av tunbrøytingsoversikten")

def vis_aktive_bestillinger():
    st.subheader("Aktive tunbestillinger")

    # Hent alle bestillinger
    bestillinger = get_bookings()

    # Filtreringsmuligheter
    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input(
            "Fra dato", value=datetime.now(TZ).date(), key="active_start_date"
        )
    with col2:
        end_date = st.date_input(
            "Til dato",
            value=datetime.now(TZ).date() + timedelta(days=30),
            key="active_end_date",
        )
    with col3:
        abonnement_type = st.multiselect(
            "Abonnement type",
            options=bestillinger["abonnement_type"].unique(),
            key="active_abonnement_type",
        )

    # Filtrer bestillinger
    mask = (pd.to_datetime(bestillinger["ankomst_dato"]).dt.date >= start_date) & (
        pd.to_datetime(bestillinger["ankomst_dato"]).dt.date <= end_date
    )
    if abonnement_type:
        mask &= bestillinger["abonnement_type"].isin(abonnement_type)

    filtered_bestillinger = bestillinger[mask]

    # Sorter bestillinger
    sort_column = st.selectbox(
        "Sorter etter",
        options=["ankomst_dato", "customer_id", "abonnement_type"],
        key="active_sort_column",
    )
    sort_order = st.radio(
        "Sorteringsrekkefølge",
        options=["Stigende", "Synkende"],
        key="active_sort_order",
    )

    filtered_bestillinger = filtered_bestillinger.sort_values(
        by=sort_column, ascending=(sort_order == "Stigende")
    )

    # Vis dataframe
    st.dataframe(filtered_bestillinger)

    # Vis statistikk
    st.subheader("Statistikk")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Totalt antall aktive bestillinger", len(filtered_bestillinger))
    with col2:
        st.metric(
            "Antall årsabonnementer",
            len(
                filtered_bestillinger[
                    filtered_bestillinger["abonnement_type"] == "Årsabonnement"
                ]
            ),
        )
    with col3:
        st.metric(
            "Antall ukentlige bestillinger",
            len(
                filtered_bestillinger[
                    filtered_bestillinger["abonnement_type"]
                    == "Ukentlig ved bestilling"
                ]
            ),
        )

    # Vis kart over aktive bestillinger
    if not filtered_bestillinger.empty:
        st.subheader("Kart over aktive bestillinger")
        customer_db = load_customer_database()

        # Merge bestillinger with customer data
        merged_data = pd.merge(
            filtered_bestillinger,
            customer_db,
            left_on="customer_id",
            right_on="Id",
            how="left",
        )

        # Create the map
        fig = go.Figure(
            go.Scattermapbox(
                lat=merged_data["Latitude"],
                lon=merged_data["Longitude"],
                mode="markers",
                marker=go.scattermapbox.Marker(size=10),
                text=merged_data["Id"],
                hoverinfo="text",
            )
        )

        fig.update_layout(
            mapbox_style="open-street-map",
            mapbox=dict(
                center=go.layout.mapbox.Center(
                    lat=merged_data["Latitude"].mean(),
                    lon=merged_data["Longitude"].mean(),
                ),
                zoom=13,
            ),
            showlegend=False,
            height=600,
        )

        st.plotly_chart(fig)
    else:
        st.info("Ingen aktive bestillinger å vise på kartet.")


# Viser bestillinger for en bruker i Bestill tunbrøyting
def display_bookings(customer_id):
    """Viser brukerens tunbrøytingsbestillinger"""
    try:
        bruker_bestillinger = get_bookings()
        if not bruker_bestillinger.empty:
            # Filtrer på bruker_id
            bruker_bestillinger = bruker_bestillinger[
                bruker_bestillinger["customer_id"].astype(str) == str(customer_id)
            ].sort_values("ankomst", ascending=False)

            for _, bestilling in bruker_bestillinger.iterrows():
                with st.expander(
                    f"Bestilling - {bestilling['ankomst'].strftime('%d.%m.%Y')}"
                ):
                    st.write(
                        f"Ankomst: {bestilling['ankomst'].strftime('%d.%m.%Y %H:%M')}"
                    )
                    if pd.notna(bestilling["avreise"]):
                        st.write(
                            f"Avreise: {bestilling['avreise'].strftime('%d.%m.%Y %H:%M')}"
                        )
                    st.write(f"Type: {bestilling['abonnement_type']}")
        else:
            st.info("Du har ingen tidligere bestillinger.")

    except Exception as e:
        logger.error(f"Feil ved visning av bestillinger: {str(e)}")
        st.error("Kunne ikke vise dine bestillinger. Vennligst prøv igjen senere.")


def vis_hyttegrend_aktivitet():
    try:
        st.subheader("Aktive tunbestillinger i hyttegrenda")
        st.info(
            "💡  Siktemålet er å være ferdig med tunbrøyting på fredager innen kl 15. "
            "Store snøfall, våt snø og/eller mange bestillinger, kan medføre forsinkelser."
        )
        alle_bestillinger = get_bookings()
        if alle_bestillinger.empty:
            st.info("Ingen bestillinger funnet for perioden.")
            return

        # Konverter datoer til datetime med tidssone
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in alle_bestillinger.columns:
                alle_bestillinger[col] = alle_bestillinger[col].apply(safe_to_datetime)
        
        start_date, end_date = get_default_date_range()
        dato_range = pd.date_range(
            start=normalize_datetime(start_date),
            end=normalize_datetime(end_date),
            freq='D',
            tz=TZ
        )
        
        df_aktivitet = pd.DataFrame(index=dato_range)
        df_aktivitet['dato_str'] = df_aktivitet.index.strftime(get_date_format("display", "short_date"))
        df_aktivitet['antall'] = 0
        
        for dato in dato_range:
            dato_normalized = normalize_datetime(dato)
            daily_bestillinger = alle_bestillinger[
                (alle_bestillinger['ankomst_dato'].apply(normalize_datetime) == dato_normalized)
            ]
            df_aktivitet.loc[dato, 'antall'] = len(daily_bestillinger)
        
        fig = px.bar(
            df_aktivitet,
            x=df_aktivitet.index,
            y='antall',
            labels={'x': 'Dato', 'antall': 'Antall bestillinger'},
            title='Tunbrøytingsaktivitet neste uke'
        )
        
        st.plotly_chart(fig, use_container_width=True, key="unique_key_1")
        return df_aktivitet
        
    except Exception as e:
        logger.error(f"Feil i vis_hyttegrend_aktivitet: {str(e)}")
        st.error("Kunne ikke vise aktivitetsoversikt")
        return None


def get_bookings(start_date=None, end_date=None):
    """Henter bestillinger fra databasen"""
    try:
        logger.info(f"get_bookings called with start_date={start_date}, end_date={end_date}")

        with get_db_connection("tunbroyting") as conn:
            query = """
            SELECT DISTINCT 
                id, 
                customer_id,
                ankomst_dato,
                ankomst_tid,
                avreise_dato,
                avreise_tid,
                abonnement_type
            FROM tunbroyting_bestillinger
            """

            params = []
            if start_date:
                query += " WHERE ankomst_dato >= ?"
                params.append(start_date)
            if end_date:
                query += " AND ankomst_dato <= ?" if start_date else " WHERE ankomst_dato <= ?"
                params.append(end_date)

            df = pd.read_sql_query(query, conn, params=params)
            
            # Konverter datokolonner til datetime med tidssone
            for col in ['ankomst_dato', 'avreise_dato']:
                if col in df.columns:
                    df[col] = pd.to_datetime(
                        df[col], 
                        format=DATE_FORMATS["database"]["date"]
                    ).dt.tz_localize(TZ)
            
            logger.info(f"Raw data:\n{df.to_string()}")
            return df

    except Exception as e:
        logger.error(f"Error in get_bookings: {str(e)}")
        return pd.DataFrame()
