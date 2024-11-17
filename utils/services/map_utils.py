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
    
    cabin_coordinates = get_cabin_coordinates()
    current_date = datetime.now(TZ).date()
    
    # Hent aktive bestillinger fra tun_utils
    from utils.services.tun_utils import hent_aktive_bestillinger_for_dag
    aktive_bestillinger = hent_aktive_bestillinger_for_dag(current_date)
    logger.info(f"Aktive bestillinger for dagens dato {current_date}: {aktive_bestillinger.to_string()}")

    latitudes, longitudes, texts, colors, sizes = [], [], [], [], []

    # Definerer farger
    BLUE = "#03b01f"  # Grønn for årsabonnement
    RED = "#db0000"   # Rød for vanlige bestillinger
    GRAY = "#C0C0C0"  # Grå for inaktive

    for cabin_id, (lat, lon) in cabin_coordinates.items():
        if lat and lon and not (pd.isna(lat) or pd.isna(lon)):
            latitudes.append(lat)
            longitudes.append(lon)

            # Finn aktiv bestilling for denne hytta
            cabin_bookings = aktive_bestillinger[aktive_bestillinger["bruker"].astype(str) == str(cabin_id)]
            
            if not cabin_bookings.empty:
                booking = cabin_bookings.iloc[0]
                logger.info(f"Fant aktiv bestilling for hytte {cabin_id}: {dict(booking)}")
                
                color = BLUE if booking["abonnement_type"] == "Årsabonnement" else RED
                size = 12
            else:
                color = GRAY
                size = 8

            colors.append(color)
            sizes.append(size)
            
            # Oppdater hover-tekst
            text = f"Hytte: {cabin_id}<br>"
            if not cabin_bookings.empty:
                text += (
                    f"Status: Aktiv<br>"
                    f"Type: {booking['abonnement_type']}<br>"
                    f"Ankomst: {booking['ankomst_dato'].strftime('%Y-%m-%d')}<br>"
                    f"Avreise: {booking['avreise_dato'].strftime('%Y-%m-%d') if pd.notnull(booking['avreise_dato']) else 'Ikke satt'}"
                )
            texts.append(text)

    # Opprett figur og legg til markører
    data = [
        go.Scattermapbox(
            lat=latitudes,
            lon=longitudes,
            mode="markers",
            marker=go.scattermapbox.Marker(
                size=sizes,
                color=colors,
                opacity=1.0,
            ),
            text=texts,
            hoverinfo="text",
        )
    ]

    fig = create_map(data, mapbox_token, title)

    # Legg til forklaring
    legend_items = {
        "Årsabonnement": BLUE,
        "Ukentlig ved bestilling": RED,
        "Ingen bestilling": GRAY
    }

    for legend_text, color in legend_items.items():
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker=dict(size=10, color=color),
                showlegend=True,
                name=legend_text,
            )
        )

    return fig

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


def create_map(data, mapbox_token, tittel):
    fig = go.Figure(data=data)

    all_lats = [point for trace in data for point in trace["lat"]]
    all_lons = [point for trace in data for point in trace["lon"]]

    center_lat = sum(all_lats) / len(all_lats) if all_lats else 59.39111
    center_lon = sum(all_lons) / len(all_lons) if all_lons else 6.42755

    fig.update_layout(
        title=tittel,
        mapbox_style="streets",
        mapbox=dict(
            accesstoken=mapbox_token,
            center=dict(lat=center_lat, lon=center_lon),
            zoom=14,
        ),
        showlegend=True,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        height=700,
        margin={"r": 0, "t": 30, "l": 0, "b": 0},
    )

    return fig


def display_live_plowmap():
    st.title("Live Brøytekart")
    # Informasjonstekst
    st.info(
        """
    Gjil Maskin, som holder til på Hauge ved Jøsenfjorden, brøyter i Fjellbergsskardet.  
    Du kan følge brøytingen live på kartet vårt! GPS-sporing aktiveres når traktoren starter å kjøre.

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
