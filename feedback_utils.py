import pandas as pd
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import streamlit as st
import plotly.express as px
from db_utils import execute_query, fetch_data
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

    # Legg til faner for ulike visninger
    tab1, tab2, tab3 = st.tabs(["Feedback-oversikt", "Reaksjonsstatistikk", "Reaksjonsrapport"])
    
    with tab1:
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

                # Only show delete button for Superadmin
                if st.session_state.get('is_superadmin', False):
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
        
    with tab2:
        display_maintenance_statistics()  # Gjenbruk eksisterende statistikkfunksjon
        
    with tab3:
        st.subheader("Detaljert reaksjonsrapport")
        
        # Datofilter for rapporten
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Fra dato", 
                value=datetime.now(TZ).date() - timedelta(days=30),
                key="reaction_start_date"
            )
        with col2:
            end_date = st.date_input(
                "Til dato", 
                value=datetime.now(TZ).date(),
                key="reaction_end_date"
            )

        # Hent reaksjonsdata
        start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
        end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)
        
        reactions_df = get_maintenance_reactions(start_datetime, end_datetime)
        
        if not reactions_df.empty:
            # Rydd opp i dataframe for visning
            display_df = reactions_df[['datetime', 'innsender', 'reaction']].copy()
            display_df['datetime'] = display_df['datetime'].dt.strftime('%d.%m.%Y %H:%M')
            display_df.columns = ['Tidspunkt', 'Hytte', 'Reaksjon']
            
            # Vis dataframe
            st.dataframe(
                display_df.sort_values('Tidspunkt', ascending=False),
                use_container_width=True
            )
            
            # Eksporter-knapp
            csv = display_df.to_csv(index=False)
            st.download_button(
                label="Last ned som CSV",
                data=csv,
                file_name=f"reaksjoner_{start_date}_{end_date}.csv",
                mime="text/csv"
            )
        else:
            st.info("Ingen reaksjoner funnet i valgt periode")

def give_feedback():
    st.title("Gi feedback")
    st.info(
        """
    Her kan du gi tilbakemeldinger, melde avvik eller komme med forslag til forbedringer. Velg type feedback fra menyen nedenfor. 
    """
    )
    
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

def save_maintenance_reaction(user_id, reaction_type, date):
    """
    Lagrer en vedlikeholdsreaksjon i feedback-tabellen.
    
    Args:
        user_id (str): Hytteeierens ID
        reaction_type (str): 'positive', 'neutral', eller 'negative'
        date (datetime): Datoen reaksjonen gjelder for
    """
    try:
        reaction_mapping = {
            'positive': '😊 Fornøyd',
            'neutral': '😐 Nøytral',
            'negative': '😡 Misfornøyd'
        }
        
        if reaction_type not in reaction_mapping:
            logger.error(f"Ugyldig reaksjonstype: {reaction_type}")
            return False
        
        feedback_type = "Vintervedlikehold"
        comment = reaction_mapping[reaction_type]  # Lagrer bare emojien og teksten
        
        result = save_feedback(
            feedback_type=feedback_type,
            datetime_str=date.isoformat(),
            comment=comment,
            cabin_identifier=user_id,
            hidden=False
        )
        
        if result:
            logger.info(f"Vedlikeholdsreaksjon lagret for hytte {user_id}: {reaction_type}")
        return result
        
    except Exception as e:
        logger.error(f"Feil ved lagring av vedlikeholdsreaksjon: {str(e)}")
        return False

