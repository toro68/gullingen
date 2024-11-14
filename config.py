# config.py
import os

# Sett DATABASE_PATH til rotmappen
DATABASE_PATH = os.path.abspath(os.path.dirname(__file__))

# Logg filstien ved oppstart
from logging_config import get_logger
logger = get_logger(__name__)
logger.info(f"Database path set to: {DATABASE_PATH}")

