import sqlite3
import pandas as pd
import os
from datetime import datetime, timedelta, time
from typing import Any, Dict, Optional, Tuple
import plotly.express as px
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import streamlit as st

from constants import TZ
from config import DATABASE_PATH
from util_functions import neste_fredag
from utils import is_active_booking
from customer_utils import get_customer_by_id, get_rode, load_customer_database, vis_arsabonnenter, customer_edit_component
from map_utils import vis_dagens_tunkart
from db_utils import get_db_connection, fetch_data
from logging_config import get_logger

logger = get_logger(__name__)

# CREATE - hovedfunksjon i app.py
def bestill_tunbroyting():
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

    customer = get_customer_by_id(st.session_state.user_id)
    if customer is None:
        st.error("Kunne ikke hente brukerinformasjon. Vennligst logg inn på nytt.")
        return

    user_id = customer["Id"]
    user_subscription = customer["Subscription"]

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
            st.write(f"Ankomstdato (neste fredag): {ankomst_dato.strftime('%d.%m.%Y')}")
        else:  # Årsabonnement
            ankomst_dato = st.date_input(
                "Velg ankomstdato",
                min_value=tomorrow,
                value=tomorrow,
                format="DD.MM.YYYY",
            )

    with col2:
        ankomst_tid = st.time_input("Velg ankomsttid")

    avreise_dato = None
    avreise_tid = None

    if abonnement_type == "Årsabonnement":
        col3, col4 = st.columns(2)
        with col3:
            avreise_dato = st.date_input(
                "Velg avreisedato",
                min_value=ankomst_dato,
                value=ankomst_dato + timedelta(days=1),
                format="DD.MM.YYYY",
            )
        with col4:
            avreise_tid = st.time_input("Velg avreisetid")

    bestillingsfrist = datetime.combine(
        ankomst_dato - timedelta(days=1), time(12, 0)
    ).replace(tzinfo=TZ)

    if st.button("Bestill Tunbrøyting"):
        if naa >= bestillingsfrist:
            st.error(
                f"Beklager, fristen for å bestille tunbrøyting for {ankomst_dato.strftime('%d.%m.%Y')} var {bestillingsfrist.strftime('%d.%m.%Y kl. %H:%M')}. "
            )
        else:
            if lagre_bestilling(
                user_id,
                ankomst_dato.isoformat(),
                ankomst_tid.isoformat(),
                avreise_dato.isoformat() if avreise_dato else None,
                avreise_tid.isoformat() if avreise_tid else None,
                abonnement_type,
            ):
                st.success("Bestilling av tunbrøyting er registrert!")
            else:
                st.error(
                    "Det oppstod en feil ved lagring av bestillingen. Vennligst prøv igjen senere."
                )

    st.info(
        f"Merk: Frist for bestilling er kl. 12:00 dagen før ønsket ankomstdato. For valgt dato ({ankomst_dato.strftime('%d.%m.%Y')}) er fristen {bestillingsfrist.strftime('%d.%m.%Y kl. %H:%M')}."
    )
    st.subheader("Dine tidligere bestillinger") 
    
    # Vis Dine tidligere bestillinger
    display_bookings(user_id)
    st.write("---")

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
        with get_db_connection('tunbroyting') as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO tunbroyting_bestillinger 
                         (bruker, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    ankomst_dato,
                    ankomst_tid,
                    avreise_dato,
                    avreise_tid,
                    abonnement_type,
                ),
            )
            conn.commit()
        logger.info("Ny tunbrøyting bestilling lagret for bruker: %s", user_id)
        return True
    except sqlite3.Error as e:
        logger.error("Database error ved lagring av tunbrøyting bestilling: %s", str(e))
        return False
    except Exception as e:
        logger.error("Uventet feil ved lagring av tunbrøyting bestilling: %s", e)
        return False

# READ
# Viser brukerens tidligere bestillinger i bestill_tunbroyting
def hent_bestillinger() -> pd.DataFrame:
    """Deprecated: Bruk get_bookings() i stedet"""
    logger.warning("hent_bestillinger() is deprecated, use get_bookings() instead")
    return get_bookings()

