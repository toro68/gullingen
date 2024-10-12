# map_utils.py
# Standard library imports
import logging 
from datetime import datetime, timedelta

# Third-party imports
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Local imports
from constants import TZ
from customer_utils import get_cabin_coordinates, load_customer_database
from util_functions import get_marker_properties
from utils import is_active_booking

from logging_config import get_logger

# Set up logging
logger = get_logger(__name__)


def vis_dagens_tunkart(bestillinger, mapbox_token, title):
    cabin_coordinates = get_cabin_coordinates()
    current_date = datetime.now(TZ).date()

    latitudes, longitudes, texts, colors, sizes = [], [], [], [], []

    # Definerer intense farger
    BLUE = "#03b01f"  # Intens grønn for aktive årsabonnementer
    RED = "#db0000"  # Intens rød for andre aktive bestillinger
    GRAY = "#C0C0C0"  # Lysere grå for inaktive bestillinger

    legend_colors = {
        "Årsabonnement": BLUE,
        "Ukentlig ved bestilling": RED,
        "Ingen bestilling": GRAY,
    }

    for cabin_id, (lat, lon) in cabin_coordinates.items():
        if lat and lon and not (pd.isna(lat) or pd.isna(lon)):
            latitudes.append(lat)
            longitudes.append(lon)

            cabin_bookings = bestillinger[bestillinger["bruker"] == str(cabin_id)]
            if not cabin_bookings.empty:
                booking = cabin_bookings.iloc[0]
                ankomst = booking["ankomst"].date()
                avreise = booking["avreise"].date() if pd.notnull(booking["avreise"]) else None
                
                is_active = (booking["abonnement_type"] == "Årsabonnement" and current_date.weekday() == 4) or \
                            (ankomst <= current_date and (avreise is None or current_date <= avreise))

                if is_active:
                    if booking["abonnement_type"] == "Årsabonnement":
                        color = BLUE
                        legend_text = "Årsabonnement"
                    else:
                        color = RED
                        legend_text = "Ukentlig ved bestilling"
                    size = 12
                else:
                    color = GRAY
                    legend_text = "Ingen bestilling"
                    size = 8

                status = "Aktiv" if is_active else "Inaktiv"
                text = f"Hytte: {cabin_id}<br>Status: {status}<br>Type: {booking['abonnement_type']}<br>Ankomst: {ankomst}<br>Avreise: {avreise if avreise else 'Ikke satt'}"
            else:
                color = GRAY
                legend_text = "Ingen bestilling"
                size = 8
                text = f"Hytte: {cabin_id}<br>Ingen bestilling"

            colors.append(color)
            sizes.append(size)
            texts.append(text)

    fig = go.Figure()

    fig.add_trace(
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
    )

    fig.update_layout(
        title=title,
        mapbox_style="streets",
        mapbox=dict(
            accesstoken=mapbox_token,
            center=dict(
                lat=sum(latitudes) / len(latitudes),
                lon=sum(longitudes) / len(longitudes),
            ),
            zoom=13.8,
        ),
        showlegend=True,
        legend=dict(
            traceorder="reversed",
            itemsizing="constant",
            title="Forklaring",
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        height=600,
        margin={"r": 0, "t": 30, "l": 0, "b": 0},
    )

    # Legg til forklaringen, men bare for kategorier som faktisk er i bruk
    for legend_text, color in legend_colors.items():
        if color in colors:
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

def vis_kommende_tunbestillinger(bestillinger, mapbox_token, title):
    logger.info(f"Starting vis_kommende_tunbestillinger with {len(bestillinger)} bookings")
    cabin_coordinates = get_cabin_coordinates()
    current_date = datetime.now(TZ).date()
    end_date = current_date + timedelta(days=7)

    latitudes, longitudes, texts, colors, sizes = [], [], [], [], []

    # Define base colors
    BASE_BLUE = "#03b01f"  # Green for yearly subscriptions
    BASE_RED = "#db0000"  # Red for other bookings
    GRAY = "#eaeaea"  # Gray for inactive bookings

    # Function to adjust color intensity
    def adjust_color_intensity(base_color, days_until):
        rgb = [int(base_color[i:i+2], 16) for i in (1, 3, 5)]
        factor = max(0, min(1, 1 - (days_until - 1) / 7))  # Ensure factor is between 0 and 1
        adjusted_rgb = [min(255, max(0, int(c + (255 - c) * (1 - factor)))) for c in rgb]
        return "#{:02x}{:02x}{:02x}".format(*adjusted_rgb)

    legend_colors = {
        "Årsabonnement": BASE_BLUE,
        "Ukentlig ved bestilling": BASE_RED,
        "Ingen bestilling": GRAY,
    }

    for _, booking in bestillinger.iterrows():
        cabin_id = booking['bruker']
        lat, lon = cabin_coordinates.get(str(cabin_id), (None, None))
        
        if lat and lon and not (pd.isna(lat) or pd.isna(lon)):
            latitudes.append(lat)
            longitudes.append(lon)

            ankomst_dato = pd.to_datetime(booking["ankomst"]).date()
            days_until = (ankomst_dato - current_date).days

            logger.debug(f"Processing booking for cabin {cabin_id}: type={booking['abonnement_type']}, ankomst_dato={ankomst_dato}, days_until={days_until}")

            if current_date <= ankomst_dato <= end_date or booking["abonnement_type"] == "Årsabonnement":
                if booking["abonnement_type"] == "Årsabonnement":
                    color = BASE_BLUE
                    legend_text = "Årsabonnement"
                    size = 12
                else:
                    color = adjust_color_intensity(BASE_RED, max(0, days_until))
                    legend_text = "Ukentlig ved bestilling"
                    size = max(8, 12 - min(days_until, 4))  # Gradvis økning i størrelse over 4 dager
            else:
                color = GRAY
                legend_text = "Ingen bestilling"
                size = 8

            logger.debug(f"Marker properties for cabin {cabin_id}: color={color}, size={size}, legend_text={legend_text}")

            text = f"Hytte: {cabin_id}<br>Type: {booking['abonnement_type']}<br>Ankomst: {ankomst_dato}<br>Avreise: {booking['avreise'].date() if pd.notnull(booking['avreise']) else 'Ikke satt'}"

            colors.append(color)
            sizes.append(size)
            texts.append(text)

    logger.info(f"Prepared {len(latitudes)} points for the map")

    fig = go.Figure()

    fig.add_trace(
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
    )

    fig.update_layout(
        title=title,
        mapbox_style="streets",
        mapbox=dict(
            accesstoken=mapbox_token,
            center=dict(
                lat=sum(latitudes) / len(latitudes) if latitudes else 0,
                lon=sum(longitudes) / len(longitudes) if longitudes else 0,
            ),
            zoom=13,
        ),
        showlegend=True,
        legend=dict(
            traceorder="reversed",
            itemsizing="constant",
            title="Forklaring",
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        height=600,
        margin={"r": 0, "t": 30, "l": 0, "b": 0},
    )

    # Add legend with base colors
    for legend_text, color in legend_colors.items():
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

    logger.info("Finished creating the map")
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
