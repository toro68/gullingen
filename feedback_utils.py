import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import streamlit as st
import plotly.express as px
from db_utils import execute_query, fetch_data, get_db_connection
from constants import TZ
from alert_utils import display_user_alerts

from logging_config import get_logger

logger = get_logger(__name__)

STATUS_COLORS = {
    'Ny': '#FF4136',
    'Under behandling': '#FF851B',
    'Løst': '#2ECC40',
    'Lukket': '#AAAAAA',
    'default': '#CCCCCC'
}

icons = {
    'Føreforhold': '🚗',
    'Parkering': '🅿️',
    'Fasilitet': '🏠',
    'Annet': '❓'
}

#hjelpefunksjoner
def safe_to_datetime(date_string):
    if date_string in [None, '', 'None', '1']:
        return None
    try:
        return pd.to_datetime(date_string)
    except ValueError:
        logger.error(f"Ugyldig datostreng: '{date_string}'")
        return None

def format_date(date_obj):
    if date_obj is None:
        return "Ikke satt"
    return date_obj.strftime('%d.%m.%Y %H:%M')

#crud-operasjoner
def save_feedback(feedback_type, datetime_str, comment, cabin_identifier, hidden):
    try:
        query = """INSERT INTO feedback (type, datetime, comment, innsender, status, status_changed_at, hidden) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)"""
        initial_status = "Ny"
        params = (feedback_type, datetime_str, comment, cabin_identifier, initial_status, datetime.now(TZ).isoformat(), hidden)
        
        execute_query('feedback', query, params)
        
        logger.info(f"Feedback saved successfully: {feedback_type}, {datetime_str}, Cabin: {cabin_identifier}, hidden: {hidden}")
        return True
    except Exception as e:
        logger.error(f"Error saving feedback: {str(e)}", exc_info=True)
        return False

def get_feedback(start_date, end_date, include_hidden=False, cabin_identifier=None, hytte_nr=None, limit=100, offset=0):
    query = """
    SELECT id, type, datetime, comment, innsender, status, status_changed_by, status_changed_at, hidden
    FROM feedback 
    WHERE 1=1
    """
    params = []
    
    if start_date and end_date:
        query += " AND datetime BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    
    if not include_hidden:
        query += " AND hidden = 0"
    
    if cabin_identifier:
        query += " AND innsender = ?"
        params.append(cabin_identifier)
    
    if hytte_nr:
        query += " AND innsender = ?"
        params.append(str(hytte_nr))
    
    query += " ORDER BY datetime DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    try:
        df = fetch_data('feedback', query, params=params)
        df['datetime'] = pd.to_datetime(df['datetime'])
        return df
    except Exception as e:
        logger.error(f"Feil ved henting av feedback: {str(e)}", exc_info=True)
        return pd.DataFrame()

def update_feedback_status(feedback_id, new_status, changed_by):
    try:
        query = """UPDATE feedback 
                   SET status = ?, status_changed_by = ?, status_changed_at = ? 
                   WHERE id = ?"""
        changed_at = datetime.now(TZ).isoformat()
        params = (new_status, changed_by, changed_at, feedback_id)
        execute_query('feedback', query, params)
        
        logger.info(f"Status updated for feedback {feedback_id}: {new_status}")
        return True
    except Exception as e:
        logger.error(f"Error updating feedback status: {str(e)}", exc_info=True)
        return False

def delete_feedback(feedback_id):
    try:
        query = "DELETE FROM feedback WHERE id = ?"
        result = execute_query('feedback', query, (feedback_id,))
        
        # Check if result is an integer (number of affected rows)
        if isinstance(result, int):
            if result > 0:
                logger.info(f"Deleted feedback with id: {feedback_id}")
                return True
            else:
                logger.warning(f"No feedback found with id: {feedback_id}")
                return "not_found"
        # If result is not an integer, assume it's a cursor-like object
        elif hasattr(result, 'rowcount'):
            if result.rowcount > 0:
                logger.info(f"Deleted feedback with id: {feedback_id}")
                return True
            else:
                logger.warning(f"No feedback found with id: {feedback_id}")
                return "not_found"
        else:
            logger.warning(f"Unexpected result type when deleting feedback with id: {feedback_id}")
            return False
    except Exception as e:
        logger.error(f"Error deleting feedback with id {feedback_id}: {str(e)}")
        return False
    
