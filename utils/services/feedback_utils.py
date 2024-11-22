# feedback_utils.py

"""
Dependencies:
- Database: feedback
- Related modules: 
  - utils.services.feedback_utils
  - utils.services.alert_utils
- Shared tables:
  - feedback
"""

from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.core.config import (
    TZ,
    DATE_FORMATS,
    get_date_format,
    get_current_time,
    DATE_VALIDATION
)
from utils.core.logging_config import get_logger
from utils.db.db_utils import execute_query, fetch_data, get_db_connection
from utils.services.stroing_utils import log_stroing_activity

logger = get_logger(__name__)

FEEDBACK_ICONS = {
    "Føreforhold": "🚗",
    "Parkering": "🅿️",
    "Fasilitet": "🏠",
    "Annet": "❓",
}

# hjelpefunksjoner
def safe_to_datetime(date_string):
    if date_string in [None, "", "None", "1"]:
        return None
    try:
        return pd.to_datetime(date_string)
    except ValueError:
        logger.error(f"Ugyldig datostreng: '{date_string}'")
        return None

def format_date(date_obj):
    if date_obj is None:
        return "Ikke satt"
    return date_obj.strftime("%d.%m.%Y %H:%M")

def get_date_range_input(default_days=DATE_VALIDATION["default_date_range"]):
    """Felles funksjon for datovelgere"""
    try:
        logger.debug("Starting get_date_range_input")
        today = get_current_time().date()
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Fra dato", 
                value=today - timedelta(days=default_days),
                format=get_date_format("display", "date").replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
            )
        with col2:
            end_date = st.date_input(
                "Til dato",
                value=today,
                format=get_date_format("display", "date").replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD"),
                max_value=today
            )
            
        if start_date > end_date:
            st.error("Fra-dato kan ikke være senere enn til-dato")
            return None, None
            
        logger.debug(f"Valgt periode: {start_date} til {end_date}")
        return start_date, end_date
        
    except Exception as e:
        logger.error(f"Feil i get_date_range_input: {str(e)}", exc_info=True)
        return None, None
# crud-operasjoner
def save_feedback(feedback_type, datetime_str, comment, customer_id, hidden):
    """
    Lagrer feedback i databasen.
    
    Args:
        feedback_type (str): Type tilbakemelding
        datetime_str (str): Dato og tid i ISO-format
        comment (str): Kommentartekst
        customer_id (str): Hytte-ID
        hidden (bool): Om feedbacken skal være skjult
    """
    try:
        query = """INSERT INTO feedback (type, datetime, comment, customer_id, status, status_changed_at, hidden) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)"""
        initial_status = "Ny"
        params = (
            feedback_type,
            datetime_str,
            comment,
            customer_id,
            initial_status,
            datetime.now(TZ).isoformat(),
            hidden,
        )

        execute_query("feedback", query, params)

        logger.info(
            f"Feedback saved successfully: {feedback_type}, {datetime_str}, Customer: {customer_id}, hidden: {hidden}"
        )
        return True
    except Exception as e:
        logger.error(f"Error saving feedback: {str(e)}", exc_info=True)
        return False


def get_feedback(start_date=None, end_date=None, include_hidden=False, customer_id=None):
    """
    Henter feedback fra databasen.
    
    Args:
        start_date (datetime, optional): Startdato for filtrering
        end_date (datetime, optional): Sluttdato for filtrering
        include_hidden (bool): Om skjulte elementer skal inkluderes
        customer_id (str, optional): Filtrer på spesifikk hytte-ID
    """
    try:
        with get_db_connection("feedback") as conn:
            base_query = """
                SELECT * FROM feedback 
                WHERE (hidden = 0 OR ? = 1)
            """
            params = [1 if include_hidden else 0]
            
            if customer_id:
                base_query += " AND customer_id = ?"
                params.append(customer_id)
            
            if start_date and end_date:
                base_query += " AND datetime BETWEEN ? AND ?"
                params.extend([start_date.isoformat(), end_date.isoformat()])
            
            base_query += " ORDER BY datetime DESC"
            
            logger.debug(f"SQL Query: {base_query}")
            logger.debug(f"Parameters: {params}")
            
            df = pd.read_sql_query(base_query, conn, params=params)
            return handle_user_feedback(df)
            
    except Exception as e:
        logger.error(f"Error in get_feedback: {str(e)}")
        return pd.DataFrame()


