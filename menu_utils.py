import logging
import traceback
import streamlit as st
from streamlit_option_menu import option_menu

from logging_config import get_logger

logger = get_logger(__name__)

def create_menu(customer_id, user_type):
    with st.sidebar:
        st.success(f"Innlogget som {customer_id}")

        # Legg til lenke til værdata-appen
        st.markdown("[🌤️ Værdata](https://gulling1.streamlit.app/)", unsafe_allow_html=True)
        
        main_menu_options = [
            "Hjem",
            "Bestill Tunbrøyting",
            "Bestill Strøing",
            "Gi feedback",
            "Live Brøytekart",
        ]
        if user_type in ['Admin', 'Superadmin']:
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
        )

        admin_choice = None
        if selected == "Administrasjon" and user_type in ['Admin', 'Superadmin']:
            admin_options = [
                "Tunkart",
                "Håndter varsler",
                "Håndter Feedback",
                "Håndter Strøing",
            ]
            if user_type == 'Superadmin':
                admin_options.extend(["Håndter tunbestillinger", "Dashbord for rapporter"])

            admin_choice = option_menu(
                "",
                admin_options,
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