import os
from datetime import datetime, timedelta

import streamlit as st
from dotenv import load_dotenv

from utils.core.config import TZ  # Importer tidssonen
from utils.core.logging_config import get_logger
from utils.services.weather_utils import get_weather_data_for_period

logger = get_logger(__name__)


def test_weather_elements():
    """Test hvilke værdata-elementer som faktisk returnerer data"""
    try:
        # Hent client_id fra miljøvariabler eller secrets
        load_dotenv()
        client_id = os.getenv("CLIENT_ID") or st.secrets["api_keys"]["client_id"]

        # Hent data for siste 24 timer med korrekt tidssone
        end_date = datetime.now(TZ)
        start_date = end_date - timedelta(days=1)

        logger.info(f"Henter værdata fra {start_date} til {end_date}")
        result = get_weather_data_for_period(client_id, start_date, end_date)

        # Sjekk om vi fikk en dictionary med DataFrame
        if result is None or "df" not in result:
            logger.error("Ingen data mottatt fra API")
            return None

        df = result["df"]  # Hent DataFrame fra resultatet

        if df.empty:
            logger.error("DataFrame er tom")
            return None

        # Sjekk hver kolonne for data
        element_status = {}
        for column in df.columns:
            has_data = not df[column].isna().all()
            non_null_count = df[column].count()
            total_count = len(df)
            coverage = (non_null_count / total_count * 100) if total_count > 0 else 0

            element_status[column] = {
                "has_data": has_data,
                "coverage": f"{coverage:.1f}%",
                "non_null_count": non_null_count,
                "total_count": total_count,
            }

        # Skriv ut status for hver kolonne
        logger.info("\nVærdata element status:")
        logger.info("-" * 60)
        logger.info(f"{'Element':<30} {'Har data':<10} {'Dekning':<10} {'Verdier'}")
        logger.info("-" * 60)

        for element, status in element_status.items():
            logger.info(
                f"{element:<30} "
                f"{'Ja' if status['has_data'] else 'Nei':<10} "
                f"{status['coverage']:<10} "
                f"{status['non_null_count']}/{status['total_count']}"
            )

        # Sjekk at vi har minst noen kolonner med data
        assert any(
            status["has_data"] for status in element_status.values()
        ), "Ingen værdata-elementer returnerer data"

        return element_status

    except Exception as e:
        logger.error(f"Feil under testing av værdata-elementer: {str(e)}")
        raise


if __name__ == "__main__":
    element_status = test_weather_elements()
