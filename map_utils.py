# map_utils.py

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
from db_utils import TZ, is_active_booking, get_cabin_coordinates

def vis_tunkart(bestillinger, mapbox_token, title, vis_type='all'):
    cabin_coordinates = get_cabin_coordinates()
    current_date = datetime.now(TZ).date()
    
    latitudes, longitudes, texts, colors, sizes = [], [], [], [], []
    
    color_scale = ['#FF0000', '#FF3300', '#FF6600', '#FF9900', '#FFCC00', '#FFFF00']
    
    for coord in cabin_coordinates:
        cabin_id = coord['cabin_id']
        lat, lon = coord['latitude'], coord['longitude']
        
        if lat and lon and not (pd.isna(lat) or pd.isna(lon)):
            latitudes.append(lat)
            longitudes.append(lon)
            
            cabin_bookings = bestillinger[bestillinger['bruker'] == str(cabin_id)]
            if not cabin_bookings.empty:
                booking = cabin_bookings.iloc[0]
                has_active_booking = is_active_booking(booking, current_date)
                
                if vis_type == 'today' and has_active_booking:
                    color = "#FF0000"  # Sterk rød for aktive bestillinger i dag
                    size = 12
                elif vis_type == 'active':
                    ankomst_dato = pd.to_datetime(booking['ankomst_dato']).date()
                    days_until = (ankomst_dato - current_date).days
                    if days_until <= 0 or days_until > 6:
                        color = "#CCCCCC"  # Grå for inaktive eller dagens bestillinger
                    else:
                        color = color_scale[days_until - 1]  # Farger for dag 1-6
                    size = 10 if 0 < days_until <= 6 else 8
                else:
                    color = "#0000FF" if booking['abonnement_type'] == "Årsabonnement" else "#FF0000"
                    size = 10
                
                text = f"Hytte: {cabin_id}<br>Status: {'Aktiv' if has_active_booking else 'Inaktiv'}<br>Type: {booking['abonnement_type']}"
            else:
                color = "#CCCCCC"  # Grå for hytter uten bestilling
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
        showlegend=False,
        height=600,
        margin={"r":0,"t":30,"l":0,"b":0}
    )

    return fig, color_scale

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

def vis_stroingskart(bestillinger, mapbox_token, tittel):
    stroing_color_scale = ['#FF0000', '#FF3300', '#FF6600', '#FF9900', '#FFCC00', '#FFFF00', '#CCFF00']

    cabin_coordinates = get_cabin_coordinates()
    current_date = pd.Timestamp.now(tz=TZ).date()

    latitudes, longitudes, texts, colors, sizes = [], [], [], [], []

    for coord in cabin_coordinates:
        cabin_id = coord['cabin_id']
        lat = float(coord['latitude'])
        lon = float(coord['longitude'])
        
        if lat != 0 and lon != 0 and not (pd.isna(lat) or pd.isna(lon)):
            latitudes.append(lat)
            longitudes.append(lon)
        
            user_bookings = bestillinger[bestillinger['bruker'].astype(str) == str(cabin_id)]
            booking = user_bookings.iloc[0] if not user_bookings.empty else None
            
            if booking is not None:
                days_until = (booking['onske_dato'].date() - current_date).days
                if days_until == 0:
                    icon_color = stroing_color_scale[0]
                    status_text = "Strøing i dag"
                elif 0 < days_until <= 7:
                    icon_color = stroing_color_scale[days_until]
                    status_text = f"Strøing om {days_until} dager"
                else:
                    icon_color = '#AAAAAA'
                    status_text = f"Strøing planlagt {booking['onske_dato'].strftime('%Y-%m-%d')}"
                size = 12
            else:
                icon_color = 'gray'
                status_text = "Ingen bestilling"
                size = 10
            
            text = f"Hytte: {cabin_id}<br>Status: {status_text}"
            texts.append(text)
            colors.append(icon_color)
            sizes.append(size)

    return create_map(latitudes, longitudes, texts, colors, sizes, mapbox_token, tittel)

def is_active_booking(booking, current_date):
    # Implement the logic to check if a booking is active
    # This function should be defined based on your specific requirements
    pass