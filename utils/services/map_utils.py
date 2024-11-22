# map_utils.py
# Standard library imports
from datetime import datetime

# Third-party imports
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Local imports
from utils.core.config import (
    safe_to_datetime,
    format_date
)
from utils.core.logging_config import get_logger
from utils.core.util_functions import get_marker_properties
from utils.services.customer_utils import get_cabin_coordinates
from utils.core.validation_utils import validate_cabin_id, validate_date
from utils.services.stroing_utils import (
    hent_stroing_bestillinger
)

# Set up logging
logger = get_logger(__name__)

# Fargekonstanter for kartmarkører
GREEN = "#03b01f"  # Årsabonnement
RED = "#db0000"    # Ukentlig bestilling
GRAY = "#C0C0C0"   # Ingen bestilling

def vis_dagens_tunkart(bestillinger, mapbox_token, title):
    """Viser kart over dagens tunbrøytinger."""
    logger.info(f"Starter vis_dagens_tunkart med {len(bestillinger)} bestillinger")
    
    try:
        # Hent koordinater for alle hytter
        cabin_coordinates = get_cabin_coordinates()
        if not cabin_coordinates:
            logger.error("Ingen koordinater funnet")
            st.error("Kunne ikke laste koordinater for hyttene")
            return None
            
        # Debug logging
        debug_map_data(bestillinger)
        
        # Opprett kartet med grupperte markører
        fig = go.Figure()
        
        # Legg til grå markører som én gruppe
        gray_lats = []
        gray_lons = []
        gray_texts = []
        for cabin_id, (lat, lon) in cabin_coordinates.items():
            gray_lats.append(lat)
            gray_lons.append(lon)
            gray_texts.append(f"Hytte: {cabin_id}")
        
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
        
        # Grupper aktive bestillinger etter type
        if not bestillinger.empty:
            yearly_bookings = bestillinger[bestillinger['abonnement_type'] == 'Årsabonnement']
            weekly_bookings = bestillinger[bestillinger['abonnement_type'] != 'Årsabonnement']
            
            # Legg til årsabonnement
            if not yearly_bookings.empty:
                yearly_lats = []
                yearly_lons = []
                yearly_texts = []
                for _, booking in yearly_bookings.iterrows():
                    customer_id = str(booking['customer_id'])
                    if customer_id in cabin_coordinates:
                        lat, lon = cabin_coordinates[customer_id]
                        yearly_lats.append(lat)
                        yearly_lons.append(lon)
                        yearly_texts.append(get_map_popup_text(booking))
                
                if yearly_lats:  # Bare legg til hvis det finnes punkter
                    fig.add_trace(go.Scattermapbox(
                        lat=yearly_lats,
                        lon=yearly_lons,
                        mode='markers',
                        marker=dict(size=12, color=GREEN),
                        text=yearly_texts,
                        hoverinfo='text',
                        name='Årsabonnement',
                        showlegend=True
                    ))
            
            # Legg til ukentlige bestillinger
            if not weekly_bookings.empty:
                weekly_lats = []
                weekly_lons = []
                weekly_texts = []
                for _, booking in weekly_bookings.iterrows():
                    customer_id = str(booking['customer_id'])
                    if customer_id in cabin_coordinates:
                        lat, lon = cabin_coordinates[customer_id]
                        weekly_lats.append(lat)
                        weekly_lons.append(lon)
                        weekly_texts.append(get_map_popup_text(booking))
                
                if weekly_lats:  # Bare legg til hvis det finnes punkter
                    fig.add_trace(go.Scattermapbox(
                        lat=weekly_lats,
                        lon=weekly_lons,
                        mode='markers',
                        marker=dict(size=12, color=RED),
                        text=weekly_texts,
                        hoverinfo='text',
                        name='Ukentlig bestilling',
                        showlegend=True
                    ))
        
        # Oppdatert layout med forbedret legend
        fig.update_layout(
            mapbox=dict(
                accesstoken=mapbox_token,
                style='streets',
                zoom=13,
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
                borderwidth=1,
                font=dict(size=12),
                itemsizing='constant',
                itemwidth=30,
                orientation="v",
                traceorder="normal"
            ),
            height=600
        )
        
        # Vis kartet
        st.plotly_chart(fig, use_container_width=True)
        
        # Vis informasjonstekst om antall bestillinger
        if bestillinger.empty:
            st.info("Ingen aktive bestillinger i dag.")
        else:
            st.success(f"Viser {len(bestillinger)} aktive bestillinger.")
            
        return fig
        
    except Exception as e:
        logger.error(f"Feil i vis_dagens_tunkart: {str(e)}", exc_info=True)
        st.error("Kunne ikke vise kart")
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