def get_maintenance_reactions(start_date, end_date):
    """
    Henter vedlikeholdsreaksjoner for en gitt periode.
    """
    try:
        query = """
        SELECT datetime, comment, innsender
        FROM feedback 
        WHERE type = 'Vintervedlikehold'
        AND datetime BETWEEN ? AND ?
        AND comment IN ('😊 Fornøyd', '😐 Nøytral', '😡 Misfornøyd')
        ORDER BY datetime DESC
        """
        
        df = fetch_data('feedback', query, params=(start_date.isoformat(), end_date.isoformat()))
        
        if df is not None and not df.empty:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df['reaction'] = df['comment']  # Reaksjonen er nå direkte i comment-feltet
            logger.info(f"Hentet {len(df)} vedlikeholdsreaksjoner")
            return df
            
        logger.info("Ingen vedlikeholdsreaksjoner funnet for perioden")
        return pd.DataFrame()
        
    except Exception as e:
        logger.error(f"Feil ved henting av vedlikeholdsreaksjoner: {str(e)}")
        return pd.DataFrame()

def display_maintenance_feedback():
    try:
        st.subheader("Gi din vurdering av dagens brøyting her")
        
        if 'user_id' not in st.session_state:
            st.warning("Du må være logget inn for å gi tilbakemelding")
            return
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            happy = st.button("😊 Fornøyd", key="happy_btn")
        
        with col2:
            neutral = st.button("😐 Nøytral", key="neutral_btn")
        
        with col3:
            sad = st.button("😡 Misfornøyd", key="sad_btn")
        
        if any([happy, neutral, sad]):
            reaction_type = (
                'positive' if happy else
                'neutral' if neutral else
                'negative'
            )
            
            result = save_maintenance_reaction(
                st.session_state.user_id,
                reaction_type,
                datetime.now(TZ)
            )
            
            if result:
                st.success("Takk for din tilbakemelding! Bruk 'Gi feedback' i menyen for en mer detaljert tilbakemelding")
            else:
                st.error("Beklager, det oppstod en feil ved lagring av tilbakemeldingen.")
        
        # Legg til visuell separator
        st.write("---")
    
    except Exception as e:
        logger.error(f"Error in display_maintenance_feedback: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av tilbakemeldingsskjema")

def display_maintenance_statistics():
    """
    Viser statistikk over vedlikeholdsreaksjoner.
    """
    try:
        st.subheader("Statistikk over tilbakemeldinger")
        
        # Hurtigvalg for tidsperiode med dagens dato som referanse
        today = datetime.now(TZ).date()
        period_options = {
            "Siste 7 dager": 7,
            "Siste 30 dager": 30,
            "Siste 90 dager": 90,
            "Dette året": (today - date(today.year, 1, 1)).days + 1,
            "Egendefinert periode": 0
        }
        
        col1, col2 = st.columns([2, 1])
        with col1:
            selected_period = st.radio("Velg periode", options=list(period_options.keys()), horizontal=True)
        with col2:
            group_by = st.selectbox(
                "Gruppering", 
                ["Dag", "Uke", "Måned"],
                help="Velg hvordan dataene skal grupperes i grafen"
            )
        
        # Datovelgere for perioden
        if selected_period == "Egendefinert periode":
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input(
                    "Fra dato",
                    value=today - timedelta(days=7),
                    format="DD.MM.YYYY"
                )
            with col2:
                end_date = st.date_input(
                    "Til dato",
                    value=today,
                    format="DD.MM.YYYY",
                    max_value=today
                )
        else:
            days = period_options[selected_period]
            end_date = today
            start_date = end_date - timedelta(days=days)
        
        if start_date > end_date:
            st.error("Fra-dato kan ikke være senere enn til-dato")
            return
            
        # Hent og behandle data
        start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
        end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)
        
        # Oppdatert spørring for å hente alle typer feedback
        query = """
        SELECT datetime, comment
        FROM feedback 
        WHERE type = 'Vintervedlikehold'
        AND datetime BETWEEN ? AND ?
        AND (
            comment LIKE '%😊%' OR 
            comment LIKE '%😐%' OR 
            comment LIKE '%😡%'
        )
        ORDER BY datetime DESC
        """
        
        reactions_df = fetch_data('feedback', query, params=(start_datetime.isoformat(), end_datetime.isoformat()))
        
        if not reactions_df.empty:
            reactions_df['datetime'] = pd.to_datetime(reactions_df['datetime'])
            
            # Grupper basert på valgt periode
            period_formats = {
                "Dag": ("%Y-%m-%d", "Daglig"),
                "Uke": ("%Y-W%W", "Ukentlig"),
                "Måned": ("%Y-%m", "Månedlig")
            }
            
            reactions_df['period'] = reactions_df['datetime'].dt.strftime(period_formats[group_by][0])
            
            # Grupper og tell reaksjoner
            daily_stats = pd.crosstab(
                reactions_df['period'],
                reactions_df['comment'],
                margins=False
            )
            
            # Beregn score og prosentandeler
            daily_stats_pct = daily_stats.div(daily_stats.sum(axis=1), axis=0) * 100
            daily_score = (
                daily_stats.get('😊 Fornøyd', pd.Series(0, index=daily_stats.index)) * 1.0 + 
                daily_stats.get('😐 Nøytral', pd.Series(0, index=daily_stats.index)) * 0.5 + 
                daily_stats.get('😡 Misfornøyd', pd.Series(0, index=daily_stats.index)) * 0.0
            ) / daily_stats.sum(axis=1)
            
            # Vis statistikk og grafer
            create_maintenance_chart(daily_stats, daily_stats_pct, daily_score, group_by)
            display_maintenance_summary(daily_stats, daily_score, group_by)
            
        else:
            st.info("Ingen tilbakemeldinger funnet i valgt periode")
            
    except Exception as e:
        logger.error(f"Feil ved visning av vedlikeholdsstatistikk: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av statistikken")

