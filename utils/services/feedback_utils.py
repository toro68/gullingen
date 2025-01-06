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
from typing import Optional
import streamlit as st

from utils.core.config import (
    TZ,
    DATE_FORMATS,
    get_date_format,
    get_current_time,
    combine_date_with_tz,
    format_date,
    ensure_tz_datetime,
    get_date_range_defaults,
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
    Lagrer feedback med korrekt tidssonebehandling
    """
    try:
        # Konverter datetime_str til datetime med tidssone
        feedback_dt = pd.to_datetime(datetime_str)
        if feedback_dt.tzinfo is None:
            feedback_dt = feedback_dt.tz_localize(TZ)
        else:
            feedback_dt = feedback_dt.tz_convert(TZ)
            
        current_time = get_current_time()
        
        query = """INSERT INTO feedback 
                  (type, datetime, comment, customer_id, status, status_changed_at, hidden) 
                  VALUES (?, ?, ?, ?, ?, ?, ?)"""
                  
        params = (
            feedback_type,
            feedback_dt.isoformat(),
            comment,
            customer_id,
            "Ny",
            current_time.isoformat(),
            hidden
        )
        
        execute_query("feedback", query, params)
        
        logger.info(f"Feedback saved: {feedback_type}, {feedback_dt}, Customer: {customer_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving feedback: {str(e)}", exc_info=True)
        return False


def get_feedback(start_date=None, end_date=None, include_hidden=False) -> pd.DataFrame:
    """
    Henter feedback fra databasen
    
    Args:
        start_date: Valgfri start dato for filtrering
        end_date: Valgfri slutt dato for filtrering
        include_hidden: Om skjulte tilbakemeldinger skal inkluderes
        
    Returns:
        pd.DataFrame: DataFrame med feedback data
    """
    try:
        with get_db_connection("feedback") as conn:
            query = """
                SELECT *
                FROM feedback
                WHERE 1=1
                """
            params = []
            
            if not include_hidden:
                query += " AND (hidden IS NULL OR hidden = 0)"
                
            if start_date:
                query += " AND datetime >= ?"
                params.append(start_date)
            if end_date:
                query += " AND datetime <= ?"
                params.append(end_date)

            df = pd.read_sql_query(query, conn, params=params)
            
            # Konverter datokolonner med mer fleksibel parsing
            date_columns = ['datetime', 'status_changed_at']
            for col in date_columns:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], format='mixed', utc=True).dt.tz_convert(TZ)
            
            return df

    except Exception as e:
        logger.error(f"Error fetching feedback: {str(e)}", exc_info=True)
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
            include_hidden=False
        )
        
        st.info(
            """
    Her kan du gi tilbakemeldinger, melde avvik eller komme med forslag til forbedringer. Velg type feedback fra menyen nedenfor. 
    """
        )

        st.link_button(
            "🔗 Klikk her for å gi en mer detaljert tilbakemelding",
            "https://docs.google.com/forms/d/e/1FAIpQLSf6vVjQy1H4Alfac3_qMl1QtEOyG4_KykRsX0R5w9R-qtcS3A/viewform",
            use_container_width=True,
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
                    avvik_tidspunkt = ensure_tz_datetime(avvik_tidspunkt)
                    description = (
                        f"Tidspunkt for avvik: {format_date(avvik_tidspunkt, 'display', 'datetime')}\n\n"
                        + description
                    )

                feedback_datetime = avvik_tidspunkt if avvik_tidspunkt else get_current_time()
                
                result = save_feedback(
                    feedback_type,
                    feedback_datetime.isoformat(),
                    description,
                    customer_id,
                    hidden=False
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
                include_hidden=False
            )
            # Filtrer på customer_id etter henting
            existing_feedback = existing_feedback[
                existing_feedback['customer_id'] == customer_id
            ]
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
            logger.error(f"Error in give_feedback: {str(e)}", exc_info=True)
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

def get_feedback_statistics(start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> dict:
    """
    Henter statistikk for feedback i gitt periode.
    
    Args:
        start_date: Start dato for filtrering
        end_date: Slutt dato for filtrering
        
    Returns:
        dict: Statistikk for feedback
    """
    try:
        logger.debug(f"Getting feedback statistics from {start_date} to {end_date}")
        
        # Hent feedback data
        feedback_data = get_feedback(start_date, end_date)
        
        if feedback_data.empty:
            logger.warning("No feedback data found for statistics")
            return {
                "total_count": 0,
                "type_distribution": {},
                "status_distribution": {},
                "daily_counts": {},
                "average_per_day": 0
            }
            
        # Sjekk og standardiser kolonnenavn
        expected_columns = ['type', 'status', 'datetime']
        for col in expected_columns:
            if col not in feedback_data.columns:
                logger.error(f"Missing required column: {col}")
                logger.debug(f"Available columns: {feedback_data.columns.tolist()}")
                return {
                    "total_count": len(feedback_data),
                    "type_distribution": {},
                    "status_distribution": {},
                    "daily_counts": {},
                    "average_per_day": 0
                }
        
        # Beregn statistikk
        stats = {
            "total_count": len(feedback_data),
            "type_distribution": (
                feedback_data["type"].value_counts().to_dict() 
                if "type" in feedback_data.columns else {}
            ),
            "status_distribution": (
                feedback_data["status"].value_counts().to_dict()
                if "status" in feedback_data.columns else {}
            )
        }
        
        # Beregn daglig statistikk
        if "datetime" in feedback_data.columns:
            daily_counts = (
                feedback_data.set_index("datetime")
                .resample("D")
                .size()
                .fillna(0)
            )
            stats["daily_counts"] = daily_counts.to_dict()
            
            # Beregn gjennomsnitt per dag
            date_range = (end_date - start_date).days + 1
            stats["average_per_day"] = len(feedback_data) / max(date_range, 1)
        else:
            stats["daily_counts"] = {}
            stats["average_per_day"] = 0
            
        logger.debug(f"Calculated statistics: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"Error calculating feedback statistics: {str(e)}", exc_info=True)
        return {
            "total_count": 0,
            "type_distribution": {},
            "status_distribution": {},
            "daily_counts": {},
            "average_per_day": 0
        }


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
        comment = reaction_mapping[reaction_type]
        
        # Sikre at datoen har tidssone
        if date.tzinfo is None:
            date = date.replace(tzinfo=TZ)
        
        logger.debug(
            f"Lagrer reaksjon - Type: {feedback_type}, "
            f"Kommentar: {comment}, Kunde: {customer_id}, "
            f"Dato: {date.isoformat()}"
        )

        result = save_feedback(
            feedback_type=feedback_type,
            datetime_str=date.isoformat(),
            comment=comment,
            customer_id=customer_id,
            hidden=False
        )

        if result:
            logger.info(f"Vedlikeholdsreaksjon lagret for hytte {customer_id}: {reaction_type}")
            logger.debug("Lagring vellykket")
        else:
            logger.error("Lagring feilet")
        return result

    except Exception as e:
        logger.error(f"Feil ved lagring av vedlikeholdsreaksjon: {str(e)}", exc_info=True)
        return False


def get_maintenance_reactions(start_date=None, end_date=None):
    """Henter vedlikeholdsreaksjoner for gitt periode"""
    logger.info("Henter vedlikeholdsreaksjoner med forbedret datetime-håndtering")
    try:
        logger.debug("Starting get_maintenance_reactions")
        logger.debug(f"Input parameters - start: {start_date}, end: {end_date}")
        
        # Sjekk at input er gyldig
        if not start_date or not end_date:
            logger.error("Manglende dato-parametere")
            return pd.DataFrame(columns=['datetime', 'customer_id', 'comment', 'type'])
            
        # Konverter datoer til ISO format med tidssone
        start_str = start_date.isoformat() if start_date else None
        end_str = end_date.isoformat() if end_date else None
        
        query = """
        SELECT datetime as datetime, comment, customer_id, type
        FROM feedback 
        WHERE type = 'Vintervedlikehold'
        AND datetime >= ?
        AND datetime <= ?
        AND (
            comment LIKE '%😊%' OR 
            comment LIKE '%😐%' OR 
            comment LIKE '%😡%'
        )
        ORDER BY datetime DESC
        """
        
        logger.debug(f"SQL Query: {query}")
        logger.debug(f"Parameters: start={start_str}, end={end_str}")

        # Hent data fra databasen
        with get_db_connection("feedback") as conn:
            cursor = conn.cursor()
            cursor.execute(query, [start_str, end_str])
            rows = cursor.fetchall()
            logger.debug(f"Rådata fra database (rows): {rows}")
            
            # Konverter til DataFrame med eksplisitte kolonnenavn
            reactions_df = pd.DataFrame(
                rows,
                columns=['datetime', 'comment', 'customer_id', 'type']
            )
            
            logger.debug(f"DataFrame før datetime konvertering:")
            logger.debug(f"Kolonner: {reactions_df.columns.tolist()}")
            logger.debug(f"Antall rader: {len(reactions_df)}")
            logger.debug(f"Første rad: {reactions_df.iloc[0].to_dict() if not reactions_df.empty else 'Ingen data'}")
            logger.debug(f"DataFrame info:")
            logger.debug(reactions_df.info())

            if not reactions_df.empty:
                # Konverter datetime til riktig format med samme metode som i get_feedback
                reactions_df['datetime'] = pd.to_datetime(
                    reactions_df['datetime'], 
                    format='mixed', 
                    utc=True
                ).dt.tz_convert(TZ)
                logger.debug(f"Data etter datetime konvertering:")
                logger.debug(f"Første rad: {reactions_df.iloc[0].to_dict()}")
                logger.debug(f"Unike kommentarer: {reactions_df['comment'].unique().tolist()}")

            return reactions_df

    except Exception as e:
        logger.error(f"Feil ved henting av vedlikeholdsreaksjoner: {str(e)}", exc_info=True)
        return pd.DataFrame(columns=['datetime', 'customer_id', 'comment', 'type'])

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
                f"{avg_stats[' Misfornøyd']:.1f}%",
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


def calculate_maintenance_stats(df, group_by='day', days_back=7):
    """
    Beregner statistikk for vedlikeholdsreaksjoner.
    
    Args:
        df (pd.DataFrame): DataFrame med reaksjoner
        group_by (str): 'day' eller 'week'
        days_back (int): Antall dager å se tilbake
        
    Returns:
        tuple: (daily_stats, daily_stats_pct, daily_score)
    """
    try:
        logger.debug(f"Calculating maintenance stats grouped by: {group_by}")
        logger.debug(f"Input DataFrame shape: {df.shape}")
        
        if df.empty:
            logger.warning("Tomt DataFrame, returnerer tomme statistikker")
            empty_df = pd.DataFrame(columns=['😊 Fornøyd', '😐 Nøytral', '😡 Misfornøyd'])
            return empty_df, empty_df, pd.Series(dtype=float)
            
        # Konverter datetime til riktig format hvis ikke allerede gjort
        if not pd.api.types.is_datetime64_any_dtype(df['datetime']):
            df['datetime'] = pd.to_datetime(df['datetime'])
            
        # Filtrer for siste X dager
        end_date = df['datetime'].max()
        start_date = end_date - pd.Timedelta(days=days_back)
        mask = (df['datetime'] >= start_date) & (df['datetime'] <= end_date)
        df = df[mask].copy()
        
        logger.debug(f"Filtrert DataFrame shape: {df.shape}")
        logger.debug(f"Dato range: {start_date} til {end_date}")
        
        if df.empty:
            logger.warning("Ingen data etter filtrering")
            empty_df = pd.DataFrame(columns=['😊 Fornøyd', '😐 Nøytral', '😡 Misfornøyd'])
            return empty_df, empty_df, pd.Series(dtype=float)
            
        # Grupper etter dag eller uke
        if group_by == 'day':
            df['group'] = df['datetime'].dt.date
        else:  # week
            df['group'] = df['datetime'].dt.isocalendar().week
            
        # Tell opp reaksjoner per gruppe
        daily_stats = pd.DataFrame({
            '😊 Fornøyd': df[df['comment'].str.contains('😊')].groupby('group').size(),
            '😐 Nøytral': df[df['comment'].str.contains('😐')].groupby('group').size(),
            '😡 Misfornøyd': df[df['comment'].str.contains('😡')].groupby('group').size()
        }).fillna(0)
        
        logger.debug(f"Statistikk per gruppe:\n{daily_stats}")
        
        # Beregn prosenter
        daily_totals = daily_stats.sum(axis=1)
        daily_stats_pct = daily_stats.div(daily_totals, axis=0) * 100
        
        # Beregn score (0-1)
        weights = {'😊 Fornøyd': 1, '😐 Nøytral': 0.5, '😡 Misfornøyd': 0}
        daily_score = pd.Series(0, index=daily_stats.index, dtype=float)
        
        for reaction, weight in weights.items():
            daily_score += daily_stats[reaction] * weight
            
        daily_score = daily_score / daily_totals
        
        return daily_stats, daily_stats_pct, daily_score
        
    except Exception as e:
        logger.error(f"Feil ved beregning av vedlikeholdsstatistikk: {str(e)}", exc_info=True)
        empty_df = pd.DataFrame(columns=['😊 Fornøyd', '😐 Nøytral', '😡 Misfornøyd'])
        return empty_df, empty_df, pd.Series(dtype=float)

def display_daily_maintenance_rating():
    """Viser dagens vedlikeholdsvurdering"""
    try:
        # Hent dagens reaksjoner
        end_date = get_current_time().replace(hour=23, minute=59, second=59)
        start_date = end_date.replace(hour=0, minute=0, second=0)
        
        logger.debug(f"Henter reaksjoner for periode: {start_date} til {end_date}")
        
        reactions = get_maintenance_reactions(start_date, end_date)
        num_reactions = len(reactions) if not reactions.empty else 0
        logger.debug(f"Antall reaksjoner funnet: {num_reactions}")
        
        # Vis reaksjonsknapper
        st.write("### Gi din vurdering av dagens brøyting")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("😊 Fornøyd", use_container_width=True):
                if save_maintenance_reaction(
                    st.session_state.get('customer_id'),
                    'positive',
                    get_current_time()
                ):
                    st.rerun()
                    
        with col2:
            if st.button("😐 Nøytral", use_container_width=True):
                if save_maintenance_reaction(
                    st.session_state.get('customer_id'),
                    'neutral',
                    get_current_time()
                ):
                    st.rerun()
                    
        with col3:
            if st.button("😡 Misfornøyd", use_container_width=True):
                if save_maintenance_reaction(
                    st.session_state.get('customer_id'),
                    'negative',
                    get_current_time()
                ):
                    st.rerun()
        
        st.link_button(
            "🔗 Klikk her for å gi en mer detaljert tilbakemelding",
            "https://docs.google.com/forms/d/e/1FAIpQLSf6vVjQy1H4Alfac3_qMl1QtEOyG4_KykRsX0R5w9R-qtcS3A/viewform",
            use_container_width=True,
        )

        if reactions.empty:
            st.info("Ingen tilbakemeldinger registrert for i dag")
            return
            
        # Beregn statistikk
        daily_stats, _, _ = calculate_maintenance_stats(
            reactions,
            group_by='day',
            days_back=1
        )
        
        # Vis statistikk
        if not daily_stats.empty:
            st.write("### Dagens vurdering")
            
            # Vis antall reaksjoner
            col1, col2, col3 = st.columns(3)
            
            with col1:
                positive_count = int(daily_stats.iloc[-1]['😊 Fornøyd'])
                st.metric("😊 Fornøyd", str(positive_count))
                
            with col2:
                neutral_count = int(daily_stats.iloc[-1]['😐 Nøytral'])
                st.metric("😐 Nøytral", str(neutral_count))
                
            with col3:
                negative_count = int(daily_stats.iloc[-1]['😡 Misfornøyd'])
                st.metric("😡 Misfornøyd", str(negative_count))
                
            # Vis totalt antall
            st.caption(f"Totalt antall tilbakemeldinger: {num_reactions}")
            
        else:
            st.info("Ingen statistikk tilgjengelig for i dag")
            
    except Exception as e:
        logger.error(f"Feil ved visning av dagens vurdering: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise dagens vurdering")

def display_admin_dashboard():
    """Viser admin dashboard for feedback"""
    try:
        st.title("Feedback Dashboard")
        
        # Legg til datovelger
        start_date, end_date = get_date_range_input(
            default_days=DATE_VALIDATION["default_date_range"],
            key_prefix="feedback_dashboard_"  # Unikt prefiks for denne komponenten
        )
        
        if start_date is None or end_date is None:
            st.warning("Vennligst velg gyldig datoperiode")
            return
            
        # Hent filtrert feedback basert på valgt datoperiode
        feedback_data = get_feedback(
            start_date=combine_date_with_tz(start_date),
            end_date=combine_date_with_tz(end_date, datetime.max.time()),
            include_hidden=True
        )
        
        if feedback_data.empty:
            st.info("Ingen tilbakemeldinger å vise i valgt periode")
            return
            
        # Vis feedback oversikt med tittel
        display_feedback_overview(
            feedback_data=feedback_data,
            section_title="Alle tilbakemeldinger"
        )
        
        # Vis statistikk og andre seksjoner...
        
    except Exception as e:
        logger.error(f"Error in display_admin_dashboard: {str(e)}")
        st.error("Kunne ikke vise feedback dashboard")
        
def display_feedback_overview(feedback_data: pd.DataFrame, section_title: str):
    """Viser oversikt over feedback"""
    try:
        if feedback_data.empty:
            st.info("Ingen tilbakemeldinger å vise")
            return
            
        # Velg kun relevante kolonner
        display_columns = [
            'datetime', 
            'type', 
            'comment', 
            'customer_id'
        ]
        
        display_data = feedback_data[display_columns].copy()
        
        # Sorter etter datetime, nyeste først
        display_data = display_data.sort_values('datetime', ascending=False)
        
        # Formater datetime til lesbart format
        display_data['datetime'] = display_data['datetime'].dt.strftime('%d.%m.%Y %H:%M')
            
        with st.expander(
            f"{section_title} ({len(display_data)} stk)",
            expanded=True
        ):
            # Vis feedback data i en tabell med konfigurerte kolonner
            st.dataframe(
                display_data,
                column_config={
                    'datetime': st.column_config.TextColumn('Tidspunkt', width=150),
                    'type': st.column_config.TextColumn('Type', width=140),
                    'comment': st.column_config.TextColumn('Kommentar', width=150),
                    'customer_id': st.column_config.TextColumn('Hytte', width=80)
                },
                use_container_width=True,
                hide_index=True
            )
            
            # Last ned-knapp hvis det finnes data
            if not display_data.empty:
                csv = display_data.to_csv(index=False)
                st.download_button(
                    "Last ned som CSV",
                    csv,
                    "feedback.csv",
                    "text/csv"
                )
                
    except Exception as e:
        logger.error(f"Feil i display_feedback_overview: {str(e)}")
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
        
        # Nedlastingsknapp for CSV
        csv = display_data.to_csv(index=False)
        st.download_button(
            "📥 Last ned CSV",
            csv,
            "feedback.csv",
            "text/csv"
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

def test_maintenance_graph(use_streamlit=False):
    """Test funksjon for å debugge grafvisning"""
    try:
        logger.debug("Starting test_maintenance_graph")
        
        # Hent data for siste 7 dager
        end_date = get_current_time()
        start_date = end_date - timedelta(days=7)
        
        logger.debug(f"Tester for periode: {start_date} til {end_date}")
        
        # Hent reaksjoner
        reactions = get_maintenance_reactions(start_date, end_date)
        logger.debug(f"Hentet {len(reactions) if not reactions.empty else 0} reaksjoner")
        
        if reactions.empty:
            logger.warning("Ingen reaksjoner funnet for test")
            return False
            
        # Beregn statistikk
        daily_stats, daily_stats_pct, daily_score = calculate_maintenance_stats(
            reactions,
            group_by='day',
            days_back=7
        )
        
        logger.debug(f"Statistikk beregnet:")
        logger.debug(f"daily_stats:\n{daily_stats}")
        logger.debug(f"daily_stats_pct:\n{daily_stats_pct}")
        logger.debug(f"daily_score:\n{daily_score}")
        
        # Prøv å lage graf
        if not daily_stats.empty:
            fig = create_maintenance_chart(daily_stats, daily_stats_pct, daily_score, 'day')
            if fig is not None:
                logger.debug("Graf opprettet vellykket")
                if use_streamlit:
                    st.plotly_chart(fig, use_container_width=True)
                return True
            else:
                logger.error("Kunne ikke opprette graf")
                return False
        else:
            logger.warning("Ingen data for graf")
            return False
            
    except Exception as e:
        logger.error(f"Feil i test_maintenance_graph: {str(e)}", exc_info=True)
        return False

def test_database_content():
    """Test funksjon for å sjekke databaseinnhold direkte"""
    try:
        logger.debug("Starting test_database_content")
        
        # Test databasetilkobling
        try:
            with get_db_connection("feedback") as conn:
                logger.debug("Databasetilkobling opprettet")
                
                cursor = conn.cursor()
                
                # Sjekk om tabellen eksisterer
                cursor.execute("""
                    SELECT name 
                    FROM sqlite_master 
                    WHERE type='table' 
                    AND name='feedback'
                """)
                if not cursor.fetchone():
                    logger.error("Feedback-tabellen eksisterer ikke")
                    return False
                    
                # Sjekk tabellstruktur
                cursor.execute("PRAGMA table_info(feedback)")
                columns = cursor.fetchall()
                logger.debug("Tabellstruktur:")
                for col in columns:
                    logger.debug(f"Kolonne: {col}")
                    
                # Sjekk data
                cursor.execute("""
                    SELECT datetime, comment, customer_id, type
                    FROM feedback 
                    WHERE type = 'Vintervedlikehold'
                    LIMIT 5
                """)
                rows = cursor.fetchall()
                logger.debug("Eksempeldata:")
                for row in rows:
                    logger.debug(f"Rad: {row}")
                    
            return True
            
        except Exception as e:
            logger.error(f"Feil ved lesing av database: {str(e)}", exc_info=True)
            return False
            
    except Exception as e:
        logger.error(f"Feil i test_database_content: {str(e)}", exc_info=True)
        return False

def test_maintenance_data():
    """Test funksjon som bare sjekker dataene"""
    try:
        logger.debug("Starting test_maintenance_data")
        
        # Hent data for siste 7 dager
        end_date = get_current_time().replace(hour=23, minute=59, second=59)
        start_date = end_date - timedelta(days=7)
        
        logger.debug(f"Tester for periode: {start_date} til {end_date}")
        
        # Hent reaksjoner
        reactions = get_maintenance_reactions(start_date, end_date)
        logger.debug(f"Hentet {len(reactions) if not reactions.empty else 0} reaksjoner")
        
        if reactions.empty:
            logger.warning("Ingen reaksjoner funnet for test")
            return False
            
        # Skriv ut data
        logger.debug("\nReaksjoner:")
        logger.debug(f"Kolonner: {reactions.columns.tolist()}")
        logger.debug(f"\nFørste rad:\n{reactions.iloc[0] if not reactions.empty else 'Ingen data'}")
        logger.debug(f"\nAlle data:\n{reactions}")
        
        # Beregn statistikk
        daily_stats, daily_stats_pct, daily_score = calculate_maintenance_stats(
            reactions,
            group_by='day',
            days_back=7
        )
        
        logger.debug("\nStatistikk:")
        logger.debug(f"daily_stats:\n{daily_stats}")
        logger.debug(f"daily_stats_pct:\n{daily_stats_pct}")
        logger.debug(f"daily_score:\n{daily_score}")
        
        return True
            
    except Exception as e:
        logger.error(f"Feil i test_maintenance_data: {str(e)}", exc_info=True)
        return False

# Kjør test når modulen lastes
if __name__ == "__main__":
    test_maintenance_data()

