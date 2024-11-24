import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Any, Dict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.core.config import (
    TZ,
    DATE_FORMATS,
    get_date_format,
    get_current_time,
    get_date_range_defaults,
    DATE_VALIDATION,
    safe_to_datetime,
    format_date,
    combine_date_with_tz,
    normalize_datetime,
    convert_for_db,
    parse_date
)
from utils.core.logging_config import get_logger
from utils.core.util_functions import neste_fredag
from utils.core.validation_utils import validere_bestilling
from utils.db.db_utils import (
    get_db_connection,
    verify_tunbroyting_database
)
from utils.services.map_utils import vis_dagens_tunkart, vis_broytekart, verify_map_configuration, debug_map_data
from utils.services.customer_utils import (
    customer_edit_component,
    get_customer_by_id,
    get_rode,
    load_customer_database,
    vis_arsabonnenter,
)

logger = get_logger(__name__)


# CREATE - hovedfunksjon i app.py
def bestill_tunbroyting():
    try:
        st.title("Bestill Tunbrøyting")
        
        # Verifiser database tidlig
        if not verify_tunbroyting_database():
            logger.error("Kunne ikke verifisere tunbrøyting database")
            st.error("Det oppstod en feil med databasen. Vennligst prøv igjen senere.")
            return
            
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
                    avreise_dato.isoformat() if avreise_dato else None,
                    abonnement_type
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
    avreise_dato: str = None,
    abonnement_type: str = "Ukentlig ved bestilling"
) -> bool:
    try:
        # Verifiser database først
        if not verify_tunbroyting_database():
            logger.error("Kunne ikke verifisere tunbrøyting database")
            return False
            
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

            if not all([customer_id, ankomst_dato, abonnement_type]):
                logger.error("Manglende påkrevde felter i bestilling")
                return False

            query = """
            INSERT INTO tunbroyting_bestillinger 
            (customer_id, ankomst_dato, avreise_dato, abonnement_type)
            VALUES (?, ?, ?, ?)
            """

            cursor.execute(
                query,
                (
                    str(customer_id),
                    str(ankomst_dato),
                    str(avreise_dato) if avreise_dato else None,
                    str(abonnement_type)
                )
            )
            conn.commit()
            return True

    except Exception as e:
        logger.error(f"Feil ved lagring av bestilling: {str(e)}")
        return False


