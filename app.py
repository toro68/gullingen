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
import atexit

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo  # ZoneInfo er en underklasse av tzinfo
from io import BytesIO
# Fjernet import av 'streamlit_calendar' siden det ikke kunne importeres
from typing import List, Dict, Any, Optional, Tuple

import numpy as np  # NumPy
import pandas as pd  # Pandas
import matplotlib.pyplot as plt
import requests
from statsmodels.nonparametric.smoothers_lowess import lowess  # Lowess Smoothing

import plotly.express as px  # Plotly Express
import plotly.graph_objects as go  # Plotly Graph Objects
from plotly.subplots import make_subplots  # Plotly Subplots

import streamlit as st
from streamlit_echarts import st_echarts  # Streamlit ECharts
from streamlit_option_menu import option_menu  # Streamlit Option Menu

# Local imports
from constants import TZ, STATUS_MAPPING, STATUS_COLORS

# UI components
from components.ui.alert_card import display_alert_card

# Database utilities
from db_utils import (
    verify_and_update_schemas,
    fetch_data,
    initialize_database,
    ensure_login_history_table_exists,
    debug_database_operations,
    create_database_indexes
    #close_all_connections
)

# Tun utilities
from tun_utils import verify_database_state

# Validation utilities
from validation_utils import sanitize_input

# Authentication and session management
from auth_utils import check_session_timeout, login_page

# Tunbrøyting utilities
from tun_utils import (
    bestill_tunbroyting,
    handle_tun,
    vis_tunbroyting_oversikt,
    hent_bruker_bestillinger,
    vis_hyttegrend_aktivitet
)

# Map utilities
from map_utils import display_live_plowmap

from customer_utils import (
    get_customer_by_id,
    check_cabin_user_consistency,
    validate_customers_and_passwords,
    customer_edit_component
)

# Feedback utilities
from feedback_utils import (
    handle_user_feedback,
    give_feedback,
    display_maintenance_feedback,
)

# Strøing utilities
from stroing_utils import (
    bestill_stroing, 
    admin_stroing_page, 
    hent_bruker_stroing_bestillinger, 
    vis_graf_stroing,
    verify_stroing_database_state
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

from alert_utils import clean_invalid_expiry_dates, get_active_alerts

# Logging configuration
from logging_config import setup_logging, get_logger

from weather_display_utils import display_weather_data, handle_weather_page
from weather_utils import fetch_and_process_data

# Set up logging
setup_logging()
logger = get_logger(__name__)

# Constants
MAX_ATTEMPTS = 5
LOCKOUT_PERIOD = timedelta(minutes=15)
SESSION_TIMEOUT = 3600  # 1 time

# Global variables
failed_attempts = {}

def display_home_page(customer):
    st.title("Fjellbergsskardet Hyttegrend")
    
    try:
        alerts = get_active_alerts()
        if alerts:
            st.subheader("Aktive varsler")
            
            for alert in alerts:
                if (alert['target_group'] is None or 
                    'Alle brukere' in alert['target_group'] or 
                    customer['Type'] in alert['target_group']):
                    
                    display_alert_card(alert)
                    
        else:
            st.info("Ingen aktive varsler for øyeblikket.")
            
    except Exception as e:
        logger.error(f"Feil ved henting av varsler: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved lasting av varsler. Vennligst prøv igjen senere.")
    
    # Vis daglige tunbrøytinger
    vis_hyttegrend_aktivitet()
    
    # Legg til mulighet for å gi tilbakemelding på vintervedlikehold
    st.write("---")  # Visuell separator
    display_maintenance_feedback()  # Legg til denne linjen
    
    # Lenker til ressurser
    st.subheader("❗️ Nyttige lenker")
    with st.expander("📍Kart og dokumenter"):
        st.markdown(
            """
            - [Brøytekart](https://sartopo.com/m/J881)
            - [Brøytestandard](https://docs.google.com/document/d/1Kz7RTsp9J7KFNswmkuHiYbAY0QL6zLeSWrlbBxwUaAg/edit?usp=sharing)
            - [Tunkart - alle tun](https://t.ly/2ewsw)
            - Tunkart bare for årsabonnement, [se her](https://t.ly/Rgrm_)
            """
        )

    with st.expander("🌤️ 🌨️ Væroppdateringer og varsler"):
        st.markdown(
            """
            - Følg @gullingen365 p [X(Twitter)](https://x.com/gullingen365) 
              eller [Telegram](https://t.me/s/gullingen365) for å få 4 daglige væroppdateringer (ca kl 6, 11, 17, 22).
            - Abonner på en daglig e-post med oppsummering av været siste døgn. Man vil også få alarm 
              hvis det ikke brøytes ved mer enn 8mm nedbør som nysnø, [se her](https://t.ly/iFdRZ/)
            """
        )
    
# Validering av brukerinput
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
    try:
        verify_and_update_schemas()
        initialize_database()
        ensure_login_history_table_exists()
        clean_invalid_expiry_dates()
        check_cabin_user_consistency()
        validate_customers_and_passwords()
        create_database_indexes() 
        logger.info("Application initialization completed successfully")
    except Exception as e:
        logger.error(f"Error during application initialization: {str(e)}")
        st.error("Det oppstod en feil under initialisering av applikasjonen. Vennligst kontakt support.")
        raise

def main():
    try:
        # Logging og debugging
        logger.info("Starting application initialization")
        debug_database_operations()
        
        # Sjekk og oppdater databaseskjemaer
        verify_and_update_schemas()
        
        # Initialisering av applikasjonen
        initialize_app()
        
        # Verifiser databasetilstand
        if not verify_database_state():
            logger.error("Feil ved verifisering av tunbrøyting-database")
            st.error("Det oppstod en feil ved oppstart av appen. Vennligst prøv igjen senere.")
            return
            
        # Verifiser strøingsdatabase
        if not verify_stroing_database_state():
            logger.error("Feil ved verifisering av strøingsdatabase")
            st.error("Det oppstod en feil ved oppstart av appen. Vennligst prøv igjen senere.")
            return
        
        # Sesjonshåndtering
        check_session_timeout()
        
        # # Registrer funksjoner for å lukke databasetilkoblinger ved avslutning
        # atexit.register(close_all_connections)
        
        logger.info("Application initialization completed successfully")

        # UI-elementer (ikke i bruk)
        # - show_database_update_button()     

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
                user_type = customer["Type"]
                st.session_state.is_admin = user_type in ['Admin', 'Superadmin']
                selected, admin_choice = create_menu(customer["Id"], user_type)

                if selected == "Hjem":
                    display_home_page(customer)
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
                    elif admin_choice == "Håndter tunbestillinger" and user_type == 'Superadmin':
                        handle_tun()
                    elif admin_choice == "Dashbord for rapporter" and user_type == 'Superadmin':
                        unified_report_page(include_hidden=True)

    except Exception as e:
        logger.error(f"An error occurred during application execution: {e}", exc_info=True)
    finally:
        logger.info("Application shutting down")
        
if __name__ == "__main__":
    main()
