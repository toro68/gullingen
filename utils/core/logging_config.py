import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging():
    # Opprett logs-mappen hvis den ikke eksisterer
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Sett full sti til loggfilen
    log_file = os.path.join(log_dir, "app.log")

    # Opprett root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Fjern eksisterende handlers
    root_logger.handlers = []

    # Opprett handlers
    file_handler = RotatingFileHandler(log_file, maxBytes=1024 * 1024, backupCount=5)
    console_handler = logging.StreamHandler()

    # Sett nivå
    file_handler.setLevel(logging.INFO)
    console_handler.setLevel(logging.INFO)

    # Definer format
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Legg til handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def get_logger(name):
    logger = logging.getLogger(name)
    return logger
