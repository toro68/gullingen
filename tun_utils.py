import sqlite3
import pandas as pd

from datetime import datetime, timedelta, time
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import base64
import streamlit as st

from constants import TZ
from util_functions import neste_fredag
from utils import is_active_booking
from customer_utils import get_customer_by_id, get_rode, load_customer_database
from map_utils import vis_dagens_tunkart, vis_kommende_tunbestillinger
from logging_config import get_logger

logger = get_logger(__name__)


def get_tunbroyting_connection() -> sqlite3.Connection:
    """
    Oppretter og returnerer en tilkobling til tunbrøyting-databasen.

    Returns:
        sqlite3.Connection: En tilkobling til tunbrøyting-databasen.
    """
    return sqlite3.connect("tunbroyting.db", check_same_thread=False)

def bestill_tunbroyting():
    st.title("Bestill Tunbrøyting")
    # Informasjonstekst
    st.info(
        """
    Tunbrøyting i Fjellbergsskardet - Vintersesongen 2024/2025

    Årsabonnement: 
    - Tunet ditt brøytes automatisk hver fredag ved behov, uten ekstra bestilling. 
    - Fleksibel brøyting andre dager: Mandag til torsdag og lørdag til søndag: Tunbrøyting utføres ved aktiv bestilling. 
    Merk: Brøytefirmaet rykker ikke ut for å brøyte enkelttun på disse dagene. 
    Du må legge inn bestilling for lørdag-torsdag for å være garantert brøyting. 
    - , eller deler av den (f.eks. januar, januar-februar, utleieperioder).
    
    
    - Aktiv bestilling: De som har årsabonnement og ønsker tunbrøyting alle dager det brøytes i hyttegrenda, må legge inn en bestilling for hele perioden
    fra 1. november til 1. mai. 
    Det er selvsagt også mulig å bestille hele januar, hele januar-februar, perioder når hytta leies ut, etc. 
    
    Ukentlig ved bestilling: 
    - Kun fredager tilgjengelig som brøytedag. Aktiv bestilling kreves for hver ønsket brøyting. 
    
    Brøytefirma utfører vedlikeholdsbrøyting for å unngå gjengroing når de ser behov for det.
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
    display_bookings(st.session_state.user_id)

    # Hent alle bestillinger og filtrer dem
    all_bestillinger = hent_bestillinger()
    start_date = naa.date()
    end_date = start_date + timedelta(days=7)  # Vis neste 30 dager
    filtered_bestillinger = filter_tunbroyting_bestillinger(all_bestillinger, {
        "start_date": start_date,
        "end_date": end_date,
    })

    # Vis daglige brøytinger
    vis_hyttegrend_aktivitet()

def lagre_bestilling(
    user_id: str,
    ankomst_dato: str,
    ankomst_tid: str,
    avreise_dato: str,
    avreise_tid: str,
    abonnement_type: str,
) -> bool:
    """
    Lagrer en ny tunbrøytingsbestilling i databasen.

    Args:
        user_id (str): Brukerens ID
        ankomst_dato (str): Ankomstdato i ISO-format
        ankomst_tid (str): Ankomsttid i HH:MM:SS-format
        avreise_dato (str): Avreisedato i ISO-format eller None
        avreise_tid (str): Avreisetid i HH:MM:SS-format eller None
        abonnement_type (str): Type abonnement

    Returns:
        bool: True hvis lagringen var vellykket, False ellers
    """
    try:
        with get_tunbroyting_connection() as conn:
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

def hent_bestillinger() -> pd.DataFrame:
    """
    Henter alle tunbrøytingsbestillinger fra databasen.

    Returns:
        pd.DataFrame: En DataFrame med alle bestillinger, eller en tom DataFrame hvis det oppstår en feil.
    """
    try:
        with get_tunbroyting_connection() as conn:
            query = "SELECT * FROM tunbroyting_bestillinger"
            df = pd.read_sql_query(query, conn)

        if df.empty:
            logger.warning("Ingen bestillinger funnet i databasen.")
            return pd.DataFrame()

        # Konverter dato- og tidskolonner
        for col in ["ankomst_dato", "avreise_dato"]:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        for col in ["ankomst_tid", "avreise_tid"]:
            df[col] = pd.to_datetime(
                df[col], format="%H:%M:%S", errors="coerce"
            ).dt.time

        # Kombiner dato og tid til datetime-objekter
        df["ankomst"] = df.apply(
            lambda row: (
                pd.Timestamp.combine(row["ankomst_dato"], row["ankomst_tid"])
                if pd.notnull(row["ankomst_dato"]) and pd.notnull(row["ankomst_tid"])
                else pd.NaT
            ),
            axis=1,
        )
        df["avreise"] = df.apply(
            lambda row: (
                pd.Timestamp.combine(row["avreise_dato"], row["avreise_tid"])
                if pd.notnull(row["avreise_dato"]) and pd.notnull(row["avreise_tid"])
                else pd.NaT
            ),
            axis=1,
        )

        # Sett tidssone
        for col in ["ankomst", "avreise"]:
            df[col] = df[col].dt.tz_localize(TZ, ambiguous="NaT", nonexistent="NaT")

        logger.info("Hentet %s bestillinger fra databasen.", len(df))
        return df

    except sqlite3.Error as e:
        logger.error("Database error ved henting av bestillinger: %s", str(e))
        return pd.DataFrame()
    except Exception as e:
        logger.error(
            "Uventet feil ved henting av bestillinger: %s", str(e), exc_info=True
        )
        return pd.DataFrame()

def hent_bruker_bestillinger(user_id):
    with get_tunbroyting_connection() as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE bruker = ? 
        ORDER BY ankomst_dato DESC, ankomst_tid DESC
        """
        df = pd.read_sql_query(query, conn, params=(user_id,))
    return df

def hent_bestillinger_for_periode(start_date, end_date):
    with get_tunbroyting_connection() as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE (ankomst_dato BETWEEN ? AND ?) OR (avreise_dato BETWEEN ? AND ?)
        ORDER BY ankomst_dato, ankomst_tid
        """
        df = pd.read_sql_query(
            query, conn, params=(start_date, end_date, start_date, end_date)
        )
    return df

def hent_dagens_bestillinger():
    today = datetime.now(TZ).date()
    with get_tunbroyting_connection() as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE date(ankomst_dato) = ? OR (date(ankomst_dato) <= ? AND date(avreise_dato) >= ?)
        """
        df = pd.read_sql_query(query, conn, params=(today, today, today))

    df["ankomst_dato"] = pd.to_datetime(df["ankomst_dato"])
    df["avreise_dato"] = pd.to_datetime(df["avreise_dato"])

    return df

def hent_aktive_bestillinger():
    today = datetime.now(TZ).date()
    with get_tunbroyting_connection() as conn:
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
        with get_tunbroyting_connection() as conn:
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

def count_bestillinger():
    try:
        with get_tunbroyting_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tunbroyting_bestillinger")
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Feil ved telling av bestillinger: {str(e)}")
        return 0

def get_max_bestilling_id():
    try:
        with get_tunbroyting_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(id) FROM tunbroyting_bestillinger")
            max_id = cursor.fetchone()[0]
            return max_id if max_id is not None else 0
    except Exception as e:
        logger.error("Feil ved henting av maksimum bestillings-ID: %s", str(e))
        return 0

def oppdater_bestilling(bestilling_id: int, nye_data: Dict[str, Any]) -> bool:
    """
    Oppdaterer en eksisterende tunbrøytingsbestilling i databasen.

    Args:
        bestilling_id (int): ID-en til bestillingen som skal oppdateres
        nye_data (Dict[str, Any]): En dictionary med de nye dataene for bestillingen

    Returns:
        bool: True hvis oppdateringen var vellykket, False ellers
    """
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
        with get_tunbroyting_connection() as conn:
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

def slett_bestilling(bestilling_id: int) -> bool:
    """
    Sletter en tunbrøytingsbestilling fra databasen.

    Args:
        bestilling_id (int): ID-en til bestillingen som skal slettes

    Returns:
        bool: True hvis slettingen var vellykket, False ellers
    """
    try:
        with get_tunbroyting_connection() as conn:
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

def get_booking_status(
    user_id: str, bestillinger: pd.DataFrame
) -> Tuple[Optional[str], Optional[pd.Timestamp]]:
    """
    Henter bestillingsstatus for en gitt bruker.

    Args:
        user_id (str): Brukerens ID
        bestillinger (pd.DataFrame): DataFrame med alle bestillinger

    Returns:
        Tuple[Optional[str], Optional[pd.Timestamp]]: 
        En tuple med abonnementstype og ankomstdato, eller (None, None) hvis ingen bestilling finnes
    """
    if user_id in bestillinger["bruker"].astype(str).values:
        booking = bestillinger[bestillinger["bruker"].astype(str) == str(user_id)].iloc[
            0
        ]
        return booking["abonnement_type"], booking["ankomst_dato"]
    return None, None

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
                    if oppdater_bestilling_i_database(bestilling_id, nye_data):
                        st.success(f"Bestilling {bestilling_id} er oppdatert!")
                    else:
                        st.error(
                            "Det oppstod en feil under oppdatering av bestillingen."
                        )
                else:
                    st.error("Ugyldig input. Vennligst sjekk datoene og prøv igjen.")
    else:
        st.warning(f"Ingen aktiv bestilling funnet med ID {bestilling_id}")

def validere_bestilling(data):
    if data["avreise_dato"] is None or data["avreise_tid"] is None:
        return True  # Hvis avreisedato eller -tid ikke er satt, er bestillingen gyldig

    ankomst = datetime.combine(data["ankomst_dato"], data["ankomst_tid"])
    avreise = datetime.combine(data["avreise_dato"], data["avreise_tid"])

    return avreise > ankomst

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
    # st.header("Rediger bestilling")
    vis_rediger_bestilling()

    # Slett bestilling
    st.header("Slett bestilling")

    slett_metode = st.radio(
        "Velg slettingsmetode:",
        ["Slett etter ID", "Slett etter brukernavn", "Slett etter datoperiode"],
        key="slett_metode",
    )

    if slett_metode == "Slett etter ID":
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

    elif slett_metode == "Slett etter brukernavn":
        slett_bruker = st.text_input(
            "Skriv inn brukernavn for å slette alle bestillinger fra brukeren",
            key="slett_bruker",
        )
        if st.button("Slett bestillinger", key="slett_bruker_button"):
            antall_slettet = slett_bestillinger_for_bruker(slett_bruker)
            if antall_slettet > 0:
                st.success(
                    f"{antall_slettet} bestilling(er) for bruker {slett_bruker} er slettet."
                )
            else:
                st.warning(f"Ingen bestillinger funnet for bruker {slett_bruker}.")

    elif slett_metode == "Slett etter datoperiode":
        col1, col2 = st.columns(2)
        with col1:
            slett_dato_fra = st.date_input(
                "Slett bestillinger fra dato", key="slett_dato_fra"
            )
        with col2:
            slett_dato_til = st.date_input(
                "Slett bestillinger til dato", key="slett_dato_til"
            )
        if st.button("Slett bestillinger", key="slett_dato_button"):
            antall_slettet = slett_bestillinger_for_periode(
                slett_dato_fra, slett_dato_til
            )
            if antall_slettet > 0:
                st.success(
                    f"{antall_slettet} bestilling(er) i perioden {slett_dato_fra} til {slett_dato_til} er slettet."
                )
            else:
                st.warning(
                    f"Ingen bestillinger funnet i perioden {slett_dato_fra} til {slett_dato_til}."
                )

    # # Vis aktive bestillinger
    # st.header("Aktive bestillinger")
    # vis_aktive_bestillinger()

# Visninger for tunbrøyting

def filter_todays_bookings(bestillinger):
    today = datetime.now(TZ).date()
    return bestillinger[
        (bestillinger['ankomst'].dt.date == today) |
        ((bestillinger['ankomst'].dt.date <= today) & (bestillinger['avreise'].dt.date >= today)) |
        ((bestillinger['abonnement_type'] == 'Årsabonnement') & (today.weekday() == 4))  # Fredag
    ]

def filter_bookings_for_period(bestillinger, start_date, end_date):
    return bestillinger[
        ((bestillinger['ankomst'].dt.date >= start_date) & (bestillinger['ankomst'].dt.date <= end_date)) |
        ((bestillinger['ankomst'].dt.date <= end_date) & (bestillinger['avreise'].dt.date >= start_date)) |
        (bestillinger['abonnement_type'] == 'Årsabonnement')
    ]

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

def vis_daglige_broytinger(bestillinger, start_date, end_date):
    if bestillinger.empty:
        st.write("Ingen data tilgjengelig for å vise daglige brøytinger.")
        return

    # Konverter 'ankomst_dato' til datetime hvis det ikke allerede er det, og så til date
    bestillinger["ankomst_dato"] = pd.to_datetime(bestillinger["ankomst_dato"], errors="coerce").dt.date

    # Hent alle unike brukere med årsabonnement
    yearly_subscribers = bestillinger[bestillinger["abonnement_type"] == "Årsabonnement"]["bruker"].unique()

    # Opprett en datoindeks for hele perioden
    date_index = pd.date_range(start=start_date, end=end_date, freq='D')

    # Initialiser en DataFrame for alle datoer
    all_dates_df = pd.DataFrame(index=date_index.date, columns=['antall'])
    all_dates_df['antall'] = 0

    # Teller bestillinger per dag
    daily_counts = bestillinger.groupby("ankomst_dato").size()

    # Legg til daglige tellinger og årlige abonnenter
    for date in date_index:
        date = date.date()
        if date in daily_counts.index:
            all_dates_df.loc[date, 'antall'] += daily_counts[date]
        
        if date.weekday() == 4 and (date.month >= 11 or date.month <= 4):  # Fredag i vintersesongen
            all_dates_df.loc[date, 'antall'] += len(yearly_subscribers)

    # Opprett et søylediagram
    fig = px.bar(
        all_dates_df.reset_index(),
        x="index",
        y="antall",
        title="Oversikt over aktive bestillinger",
        labels={"index": "Dato", "antall": "Antall brøytinger"},
    )

    # Oppdater layout for bedre lesbarhet
    fig.update_layout(hovermode="x unified")
    fig.update_traces(hovertemplate="Dato: %{x}<br>Antall brøytinger: %{y}")

    # Vis grafen
    st.plotly_chart(fig)

    # # Vis dataene i en tabell i en kollapsbar seksjon
    # with st.expander("Vis antallet bestilinger i valgt periode i tabellform", expanded=False):
    #     st.dataframe(all_dates_df.reset_index().rename(columns={"index": "Dato"}))

    # # Legg til debugging informasjon
    # st.write("Debugging informasjon:")
    # st.write(f"Start dato: {start_date}, Slutt dato: {end_date}")
    # st.write(f"Antall bestillinger: {len(bestillinger)}")
    # st.write(f"Unike ankomstdatoer: {bestillinger['ankomst_dato'].nunique()}")
    # st.write(f"Daglige tellinger:\n{daily_counts}")
    # st.write(f"Ankomstdatoer:\n{bestillinger['ankomst_dato'].value_counts().sort_index()}")# Oppdatert hovedfunksjon

def vis_tunbroyting_oversikt():
    st.title("Oversikt over tunbestillinger")
    st.info(
        """
        Retningslinjer for brøytefirma:
        - Mandag-torsdag brøytes tun ifm nødvendig brøyting av veinettet. (Unntaket er juleferie, vinterferie, påske.)         
        - Gjennomgå dagens brøyteordre opp mot ordrer for de kommende dagene. 
        Hvis værmeldingen tilsier at det ikke blir veibrøyting kommende dager, vurder å brøyte alle bestilte tun samtidig.
        - Fredager er hoveddag for tunbrøyting. Dere kan framskynde og rydde tun fra torsdag 
        hvis værmeldingen tilsier stabilt vær fram til helgen.
        - Vedlikeholdsbrøyting kan utføres ved behov i alle tun. Legg ut driftsmelding (varsel) hvis dette gjøres.
        """
        )
    bestillinger = hent_bestillinger()

    if bestillinger.empty:
        st.write("Ingen bestillinger å vise.")
        return

    # Add rode information to bestillinger
    bestillinger['rode'] = bestillinger['bruker'].apply(get_rode)

    current_date = datetime.now(TZ).date()
    end_date = current_date + timedelta(days=7)

    # Vis dagens bestillinger
    st.subheader("Dagens bestillinger")
    dagens_bestillinger = filter_todays_bookings(bestillinger)
    with st.expander("Se liste med dagens bestillinger", expanded=False):
        st.dataframe(dagens_bestillinger.sort_values(['rode', 'bruker']))

    # Vis kart for dagens bestillinger
    fig_today = vis_dagens_tunkart(
        dagens_bestillinger, st.secrets["mapbox"]["access_token"], "Dagens tunbrøyting"
    )
    st.plotly_chart(fig_today, use_container_width=True)

    # Vis aktive bestillinger kommende uke
    st.subheader("Aktive bestillinger kommende uke")
    kommende_uke_bestillinger = filter_bookings_for_period(bestillinger, current_date, end_date)
    with st.expander("Se aktive bestillinger kommende uke", expanded=False):
        st.dataframe(kommende_uke_bestillinger.sort_values(['rode', 'bruker']))

    # Vis kart for aktive bestillinger kommende uke
    fig_coming_week = vis_kommende_tunbestillinger(
        kommende_uke_bestillinger,
        st.secrets["mapbox"]["access_token"],
        f"Kommende tunbrøyting",
    )
    st.plotly_chart(fig_coming_week, use_container_width=True)

    # Periodevelger
    st.subheader("Velg periode for visning av aktive bestillinger")
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=current_date, key="start_date")
    with col2:
        end_date = st.date_input("Til dato", value=end_date, key="end_date")

    # Filtrer bestillinger basert på valgt periode
    filtered_bestillinger = filter_bookings_for_period(bestillinger, start_date, end_date)

    # Vis aktive bestillinger i valgt periode
    st.subheader(f"Aktive bestillinger ({start_date} - {end_date})")
    sorted_filtered_bestillinger = filtered_bestillinger.sort_values(['rode', 'bruker'])
    st.dataframe(sorted_filtered_bestillinger)

    # Knapp for å laste ned CSV
    if st.button("Last ned bestillinger som CSV"):
        csv = sorted_filtered_bestillinger.to_csv(index=False)
        b64 = base64.b64encode(csv.encode()).decode()
        href = f'<a href="data:file/csv;base64,{b64}" download="tunbroyting_bestillinger_{start_date}_{end_date}.csv">Last ned CSV-fil</a>'
        st.markdown(href, unsafe_allow_html=True)