def update_feedback_status(feedback_id, new_status, changed_by, new_expiry=None, new_display=None, new_target=None):
    """
    Oppdaterer status og andre felter for en feedback/varsel.
    
    Args:
        feedback_id (int): ID til feedbacken som skal oppdateres
        new_status (str): Ny status
        changed_by (str): Bruker-ID til den som gjorde endringen
        new_expiry (str, optional): Ny utløpsdato i ISO format
        new_display (bool, optional): Om varselet skal vises på værsiden
        new_target (str, optional): Ny målgruppe (kommaseparert streng)
    """
    try:
        query = """UPDATE feedback 
                   SET status = ?, 
                       status_changed_by = ?, 
                       status_changed_at = ?"""
        params = [new_status, changed_by, datetime.now(TZ).isoformat()]
        
        if new_expiry is not None:
            query += ", expiry_date = ?"
            params.append(new_expiry)
            
        if new_display is not None:
            query += ", display_on_weather = ?"
            params.append(1 if new_display else 0)
            
        if new_target is not None:
            query += ", target_group = ?"
            params.append(new_target)
            
        query += " WHERE id = ?"
        params.append(feedback_id)

        execute_query("feedback", query, params)
        logger.info(f"Status updated for feedback {feedback_id}: {new_status}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating feedback status: {str(e)}", exc_info=True)
        return False


def delete_feedback(feedback_id):
    try:
        query = "DELETE FROM feedback WHERE id = ?"
        result = execute_query("feedback", query, (feedback_id,))

        # Check if result is an integer (number of affected rows)
        if isinstance(result, int):
            if result > 0:
                logger.info(f"Deleted feedback with id: {feedback_id}")
                return True
            else:
                logger.warning(f"No feedback found with id: {feedback_id}")
                return "not_found"
        # If result is not an integer, assume it's a cursor-like object
        elif hasattr(result, "rowcount"):
            if result.rowcount > 0:
                logger.info(f"Deleted feedback with id: {feedback_id}")
                return True
            else:
                logger.warning(f"No feedback found with id: {feedback_id}")
                return "not_found"
        else:
            logger.warning(
                f"Unexpected result type when deleting feedback with id: {feedback_id}"
            )
            return False
    except Exception as e:
        logger.error(f"Error deleting feedback with id {feedback_id}: {str(e)}")
        return False


def display_feedback_dashboard():
    """Viser feedback-dashboard for administratorer"""
    try:
        logger.info("=== Starting display_feedback_dashboard ===")
        st.subheader("Feedback Dashboard")

        # Default datoer hvis ikke annet er valgt
        default_start = datetime.now(TZ) - timedelta(days=30)
        default_end = datetime.now(TZ)
        
        # Dato-velgere
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Fra dato",
                value=default_start.date(),
                key="feedback_start_date"
            )
            logger.debug(f"Valgt startdato: {start_date}")
            
        with col2:
            end_date = st.date_input(
                "Til dato",
                value=default_end.date(),
                key="feedback_end_date"
            )
            logger.debug(f"Valgt sluttdato: {end_date}")

        # Konverter til datetime med tidssone
        start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
        end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)
        
        logger.info(f"Henter feedback for periode: {start_datetime} til {end_datetime}")
        
        # Hent feedback data
        feedback_data = get_feedback(
            start_date=start_datetime,
            end_date=end_datetime,
            include_hidden=st.checkbox("Vis skjult feedback", value=False)
        )
        
        logger.debug(f"Hentet {len(feedback_data) if not feedback_data.empty else 0} feedback-elementer")

        if feedback_data.empty:
            st.warning(f"Ingen feedback-data tilgjengelig for perioden {start_date} til {end_date}")
            return

        # Vis statistikk
        st.info(f"Totalt {len(feedback_data)} feedback-elementer for perioden")
        
        # Vis filtrering - bruk direkte status-strenger
        status_filter = st.multiselect(
            "Filtrer på status:",
            options=['Ny', 'Under behandling', 'Løst', 'Avvist'],
            default=['Ny', 'Under behandling']
        )
        
        if status_filter:
            feedback_data = feedback_data[feedback_data['status'].isin(status_filter)]
            logger.debug(f"Filtrert til {len(feedback_data)} elementer basert på status")

        # Vis data i tabellform
        if not feedback_data.empty:
            st.write("### Feedback oversikt")
            
            # Formater datetime for visning
            display_data = feedback_data.copy()
            display_data['datetime'] = display_data['datetime'].dt.strftime('%d.%m.%Y %H:%M')
            
            # Vis tabell
            st.dataframe(
                display_data[[
                    'datetime', 'type', 'comment', 'status', 
                    'customer_id', 'status_changed_at'
                ]],
                use_container_width=True
            )
            
            # Last ned knapp
            csv = feedback_data.to_csv(index=False)
            st.download_button(
                label="Last ned som CSV",
                data=csv,
                file_name=f"feedback_data_{start_date}_{end_date}.csv",
                mime="text/csv",
            )

    except Exception as e:
        logger.error(f"Feil i display_feedback_dashboard: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av feedback dashboard. Sjekk loggene for detaljer.")


