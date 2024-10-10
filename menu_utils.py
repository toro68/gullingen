import logging
import traceback
import streamlit as st
from streamlit_option_menu import option_menu

from logging_config import get_logger

logger = get_logger(__name__)

def create_menu(customer_id, is_admin=False):
    with st.sidebar:
        st.success(f"Innlogget som {customer_id}")

        main_menu_options = [
            "Værdata",
            "Bestill Tunbrøyting",
            "Bestill Strøing",
            "Gi feedback",
            "Live Brøytekart",
        ]
        if is_admin:
            main_menu_options.append("Administrasjon")

        selected = option_menu(
            "Hovedmeny",
            main_menu_options,
            icons=["cloud-sun", "snow", "moisture", "chat-dots", "map", "gear"],
            menu_icon="cast",
            default_index=0,
        )

        admin_choice = None
        if selected == "Administrasjon" and is_admin:
            admin_choice = option_menu(
                "",
                [
                    "Tunkart",
                    "Håndter varsler",
                    "Håndter Feedback",
                    "Håndter Strøing",
                    "Håndter Tun",
                    "Last ned Rapporter",
                ],
                icons=[
                    "graph-up",
                    "exclamation-triangle",
                    "chat-dots",
                    "snow",
                    "house",
                    "download",
                ],
                menu_icon="cast",
                default_index=0,
            )

        if st.button("🚪 Logg ut"):
            st.session_state.authenticated = False
            st.session_state.user_id = None
            st.rerun()

    return selected, admin_choice
