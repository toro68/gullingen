# map_utils.py

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
from db_utils import TZ, is_active_booking, get_cabin_coordinates

def vis_dagens_tunkart(bestillinger, mapbox_token, title):
    cabin_coordinates = get_cabin_coordinates()
    current_date = datetime.now(TZ).date()
    
    latitudes, longitudes, texts, colors, sizes = [], [], [], [], []
    
    # Definerer intense farger
    BLUE = '#03b01f'  # Intens grønn for aktive årsabonnementer
    RED = '#db0000'   # Intens rød for andre aktive bestillinger
    GRAY = '#eaeaea'  # Lysere grå for inaktive bestillinger
    
    legend_colors = {
        "Årsabonnement": BLUE,
        "Ukentlig ved bestilling": RED,
        "Ingen bestilling": GRAY
    }
    
    for coord in cabin_coordinates:
        cabin_id = coord['cabin_id']
        lat, lon = coord['latitude'], coord['longitude']
        
        if lat and lon and not (pd.isna(lat) or pd.isna(lon)):
            latitudes.append(lat)
            longitudes.append(lon)
            
            cabin_bookings = bestillinger[bestillinger['bruker'] == str(cabin_id)]
            if not cabin_bookings.empty:
                booking = cabin_bookings.iloc[0]
                is_active = is_active_booking(booking, current_date)
                
                if is_active:
                    if booking['abonnement_type'] == "Årsabonnement":
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
                
                status = 'Aktiv' if is_active else 'Inaktiv'
                text = f"Hytte: {cabin_id}<br>Status: {status}<br>Type: {booking['abonnement_type']}<br>Ankomst: {booking['ankomst'].date()}<br>Avreise: {booking['avreise'].date() if pd.notnull(booking['avreise']) else 'Ikke satt'}"
            else:
                color = GRAY
                legend_text = "Ingen bestilling"
                size = 8
                text = f"Hytte: {cabin_id}<br>Ingen bestilling"
            
            colors.append(color)
            sizes.append(size)
            texts.append(text)

    fig = go.Figure()

    fig.add_trace(go.Scattermapbox(
        lat=latitudes,
        lon=longitudes,
        mode='markers',
        marker=go.scattermapbox.Marker(
            size=sizes,
            color=colors,
            opacity=1.0,
        ),
        text=texts,
        hoverinfo='text'
    ))

    fig.update_layout(
        title=title,
        mapbox_style="streets",
        mapbox=dict(
            accesstoken=mapbox_token,
            center=dict(lat=sum(latitudes)/len(latitudes), lon=sum(longitudes)/len(longitudes)),
            zoom=13.8
        ),
        
        showlegend=True,
        legend=dict(
            traceorder='reversed',
            itemsizing='constant',
            title='Forklaring',
            orientation='h',
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        height=600,
        margin={"r":0,"t":30,"l":0,"b":0}
    )

    # Legg til forklaringen, men bare for kategorier som faktisk er i bruk
    for legend_text, color in legend_colors.items():
        if color in colors:
            fig.add_trace(go.Scatter(
                x=[None],
                y=[None],
                mode='markers',
                marker=dict(size=10, color=color),
                showlegend=True,
                name=legend_text
            ))

    return fig

def vis_kommende_tunbestillinger(bestillinger, mapbox_token, title):
    cabin_coordinates = get_cabin_coordinates()
    current_date = datetime.now(TZ).date()
    end_date = current_date + timedelta(days=7)
    
    latitudes, longitudes, texts, colors, sizes = [], [], [], [], []
    
    # Definerer basefargene
    BASE_BLUE = '#03b01f'  # Grønn for årsabonnementer
    BASE_RED = '#db0000'   # Rød for andre bestillinger
    GRAY = '#eaeaea'       # Grå for inaktive bestillinger

    # Funksjon for å justere fargeintensitet
    def adjust_color_intensity(base_color, days_until):
        rgb = [int(base_color[i:i+2], 16) for i in (1, 3, 5)]
        factor = 1 - (days_until - 1) / 7  # 1 for dag 1, 0 for dag 7
        adjusted_rgb = [int(c + (255 - c) * (1 - factor)) for c in rgb]
        return '#{:02x}{:02x}{:02x}'.format(*adjusted_rgb)

    legend_colors = {
        "Årsabonnement": BASE_BLUE,
        "Ukentlig ved bestilling": BASE_RED,
        "Ingen bestilling": GRAY
    }
    
    for coord in cabin_coordinates:
        cabin_id = coord['cabin_id']
        lat, lon = coord['latitude'], coord['longitude']
        
        if lat and lon and not (pd.isna(lat) or pd.isna(lon)):
            latitudes.append(lat)
            longitudes.append(lon)
            
            cabin_bookings = bestillinger[bestillinger['bruker'] == str(cabin_id)]
            if not cabin_bookings.empty:
                booking = cabin_bookings.iloc[0]
                ankomst_dato = pd.to_datetime(booking['ankomst']).date()
                
                if current_date < ankomst_dato <= end_date:
                    days_until = (ankomst_dato - current_date).days
                    if booking['abonnement_type'] == "Årsabonnement":
                        color = adjust_color_intensity(BASE_BLUE, days_until)
                        legend_text = "Årsabonnement"
                    else:
                        color = adjust_color_intensity(BASE_RED, days_until)
                        legend_text = "Ukentlig ved bestilling"
                    size = 12 - days_until  # Størrelsen minsker jo lenger frem i tid
                else:
                    color = GRAY
                    legend_text = "Ingen bestilling"
                    size = 8
                
                text = f"Hytte: {cabin_id}<br>Type: {booking['abonnement_type']}<br>Ankomst: {ankomst_dato}<br>Avreise: {booking['avreise'].date() if pd.notnull(booking['avreise']) else 'Ikke satt'}"
            else:
                color = GRAY
                legend_text = "Ingen bestilling"
                size = 8
                text = f"Hytte: {cabin_id}<br>Ingen bestilling"
            
            colors.append(color)
            sizes.append(size)
            texts.append(text)

    fig = go.Figure()

    fig.add_trace(go.Scattermapbox(
        lat=latitudes,
        lon=longitudes,
        mode='markers',
        marker=go.scattermapbox.Marker(
            size=sizes,
            color=colors,
            opacity=1.0,
        ),
        text=texts,
        hoverinfo='text'
    ))

    fig.update_layout(
        title=title,
        mapbox_style="streets",
        mapbox=dict(
            accesstoken=mapbox_token,
            center=dict(lat=sum(latitudes)/len(latitudes), lon=sum(longitudes)/len(longitudes)),
            zoom=13
        ),
        showlegend=True,
        legend=dict(
            traceorder='reversed',
            itemsizing='constant',
            title='Forklaring',
            orientation='h',
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        height=600,
        margin={"r":0,"t":30,"l":0,"b":0}
    )

    # Legg til forklaringen med basisfarger
    for legend_text, color in legend_colors.items():
        fig.add_trace(go.Scatter(
            x=[None],
            y=[None],
            mode='markers',
            marker=dict(size=10, color=color),
            showlegend=True,
            name=legend_text
        ))

    return fig

def vis_stroingskart_kommende(bestillinger, mapbox_token, title):
    fig = go.Figure()

    # Filtrer ut bestillinger uten gyldige koordinater
    valid_bestillinger = bestillinger.dropna(subset=['Latitude', 'Longitude'])

    # Sorter bestillingene slik at dagens bestillinger kommer sist (for å være på toppen av kartet)
    valid_bestillinger = valid_bestillinger.sort_values('dager_til', ascending=False)

    for _, row in valid_bestillinger.iterrows():
        if row['dager_til'] == 0:
            color = 'red'
            size = 12  # Litt større markør for dagens bestillinger
        else:
            # Beregn en gulfargetone som blir lysere jo lengre fram i tid
            color = f'rgba(255, 255, 0, {1 - (row["dager_til"] - 1) / 6})'
            size = 10
        
        fig.add_trace(go.Scattermapbox(
            lat=[row['Latitude']],
            lon=[row['Longitude']],
            mode='markers',
            marker=go.scattermapbox.Marker(
                size=size,
                color=color,
                opacity=0.7
            ),
            text=f"Hytte: {row['bruker']}<br>Dato: {row['onske_dato'].strftime('%Y-%m-%d')}<br>Dager til: {row['dager_til']}",
            hoverinfo='text'
        ))

    if not valid_bestillinger.empty:
        center_lat = valid_bestillinger['Latitude'].mean()
        center_lon = valid_bestillinger['Longitude'].mean()
    else:
        # Default koordinater hvis ingen gyldige bestillinger
        center_lat, center_lon = 59.39111, 6.42755  # Eksempelkoordinater for Gullingen

    fig.update_layout(
        title=title,
        mapbox_style="streets",
        mapbox=dict(
            accesstoken=mapbox_token,
            center=dict(lat=center_lat, lon=center_lon),
            zoom=13.7
        ),
        showlegend=False,
        height=600,
        margin={"r":0,"t":30,"l":0,"b":0}
    )

    return fig
 
def create_map(data, mapbox_token, tittel):
    fig = go.Figure(data=data)

    all_lats = [point for trace in data for point in trace['lat']]
    all_lons = [point for trace in data for point in trace['lon']]

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
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        ),
        height=700,
        margin={"r":0,"t":30,"l":0,"b":0}
    )

    return fig

    fig = go.Figure()

    for _, row in bestillinger.iterrows():
        if row['dager_til'] == 0:
            color = 'red'
        else:
            # Beregn en gulfargetone som blir lysere jo lengre fram i tid
            color = f'rgba(255, 255, 0, {1 - (row["dager_til"] - 1) / 6})'
        
        fig.add_trace(go.Scattermapbox(
            lat=[row['Latitude']],
            lon=[row['Longitude']],
            mode='markers',
            marker=go.scattermapbox.Marker(
                size=10,
                color=color,
                opacity=0.7
            ),
            text=f"Hytte: {row['bruker']}<br>Dato: {row['onske_dato'].strftime('%Y-%m-%d')}<br>Dager til: {row['dager_til']}",
            hoverinfo='text'
        ))

    fig.update_layout(
        title=title,
        mapbox_style="streets",
        mapbox=dict(
            accesstoken=mapbox_token,
            center=dict(lat=bestillinger['Latitude'].mean(), lon=bestillinger['Longitude'].mean()),
            zoom=10
        ),
        showlegend=False,
        height=600,
        margin={"r":0,"t":30,"l":0,"b":0}
    )

    return fig