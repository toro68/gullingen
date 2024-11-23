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
    combine_date_with_tz,
    format_date,
    DATE_VALIDATION,
    DATE_INPUT_CONFIG
)
from utils.ui.date_inputs import get_date_range_input
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

def handle_user_feedback(feedback_data: pd.DataFrame = None) -> pd.DataFrame:
    """
    Håndterer bruker-feedback data i samsvar med databaseskjema.
    
    Args:
        feedback_data (pd.DataFrame, optional): Eksisterende feedback data
        
    Returns:
        pd.DataFrame: Behandlet feedback data
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
        
        logger.debug(f"Processed {len(feedback_data)} feedback entries")
        return feedback_data
        
    except Exception as e:
        logger.error(f"Error in handle_user_feedback: {str(e)}", exc_info=True)
        return pd.DataFrame()


def give_feedback():
    try:
        st.title("Gi tilbakemelding")
        
        # Hent brukerens customer_id fra session state
        customer_id = st.session_state.get('customer_id')
        if not customer_id:
            st.error("Kunne ikke finne hytte-ID")
            return
            
        # Sjekk eksisterende feedback
        existing_feedback = get_feedback(
            start_date=datetime.now(TZ).date(),
            end_date=datetime.now(TZ).date(),
            customer_id=customer_id
        )
        
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
                    "Glemt tunbryting",
                    "Dårlig framkommelighet",
                    "For sen brøytestart",
                    "Manglende brøyting av fellesparkeringsplasser",
                    "Manglende strøing",
                    "Uønsket snødeponering",
                    "Manglende rydding av snøfenner",
                    "For høy hastighet under brøyting",
                    "Skader på eiendom under brøyting",
                    "Annet",
                ],
            )

            col1, col2 = st.columns(2)
            with col1:
                avvik_dato = st.date_input(
                    "Dato for avviket", value=datetime.now(TZ).date(), format="DD.MM.YYYY"
                )
            with col2:
                avvik_tid = st.time_input(
                    "Tidspunkt for avviket", value=datetime.now(TZ).time()
                )

            avvik_tidspunkt = datetime.combine(avvik_dato, avvik_tid).replace(tzinfo=TZ)

            feedback_type = f"Avvik: {deviation_type}"
        elif feedback_type == "Generell tilbakemelding":
            st.subheader("Gi en generell tilbakemelding")
        elif feedback_type == "Forslag til forbedring":
            st.subheader("Kom med et forslag til forbedring")
        else:  # Annet
            st.subheader("Annen type feedback")

        description = st.text_area("Beskriv din feedback i detalj:", height=150)

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            submit_button = st.button("Send inn feedback", use_container_width=True)

        if submit_button:
            if description:
                if avvik_tidspunkt:
                    description = (
                        f"Tidspunkt for avvik: {avvik_tidspunkt.strftime('%Y-%m-%d %H:%M')}\n\n"
                        + description
                    )

                feedback_datetime = (
                    avvik_tidspunkt if avvik_tidspunkt else datetime.now(TZ)
                )

                result = save_feedback(
                    feedback_type,
                    feedback_datetime.isoformat(),
                    description,
                    customer_id,
                    hidden=False,
                )

                if result:
                    st.success("Feedback sendt inn. Takk for din tilbakemelding!")
                else:
                    st.error(
                        "Det oppstod en feil ved innsending av feedback. Vennligst prøv igjen senere."
                    )
            else:
                st.warning("Vennligst skriv en beskrivelse før du sender inn.")

        st.write("---")

        st.subheader("Din tidligere feedback")
        if customer_id:
            existing_feedback = get_feedback(
                start_date=None,
                end_date=None,
                include_hidden=False,
                customer_id=customer_id,
            )
            if existing_feedback.empty:
                st.info("Du har ingen tidligere feedback å vise.")
            else:
                for _, feedback in existing_feedback.iterrows():
                    with st.expander(f"{feedback['type']} - {feedback['datetime']}"):
                        st.write(f"Beskrivelse: {feedback['comment']}")
                        st.write(f"Status: {feedback['status']}")
        else:
            st.warning("Kunne ikke hente tidligere feedback. Vennligst logg inn på nytt.")
    except Exception as e:
            logger.error(f"Feil i give_feedback: {str(e)}", exc_info=True)
            st.error("Det oppstod en feil ved visning av feedback-skjema")

def display_recent_feedback():
    try:
        st.subheader("Nylige rapporter")
        end_date = datetime.now(TZ)
        start_date = end_date - timedelta(days=7)
        recent_feedback = get_feedback(start_date.isoformat(), end_date.isoformat())

        if not recent_feedback.empty:
            recent_feedback.loc[recent_feedback["status"].isnull(), "status"] = "Ny"
            recent_feedback = recent_feedback.sort_values("datetime", ascending=False)

            st.write(f"Viser {len(recent_feedback)} rapporter fra de siste 7 dagene:")

            for _, row in recent_feedback.iterrows():
                icon = FEEDBACK_ICONS.get(row["type"], "❓")
                status = row["status"]
                date_str = (
                    row["datetime"].strftime("%Y-%m-%d %H:%M")
                    if pd.notnull(row["datetime"])
                    else "Ukjent dato"
                )

                with st.expander(f"{icon} {row['type']} - {date_str}"):
                    st.write(f"**Status:** {status}")
                    st.write(f"**Rapportert av:** {row['customer_id']}")
                    st.write(f"**Kommentar:** {row['comment']}")
                    if pd.notnull(row["status_changed_at"]):
                        st.write(
                            f"**Status oppdatert:** {row['status_changed_at'].strftime('%Y-%m-%d %H:%M')}"
                        )
        else:
            st.info("Ingen rapporter i de siste 7 dagene.")
            
    except Exception as e:
        logger.error(f"Feil i display_recent_feedback: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av nylige rapporter")

def get_feedback_statistics(start_date, end_date):
    feedback_data = get_feedback(start_date, end_date)

    if feedback_data.empty:
        return None

    stats = {
        "total_count": len(feedback_data),
        "type_distribution": feedback_data["type"].value_counts().to_dict(),
        "status_distribution": feedback_data["status"].value_counts().to_dict(),
        "daily_counts": feedback_data.groupby(feedback_data["datetime"].dt.date)
        .size()
        .to_dict(),
    }

    return stats


def generate_feedback_report(start_date, end_date):
    feedback_data = get_feedback(start_date, end_date)
    stats = get_feedback_statistics(start_date, end_date)

    report = f"Feedback Report: {start_date} to {end_date}\n\n"

    if stats:
        report += f"Total Feedback Count: {stats['total_count']}\n\n"

        report += "Type Distribution:\n"
        for feedback_type, count in stats["type_distribution"].items():
            report += f"  {feedback_type}: {count}\n"
        report += "\n"

        report += "Status Distribution:\n"
        for status, count in stats["status_distribution"].items():
            report += f"  {status}: {count}\n"
        report += "\n"

        report += "Daily Counts:\n"
        for date, count in stats["daily_counts"].items():
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

# Helper function to get daily feedback counts
def get_daily_feedback_counts(start_date, end_date):
    feedback_data = get_feedback(start_date, end_date)
    return feedback_data.groupby(feedback_data["datetime"].dt.date).size().to_dict()

# Function to categorize feedback automatically
def categorize_feedback(feedback_text):
    # This is a simple example. In a real-world scenario, you might use
    # more sophisticated NLP techniques or machine learning models.
    keywords = {
        "snø": "Snørelatert",
        "brøyt": "Brøyterelatert",
        "parkering": "Parkering",
        "vei": "Veirelatert",
        "sty": "Støyrelatert",
    }

    feedback_text = feedback_text.lower()
    for keyword, category in keywords.items():
        if keyword in feedback_text:
            return category

    return "Annet"


# Add this function to your feedback_utils.py file
def get_feedback_by_id(feedback_id):
    query = """
    SELECT id, type, datetime, comment, customer_id, status, status_changed_by, status_changed_at, hidden
    FROM feedback 
    WHERE id = ?
    """
    df = fetch_data("feedback", query, params=(feedback_id,))
    if not df.empty:
        return df.iloc[0].to_dict()
    return None


def save_maintenance_reaction(customer_id, reaction_type, date):
    """
    Lagrer en vedlikeholdsreaksjon i feedback-tabellen.

    Args:
        customer_id (str): Hytte-ID
        reaction_type (str): 'positive', 'neutral', eller 'negative'
        date (datetime): Datoen reaksjonen gjelder for
    """
    try:
        reaction_mapping = {
            "positive": "😊 Fornøyd",
            "neutral": "😐 Nøytral",
            "negative": "😡 Misfornøyd",
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
            customer_id=customer_id,
            hidden=False,
        )

        if result:
            logger.info(
                f"Vedlikeholdsreaksjon lagret for hytte {customer_id}: {reaction_type}"
            )
        return result

    except Exception as e:
        logger.error(f"Feil ved lagring av vedlikeholdsreaksjon: {str(e)}")
        return False


def get_maintenance_reactions(start_datetime, end_datetime):
    try:
        query = """
        SELECT datetime, comment, customer_id
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

        reactions_df = pd.DataFrame(fetch_data(
            "feedback",
            query,
            [start_datetime, end_datetime]
        ))

        if not reactions_df.empty:
            # Konverter datetime til riktig format
            reactions_df['datetime'] = pd.to_datetime(reactions_df['datetime'])
            
            # Hent ut hyttenummer fra reaksjonsteksten
            reactions_df['customer_id'] = reactions_df['comment'].str.extract(r'Hytte (\d+)')

        return reactions_df

    except Exception as e:
        logger.error(f"Feil ved henting av vedlikeholdsreaksjoner: {str(e)}")
        return pd.DataFrame(columns=['datetime', 'customer_id', 'reaction'])

