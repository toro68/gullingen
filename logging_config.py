import logging
from logging.handlers import RotatingFileHandler

def setup_logging():
    handler = RotatingFileHandler(
        'app.log',
        maxBytes=1024*1024,  # 1MB
        backupCount=5
    )
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[handler]
    )

# Opprett en funksjon for å hente logger for hver modul
def get_logger(name):
    return logging.getLogger(name)