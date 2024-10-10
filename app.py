import os
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

from contextlib import contextmanager  # Context Manager
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
    update_database_schema,
    create_all_tables,
    initialize_database,
    initialize_stroing_database,
    update_login_history_table
)

# Authentication and session management
from auth_utils import (
    check_session_timeout,
    log_login,
    log_failed_attempt,
    get_login_history,
    login_page,
    check_rate_limit,
    reset_rate_limit
)

# Tunbrøyting utilities
from tun_utils import (
    lagre_bestilling, 
    hent_bestillinger, 
    oppdater_bestilling, 
    slett_bestilling, 
    filter_tunbroyting_bestillinger, 
    hent_statistikk_data,
    hent_bruker_bestillinger,
    hent_bestillinger_for_periode,
    hent_dagens_bestillinger,
    hent_aktive_bestillinger,
    hent_bestilling,
    is_active_booking,
    get_max_bestilling_id,
    count_bestillinger,
    vis_tunbroyting_statistikk,
    bestill_tunbroyting,
    handle_tun,
    vis_daglige_broytinger,
    vis_tunbroyting_oversikt,
    vis_rediger_bestilling,
    vis_aktive_bestillinger,
    validere_bestilling
)

# Map utilities
from map_utils import (
    vis_dagens_tunkart,
    vis_kommende_tunbestillinger,
    vis_stroingskart_kommende,
    display_live_plowmap
)

# Alert utilities
from alert_utils import handle_alerts_ui, get_alerts

from customer_utils import (
    get_customer_by_id, 
    load_customer_database, 
    check_cabin_user_consistency, 
    validate_customers_and_passwords,
    get_customer_details,
    get_cabin_coordinates,
    get_rode
)

# Feedback utilities
from feedback_utils import (
    save_feedback,
    get_feedback,
    update_feedback_status,
    delete_feedback,
    display_feedback_dashboard,
    handle_user_feedback,
    give_feedback,
    display_recent_feedback,
    batch_insert_feedback,
    hide_feedback,
    get_feedback_statistics,
    generate_feedback_report,
    analyze_feedback_trends,
    categorize_feedback,
    get_feedback_by_id
)

# Strøing utilities
from stroing_utils import (
    lagre_stroing_bestilling,
    hent_stroing_bestillinger,
    hent_bruker_stroing_bestillinger,
    count_stroing_bestillinger,
    update_stroing_info,
    slett_stroingsbestilling,
    bestill_stroing,
    display_stroing_bookings,
    admin_stroing_page
)

# Weather utilities
from weather_utils import (
    get_weather_data_for_period,
    fetch_and_process_data,
    calculate_snow_drift_alarms,
    calculate_slippery_road_alarms,
    calculate_snow_precipitations
)

# 
from weather_display_utils import (
    display_weather_data,
    create_improved_graph,
    display_additional_data,
    display_wind_data,
    display_alarms,
    display_weather_statistics
)

# GPS utilities
from gps_utils import (
    get_gps_coordinates,
    fetch_gps_data,
    display_gps_data
)
    
# Utility functions
from util_functions import (
    get_date_range,
    get_status_display,
    dump_secrets, 
    neste_fredag
)

# admin utilities
from admin_utils import (
    admin_alert,
    admin_broytefirma_page,
    unified_report_page,
    download_reports
)

from menu_utils import create_menu

from debug_utils import dump_debug_info
# Encryption utilities
from encryption_utils import encrypt_data, decrypt_data

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

# Hovedfunksjonene for appen
def main():
    try:
        dump_debug_info()
        create_all_tables()
        update_login_history_table()
        update_database_schema()
        initialize_database()
        initialize_stroing_database()
        check_session_timeout()
        check_cabin_user_consistency()
        validate_customers_and_passwords()

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
        logger.error(f"An error occurred during application setup: {str(e)}")
        logger.error(f"Error traceback: {traceback.format_exc()}")
        st.error(
            "An error occurred during application setup. Please check the logs for more information."
        )

if __name__ == "__main__":
    main()