def display_maintenance_feedback():
    try:
        logger.debug("Starting display_maintenance_feedback")
        
        # Bruk den nye felles datovelger-funksjonen
        start_date, end_date = get_date_range_input()
        if start_date is None or end_date is None:
            st.warning("Vennligst velg gyldig datoperiode")
            return

        # Konverter til datetime med tidssone
        start_datetime = combine_date_with_tz(start_date)
        end_datetime = combine_date_with_tz(end_date, datetime.max.time())
        
        logger.debug(f"Henter data for periode: {start_datetime} til {end_datetime}")
        
        # Hent reaksjoner
        reactions_df = get_maintenance_reactions(start_datetime, end_datetime)
        
        if reactions_df.empty:
            st.info("Ingen tilbakemeldinger funnet i valgt periode")
            return
            
        return reactions_df
        
    except Exception as e:
        logger.error(f"Feil ved henting av vedlikeholdsreaksjoner: {str(e)}", exc_info=True)
        return pd.DataFrame()


def create_maintenance_chart(daily_stats, daily_stats_pct, daily_score, group_by):
    """Oppretter Plotly-figur for vedlikeholdsstatistikk"""
    try:
        logger.debug("Starting create_maintenance_chart")
        logger.debug(f"Gruppering: {group_by}")
        logger.debug(f"Antall datapunkter: {len(daily_stats)}")
        
        fig = go.Figure()

        colors = {
            "😊 Fornøyd": "#2ECC40",
            "😐 Nøytral": "#FF851B",
            "😡 Misfornøyd": "#FF4136",
        }

        # Legg til stolper for hver reaksjonstype
        for reaction in daily_stats.columns:
            if reaction in colors:  # Sjekk at vi har en gyldig reaksjonstype
                fig.add_trace(
                    go.Bar(
                        name=reaction,
                        x=daily_stats.index,
                        y=daily_stats_pct[reaction],
                        marker_color=colors[reaction],
                        hovertemplate=(
                            f"{reaction}<br>"
                            f"Periode: %{{x}}<br>"
                            f"Prosent: %{{y:.1f}}%<br>"
                            f"Antall: {daily_stats[reaction]}"
                            "<extra></extra>"
                        )
                    )
                )

        # Legg til score-linje
        fig.add_trace(
            go.Scatter(
                name="Score",
                x=daily_score.index,
                y=daily_score,
                yaxis="y2",
                line=dict(color="#000000", width=2),
                hovertemplate="Score: %{y:.2f}<extra></extra>"
            )
        )
        # Oppdater layout
        fig.update_layout(
            barmode='stack',
            yaxis=dict(
                title="Prosent",
                tickformat=".0%",
                range=[0, 100]
            ),
            yaxis2=dict(
                title="Score",
                overlaying="y",
                side="right",
                range=[0, 1],
                tickformat=".2f"
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            margin=dict(t=30),
            height=400
        )

        logger.debug("Chart created successfully")
        return fig
        
    except Exception as e:
        logger.error(f"Feil ved opprettelse av vedlikeholdsgraf: {str(e)}", exc_info=True)
        st.error("Kunne ikke opprette graf")
        return None


def display_maintenance_summary(daily_stats, daily_stats_pct, daily_score, group_by='day'):
    """
    Viser oppsummering av vedlikeholdsstatistikk
    
    Args:
        daily_stats (pd.DataFrame): Daglig statistikk
        daily_stats_pct (pd.DataFrame): Prosentvis fordeling
        daily_score (pd.Series): Score per dag
        group_by (str): Grupperingsperiode ('day', 'week', 'month')
    """
    try:
        logger.info("Starting display_maintenance_summary")
        logger.debug(f"daily_stats shape: {daily_stats.shape if not daily_stats.empty else 'Empty'}")
        logger.debug(f"group_by: {group_by}")
        
        if daily_stats.empty:
            st.info("Ingen vedlikeholdsdata tilgjengelig")
            return
            
        # Vis statistikk basert på grupperingsperiode
        periode = {
            'day': 'dagen',
            'week': 'uken',
            'month': 'måneden'
        }.get(group_by, 'perioden')
        
        st.subheader(f"📊 Statistikk for {periode}")
        
        # Vis total statistikk
        total_reactions = daily_stats.sum().sum()
        st.write(f"Totalt antall reaksjoner: {total_reactions}")
        
        # Beregn gjennomsnittlige prosenter
        avg_stats = daily_stats_pct.mean()
        
        # Vis prosentvis fordeling i kolonner med fargekodet metrikk
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "😊 Fornøyd", 
                f"{avg_stats['😊 Fornøyd']:.1f}%",
                delta=None,
                delta_color="normal"
            )
            
        with col2:
            st.metric(
                "😐 Nøytral", 
                f"{avg_stats['😐 Nøytral']:.1f}%",
                delta=None,
                delta_color="normal"
            )
            
        with col3:
            st.metric(
                "😡 Misfornøyd", 
                f"{avg_stats['😡 Misfornøyd']:.1f}%",
                delta=None,
                delta_color="inverse"
            )
            
        # Vis gjennomsnittlig score
        st.metric(
            "Gjennomsnittlig score",
            f"{daily_score.mean():.2f}",
            delta=None,
            delta_color="normal"
        )
        
        # Vis detaljert statistikk i en tabell
        st.subheader("Detaljert statistikk")
        summary_df = pd.DataFrame({
            'Dato': daily_stats.index,
            'Fornøyd': daily_stats['😊 Fornøyd'],
            'Nøytral': daily_stats['😐 Nøytral'],
            'Misfornøyd': daily_stats['😡 Misfornøyd'],
            'Total': daily_stats.sum(axis=1),
            'Score': daily_score.round(2)
        })
        
        st.dataframe(
            summary_df,
            column_config={
                'Dato': st.column_config.TextColumn('Dato'),
                'Fornøyd': st.column_config.NumberColumn('😊', format="%d"),
                'Nøytral': st.column_config.NumberColumn('😐', format="%d"),
                'Misfornøyd': st.column_config.NumberColumn('😡', format="%d"),
                'Score': st.column_config.ProgressColumn(
                    'Score',
                    help='Score (0-1)',
                    format="%.2f",
                    min_value=0,
                    max_value=1
                )
            },
            use_container_width=True,
            hide_index=True
        )
            
    except Exception as e:
        logger.error(f"Error in display_maintenance_summary: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise vedlikeholdsoppsummering")

