import logging
import traceback

import streamlit as st
from streamlit_option_menu import option_menu

from utils.core.logging_config import get_logger

logger = get_logger(__name__)


def create_menu(customer_id, user_type):
    with st.sidebar:
        logger.info(f"Creating menu for user {customer_id} with type {user_type}")
        st.success(f"Innlogget som {customer_id}")

        main_menu_options = [
            "Hjem",
            "Bestill Tunbrøyting",
            "Bestill Strøing",
            "Gi feedback",
            "Live Brøytekart",
        ]
        
        # Legg til logging for å sjekke user_type
        logger.info(f"Checking admin status: user_type={user_type}, is_admin={user_type in ['Admin', 'Superadmin']}")
        
        if user_type in ["Admin", "Superadmin"]:
            logger.info("Adding admin option to main menu")
            main_menu_options.append("Administrasjon")

        icons = [
            "house",
            "snow",
            "moisture",
            "chat-dots",
            "map",
            "gear",
        ]

        selected = option_menu(
            "Hovedmeny",
            main_menu_options,
            icons=icons,
            menu_icon="cast",
            default_index=0,
            key="main_menu",
        )

        admin_choice = None
        # Legg til mer logging for å spore admin-meny logikken
        logger.info(f"Selected menu: {selected}")
        logger.info(f"User type for admin menu: {user_type}")
        
        if selected == "Administrasjon" and user_type in ["Admin", "Superadmin"]:
            logger.info(f"Showing admin menu for {user_type}")
            admin_options = [
                "Tunkart",
                "Varsler",
                "Feedback",
                "Strøing",
            ]
            if user_type == "Superadmin":
                logger.info("Adding superadmin options")
                admin_options.extend(
                    ["Kunder", "Håndter tunbestillinger", "Dashbord for rapporter"]
                )

            admin_icons = [
                "map",
                "bell",
                "chat-dots",
                "snow",
                "people",
                "house",
                "graph-up",
            ]

            admin_choice = option_menu(
                "Admin-meny",
                admin_options,
                icons=admin_icons,
                menu_icon="gear",
                default_index=0,
                key="admin_menu",
            )

        if st.button("🚪 Logg ut"):
            st.session_state.authenticated = False
            st.session_state.user_id = None
            st.rerun()

    return selected, admin_choice
