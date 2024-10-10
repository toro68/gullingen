"""
validation_utils.py

Dette modulet inneholder ulike hjelpefunksjoner for validering av data
brukt i Fjellbergsskardet-applikasjonen.
"""

import re
import json
from datetime import datetime
from typing import Tuple, Optional

from logging_config import get_logger

logger = get_logger(__name__)

def validate_date(date_string: str) -> bool:
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_time(time_string: str) -> bool:
    time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')
    return bool(time_pattern.match(time_string))

def validate_user_id(user_id: str) -> bool:
    # Tillat numeriske verdier, bokstaver, og noen spesialtegn
    user_id_pattern = re.compile(r'^[a-zA-Z0-9_\-., ]{1,50}$')
    return bool(user_id_pattern.match(str(user_id)))

def advanced_validate_and_fix_json(json_string):
    def fix_line(line):
        # Fjern mellomrom på slutten av linjen
        line = line.rstrip()
        # Legg til manglende komma hvis nødvendig
        if line and line[-1] not in [',', '{', '['] and not line.strip().startswith('}') and not line.strip().startswith(']'):
            line += ','
        return line

    lines = json_string.split('\n')
    fixed_lines = [fix_line(line) for line in lines]
    fixed_json = '\n'.join(fixed_lines)

    # Fjern eventuelle ekstra komma før lukkende klammer og parenteser
    fixed_json = re.sub(r',\s*([\]}])', r'\1', fixed_json)

    try:
        # Prøv å parse den fiksede JSON-en
        json.loads(fixed_json)
        return fixed_json, "JSON fixed successfully"
    except json.JSONDecodeError as e:
        # Hvis det fortsatt feiler, returner den originale feilen
        return None, f"Unable to fix JSON. Error: {str(e)}"