def display_feedback_dashboard():
    st.subheader("Feedback Dashboard")

    end_date = datetime.now(TZ).date() + timedelta(days=1)
    start_date = end_date - timedelta(days=7)

    col1, col2 = st.columns(2)
    with col1:
        selected_start_date = st.date_input("Fra dato", value=start_date, max_value=end_date)
    with col2:
        selected_end_date = st.date_input("Til dato", value=end_date, min_value=selected_start_date)

    start_datetime = datetime.combine(selected_start_date, datetime.min.time()).replace(tzinfo=TZ)
    end_datetime = datetime.combine(selected_end_date, datetime.max.time()).replace(tzinfo=TZ)

    feedback_data = get_feedback(start_date=start_datetime.isoformat(), end_date=end_datetime.isoformat(), include_hidden=False)

    if feedback_data.empty:
        st.warning(f"Ingen feedback-data tilgjengelig for perioden {selected_start_date} til {selected_end_date}.")
        return

    feedback_data['datetime'] = pd.to_datetime(feedback_data['datetime'])
    feedback_data.loc[feedback_data['status'].isnull() | (feedback_data['status'] == 'Innmeldt'), 'status'] = 'Ny'

    full_date_range = pd.date_range(start=selected_start_date, end=selected_end_date, freq='D')
    daily_counts = feedback_data.groupby(feedback_data['datetime'].dt.date).size().reindex(full_date_range, fill_value=0).reset_index()
    daily_counts.columns = ['date', 'count']

    fig_bar = px.bar(daily_counts, x='date', y='count', title="Antall feedback over tid")
    fig_bar.update_xaxes(title_text="Dato", tickformat="%Y-%m-%d")
    fig_bar.update_yaxes(title_text="Antall feedback", dtick=1)
    fig_bar.update_layout(bargap=0.2)
    st.plotly_chart(fig_bar)

    st.info(f"Totalt {len(feedback_data)} feedback-elementer for perioden {selected_start_date} til {selected_end_date}")

    if st.checkbox("Vis rådata for grafen"):
        st.write("Rådata for grafen:")
        st.write(daily_counts)

    if not feedback_data.empty:
        csv = feedback_data.to_csv(index=False)
        st.download_button(
            label="Last ned som CSV",
            data=csv,
            file_name="feedback_data.csv",
            mime="text/csv",
        )