def calculate_maintenance_stats(reactions_df, group_by='day', days_back=7):
    """Beregner vedlikeholdsstatistikk med fargekodet visning"""
    try:
        logger.debug(f"Calculating maintenance stats for last {days_back} days")
        
        if reactions_df.empty:
            st.info("Ingen vedlikeholdsdata tilgjengelig")
            return pd.DataFrame(), pd.DataFrame(), pd.Series()
            
        # Filtrer for siste X dager
        end_date = get_current_time()
        start_date = end_date - timedelta(days=days_back)
        
        reactions_df = reactions_df.copy()
        reactions_df['datetime'] = pd.to_datetime(reactions_df['datetime'])
        mask = (reactions_df['datetime'] >= start_date) & (reactions_df['datetime'] <= end_date)
        reactions_df = reactions_df[mask]
        
        if reactions_df.empty:
            st.info(f"Ingen data for siste {days_back} dager")
            return pd.DataFrame(), pd.DataFrame(), pd.Series()
            
        # Grupper etter dato
        reactions_df['date'] = reactions_df['datetime'].dt.date
        
        # Tell reaksjoner per dag
        daily_stats = pd.DataFrame({
            'Dato': pd.date_range(start=start_date.date(), end=end_date.date()),
            'Fornøyd': 0,
            'Nøytral': 0,
            'Misfornøyd': 0
        }).set_index('Dato')
        
        # Oppdater med faktiske tall
        for date, group in reactions_df.groupby('date'):
            daily_stats.loc[date, 'Fornøyd'] = group['comment'].str.count('😊').sum()
            daily_stats.loc[date, 'Nøytral'] = group['comment'].str.count('😐').sum()
            daily_stats.loc[date, 'Misfornøyd'] = group['comment'].str.count('😡').sum()
        
        # Beregn totaler og score
        daily_stats['Total'] = daily_stats.sum(axis=1)
        daily_stats['Score'] = (
            (daily_stats['Fornøyd'] * 1.0 + daily_stats['Nøytral'] * 0.5) / 
            daily_stats['Total']
        ).fillna(0)
        
        # Formater datoer for visning
        display_df = daily_stats.reset_index()
        display_df['Dato'] = display_df['Dato'].dt.strftime('%d.%m')
        
        # Vis statistikk med fargeformatering
        st.dataframe(
            display_df,
            column_config={
                'Dato': st.column_config.TextColumn('Dato'),
                'Fornøyd': st.column_config.NumberColumn(
                    '😊',
                    help='Antall fornøyde tilbakemeldinger',
                    format='%d'
                ),
                'Nøytral': st.column_config.NumberColumn(
                    '😐',
                    help='Antall nøytrale tilbakemeldinger',
                    format='%d'
                ),
                'Misfornøyd': st.column_config.NumberColumn(
                    '😡',
                    help='Antall misfornøyde tilbakemeldinger',
                    format='%d'
                ),
                'Score': st.column_config.ProgressColumn(
                    'Score',
                    help='Score (0-1)',
                    format='%.2f',
                    min_value=0,
                    max_value=1
                )
            },
            use_container_width=True,
            hide_index=True
        )
        
        return daily_stats, daily_stats / daily_stats['Total'].values.reshape(-1, 1), daily_stats['Score']
        
    except Exception as e:
        logger.error(f"Feil ved beregning av vedlikeholdsstatistikk: {str(e)}", exc_info=True)
        return pd.DataFrame(), pd.DataFrame(), pd.Series()