def create_maintenance_chart(daily_stats, daily_stats_pct, daily_score, group_by):
    """Oppretter Plotly-figur for vedlikeholdsstatistikk"""
    fig = go.Figure()
    
    colors = {
        '😊 Fornøyd': '#2ECC40',
        '😐 Nøytral': '#FF851B',
        '😡 Misfornøyd': '#FF4136'
    }
    
    # Legg til stolper for hver reaksjonstype
    for reaction in daily_stats.columns:
        fig.add_trace(go.Bar(
            name=reaction,
            x=daily_stats.index,
            y=daily_stats_pct[reaction],
            marker_color=colors.get(reaction, '#AAAAAA'),
            hovertemplate=(
                f"Periode: %{{x}}<br>"
                f"Andel: %{{y:.1f}}%<br>"
                f"Reaksjon: {reaction}<extra></extra>"
            )
        ))
    
    # Legg til trendlinje
    fig.add_trace(go.Scatter(
        name='Score',
        x=daily_stats.index,
        y=daily_score * 100,
        line=dict(color='black', width=2, dash='dot'),
        yaxis='y2'
    ))
    
    fig.update_layout(
        barmode='relative',
        title={
            'text': f'{group_by}lige tilbakemeldinger på vintervedlikehold',
            'x': 0.5,
            'xanchor': 'center'
        },
        xaxis_title='Periode',
        yaxis_title='Prosentandel av tilbakemeldinger',
        yaxis2=dict(
            title='Score (0-100)',
            overlaying='y',
            side='right',
            range=[0, 100]
        ),
        legend_title='Reaksjoner',
        hovermode='x unified'
    )
    
    return fig