# READ
def hent_bruker_bestillinger(customer_id):
    """Henter brukerens bestillinger"""
    try:
        with get_db_connection("tunbroyting") as conn:
            query = """
            SELECT DISTINCT * FROM tunbroyting_bestillinger 
            WHERE customer_id = ? 
            ORDER BY ankomst_dato DESC
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
            SELECT id, customer_id, ankomst_dato, 
                   avreise_dato, abonnement_type
            FROM tunbroyting_bestillinger 
            WHERE 
                (
                    (abonnement_type != 'Årsabonnement' AND
                     ankomst_dato >= ? AND ankomst_dato <= ?)
                    OR
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
    try:
        dato_dt = normalize_datetime(dato)
        logger.info(f"Normalisert dato for filtrering: {dato_dt}")
            
        alle_bestillinger = get_bookings()
        logger.info(f"Totalt antall bestillinger hentet: {len(alle_bestillinger)}")
            
        # Konverter datokolonner til datetime med tidssone
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in alle_bestillinger.columns:
                alle_bestillinger[col] = pd.to_datetime(alle_bestillinger[col]).dt.tz_localize(TZ)

        # Filtrer bestillinger - endret logikk her
        aktive_bestillinger = alle_bestillinger[
            # Årsabonnement som er aktive i dag (ikke utløpt)
            (
                (alle_bestillinger['abonnement_type'] == 'Årsabonnement') &
                (alle_bestillinger['ankomst_dato'].dt.date <= dato_dt.date()) &
                (
                    alle_bestillinger['avreise_dato'].isna() |
                    (alle_bestillinger['avreise_dato'].dt.date >= dato_dt.date())
                )
            ) |
            # Ukentlige bestillinger som er aktive i dag
            (
                (alle_bestillinger['abonnement_type'] == 'Ukentlig ved bestilling') &
                (alle_bestillinger['ankomst_dato'].dt.date <= dato_dt.date()) &
                (
                    alle_bestillinger['avreise_dato'].isna() |
                    (alle_bestillinger['avreise_dato'].dt.date >= dato_dt.date())
                )
            )
        ]
        
        logger.info(f"=== Resultat ===")
        logger.info(f"Filtrerte bestillinger for {dato_dt.date()}:")
        logger.info(f"Antall funnet: {len(aktive_bestillinger)}")
        logger.info(f"Filtrerte data:\n{aktive_bestillinger.to_string()}")
        
        return aktive_bestillinger
        
    except Exception as e:
        logger.error(f"Feil i hent_aktive_bestillinger_for_dag: {str(e)}", exc_info=True)
        return pd.DataFrame()

# filtrerer bestillinger i bestill_tunbroyting
def filter_todays_bookings(bookings_df: pd.DataFrame) -> pd.DataFrame:
    """
    Filtrerer bestillinger for å finne dagens aktive bestillinger.
    Inkluderer bestillinger der:
    - ankomst_dato er i dag eller tidligere
    - avreise_dato er i dag eller senere (eller er None/null)
    """
    try:
        logger.info("Starter filtrering av dagens bestillinger")
        
        if bookings_df.empty:
            return bookings_df
            
        # Konverter dagens dato til tz-aware datetime ved midnatt
        dagens_dato = normalize_datetime(datetime.now(TZ))
        
        # Konverter datokolonner til tz-aware datetime
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in bookings_df.columns:
                bookings_df[col] = pd.to_datetime(bookings_df[col]).dt.tz_localize(TZ)

        # Filtrer bestillinger
        mask = (
            (bookings_df['ankomst_dato'] <= dagens_dato) & 
            ((bookings_df['avreise_dato'].isna()) | 
             (bookings_df['avreise_dato'] >= dagens_dato))
        )
        
        filtered_df = bookings_df[mask].copy()
        
        logger.info(f"Dagens aktive bestillinger: {filtered_df}")
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
            # Bestillinger som starter i kommende uke
            (
                (bestillinger["ankomst_dato"].dt.tz_convert(TZ) >= current_date) & 
                (bestillinger["ankomst_dato"].dt.tz_convert(TZ) <= end_date)
            )
            |
            # Pågående bestillinger
            (
                (bestillinger["ankomst_dato"].dt.tz_convert(TZ) < current_date) &
                (
                    (bestillinger["avreise_dato"].isnull()) |
                    (bestillinger["avreise_dato"].dt.tz_convert(TZ) >= current_date)
                )
            )
            |
            # Årsabonnement bestillinger
            (bestillinger["abonnement_type"] == "Årsabonnement")
        )
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

# Kategori: View Functions
# liste for tunkart-siden
def vis_dagens_bestillinger():
    """Viser dagens aktive bestillinger i en tabell"""
    dagens_dato = get_current_time().date()  # Bruker config.py funksjon
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
            
            # Formater dato og tid med config.py funksjoner
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
        
        # Legg til kartvisning her
        st.subheader(f"Tunbrøytingskart for {format_date(current_time, 'display', 'date')}")
        vis_dagens_tunkart(
            dagens_bestillinger,
            mapbox_token=mapbox_token,
            title=f"Tunbrøyting {format_date(current_time, 'display', 'date')}"
        )
        
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
        default_start, default_end = get_date_range_defaults()
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Fra dato",
                value=default_start,  # Nå er dette allerede en date
                min_value=datetime.now(TZ).date() - timedelta(days=DATE_VALIDATION["default_date_range"]),
                max_value=datetime.now(TZ).date() + timedelta(days=DATE_VALIDATION["max_future_booking"]),
                format=get_date_format("display", "date").replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
            )
        
        with col2:
            end_date = st.date_input(
                "Til dato",
                value=default_end,  # Nå er dette allerede en date
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

def vis_hyttegrend_aktivitet():
    try:
        st.subheader("Aktive tunbestillinger i hyttegrenda")
        st.info(
            "💡  Siktemålet er å være ferdig med tunbrøyting på fredager innen kl 15. "
            "Store snøfall, våt snø og/eller mange bestillinger, kan medføre forsinkelser."
        )
        
        # Verifiser database først
        if not verify_tunbroyting_database():
            logger.error("Kunne ikke verifisere tunbrøyting database")
            st.error("Kunne ikke laste aktivitetsoversikt på grunn av databasefeil")
            return None
            
        alle_bestillinger = get_bookings()
        if alle_bestillinger.empty:
            st.info("Ingen bestillinger funnet for perioden.")
            return

        # Konverter datoer til datetime med tidssone
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in alle_bestillinger.columns:
                alle_bestillinger[col] = alle_bestillinger[col].apply(safe_to_datetime)
        
        start_date, end_date = get_date_range_defaults()
        if isinstance(start_date, date):
            start_date = datetime.combine(start_date, datetime.min.time())
        if isinstance(end_date, date):
            end_date = datetime.combine(end_date, datetime.min.time())
            
        dato_range = pd.date_range(
            start=start_date,
            end=end_date,
            freq='D'
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
        
        # Verifiser database først
        if not verify_tunbroyting_database():
            logger.error("Kunne ikke verifisere tunbrøyting database")
            return pd.DataFrame()

        with get_db_connection("tunbroyting") as conn:
            query = """
            SELECT DISTINCT 
                id, 
                customer_id,
                ankomst_dato,
                avreise_dato,
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

            # Logg spørringen og parametrene
            logger.info(f"SQL Query: {query}")
            logger.info(f"Parameters: {params}")

            df = pd.read_sql_query(query, conn, params=params)
            
            # Logg resultatet
            logger.info(f"Query returned {len(df)} rows")
            if not df.empty:
                logger.info(f"First row: {df.iloc[0].to_dict()}")
            
            return df

    except Exception as e:
        logger.error(f"Error in get_bookings: {str(e)}", exc_info=True)
        return pd.DataFrame()