def display_reaction_statistics(feedback_data):
    try:
        logger.debug("Starting display_reaction_statistics")
        
        if feedback_data.empty:
            st.info("Ingen data tilgjengelig for statistikk")
            return
            
        # Filtrer for reaksjoner
        reactions = feedback_data[
            feedback_data['type'] == 'Vintervedlikehold'
        ].copy()
        
        logger.debug(f"Filtrerte reaksjoner: {len(reactions)} rader")
        logger.debug(f"Kolonner: {reactions.columns.tolist()}")
        
        if reactions.empty:
            st.info("Ingen reaksjoner funnet")
            return
            
        # Bruk customer_id-kolonnen direkte som hytte_nr
        stats = reactions.groupby('customer_id').size().reset_index(name='antall')
        stats.columns = ['Hytte', 'Antall reaksjoner']
        stats = stats.sort_values('Antall reaksjoner', ascending=False)
        
        logger.debug(f"Statistikk generert: {len(stats)} hytter")
        logger.debug(f"Første rad: {stats.iloc[0].to_dict() if not stats.empty else 'Tom DataFrame'}")
        
        st.subheader("Reaksjoner per hytte")
        st.dataframe(stats)
        
    except Exception as e:
        logger.error(f"Feil ved visning av reaksjonsstatistikk: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise statistikk")


# feedback_utils.py

