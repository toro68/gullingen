# map_utils.py
# Standard library imports
import logging
from datetime import datetime, timedelta

# Third-party imports
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Local imports
from utils.core.config import TZ
from utils.core.logging_config import get_logger
from utils.core.util_functions import get_marker_properties
from utils.services.customer_utils import get_cabin_coordinates, load_customer_database
from utils.services.utils import is_active_booking
# Set up logging
logger = get_logger(__name__)


def vis_dagens_tunkart(bestillinger, mapbox_token, title):
    logger.info(f"Starter vis_dagens_tunkart med {len(bestillinger)} bestillinger")
    
    try:
        cabin_coordinates = get_cabin_coordinates()
        if not cabin_coordinates:
            logger.error("Ingen koordinater funnet")
            st.error("Kunne ikke laste koordinater for hyttene")
            return
            
        current_date = datetime.now(TZ).date()
        
        # Hent aktive bestillinger
        from utils.services.tun_utils import hent_aktive_bestillinger_for_dag
        aktive_bestillinger = hent_aktive_bestillinger_for_dag(current_date)
        
        if aktive_bestillinger is None or aktive_bestillinger.empty:
            logger.info("Ingen aktive bestillinger for dagens dato")
            aktive_bestillinger = pd.DataFrame(columns=["customer_id", "abonnement_type", "ankomst_dato", "avreise_dato"])
        
        logger.info(f"Aktive bestillinger: {aktive_bestillinger.to_string()}")
        
        # Definerer farger
        GREEN = "#03b01f"  # Grønn for årsabonnement
        RED = "#db0000"    # Rød for vanlige bestillinger
        GRAY = "#C0C0C0"   # Grå for inaktive
        
        points_data = []
        for cabin_id, (lat, lon) in cabin_coordinates.items():
            if pd.isna(lat) or pd.isna(lon):
                continue
                
            cabin_bookings = aktive_bestillinger[aktive_bestillinger["customer_id"].astype(str) == str(cabin_id)]
            
            point = {
                "lat": lat,
                "lon": lon,
                "color": GRAY,
                "size": 8,
                "text": f"Hytte: {cabin_id}<br>"
            }
            
            if not cabin_bookings.empty:
                booking = cabin_bookings.iloc[0]
                point["color"] = GREEN if booking["abonnement_type"] == "Årsabonnement" else RED
                point["size"] = 12
                point["text"] += (
                    f"Status: Aktiv<br>"
                    f"Type: {booking['abonnement_type']}<br>"
                    f"Ankomst: {booking['ankomst_dato'].strftime('%Y-%m-%d')}<br>"
                    f"Avreise: {booking['avreise_dato'].strftime('%Y-%m-%d') if pd.notnull(booking['avreise_dato']) else 'Ikke satt'}"
                )
            
            points_data.append(point)
        
        if not points_data:
            logger.error("Ingen gyldige punkter å vise på kartet")
            st.error("Kunne ikke generere kartvisning")
            return
            
        # Opprett kartdata for Plotly
        map_data = []
        
        # Grupper punkter etter type
        yearly_points = {"lat": [], "lon": [], "text": [], "name": "Årsabonnement"}
        weekly_points = {"lat": [], "lon": [], "text": [], "name": "Ukentlig bestilling"}
        inactive_points = {"lat": [], "lon": [], "text": [], "name": "Ingen bestilling"}
        
        for point in points_data:
            if point["color"] == GREEN:
                yearly_points["lat"].append(point["lat"])
                yearly_points["lon"].append(point["lon"])
                yearly_points["text"].append(point["text"])
            elif point["color"] == RED:
                weekly_points["lat"].append(point["lat"])
                weekly_points["lon"].append(point["lon"])
                weekly_points["text"].append(point["text"])
            else:
                inactive_points["lat"].append(point["lat"])
                inactive_points["lon"].append(point["lon"])
                inactive_points["text"].append(point["text"])
        
        # Legg til scatter traces for hver type
        if yearly_points["lat"]:
            map_data.append({
                "type": "scattermapbox",
                "lat": yearly_points["lat"],
                "lon": yearly_points["lon"],
                "text": yearly_points["text"],
                "name": yearly_points["name"],
                "mode": "markers",
                "marker": {"size": 12, "color": GREEN},
                "hoverinfo": "text"
            })
            
        if weekly_points["lat"]:
            map_data.append({
                "type": "scattermapbox",
                "lat": weekly_points["lat"],
                "lon": weekly_points["lon"],
                "text": weekly_points["text"],
                "name": weekly_points["name"],
                "mode": "markers",
                "marker": {"size": 12, "color": RED},
                "hoverinfo": "text"
            })
            
        if inactive_points["lat"]:
            map_data.append({
                "type": "scattermapbox",
                "lat": inactive_points["lat"],
                "lon": inactive_points["lon"],
                "text": inactive_points["text"],
                "name": inactive_points["name"],
                "mode": "markers",
                "marker": {"size": 8, "color": GRAY},
                "hoverinfo": "text"
            })
        
        # Opprett og returner kartet
        return create_map(map_data, mapbox_token, title)

    except Exception as e:
        logger.error(f"Feil i vis_dagens_tunkart: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved generering av tunkart")


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
                    text=f"Hytte: {row['bruker']}<br>Dato: {row['onske_dato'].strftime('%d.%m.%Y')}<br>Dager til: {row['dager_til']}",
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


def create_map(data, mapbox_token, title):
    """Opprett basiskart med Gullingen som senterpunkt og legende i øvre venstre hjørne"""
    fig = go.Figure(data=data)
    
    fig.update_layout(
        title=title,
        mapbox=dict(
            accesstoken=mapbox_token,
            style='streets',
            center=dict(lat=59.39210, lon=6.43016),  # Gullingen koordinater
            zoom=13.8
        ),
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255, 255, 255, 0.8)",  # Hvit bakgrunn med litt gjennomsiktighet
            bordercolor="rgba(0, 0, 0, 0.3)",    # Svart ramme med litt gjennomsiktighet
            borderwidth=1
        ),
        margin=dict(l=0, r=0, t=30, b=0)
    )
    
    return fig


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
            for _, row in bestillinger.iterrows():
                # Legg til markør for hver bestilling
                add_stroing_marker(m, row)

        return True

    except Exception as e:
        logger.error(f"Feil ved visning av strøing på kart: {str(e)}")
        return False
