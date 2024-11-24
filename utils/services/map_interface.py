from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Tuple

import pandas as pd
import plotly.graph_objects as go

from utils.core.config import (
    safe_to_datetime,
    format_date,
    get_current_time,
    TZ
)
from utils.core.logging_config import get_logger
from utils.services.customer_utils import get_cabin_coordinates
from utils.core.models import MapBooking, GREEN, RED, GRAY

logger = get_logger(__name__)

@dataclass
class MapConfig:
    """Konfigurasjon for kartvisning"""
    mapbox_token: str
    center_lat: float = 59.39111  # Default senterpunkt for Gullingen
    center_lon: float = 6.42755
    zoom_level: int = 14
    marker_colors: Dict[str, str] = field(default_factory=lambda: {
        "Årsabonnement": GREEN,
        "Ukentlig ved bestilling": RED,
        "none": GRAY
    })
    
    def get_marker_color(self, subscription_type: str) -> str:
        """Henter riktig markørfarge basert på abonnementstype"""
        return self.marker_colors.get(subscription_type, self.marker_colors["none"])
    
    def get_map_layout(self, title: str) -> dict:
        """Genererer layout-konfigurasjon for plotly kart"""
        return {
            "mapbox": {
                "accesstoken": self.mapbox_token,
                "style": "streets",
                "zoom": self.zoom_level,
                "center": {
                    "lat": self.center_lat,
                    "lon": self.center_lon
                }
            },
            "margin": {"l": 0, "r": 0, "t": 30, "b": 0},
            "title": title,
            "showlegend": True,
            "legend": {
                "yanchor": "top",
                "y": 0.99,
                "xanchor": "left",
                "x": 0.01,
                "bgcolor": "rgba(255, 255, 255, 0.9)",
                "bordercolor": "rgba(0, 0, 0, 0.2)",
                "borderwidth": 1
            },
            "height": 600
        }

def prepare_bookings_for_map(bookings: pd.DataFrame) -> List[MapBooking]:
    """
    Konverterer rådata fra database til MapBooking objekter
    
    Args:
        bookings (pd.DataFrame): Rådata fra databasen
        
    Returns:
        List[MapBooking]: Liste med forberedte booking-objekter for kartvisning
    """
    try:
        if bookings.empty:
            logger.info("Ingen bestillinger å forberede for kart")
            return []
            
        map_bookings = []
        current_time = get_current_time()
        
        for _, booking in bookings.iterrows():
            try:
                # Konverter datoer
                arrival = safe_to_datetime(booking['ankomst_dato'])
                departure = safe_to_datetime(booking['avreise_dato']) if pd.notna(booking['avreise_dato']) else None
                
                # Sjekk om bestillingen er aktiv
                is_active = True
                if arrival and arrival.date() > current_time.date():
                    is_active = False
                elif departure and departure.date() < current_time.date():
                    is_active = False
                
                map_booking = MapBooking(
                    customer_id=str(booking['customer_id']),
                    ankomst_dato=arrival,
                    avreise_dato=departure,
                    abonnement_type=booking['abonnement_type'],
                    is_active=is_active
                )
                map_bookings.append(map_booking)
                
            except Exception as e:
                logger.error(f"Feil ved konvertering av bestilling {booking['customer_id']}: {str(e)}")
                continue
                
        logger.info(f"Forberedt {len(map_bookings)} bestillinger for kartvisning")
        return map_bookings
        
    except Exception as e:
        logger.error(f"Feil i prepare_bookings_for_map: {str(e)}")
        return []