def display_feedback_overview(feedback_data):
    """
    Viser feedback-oversikt med nedlastingsmuligheter.
    Håndterer tidssoner korrekt for Excel-eksport.
    """
    try:
        logger.debug("Starting display_feedback_overview")
        
        if feedback_data.empty:
            st.info("Ingen feedback å vise")
            return
            
        # Lag en kopi for eksport og visning
        export_data = feedback_data.copy()
        
        # Konverter datetime-kolonner til timezone-naive for Excel
        datetime_columns = ['datetime', 'status_changed_at', 'expiry_date']
        for col in datetime_columns:
            if col in export_data.columns:
                # Sjekk om kolonnen er datetime og har tidssone
                if pd.api.types.is_datetime64_any_dtype(export_data[col]):
                    # Konverter til lokal tid og fjern tidssone
                    export_data[col] = export_data[col].dt.tz_convert(TZ).dt.tz_localize(None)
        
        # Vis nedlastingsknapper
        st.subheader("Last ned data")
        col1, col2 = st.columns(2)
        
        with col1:
            csv = export_data.to_csv(index=False)
            st.download_button(
                label="📥 Last ned som CSV",
                data=csv,
                file_name="feedback_oversikt.csv",
                mime="text/csv",
                key=f"download_csv_{id(csv)}"
            )
            
        with col2:
            buffer = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                feedback_data.to_excel(writer, sheet_name="Feedback", index=False)
            excel_data = output.getvalue()
            st.download_button(
                label="📊 Last ned Excel",
                data=excel_data,
                file_name="feedback.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                key=f"download_excel_{id(excel_data)}"
            )
    
        # Vis feedback i expanders - bruker original data for visning
        st.subheader("Feedback oversikt")
        for _, row in feedback_data.iterrows():
            # Formatering av dato med tidssone
            date_str = format_date(row['datetime'], DATE_FORMATS['display']['datetime']) if pd.notnull(row['datetime']) else "Ukjent dato"
            
            with st.expander(
                f"{row['type']} - {date_str} - Status: {row['status']}"
            ):
                st.write(f"**Kommentar:** {row['comment']}")
                st.write(f"**Innsender:** {row['customer_id']}")
                st.write(f"**Type:** {row['type']}")
                
                if pd.notnull(row['status_changed_at']):
                    changed_date = format_date(row['status_changed_at'], DATE_FORMATS['display']['datetime'])
                    st.write(f"**Sist oppdatert:** {changed_date}")
                    if pd.notnull(row['status_changed_by']):
                        st.write(f"**Oppdatert av:** {row['status_changed_by']}")
                        
    except Exception as e:
        logger.error(f"Feil i display_feedback_overview: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise feedback-oversikt")

def display_reaction_report(feedback_data):
    try:
        logger.debug("Starting display_reaction_report")
        
        reactions = feedback_data[feedback_data['type'] == 'Vintervedlikehold'].copy()
        if reactions.empty:
            st.info("Ingen reaksjoner å vise")
            return
            
        # Vis graf først
        st.subheader("Reaksjoner over tid")
        
        # Gruppering-selector
        group_by = st.selectbox(
            "Gruppér etter",
            options=['day', 'week', 'month'],
            format_func=lambda x: {'day': 'Dag', 'week': 'Uke', 'month': 'Måned'}[x],
            index=0
        )
        
        # Beregn statistikk med standard periode
        default_start, default_end = get_date_range_defaults(DATE_VALIDATION["default_date_range"])
        daily_stats, daily_stats_pct, daily_score = calculate_maintenance_stats(
            reactions, 
            group_by=group_by,
            days_back=DATE_VALIDATION["default_date_range"]
        )
        
        if not daily_stats.empty:
            fig = create_maintenance_chart(daily_stats, daily_stats_pct, daily_score, group_by)
            st.plotly_chart(fig, use_container_width=True)
        
        # Datofilter under grafen
        start_date, end_date = get_date_range_input()
        if start_date is None or end_date is None:
            st.warning("Vennligst velg gyldig datoperiode")
            return
            
        # Konverter datoer og filtrer data
        start_datetime = combine_date_with_tz(start_date)
        end_datetime = combine_date_with_tz(end_date, datetime.max.time())
        
        mask = (reactions['datetime'] >= start_datetime) & (reactions['datetime'] <= end_datetime)
        filtered_reactions = reactions[mask]
        
        if filtered_reactions.empty:
            st.info("Ingen reaksjoner i valgt periode")
            return
            
        # Vis reaksjoner i expanders
        st.subheader("Detaljerte reaksjoner")
        for _, row in filtered_reactions.iterrows():
            with st.expander(f"{row['datetime'].strftime('%Y-%m-%d %H:%M')} - Hytte {row['customer_id']}"):
                st.write(f"**Kommentar:** {row['comment']}")
                st.write(f"**Innsender:** {row['customer_id']}")
                
    except Exception as e:
        logger.error(f"Feil i display_reaction_report: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise reaksjonsrapport")


