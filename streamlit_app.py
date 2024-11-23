import os
import sys
from pathlib import Path

import streamlit as st

# Set up paths
current_dir = Path(__file__).parent.absolute()
sys.path.append(str(current_dir))

from utils.core.logging_config import get_logger, setup_logging
setup_logging()
logger = get_logger(__name__)

# Importer config først
from utils.core.config import DATABASE_PATH, TZ, get_current_time

# Deretter endre arbeidsmappe
if os.path.exists("/mount/gullingen"):
    os.chdir("/mount/gullingen")
    logger.info(f"Changed working directory to: {os.getcwd()}")
    logger.info(f"Database path is: {DATABASE_PATH}")

from utils.core.menu_utils import create_menu
from utils.services.customer_utils import handle_customers

# Initialiser tidssone i session state
if 'TZ' not in st.session_state:
    st.session_state.TZ = TZ
    current_time = get_current_time()
    logger.info(f"Initialiserer tidssone til {TZ}. Nåværende tid: {current_time}")
    
try:
    from src.app import (
        initialize_app,
        display_home_page,
        get_customer_by_id,
        login_page,
        check_session_timeout,
        bestill_tunbroyting,
        bestill_stroing,
        give_feedback,
        display_live_plowmap,
        vis_tunbroyting_oversikt,
        admin_alert,
        handle_user_feedback,
        admin_stroing_page,
        display_admin_dashboard,
        handle_tun,
        unified_report_page,
    )

    # La app.py håndtere all initialisering
    if not st.session_state.get("app_initialized", False):
        logger.info("Starting app initialization")
        if not initialize_app():
            logger.error("Failed to initialize app")
            st.error("Kunne ikke starte applikasjonen. Vennligst sjekk loggene.")
            st.stop()
        st.session_state.app_initialized = True

    # Handle authentication
    if not check_session_timeout():
        st.session_state.authenticated = False
        login_page()
        st.stop()

    if not st.session_state.get("authenticated", False):
        login_page()
    else:
        customer = get_customer_by_id(st.session_state.customer_id)
        if customer is None:
            st.error("Kunne ikke finne brukerinformasjon")
            st.session_state.authenticated = False
            st.session_state.is_admin = False
            st.rerun()
        else:
            # Legg til logging for å sjekke customer data
            logger.info(f"Customer data: {customer}")
            
            # Sjekk at vi bruker riktig felt for brukertype
            user_type = customer.get("type", "Standard")  # Endre fra "Type" til "type"
            logger.info(f"User type from customer: {user_type}")
            
            st.session_state.is_admin = user_type in ["Admin", "Superadmin"]
            logger.info(f"Is admin: {st.session_state.is_admin}")
            
            # Create menu and handle navigation
            selected, admin_choice = create_menu(customer["customer_id"], user_type)
            
            # Handle page navigation based on menu selection
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
                elif admin_choice == "Varsler":
                    admin_alert()
                elif admin_choice == "Feedback Dashboard":
                    display_admin_dashboard()
                elif admin_choice == "Strøing":
                    admin_stroing_page()
                elif admin_choice == "Kunder" and user_type == "Superadmin":
                    handle_customers()
                elif admin_choice == "Håndter tunbestillinger" and user_type == "Superadmin":
                    handle_tun()
                elif admin_choice == "Dashbord for rapporter" and user_type == "Superadmin":
                    unified_report_page(include_hidden=True)

            logger.info(f"User type: {user_type}")
            logger.info(f"Is admin: {st.session_state.is_admin}")
            logger.info(f"Selected menu: {selected}")
            logger.info(f"Admin choice: {admin_choice}")

except Exception as e:
    logger.error(f"Error in main execution: {str(e)}", exc_info=True)
    st.error("Det oppstod en feil. Vennligst prøv igjen senere.")