def get_map_popup_text(booking: MapBooking) -> str:
    try:
        # Start med grunnleggende informasjon
        popup_lines = [f"<b>Hytte {booking.customer_id}</b>"]
        
        # Legg til ankomstdato hvis den finnes
        if booking.ankomst_dato:
            formatted_arrival = format_date(booking.ankomst_dato, 'display', 'date')
            popup_lines.append(f"Ankomst: {formatted_arrival}")
            
        # Legg til avreisedato hvis den finnes
        if booking.avreise_dato:
            formatted_departure = format_date(booking.avreise_dato, 'display', 'date')
            popup_lines.append(f"Avreise: {formatted_departure}")
            
        # Legg til abonnementstype
        popup_lines.append(f"Type: {booking.abonnement_type}")
        
        # Sett sammen alle linjer med HTML linebreak
        return "<br>".join(popup_lines)
        
    except Exception as e:
        logger.error(f"Feil i get_map_popup_text: {str(e)}")
        return "Kunne ikke vise informasjon"

def create_default_map_config(mapbox_token: str) -> MapConfig:
    """Oppretter standard kartkonfigurasjon"""
    try:
        return MapConfig(
            mapbox_token=mapbox_token
        )
    except Exception as e:
        logger.error(f"Feil ved opprettelse av kartkonfigurasjon: {str(e)}")
        raise ValueError("Kunne ikke opprette kartkonfigurasjon")

def prepare_map_data(bestillinger: pd.DataFrame) -> pd.DataFrame:
    """Forbereder data for kartvisning"""
    try:
        if bestillinger.empty:
            return bestillinger
            
        # Konverter datoer
        date_columns = ['ankomst_dato', 'avreise_dato', 'onske_dato', 'bestilt_dato']
        for col in date_columns:
            if col in bestillinger.columns:
                bestillinger[col] = bestillinger[col].apply(safe_to_datetime)
                
        # ... resten av dataforberedelseskoden fra map_utils.py ...
        
    except Exception as e:
        logger.error(f"Feil i prepare_map_data: {str(e)}")
        return pd.DataFrame()

def debug_map_data(bestillinger: pd.DataFrame):
    """Logger debug informasjon om kartdata"""
    logger.info("=== Kart Debug Info ===")
    logger.info(f"Antall bestillinger: {len(bestillinger)}")
    logger.info(f"Kolonner i bestillinger: {bestillinger.columns.tolist()}")
    if not bestillinger.empty:
        logger.info(f"Første rad i bestillinger:\n{bestillinger.iloc[0]}")

def verify_map_configuration(bestillinger: pd.DataFrame, mapbox_token: str) -> tuple[bool, str]:
    """
    Verifiserer at kartkonfigurasjonen er gyldig.
    
    Args:
        bestillinger (pd.DataFrame): DataFrame med bestillinger
        mapbox_token (str): Mapbox API token
        
    Returns:
        tuple[bool, str]: (er_gyldig, feilmelding)
    """
    try:
        if bestillinger.empty:
            return True, ""
            
        if not mapbox_token:
            return False, "Mangler Mapbox token"
            
        required_columns = ['customer_id', 'ankomst_dato', 'avreise_dato', 'abonnement_type']
        missing_columns = [col for col in required_columns if col not in bestillinger.columns]
        
        if missing_columns:
            return False, f"Mangler påkrevde kolonner: {', '.join(missing_columns)}"
            
        return True, ""
        
    except Exception as e:
        logger.error(f"Feil i verify_map_configuration: {str(e)}")
        return False, "Kunne ikke verifisere kartkonfigurasjon"

def create_empty_map(mapbox_token: str, title: str = None) -> go.Figure:
    """Oppretter et tomt kart med standardkonfigurasjon"""
    logger.info("Oppretter tomt kart")
    
    fig = go.Figure()
    fig.add_trace(go.Scattermapbox(
        lat=[59.39111],  # Standard breddegrad for Gullingen
        lon=[6.42755],   # Standard lengdegrad for Gullingen
        mode='markers',
        marker=dict(size=0),
        showlegend=False
    ))
    
    fig.update_layout(
        mapbox=dict(
            accesstoken=mapbox_token,
            style='streets',
            zoom=14,
            center=dict(lat=59.39111, lon=6.42755)
        ),
        margin=dict(l=0, r=0, t=30, b=0),
        title=title or "Tunbrøytingskart",
        height=600
    )
    
    return fig
