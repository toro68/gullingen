import streamlit as st
from datetime import date
from typing import Optional, Tuple
from utils.core.config import (
    TZ, 
    DATE_INPUT_CONFIG,
    DATE_VALIDATION,
    get_current_time,
    get_date_format,
    get_date_range_defaults
)
from utils.core.logging_config import get_logger

logger = get_logger(__name__)

def get_date_range_input(
    default_days: int = DATE_VALIDATION["default_date_range"]
) -> Tuple[Optional[date], Optional[date]]:
    """
    Viser datovelgere for start- og sluttdato
    
    Args:
        default_days: Antall dager i standard periode
        
    Returns:
        Tuple[Optional[date], Optional[date]]: Valgt (start_dato, slutt_dato) eller (None, None) ved feil
    """
    try:
        logger.debug("Starting date range input selection")
        start_default, end_default = get_date_range_defaults(default_days)
        
        date_format = get_date_format("display", "date").replace(
            "%Y", "YYYY").replace("%m", "MM").replace("%d", "DD"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                DATE_INPUT_CONFIG["start_label"],
                value=start_default,
                format=date_format
            )
        
        with col2:
            end_date = st.date_input(
                DATE_INPUT_CONFIG["end_label"],
                value=end_default,
                format=date_format
            )
            
        if start_date > end_date:
            st.error(DATE_INPUT_CONFIG["error_message"])
            return None, None
            
        logger.debug(f"Selected date range: {start_date} to {end_date}")
        return start_date, end_date
        
    except Exception as e:
        logger.error(f"Error in date range input: {str(e)}", exc_info=True)
        return None, None 