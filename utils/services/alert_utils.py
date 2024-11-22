import time
from datetime import datetime
from typing import List, Optional

import pandas as pd
import streamlit as st
from utils.core.config import (
    TZ,
    get_current_time,
    format_date,
    safe_to_datetime
)
from utils.core.logging_config import get_logger
from utils.db.db_utils import execute_query, get_db_connection, fetch_data
from utils.components.ui.alert_card import get_alert_icon, is_new_alert

logger = get_logger(__name__)

# Hjelpefunksjoner for datohåndtering
def is_valid_date(date_string):
    try:
        if pd.isna(date_string) or date_string == "":
            return False
        pd.to_datetime(date_string)
        return True
    except ValueError:
        return False

# Database operasjoner
@st.cache_data(ttl=60)
def get_alerts(alert_type='active', only_today=False):
    """
    Henter varsler fra databasen.
    
    Args:
        alert_type (str): 'active' for aktive varsler, 'inactive' for tidligere varsler
        only_today (bool): Hvis True, returner kun dagens varsler
    """
    try:
        base_query = """
            SELECT id, type, datetime, comment, customer_id, status, 
                   status_changed_by, status_changed_at, hidden, 
                   is_alert, display_on_weather, expiry_date, target_group
            FROM feedback
            WHERE type LIKE 'Admin varsel:%'
            AND (hidden = 0 OR hidden IS NULL)
            AND (is_alert = 1 OR is_alert IS NULL)
        """
        
        current_date = get_current_time().date()
        
        if only_today:
            query = base_query + """
                AND status = 'Aktiv'
                AND date(datetime) = date(?)
                AND (expiry_date IS NULL OR date(expiry_date) >= date(?))
                ORDER BY datetime DESC
            """
            params = (current_date.isoformat(), current_date.isoformat())
        elif alert_type == 'active':
            query = base_query + """
                AND status = 'Aktiv'
                AND (expiry_date IS NULL OR date(expiry_date) >= date(?))
                ORDER BY datetime DESC
            """
            params = (current_date.isoformat(),)
        else:
            query = base_query + """
                AND (status = 'Inaktiv' OR date(expiry_date) < date(?))
                ORDER BY datetime DESC LIMIT 5
            """
            params = (current_date.isoformat(),)
            
        result = fetch_data("feedback", query, params)
        if not result:
            return pd.DataFrame()
            
        df = pd.DataFrame(result, columns=[
            'id', 'type', 'datetime', 'comment', 'customer_id', 'status', 
            'status_changed_by', 'status_changed_at', 'hidden', 
            'is_alert', 'display_on_weather', 'expiry_date', 'target_group'
        ])
        
        return df
        
    except Exception as e:
        logger.error(f"Error fetching alerts: {str(e)}")
        return pd.DataFrame()