def calculate_maintenance_stats(reactions_df, group_by='day', days_back=DATE_VALIDATION["default_date_range"]):
    """
    Beregner statistikk for vedlikeholdsreaksjoner.
    
    Args:
        reactions_df (pd.DataFrame): DataFrame med reaksjoner
        group_by (str): Gruppering ('day', 'week', 'month')
        days_back (int): Antall dager bakover i tid
        
    Returns:
        tuple[pd.DataFrame, pd.DataFrame, pd.Series]: (daily_stats, daily_stats_pct, daily_score)
    """
    try:
        logger.debug(f"Calculating maintenance stats grouped by: {group_by}")
        logger.debug(f"Input DataFrame shape: {reactions_df.shape}")
        
        if reactions_df.empty:
            logger.warning("Tomt reactions_df datasett")
            return pd.DataFrame(), pd.DataFrame(), pd.Series()
            
        # Filtrer for siste X dager
        end_date = get_current_time()
        start_date = end_date - timedelta(days=days_back)
        
        reactions_df = reactions_df.copy()
        reactions_df['datetime'] = pd.to_datetime(reactions_df['datetime'])
        
        # Sikre at datetime har riktig tidssone
        if reactions_df['datetime'].dt.tz is None:
            reactions_df['datetime'] = reactions_df['datetime'].dt.tz_localize(TZ)
        else:
            reactions_df['datetime'] = reactions_df['datetime'].dt.tz_convert(TZ)
            
        mask = (reactions_df['datetime'] >= start_date) & (reactions_df['datetime'] <= end_date)
        reactions_df = reactions_df[mask]
        
        if reactions_df.empty:
            logger.warning(f"Ingen data for siste {days_back} dager")
            return pd.DataFrame(), pd.DataFrame(), pd.Series()
            
        # Definer grupperingsfunksjon basert på group_by
        if group_by == 'week':
            reactions_df['group'] = reactions_df['datetime'].dt.strftime('%Y-W%V')
        elif group_by == 'month':
            reactions_df['group'] = reactions_df['datetime'].dt.strftime('%Y-%m')
        else:  # default to day
            reactions_df['group'] = reactions_df['datetime'].dt.strftime(DATE_FORMATS['database']['date'])
            
        # Tell reaksjoner
        stats = pd.DataFrame({
            '😊 Fornøyd': reactions_df['comment'].str.count('😊'),
            '😐 Nøytral': reactions_df['comment'].str.count('😐'),
            '😡 Misfornøyd': reactions_df['comment'].str.count('😡')
        })
        
        # Grupper etter valgt periode
        daily_stats = stats.groupby(reactions_df['group']).sum()
        
        # Beregn prosenter
        daily_total = daily_stats.sum(axis=1)
        daily_stats_pct = daily_stats.div(daily_total, axis=0) * 100
        
        # Beregn score
        daily_score = (
            daily_stats['😊 Fornøyd'] * 1.0 + 
            daily_stats['😐 Nøytral'] * 0.5
        ) / daily_total
        
        # Vis statistikk i dataframe
        st.subheader("Statistikk oversikt")
        summary_df = pd.DataFrame({
            'Dato': daily_stats.index,
            'Fornøyd': daily_stats['😊 Fornøyd'],
            'Nøytral': daily_stats['😐 Nøytral'],
            'Misfornøyd': daily_stats['😡 Misfornøyd'],
            'Total': daily_total,
            'Score': daily_score.round(2)
        })
        st.dataframe(summary_df, use_container_width=True)
        
        return daily_stats, daily_stats_pct, daily_score
        
    except Exception as e:
        logger.error(f"Feil ved beregning av vedlikeholdsstatistikk: {str(e)}", exc_info=True)
        return pd.DataFrame(), pd.DataFrame(), pd.Series()

def display_daily_maintenance_rating():
    """Viser et enkelt skjema for å vurdere dagens brøyting"""
    try:
        st.subheader("Gi din vurdering av dagens brøyting her")
        
        if 'customer_id' not in st.session_state:
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
                st.session_state.customer_id,
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
        logger.error(f"Error in display_daily_maintenance_rating: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av tilbakemeldingsskjema")

def display_admin_dashboard():
    """
    Viser admin dashboard for feedback med omfattende oversikt, statistikk og rapporter.
    Bruker eksisterende funksjoner fra feedback_utils.
    """
    try:
        st.title("📊 Feedback Dashboard")
        logger.info("Starting display_admin_dashboard")
        
        # Bruk den eksisterende datovelger-funksjonen
        start_date, end_date = get_date_range_input(
            default_days=DATE_VALIDATION["default_date_range"]
        )
        
        if start_date is None or end_date is None:
            st.warning("Vennligst velg gyldig datoperiode")
            return
            
        # Konverter til datetime med tidssone
        start_datetime = combine_date_with_tz(start_date)
        end_datetime = combine_date_with_tz(end_date, datetime.max.time())
        logger.debug(f"Valgt periode: {start_datetime} til {end_datetime}")
        
        # Hovedtabs for ulike visninger
        tab1, tab2, tab3 = st.tabs([
            "🔍 Oversikt og Feedback", 
            "🚜 Vedlikeholdsanalyse", 
            "📝 Rapporter"
        ])
        
        # Hent feedback data én gang
        feedback_data = get_feedback(
            start_date=start_datetime,
            end_date=end_datetime,
            include_hidden=True
        )
        
        # === Tab 1: Oversikt og Feedback ===
        with tab1:
            st.subheader("📊 Statistikk og Feedback")
            if feedback_data.empty:
                st.info("Ingen feedback-data tilgjengelig for valgt periode")
            else:
                # Bruk eksisterende get_feedback_statistics
                stats = get_feedback_statistics(start_datetime, end_datetime)
                if stats:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric(
                            "Totalt antall", 
                            stats["total_count"],
                            help="Totalt antall tilbakemeldinger i perioden"
                        )
                    with col2:
                        st.metric(
                            "Unike innsendere", 
                            len(feedback_data['customer_id'].unique()),
                            help="Antall unike hytter som har gitt tilbakemelding"
                        )
                    with col3:
                        new_cases = len(feedback_data[feedback_data['status']=='Ny'])
                        st.metric(
                            "Åpne saker", 
                            new_cases,
                            help="Antall ubehandlede tilbakemeldinger"
                        )
                
                # Vis feedback oversikt med eksisterende funksjon
                display_feedback_overview(feedback_data)
                
        # === Tab 2: Vedlikeholdsanalyse ===
        with tab2:
            st.subheader("🚜 Vedlikeholdsanalyse")
            # Bruk eksisterende display_maintenance_report
            reactions_df = display_maintenance_feedback()
            
            if reactions_df is not None and not reactions_df.empty:
                # Bruk eksisterende funksjoner for å vise statistikk
                daily_stats, daily_stats_pct, daily_score = calculate_maintenance_stats(
                    reactions_df,
                    group_by='day'
                )
                
                if not daily_stats.empty:
                    # Vis vedlikeholdssammendrag med eksisterende funksjon
                    display_maintenance_summary(
                        daily_stats,
                        daily_stats_pct,
                        daily_score,
                        'day'
                    )
                    
                    # Vis detaljer med eksisterende funksjon
                    st.subheader("Detaljert vedlikeholdsstatistikk")
                    display_reaction_statistics(reactions_df)
                    
                    # Vis reaksjonsrapport med eksisterende funksjon
                    display_reaction_report(reactions_df)
            else:
                st.info("Ingen vedlikeholdsdata tilgjengelig for valgt periode")
        
        # === Tab 3: Rapporter ===
        with tab3:
            st.subheader("📝 Rapporter og Detaljer")
            
            if not feedback_data.empty:
                # La brukeren filtrere på type
                feedback_types = ["Alle"] + list(FEEDBACK_ICONS.keys())
                selected_type = st.selectbox("Filtrer på type:", feedback_types)
                
                # Filtrer data hvis nødvendig
                filtered_data = feedback_data
                if selected_type != "Alle":
                    filtered_data = feedback_data[feedback_data['type'] == selected_type]
                
                # Vis filtrert data med eksisterende funksjon
                #display_feedback_overview(filtered_data)
                
                # Generer og vis rapport med eksisterende funksjon
                report = generate_feedback_report(start_datetime, end_datetime)
                if report:
                    st.download_button(
                        "Last ned rapport",
                        report,
                        "feedback_report.txt",
                        "text/plain"
                    )
            else:
                st.info("Ingen rapportdata tilgjengelig for valgt periode")
        
    except Exception as e:
        logger.error(f"Feil i display_admin_dashboard: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av feedback-dashboard")

