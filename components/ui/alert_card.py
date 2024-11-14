# Fil: components/ui/alert_card.py
# Kategori: UI Components

import streamlit as st
from datetime import datetime
import pytz
import logging
from typing import Dict, Any
from zoneinfo import ZoneInfo  # Lagt til import av ZoneInfo
from constants import TZ
from logging_config import get_logger

logger = get_logger(__name__)

def create_alert_style():
    return """
    <style>
        @import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css');

        .alert-card {
            background-color: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
            border: 1px solid #e5e7eb;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        
        .alert-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
        }
        
        .alert-type {
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 600;
            font-size: 1.1em;
            color: #1F2937;
        }
        
        .alert-datetime {
            color: #6B7280;
            font-size: 0.9em;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .alert-content {
            color: #374151;
            line-height: 1.6;
            margin: 0 0 16px 0;
        }
        
        .alert-footer {
            border-top: 1px solid #e5e7eb;
            padding-top: 16px;
            margin-top: 16px;
        }
        
        .footer-item {
            display: flex;
            align-items: center;
            gap: 6px;
            color: #6B7280;
            font-size: 0.9em;
        }
        
        /* Spesifikke ikoner for varseltyper */
        .alert-type i.fa-snowplow { color: #2563EB; }
        .alert-type i.fa-road { color: #9333EA; }
        .alert-type i.fa-wrench { color: #D97706; }
        .alert-type i.fa-circle-info { color: #059669; }
        .alert-type i.fa-bell { color: #DC2626; }
    </style>
    """

def get_alert_icon(alert_type: str) -> str:
    """Returnerer passende ikon basert på varseltype"""
    clean_type = alert_type.replace("Admin varsel: ", "").lower()
    
    icons = {
        'generelt': 'fa-circle-info',
        'brøyting': 'fa-snowplow',
        'strøing': 'fa-road',
        'vedlikehold': 'fa-wrench',
        'annet': 'fa-bell'
    }
    return icons.get(clean_type, 'fa-circle-info')

def convert_to_local_time(dt) -> datetime:
    """Konverterer en datetime til lokal tid ved bruk av ZoneInfo"""
    if dt is None:
        return None
        
    # Hvis datetime er en string, konverter til datetime
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        
    # Hvis datetime ikke har tidssone, anta UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo('UTC'))
    
    # Konverter til Oslo tidssone ved bruk av TZ fra constants
    return dt.astimezone(TZ)

def is_new_alert(alert_datetime: datetime, hours: int = 24) -> bool:
    """Sjekker om varselet er nyere enn gitt antall timer"""
    try:
        if isinstance(alert_datetime, str):
            alert_datetime = datetime.fromisoformat(alert_datetime.replace('Z', '+00:00'))
        
        now = datetime.now(pytz.UTC)
        
        if alert_datetime.tzinfo is None:
            alert_datetime = pytz.UTC.localize(alert_datetime)
        
        return (now - alert_datetime).total_seconds() < hours * 3600
    except Exception as e:
        logger.error(f"Feil ved sjekk av nytt varsel: {str(e)}")
        return False

def get_status_badge(alert: Dict[str, Any]) -> str:
    """Returnerer status badge basert på varselets status"""
    status = alert.get('status', 'Aktiv')
    if status == 'Aktiv':
        return '<span class="badge new"><i class="fas fa-check"></i>Aktiv</span>'
    return '<span class="badge inactive"><i class="fas fa-clock"></i>Inaktiv</span>'

def display_alert_card(alert: Dict[str, Any]) -> None:
    """
    Viser et varsel i et stilig kort-format.
    
    Args:
        alert (dict): Et dictionary som inneholder varselet med følgende nøkler:
            - type: String med varseltype
            - datetime: Datetime eller string for når varselet ble opprettet
            - comment: String med varselteksten
            - expiry_date: Optional datetime eller string for utløpsdato
    """
    try:
        # Håndter datetime
        if isinstance(alert['datetime'], str):
            alert_datetime = datetime.fromisoformat(alert['datetime'].replace('Z', '+00:00'))
        else:
            alert_datetime = alert['datetime']
        
        # Konverter til lokal tid
        local_datetime = convert_to_local_time(alert_datetime)
        formatted_datetime = local_datetime.strftime('%d.%m.%Y %H:%M')
        
        # Håndter utløpsdato
        expiry_date = None
        if alert.get('expiry_date'):
            if isinstance(alert['expiry_date'], str):
                expiry_datetime = datetime.fromisoformat(alert['expiry_date'].replace('Z', '+00:00'))
                expiry_date = convert_to_local_time(expiry_datetime).strftime('%d.%m.%Y')
            elif alert['expiry_date'] is not None:
                expiry_date = convert_to_local_time(alert['expiry_date']).strftime('%d.%m.%Y')

        # Rens varseltypen og kommentaren
        display_type = alert['type'].replace("Admin varsel: ", "")
        icon_class = get_alert_icon(alert['type'])
        comment = str(alert['comment']).replace("<", "&lt;").replace(">", "&gt;")
        
        # Bygg HTML
        alert_html = [
            '<div class="alert-card">',
            '    <div class="alert-header">',
            f'        <div class="alert-type">',
            f'            <i class="fas {icon_class}"></i>',
            f'            {display_type}',
            '        </div>',
            '        <div class="alert-datetime">',
            '            <i class="far fa-clock"></i>',
            f'            {formatted_datetime}',
            '        </div>',
            '    </div>',
            '    <div class="alert-content">',
            f'        {comment}',
            '    </div>'
        ]
        
        # Legg til footer hvis vi har utløpsdato
        if expiry_date:
            alert_html.extend([
                '    <div class="alert-footer">',
                '        <div class="footer-item">',
                '            <i class="far fa-calendar-times"></i>',
                f'            Utløper: {expiry_date}',
                '        </div>',
                '    </div>'
            ])
        
        alert_html.append('</div>')
        
        # Vis CSS-stilen og alert-kortet
        st.markdown(create_alert_style(), unsafe_allow_html=True)
        st.markdown('\n'.join(alert_html), unsafe_allow_html=True)
        
    except Exception as e:
        logger.error(f"Feil ved visning av varsel: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved visning av varselet.")