def hent_bruker_bestillinger(user_id):
    with get_db_connection('tunbroyting') as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE bruker = ? 
        ORDER BY ankomst_dato DESC, ankomst_tid DESC
        """
        df = pd.read_sql_query(query, conn, params=(user_id,))
    return df

def hent_bestillinger_for_periode(start_date, end_date):
    try:
        with get_db_connection('tunbroyting') as conn:
            query = """
            SELECT * FROM tunbroyting_bestillinger 
            WHERE (ankomst_dato BETWEEN ? AND ?) OR (avreise_dato BETWEEN ? AND ?)
            ORDER BY ankomst_dato, ankomst_tid
            """
            df = pd.read_sql_query(
                query, conn, params=(start_date, end_date, start_date, end_date)
            )
        return df
    except sqlite3.Error as e:
        logger.error(f"SQLite error in hent_bestillinger_for_periode: {str(e)}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Unexpected error in hent_bestillinger_for_periode: {str(e)}")
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

# READ for map
def hent_dagens_bestillinger() -> pd.DataFrame:
    """Deprecated: Bruk get_bookings() og filter_todays_bookings() i stedet"""
    logger.warning("hent_dagens_bestillinger() is deprecated, use get_bookings() and filter_todays_bookings() instead")
    return filter_todays_bookings(get_bookings())

def hent_aktive_bestillinger():
    today = datetime.now(TZ).date()
    with get_db_connection('tunbroyting') as conn:
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
        with get_db_connection('tunbroyting') as conn:
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
            "Feil ved henting av bestilling %s: %s", bestilling_id, str(e), exc_info=True
        )
        return None

# def count_bestillinger():
#     try:
#         with get_db_connection() as conn:
#             cursor = conn.cursor()
#             cursor.execute("SELECT COUNT(*) FROM tunbroyting_bestillinger")
#             return cursor.fetchone()[0]
#     except Exception as e:
#         logger.error(f"Feil ved telling av bestillinger: {str(e)}")
#         return 0

def get_max_bestilling_id():
    try:
        with get_db_connection('tunbroyting') as conn:
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
        with get_db_connection('tunbroyting') as conn:
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
        with get_db_connection('tunbroyting') as conn:
            c = conn.cursor()
            c.execute(
                "DELETE FROM tunbroyting_bestillinger WHERE id = ?", (bestilling_id,)
            )
            conn.commit()
        logger.info("Slettet bestilling med id: %s", bestilling_id)
        return True
    except sqlite3.Error as e:
        logger.error(
            "Database error ved sletting av bestilling med id %s: %s", bestilling_id, str(e)
        )
        return False
    except Exception as e:
        logger.error(
            "Uventet feil ved sletting av bestilling med id %s: %s", bestilling_id, str(e)
        )
        return False

# hjelpefunksjoner

# teller bestillinger i handle_tun
def count_bestillinger():
    try:
        with get_db_connection('tunbroyting') as conn:
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

# validerer bestilling i vis_rediger_bestilling
def validere_bestilling(data):
    if data["avreise_dato"] is None or data["avreise_tid"] is None:
        return True  # Hvis avreisedato eller -tid ikke er satt, er bestillingen gyldig

    ankomst = datetime.combine(data["ankomst_dato"], data["ankomst_tid"])
    avreise = datetime.combine(data["avreise_dato"], data["avreise_tid"])

    return avreise > ankomst

# oppdaterer bestilling i Admin-panelet
def handle_tun():
    st.title("Håndter tunbestillinger")
    st.info("Her kan Fjellbergsskardet Drift redigere og slette bestillinger.")
    
    # Vis statistikk
    total_bestillinger = count_bestillinger()
    st.write(f"Totalt antall bestillinger: {total_bestillinger}")

    # Legg til en ekspanderende seksjon for statistikk og visualiseringer
    with st.expander("Vis statistikk og visualiseringer", expanded=False):
        vis_tunbroyting_statistikk(hent_bestillinger())

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
            
# def handle_tun():
#     st.title("Håndter tunbestillinger")
#     st.info("Her kan Fjellbergsskardet Drift redigere og slette bestillinger.")
#     # Vis statistikk
#     total_bestillinger = count_bestillinger()
#     st.write(f"Totalt antall bestillinger: {total_bestillinger}")

#     # Legg til en ekspanderende seksjon for statistikk og visualiseringer
#     with st.expander("Vis statistikk og visualiseringer", expanded=False):
#         vis_tunbroyting_statistikk(hent_bestillinger())

#     # Rediger bestilling
#     # st.header("Rediger bestilling")
#     vis_rediger_bestilling()

#     # Slett bestilling
#     st.header("Slett bestilling")

#     slett_metode = st.radio(
#         "Velg slettingsmetode:",
#         ["Slett etter ID", "Slett etter brukernavn", "Slett etter datoperiode"],
#         key="slett_metode",
#     )

#     if slett_metode == "Slett etter ID":
#         slett_id = st.number_input(
#             "Skriv inn ID på bestillingen du vil slette", min_value=1, key="slett_id"
#         )
#         if st.button("Slett bestilling", key="slett_id_button"):
#             if slett_bestilling(slett_id):
#                 st.success(f"Bestilling {slett_id} er slettet.")
#             else:
#                 st.error(
#                     "Kunne ikke slette bestillingen. Vennligst sjekk ID og prøv igjen."
#                 )

#     elif slett_metode == "Slett etter brukernavn":
#         slett_bruker = st.text_input(
#             "Skriv inn brukernavn for å slette alle bestillinger fra brukeren",
#             key="slett_bruker",
#         )
#         if st.button("Slett bestillinger", key="slett_bruker_button"):
#             antall_slettet = slett_bestillinger_for_bruker(slett_bruker)
#             if antall_slettet > 0:
#                 st.success(
#                     f"{antall_slettet} bestilling(er) for bruker {slett_bruker} er slettet."
#                 )
#             else:
#                 st.warning(f"Ingen bestillinger funnet for bruker {slett_bruker}.")

#     elif slett_metode == "Slett etter datoperiode":
#         col1, col2 = st.columns(2)
#         with col1:
#             slett_dato_fra = st.date_input(
#                 "Slett bestillinger fra dato", key="slett_dato_fra"
#             )
#         with col2:
#             slett_dato_til = st.date_input(
#                 "Slett bestillinger til dato", key="slett_dato_til"
#             )
#         if st.button("Slett bestillinger", key="slett_dato_button"):
#             antall_slettet = slett_bestillinger_for_periode(
#                 slett_dato_fra, slett_dato_til
#             )
#             if antall_slettet > 0:
#                 st.success(
#                     f"{antall_slettet} bestilling(er) i perioden {slett_dato_fra} til {slett_dato_til} er slettet."
#                 )
#             else:
#                 st.warning(
#                     f"Ingen bestillinger funnet i perioden {slett_dato_fra} til {slett_dato_til}."
#                 )

def hent_aktive_bestillinger_for_dag(dato):
    # Hent alle bestillinger ved å bruke den eksisterende funksjonen hent_bestillinger()
    alle_bestillinger = hent_bestillinger()
    
    aktive_bestillinger = alle_bestillinger[
        # Bestillinger som starter i dag
        (alle_bestillinger['ankomst'].dt.date == dato) |
        # Bestillinger som er aktive i dag (startet før og slutter etter eller har ingen sluttdato)
        ((alle_bestillinger['ankomst'].dt.date < dato) & 
         ((alle_bestillinger['avreise'].isnull()) | (alle_bestillinger['avreise'].dt.date >= dato))) |
        # Årsabonnementer
        (alle_bestillinger['abonnement_type'] == 'Årsabonnement')
    ]
    
    return aktive_bestillinger

# filtrerer bestillinger i bestill_tunbroyting
def filter_tunbroyting_bestillinger(bestillinger: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    filtered = bestillinger.copy()
    current_date = datetime.now(TZ).date()

    if filters.get("vis_type") == "today":
        filtered = filtered[
            (filtered["abonnement_type"] == "Årsabonnement") |
            (
                (filtered["abonnement_type"] == "Ukentlig ved bestilling") &
                (
                    (filtered["ankomst"].dt.date <= current_date) &
                    (
                        (filtered["avreise"].isnull()) |
                        (filtered["avreise"].dt.date >= current_date)
                    )
                )
            )
        ]
    elif filters.get("vis_type") == "active":
        end_date = current_date + timedelta(days=7)
        filtered = filtered[
            (filtered["abonnement_type"] == "Årsabonnement") |
            (
                (filtered["abonnement_type"] == "Ukentlig ved bestilling") &
                (
                    (filtered["ankomst"].dt.date <= end_date) &
                    (
                        (filtered["avreise"].isnull()) |
                        (filtered["avreise"].dt.date >= current_date)
                    )
                )
            )
        ]
    else:
        if filters.get("start_date"):
            filtered = filtered[
                (filtered["ankomst"].dt.date >= filters["start_date"]) |
                (
                    (filtered["ankomst"].dt.date < filters["start_date"]) &
                    (
                        (filtered["avreise"].isnull()) |
                        (filtered["avreise"].dt.date >= filters["start_date"])
                    )
                )
            ]
        if filters.get("end_date"):
            filtered = filtered[filtered["ankomst"].dt.date <= filters["end_date"]]

    if filters.get("abonnement_type"):
        filtered = filtered[filtered["abonnement_type"].isin(filters["abonnement_type"])]

    return filtered

def filter_todays_bookings(bestillinger: pd.DataFrame) -> pd.DataFrame:
    """
    Filtrerer bestillinger for å vise dagens aktive bestillinger.
    
    Args:
        bestillinger (pd.DataFrame): DataFrame med alle bestillinger
        
    Returns:
        pd.DataFrame: Filtrerte bestillinger for dagens dato
    """
    if bestillinger.empty:
        logger.info("No bookings found to filter")
        return bestillinger
        
    try:
        today = pd.Timestamp.now(TZ).normalize()
        logger.info(f"Filtering bookings for date: {today}")
        
        # Lag en ny kopi av DataFrame for å unngå advarsler
        result = bestillinger.copy()
        
        # Sjekk at nødvendige kolonner eksisterer
        required_columns = ['abonnement_type', 'ankomst']
        if not all(col in result.columns for col in required_columns):
            logger.error("Missing required columns in DataFrame")
            return pd.DataFrame()
        
        # Opprett masker for hver betingelse
        friday_mask = (today.weekday() == 4)
        active_annual = (
            (result['abonnement_type'] == 'Årsabonnement') & 
            friday_mask
        )
        
        active_weekly = (
            (result['abonnement_type'] == 'Ukentlig ved bestilling') & 
            (result['ankomst'].dt.normalize() == today)
        )
        
        # Kombiner masker og filtrer
        result = result[active_annual | active_weekly].copy()
        
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
        ((bestillinger['ankomst'].dt.date >= current_date) & (bestillinger['ankomst'].dt.date <= end_date)) |
        # Bestillinger som allerede er aktive og fortsetter inn i neste uke
        ((bestillinger['ankomst'].dt.date < current_date) & 
         ((bestillinger['avreise'].isnull()) | (bestillinger['avreise'].dt.date >= current_date))) |
        # Årsabonnementer
        (bestillinger['abonnement_type'] == 'Årsabonnement')
    ]

# Visninger for tunbrøyting
def vis_tunbroyting_statistikk(bestillinger: pd.DataFrame) -> Optional[Dict[str, Any]]:
    if bestillinger.empty:
        logger.warning("Ingen data tilgjengelig for å vise statistikk.")
        return None

    bestillinger["ankomst_dato"] = pd.to_datetime(bestillinger["ankomst_dato"], errors="coerce")
    bestillinger["avreise_dato"] = pd.to_datetime(bestillinger["avreise_dato"], errors="coerce")

    daily_counts = bestillinger.groupby("ankomst_dato").size().reset_index(name="count")
    abonnement_counts = bestillinger["abonnement_type"].value_counts()
    rode_counts = bestillinger["rode"].value_counts() if "rode" in bestillinger.columns else None

    total_bestillinger = len(bestillinger)
    unike_brukere = bestillinger["bruker"].nunique()

    avg_stay = None
    if "avreise_dato" in bestillinger.columns and "ankomst_dato" in bestillinger.columns:
        bestillinger["opphold"] = (bestillinger["avreise_dato"] - bestillinger["ankomst_dato"]).dt.total_seconds() / (24 * 60 * 60)
        avg_stay = bestillinger["opphold"].mean()

    return {
        "daily_counts": daily_counts,
        "abonnement_counts": abonnement_counts,
        "rode_counts": rode_counts,
        "total_bestillinger": total_bestillinger,
        "unike_brukere": unike_brukere,
        "avg_stay": avg_stay,
    }

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
            bestillinger['rode'] = bestillinger['bruker'].apply(get_rode)
            
            # Endre kolonnenavn fra 'bruker' til 'Hytte'
            bestillinger = bestillinger.rename(columns={'bruker': 'Hytte'})
            
            # Sorter bestillinger etter rode og deretter hytte
            bestillinger_sortert = bestillinger.sort_values(['rode', 'Hytte'])
            
            st.subheader(f"Bestillinger for perioden {start_date} til {end_date}")
            
            # Velg kolonner som skal vises
            kolonner_a_vise = ['rode', 'Hytte']
            for kolonne in ['ankomst', 'avreise', 'ankomst_dato', 'avreise_dato', 'abonnement_type']:
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
    #st.subheader("Dagens tunbestillinger")
    bestillinger = hent_bestillinger()
    dagens_bestillinger = filter_todays_bookings(bestillinger)

    if not dagens_bestillinger.empty:
        # Lag en ny DataFrame for visning
        visnings_df = pd.DataFrame()
        
        # Legg til 'rode' informasjon
        visnings_df['rode'] = dagens_bestillinger['bruker'].apply(get_rode)
        
        # Kopier og rename kolonner
        visnings_df['hytte'] = dagens_bestillinger['bruker']
        visnings_df['abonnement_type'] = dagens_bestillinger['abonnement_type']
        
        # Formater dato og tid
        visnings_df['ankomst'] = dagens_bestillinger['ankomst'].dt.strftime('%Y-%m-%d %H:%M')
        visnings_df['avreise'] = dagens_bestillinger['avreise'].apply(
            lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notnull(x) else 'Ikke satt'
        )

        # Legg til en kolonne for status
        today = datetime.now(TZ).date()
        visnings_df['status'] = dagens_bestillinger.apply(
            lambda row: 'Ankommer i dag' if row['ankomst'].date() == today else 
                        ('Avreiser i dag' if pd.notnull(row['avreise']) and row['avreise'].date() == today else 
                         ('Aktiv' if row['abonnement_type'] == 'Årsabonnement' else 'Ikke aktiv')),
            axis=1
        )

        # Fjern rader med 'Ikke aktiv' status for "Ukentlig ved bestilling"
        visnings_df = visnings_df[~((visnings_df['abonnement_type'] == 'Ukentlig ved bestilling') & 
                                (visnings_df['status'] == 'Ikke aktiv'))]

        # Sorter dataframe
        visnings_df = visnings_df.sort_values(['rode', 'hytte'])

        # Vis dataframe i en ekspanderende seksjon
        with st.expander("Se liste med dagens bestillinger", expanded=False):
            st.dataframe(visnings_df)

        # Vis antall bestillinger
        st.info(f"Totalt antall aktive bestillinger for i dag: {len(visnings_df)}")
        
        # Vis oppsummering
        ankommer = visnings_df['status'].eq('Ankommer i dag').sum()
        avreiser = visnings_df['status'].eq('Avreiser i dag').sum()
        aktive = visnings_df['status'].eq('Aktiv').sum()
        st.write(f"Ankommer i dag: {ankommer}")
        st.write(f"Avreiser i dag: {avreiser}")
        st.write(f"Aktive opphold: {aktive}")
    else:
        st.info("Ingen bestillinger for i dag.")
        
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
    
    bestillinger = hent_bestillinger()
    print_dataframe_info(bestillinger, "Alle bestillinger")
    if bestillinger.empty:
        st.write("Ingen bestillinger å vise.")
        return

    # Vis dagens bestillinger
    vis_dagens_bestillinger()
    
    # Vis kart for dagens bestillinger
    dagens_bestillinger = filter_todays_bookings(bestillinger)
    print_dataframe_info(dagens_bestillinger, "Dagens bestillinger")
    fig_today = vis_dagens_tunkart(
        dagens_bestillinger, 
        st.secrets["mapbox"]["access_token"], 
        "Dagens tunbrøyting"
    )
    st.plotly_chart(fig_today, use_container_width=True, key="today_chart")
    st.write("---")
    
    # Vis aktive bestillinger kommende uke
    vis_tunbestillinger_for_periode()
    
    # Vis hytter med årsabonnement
    vis_arsabonnenter()
    
def vis_aktive_bestillinger():
    st.subheader("Aktive tunbestillinger")

    # Hent alle bestillinger
    bestillinger = hent_bestillinger()

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
    previous_bookings = hent_bruker_bestillinger(user_id)

    if not previous_bookings.empty:
        for _, booking in previous_bookings.iterrows():
            ankomst_dato = booking['ankomst_dato']
            avreise_dato = booking['avreise_dato']
            
            # Konverter til datetime hvis det er en streng
            if isinstance(ankomst_dato, str):
                ankomst_dato = datetime.strptime(ankomst_dato, '%Y-%m-%d').date()
            
            if isinstance(avreise_dato, str) and avreise_dato:
                avreise_dato = datetime.strptime(avreise_dato, '%Y-%m-%d').date()
            
            # Formater datoene
            ankomst_str = ankomst_dato.strftime('%d.%m.%Y') if ankomst_dato else ''
            avreise_str = avreise_dato.strftime('%d.%m.%Y') if avreise_dato else ''
            
            with st.expander(f"Bestilling - {ankomst_str}"):
                st.write(f"Ankomst: {ankomst_str}")
                if avreise_str:
                    st.write(f"Avreise: {avreise_str}")
                st.write(f"Type: {booking['abonnement_type']}")
    else:
        st.info("Du har ingen tidligere bestillinger.")

def vis_hyttegrend_aktivitet():
    """Viser oversikt over tunbrøytingsaktivitet for neste 7 dager."""
    try:
        st.subheader("Aktive tunbestillinger i hyttegrenda")
        st.info(
            "💡  Siktemålet er å være ferdig med tunbrøyting på fredager innen kl 15. "
            "Store snøfall, våt snø og/eller mange bestillinger, kan medføre forsinkelser."
        )
        
        alle_bestillinger = hent_bestillinger()
        if alle_bestillinger is None:
            logger.error("Kunne ikke hente bestillinger fra databasen")
            st.error("Det oppstod en feil ved henting av bestillinger. Vennligst prøv igjen senere.")
            return
            
        if alle_bestillinger.empty:
            st.info("Ingen bestillinger funnet for perioden.")
            return

        dagens_dato = pd.Timestamp.now(TZ).normalize()
        sluttdato = dagens_dato + pd.Timedelta(days=7)
        dato_range = pd.date_range(dagens_dato, sluttdato)

        # Opprett aktivitets-DataFrame med sikker konvertering
        try:
            df_aktivitet = pd.DataFrame(index=dato_range)
            df_aktivitet['dato_str'] = df_aktivitet.index.strftime('%d.%m')
            df_aktivitet['ukedag'] = df_aktivitet.index.strftime('%A').map({
                'Monday': 'Mandag', 'Tuesday': 'Tirsdag', 'Wednesday': 'Onsdag',
                'Thursday': 'Torsdag', 'Friday': 'Fredag', 'Saturday': 'Lørdag', 
                'Sunday': 'Søndag'
            })
            
            # Tell bestillinger per dag
            df_aktivitet['antall'] = 0
            for dato in dato_range:
                # Filter for årlige abonnementer på fredager
                if dato.weekday() == 4:  # Fredag
                    yearly_count = len(alle_bestillinger[
                        alle_bestillinger['abonnement_type'] == 'Årsabonnement'
                    ])
                else:
                    yearly_count = 0
                    
                # Filter for ukentlige bestillinger på denne datoen
                daily_count = len(alle_bestillinger[
                    (alle_bestillinger['abonnement_type'] == 'Ukentlig ved bestilling') & 
                    (alle_bestillinger['ankomst'].dt.normalize() == dato)
                ])
                
                df_aktivitet.loc[dato, 'antall'] = yearly_count + daily_count

            # Vis aktivitetsoversikt
            if df_aktivitet['antall'].sum() > 0:
                st.write("Oversikt over tunbrøytinger neste 7 dager:")
                
                # Formater visning
                df_display = df_aktivitet.copy()
                df_display['Dato'] = df_display['dato_str'] + ' (' + df_display['ukedag'] + ')'
                df_display = df_display[['Dato', 'antall']].rename(columns={'antall': 'Antall tun'})
                
                # Bruk st.dataframe med styling
                st.dataframe(
                    df_display.style.highlight_max(subset=['Antall tun'], color='lightgreen'),
                    hide_index=True
                )
                
                # Vis total
                st.write(f"Totalt antall tunbrøytinger i perioden: {df_aktivitet['antall'].sum()}")
            else:
                st.info("Ingen planlagte tunbrøytinger de neste 7 dagene.")
                
            # Legg til ekstra informasjon om fredager
            if df_aktivitet.loc[df_aktivitet.index[df_aktivitet.index.weekday == 4], 'antall'].sum() > 0:
                st.info("💡 På fredager brøytes alle tun med årsabonnement automatisk.")
                
        except Exception as e:
            logger.error(f"Feil ved behandling av bestillingsdata: {str(e)}", exc_info=True)
            st.error("Det oppstod en feil ved behandling av bestillingsdataene.")
            
    except Exception as e:
        logger.error(f"Feil i vis_hyttegrend_aktivitet: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved lasting av tunbrøytingsaktivitet. Vennligst prøv igjen senere.")

def get_bookings(start_date=None, end_date=None):
    """
    Henter tunbrøyting-bestillinger for en gitt periode.
    
    Args:
        start_date (datetime, optional): Startdato for filtreringen
        end_date (datetime, optional): Sluttdato for filtreringen
        
    Returns:
        pd.DataFrame: DataFrame med bestillinger
    """
    logger.info(f"Starting get_bookings with start_date={start_date}, end_date={end_date}")
    
    try:
        query = """
            SELECT id, bruker, ankomst_dato, ankomst_tid, 
                   avreise_dato, avreise_tid, abonnement_type 
            FROM tunbroyting_bestillinger
        """
        
        # Hent data fra databasen
        df = fetch_data('tunbroyting', query)
        
        if df is None or df.empty:
            logger.info("No bookings found")
            return pd.DataFrame(columns=[
                'id', 'bruker', 'ankomst_dato', 'ankomst_tid', 
                'avreise_dato', 'avreise_tid', 'abonnement_type',
                'ankomst', 'avreise'
            ])
            
        # Lag en ny DataFrame for å unngå SettingWithCopyWarning
        df = df.copy()
            
        # Konverter datoer med eksplisitt format og feilhåndtering
        for col in ['ankomst_dato', 'avreise_dato']:
            try:
                df[col] = pd.to_datetime(df[col], format='%Y-%m-%d', errors='coerce')
            except Exception as e:
                logger.error(f"Error converting {col}: {str(e)}")
                df[col] = pd.NaT
        
        # Filtrer på dato hvis spesifisert
        if start_date:
            df = df.loc[df['ankomst_dato'] >= start_date]
        if end_date:
            df = df.loc[df['ankomst_dato'] <= end_date]
        
        # Kombiner dato og tid med sikker tidssone-håndtering
        for col_pair in [('ankomst_dato', 'ankomst_tid', 'ankomst'), 
                        ('avreise_dato', 'avreise_tid', 'avreise')]:
            try:
                df[col_pair[2]] = pd.to_datetime(
                    df[col_pair[0]].dt.strftime('%Y-%m-%d') + ' ' + 
                    df[col_pair[1]].astype(str)
                ).dt.tz_localize('UTC').dt.tz_convert('Europe/Oslo')
            except Exception as e:
                logger.error(f"Error creating {col_pair[2]}: {str(e)}")
                df[col_pair[2]] = pd.NaT
        
        logger.info(f"Successfully retrieved {len(df)} bookings")
        return df
        
    except Exception as e:
        logger.error(f"Error in get_bookings: {str(e)}", exc_info=True)
        return pd.DataFrame(columns=[
            'id', 'bruker', 'ankomst_dato', 'ankomst_tid', 
            'avreise_dato', 'avreise_tid', 'abonnement_type',
            'ankomst', 'avreise'
        ])