def handle_user_feedback():
    st.subheader("Håndter bruker-feedback")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=datetime.now(TZ).date() - timedelta(days=7), format="DD.MM.YYYY")
    with col2:
        end_date = st.date_input("Til dato", value=datetime.now(TZ).date(), format="DD.MM.YYYY")

    hytte_nr = st.text_input("Filtrer på hyttenummer (valgfritt)")

    start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
    end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)

    feedback_data = get_feedback(
        start_date=start_datetime.isoformat(), 
        end_date=end_datetime.isoformat(), 
        include_hidden=False,
        hytte_nr=hytte_nr if hytte_nr else None
    )
    
    if feedback_data.empty:
        st.warning(f"Ingen feedback-data tilgjengelig for de valgte kriteriene.")
        return

    user_feedback = feedback_data.copy()
    user_feedback.loc[user_feedback['status'].isnull() | (user_feedback['status'] == 'Innmeldt'), 'status'] = 'Ny'

    user_feedback['datetime'] = pd.to_datetime(user_feedback['datetime'])
    user_feedback = user_feedback.sort_values('datetime', ascending=False)

    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.multiselect("Filtrer på status", options=list(STATUS_COLORS.keys())[:-1])
    with col2:
        type_filter = st.multiselect("Filtrer på type", options=user_feedback['type'].dropna().unique())

    if status_filter:
        user_feedback = user_feedback[user_feedback['status'].isin(status_filter)]
    if type_filter:
        user_feedback = user_feedback[user_feedback['type'].isin(type_filter)]

    st.subheader("Detaljert feedback-oversikt")
    for index, feedback in user_feedback.iterrows():
        status = feedback['status']
        status_color = STATUS_COLORS.get(status, STATUS_COLORS['default'])
        
        with st.expander(f"Hytte {feedback['innsender']} - {feedback['type']} - {feedback['datetime'].strftime('%Y-%m-%d %H:%M')}", expanded=False):
            st.markdown(f"<h4 style='color: {status_color};'>Status: {status}</h4>", unsafe_allow_html=True)
            st.write(f"Fra: Hytte {feedback['innsender']}")
            st.write(f"Kommentar: {feedback['comment']}")
            
            new_status = st.selectbox("Endre status", 
                                      options=list(STATUS_COLORS.keys())[:-1],
                                      index=list(STATUS_COLORS.keys()).index(status) if status in STATUS_COLORS else 0,
                                      key=f"status_{index}")
            
            if st.button("Oppdater status", key=f"update_{index}"):
                if update_feedback_status(feedback['id'], new_status, st.session_state.user_id):
                    st.success("Status oppdatert")
                    st.rerun()
                else:
                    st.error("Feil ved oppdatering av status")

            if st.button("Slett feedback", key=f"delete_{index}"):
                result = delete_feedback(feedback['id'])
                if result is True:
                    st.success("Feedback slettet")
                    st.rerun()
                elif result == "not_found":
                    st.warning("Feedback-en ble ikke funnet. Den kan allerede være slettet.")
                    st.rerun()
                else:
                    st.error("Feil ved sletting av feedback")

    st.info(f"Viser {len(user_feedback)} feedback-elementer for de valgte kriteriene")

    if not user_feedback.empty:
        csv = user_feedback.to_csv(index=False)
        st.download_button(
            label="Last ned som CSV",
            data=csv,
            file_name="feedback_data.csv",
            mime="text/csv",
        )
        
