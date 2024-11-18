import logging
import os
import sys
from pathlib import Path

import streamlit as st

# Sett opp paths
current_dir = Path(__file__).parent.absolute()
sys.path.append(str(current_dir))

# For Streamlit Cloud
if os.path.exists("/mount/gullingen"):
    os.chdir("/mount/gullingen")
    logger.info(f"Running on Streamlit Cloud, changed directory to: {os.getcwd()}")
    logger.info(f"Files in directory: {os.listdir()}")

# Nå kan vi importere utils
from utils.core.logging_config import get_logger, setup_logging
from src.app import (
    initialize_app,
    initialize_session_state,
    display_home_page,
    get_customer_by_id
)
from utils.core.auth_utils import check_session_timeout, login_page

# Sett opp logging
setup_logging()
logger = get_logger(__name__)

# Fjern alle eksisterende handlers for å unngå dupliserte logger outputs
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Legg til EN console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Legg til logging av mappestier for debugging
logger.info(f"Current working directory: {os.getcwd()}")
logger.info(f"Root path: {current_dir}")
logger.info(f"Python path: {sys.path}")

try:
    # Import app.py etter at paths er satt opp
    from src.app import (
        initialize_app,
        initialize_session_state,
        display_home_page,
        get_customer_by_id,
        create_menu,
        login_page,
        check_session_timeout
    )
    
    # Resten av koden forblir uendret...
    # Initialize session state variables
    if "_script_run_count" not in st.session_state:
        st.session_state._script_run_count = 0

    # Increment counter at start of execution
    st.session_state._script_run_count += 1
    
    logger.info(
        f"=== MAIN EXECUTION START - Run #{st.session_state._script_run_count} ==="
    )

    # Initialiser session state
    initialize_session_state()

    # Kjør app initialisering én gang
    if not st.session_state.get("app_initialized", False):
        logger.info("App not initialized, starting initialization")
        if not initialize_app():
            logger.error("Failed to initialize app")
            st.error("Kunne ikke starte applikasjonen. Vennligst sjekk loggene.")
            st.stop()
        st.session_state.app_initialized = True

    # Håndter autentisering
    if not check_session_timeout():
        st.session_state.authenticated = False
        login_page()
        st.stop()

    if not st.session_state.get("authenticated", False):
        login_page()
    else:
        customer = get_customer_by_id(st.session_state.user_id)
        if customer is None:
            st.error("Kunne ikke finne brukerinformasjon")
            st.session_state.authenticated = False
            st.session_state.is_admin = False
            st.rerun()
        else:
            user_type = customer.get("Type", "Standard")
            st.session_state.is_admin = user_type in ["Admin", "Superadmin"]
            display_home_page(customer)

except Exception as e:
    logger.error(f"Error in main execution: {str(e)}", exc_info=True)
    st.error("Det oppstod en feil. Vennligst prøv igjen senere.")
finally:
    logger.info(f"=== MAIN EXECUTION END - Run #{st.session_state._script_run_count} ===")