def create_map(bestillinger: pd.DataFrame, mapbox_token: str = None, title: str = None):
    """Oppretter og returnerer kartet med bestillinger"""
    try:
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
            popup_text = get_booking_popup_text(booking)
            
            # Legg til markør
            marker_props = get_marker_properties(booking['abonnement_type'])
            fig.add_trace(
                go.Scattermapbox(
                    lat=[coords['lat']],
                    lon=[coords['lon']],
                    mode='markers',
                    marker=marker_props,
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


def add_stroing_to_map(m):
    """Legger til strøingsinformasjon på kartet"""
    try:
        # Hent aktive strøingsbestillinger
        bestillinger = hent_stroing_bestillinger()
        if not bestillinger.empty:
            for col in ['dato', 'bestilt_dato']:  # anta disse kolonnene finnes
                if col in bestillinger.columns:
                    bestillinger[col] = bestillinger[col].apply(
                        lambda x: safe_to_datetime(x)
                    )
            for _, row in bestillinger.iterrows():
                # Legg til markør for hver bestilling
                add_stroing_marker(m, row)

        return True

    except Exception as e:
        logger.error(f"Feil ved visning av strøing på kart: {str(e)}")
        return False

def prepare_map_data(bestillinger: pd.DataFrame) -> pd.DataFrame:
    """Forbereder data for kartvisning"""
    try:
        if bestillinger.empty:
            return bestillinger
            
        # Først konverter til datetime objekter
        date_columns = ['ankomst_dato', 'avreise_dato', 'onske_dato', 'bestilt_dato']
        for col in date_columns:
            if col in bestillinger.columns:
                bestillinger[col] = bestillinger[col].apply(safe_to_datetime)
                
        # Så konverter til database format for validering
        for col in ['ankomst_dato', 'avreise_dato']:
            if col in bestillinger.columns:
                bestillinger[f"{col}_db"] = bestillinger[col].apply(
                    lambda x: format_date(x, "database", "date") if pd.notna(x) else None
                )
                
        # Til slutt lag formaterte versjoner for visning
        for col in date_columns:
            if col in bestillinger.columns:
                bestillinger[f"{col}_formatted"] = bestillinger[col].apply(
                    lambda x: format_date(x, "display", "date") if pd.notna(x) else None
                )
        
        return bestillinger
        
    except Exception as e:
        logger.error(f"Feil i prepare_map_data: {str(e)}")
        return pd.DataFrame()

def verify_map_configuration(bestillinger: pd.DataFrame, mapbox_token: str = None) -> tuple[bool, str]:
    try:
        if bestillinger.empty:
            return False, "Ingen bestillinger å vise"
            
        # Valider påkrevde kolonner fra faktisk skjema
        required_cols = ['customer_id', 'ankomst_dato', 'avreise_dato', 'abonnement_type']
        missing = [col for col in required_cols if col not in bestillinger.columns]
        if missing:
            return False, f"Mangler kolonner: {', '.join(missing)}"
            
        # Valider mapbox token
        if not mapbox_token:
            return False, "Mapbox token mangler"
            
        # Valider koordinater
        cabin_coordinates = get_cabin_coordinates()
        if not cabin_coordinates:
            return False, "Ingen koordinater funnet for hyttene"
            
        # Valider hver bestilling
        invalid_cabins = []
        invalid_dates = []
        missing_coords = []
        
        for _, row in bestillinger.iterrows():
            # Valider hyttenummer
            if not validate_cabin_id(str(row['customer_id'])):
                invalid_cabins.append(str(row['customer_id']))
                
            # Valider datoer direkte
            for date_col in ['ankomst_dato', 'avreise_dato']:
                if pd.notna(row[date_col]) and not validate_date(
                    format_date(row[date_col], 'database', 'date')
                ):
                    invalid_dates.append(f"{row['customer_id']}: {date_col}")
                    
            # Sjekk koordinater
            if str(row['customer_id']) not in cabin_coordinates:
                missing_coords.append(str(row['customer_id']))
        
        if invalid_cabins:
            return False, f"Ugyldige hyttenummer: {', '.join(invalid_cabins)}"
            
        if invalid_dates:
            return False, f"Ugyldige datoer for: {', '.join(invalid_dates)}"
            
        if missing_coords:
            return False, f"Mangler koordinater for hytter: {', '.join(missing_coords)}"
            
        return True, "Data er gyldig"
        
    except Exception as e:
        logger.error(f"Feil i verify_map_configuration: {str(e)}")
        return False, f"Valideringsfeil: {str(e)}"

def get_map_popup_text(booking: pd.Series) -> str:
    """Genererer popup-tekst for kartmarkører"""
    try:
        popup_text = [
            f"Hytte: {booking['customer_id']}",
            f"Ankomst: {format_date(booking['ankomst_dato'], 'display', 'date')}"
        ]
        
        if pd.notna(booking['avreise_dato']):
            popup_text.append(f"Avreise: {booking['avreise_dato']}")
            
        popup_text.append(f"Type: {booking['abonnement_type']}")
        
        return "<br>".join(popup_text)
        
    except Exception as e:
        logger.error(f"Feil i get_map_popup_text: {str(e)}")
        return "Kunne ikke generere informasjon"

def debug_map_data(bestillinger: pd.DataFrame):
    """Logger debug informasjon om kartdata"""
    logger.info("=== Kart Debug Info ===")
    logger.info(f"Antall bestillinger: {len(bestillinger)}")
    logger.info(f"Kolonner i bestillinger: {bestillinger.columns.tolist()}")
    if not bestillinger.empty:
        logger.info(f"Første rad i bestillinger:\n{bestillinger.iloc[0]}")
        
def get_booking_popup_text(booking):
    """Genererer popup tekst for en bestilling på kartet"""
    try:
        status = booking.get('status', 'Ukjent')
        ankomst = booking.get('ankomst_dato', 'Ikke satt')
        avreise = booking.get('avreise_dato', 'Ikke satt')
        bestilt = booking.get('bestilt_dato', 'Ukjent')
        
        return f"""
        <b>Tunbrøyting</b><br>
        Status: {status}<br>
        Ankomst: {ankomst}<br>
        Avreise: {avreise}<br>
        Bestilt: {bestilt}
        """
    except Exception as e:
        logger.error(f"Feil ved generering av popup tekst: {str(e)}")
        return "Kunne ikke vise detaljer"