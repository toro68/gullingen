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
    # Opprett logger
    logger = logging.getLogger(name)
    
    # Sett globalt loggnivå til INFO
    logger.setLevel(logging.INFO)
    
    # Opprett en console handler hvis den ikke allerede eksisterer
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Definer format
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        
        # Legg til handler
        logger.addHandler(console_handler)
    
    return logger