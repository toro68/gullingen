import pandas as pd
import streamlit as st
import logging

from util_functions import dump_secrets
from customer_utils import load_customer_database
from tun_utils import hent_bestillinger
from logging_config import get_logger

logger = get_logger(__name__)

def dump_debug_info():
    logger.info("Dumping debug info")

    # Dump innholdet i st.secrets
    dump_secrets()

    # Forsøk å laste kundedatabasen
    customer_db = load_customer_database()

    if isinstance(customer_db, pd.DataFrame):
        logger.info(f"Total number of customers: {len(customer_db)}")

        if not customer_db.empty:
            # Logg noen detaljer om kundedatabasen
            first_customer = customer_db.iloc[0].to_dict()
            logger.info(f"First customer: {first_customer}")
            logger.info(f"Keys in customer data: {list(first_customer.keys())}")
        else:
            logger.warning("Customer database is empty")
    else:
        logger.warning("Customer database is not a DataFrame")

    # Logg passordinformasjon (ikke selve passordene)
    logger.info("Passwords:")
    for user_id in st.secrets.get("passwords", {}):
        logger.info(f"User ID: {user_id} has a password set")

    logger.info("Bestillinger:")
    bestillinger = hent_bestillinger()
    if isinstance(bestillinger, pd.DataFrame):
        if bestillinger.empty:
            logger.info("Ingen bestillinger funnet.")
        else:
            for _, row in bestillinger.iterrows():
                logger.info(
                    f"Bestilling ID: {row['id']}, Bruker: {row['bruker']}, "
                    f"Ankomst dato: {row['ankomst_dato']}, Ankomst tid: {row['ankomst_tid']}, "
                    f"Avreise dato: {row['avreise_dato']}, Avreise tid: {row['avreise_tid']}, "
                    f"Kombinert ankomst: {row['ankomst']}, Kombinert avreise: {row['avreise']}, "
                    f"Type: {row['abonnement_type']}"
                )

            logger.info("Kolonnetyper:")
            for col in bestillinger.columns:
                logger.info(f"{col}: {bestillinger[col].dtype}")
    else:
        logger.warning("Bestillinger is not a DataFrame")