def handle_user_feedback(feedback_data: pd.DataFrame = None) -> pd.DataFrame:
    """
    Håndterer bruker-feedback data i samsvar med databaseskjema.
    """
    try:
        if feedback_data is None:
            feedback_data = get_feedback()
            
        if feedback_data.empty:
            return feedback_data
            
        # Konverter datetime-kolonner fra TEXT til datetime
        datetime_columns = ['datetime', 'status_changed_at', 'expiry_date']
        for col in datetime_columns:
            if col in feedback_data.columns and not feedback_data[col].empty:
                # Konverter fra databasens tekstformat til datetime
                feedback_data[col] = pd.to_datetime(
                    feedback_data[col],
                    format=DATE_FORMATS["database"]["datetime"],
                    errors='coerce'
                )
                
                # Hvis kolonnen ikke har tidssone, legg til
                if feedback_data[col].dt.tz is None:
                    feedback_data[col] = feedback_data[col].dt.tz_localize(TZ)
                else:
                    # Hvis kolonnen allerede har tidssone, konverter til riktig
                    feedback_data[col] = feedback_data[col].dt.tz_convert(TZ)
        
        # Sorter etter datetime
        feedback_data = feedback_data.sort_values('datetime', ascending=False)
        
        return feedback_data
        
    except Exception as e:
        logger.error(f"Feil i handle_user_feedback: {str(e)}", exc_info=True)
        return pd.DataFrame()


def give_user_feedback():
    """Forenklet versjon av give_feedback() fokusert på brukergrensesnittet"""
    try:
        st.title("Gi tilbakemelding")
        
        if 'customer_id' not in st.session_state:
            st.warning("Du må være logget inn for å gi tilbakemelding")
            return
            
        feedback_type = st.radio(
            "Velg type feedback:",
            list(FEEDBACK_ICONS.keys())
        )

        description = st.text_area("Beskriv din feedback i detalj:", height=150)
        
        if st.button("Send inn feedback"):
            if description:
                result = save_feedback(
                    feedback_type=feedback_type,
                    datetime_str=datetime.now(TZ).isoformat(),
                    comment=description,
                    customer_id=st.session_state.customer_id,
                    hidden=False
                )
                
                if result:
                    st.success("Feedback sendt inn. Takk for din tilbakemelding!")
                else:
                    st.error("Det oppstod en feil ved innsending av feedback.")
            else:
                st.warning("Vennligst skriv en beskrivelse før du sender inn.")

        # Vis tidligere feedback
        st.subheader("Din tidligere feedback")
        show_user_feedback_history(st.session_state.customer_id)
        
    except Exception as e:
        logger.error(f"Feil i give_user_feedback: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av feedback-skjema")

def show_user_feedback_history(customer_id: str):
    """Viser brukerens tidligere feedback"""
    try:
        feedback_data = get_feedback(customer_id=customer_id)
        if feedback_data.empty:
            st.info("Du har ingen tidligere feedback å vise.")
        else:
            for _, feedback in feedback_data.iterrows():
                with st.expander(f"{FEEDBACK_ICONS[feedback['type']]} {feedback['datetime'].strftime('%d.%m.%Y %H:%M')}"):
                    st.write(f"Status: {feedback['status']}")
                    st.write(f"Beskrivelse: {feedback['comment']}")
    except Exception as e:
        logger.error(f"Feil ved visning av feedback-historikk: {str(e)}")
        st.error("Kunne ikke hente feedback-historikk")

