import os
from time import time

# Fjernet import av 'streamlit_calendar' siden det ikke kunne importeres
from zoneinfo import ZoneInfo  # ZoneInfo er en underklasse av tzinfo

import streamlit as st

from utils.components.ui.alert_card import display_alert_card
from utils.core.auth_utils import check_session_timeout, login_page
from utils.core.config import (
    DATABASE_PATH,
)
from utils.core.logging_config import get_logger, setup_logging
from utils.core.menu_utils import create_menu
from utils.db.db_utils import (
    initialize_database_system
)
from utils.db.migrations import (
    run_migrations,
    migrate_feedback_table,
    migrate_tunbroyting_table,
    migrate_login_history_table,
    migrate_stroing_table,
    migrate_customer_table
)
from utils.services.admin_utils import (  # admin_utils er i services, ikke core
    admin_alert,
    unified_report_page,
)
from utils.services.alert_utils import (
    get_active_alerts
)
from utils.services.customer_utils import (
    get_customer_by_id,
    handle_customers
)
from utils.services.feedback_utils import (
    display_daily_maintenance_rating,
    handle_user_feedback,
    display_admin_dashboard,
)
from utils.services.gps_utils import display_last_activity
from utils.services.map_utils import display_live_plowmap
from utils.services.stroing_utils import (
    admin_stroing_page,
    bestill_stroing
)
from utils.services.tun_utils import (
    bestill_tunbroyting,
    handle_tun,
    vis_hyttegrend_aktivitet,
    vis_tunbroyting_oversikt,
)

# Set up logging ONCE
setup_logging()
logger = get_logger(__name__)

# Global variables
failed_attempts = {}


def display_home_page(customer):
    st.title("Fjellbergsskardet Hyttegrend")
    logger.info("Starting display_home_page")

    # Vis siste brøyteaktivitet først
    logger.info("Displaying last activity")
    display_last_activity()
    logger.info("Last activity displayed")

    try:
        logger.info("Getting active alerts")
        alerts = get_active_alerts()
        
        if not alerts.empty:
            st.subheader("Aktive varsler")
            logger.info(f"Found {len(alerts)} active alerts")

            for _, alert in alerts.iterrows():
                if (
                    alert["target_group"] is None
                    or "Alle brukere" in alert["target_group"]
                    or customer["Type"] in alert["target_group"]
                ):
                    display_alert_card(alert)
        else:
            logger.info("No active alerts")
            st.info("Ingen aktive varsler for øyeblikket.")

    except Exception as e:
        logger.error(f"Feil ved henting av varsler: {str(e)}", exc_info=True)
        st.error(
            "Det oppstod en feil ved lasting av varsler. Vennligst prøv igjen senere."
        )

    # Vis daglige tunbrøytinger
    logger.info("Displaying hyttegrend activity")
    vis_hyttegrend_aktivitet()
    logger.info("Hyttegrend activity displayed")

    # Tilbakemelding på vintervedlikehold
    st.write("---")  # Visuell separator
    logger.info("Starting maintenance feedback display")
    display_daily_maintenance_rating()
    logger.info("Maintenance feedback display completed")

    # Lenker til ressurser
    st.subheader("❗️ Nyttige lenker")
    with st.expander("📍Kart og dokumenter"):
        st.markdown(
            """
            - [Brøytekart](https://sartopo.com/m/J881)
            - [Brøytestandard](https://docs.google.com/document/d/1Kz7RTsp9J7KFNswmkuHiYbAY0QL6zLeSWrlbBxwUaAg/edit?usp=sharing)
            - [Tunkart - alle tun](https://t.ly/2ewsw)
            - [Tunkart - årsabonnement](https://t.ly/Rgrm_)
            - [Tunkart - vinter 2024](https://t.ly/2ewsw)
            - [Tunkart - vinter 2024 årsabonnement](https://t.ly/Rgrm_)
            """
        )

    with st.expander("📸 Webkamera"):
        st.markdown(
            """
            - [Webkamera Nesvik](https://www.vegvesen.no/trafikkinformasjon/reiseinformasjon/webkamera/#/vis/3001002_1)
            - [Webkamera Hjelmeland](https://www.vegvesen.no/trafikkinformasjon/reiseinformasjon/webkamera/#/vis/3001003_1)
            """
        )

    with st.expander("🌤️ 🌨️ Væroppdateringer og varsler"):
        st.markdown(
            """
            - [Værdata](https://gulling1.streamlit.app/) - Se detaljert værstatistikk og prognoser
            - Følg @gullingen365 p [X(Twitter)](https://x.com/gullingen365) 
              eller [Telegram](https://t.me/s/gullingen365) for å få 4 daglige væroppdateringer (ca kl 6, 11, 17, 22).
            - Abonner på en daglig e-post med oppsummering av været siste døgn. Man vil også få alarm 
              hvis det ikke brøytes ved mer enn 8mm nedbør som nysnø, [se her](https://t.ly/iFdRZ/)
            """
        )


