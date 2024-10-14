import io
import logging
import sqlite3
import json
import time as pytime
import hmac
import re
import pytz
import altair as alt
import xlsxwriter
import locale
import uuid
import traceback
import base64

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo  # ZoneInfo is a subclass of tzinfo
from io import BytesIO
from streamlit_calendar import calendar
from typing import List, Dict, Any, Optional, Tuple

import numpy as np  # NumPy
import pandas as pd  # Pandas
import matplotlib.pyplot as plt
import plotly.express as px  # Plotly Express
import requests
from statsmodels.nonparametric.smoothers_lowess import lowess  # Lowess Smoothing

import plotly.graph_objects as go  # Plotly Graph Objects
from plotly.subplots import make_subplots  # Plotly Subplots

import streamlit as st
from streamlit_echarts import st_echarts  # Streamlit ECharts
from streamlit_option_menu import option_menu  # Streamlit Option Menu

# Local imports
from constants import TZ, STATUS_MAPPING, STATUS_COLORS

# Database utilities
from db_utils import (
    update_database_schemas,
    initialize_database,
    ensure_login_history_table_exists,
    debug_database_operations,
)
# Validation utilities
from validation_utils import sanitize_input

# Authentication and session management
from auth_utils import (
    check_session_timeout,
    login_page
)

# Tunbrøyting utilities
from tun_utils import (
    bestill_tunbroyting,
    handle_tun,
    vis_tunbroyting_oversikt,
)

# Map utilities
from map_utils import (
    display_live_plowmap
)

from customer_utils import (
    get_customer_by_id, 
    check_cabin_user_consistency, 
    validate_customers_and_passwords,
)

# Feedback utilities
from feedback_utils import (
    handle_user_feedback,
    give_feedback,
)

# Strøing utilities
from stroing_utils import (
    bestill_stroing,
    admin_stroing_page
)

# Weather utilities 
from weather_display_utils import (
    display_weather_data
)
    
# Utility functions
from util_functions import (
    get_date_range,
)

# admin utilities
from admin_utils import (
    admin_alert,
    unified_report_page,
)

from menu_utils import create_menu

# Logging configuration
from logging_config import setup_logging, get_logger

# Set up logging
setup_logging()
logger = get_logger(__name__)

# Constants
MAX_ATTEMPTS = 5
LOCKOUT_PERIOD = timedelta(minutes=15)
SESSION_TIMEOUT = 3600  # 1 time

# Global variables
failed_attempts = {}
 
#Validering av brukerinput
def validate_user_input(input_data):
    """
    Validerer og saniterer brukerinput.
    
    Args:
    input_data (dict): Et dictionary med brukerinput
    
    Returns:
    dict: Et dictionary med validert og sanitert input
    """
    validated_data = {}
    for key, value in input_data.items():
        if isinstance(value, str):
            validated_data[key] = sanitize_input(value)
        elif isinstance(value, (int, float)):
            validated_data[key] = value
        elif isinstance(value, (list, dict)):
            validated_data[key] = validate_user_input(value)
        else:
            logger.warning(f"Unexpected input type for {key}: {type(value)}")
            validated_data[key] = None
    
    return validated_data

logger.info("Added validate_user_input function to app.py")

def initialize_app():
    initialize_database()
    update_database_schemas()
    ensure_login_history_table_exists()
    check_cabin_user_consistency()
    validate_customers_and_passwords()

# Hovedfunksjonene for appen
def main():
    try:
        # Debug og logging
        debug_database_operations()

        # Database initialisering og oppdatering
        initialize_app()

        # Sesjonshåndtering
        check_session_timeout()

        # UI-elementer
        # show_database_update_button()

        logger.info("Application setup complete")

        if "authenticated" not in st.session_state:
            st.session_state.authenticated = False
            st.session_state.user_id = None
            st.session_state.is_admin = False

        if not st.session_state.authenticated:
            login_page()
        else:
            customer = get_customer_by_id(st.session_state.user_id)
            if customer is None:
                st.error("Kunne ikke finne brukerinformasjon")
                st.session_state.authenticated = False
                st.session_state.is_admin = False
                st.rerun()
            else:
                st.session_state.is_admin = customer["Type"].lower() == "admin"
                selected, admin_choice = create_menu(
                    customer["Id"], st.session_state.is_admin
                )

                if selected == "Værdata":
                    client_id = st.secrets["api_keys"]["client_id"]

                    # Periode-velger
                    period_options = [
                        "Siste 24 timer",
                        "Siste 7 dager",
                        "Siste 12 timer",
                        "Siste 4 timer",
                        "Siden sist fredag",
                        "Siden sist søndag",
                        "Egendefinert periode",
                        "Siste GPS-aktivitet til nå",
                    ]
                    period = st.selectbox("Velg en periode:", options=period_options)

                    start_date, end_date = get_date_range(period)

                    if start_date is None or end_date is None:
                        st.error(f"Kunne ikke hente datoområde for perioden: {period}")
                    else:
                        st.write(
                            f"Henter data fra: {start_date.strftime('%d.%m.%Y kl. %H:%M')} til: {end_date.strftime('%d.%m.%Y kl. %H:%M')}"
                        )
                        display_weather_data(client_id, start_date, end_date)

                elif selected == "Bestill Tunbrøyting":
                    bestill_tunbroyting()
                elif selected == "Bestill Strøing":
                    bestill_stroing()
                elif selected == "Gi feedback":
                    give_feedback()
                elif selected == "Live Brøytekart":
                    display_live_plowmap()
                elif selected == "Administrasjon" and st.session_state.is_admin:
                    if admin_choice == "Tunkart":
                        vis_tunbroyting_oversikt()
                    elif admin_choice == "Håndter varsler":
                        admin_alert()
                    elif admin_choice == "Håndter Feedback":
                        handle_user_feedback()
                    elif admin_choice == "Håndter Strøing":
                        admin_stroing_page()
                    elif admin_choice == "Håndter Tun":
                        handle_tun()
                    elif admin_choice == "Last ned Rapporter":
                        unified_report_page(include_hidden=True)

    except Exception as e:
        st.error(f"En feil oppstod: {str(e)}")
        st.write("Feilsøkingsinformasjon:")
        st.code(traceback.format_exc())
        

if __name__ == "__main__":
    main()
