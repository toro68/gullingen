from datetime import datetime

from utils.core.config import TZ
from utils.core.logging_config import get_logger
from utils.db.db_utils import execute_query

logger = get_logger(__name__)


def log_status_change(
    bestilling_id, old_status, new_status, changed_by, db_name="stroing"
):
    """
    Logger en statusendring for en bestilling.

    Args:
    bestilling_id (int): ID-en til bestillingen som endres.
    old_status (str): Den gamle statusen.
    new_status (str): Den nye statusen.
    changed_by (str): Identifikatoren til personen som utførte endringen.
    db_name (str): Navnet på databasen (standard er 'stroing').

    Returns:
    bool: True hvis loggingen var vellykket, False ellers.
    """
    try:
        query = """
        INSERT INTO stroing_status_log (bestilling_id, old_status, new_status, changed_by, changed_at)
        VALUES (?, ?, ?, ?, ?)
        """
        params = (
            bestilling_id,
            old_status,
            new_status,
            changed_by,
            datetime.now(TZ).isoformat(),
        )

        rows_affected = execute_query(db_name, query, params)

        if rows_affected > 0:
            logger.info(
                f"Status endret for bestilling {bestilling_id} fra {old_status} til {new_status} av {changed_by}"
            )
            return True
        else:
            logger.warning(
                f"Ingen rader påvirket ved logging av statusendring for bestilling {bestilling_id}"
            )
            return False

    except Exception as e:
        logger.error(
            f"Feil ved logging av statusendring for bestilling {bestilling_id}: {str(e)}"
        )
        return False


def log_general_event(event_type, description, user_id=None, db_name="event_log"):
    """
    Logger en generell hendelse.

    Args:
    event_type (str): Typen hendelse som logges.
    description (str): Beskrivelse av hendelsen.
    user_id (str, optional): ID-en til brukeren knyttet til hendelsen, hvis relevant.
    db_name (str): Navnet på databasen (standard er 'event_log').

    Returns:
    bool: True hvis loggingen var vellykket, False ellers.
    """
    try:
        query = """
        INSERT INTO event_log (event_type, description, user_id, timestamp)
        VALUES (?, ?, ?, ?)
        """
        params = (event_type, description, user_id, datetime.now(TZ).isoformat())

        rows_affected = execute_query(db_name, query, params)

        if rows_affected > 0:
            logger.info(f"Hendelse logget: {event_type} - {description}")
            return True
        else:
            logger.warning(
                f"Ingen rader påvirket ved logging av hendelse: {event_type}"
            )
            return False

    except Exception as e:
        logger.error(f"Feil ved logging av hendelse {event_type}: {str(e)}")
        return False


def log_feedback_event(
    feedback_id: int, event_type: str, description: str, user_id: str = None
) -> bool:
    """Logger feedback-relaterte hendelser"""
    try:
        query = """
        INSERT INTO feedback_log (feedback_id, event_type, description, user_id, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """
        params = (
            feedback_id,
            event_type,
            description,
            user_id,
            datetime.now(TZ).isoformat(),
        )

        rows_affected = execute_query("feedback", query, params)

        if rows_affected > 0:
            logger.info(f"Feedback hendelse logget: {event_type} - {description}")
            return True
        else:
            logger.warning(
                f"Ingen rader påvirket ved logging av feedback hendelse: {event_type}"
            )
            return False

    except Exception as e:
        logger.error(f"Feil ved logging av feedback hendelse: {str(e)}")
        return False


# Legg til flere loggingsfunksjoner etter behov