def save_alert(alert_type: str, message: str, expiry_date: str, 
               target_group: List[str], created_by: str) -> Optional[int]:
    try:
        # Konverter og valider datoer
        expiry_dt = safe_to_datetime(expiry_date)
        if expiry_dt:
            expiry_date = format_date(expiry_dt, "database", "date")
        
        current_time = get_current_time()
        
        query = """
        INSERT INTO feedback (
            type, comment, datetime, customer_id, status, 
            is_alert, display_on_weather, expiry_date, target_group
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            f"Admin varsel: {alert_type}",
            message,
            format_date(current_time, "database", "datetime"),
            created_by,
            "Aktiv",
            1,
            1,
            expiry_date,
            ",".join(target_group),
        )

        with get_db_connection("feedback") as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            new_id = cursor.lastrowid

        if new_id:
            logger.info(f"Alert saved successfully by {created_by}. New ID: {new_id}")
            get_alerts.clear()  # Clear cache
            return new_id
            
        logger.warning("Alert may not have been saved. No new ID returned.")
        return None
        
    except Exception as e:
        logger.error(f"Error saving alert: {str(e)}", exc_info=True)
        return None

def delete_alert(alert_id: int) -> bool:
    try:
        affected_rows = execute_query(
            "feedback", 
            "DELETE FROM feedback WHERE id = ? AND type LIKE 'Admin varsel:%'", 
            (alert_id,)
        )
        success = affected_rows > 0
        
        if success:
            logger.info(f"Alert {alert_id} deleted successfully")
            get_alerts.clear()
        else:
            logger.warning(f"No alert found with id: {alert_id}")
            
        return success
    except Exception as e:
        logger.error(f"Error deleting alert: {str(e)}", exc_info=True)
        return False

# UI Komponenter
def display_all_alerts():
    """Viser alle varsler i admin-panelet"""
    st.subheader("Rediger varsler")
    if st.button("Oppdater varselliste"):
        get_alerts.clear()
        st.rerun()

    all_active_alerts = get_alerts(alert_type='active')
    all_inactive_alerts = get_alerts(alert_type='inactive')

    if all_active_alerts.empty and all_inactive_alerts.empty:
        st.info("Ingen varsler funnet.")
        return

    st.write("### Aktive varsler")
    if not all_active_alerts.empty:
        for _, alert in all_active_alerts.iterrows():
            with st.expander(f"{alert['type']} - {pd.to_datetime(alert['datetime']).strftime('%d.%m.%Y %H:%M')}", expanded=True):
                display_alert_details(alert)
    else:
        st.info("Ingen aktive varsler.")

    st.write("### Tidligere varsler")
    if not all_inactive_alerts.empty:
        for _, alert in all_inactive_alerts.iterrows():
            with st.expander(f"{alert['type']} - {pd.to_datetime(alert['datetime']).strftime('%d.%m.%Y %H:%M')}", expanded=False):
                display_alert_details(alert)
    else:
        st.info("Ingen tidligere varsler.")

def create_new_alert():
    st.subheader("Opprett nytt varsel")
    alert_type = st.selectbox(
        "Type varsel", 
        ["Generelt", "Brøyting", "Strøing", "Vedlikehold", "Annet"]
    )
    message = st.text_area("Skriv varselmelding")
    expiry_date = st.date_input(
        "Utløpsdato for varselet", 
        min_value=datetime.now(TZ).date()
    )
    target_group = st.multiselect(
        "Målgruppe",
        ["Alle brukere", "Årsabonnenter", "Ukentlig ved bestilling", "Ikke-abonnenter"],
        default=["Alle brukere"]
    )

    if st.button("Send varsel"):
        if message and target_group:
            new_alert_id = save_alert(
                alert_type,
                message,
                expiry_date.isoformat(),
                target_group,
                st.session_state.customer_id,
            )
            if new_alert_id:
                st.success(f"Varsel opprettet og lagret med ID: {new_alert_id}")
                get_alerts.clear()
                time.sleep(0.1)
                st.rerun()
            else:
                st.error("Feil ved opprettelse av varselet.")
        else:
            st.warning("Vennligst fyll ut alle feltene før du sender.")

def handle_alerts_ui():
    st.title("Håndter varsler")
    st.info(
        """Her kan brøytefirma og Fjellbergsskardet Drift opprette varsler. 
        Utløpsdato for varselet er automatisk satt til dagens dato,
        men kan forlenges ved å velge seinere dato."""
    )
    clean_invalid_expiry_dates()
    create_new_alert()
    display_all_alerts()

def display_active_alerts(only_today=False):
    """Viser aktive varsler"""
    try:
        alerts = get_alerts(alert_type='active', only_today=only_today)
        if alerts.empty:
            st.info(
                "Ingen aktive varsler for øyeblikket."
                if only_today
                else "Ingen aktive varsler."
            )
            return

        st.subheader(
            "Dagens aktive varsler"
            if only_today
            else "Aktive varsler fra brøytefirma / FD"
        )
        for _, alert in alerts.iterrows():
            st.warning(f"{alert['type']}: {alert['comment']}")
    except Exception as e:
        st.error(f"Feil ved visning av aktive alarmer: {str(e)}")
        logger.error(f"Uventet feil i display_active_alerts: {str(e)}", exc_info=True)

def clean_invalid_expiry_dates():
    """Renser ugyldige utløpsdatoer fra databasen"""
    try:
        query = """
            UPDATE feedback 
            SET expiry_date = NULL 
            WHERE expiry_date < date('now') 
            AND type LIKE 'Admin varsel:%'
        """
        # Legg til "feedback" som første argument
        execute_query("feedback", query)
        logger.info("Renset ugyldige utløpsdatoer")
    except Exception as e:
        logger.error(f"Feil ved rensing av utløpsdatoer: {str(e)}")

def display_alarms_homepage():
    try:
        active_alerts = get_alerts(alert_type='active')
        if not active_alerts.empty:
            with st.expander("⚠️ Aktive varsler", expanded=True):
                for _, alert in active_alerts.iterrows():
                    if pd.notnull(alert['display_on_weather']) and alert['display_on_weather'] == 1:
                        icon = get_alert_icon(alert['type'])
                        alert_type = alert['type'].replace("Admin varsel: ", "")
                        st.markdown(f"### <i class='fas {icon}'></i> {alert_type}", unsafe_allow_html=True)
                        st.write(alert['comment'])
                        expiry_date = safe_to_datetime(alert["expiry_date"])
                        if expiry_date:
                            st.caption(f"Gyldig til: {format_date(expiry_date)}")
                        if is_new_alert(alert['datetime']):
                            st.markdown("🆕 **Nytt varsel**")
                        st.divider()
    except Exception as e:
        logger.error(f"Feil ved visning av admin-varsler: {str(e)}")

def display_alert_details(alert):
    """Viser detaljer for et enkelt varsel"""
    try:
        # Vis standard informasjon
        st.write(f"**Type:** {alert['type']}")
        st.write(f"**Melding:** {alert['comment']}")
        st.write(f"**Opprettet av:** {alert['customer_id']}")
        st.write(f"**Opprettet:** {pd.to_datetime(alert['datetime']).strftime('%d.%m.%Y %H:%M')}")
        
        # Sjekk om vi er i redigeringsmodus for dette varselet
        edit_key = f"edit_{alert['id']}"
        if edit_key not in st.session_state:
            st.session_state[edit_key] = False
            
        if not st.session_state[edit_key]:
            # Vis normal visning
            if alert['expiry_date']:
                expiry = safe_to_datetime(alert['expiry_date'])
                if expiry:
                    st.write(f"**Utløper:** {format_date(expiry)}")
            
            st.write(f"**Status:** {alert['status']}")
            if alert['status_changed_by']:
                st.write(f"**Sist endret av:** {alert['status_changed_by']}")
                st.write(f"**Endret dato:** {pd.to_datetime(alert['status_changed_at']).strftime('%d.%m.%Y %H:%M')}")
            
            st.write(f"**Målgruppe:** {alert['target_group']}")
            
            # Knapper for sletting og redigering
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Slett", key=f"delete_{alert['id']}"):
                    if delete_alert(alert['id']):
                        st.success("Varsel slettet")
                        st.rerun()
                    else:
                        st.error("Kunne ikke slette varselet")
            
            with col2:
                if st.button("Rediger", key=f"edit_btn_{alert['id']}"):
                    st.session_state[edit_key] = True
                    st.rerun()
        
        else:
            # Vis redigeringsform
            new_status = st.selectbox(
                "Status",
                ["Aktiv", "Inaktiv"],
                index=0 if alert['status'] == 'Aktiv' else 1,
                key=f"status_{alert['id']}"
            )
            
            new_expiry = st.date_input(
                "Utløpsdato",
                value=pd.to_datetime(alert['expiry_date']).date() if pd.notnull(alert['expiry_date']) else datetime.now(TZ).date(),
                min_value=datetime.now(TZ).date(),
                key=f"expiry_{alert['id']}"
            )
            
            new_display = st.checkbox(
                "Vis på værsiden",
                value=bool(alert['display_on_weather']),
                key=f"display_{alert['id']}"
            )
            
            new_target = st.multiselect(
                "Målgruppe",
                ["Alle brukere", "Årsabonnenter", "Ukentlig ved bestilling", "Ikke-abonnenter"],
                default=alert['target_group'].split(',') if alert['target_group'] else ["Alle brukere"],
                key=f"target_{alert['id']}"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Avbryt", key=f"cancel_{alert['id']}"):
                    st.session_state[edit_key] = False
                    st.rerun()
            
            with col2:
                if st.button("Lagre", key=f"save_{alert['id']}"):
                    success = update_alert(
                        alert['id'],
                        new_status,
                        new_expiry.isoformat(),
                        new_display,
                        ','.join(new_target)
                    )
                    if success:
                        st.success("Varsel oppdatert")
                        st.session_state[edit_key] = False
                        get_alerts.clear()
                        st.rerun()
                    else:
                        st.error("Kunne ikke oppdatere varselet")
                        
    except Exception as e:
        logger.error(f"Feil ved visning av varseldetaljer: {str(e)}")
        st.error("Feil ved visning av varseldetaljer")

@st.cache_data(ttl=60)
def get_active_alerts():
    """
    Henter aktive varsler for visning på hjemmesiden.
    Wrapper rundt get_alerts() med riktige parametre.
    
    Returns:
        pd.DataFrame: DataFrame med aktive varsler
    """
    try:
        return get_alerts(alert_type='active', only_today=False)
    except Exception as e:
        logger.error(f"Feil ved henting av aktive varsler: {str(e)}")
        return pd.DataFrame()
