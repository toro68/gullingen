import os
import sqlite3
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.core.config import DATABASE_PATH, TZ
from utils.core.logging_config import get_logger
from utils.core.util_functions import neste_fredag
from utils.core.validation_utils import validere_bestilling
from utils.db.db_utils import fetch_data, get_db_connection
from utils.services.map_utils import vis_dagens_tunkart
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
    logger.info("Starting bestill_tunbroyting()")
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

        # Log user info
        logger.info(f"User ID from session: {st.session_state.user_id}")

        customer = get_customer_by_id(st.session_state.user_id)
        logger.info(f"Retrieved customer data: {customer}")

        if customer is None:
            logger.error("Customer data is None")
            st.error("Kunne ikke hente brukerinformasjon. Vennligst logg inn på nytt.")
            return

        user_id = customer["customer_id"]
        logger.info(f"Using user_id: {user_id}")
        user_subscription = customer.get("subscription") or customer.get("icon")

        if user_subscription not in ["star_white", "star_red"]:
            st.warning(
                "Du har ikke et aktivt tunbrøytingsabonnement og kan derfor ikke bestille tunbrøyting."
            )
            return

        naa = datetime.now(TZ)
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

        bestillingsfrist = datetime.combine(
            ankomst_dato - timedelta(days=1), time(12, 0)
        ).replace(tzinfo=TZ)

        if st.button("Bestill Tunbrøyting"):
            if naa >= bestillingsfrist:
                st.error(
                    f"Beklager, fristen for å bestille tunbrøyting for {ankomst_dato.strftime('%d.%m.%Y')} var {bestillingsfrist.strftime('%d.%m.%Y kl. %H:%M')}. "
                )
            else:
                resultat = lagre_bestilling(
                    user_id,
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
        bruker_bestillinger = hent_bruker_bestillinger(user_id)
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
    user_id: str,
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
                WHERE bruker = ? AND ankomst_dato = ?
            """,
                (user_id, ankomst_dato),
            )

            if cursor.fetchone()[0] > 0:
                logger.warning(
                    f"Bruker {user_id} har allerede bestilling på {ankomst_dato}"
                )
                return False

            # Valider input - fjernet ankomst_tid fra valideringen
            if not all([user_id, ankomst_dato, abonnement_type]):
                logger.error("Manglende påkrevde felter i bestilling")
                return False

            # SQL-spørring med eksplisitte kolonnenavn
            query = """
            INSERT INTO tunbroyting_bestillinger 
            (bruker, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """

            cursor.execute(
                query,
                (
                    str(user_id),
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
def hent_bruker_bestillinger(user_id):
    """Henter brukerens bestillinger"""
    try:
        with get_db_connection("tunbroyting") as conn:
            query = """
            SELECT DISTINCT * FROM tunbroyting_bestillinger 
            WHERE bruker = ? 
            ORDER BY ankomst_dato DESC, ankomst_tid DESC
            """
            df = pd.read_sql_query(query, conn, params=(user_id,))

        logger.info(f"Hentet {len(df)} unike bestillinger for bruker {user_id}")
        return df

    except Exception as e:
        logger.error(f"Feil ved henting av bestillinger: {str(e)}")
        return pd.DataFrame()


def hent_bestillinger_for_periode(start_date, end_date):
    """Henter bestillinger for en gitt periode"""
    try:
        logger.info(f"Henter bestillinger fra {start_date} til {end_date}")

        with get_db_connection("tunbroyting") as conn:
            query = """
            SELECT id, bruker, ankomst_dato, ankomst_tid, 
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
                start_date, end_date,  # For vanlige bestillinger
                end_date, start_date   # For årsabonnement
            ]

            logger.info(f"Executing query with params: {params}")
            df = pd.read_sql_query(query, conn, params=params)
            
            logger.info(f"Query returned {len(df)} rows")
            logger.info(f"Raw data:\n{df.to_string()}")

            return df

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
        "unike_brukere": bestillinger["bruker"].nunique(),
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
        SELECT id, bruker, ankomst_dato, avreise_dato, abonnement_type
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

        bestilling = df.iloc[0]

        # Konverter dato- og tidskolonner
        for col in ["ankomst_dato", "avreise_dato"]:
            bestilling[col] = pd.to_datetime(bestilling[col], errors="coerce")

        for col in ["ankomst_tid", "avreise_tid"]:
            bestilling[col] = pd.to_datetime(
                bestilling[col], format="%H:%M:%S", errors="coerce"
            ).time()

        logger.info("Hentet bestilling med ID %s", bestilling_id)
        return bestilling

    except Exception as e:
        logger.error(
            "Feil ved henting av bestilling %s: %s",
            bestilling_id,
            str(e),
            exc_info=True,
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
                   SET bruker = ?, ankomst_dato = ?, ankomst_tid = ?, 
                       avreise_dato = ?, avreise_tid = ?, abonnement_type = ?
                   WHERE id = ?"""
        params = (
            nye_data["bruker"],
            nye_data["ankomst_dato"].isoformat(),
            nye_data["ankomst_tid"].isoformat(),
            nye_data["avreise_dato"].isoformat() if nye_data["avreise_dato"] else None,
            nye_data["avreise_tid"].isoformat() if nye_data["avreise_tid"] else None,
            nye_data["abonnement_type"],
            bestilling_id,
        )
        with get_db_connection("tunbroyting") as conn:
            c = conn.cursor()
            c.execute(query, params)
            conn.commit()
        logger.info("Bestilling %s oppdatert", bestilling_id)
        return True
    except sqlite3.Error as e:
        logger.error(
            "Database error ved oppdatering av bestilling %s: %s", bestilling_id, str(e)
        )
        return False
    except Exception as e:
        logger.error(
            "Uventet feil ved oppdatering av bestilling %s: %s", bestilling_id, str(e)
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
    # Vis bestillinger for en periode
    st.header("Vis bestillinger for periode")
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=datetime.now().date())
    with col2:
        end_date = st.date_input("Til dato", value=start_date + timedelta(days=7))

    bestillinger = hent_bestillinger_for_periode(start_date, end_date)
    if not bestillinger.empty:
        st.dataframe(bestillinger)
    else:
        st.info("Ingen bestillinger funnet for valgt periode.")

    st.header("Rediger bestilling")

    max_id = get_max_bestilling_id()
    total_bestillinger = count_bestillinger()
    st.write(f"Totalt antall aktive bestillinger: {total_bestillinger}")
    st.write(f"Høyeste bestillings-ID: {max_id}")

    bestilling_id = st.number_input(
        "Skriv inn bestillings-ID for redigering", min_value=1, max_value=max(max_id, 1)
    )

    eksisterende_data = hent_bestilling(bestilling_id)

    if eksisterende_data is not None:
        st.success(f"Bestilling funnet med ID {bestilling_id}")
        with st.form("rediger_bestilling_form"):
            nye_data = {}
            nye_data["bruker"] = st.text_input(
                "Bruker", value=eksisterende_data["bruker"]
            )

            # Håndter ankomst_dato
            ankomst_dato = (
                pd.to_datetime(eksisterende_data["ankomst_dato"]).date()
                if pd.notnull(eksisterende_data["ankomst_dato"])
                else datetime.now().date()
            )
            nye_data["ankomst_dato"] = st.date_input("Ankomstdato", value=ankomst_dato)

            # Håndter ankomst_tid
            ankomst_tid = (
                eksisterende_data["ankomst_tid"]
                if pd.notnull(eksisterende_data["ankomst_tid"])
                else datetime.now().time()
            )
            nye_data["ankomst_tid"] = st.time_input("Ankomsttid", value=ankomst_tid)

            # Håndter avreise_dato
            avreise_dato = (
                pd.to_datetime(eksisterende_data["avreise_dato"]).date()
                if pd.notnull(eksisterende_data["avreise_dato"])
                else None
            )
            nye_data["avreise_dato"] = st.date_input(
                "Avreisetato", value=avreise_dato or ankomst_dato
            )

            # Håndter avreise_tid
            avreise_tid = (
                eksisterende_data["avreise_tid"]
                if pd.notnull(eksisterende_data["avreise_tid"])
                else datetime.now().time()
            )
            nye_data["avreise_tid"] = st.time_input("Avreisetid", value=avreise_tid)

            # Håndter abonnement_type
            nye_data["abonnement_type"] = st.selectbox(
                "Abonnementstype",
                options=["Ukentlig ved bestilling", "Årsabonnement"],
                index=["Ukentlig ved bestilling", "Årsabonnement"].index(
                    eksisterende_data["abonnement_type"]
                ),
            )

            submitted = st.form_submit_button("Oppdater bestilling")

            if submitted:
                if validere_bestilling(nye_data):
                    if oppdater_bestilling(bestilling_id, nye_data):
                        st.success(f"Bestilling {bestilling_id} er oppdatert!")
                    else:
                        st.error(
                            "Det oppstod en feil under oppdatering av bestillingen."
                        )
                else:
                    st.error("Ugyldig input. Vennligst sjekk datoene og prøv igjen.")
    else:
        st.warning(f"Ingen aktiv bestilling funnet med ID {bestilling_id}")


# oppdaterer bestilling i Admin-panelet
def handle_tun():
    st.title("Håndter tunbestillinger")
    st.info("Her kan Fjellbergsskardet Drift redigere og slette bestillinger.")

    # Vis statistikk
    total_bestillinger = count_bestillinger()
    st.write(f"Totalt antall bestillinger: {total_bestillinger}")

    # Legg til en ekspanderende seksjon for statistikk og visualiseringer
    with st.expander("Vis statistikk og visualiseringer", expanded=False):
        vis_tunbroyting_statistikk(get_bookings)

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
    """Henter aktive bestillinger for en gitt dag, inkludert årsabonnement."""
    alle_bestillinger = get_bookings()
    logger.info(f"Henter aktive bestillinger for dato: {dato}")
    
    try:
        # Konverter datokolonnene til datetime
        alle_bestillinger["ankomst_dato"] = pd.to_datetime(alle_bestillinger["ankomst_dato"])
        alle_bestillinger["avreise_dato"] = pd.to_datetime(alle_bestillinger["avreise_dato"])
        
        aktive_bestillinger = alle_bestillinger[
            # Vanlige bestillinger som er aktive i dag
            (
                (alle_bestillinger["abonnement_type"] != "Årsabonnement")
                & (
                    (alle_bestillinger["ankomst_dato"].dt.date == dato)
                    | (
                        (alle_bestillinger["ankomst_dato"].dt.date <= dato)
                        & (alle_bestillinger["avreise_dato"].dt.date >= dato)
                    )
                )
            )
            |
            # Årsabonnement som er aktive
            (
                (alle_bestillinger["abonnement_type"] == "Årsabonnement")
                & (
                    (alle_bestillinger["ankomst_dato"].isnull() & alle_bestillinger["avreise_dato"].isnull())
                    |
                    (
                        (alle_bestillinger["ankomst_dato"].dt.date <= dato)
                        & (
                            alle_bestillinger["avreise_dato"].isnull()
                            | (alle_bestillinger["avreise_dato"].dt.date >= dato)
                        )
                    )
                )
            )
        ].copy()
        
        logger.info(f"Fant {len(aktive_bestillinger)} aktive bestillinger")
        return aktive_bestillinger
        
    except Exception as e:
        logger.error(f"Feil ved henting av aktive bestillinger: {str(e)}", exc_info=True)
        return pd.DataFrame()


# filtrerer bestillinger i bestill_tunbroyting
def filter_tunbroyting_bestillinger(
    bestillinger: pd.DataFrame, filters: Dict[str, Any]
) -> pd.DataFrame:
    filtered = bestillinger.copy()
    current_date = datetime.now(TZ).date()

    if filters.get("vis_type") == "today":
        filtered = filtered[
            (filtered["abonnement_type"] == "Årsabonnement")
            | (
                (filtered["abonnement_type"] == "Ukentlig ved bestilling")
                & (
                    (filtered["ankomst"].dt.date <= current_date)
                    & (
                        (filtered["avreise"].isnull())
                        | (filtered["avreise"].dt.date >= current_date)
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
                    (filtered["ankomst"].dt.date <= end_date)
                    & (
                        (filtered["avreise"].isnull())
                        | (filtered["avreise"].dt.date >= current_date)
                    )
                )
            )
        ]
    else:
        if filters.get("start_date"):
            filtered = filtered[
                (filtered["ankomst"].dt.date >= filters["start_date"])
                | (
                    (filtered["ankomst"].dt.date < filters["start_date"])
                    & (
                        (filtered["avreise"].isnull())
                        | (filtered["avreise"].dt.date >= filters["start_date"])
                    )
                )
            ]
        if filters.get("end_date"):
            filtered = filtered[filtered["ankomst"].dt.date <= filters["end_date"]]

    if filters.get("abonnement_type"):
        filtered = filtered[
            filtered["abonnement_type"].isin(filters["abonnement_type"])
        ]

    return filtered


def filter_todays_bookings(bestillinger: pd.DataFrame) -> pd.DataFrame:
    """
    Filtrerer bestillinger for å vise dagens aktive bestillinger.
    Ekskluderer årsabonnenter som ikke har aktiv bestilling.
    """
    if bestillinger.empty:
        logger.info("No bookings found to filter")
        return bestillinger

    try:
        current_date = datetime.now(TZ).date()
        logger.info(f"Filtering bookings for date: {current_date}")

        # Lag en ny kopi av DataFrame for å unngå advarsler
        result = bestillinger.copy()

        # Sjekk at nødvendige kolonner eksisterer
        required_columns = ["abonnement_type", "ankomst_dato", "avreise_dato"]
        if not all(col in result.columns for col in required_columns):
            logger.error(f"Missing required columns. Available columns: {result.columns}")
            return pd.DataFrame()

        # Konverter datoer til date objekter for konsistent sammenligning
        result["ankomst_dato"] = pd.to_datetime(result["ankomst_dato"]).dt.date
        result["avreise_dato"] = pd.to_datetime(result["avreise_dato"]).dt.date

        # Filtrer bestillinger basert på type og dato
        aktive_bestillinger = result.apply(
            lambda row: (
                # Kun ukentlige bestillinger
                (row["abonnement_type"] == "Ukentlig ved bestilling" and
                 row["ankomst_dato"] <= current_date and
                 (pd.isna(row["avreise_dato"]) or current_date <= row["avreise_dato"]))
            ),
            axis=1
        )

        # Filtrer dataframe
        result = result[aktive_bestillinger].copy()
        
        logger.info(f"Found {len(result)} active bookings for today")
        return result

    except Exception as e:
        logger.error(f"Error filtering today's bookings: {str(e)}", exc_info=True)
        return pd.DataFrame()


def tunbroyting_kommende_uke(bestillinger):
    current_date = datetime.now(TZ).date()
    end_date = current_date + timedelta(days=7)

    return bestillinger[
        # Bestillinger som starter innenfor neste uke
        (
            (bestillinger["ankomst"].dt.date >= current_date)
            & (bestillinger["ankomst"].dt.date <= end_date)
        )
        |
        # Bestillinger som allerede er aktive og fortsetter inn i neste uke
        (
            (bestillinger["ankomst"].dt.date < current_date)
            & (
                (bestillinger["avreise"].isnull())
                | (bestillinger["avreise"].dt.date >= current_date)
            )
        )
        |
        # Årsabonnementer
        (bestillinger["abonnement_type"] == "Årsabonnement")
    ]


# Visninger for tunbrøyting
def vis_tunbroyting_statistikk():
    # Hent bestillinger som DataFrame
    bestillinger_df = get_bookings()  # Endre fra bestillinger = get_bookings()
    
    if bestillinger_df.empty:
        st.info("Ingen bestillinger funnet")
        return
    
    # ... resten av funksjonen ...


def vis_tunbestillinger_for_periode():
    st.subheader("Tunbrøyting i valgt periode")

    # Datovelgere
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=datetime.now(TZ).date())
    with col2:
        end_date = st.date_input("Til dato", value=start_date + timedelta(days=7))

    if start_date <= end_date:
        bestillinger = hent_bestillinger_for_periode(start_date, end_date)

        if not bestillinger.empty:
            # Legg til 'rode' informasjon til bestillingene
            bestillinger["rode"] = bestillinger["bruker"].apply(get_rode)

            # Endre kolonnenavn fra 'bruker' til 'Hytte'
            bestillinger = bestillinger.rename(columns={"bruker": "Hytte"})

            # Sorter bestillinger etter rode og deretter hytte
            bestillinger_sortert = bestillinger.sort_values(["rode", "Hytte"])

            st.subheader(f"Bestillinger for perioden {start_date} til {end_date}")

            # Velg kolonner som skal vises
            kolonner_a_vise = ["rode", "Hytte"]
            for kolonne in [
                "ankomst",
                "avreise",
                "ankomst_dato",
                "avreise_dato",
                "abonnement_type",
            ]:
                if kolonne in bestillinger_sortert.columns:
                    kolonner_a_vise.append(kolonne)

            st.dataframe(bestillinger_sortert[kolonner_a_vise])

            # Legg til mulighet for å laste ned bestillinger som CSV
            csv = bestillinger_sortert.to_csv(index=False)
            st.download_button(
                label="Last ned som CSV",
                data=csv,
                file_name=f"tunbroyting_bestillinger_{start_date}_{end_date}.csv",
                mime="text/csv",
            )


# liste for tunkart-siden
def vis_dagens_bestillinger():
    """Viser dagens aktive bestillinger i en tabell"""
    dagens_dato = datetime.now(TZ).date()
    logger.info(f"Viser bestillinger for dato: {dagens_dato}")
    
    try:
        dagens_bestillinger = hent_aktive_bestillinger_for_dag(dagens_dato)
        logger.info(f"Dagens aktive bestillinger: {dagens_bestillinger.to_string()}")

        if not dagens_bestillinger.empty:
            # Lag en ny DataFrame for visning
            visnings_df = pd.DataFrame()
            
            # Legg til 'rode' informasjon
            visnings_df["rode"] = dagens_bestillinger["bruker"].apply(get_rode)
            
            # Kopier og rename kolonner
            visnings_df["hytte"] = dagens_bestillinger["bruker"]
            visnings_df["abonnement_type"] = dagens_bestillinger["abonnement_type"]
            
            # Formater dato og tid
            visnings_df["ankomst"] = dagens_bestillinger["ankomst_dato"].dt.strftime("%Y-%m-%d %H:%M")
            visnings_df["avreise"] = dagens_bestillinger["avreise_dato"].apply(
                lambda x: x.strftime("%Y-%m-%d %H:%M") if pd.notnull(x) else "Ikke satt"
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
    st.title("Oversikt over tunbestillinger")
    
    bestillinger = get_bookings()
    logger.info(f"Hentet bestillinger: {bestillinger.to_string()}")
    
    if bestillinger.empty:
        st.write("Ingen bestillinger å vise.")
        return

    # Vis kart for dagens bestillinger først
    dagens_bestillinger = filter_todays_bookings(bestillinger)
    logger.info(f"Dagens bestillinger: {dagens_bestillinger.to_string()}")
    
    # Vis kartet hvis det finnes bestillinger
    if not dagens_bestillinger.empty:
        st.subheader("Kart over dagens tunbrøytinger")
        fig_today = vis_dagens_tunkart(
            dagens_bestillinger, 
            st.secrets["mapbox"]["access_token"], 
            "Dagens tunbrøyting"
        )
        if fig_today:
            st.plotly_chart(fig_today, use_container_width=True)
    
    # Vis dagens bestillinger som liste
    st.subheader("Dagens tunbrøytinger")
    vis_dagens_bestillinger()
    st.write("---")
    
    # Vis aktive bestillinger kommende uke
    vis_tunbestillinger_for_periode()
    
    # Vis hytter med årsabonnement
    vis_arsabonnenter()


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
        options=["ankomst_dato", "bruker", "abonnement_type"],
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
            left_on="bruker",
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
def display_bookings(user_id):
    """Viser brukerens tunbrøytingsbestillinger"""
    try:
        bruker_bestillinger = get_bookings()
        if not bruker_bestillinger.empty:
            # Filtrer på bruker_id
            bruker_bestillinger = bruker_bestillinger[
                bruker_bestillinger["bruker"].astype(str) == str(user_id)
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
    """Viser oversikt over tunbrøytingsaktivitet for neste 7 dager."""
    try:
        st.subheader("Aktive tunbestillinger i hyttegrenda")
        st.info(
            "💡  Siktemålet er å være ferdig med tunbrøyting på fredager innen kl 15. "
            "Store snøfall, våt snø og/eller mange bestillinger, kan medføre forsinkelser."
        )
        
        alle_bestillinger = get_bookings()
        logger.info(f"Hentet bestillinger: {alle_bestillinger.to_string()}")
        
        if alle_bestillinger is None:
            logger.error("Kunne ikke hente bestillinger fra databasen")
            st.error("Det oppstod en feil ved henting av bestillinger. Vennligst prøv igjen senere.")
            return
            
        if alle_bestillinger.empty:
            st.info("Ingen bestillinger funnet for perioden.")
            return

        # Konverter ankomst_dato til datetime og fjern timezone
        alle_bestillinger['ankomst_dato'] = pd.to_datetime(alle_bestillinger['ankomst_dato']).dt.tz_localize(None)
        logger.info(f"Konverterte datoer: {alle_bestillinger['ankomst_dato'].to_string()}")
            
        dagens_dato = pd.Timestamp.now(TZ).normalize().tz_localize(None)
        sluttdato = dagens_dato + pd.Timedelta(days=7)
        dato_range = pd.date_range(dagens_dato, sluttdato)
        logger.info(f"Datoperiode: {dato_range}")
        
        # Opprett aktivitets-DataFrame med sikker konvertering
        df_aktivitet = pd.DataFrame(index=dato_range).copy()
        
        # Bruk .loc for å unngå SettingWithCopyWarning
        df_aktivitet.loc[:, 'dato_str'] = df_aktivitet.index.strftime('%d.%m')
        df_aktivitet.loc[:, 'ukedag'] = df_aktivitet.index.strftime('%A').map({
            'Monday': 'Mandag', 'Tuesday': 'Tirsdag', 'Wednesday': 'Onsdag',
            'Thursday': 'Torsdag', 'Friday': 'Fredag', 'Saturday': 'Lørdag', 
            'Sunday': 'Søndag'
        })
        
        # Initialiser antall-kolonnen
        df_aktivitet.loc[:, 'antall'] = 0
        
        # Tell bestillinger per dag
        for dato in dato_range:
            logger.info(f"Prosesserer dato: {dato}")
            # Filter for ukentlige bestillinger på denne datoen
            daily_bestillinger = alle_bestillinger[
                (alle_bestillinger['ankomst_dato'].dt.normalize() == dato)
            ]
            daily_count = len(daily_bestillinger)
            logger.info(f"Antall bestillinger for {dato}: {daily_count}")
            
            df_aktivitet.loc[dato, 'antall'] = daily_count
            
        logger.info(f"Ferdig aktivitetsdata:\n{df_aktivitet.to_string()}")
        
        # Vis aktivitetsoversikt
        if df_aktivitet['antall'].sum() > 0:
            st.write("Oversikt over tunbrøytinger neste 7 dager:")
            
            # Formater visning
            df_display = df_aktivitet.copy()
            df_display['Dato'] = df_display['dato_str'] + ' (' + df_display['ukedag'] + ')'
            df_display = df_display[['Dato', 'antall']].rename(columns={'antall': 'Antall tun'})
            df_display = df_display[df_display['Antall tun'] > 0]  # Vis bare dager med bestillinger
            
            # Vis dataframe
            st.dataframe(
                df_display,
                hide_index=True
            )
            
            # Vis total
            st.write(f"Totalt antall tunbrøytinger i perioden: {df_aktivitet['antall'].sum()}")
        else:
            st.info("Ingen planlagte tunbrøytinger de neste 7 dagene.")
            
        # Legg til ekstra informasjon om fredager
        if df_aktivitet.loc[df_aktivitet.index[df_aktivitet.index.weekday == 4], 'antall'].sum() > 0:
            st.info("På fredager brøytes alle tun med årsabonnement automatisk.")
            
    except Exception as e:
        logger.error(f"Feil i vis_hyttegrend_aktivitet: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved lasting av tunbrøytingsaktivitet. Vennligst prøv igjen senere.")


def get_bookings(start_date=None, end_date=None):
    """Henter bestillinger fra databasen"""
    try:
        logger.info(
            f"get_bookings called with start_date={start_date}, end_date={end_date}"
        )

        with get_db_connection("tunbroyting") as conn:
            query = """
            SELECT DISTINCT id, bruker, ankomst_dato, ankomst_tid, 
                   avreise_dato, avreise_tid, abonnement_type
            FROM tunbroyting_bestillinger
            """

            params = []
            if start_date:
                query += " WHERE ankomst_dato >= ?"
                params.append(start_date)
            if end_date:
                query += (
                    " AND ankomst_dato <= ?"
                    if start_date
                    else " WHERE ankomst_dato <= ?"
                )
                params.append(end_date)

            logger.info(f"Executing query: {query} with params: {params}")

            df = pd.read_sql_query(query, conn, params=params)
            logger.info(f"Raw query result shape: {df.shape}")
            logger.info(f"Raw query result:\n{df.to_string()}")

            return df

    except Exception as e:
        logger.error(f"Error in get_bookings: {str(e)}", exc_info=True)
        return pd.DataFrame()