def display_maintenance_summary(daily_stats, daily_score, group_by):
    """Viser sammendrag og eksportmuligheter for vedlikeholdsstatistikk"""
    try:
        print("DEBUG: Starting display_maintenance_summary")
        print(f"DEBUG: daily_stats type: {type(daily_stats)}")
        print(f"DEBUG: daily_stats content:\n{daily_stats}")
        print(f"DEBUG: daily_score type: {type(daily_score)}")
        print(f"DEBUG: daily_score content:\n{daily_score}")
        
        logger.info("Starting display_maintenance_summary")
        logger.info(f"Input daily_stats:\n{daily_stats}")
        logger.info(f"Input daily_score:\n{daily_score}")
        logger.info(f"Group by: {group_by}")

        # Beregn total statistikk
        print("DEBUG: Calculating total statistics")
        total_stats = daily_stats.sum()
        print(f"DEBUG: total_stats:\n{total_stats}")
        
        total_reactions = total_stats.sum()
        print(f"DEBUG: total_reactions: {total_reactions}")
        
        if total_reactions == 0:
            print("DEBUG: No reactions found")
            st.info("Ingen tilbakemeldinger å vise for valgt periode")
            return
            
        st.write("### Sammendrag for perioden")
        
        # Opprett kolonner
        print("DEBUG: Creating columns")
        cols = st.columns(4)
        
        # Hent verdier
        print("DEBUG: Getting reaction counts")
        fornoyd = total_stats.get('😊 Fornøyd', 0)
        noytral = total_stats.get('😐 Nøytral', 0)
        misfornoyd = total_stats.get('😡 Misfornøyd', 0)
        print(f"DEBUG: Counts - Fornøyd: {fornoyd}, Nøytral: {noytral}, Misfornøyd: {misfornoyd}")
        
        try:
            print("DEBUG: Calculating percentages")
            fornoyd_pct = (fornoyd / total_reactions * 100) if total_reactions > 0 else 0
            noytral_pct = (noytral / total_reactions * 100) if total_reactions > 0 else 0
            misfornoyd_pct = (misfornoyd / total_reactions * 100) if total_reactions > 0 else 0
            print(f"DEBUG: Percentages - Fornøyd: {fornoyd_pct}%, Nøytral: {noytral_pct}%, Misfornøyd: {misfornoyd_pct}%")
            
            print("DEBUG: Displaying metrics")
            with cols[0]:
                st.metric("😊 Fornøyd", f"{fornoyd_pct:.1f}%", f"{fornoyd} stk")
            with cols[1]:
                st.metric("😐 Nøytral", f"{noytral_pct:.1f}%", f"{noytral} stk")
            with cols[2]:
                st.metric("😡 Misfornøyd", f"{misfornoyd_pct:.1f}%", f"{misfornoyd} stk")
            
            print("DEBUG: Calculating average score")
            avg_score = daily_score.mean() if not daily_score.empty else 0
            print(f"DEBUG: Average score: {avg_score}")
            
            with cols[3]:
                st.metric("Totalt antall", str(total_reactions), f"Score: {avg_score:.2f}/1.0")
                
        except Exception as e:
            print(f"DEBUG ERROR: Error in metrics calculation/display: {str(e)}")
            logger.error(f"Error in metrics: {str(e)}", exc_info=True)
            raise
            
        print("DEBUG: Setting up export options")
        with st.expander("Vis rådata og eksport"):
            st.dataframe(daily_stats)
            
            col1, col2 = st.columns(2)
            with col1:
                csv = daily_stats.to_csv()
                st.download_button(
                    label="📥 Last ned som CSV",
                    data=csv,
                    file_name=f"vedlikehold_statistikk_{group_by.lower()}.csv",
                    mime="text/csv"
                )
            with col2:
                buffer = BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    daily_stats.to_excel(writer, sheet_name='Statistikk')
                st.download_button(
                    label="📊 Last ned som Excel",
                    data=buffer.getvalue(),
                    file_name=f"vedlikehold_statistikk_{group_by.lower()}.xlsx",
                    mime="application/vnd.ms-excel"
                )
                
        print("DEBUG: Successfully completed display_maintenance_summary")
        
    except Exception as e:
        print(f"DEBUG ERROR: Main error in display_maintenance_summary: {str(e)}")
        print(f"DEBUG ERROR: daily_stats type: {type(daily_stats)}")
        print(f"DEBUG ERROR: daily_score type: {type(daily_score)}")
        logger.error(f"Error in display_maintenance_summary: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av statistikken")
        raise