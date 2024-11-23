# date_inputs.py
import streamlit as st
from datetime import date, datetime, timedelta
from typing import Optional, Tuple
from utils.core.config import (
    TZ, 
    DATE_INPUT_CONFIG,
    DATE_VALIDATION,
    get_current_time,
    get_date_range_defaults,
    normalize_datetime,
    ensure_tz_datetime
)
from utils.core.logging_config import get_logger

logger = get_logger(__name__)

def get_date_range_input(
    default_days: int = DATE_VALIDATION["default_date_range"],
    key_prefix: str = ""
) -> Tuple[Optional[date], Optional[date]]:
    """
    Viser datovelgere for start- og sluttdato
    
    Args:
        default_days: Antall dager i standard periode
        key_prefix: Prefiks for widget keys for å unngå duplikater
        
    Returns:
        Tuple[Optional[date], Optional[date]]: Valgt (start_dato, slutt_dato) eller (None, None) ved feil
    """
    try:
        logger.debug("Starting date range input selection")
        start_default, end_default = get_date_range_defaults(default_days)
        
        # Sikre at vi har date-objekter
        if isinstance(start_default, datetime):
            start_default = start_default.date()
        if isinstance(end_default, datetime):
            end_default = end_default.date()
        
        date_format = get_date_format("display", "date").replace(
            "%Y", "YYYY").replace("%m", "MM").replace("%d", "DD"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                DATE_INPUT_CONFIG["start_label"],
                value=start_default,
                format=date_format,
                key=f"{key_prefix}start_date"
            )
        
        with col2:
            end_date = st.date_input(
                DATE_INPUT_CONFIG["end_label"],
                value=end_default,
                format=date_format,
                key=f"{key_prefix}end_date"
            )
            
        if start_date > end_date:
            st.error(DATE_INPUT_CONFIG["error_message"])
            return None, None
            
        logger.debug(f"Selected date range: {start_date} to {end_date}")
        return start_date, end_date
        
    except Exception as e:
        logger.error(f"Error in date range input: {str(e)}", exc_info=True)
        return None, None
    