def display_feedback_overview(feedback_data):
    """
    Viser feedback-oversikt med nedlastingsmuligheter.
    """
    try:
        logger.debug("Starting display_feedback_overview")
        
        if feedback_data.empty:
            st.info("Ingen feedback å vise")
            return
            
        # Lag en kopi for eksport
        export_data = feedback_data.copy()
        
        # Konverter datetime-kolonner til timezone-naive for Excel
        datetime_columns = ['datetime', 'status_changed_at', 'expiry_date']
        for col in datetime_columns:
            if col in export_data.columns and not export_data[col].empty:
                if pd.api.types.is_datetime64_any_dtype(export_data[col]):
                    export_data[col] = export_data[col].dt.tz_convert(TZ).dt.tz_localize(None)
        
        # Nedlastingsknapper
        st.subheader("Last ned data")
        col1, col2 = st.columns(2)
        
        with col1:
            csv = export_data.to_csv(index=False)
            st.download_button(
                label="📥 Last ned som CSV",
                data=csv,
                file_name="feedback_oversikt.csv",
                mime="text/csv"
            )
            
        with col2:
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                export_data.to_excel(writer, sheet_name="Feedback", index=False)
            
            st.download_button(
                label="📊 Last ned som Excel",
                data=buffer.getvalue(),
                file_name="feedback_oversikt.xlsx",
                mime="application/vnd.ms-excel"
            )
        
        # Vis feedback i expanders
        st.subheader("Feedback oversikt")
        for _, row in feedback_data.iterrows():
            # Bruk standardisert datoformat fra config
            date_format = get_date_format("display", "datetime")
            
            try:
                date_str = row['datetime'].strftime(date_format) if pd.notnull(row['datetime']) else "Ukjent dato"
            except Exception as e:
                logger.warning(f"Kunne ikke formatere dato: {str(e)}")
                date_str = "Ukjent dato"
            
            with st.expander(
                f"{row['type']} - {date_str} - Status: {row['status']}"
            ):
                st.write(f"**Kommentar:** {row['comment']}")
                st.write(f"**Innsender:** {row['customer_id']}")
                st.write(f"**Type:** {row['type']}")
                
                if pd.notnull(row['status_changed_at']):
                    try:
                        changed_date = row['status_changed_at'].strftime(date_format)
                        st.write(f"**Sist oppdatert:** {changed_date}")
                    except:
                        st.write("**Sist oppdatert:** Ukjent tidspunkt")
                    
                    if pd.notnull(row['status_changed_by']):
                        st.write(f"**Oppdatert av:** {row['status_changed_by']}")
                        
    except Exception as e:
        logger.error(f"Feil i display_feedback_overview: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise feedback-oversikt")
        
def display_maintenance_tab(feedback_data):
    """Viser vedlikeholdsfanen med statistikk og oversikt"""
    try:
        logger.debug("Starting display_maintenance_tab")
        st.subheader("Vedlikehold")
        
        # Filtrer for vedlikeholdsrelatert feedback
        maintenance_data = feedback_data[
            feedback_data['type'].str.contains('vedlikehold', case=False, na=False)
        ].copy()
        
        if maintenance_data.empty:
            st.info("Ingen vedlikeholdsrelatert feedback funnet")
            return
            
        # Vis statistikk
        tab1, tab2 = st.tabs(["📊 Statistikk", "📝 Detaljer"])
        
        with tab1:
            # Gruppering-selector
            group_by = st.selectbox(
                "Gruppér etter",
                options=['day', 'week', 'month'],
                format_func=lambda x: {'day': 'Dag', 'week': 'Uke', 'month': 'Måned'}[x],
                index=0
            )
            
            daily_stats, daily_stats_pct, daily_score = calculate_maintenance_stats(maintenance_data, group_by)
            if not daily_stats.empty:
                fig = create_maintenance_chart(daily_stats, daily_stats_pct, daily_score, group_by)
                st.plotly_chart(fig, use_container_width=True)
                
                display_maintenance_summary(daily_stats, daily_score, group_by)
                
        with tab2:
            # Vis detaljert feedback
            for _, row in maintenance_data.iterrows():
                date_str = row['datetime'].strftime(DATE_FORMATS['display']['datetime']) if pd.notnull(row['datetime']) else "Ukjent dato"
                
                with st.expander(f"{date_str} - Hytte {row['customer_id']}"):
                    st.write(f"**Kommentar:** {row['comment']}")
                    st.write(f"**Status:** {row['status']}")
                    
    except Exception as e:
        logger.error(f"Feil i display_maintenance_tab: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise vedlikeholdsfanen")