def give_feedback():
    st.title("Gi feedback")
    st.info(
        """
    Her kan du gi tilbakemeldinger, melde avvik eller komme med forslag til forbedringer. Velg type feedback fra menyen nedenfor. 

    - Brøytekartet viser hvor det skal brøytes hver gang det er behov, [se her](https://sartopo.com/m/J881). Annen brøyting må du betale selv.
    - Brøytestandarden er vår kravspesifikasjon til brøytefirmaet og regulerer samspillet med hytteeierne. 
    - Gå gjennom varslene under, før du gir feedback.   
    """
    )
    
    display_user_alerts()
    
    feedback_type = st.radio(
        "Velg type feedback:",
        ["Avvik", "Generell tilbakemelding", "Forslag til forbedring", "Annet"],
    )

    st.write("---")

    avvik_tidspunkt = None
    if feedback_type == "Avvik":
        st.subheader("Rapporter et avvik")
        deviation_type = st.selectbox(
            "Velg type avvik:",
            [
                "Glemt tunbrøyting",
                "Dårlig framkommelighet",
                "For sen brøytestart",
                "Manglende brøyting av fellesparkeringsplasser",
                "Manglende strøing",
                "Uønsket snødeponering",
                "Manglende rydding av snøfenner",
                "For høy hastighet under brøyting",
                "Skader på eiendom under brøyting",
                "Annet"
            ]
        )
        
        col1, col2 = st.columns(2)
        with col1:
            avvik_dato = st.date_input("Dato for avviket", value=datetime.now(TZ).date(), format="DD.MM.YYYY")
        with col2:
            avvik_tid = st.time_input("Tidspunkt for avviket", value=datetime.now(TZ).time())
        
        avvik_tidspunkt = datetime.combine(avvik_dato, avvik_tid).replace(tzinfo=TZ)
        
        feedback_type = f"Avvik: {deviation_type}"
    elif feedback_type == "Generell tilbakemelding":
        st.subheader("Gi en generell tilbakemelding")
    elif feedback_type == "Forslag til forbedring":
        st.subheader("Kom med et forslag til forbedring")
    else:  # Annet
        st.subheader("Annen type feedback")

    description = st.text_area("Beskriv din feedback i detalj:", height=150)
    
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        submit_button = st.button("Send inn feedback", use_container_width=True)

    if submit_button:
        if description:
            cabin_identifier = st.session_state.get('user_id')
            
            if cabin_identifier:
                if avvik_tidspunkt:
                    description = f"Tidspunkt for avvik: {avvik_tidspunkt.strftime('%Y-%m-%d %H:%M')}\n\n" + description
                
                feedback_datetime = avvik_tidspunkt if avvik_tidspunkt else datetime.now(TZ)
                
                result = save_feedback(feedback_type, feedback_datetime.isoformat(), description, cabin_identifier, hidden=False)
                
                if result:
                    st.success("Feedback sendt inn. Takk for din tilbakemelding!")
                else:
                    st.error("Det oppstod en feil ved innsending av feedback. Vennligst prøv igjen senere.")
            else:
                st.error("Kunne ikke identifisere hytten. Vennligst logg inn på nytt.")
        else:
            st.warning("Vennligst skriv en beskrivelse før du sender inn.")

    st.write("---")

    st.subheader("Din tidligere feedback")
    cabin_identifier = st.session_state.get('user_id')
    if cabin_identifier:
        existing_feedback = get_feedback(start_date=None, end_date=None, include_hidden=False, cabin_identifier=cabin_identifier)
        if existing_feedback.empty:
            st.info("Du har ingen tidligere feedback å vise.")
        else:
            for _, feedback in existing_feedback.iterrows():
                with st.expander(f"{feedback['type']} - {feedback['datetime']}"):
                    st.write(f"Beskrivelse: {feedback['comment']}")
                    st.write(f"Status: {feedback['status']}")
    else:
        st.warning("Kunne ikke hente tidligere feedback. Vennligst logg inn på nytt.")

def display_recent_feedback():
    st.subheader("Nylige rapporter")
    end_date = datetime.now(TZ)
    start_date = end_date - timedelta(days=7)
    recent_feedback = get_feedback(start_date.isoformat(), end_date.isoformat())
    
    if not recent_feedback.empty:
        recent_feedback.loc[recent_feedback['status'].isnull(), 'status'] = 'Ny'
        
        recent_feedback = recent_feedback.sort_values('datetime', ascending=False)
        
        st.write(f"Viser {len(recent_feedback)} rapporter fra de siste 7 dagene:")
        
        for _, row in recent_feedback.iterrows():
            icon = icons.get(row['type'], "❓")
            status = row['status']
            status_color = STATUS_COLORS.get(status, STATUS_COLORS['default'])
            date_str = row['datetime'].strftime('%Y-%m-%d %H:%M') if pd.notnull(row['datetime']) else 'Ukjent dato'
            
            with st.expander(f"{icon} {row['type']} - {date_str}"):
                st.markdown(f"<span style='color:{status_color};'>●</span> **Status:** {status}", unsafe_allow_html=True)
                st.write(f"**Rapportert av:** {row['innsender']}")
                st.write(f"**Kommentar:** {row['comment']}")
                if pd.notnull(row['status_changed_at']):
                    st.write(f"**Status oppdatert:** {row['status_changed_at'].strftime('%Y-%m-%d %H:%M')}")
    else:
        st.info("Ingen rapporter i de siste 7 dagene.")

