import logging
import time
from datetime import datetime
from typing import List, Dict, Optional
import streamlit as st
import pandas as pd

from db_utils import (
    TZ, execute_query, fetch_data, get_db_connection
)

from logging_config import get_logger

logger = get_logger(__name__)

def save_alert(alert_type: str, message: str, expiry_date: str, 
               target_group: List[str], created_by: str) -> Optional[int]:
    try:
        query = """
        INSERT INTO feedback (type, comment, datetime, innsender, status, is_alert, display_on_weather, expiry_date, target_group)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            f"Admin varsel: {alert_type}",
            message,
            datetime.now(TZ).isoformat(),
            created_by,
            "Aktiv",
            1,
            1,
            expiry_date,
            ','.join(target_group)
        )
        
        with get_db_connection('feedback') as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            new_id = cursor.lastrowid
        
        if new_id:
            logger.info(f"Alert saved successfully by {created_by}. New ID: {new_id}")
            return new_id
        else:
            logger.warning("Alert may not have been saved. No new ID returned.")
            return None
    except Exception as e:
        logger.error(f"An error occurred while saving the alert: {str(e)}", exc_info=True)
        return None
           
@st.cache_data(ttl=60)  # Cache data for 60 seconds
def get_alerts(only_today: bool = False, include_expired: bool = False) -> pd.DataFrame:
    query = """
    SELECT * FROM feedback 
    WHERE is_alert = 1 
    AND status = 'Aktiv'
    """
    
    params = []
    
    if only_today:
        query += " AND date(datetime, 'localtime') = date('now', 'localtime')"
    
    if not include_expired:
        query += " AND (expiry_date IS NULL OR date(expiry_date, 'localtime') >= date('now', 'localtime'))"
    
    query += " ORDER BY datetime DESC"
    
    logger.debug(f"Executing query: {query}")
    df = fetch_data('feedback', query, params)
    logger.info(f"Fetched {len(df)} alerts. only_today={only_today}, include_expired={include_expired}")
    logger.debug(f"Fetched alerts: {df.to_dict('records')}")
    return df

def update_alert(alert_id: int, new_type: str, new_message: str, new_expiry_date: str, 
                 new_target_group: List[str], new_status: str, updated_by: str) -> bool:
    query = """
    UPDATE feedback 
    SET type = ?, comment = ?, expiry_date = ?, target_group = ?, status = ?, status_changed_by = ?, status_changed_at = ?
    WHERE id = ? AND is_alert = 1
    """
    try:
        current_time = datetime.now(TZ).isoformat()
        params = (f"Admin varsel: {new_type}", new_message, new_expiry_date, 
                  ','.join(new_target_group), new_status, updated_by, current_time, alert_id)
        affected_rows = execute_query('feedback', query, params)
        if affected_rows > 0:
            logger.info(f"Alert {alert_id} updated by {updated_by}")
            return True
        else:
            logger.warning(f"No alert found with id: {alert_id}")
            return False
    except Exception as e:
        logger.error(f"An error occurred while updating alert: {e}", exc_info=True)
        return False

def delete_alert(alert_id: int) -> bool:
    query = "DELETE FROM feedback WHERE id = ? AND type LIKE 'Admin varsel:%'"
    try:
        affected_rows = execute_query('feedback', query, (alert_id,))
        if affected_rows > 0:
            logger.info(f"Alert {alert_id} deleted successfully")
            return True
        else:
            logger.warning(f"No alert found with id: {alert_id}")
            return False
    except Exception as e:
        logger.error(f"An error occurred while deleting alert: {e}", exc_info=True)
        return False

def delete_alert_action(alert_id):
    try:
        if delete_alert(alert_id):
            st.success("Varsel slettet")
            # Force cache clear for get_alerts
            get_alerts.clear()
            time.sleep(0.1)  # Small delay to ensure cache is cleared
            st.rerun()
        else:
            st.error("Feil ved sletting av varsel: Varselet ble ikke funnet eller kunne ikke slettes.")
    except Exception as e:
        st.error(f"Uventet feil ved sletting av varsel: {str(e)}")
        logger.error(f"Error deleting alert {alert_id}: {str(e)}", exc_info=True)
        
def handle_alerts_ui():
    st.title("Håndter varsler")
    st.info(
        """
        Her kan brøytefirma og Fjellbergsskardet Drift opprette varsler. 
        Varslene vil vise øverst på hovedsiden "Værdata". Utløpsdato for varselet er automatisk satt til dagens dato,
        men kan forlenges ved å velge seinere dato.
        """
        )
  
    create_new_alert()
    display_user_alerts()
    # display_active_alerts()
    display_all_alerts()

def display_active_alerts():
    st.subheader("Dagens aktive varsler")
    todays_alerts = get_alerts(only_today=True)
    if todays_alerts.empty:
        st.info("Ingen aktive varsler for i dag.")
    else:
        for _, alert in todays_alerts.iterrows():
            st.warning(f"{alert['type']}: {alert['comment']}")

def display_all_alerts():
    st.subheader("Rediger varsler")
    if st.button("Oppdater varselliste"):
        get_alerts.clear()
        st.rerun()
    
    all_active_alerts = get_alerts(include_expired=False)

    if all_active_alerts.empty:
        st.info("Ingen aktive varsler.")
    else:
        for _, alert in all_active_alerts.iterrows():
            with st.expander(f"{alert['type']} - {alert['datetime']}"):
                display_alert_details(alert)
                edit_alert(alert)
                
def display_alert_details(alert):
    st.write(f"Melding: {alert['comment']}")
    st.write(f"Utløper: {alert['expiry_date']}")
    st.write(f"Målgruppe: {alert['target_group']}")

def edit_alert(alert):
    new_type = st.selectbox("Endre type", ["Generelt", "Brøyting", "Strøing", "Vedlikehold", "Annet"], 
                            index=["Generelt", "Brøyting", "Strøing", "Vedlikehold", "Annet"].index(alert['type'].split(": ")[-1]), 
                            key=f"type_{alert['id']}")
    new_message = st.text_area("Endre melding", value=alert['comment'], key=f"message_{alert['id']}")
    new_expiry_date = st.date_input("Endre utløpsdato", value=datetime.fromisoformat(alert['expiry_date']).date(), key=f"expiry_{alert['id']}")
    new_target_group = st.multiselect("Endre målgruppe", ["Alle brukere", "Årsabonnenter", "Ukentlig ved bestilling", "Ikke-abonnenter"], 
                                      default=alert['target_group'].split(','), key=f"target_{alert['id']}")
    new_status = st.selectbox("Status", ["Aktiv", "Inaktiv"], index=0 if alert['status'] == "Aktiv" else 1, key=f"status_{alert['id']}")
    
    if st.button("Oppdater varsel", key=f"update_alert_{alert['id']}"):
        update_alert_action(alert['id'], new_type, new_message, new_expiry_date, new_target_group, new_status)

    if st.button("Slett varsel", key=f"delete_{alert['id']}"):
        delete_alert_action(alert['id'])

def update_alert_action(alert_id, new_type, new_message, new_expiry_date, new_target_group, new_status):
    try:
        if update_alert(alert_id, new_type, new_message, new_expiry_date.isoformat(), new_target_group, new_status, st.session_state.user_id):
            st.success("Varsel oppdatert")
            st.rerun()
        else:
            st.error("Feil ved oppdatering av varsel")
    except Exception as e:
        st.error(f"Uventet feil ved oppdatering av varsel: {str(e)}")
        logger.error(f"Error updating alert {alert_id}: {str(e)}", exc_info=True)

def create_new_alert():
    st.subheader("Opprett nytt varsel")
    alert_type = st.selectbox("Type varsel", ["Generelt", "Brøyting", "Strøing", "Vedlikehold", "Annet"])
    message = st.text_area("Skriv varselmelding")
    expiry_date = st.date_input("Utløpsdato for varselet", min_value=datetime.now(TZ).date())
    target_group = st.multiselect(
        "Målgruppe", 
        ["Alle brukere", "Årsabonnenter", "Ukentlig ved bestilling", "Ikke-abonnenter"],
        default=["Alle brukere"]  # Set "Alle brukere" as the default selection
    )
    
    if st.button("Send varsel"):
        if message and target_group:
            new_alert_id = save_alert(alert_type, message, expiry_date.isoformat(), target_group, st.session_state.user_id)
            if new_alert_id:
                st.success(f"Varsel opprettet og lagret med ID: {new_alert_id}")
                get_alerts.clear()  # Clear the cache to reflect the new alert
                time.sleep(0.1)  # Small delay to ensure cache is cleared
                st.rerun()
            else:
                st.error("Det oppstod en feil ved opprettelse av varselet. Vennligst prøv igjen senere.")
        else:
            st.warning("Vennligst fyll ut alle feltene før du sender.")
                 
# Kategori: User Interface Functions

def display_user_alerts():
    with st.expander("Se aktive og tidligere varsler fra brøytefirma og Fjellbergsskardet Drift"):
        # Hent alle varsler, inkludert utløpte
        all_alerts = get_alerts(only_today=False, include_expired=True)
        
        if all_alerts.empty:
            st.info("Ingen varsler å vise.")
        else:
            # Sorter varslene etter dato, nyeste først
            all_alerts['datetime'] = pd.to_datetime(all_alerts['datetime'])
            all_alerts = all_alerts.sort_values('datetime', ascending=False)
            
            # Opprett to lister: en for aktive og en for utløpte varsler
            active_alerts = []
            expired_alerts = []
            
            current_date = datetime.now(TZ).date()
            
            for _, alert in all_alerts.iterrows():
                expiry_date = pd.to_datetime(alert['expiry_date']).date()
                alert_info = f"**{alert['type']}** ({alert['datetime'].strftime('%d.%m.%Y')}): {alert['comment']}"
                
                if expiry_date >= current_date:
                    active_alerts.append(alert_info)
                else:
                    expired_alerts.append(alert_info)
            
            # Vis aktive varsler
            if active_alerts:
                st.subheader("Aktive varsler")
                for alert in active_alerts:
                    st.markdown(alert)
            else:
                st.info("Ingen aktive varsler for øyeblikket.")
            
            # Vis utløpte varsler
            if expired_alerts:
                st.subheader("Tidligere varsler")
                for alert in expired_alerts:
                    st.markdown(f"<span style='color: gray;'>{alert}</span>", unsafe_allow_html=True)
            
            # Legg til en note om at utløpte varsler vises i 30 dager
            st.caption("Merk: Utløpte varsler vises i 30 dager etter utløpsdatoen.")
        