def display_feedback_dashboard():
    try:
        logger.info("Starting display_feedback_dashboard")
        st.header("📬 Feedback Oversikt")
        
        # Hent standardperiode for siste 7 dager
        default_start, default_end = get_date_range_defaults(7)
        
        # Hent først all feedback for reactions statistikk
        all_feedback = get_feedback(
            start_date=combine_date_with_tz(default_start),
            end_date=combine_date_with_tz(default_end, datetime.max.time()),
            include_hidden=False
        )
        
        # Vis statistikk i kolonner
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.subheader("🚜 Vedlikehold siste 7 dager")
            maintenance_data = all_feedback[
                all_feedback['type'].str.contains('vedlikehold', case=False, na=False)
            ].copy()
            
            if not maintenance_data.empty:
                daily_stats, _, _ = calculate_maintenance_stats(
                    maintenance_data, 
                    group_by='day', 
                    days_back=7
                )
            else:
                st.info("Ingen vedlikeholdsdata for perioden")
        
        st.write("---")
        
        # Filtre for hovedoversikt
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        
        with filter_col1:
            start_date, end_date = get_date_range_input()
            if start_date is None or end_date is None:
                st.warning("Vennligst velg gyldig datoperiode")
                return
            
        with filter_col2:
            feedback_types = ["Alle"] + list(FEEDBACK_ICONS.keys())
            selected_type = st.selectbox("Type", feedback_types)
            
        with filter_col3:
            include_hidden = st.checkbox("Vis skjult", value=False)
            
        # Hent og vis filtrert data
        feedback_data = get_filtered_feedback(start_date, end_date, selected_type, include_hidden)
        
        if feedback_data is not None and not feedback_data.empty:
            display_feedback_table(feedback_data)
        else:
            st.info("Ingen feedback funnet i valgt periode")
            
    except Exception as e:
        logger.error(f"Feil i feedback oversikt: {str(e)}")
        st.error("Kunne ikke vise feedback oversikt")

# Hjelpefunksjoner
def get_filtered_feedback(start_date, end_date, feedback_type, include_hidden):
    """
    Henter filtrert feedback fra databasen
    
    Args:
        start_date (date): Startdato for filtrering
        end_date (date): Sluttdato for filtrering
        feedback_type (str): Type feedback å filtrere på
        include_hidden (bool): Om skjulte elementer skal inkluderes
        
    Returns:
        pd.DataFrame: Filtrert feedback data
    """
    try:
        logger.debug(f"Getting filtered feedback for period: {start_date} to {end_date}")
        
        # Konverter datoer til datetime med tidssone
        start_datetime = combine_date_with_tz(start_date)
        end_datetime = combine_date_with_tz(end_date, datetime.max.time())
        
        # Hent data og lag en eksplisitt kopi
        feedback_data = get_feedback(
            start_date=start_datetime,
            end_date=end_datetime,
            include_hidden=include_hidden
        ).copy()
        
        if feedback_type != "Alle":
            # Bruk .loc for å unngå SettingWithCopyWarning
            feedback_data = feedback_data.loc[feedback_data['type'] == feedback_type]
            
        logger.debug(f"Retrieved {len(feedback_data)} feedback entries")
        return feedback_data
        
    except Exception as e:
        logger.error(f"Error in get_filtered_feedback: {str(e)}", exc_info=True)
        return pd.DataFrame()

def display_feedback_table(feedback_data):
    """Viser feedback-tabell med nedlastingsmuligheter"""
    try:
        if feedback_data.empty:
            st.info("Ingen feedback funnet i valgt periode")
            return
            
        # Lag en kopi for visning og eksport
        display_data = feedback_data.copy()
        
        # Konverter datetime-kolonner til timezone-naive
        datetime_columns = display_data.select_dtypes(include=['datetime64[ns, UTC]']).columns
        for col in datetime_columns:
            display_data[col] = pd.to_datetime(display_data[col]).dt.tz_localize(None)
        
        # Vis tabell
        st.dataframe(
            display_data[[
                'datetime', 'type', 'comment', 'status', 
                'customer_id', 'status_changed_at'
            ]],
            use_container_width=True
        )
        
        # Nedlastingsknapper bruker pandas direkte
        col1, col2 = st.columns(2)
        with col1:
            csv = display_data.to_csv(index=False)
            st.download_button(
                "📥 Last ned CSV",
                csv,
                "feedback.csv",
                "text/csv"
            )
        with col2:
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                display_data.to_excel(writer, index=False)
            st.download_button(
                "📊 Last ned Excel",
                buffer.getvalue(),
                "feedback.xlsx",
                "application/vnd.ms-excel"
            )
            
    except Exception as e:
        logger.error(f"Feil ved visning av feedback-tabell: {str(e)}")
        st.error("Kunne ikke vise feedback-oversikt")
def display_maintenance_chart(data):
    """Viser vedlikeholdsgraf"""
    try:
        if data.empty:
            st.info("Ingen data tilgjengelig for grafen")
            return
            
        # Implementer grafvisning
        st.line_chart(data)
    except Exception as e:
        logger.error(f"Feil ved visning av vedlikeholdsgraf: {str(e)}")

