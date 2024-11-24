# map_utils.py
# Standard library imports
from datetime import datetime
from typing import List

# Third-party imports
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Local imports fra utils
from utils.core.config import (
    safe_to_datetime,
    format_date,
    ensure_tz_datetime,
    get_current_time
)
from utils.core.logging_config import get_logger
from utils.core.util_functions import filter_todays_bookings
from utils.services.customer_utils import get_cabin_coordinates
from utils.core.models import MapBooking, GREEN, RED, GRAY
from utils.services.map_interface import (
    MapConfig,
    prepare_map_data,
    create_empty_map,
    get_map_popup_text,
    create_default_map_config,
    debug_map_data,
    prepare_bookings_for_map
)
from utils.core.validation_utils import validate_map_data

# Set up logging
logger = get_logger(__name__)

def vis_dagens_tunkart(bestillinger, mapbox_token, title):
    """Viser kart over dagens tunbrøytinger."""
    logger.info(f"=== STARTER VIS_DAGENS_TUNKART ===")
    logger.info(f"Input bestillinger: {len(bestillinger)} rader")
    
    try:
        if bestillinger.empty:
            return create_empty_map(mapbox_token, title)
            
        # Filtrer dagens bestillinger først
        aktive_bestillinger = filter_todays_bookings(bestillinger)
        logger.info(f"Aktive bestillinger etter filtrering: {len(aktive_bestillinger)} rader")
        
        if aktive_bestillinger.empty:
            logger.info("Ingen aktive bestillinger å vise")
            return create_empty_map(mapbox_token, title)
        
        # Konverter tuple-koordinater til dict-format
        cabin_coordinates = get_cabin_coordinates()
        formatted_coordinates = {}
        for cabin_id, coords in cabin_coordinates.items():
            formatted_coordinates[cabin_id] = {
                'lat': coords[0],  # Første element i tuple
                'lon': coords[1]   # Andre element i tuple
            }
        
        # Bruk de formaterte koordinatene
        cabin_coordinates = formatted_coordinates
        
        if not cabin_coordinates:
            logger.error("Ingen koordinater funnet")
            st.error("Kunne ikke laste koordinater for hyttene")
            return None
            
        # Opprett basisfigur
        fig = go.Figure()
        
        # Legg til et tomt scatter-lag for å initialisere kartet riktig
        fig.add_trace(go.Scattermapbox(
            lat=[59.39111],
            lon=[6.42755],
            mode='markers',
            marker=dict(size=0),
            showlegend=False
        ))
        
        # Fortsett med normal prosessering hvis vi har data
        logger.info(f"Aktive bestillinger: {len(aktive_bestillinger)}")
        
        # Legg til grå markører som én gruppe
        gray_lats = []
        gray_lons = []
        gray_texts = []
        for cabin_id, coords in cabin_coordinates.items():
            # Konverter cabin_id til string for sammenligning
            cabin_id_str = str(cabin_id)
            # Sjekk om hytta har aktiv bestilling
            if not any(str(booking['customer_id']) == cabin_id_str 
                       for _, booking in aktive_bestillinger.iterrows()):
                gray_lats.append(coords['lat'])
                gray_lons.append(coords['lon'])
                gray_texts.append(f"Hytte: {cabin_id}")
        if gray_lats:  # Bare legg til hvis det finnes inaktive hytter
            fig.add_trace(go.Scattermapbox(
                lat=gray_lats,
                lon=gray_lons,
                mode='markers',
                marker=dict(
                    size=8,
                    color=GRAY,
                    symbol='circle'
                ),
                text=gray_texts,
                hoverinfo='text',
                name='Ingen bestilling',
                showlegend=True
            ))
        
        # Legg til aktive bestillinger (alle med samme farge)
        if not aktive_bestillinger.empty:
            active_lats = []
            active_lons = []
            active_texts = []
            
            for _, booking in aktive_bestillinger.iterrows():
                customer_id = str(booking['customer_id'])
                coords = cabin_coordinates.get(customer_id)
                if coords:
                    active_lats.append(coords['lat'])
                    active_lons.append(coords['lon'])
                    # Konverter booking til MapBooking objekt
                    map_booking = MapBooking(
                        customer_id=customer_id,
                        ankomst_dato=booking.get('ankomst_dato'),
                        avreise_dato=booking.get('avreise_dato'),
                        abonnement_type=booking['abonnement_type'],
                        is_active=booking.get('is_active', True)
                    )
                    active_texts.append(get_map_popup_text(map_booking))
            
            if active_lats:  # Bare legg til hvis det finnes aktive bestillinger
                fig.add_trace(go.Scattermapbox(
                    lat=active_lats,
                    lon=active_lons,
                    mode='markers',
                    marker=dict(
                        size=12,
                        color=RED,  # Bruker rød for alle aktive bestillinger
                        symbol='circle'
                    ),
                    text=active_texts,
                    hoverinfo='text',
                    name='Aktiv bestilling',
                    showlegend=True
                ))
        
        # Oppdater layout
        fig.update_layout(
            mapbox=dict(
                accesstoken=mapbox_token,
                style='streets',
                zoom=14,
                center=dict(lat=59.39111, lon=6.42755)
            ),
            margin=dict(l=0, r=0, t=30, b=0),
            title=title or "Tunbrøytingskart",
            showlegend=True,
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=0.01,
                bgcolor="rgba(255, 255, 255, 0.9)",
                bordercolor="rgba(0, 0, 0, 0.2)",
                borderwidth=1
            ),
            height=600
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Feil i vis_dagens_tunkart: {str(e)}", exc_info=True)
        return None
    