def vis_aktive_bestillinger():
    st.subheader("Oversikt over aktive tunbrøytingsbestillinger")

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

def display_bookings(user_id):
    previous_bookings = hent_bruker_bestillinger(user_id)

    if not previous_bookings.empty:
        for _, booking in previous_bookings.iterrows():
            with st.expander(f"Bestilling - {booking['ankomst_dato']}"):
                st.write(f"Ankomst: {booking['ankomst_dato']} {booking['ankomst_tid']}")
                if pd.notnull(booking["avreise_dato"]):
                    st.write(
                        f"Avreise: {booking['avreise_dato']} {booking['avreise_tid']}"
                    )
                st.write(f"Type: {booking['abonnement_type']}")
    else:
        st.info("Du har ingen tidligere bestillinger.")

#Visning til brukerne for å vise statistikk og aktivitet i hyttegrenda - på siden for bestillinger av tunbrøyting

def vis_hyttegrend_aktivitet():
    st.subheader("Aktive bestillinger av tunbrøyting per dag i hyttegrenda")
    st.info("Siktemålet er å være ferdig med tunbrøyting på fredager innen kl 15. Store snøfall og/eller mange bestillinger, kan medføre forsinkelser.")
    
    # Hent alle bestillinger
    alle_bestillinger = hent_bestillinger()

    if alle_bestillinger.empty:
        st.info("Ingen bestillinger funnet for perioden.")
        return

    # Definer datoperioden
    dagens_dato = datetime.now(TZ).date()
    sluttdato = dagens_dato + timedelta(days=7)

    # Initialiser en dictionary for å telle aktive bestillinger per dag
    daglig_aktivitet = {dagen.date(): {'Ukentlig ved bestilling': 0, 'Årsabonnement': 0} 
                        for dagen in pd.date_range(dagens_dato, sluttdato)}

    # Tell aktive bestillinger for hver dag
    for _, bestilling in alle_bestillinger.iterrows():
        ankomst_dato = bestilling['ankomst'].date()
        if bestilling['abonnement_type'] == 'Ukentlig ved bestilling':
            # For 'Ukentlig ved bestilling', tell kun for ankomstdatoen hvis den er innenfor perioden
            if ankomst_dato in daglig_aktivitet:
                daglig_aktivitet[ankomst_dato]['Ukentlig ved bestilling'] += 1
        else:  # 'Årsabonnement'
            # For 'Årsabonnement', tell for hver dag fra ankomst til avreise (eller sluttdato) innenfor perioden
            avreise_dato = bestilling['avreise'].date() if pd.notnull(bestilling['avreise']) else sluttdato
            for dag in pd.date_range(max(ankomst_dato, dagens_dato), min(avreise_dato, sluttdato)):
                if dag.date() in daglig_aktivitet:
                    daglig_aktivitet[dag.date()]['Årsabonnement'] += 1

    # Legg til de 37 årsabonnementene på fredager
    for dag in daglig_aktivitet.keys():
        if dag.weekday() == 4:  # Fredag
            daglig_aktivitet[dag]['Årsabonnement'] = max(daglig_aktivitet[dag]['Årsabonnement'], 37)

    # Konverter til DataFrame for enklere visning
    aktivitet_df = pd.DataFrame.from_dict(daglig_aktivitet, orient='index')
    aktivitet_df['Totalt'] = aktivitet_df['Ukentlig ved bestilling'] + aktivitet_df['Årsabonnement']
    aktivitet_df.index.name = 'Dato'

    # Vis daglig aktivitet som tabell
    st.table(aktivitet_df)

    # Vis daglig aktivitet som stolpediagram (kun totalen)
    fig, ax = plt.subplots(figsize=(10, 6))
    aktivitet_df['Totalt'].plot(kind='bar', ax=ax)
    ax.set_xlabel('Dato')
    ax.set_ylabel('Totalt antall bestillinger')
    plt.xticks(rotation=45)
    plt.tight_layout()
    st.pyplot(fig)

    # Beregn og vis antall unike brukere
    unike_brukere = alle_bestillinger['bruker'].nunique()
    st.subheader("Antall unike brukere med bestillinger")
    st.write(f"{unike_brukere} unike brukere har aktive bestillinger i denne perioden.")
