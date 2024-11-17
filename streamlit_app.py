import logging
import os
import sys
from pathlib import Path

import streamlit as st

from utils.core.logging_config import get_logger, setup_logging

# Sett opp logging først
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

# Legg til en guard mot multiple handlers
if not hasattr(st.session_state, "logging_configured"):
    logger.info("=== STREAMLIT APP STARTUP ===")
    logger.info(f"Process ID: {os.getpid()}")
    logger.info(f"Parent Process ID: {os.getppid()}")
    logger.info(f"Session State Keys: {st.session_state.keys()}")
    logger.info(f"Script Rerun Count: {st.session_state.get('_script_run_count', 0)}")
    st.session_state.logging_configured = True

# Initialize session state variables
if "_script_run_count" not in st.session_state:
    st.session_state._script_run_count = 0

try:
    # Increment counter at start of execution
    st.session_state._script_run_count += 1
    
    logger.info(
        f"=== MAIN EXECUTION START - Run #{st.session_state._script_run_count} ==="
    )
    
    # Import main etter logging setup
    from src.app import main
    
    main()
    
except Exception as e:
    logger.error(f"Error in main execution: {str(e)}", exc_info=True)
    raise e
finally:
    # Safely log end of execution even if session state is cleared
    run_count = getattr(st.session_state, "_script_run_count", "Unknown")
    logger.info(f"=== MAIN EXECUTION END - Run #{run_count} ===")