def initialize_app():
    """Initialiserer applikasjonen"""
    try:
        logger.info("=== Starting app initialization ===")
        logger.info(f"Current working directory: {os.getcwd()}")
        logger.info(f"Database path: {DATABASE_PATH}")
        logger.info(f"Database files exist: {[f.name for f in DATABASE_PATH.glob('*.db')]}")
        
        # Kjør migrasjoner først
        migrations = [
            migrate_feedback_table,
            migrate_tunbroyting_table,
            migrate_login_history_table,
            migrate_stroing_table,
            migrate_customer_table
        ]
        
        for migration in migrations:
            logger.info(f"Running migration: {migration.__name__}")
            if not migration():
                logger.error(f"Failed to run {migration.__name__}")
                return False
        
        # Kjør generell migrasjonssjekk
        if not run_migrations():
            logger.error("Failed to run migrations")
            return False
            
        # Initialiser databasesystem
        if not initialize_database_system():
            logger.error("Failed to initialize database system")
            return False
            
        logger.info("=== App initialization completed successfully ===")
        return True
        
    except Exception as e:
        logger.error(f"Error during app initialization: {str(e)}")
        return False


def initialize_session_state():
    """Initialiserer session state variabler"""
    # Fjernet tvungen reinitialisering
    if "app_initialized" not in st.session_state:
        st.session_state.app_initialized = False
    
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "customer_id" not in st.session_state:  
        st.session_state.customer_id = None
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False
    if "last_activity" not in st.session_state:
        st.session_state.last_activity = time()  
    if "tz" not in st.session_state:
        st.session_state.tz = ZoneInfo("Europe/Oslo")


def main():
    try:
        logger.info("=== Starting main() function ===")
        logger.info(f"Current working directory: {os.getcwd()}")
        logger.info(f"DATABASE_PATH: {DATABASE_PATH}")

        # Initialiser session state
        logger.info("Initializing session state")
        initialize_session_state()

        # Kjør app initialisering én gang
        if not st.session_state.app_initialized:
            logger.info("App not initialized, starting initialization")
            if not initialize_app():
                logger.error("Failed to initialize app")
                st.error("Kunne ikke starte applikasjonen. Vennligst sjekk loggene.")
                return
            logger.info("App initialization completed")
            st.session_state.app_initialized = True
        else:
            logger.info("App already initialized")

        # Håndter autentisering
        logger.info("Checking session timeout")
        if not check_session_timeout():
            logger.info("Session timed out, resetting authentication")
            st.session_state.authenticated = False
            login_page()
            return

        if not st.session_state.authenticated:
            logger.info("User not authenticated, showing login page")
            login_page()
        else:
            logger.info(
                f"User authenticated, getting customer data for ID: {st.session_state.customer_id}"
            )
            customer = get_customer_by_id(st.session_state.customer_id)
            logger.info(f"Retrieved customer data: {customer}")

            if customer is None:
                logger.error("Could not find customer data")
                st.error("Kunne ikke finne brukerinformasjon")
                st.session_state.authenticated = False
                st.session_state.is_admin = False
                st.rerun()
            else:
                logger.info(f"Found customer data: {customer}")
                user_type = customer.get("Type", "Standard")
                st.session_state.is_admin = user_type in ["Admin", "Superadmin"]

                selected, admin_choice = create_menu(customer["customer_id"], user_type)
                logger.info(f"Menu selection: {selected}, Admin choice: {admin_choice}")

                # Håndter sidenavigasjon
                if selected == "Hjem":
                    display_home_page(customer)
                elif selected == "Bestill Tunbrøyting":
                    bestill_tunbroyting()
                elif selected == "Bestill Strøing":
                    bestill_stroing()
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
                    elif admin_choice == "Dashboard":
                        display_admin_dashboard()
                    elif admin_choice == "Kunder" and user_type == "Superadmin":
                        handle_customers()
                    elif (
                        admin_choice == "Håndter tunbestillinger"
                        and user_type == "Superadmin"
                    ):
                        handle_tun()
                    elif (
                        admin_choice == "Dashbord for rapporter"
                        and user_type == "Superadmin"
                    ):
                        unified_report_page(include_hidden=True)

    except Exception as e:
        logger.error(f"Critical error in main(): {str(e)}", exc_info=True)
    finally:
        logger.info("=== Exiting main() function ===")