def vis_stroingskart_kommende(bestillinger, mapbox_token, title):
    try:
        fig = go.Figure()

        # Filtrer ut bestillinger uten gyldige koordinater
        valid_bestillinger = bestillinger.dropna(subset=["Latitude", "Longitude"])

        if valid_bestillinger.empty:
            raise ValueError("Ingen gyldige bestillinger med koordinater funnet")

        # Konverter 'Latitude' og 'Longitude' til float
        valid_bestillinger["Latitude"] = valid_bestillinger["Latitude"].astype(float)
        valid_bestillinger["Longitude"] = valid_bestillinger["Longitude"].astype(float)

        # Sorter bestillingene slik at dagens bestillinger kommer sist (for å være på toppen av kartet)
        valid_bestillinger = valid_bestillinger.sort_values(
            "dager_til", ascending=False
        )

        for _, row in valid_bestillinger.iterrows():
            if row["dager_til"] == 0:
                color = "red"
                size = 12  # Litt større markør for dagens bestillinger
            else:
                # Beregn en gulfargetone som blir lysere jo lengre fram i tid
                intensity = max(0, min(1, 1 - (row["dager_til"] - 1) / 6))
                color = f"rgba(255, 255, 0, {intensity})"
                size = 10

            fig.add_trace(
                go.Scattermapbox(
                    lat=[row["Latitude"]],
                    lon=[row["Longitude"]],
                    mode="markers",
                    marker=go.scattermapbox.Marker(size=size, color=color, opacity=0.7),
                    text=f"Hytte: {row['bruker']}<br>Dato: {format_date(row['onske_dato'], 'display', 'date')}<br>Dager til: {row['dager_til']}",
                    hoverinfo="text",
                )
            )

        # Beregn zoom-nivå basert på spredningen av punkter
        lat_range = (
            valid_bestillinger["Latitude"].max() - valid_bestillinger["Latitude"].min()
        )
        lon_range = (
            valid_bestillinger["Longitude"].max()
            - valid_bestillinger["Longitude"].min()
        )
        zoom = min(
            13.7, max(10, 12 - max(lat_range, lon_range) * 100)
        )  # Juster faktorene etter behov

        fig.update_layout(
            title=title,
            mapbox_style="streets",
            mapbox=dict(
                accesstoken=mapbox_token,
                center=dict(
                    lat=valid_bestillinger["Latitude"].mean(),
                    lon=valid_bestillinger["Longitude"].mean(),
                ),
                zoom=zoom,
            ),
            showlegend=False,
            height=600,
            margin={"r": 0, "t": 30, "l": 0, "b": 0},
        )

        return fig

    except Exception as e:
        print(f"Feil ved generering av strøingskart: {str(e)}")
        return None

def create_map(bestillinger: pd.DataFrame, mapbox_token: str = None, title: str = None, config: MapConfig = None):
    """Oppretter og returnerer kartet med bestillinger"""
    try:
        if config is None:
            config = create_default_map_config(mapbox_token)

        # Hent koordinater
        cabin_coordinates = get_cabin_coordinates()
        if not cabin_coordinates:
            logger.error("Ingen koordinater funnet")
            return None

        # Opprett kart
        fig = go.Figure()
        
        # Legg til markører for hver bestilling
        for _, booking in bestillinger.iterrows():
            coords = cabin_coordinates.get(str(booking['customer_id']))
            if not coords:
                continue
                
            # Bruk config.py for å generere popup tekst
            map_booking = MapBooking(
                customer_id=str(booking['customer_id']),
                ankomst_dato=booking.get('ankomst_dato'),
                avreise_dato=booking.get('avreise_dato'),
                abonnement_type=booking['abonnement_type'],
                is_active=booking.get('is_active', True)
            )
            popup_text = get_map_popup_text(map_booking)
            
            marker_style = map_booking.get_marker_style(config)
            fig.add_trace(
                go.Scattermapbox(
                    lat=[coords['lat']],
                    lon=[coords['lon']],
                    mode='markers',
                    marker=marker_style,
                    text=[popup_text],
                    hoverinfo='text'
                )
            )

        # Konfigurer kartvisning
        fig.update_layout(
            mapbox=dict(
                accesstoken=mapbox_token,
                style='outdoors',
                zoom=14
            ),
            title=title,
            showlegend=False,
            margin=dict(l=0, r=0, t=30, b=0)
        )

        return fig

    except Exception as e:
        logger.error(f"Feil ved opprettelse av kart: {str(e)}")
        return None


def display_live_plowmap():
    st.title("Live Brøytekart")
    # Informasjonstekst
    st.info(
        """
    Gjil Maskin, som holder til på Hauge ved Jøsenfjorden, brøyter i Fjellbergsskardet.  
    Du kan følge brøytingen live p kartet vårt! GPS-sporing aktiveres når traktoren starter å kjøre.

    Vær oppmerksom på:
    - Det er ca. 10 minutters forsinkelse på GPS-signalet.
    - GPS-spor kan vise som brøytet selv om traktoren bare har kjørt forbi. 
    Dette skyldes en liten feilmargin i posisjoneringen.
    - Noen stikkveier i hyttegrenda er ikke med på kartet. 
    De blir brøytet selv om det ikke vises spor.
    """
    )
    st.components.v1.html(
        '<iframe style="height: 100vh; width: 100vw;" src="https://plowman-new.xn--snbryting-m8ac.net/nb/share/Y3VzdG9tZXItMTM=" title="Live brøytekart"></iframe>',
        height=600,
        scrolling=True,
    )

def display_map(bookings: List[MapBooking], config: MapConfig):
    """Viser kart basert på forberedte booking-objekter"""
    try:
        validate_map_data(bookings)
        
    except Exception as e:
        logger.error(f"Feil ved visning av kart: {str(e)}")
        st.error("Kunne ikke vise kart")
        return None
    