def batch_insert_feedback(feedback_list):
    query = """
    INSERT INTO feedback (type, datetime, comment, innsender, status, hidden)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    params = [(f['type'], f['datetime'], f['comment'], f['innsender'], 'Ny', 0) for f in feedback_list]
    
    execute_query('feedback', query, params, many=True)
    
    logger.info(f"Batch inserted {len(feedback_list)} feedback entries")

def hide_feedback(feedback_id):
    try:
        query = "UPDATE feedback SET hidden = 1 WHERE id = ?"
        execute_query('feedback', query, (feedback_id,))
        logger.info(f"Skjulte feedback med id: {feedback_id}")
        return True
    except Exception as e:
        logger.error(f"Feil ved skjuling av feedback: {str(e)}")
        return False

def get_feedback_statistics(start_date, end_date):
    feedback_data = get_feedback(start_date, end_date)
    
    if feedback_data.empty:
        return None
    
    stats = {
        'total_count': len(feedback_data),
        'type_distribution': feedback_data['type'].value_counts().to_dict(),
        'status_distribution': feedback_data['status'].value_counts().to_dict(),
        'daily_counts': feedback_data.groupby(feedback_data['datetime'].dt.date).size().to_dict()
    }
    
    return stats

def generate_feedback_report(start_date, end_date):
    feedback_data = get_feedback(start_date, end_date)
    stats = get_feedback_statistics(start_date, end_date)
    
    report = f"Feedback Report: {start_date} to {end_date}\n\n"
    
    if stats:
        report += f"Total Feedback Count: {stats['total_count']}\n\n"
        
        report += "Type Distribution:\n"
        for feedback_type, count in stats['type_distribution'].items():
            report += f"  {feedback_type}: {count}\n"
        report += "\n"
        
        report += "Status Distribution:\n"
        for status, count in stats['status_distribution'].items():
            report += f"  {status}: {count}\n"
        report += "\n"
        
        report += "Daily Counts:\n"
        for date, count in stats['daily_counts'].items():
            report += f"  {date}: {count}\n"
        report += "\n"
    
    report += "Detailed Feedback:\n"
    for _, feedback in feedback_data.iterrows():
        report += f"ID: {feedback['id']}\n"
        report += f"Type: {feedback['type']}\n"
        report += f"Date: {feedback['datetime']}\n"
        report += f"Status: {feedback['status']}\n"
        report += f"Comment: {feedback['comment']}\n"
        report += "---\n"
    
    return report

# Helper function to get feedback counts by type
def get_feedback_counts_by_type(start_date, end_date):
    feedback_data = get_feedback(start_date, end_date)
    return feedback_data['type'].value_counts().to_dict()

# Helper function to get feedback counts by status
def get_feedback_counts_by_status(start_date, end_date):
    feedback_data = get_feedback(start_date, end_date)
    return feedback_data['status'].value_counts().to_dict()

# Helper function to get daily feedback counts
def get_daily_feedback_counts(start_date, end_date):
    feedback_data = get_feedback(start_date, end_date)
    return feedback_data.groupby(feedback_data['datetime'].dt.date).size().to_dict()

# Function to analyze feedback trends
def analyze_feedback_trends(start_date, end_date, window=7):
    daily_counts = get_daily_feedback_counts(start_date, end_date)
    df = pd.DataFrame(list(daily_counts.items()), columns=['date', 'count'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    df['rolling_avg'] = df['count'].rolling(window=window).mean()
    
    return df

# Function to categorize feedback automatically
def categorize_feedback(feedback_text):
    # This is a simple example. In a real-world scenario, you might use
    # more sophisticated NLP techniques or machine learning models.
    keywords = {
        'snø': 'Snørelatert',
        'brøyt': 'Brøyterelatert',
        'parkering': 'Parkering',
        'vei': 'Veirelatert',
        'støy': 'Støyrelatert'
    }
    
    feedback_text = feedback_text.lower()
    for keyword, category in keywords.items():
        if keyword in feedback_text:
            return category
    
    return 'Annet'

# Add this function to your feedback_utils.py file
def get_feedback_by_id(feedback_id):
    query = """
    SELECT id, type, datetime, comment, innsender, status, status_changed_by, status_changed_at, hidden
    FROM feedback 
    WHERE id = ?
    """
    df = fetch_data('feedback', query, params=(feedback_id,))
    if not df.empty:
        return df.iloc[0].to_dict()
    return None