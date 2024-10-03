import hashlib
import os
import io
import logging
import sqlite3
import json
import time as pytime
import hmac
import re
import altair as alt
import xlsxwriter
import locale
import uuid

from contextlib import contextmanager # Context Manager
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo # ZoneInfo is a subclass of tzinfo
from io import BytesIO
from streamlit_calendar import calendar
from typing import List, Dict, Any

import numpy as np # NumPy
import pandas as pd # Pandas
import matplotlib.pyplot as plt
import plotly.express as px # Plotly Express
import requests     
from statsmodels.nonparametric.smoothers_lowess import lowess # Lowess Smoothing

import plotly.graph_objects as go # Plotly Graph Objects
from plotly.subplots import make_subplots # Plotly Subplots

import streamlit as st
from streamlit_echarts import st_echarts # Streamlit ECharts
from streamlit_option_menu import option_menu # Streamlit Option Menu
from db_utils import (
    TZ,
    STATUS_MAPPING,
    get_db_connection, get_feedback_connection, get_tunbroyting_connection, get_stroing_connection,
    execute_query, fetch_data, update_database_schema, hide_feedback, create_all_tables,
    delete_feedback, lagre_bestilling, rediger_bestilling, log_login, update_login_history_table, 
    update_stroing_status, slett_bestilling, get_alerts, log_failed_attempt, oppdater_bestilling_i_database,
    save_alert, update_alert_status, delete_alert, hent_tunbroyting_bestillinger, count_bestillinger,
    hent_stroing_bestillinger, hent_bruker_stroing_bestillinger, lagre_stroing_bestilling,
    send_credentials_email, load_customer_database, get_feedback, check_session_timeout,
    check_cabin_user_consistency, validate_customers_and_passwords, authenticate_user,
    get_customer_by_id, get_date_range, get_weather_data_for_period, fetch_gps_data, get_status_display,
    is_active_booking, get_max_bestilling_id, initialize_database, hent_bruker_bestillinger,
    slett_stroing_bestilling, update_stroing_bestillinger_table, verify_stroing_data, count_stroing_bestillinger,
    initialize_database, hent_dagens_bestillinger, hent_aktive_bestillinger, hent_bestillinger, hent_bestilling,
    filter_tunbroyting_bestillinger
)# Database utilities
from map_utils import vis_tunkart, vis_stroingskart
from cryptography.fernet import Fernet

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
LOCKOUT_PERIOD = timedelta(minutes=15)
SESSION_TIMEOUT = 3600  # 1 time

failed_attempts = {}

# Globale variabler og konstanter for værdata 
icons = {
    "Glatt vei": "🧊",
    "Slush": "⚠️",
    "Gjenblåst vei": "💨",
    "Annet": "❓"
}

STATUS_COLORS = {
    'Ny': '#FF4136',
    'Under behandling': '#FF851B',
    'Løst': '#2ECC40',
    'Lukket': '#AAAAAA',
    'default': '#CCCCCC'
} 

icons = {
    'Føreforhold': '🚗',
    'Parkering': '🅿️',
    'Fasilitet': '🏠',
    'Annet': '❓'
}

# Hjelpefunksjoner som ikke er direkte relatert til databaseoperasjoner
def check_rate_limit(code):
    now = datetime.now()
    if code in failed_attempts:
        attempts, last_attempt = failed_attempts[code]
        if now - last_attempt < LOCKOUT_PERIOD:
            if attempts >= MAX_ATTEMPTS:
                return False
        else:
            attempts = 0
    else:
        attempts = 0
    
    failed_attempts[code] = (attempts + 1, now)
    return True

def reset_rate_limit(code):
    if code in failed_attempts:
        del failed_attempts[code]
        
def encrypt_data(data):
    f = Fernet(st.secrets["encryption_key"])
    return f.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data):
    f = Fernet(st.secrets["encryption_key"])
    return f.decrypt(encrypted_data.encode()).decode()

def get_cabin_coordinates():
    customer_db = load_customer_database()
    return [
        {
            "cabin_id": row["Id"],
            "name": row["Name"],
            "latitude": float(row["Latitude"]) if pd.notnull(row["Latitude"]) else None,
            "longitude": float(row["Longitude"]) if pd.notnull(row["Longitude"]) else None,
            "subscription": row["Subscription"]
        }
        for _, row in customer_db.iterrows()
        if pd.notnull(row["Latitude"]) and pd.notnull(row["Longitude"])
    ]

# Funksjoner relatert til værdatainnhenting og -prosessering:
def fetch_and_process_data(client_id, date_start, date_end):
    try:
        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start}/{date_end}"
        }
        response = requests.get(API_URL, params=params, auth=(client_id, ""))
        response.raise_for_status()  # Dette vil reise en HTTPError for dårlige statuskoder
        data = response.json()

        if not data or not data.get('data'):
            raise ValueError("Ingen data returnert fra API-et")

        df = pd.DataFrame([
            {
                'timestamp': datetime.fromisoformat(item['referenceTime'].rstrip('Z')),
                'air_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'air_temperature'), np.nan),
                'precipitation_amount': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'sum(precipitation_amount PT1H)'), np.nan),
                'surface_snow_thickness': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_snow_thickness'), np.nan),
                'wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'wind_speed'), np.nan),
                'max_wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'max(wind_speed_of_gust PT1H)'), np.nan),
                'min_wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'min(wind_speed P1M)'), np.nan),
                'wind_from_direction': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'max_wind_speed(wind_from_direction PT1H)'), np.nan),
                'surface_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_temperature'), np.nan),
                'relative_humidity': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'relative_humidity'), np.nan),
                'dew_point_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'dew_point_temperature'), np.nan)
            }
            for item in data['data']
        ]).set_index('timestamp')

        if df.empty:
            raise ValueError("Ingen data kunne konverteres til DataFrame")

        df.index = pd.to_datetime(df.index).tz_localize(TZ, nonexistent='shift_forward', ambiguous='NaT')

        processed_data = {}
        for column in df.columns:
            processed_data[column] = pd.to_numeric(df[column], errors='coerce')
            processed_data[column] = validate_data(processed_data[column])
            processed_data[column] = handle_missing_data(df.index, processed_data[column], method='time')

        processed_df = pd.DataFrame(processed_data, index=df.index)
        processed_df['snow_precipitation'] = calculate_snow_precipitations(
            processed_df['air_temperature'].values,
            processed_df['precipitation_amount'].values,
            processed_df['surface_snow_thickness'].values
        )

        processed_df = calculate_snow_drift_alarms(processed_df)
        processed_df = calculate_slippery_road_alarms(processed_df)
        
        smoothed_data = {}
        for column in processed_df.columns:
            if column not in ['snow_drift_alarm', 'slippery_road_alarm', 'snow_precipitation']:
                smoothed_data[column] = smooth_data(processed_df[column].values)
            else:
                smoothed_data[column] = processed_df[column]
        
        smoothed_df = pd.DataFrame(smoothed_data, index=processed_df.index)
        smoothed_df['wind_direction_category'] = smoothed_df['wind_from_direction'].apply(categorize_direction)

        return {'df': smoothed_df}

    except requests.RequestException as e:
        error_message = f"Nettverksfeil ved henting av data: {str(e)}"
        if isinstance(e, requests.ConnectionError):
            error_message = "Kunne ikke koble til værdata-serveren. Sjekk internettforbindelsen din."
        elif isinstance(e, requests.Timeout):
            error_message = "Forespørselen tok for lang tid. Prøv igjen senere."
        elif isinstance(e, requests.HTTPError):
            if e.response.status_code == 401:
                error_message = "Ugyldig API-nøkkel. Kontakt systemadministrator."
            elif e.response.status_code == 404:
                error_message = "Værdata-ressursen ble ikke funnet. Sjekk stasjonsnummeret."
            else:
                error_message = f"HTTP-feil {e.response.status_code}: {e.response.reason}"
        logger.error(error_message)
        return {'error': error_message}

    except ValueError as e:
        error_message = f"Feil i databehandling: {str(e)}"
        logger.error(error_message)
        return {'error': error_message}

    except Exception as e:
        error_message = f"Uventet feil ved datahenting eller -behandling: {str(e)}"
        logger.error(error_message, exc_info=True)
        return {'error': error_message}

def calculate_snow_drift_alarms(df):
    df['snow_depth_change'] = df['surface_snow_thickness'].diff()
    conditions = [
        df['wind_speed'] > 6,
        df['air_temperature'] <= -1,
        ((df['precipitation_amount'] <= 0.1) & (df['surface_snow_thickness'].diff().fillna(0).abs() >= 1)) | 
        ((df['precipitation_amount'] > 0.1) & (df['surface_snow_thickness'].diff().fillna(0) <= -0.5))
    ]
    df['snow_drift_alarm'] = (conditions[0] & conditions[1] & conditions[2]).astype(int)
    return df

def calculate_slippery_road_alarms(df):
    conditions = [
        df['air_temperature'] > 0,
        df['precipitation_amount'] > 1.5,
        df['surface_snow_thickness'] >= 20,
        df['surface_snow_thickness'].diff().fillna(0) < 0
    ]
    df['slippery_road_alarm'] = np.all(conditions, axis=0).astype(int)
    return df

def calculate_snow_precipitations(temperatures, precipitations, snow_depths):
    snow_precipitations = np.zeros_like(temperatures)
    for i in range(len(temperatures)):
        if temperatures[i] is not None and not np.isnan(temperatures[i]):
            condition1 = temperatures[i] <= 1.5 and i > 0 and not np.isnan(snow_depths[i]) and not np.isnan(snow_depths[i-1]) and snow_depths[i] > snow_depths[i-1]
            condition2 = temperatures[i] <= 0 and not np.isnan(precipitations[i]) and precipitations[i] > 0
            if condition1 or condition2:
                snow_precipitations[i] = precipitations[i] if not np.isnan(precipitations[i]) else 0
    return snow_precipitations

# Funksjoner for å vise data og grensesnitt
def display_weather_data():
    st.title("Værdata for Gullingen")
    
    # Vis aktive varsler øverst
    display_active_alerts()

    period_options = [
        "Siste 24 timer", "Siste 7 dager", "Siste 12 timer", "Siste 4 timer", 
        "Siden sist fredag", "Siden sist søndag", "Egendefinert periode", 
        "Siste GPS-aktivitet til nå"
    ]

    period = st.selectbox("Velg en periode:", options=period_options)

    client_id = st.secrets["api_keys"]["client_id"]

    start_date, end_date = get_date_range(period)
    
    if start_date is None or end_date is None:
        st.error(f"Kunne ikke hente datoområde for perioden: {period}")
        return

    st.write(f"Henter data fra {start_date.isoformat()} til {end_date.isoformat()}")

    try:
        with st.spinner('Henter og behandler data...'):
            weather_data = get_weather_data_for_period(client_id, start_date.isoformat(), end_date.isoformat())
            
        if weather_data and 'df' in weather_data:
            df = weather_data['df']
            
            # Create and display the main graph
            fig = create_improved_graph(df)
            st.plotly_chart(fig, use_container_width=True)
            st.subheader("Andre værdata")
            # Display additional data without creating separate graphs
            display_additional_data(df)
            
            # Add weather statistics table
            display_weather_statistics(df)
            
            # Display GPS data
            display_gps_data(start_date, end_date)
        elif weather_data and 'error' in weather_data:
            st.error(f"Feil ved henting av værdata: {weather_data['error']}")
        else:
            st.error("Kunne ikke hente værdata. Vennligst sjekk loggene for mer informasjon.")

    except Exception as e:
        st.error(f"Uventet feil ved visning av værdata: {str(e)}")
        logger.error(f"Uventet feil i display_weather_data: {str(e)}", exc_info=True)

def create_improved_graph(df):
    fig = make_subplots(rows=6, cols=1, 
                        shared_xaxes=True, 
                        vertical_spacing=0.05,
                        subplot_titles=("Lufttemperatur", "Nedbør", "Antatt snønedbør", "Snødybde", "Vind", "Alarmer"))

    trace_data = {
        "Lufttemperatur": {"data": df['air_temperature'], "color": 'darkred', "type": 'scatter', "row": 1, "units": "°C"},
        "Nedbør": {"data": df['precipitation_amount'], "color": 'blue', "type": 'bar', "row": 2, "units": "mm"},
        "Antatt snønedbør": {"data": df['snow_precipitation'], "color": 'lightblue', "type": 'bar', "row": 3, "units": "mm"},
        "Snødybde": {"data": df['surface_snow_thickness'], "color": 'cyan', "type": 'scatter', "row": 4, "units": "cm"},
        "Vindhastighet": {"data": df['wind_speed'], "color": 'green', "type": 'scatter', "row": 5, "units": "m/s"},
        "Maks vindhastighet": {"data": df['max_wind_speed'], "color": 'darkgreen', "type": 'scatter', "row": 5, "units": "m/s"}
    }

    for title, data in trace_data.items():
        if data["type"] == 'scatter':
            fig.add_trace(go.Scatter(
                x=df.index, y=data["data"], name=title,
                line=dict(color=data["color"]),
                hovertemplate=f'%{{y:.1f}} {data["units"]}<br>%{{x}}',
            ), row=data["row"], col=1)
        elif data["type"] == 'bar':
            fig.add_trace(go.Bar(
                x=df.index, y=data["data"], name=title,
                marker_color=data["color"],
                hovertemplate=f'%{{y:.1f}} {data["units"]}<br>%{{x}}',
            ), row=data["row"], col=1)

    # Add freezing point reference line for temperature
    fig.add_hline(y=0, line_dash="dash", line_color="blue", row=1, col=1)

    # Add alarm traces
    snow_drift_alarms = df[df['snow_drift_alarm'] == 1]
    slippery_road_alarms = df[df['slippery_road_alarm'] == 1]

    fig.add_trace(go.Scatter(
        x=snow_drift_alarms.index, y=[1]*len(snow_drift_alarms),
        mode='markers', name='Snøfokk-alarm',
        marker=dict(symbol='star', size=12, color='blue'),
        hovertemplate='Snøfokk-alarm<br>%{x}',
    ), row=6, col=1)

    fig.add_trace(go.Scatter(
        x=slippery_road_alarms.index, y=[0.5]*len(slippery_road_alarms),
        mode='markers', name='Glatt vei-alarm',
        marker=dict(symbol='triangle-up', size=12, color='red'),
        hovertemplate='Glatt vei-alarm<br>%{x}',
    ), row=6, col=1)

    # Update layout
    fig.update_layout(
        height=1400, 
        title_text="Værdataoversikt",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # Update x and y axes
    for i in range(1, 7):
        fig.update_xaxes(
            title_text="Dato" if i == 6 else "",
            type='date',
            tickformat='%Y-%m-%d %H:%M',
            dtick='H2',
            row=i, col=1
        )
        if i < 6:  # Skip the last row (alarms)
            title = list(trace_data.keys())[i-1]
            units = trace_data[title]["units"]
            fig.update_yaxes(title_text=f"{title} ({units})", row=i, col=1)

    # Special case for the alarms row
    fig.update_yaxes(title_text="Alarmer", row=6, col=1, tickmode='array', tickvals=[0, 0.5, 1], ticktext=['', 'Glatt vei', 'Snøfokk'])

    # Ensure each subplot uses its own y-axis
    for i in range(1, 7):
        fig.update_yaxes(matches=None, row=i, col=1)

    # Add annotations for extreme values
    max_temp_idx = df['air_temperature'].idxmax()
    min_temp_idx = df['air_temperature'].idxmin()
    max_wind_idx = df['max_wind_speed'].idxmax()

    fig.add_annotation(x=max_temp_idx, y=df.loc[max_temp_idx, 'air_temperature'],
                       text=f"Max: {df.loc[max_temp_idx, 'air_temperature']:.1f}°C",
                       showarrow=True, arrowhead=2, row=1, col=1)
    fig.add_annotation(x=min_temp_idx, y=df.loc[min_temp_idx, 'air_temperature'],
                       text=f"Min: {df.loc[min_temp_idx, 'air_temperature']:.1f}°C",
                       showarrow=True, arrowhead=2, row=1, col=1)
    fig.add_annotation(x=max_wind_idx, y=df.loc[max_wind_idx, 'max_wind_speed'],
                       text=f"Max: {df.loc[max_wind_idx, 'max_wind_speed']:.1f} m/s",
                       showarrow=True, arrowhead=2, row=5, col=1)

    return fig
     
def display_additional_data(df):
    with st.expander("Overflatetemperatur - på bakken"):
        st.line_chart(df['surface_temperature'])
        st.write(f"Gjennomsnitt: {df['surface_temperature'].mean():.1f}°C")
        st.write(f"Minimum: {df['surface_temperature'].min():.1f}°C")
        st.write(f"Maksimum: {df['surface_temperature'].max():.1f}°C")

    with st.expander("Relativ luftfuktighet - Høy luftfuktighet i kombinasjon med lave temperaturer øker risikoen for ising"):
        st.line_chart(df['relative_humidity'])
        st.write(f"Gjennomsnitt: {df['relative_humidity'].mean():.1f}%")
        st.write(f"Minimum: {df['relative_humidity'].min():.1f}%")
        st.write(f"Maksimum: {df['relative_humidity'].max():.1f}%")

    with st.expander("Duggpunkt - Temperaturen hvor luften blir mettet og dugg eller frost kan dannes"):
        st.line_chart(df['dew_point_temperature'])
        st.write(f"Gjennomsnitt: {df['dew_point_temperature'].mean():.1f}°C")
        st.write(f"Minimum: {df['dew_point_temperature'].min():.1f}°C")
        st.write(f"Maksimum: {df['dew_point_temperature'].max():.1f}°C")

    display_wind_data(df)
    display_alarms(df)

def display_wind_data(df):
    with st.expander("Detaljert vinddata"):
        st.subheader("Vindhastighetsprofil")
        wind_fig = go.Figure()
        wind_fig.add_trace(go.Scatter(x=df.index, y=df['wind_speed'], mode='lines', name='Gjennomsnittlig vindhastighet'))
        wind_fig.add_trace(go.Scatter(x=df.index, y=df['max_wind_speed'], mode='lines', name='Maks vindhastighet'))
        wind_fig.update_layout(title='Vindhastighetsprofil over tid', xaxis_title='Tid', yaxis_title='Vindhastighet (m/s)')
        st.plotly_chart(wind_fig)
        
        st.subheader("Vindretningsfordeling")
        wind_direction_counts = df['wind_direction_category'].value_counts()
        directions = ['N', 'NØ', 'Ø', 'SØ', 'S', 'SV', 'V', 'NV']
        values = [wind_direction_counts.get(d, 0) for d in directions]
        
        wind_direction_fig = go.Figure(data=[go.Barpolar(
            r=values,
            theta=directions,
            marker_color='rgb(106,81,163)'
        )])
        wind_direction_fig.update_layout(
            title='Fordeling av vindretninger',
            polar=dict(
                radialaxis=dict(visible=True, range=[0, max(values)]),
                angularaxis=dict(direction="clockwise")
            )
        )
        st.plotly_chart(wind_direction_fig)

def display_alarms(df):
    with st.expander("Snøfokk-alarmer"):
        st.write("Alarmene er basert på værdata og ikke direkte observasjoner")
        st.write("Kriterier: Vind > 6 m/s, temperatur ≤ -1°C, og enten:")
        st.write("1) nedbør ≤ 0.1 mm og endring i snødybde ≥ 1.0 cm, eller")
        st.write("2) nedbør > 0.1 mm og minking i snødybde ≥ 0.5 cm")
        snow_drift_alarms = df[df['snow_drift_alarm'] == 1]
        if not snow_drift_alarms.empty:
            st.dataframe(snow_drift_alarms[['air_temperature', 'wind_speed', 'surface_snow_thickness', 'precipitation_amount', 'snow_depth_change']])
            st.write(f"Totalt antall snøfokk-alarmer: {len(snow_drift_alarms)}")
        else:
            st.write("Ingen snøfokk-alarmer i den valgte perioden.")

    with st.expander("Glatt vei / slush-alarmer"):
        st.write("Alarmene er basert på værdata og ikke direkte observasjoner.")
        st.write("Kriterier: Temperatur > 0°C, nedbør > 1.5 mm, snødybde ≥ 20 cm, og synkende snødybde.")
        slippery_road_alarms = df[df['slippery_road_alarm'] == 1]
        if not slippery_road_alarms.empty:
            st.dataframe(slippery_road_alarms[['air_temperature', 'precipitation_amount', 'surface_snow_thickness']])
            st.write(f"Totalt antall glatt vei / slush-alarmer: {len(slippery_road_alarms)}")
        else:
            st.write("Ingen glatt vei / slush-alarmer i den valgte perioden.")

def display_gps_data(start_date, end_date):
    gps_data = fetch_gps_data()
    with st.expander("Siste GPS aktivitet"):
        if gps_data:
            gps_df = pd.DataFrame(gps_data)
            st.dataframe(gps_df)
        else:
            st.write("Ingen GPS-aktivitet i den valgte perioden.")
    
def display_weather_statistics(df):
    st.subheader("Værstatistikk for valgt periode")
    
    # Calculate statistics
    stats = pd.DataFrame({
        'Statistikk': ['Gjennomsnitt', 'Median', 'Minimum', 'Maksimum', 'Sum'],
        'Lufttemperatur (°C)': [
            f"{df['air_temperature'].mean():.1f}",
            f"{df['air_temperature'].median():.1f}",
            f"{df['air_temperature'].min():.1f}",
            f"{df['air_temperature'].max():.1f}",
            'N/A'
        ],
        'Nedbør (mm)': [
            f"{df['precipitation_amount'].mean():.1f}",
            f"{df['precipitation_amount'].median():.1f}",
            f"{df['precipitation_amount'].min():.1f}",
            f"{df['precipitation_amount'].max():.1f}",
            f"{df['precipitation_amount'].sum():.1f}"
        ],
        'Antatt snønedbør (mm)': [
            f"{df['snow_precipitation'].mean():.1f}",
            f"{df['snow_precipitation'].median():.1f}",
            f"{df['snow_precipitation'].min():.1f}",
            f"{df['snow_precipitation'].max():.1f}",
            f"{df['snow_precipitation'].sum():.1f}"
        ],
        'Snødybde (cm)': [
            f"{df['surface_snow_thickness'].mean():.1f}",
            f"{df['surface_snow_thickness'].median():.1f}",
            f"{df['surface_snow_thickness'].min():.1f}",
            f"{df['surface_snow_thickness'].max():.1f}",
            'N/A'
        ],
        'Vindhastighet (m/s)': [
            f"{df['wind_speed'].mean():.1f}",
            f"{df['wind_speed'].median():.1f}",
            f"{df['wind_speed'].min():.1f}",
            f"{df['wind_speed'].max():.1f}",
            'N/A'
        ],
        'Maks vindhastighet (m/s)': [
            f"{df['max_wind_speed'].mean():.1f}",
            f"{df['max_wind_speed'].median():.1f}",
            f"{df['max_wind_speed'].min():.1f}",
            f"{df['max_wind_speed'].max():.1f}",
            'N/A'
        ]
    })
    
    # Display the table
    st.table(stats)

def bestill_tunbroyting():
    st.title("Bestill Tunbrøyting")

    customer = get_customer_by_id(st.session_state.username)
    if customer is None:
        st.error("Kunne ikke hente brukerinformasjon. Vennligst logg inn på nytt.")
        return

    user_id = customer['Id']  # Bruk 'Id' i stedet for 'Name'
    user_subscription = customer['Subscription']

    if user_subscription not in ["star_white", "star_red"]:
        st.warning("Du har ikke et aktivt tunbrøytingsabonnement og kan derfor ikke bestille tunbrøyting.")
        return


    naa = datetime.now(TZ)
    tomorrow = naa.date() + timedelta(days=1)

    abonnement_type = "Årsabonnement" if user_subscription == "star_white" else "Ukentlig ved bestilling"
    st.write(f"Ditt abonnement: {abonnement_type}")

    col1, col2 = st.columns(2)
    
    with col1:
        if abonnement_type == "Ukentlig ved bestilling":
            ankomst_dato = neste_fredag()
            st.write(f"Ankomstdato (neste fredag): {ankomst_dato}")
        else:  # Årsabonnement
            ankomst_dato = st.date_input("Velg ankomstdato", min_value=tomorrow, value=tomorrow)
        
    with col2:
        ankomst_tid = st.time_input("Velg ankomsttid")

    avreise_dato = None
    avreise_tid = None
    
    if abonnement_type == "Årsabonnement":
        col3, col4 = st.columns(2)
        with col3:
            avreise_dato = st.date_input("Velg avreisetato", min_value=ankomst_dato, value=ankomst_dato + timedelta(days=1))
        with col4:
            avreise_tid = st.time_input("Velg avreisetid")

    bestillingsfrist = datetime.combine(ankomst_dato - timedelta(days=1), time(12, 0)).replace(tzinfo=TZ)

    if st.button("Bestill Tunbrøyting"):
        if naa >= bestillingsfrist:
            st.error(f"Beklager, fristen for å bestille tunbrøyting for {ankomst_dato.strftime('%d.%m.%Y')} var {bestillingsfrist.strftime('%d.%m.%Y kl. %H:%M')}. Vennligst velg en senere dato.")
        else:
            if lagre_bestilling(
                user_id,  # Bruk user_id i stedet for customer['Id']
                ankomst_dato.isoformat(), 
                ankomst_tid.isoformat(),
                avreise_dato.isoformat() if avreise_dato else None,
                avreise_tid.isoformat() if avreise_tid else None,
                abonnement_type
            ):
                st.success("Bestilling av tunbrøyting er registrert!")
            else:
                st.error("Det oppstod en feil ved lagring av bestillingen. Vennligst prøv igjen senere.")

    st.info(f"Merk: Frist for bestilling er kl. 12:00 dagen før ønsket ankomstdato. For valgt dato ({ankomst_dato.strftime('%d.%m.%Y')}) er fristen {bestillingsfrist.strftime('%d.%m.%Y kl. %H:%M')}.")

    st.subheader("Dine tidligere bestillinger")
    display_bookings(st.session_state.username)
    
def bestill_stroing():
    st.title("Bestill Strøing")

    # Informasjonstekst
    st.info("""
    Strøing av stikkveier i Fjellbergsskardet Hyttegrend - Sesong 2024/2025

    - Hovedstrekningen Gullingvegen-Tjernet er alltid prioritert
    - Stikkveier strøs på bestilling og faktureres egenandel for sesongen + per bestilling
    - Bindende bestilling hvis brøytekontakten godkjenner strøing
    - Brøytekontakten vurderer værforhold og effektivitet før strøing utføres
    
    Tips ved glatte forhold:
    - Bruk piggdekk/kjetting
    - Ha med strøsand, spade og tau. Bruk strøsandkassene
    - Brodder til beina
    """)

    # Radioknapper for bestillingstype
    bestilling_type = st.radio(
        "Velg bestillingstype:",
        ("Stikkvei kommende helg", "Mandag-fredag")
    )

    if bestilling_type == "Stikkvei kommende helg":
        # Beregn neste helg
        today = datetime.now(TZ).date()
        days_until_weekend = (5 - today.weekday()) % 7
        next_saturday = today + timedelta(days=days_until_weekend)
        next_sunday = next_saturday + timedelta(days=1)
        
        st.write(f"Bestilling for helgen {next_saturday.strftime('%d.%m.%Y')} - {next_sunday.strftime('%d.%m.%Y')}")
        
        # Sjekk om fristen har gått ut
        if today.weekday() >= 3 and datetime.now(TZ).hour >= 12:
            st.warning("Fristen for bestilling denne helgen har gått ut (torsdag kl. 12:00).")
        else:
            st.success("Du kan bestille strøing for kommende helg.")
        
        onske_dato = next_saturday
    else:  # Mandag-fredag
        available_dates = [datetime.now(TZ).date() + timedelta(days=i) for i in range(4)]
        onske_dato = st.selectbox("Velg dato for strøing:", available_dates, format_func=lambda x: x.strftime('%d.%m.%Y'))
        
        if onske_dato == datetime.now(TZ).date():
            st.info("Du har valgt strøing for i dag. Merk at dette er med forbehold om godkjenning fra brøytekontakten.")

    if st.button("Bestill Strøing"):
        if lagre_stroing_bestilling(st.session_state.username, onske_dato.isoformat()):
            st.success("Bestilling av strøing er registrert!")
        else:
            st.error("Det oppstod en feil ved registrering av bestillingen. Vennligst prøv igjen senere.")
        
        st.info("Merk: Du vil bli fakturert kun hvis strøing utføres.")

    st.subheader("Dine tidligere strøing-bestillinger")
    display_stroing_bookings(st.session_state.username)

def vis_daglige_broytinger(bestillinger):
    if bestillinger.empty:
        st.write("Ingen data tilgjengelig for å vise daglige brøytinger.")
        return

    # Konverter 'ankomst_dato' til datetime hvis det ikke allerede er det
    bestillinger['ankomst_dato'] = pd.to_datetime(bestillinger['ankomst_dato'])

    # Grupper bestillinger per dag
    daglige_broytinger = bestillinger.groupby(bestillinger['ankomst_dato'].dt.date).size().reset_index(name='antall')

    # Opprett en linjegraf
    fig = px.line(daglige_broytinger, x='ankomst_dato', y='antall', 
                  title='Daglige brøytinger',
                  labels={'ankomst_dato': 'Dato', 'antall': 'Antall brøytinger'})

    # Legg til punkter på linjen
    fig.add_trace(go.Scatter(x=daglige_broytinger['ankomst_dato'], y=daglige_broytinger['antall'],
                             mode='markers', name='Daglige punkter'))

    # Oppdater layout for bedre lesbarhet
    fig.update_layout(hovermode="x unified")
    fig.update_traces(hovertemplate="Dato: %{x}<br>Antall brøytinger: %{y}")

    # Vis grafen
    st.plotly_chart(fig)

    # Vis også dataene i en tabell
    # st.write("Daglige brøytinger:")
    # st.dataframe(daglige_broytinger)

def vis_tunbroyting_oversikt():
    st.title("Oversikt over tunbrøytingsbestillinger")
    
    bestillinger = hent_bestillinger()
    
    if bestillinger.empty:
        st.write("Ingen bestillinger å vise.")
        return

    current_date = datetime.now(TZ).date()

    # Filtreringsmuligheter
    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("Fra dato", value=current_date)
    with col2:
        end_date = st.date_input("Til dato", value=current_date + timedelta(days=7))
    with col3:
        abonnement_type = st.multiselect("Abonnement type", options=bestillinger['abonnement_type'].unique())

    # Filtrer bestillinger basert på dato og abonnement type
    filtered_bestillinger = bestillinger[
        (bestillinger['ankomst_dato'].dt.date >= start_date) & 
        (bestillinger['ankomst_dato'].dt.date <= end_date)
    ]

    if abonnement_type:
        filtered_bestillinger = filtered_bestillinger[filtered_bestillinger['abonnement_type'].isin(abonnement_type)]

    # Vis kart for dagens bestillinger
    st.subheader("Dagens bestillinger")
    dagens_bestillinger = filtered_bestillinger[filtered_bestillinger['ankomst_dato'].dt.date == current_date]
    st.write(f"Antall bestillinger for i dag: {len(dagens_bestillinger)}")
    fig_today, _ = vis_tunkart(dagens_bestillinger, 
                            st.secrets["mapbox"]["access_token"],
                            "Kart over dagens tunbrøytingsbestillinger", 
                            vis_type='today')
    st.plotly_chart(fig_today, use_container_width=True)

    # Forklaring for dagens bestillinger
    st.write("Forklaring:")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.color_picker("Aktiv bestilling", "#FF0000", disabled=True)
        st.write("Aktiv bestilling")
    with col2:
        st.color_picker("Årsabonnement", "#0000FF", disabled=True)
        st.write("Årsabonnement")
    with col3:
        st.color_picker("Ingen aktiv bestilling", "#CCCCCC", disabled=True)
        st.write("Ingen aktiv bestilling")

    # Vis kart for aktive bestillinger
    st.subheader("Aktive bestillinger de neste syv dagene")
    aktive_bestillinger = filtered_bestillinger[
        (filtered_bestillinger['ankomst_dato'].dt.date >= current_date) & 
        (filtered_bestillinger['ankomst_dato'].dt.date <= current_date + timedelta(days=7))
    ]
    st.write(f"Antall aktive bestillinger: {len(aktive_bestillinger)}")
    fig_active, color_scale = vis_tunkart(aktive_bestillinger, 
                             st.secrets["mapbox"]["access_token"],
                             "Kart over aktive tunbrøytingsbestillinger de neste syv dagene", 
                             vis_type='active')
    st.plotly_chart(fig_active, use_container_width=True)

    # Forklaring for aktive bestillinger
    st.write("Forklaring:")
    cols = st.columns(7)
    for i, col in enumerate(cols):
        with col:
            if i < 6:
                st.color_picker(f"Dag {i+1}", color_scale[i], disabled=True)
                st.write(f"Dag {i+1}")
            else:
                st.color_picker("Inaktiv", "#CCCCCC", disabled=True)
                st.write("Inaktiv")

    # Vis statistikk
    st.subheader("Bestillingsstatistikk")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Filtrerte bestillinger", len(filtered_bestillinger))
    with col2:
        st.metric("Totalt antall bestillinger", len(bestillinger))

    # Vis filtrerte og sorterte bestillinger i en kollapsbar seksjon
    with st.expander("Bestillinger for valgt periode", expanded=False):
        st.dataframe(filtered_bestillinger)

    # Vis graf over daglige brøytinger
    st.subheader("Oversikt over daglige brøytinger")
    vis_daglige_broytinger(filtered_bestillinger)

def give_feedback():
    st.title("Gi feedback")
    
    st.info("Her kan du gi tilbakemeldinger, melde avvik eller komme med forslag til forbedringer. Velg type feedback fra menyen nedenfor.")

    feedback_type = st.radio(
        "Velg type feedback:",
        ["Avvik", "Generell tilbakemelding", "Forslag til forbedring", "Annet"],
    )

    st.write("---")

    avvik_tidspunkt = None
    if feedback_type == "Avvik":
        st.subheader("Rapporter et avvik")
        deviation_type = st.selectbox(
            "Velg type avvik:",
            [
                "Glemt tunbrøyting",
                "Dårlig framkommelighet",
                "For sen brøytestart",
                "Manglende brøyting av fellesparkeringsplasser",
                "Manglende strøing",
                "Uønsket snødeponering",
                "Manglende rydding av snøfenner",
                "For høy hastighet under brøyting",
                "Skader på eiendom under brøyting",
                "Annet"
            ]
        )
        
        # Legg til dato- og tidsvelger for avviket
        col1, col2 = st.columns(2)
        with col1:
            avvik_dato = st.date_input("Dato for avviket", value=datetime.now(TZ).date())
        with col2:
            avvik_tid = st.time_input("Tidspunkt for avviket", value=datetime.now(TZ).time())
        
        avvik_tidspunkt = datetime.combine(avvik_dato, avvik_tid).replace(tzinfo=TZ)
        
        feedback_type = f"Avvik: {deviation_type}"
    elif feedback_type == "Generell tilbakemelding":
        st.subheader("Gi en generell tilbakemelding")
    elif feedback_type == "Forslag til forbedring":
        st.subheader("Kom med et forslag til forbedring")
    else:  # Annet
        st.subheader("Annen type feedback")

    description = st.text_area("Beskriv din feedback i detalj:", height=150)
    
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        submit_button = st.button("Send inn feedback", use_container_width=True)

    if submit_button:
        if description:
            cabin_identifier = st.session_state.get('username')
            
            st.write(f"Debug: Forsøker å lagre feedback av type {feedback_type}")
            st.write(f"Debug: Beskrivelse: {description}")
            st.write(f"Debug: Hytte ID: {cabin_identifier}")
            
            if cabin_identifier:
                # Legg til tidspunkt i beskrivelsen for avvik
                if avvik_tidspunkt:
                    description = f"Tidspunkt for avvik: {avvik_tidspunkt.strftime('%Y-%m-%d %H:%M')}\n\n" + description
                
                feedback_datetime = avvik_tidspunkt if avvik_tidspunkt else datetime.now(TZ)
                
                result = save_feedback(feedback_type, feedback_datetime.isoformat(), description, cabin_identifier, hidden=False)
                
                st.write(f"Debug: Resultat av save_feedback: {result}")
                
                if result:
                    st.success("Feedback sendt inn. Takk for din tilbakemelding!")
                else:
                    st.error("Det oppstod en feil ved innsending av feedback. Vennligst prøv igjen senere.")
            else:
                st.error("Kunne ikke identifisere hytten. Vennligst logg inn på nytt.")
        else:
            st.warning("Vennligst skriv en beskrivelse før du sender inn.")

    st.write("---")

    # Vis eksisterende feedback for denne hytten
    st.subheader("Din tidligere feedback")
    cabin_identifier = st.session_state.get('username')
    if cabin_identifier:
        existing_feedback = get_feedback(start_date=None, end_date=None, include_hidden=False, cabin_identifier=cabin_identifier)
        if existing_feedback.empty:
            st.info("Du har ingen tidligere feedback å vise.")
        else:
            for _, feedback in existing_feedback.iterrows():
                with st.expander(f"{feedback['type']} - {feedback['datetime']}"):
                    st.write(f"Beskrivelse: {feedback['comment']}")
                    st.write(f"Status: {feedback['status']}")
    else:
        st.warning("Kunne ikke hente tidligere feedback. Vennligst logg inn på nytt.")

def display_active_alerts():
    alerts = get_alerts(include_expired=False)
    
    if not alerts.empty:
        # st.warning("Aktive varsler:")
        for _, alert in alerts.iterrows():
            alert_date = pd.to_datetime(alert['datetime']).strftime('%d.%m.%Y %H:%M')
            st.info(f"{alert['type']} - {alert_date}: {alert['comment']}")
    
    st.write("---")

# Administrasjonsfunksjoner 

def admin_broytefirma_page():
    st.title("Administrer feedback, tunbrøyting og strøing")

    if st.session_state.username in ["Fjbs Drift"]:
        admin_menu()
    else:
        st.error("Du har ikke tilgang til denne siden")

def admin_stroing_page():
    st.title("Administrer Strøing-bestillinger")

    # Dato-range velger
    today = datetime.now(TZ).date()
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=today, min_value=today)
    with col2:
        end_date = st.date_input("Til dato", value=today + timedelta(days=30), min_value=start_date)

    # Hent alle strøingsbestillinger
    bestillinger = hent_stroing_bestillinger()

    # Konverter dato-kolonner til datetime
    for col in ['bestillings_dato', 'onske_dato']:
        if col in bestillinger.columns:
            bestillinger[col] = pd.to_datetime(bestillinger[col], utc=True).dt.tz_convert(TZ)

    # Filtrer bestillinger basert på dato-range
    filtered_bestillinger = bestillinger[
        (bestillinger['onske_dato'].dt.date >= start_date) &
        (bestillinger['onske_dato'].dt.date <= end_date)
    ]

    # Vis kart over bestillinger
    st.subheader("Kart over strøingsbestillinger")
    mapbox_token = st.secrets["mapbox"]["access_token"]
    fig = vis_stroingskart(filtered_bestillinger, mapbox_token, "Kart over strøingsbestillinger")
    st.plotly_chart(fig, use_container_width=True)

    # Filtreringsmuligheter
    hytte_id_filter = st.text_input("Filtrer på hytte-ID")

    # Anvend filtre
    if hytte_id_filter:
        filtered_bestillinger = filtered_bestillinger[filtered_bestillinger['bruker'].astype(str).str.contains(hytte_id_filter)]

    # Sortering
    sort_column = st.selectbox("Sorter etter", options=['onske_dato', 'bestillings_dato', 'bruker'])
    sort_order = st.radio("Sorteringsrekkefølge", options=['Stigende', 'Synkende'])
    filtered_bestillinger = filtered_bestillinger.sort_values(by=sort_column, ascending=(sort_order == 'Stigende'))

    # Vis bestillinger
    st.subheader("Strøingsbestillinger")
    for index, row in filtered_bestillinger.iterrows():
        with st.expander(f"Bestilling - Hytte {row['bruker']} - Ønsket dato: {row['onske_dato'].strftime('%Y-%m-%d')}"):
            st.write(f"Bestilt: {row['bestillings_dato'].strftime('%Y-%m-%d %H:%M')}")
            st.write(f"Ønsket dato for strøing: {row['onske_dato'].strftime('%Y-%m-%d')}")
            if st.button("Slett bestilling", key=f"delete_{row['id']}"):
                if slett_stroing_bestilling(row['id']):
                    st.success(f"Bestilling for Hytte {row['bruker']} er slettet")
                    st.rerun()
                else:
                    st.error(f"Feil ved sletting av bestilling for Hytte {row['bruker']}")

    # Vis antall viste bestillinger
    st.info(f"Viser {len(filtered_bestillinger)} av totalt {len(bestillinger)} bestillinger")

    # Legg til mulighet for å laste ned bestillingene som CSV
    if not filtered_bestillinger.empty:
        csv = filtered_bestillinger.to_csv(index=False)
        st.download_button(
            label="Last ned som CSV",
            data=csv,
            file_name="stroingsbestillinger.csv",
            mime="text/csv",
        )

def admin_alert():
    st.title("Administrer varsler")
    
    st.info("Dette er en administratorfunksjon for å sende og administrere offisielle varsler.")

    # Vis eksisterende varsler
    st.subheader("Eksisterende aktive varsler")
    alerts = get_alerts(include_expired=False)

    if alerts is None:
        st.error("Kunne ikke hente varsler. Vennligst sjekk get_alerts() funksjonen.")
        return

    if isinstance(alerts, str):
        st.error(f"Uventet returverdi fra get_alerts(): {alerts}")
        return

    if not isinstance(alerts, (list, pd.DataFrame)):
        st.error(f"Uventet datatype returnert fra get_alerts(): {type(alerts)}")
        return

    if isinstance(alerts, list) and len(alerts) == 0:
        st.info("Ingen aktive varsler.")
    elif isinstance(alerts, pd.DataFrame) and alerts.empty:
        st.info("Ingen aktive varsler.")
    else:
        for alert in (alerts if isinstance(alerts, list) else alerts.to_dict('records')):
            try:
                with st.expander(f"{alert['type']} - {alert['datetime']}"):
                    st.write(f"Melding: {alert['comment']}")
                    st.write(f"Utløper: {alert['expiry_date']}")
                    st.write(f"Målgruppe: {alert['target_group']}")
                    
                    # Oppdater status
                    new_status = st.selectbox("Status", ["Aktiv", "Inaktiv"], 
                                              index=0 if alert['status'] == "Aktiv" else 1,
                                              key=f"status_{alert['id']}")
                    if st.button("Oppdater status", key=f"update_{alert['id']}"):
                        if update_alert_status(alert['id'], new_status, st.session_state.username):
                            st.success("Status oppdatert")
                            st.rerun()
                        else:
                            st.error("Feil ved oppdatering av status")
                    
                    # Slett varsel
                    if st.button("Slett varsel", key=f"delete_{alert['id']}"):
                        if delete_alert(alert['id']):
                            st.success("Varsel slettet")
                            st.rerun()
                        else:
                            st.error("Feil ved sletting av varsel")
            except Exception as e:
                st.error(f"Feil ved behandling av varsel: {str(e)}")
                st.json(alert)  # Display the raw alert data for debugging

    # Opprett nytt varsel
    st.subheader("Opprett nytt varsel")
    alert_type = st.selectbox("Type varsel", ["Generelt", "Brøyting", "Strøing", "Vedlikehold", "Annet"])
    message = st.text_area("Skriv varselmelding")
    expiry_date = st.date_input("Utløpsdato for varselet", min_value=datetime.now(TZ).date())
    target_group = st.multiselect("Målgruppe", ["Alle brukere", "Årsabonnenter", "Ukentlige abonnenter", "Ikke-abonnenter"])
    
    if st.button("Send varsel"):
        if message and target_group:
            if save_alert(alert_type, message, expiry_date.isoformat(), target_group, st.session_state.username):
                st.success("Varsel opprettet og lagret.")
                st.rerun()
            else:
                st.error("Det oppstod en feil ved opprettelse av varselet. Vennligst prøv igjen senere.")
        else:
            st.warning("Vennligst fyll ut alle feltene før du sender.")

def show_dashboard(include_hidden=False):
    st.title("Dashbord for administrasjon")

    # Set default date range to last 7 days
    end_date = datetime.now(TZ).date()
    start_date = end_date - timedelta(days=7)

    # Date range selector with default values
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=start_date)
    with col2:
        end_date = st.date_input("Til dato", value=end_date)

    # Konverter datoene til datetime med klokkeslett
    start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
    end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)

    # Fetch data
    feedback_data = get_feedback(start_date=start_datetime.isoformat(), end_date=end_datetime.isoformat(), include_hidden=include_hidden)
    tunbroyting_data = hent_bestillinger()
    stroing_data = hent_stroing_bestillinger()

    if feedback_data.empty:
        st.warning(f"Ingen feedback-data tilgjengelig for perioden {start_date} til {end_date}.")
    else:
        # Forbered data for grafer
        feedback_data['datetime'] = pd.to_datetime(feedback_data['datetime'])
        feedback_data.loc[feedback_data['status'].isnull() | (feedback_data['status'] == 'Innmeldt'), 'status'] = 'Ny'
        feedback_data['date'] = feedback_data['datetime'].dt.date

        # Summary statistics
        st.subheader("Oppsummering")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Totalt antall Feedback", len(feedback_data))
        with col2:
            try:
                today = pd.Timestamp.now(tz=TZ).floor('D')
                tunbroyting_data['ankomst_dato'] = pd.to_datetime(tunbroyting_data['ankomst_dato'], errors='coerce').dt.tz_localize(TZ)
                active_tunbroyting = tunbroyting_data[(tunbroyting_data['ankomst_dato'].notna()) & (tunbroyting_data['ankomst_dato'].dt.date >= today.date())]
                st.metric("Aktive tunbrøytingsbestillinger", len(active_tunbroyting))
            except Exception as e:
                st.error(f"Error calculating active tunbroyting: {str(e)}")
                st.metric("Aktive tunbrøytingsbestillinger", "Error")
        with col3:
            try:
                if 'status' not in stroing_data.columns:
                    #st.warning("'status' kolonne mangler i strøing-data. Viser totalt antall bestillinger.")
                    st.metric("Totale strøingsbestillinger", len(stroing_data))
                else:
                    pending_stroing = stroing_data[stroing_data['status'] == 'Pending']
                    st.metric("Ventende strøingsbestillinger", len(pending_stroing))
            except Exception as e:
                st.error(f"Error calculating pending stroing: {str(e)}")
                st.metric("Ventende strøingsbestillinger", "Error")

        # Vis debug-informasjon for strøing-data
        if st.checkbox("Vis debug-info for strøing-data"):
            st.write("Strøing-data kolonner:")
            st.write(stroing_data.columns)
            st.write("Første få rader av strøing-data:")
            st.write(stroing_data.head())


        # Feedback Oversikt
        st.header("Feedback Oversikt")

        # Opprett to kolonner for grafene
        col1, col2 = st.columns(2)

        with col1:
            # 1. Sektordiagram for feedback-typer
            type_counts = feedback_data['type'].value_counts()
            fig_pie = px.pie(values=type_counts.values, names=type_counts.index, title="Fordeling av feedback-typer")
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            # 2. Stolpediagram for status
            status_counts = feedback_data['status'].value_counts()
            fig_bar = px.bar(x=status_counts.index, y=status_counts.values, 
                             title="Antall feedback per status",
                             labels={'x': 'Status', 'y': 'Antall'},
                             color=status_counts.index,
                             color_discrete_map=STATUS_COLORS)
            st.plotly_chart(fig_bar, use_container_width=True)

        # 3. Tidslinje for feedback over tid (full bredde)
        daily_counts = feedback_data.groupby('date').size().reset_index(name='count')
        fig_line = px.line(daily_counts, x='date', y='count', title="Antall feedback over tid")
        fig_line.update_xaxes(title_text="Dato")
        fig_line.update_yaxes(title_text="Antall feedback")
        st.plotly_chart(fig_line, use_container_width=True)

        # Vis totalt antall feedback-elementer
        st.info(f"Viser {len(feedback_data)} feedback-elementer for perioden {start_date} til {end_date}")

def handle_user_feedback():
    st.subheader("Håndter bruker-feedback")

    # Dato-velgere for periode
    col1, col2 = st.columns(2)
    with col1:
        end_date = st.date_input("Til dato", value=datetime.now(TZ).date())
    with col2:
        start_date = st.date_input("Fra dato", value=end_date - timedelta(days=7))

    # Konverter datoene til datetime med klokkeslett
    start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
    end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)

    # Hent bruker-feedback for den valgte perioden
    feedback_data = get_feedback(start_date=start_datetime.isoformat(), end_date=end_datetime.isoformat(), include_hidden=False)
    
    if feedback_data.empty:
        st.warning(f"Ingen feedback-data tilgjengelig for perioden {start_date} til {end_date}.")
        return

    # Filtrer ut administrative varsler og sett status for fersk feedback
    user_feedback = feedback_data[~feedback_data['type'].str.contains('Admin varsel', na=False)].copy()
    user_feedback.loc[user_feedback['status'].isnull() | (user_feedback['status'] == 'Innmeldt'), 'status'] = 'Ny'

    if user_feedback.empty:
        st.warning(f"Ingen bruker-feedback tilgjengelig for perioden {start_date} til {end_date}.")
        return

    # Sorter etter dato, nyeste først
    user_feedback['datetime'] = pd.to_datetime(user_feedback['datetime'])
    user_feedback = user_feedback.sort_values('datetime', ascending=False)

    # Lag kolonner for filtrering
    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.multiselect("Filtrer på status", options=list(STATUS_COLORS.keys())[:-1])
    with col2:
        type_filter = st.multiselect("Filtrer på type", options=user_feedback['type'].dropna().unique())

    # Anvend filtre
    if status_filter:
        user_feedback = user_feedback[user_feedback['status'].isin(status_filter)]
    if type_filter:
        user_feedback = user_feedback[user_feedback['type'].isin(type_filter)]

    # Vis feedback
    st.subheader("Detaljert feedback-oversikt")
    for index, feedback in user_feedback.iterrows():
        status = feedback['status']
        status_color = STATUS_COLORS.get(status, STATUS_COLORS['default'])
        
        # Lag en farget kollapsbar for hver feedback-post
        with st.expander(f"{feedback['type']} - {feedback['datetime'].strftime('%Y-%m-%d %H:%M')}", expanded=False):
            st.markdown(f"<h4 style='color: {status_color};'>Status: {status}</h4>", unsafe_allow_html=True)
            st.write(f"Fra: {feedback['innsender']}")
            st.write(f"Kommentar: {feedback['comment']}")
            
            # Dropdown for å endre status
            new_status = st.selectbox("Endre status", 
                                      options=list(STATUS_COLORS.keys())[:-1],  # Ekskluder 'default'
                                      index=list(STATUS_COLORS.keys()).index(status) if status in STATUS_COLORS else 0,
                                      key=f"status_{index}")
            
            # Knapp for å oppdatere status
            if st.button("Oppdater status", key=f"update_{index}"):
                if update_feedback_status(feedback['id'], new_status, st.session_state.username):
                    st.success("Status oppdatert")
                    st.rerun()
                else:
                    st.error("Feil ved oppdatering av status")

            # Knapp for å slette feedback
            if st.button("Slett feedback", key=f"delete_{index}"):
                result = delete_feedback(feedback['id'])
                if result is True:
                    st.success("Feedback slettet")
                    st.rerun()
                elif result == "not_found":
                    st.warning("Feedback-en ble ikke funnet. Den kan allerede være slettet.")
                    st.rerun()
                else:
                    st.error("Feil ved sletting av feedback")

    # Vis antall feedback-elementer
    st.info(f"Viser {len(user_feedback)} feedback-elementer for perioden {start_date} til {end_date}")

    # Legg til CSV-nedlastingsknapp
    if not user_feedback.empty:
        csv = user_feedback.to_csv(index=False)
        st.download_button(
            label="Last ned som CSV",
            data=csv,
            file_name="feedback_data.csv",
            mime="text/csv",
        )

def download_reports(include_hidden=False):
    st.subheader("Last ned rapporter og påloggingshistorikk")
    
    TZ = ZoneInfo("Europe/Oslo")
    
    # Date range selection
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=datetime(2020, 1, 1), min_value=datetime(2020, 1, 1), max_value=datetime.now(TZ))
    with col2:
        end_date = st.date_input("Til dato", value=datetime.now(TZ), min_value=datetime(2020, 1, 1), max_value=datetime.now(TZ))
    
    start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
    end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)
    
    # Data type selection
    data_types = st.multiselect("Velg datatyper", ["Rapporter", "Påloggingshistorikk"], default=["Rapporter", "Påloggingshistorikk"])
    
    # Fetch data
    all_reports = get_feedback(start_datetime.isoformat(), end_datetime.isoformat(), include_hidden=include_hidden) if "Rapporter" in data_types else pd.DataFrame()
    login_history = get_login_history(start_datetime, end_datetime) if "Påloggingshistorikk" in data_types else pd.DataFrame()
    
    if not all_reports.empty or not login_history.empty:
        # Data preprocessing
        if not all_reports.empty:
            all_reports['datetime'] = pd.to_datetime(all_reports['datetime']).dt.tz_convert(TZ)
            all_reports['date'] = all_reports['datetime'].dt.date
        
        if not login_history.empty:
            login_history['login_time'] = pd.to_datetime(login_history['login_time']).dt.tz_convert(TZ)
            login_history['date'] = login_history['login_time'].dt.date
        
        # Data visualization
        if not all_reports.empty:
            st.subheader("Rapportanalyse")
            fig1 = px.histogram(all_reports, x='date', title='Rapporter over tid')
            st.plotly_chart(fig1)
            
            fig2 = px.pie(all_reports, names='type', title='Fordeling av rapporttyper')
            st.plotly_chart(fig2)
        
        if not login_history.empty:
            st.subheader("Påloggingsanalyse")
            fig3 = px.histogram(login_history, x='date', title='Pålogginger over tid')
            st.plotly_chart(fig3)
            
            success_rate = (login_history['success'].sum() / len(login_history)) * 100
            st.metric("Vellykket påloggingsrate", f"{success_rate:.2f}%")
        
        # Export options
        st.subheader("Eksportalternativer")
        export_format = st.radio("Velg eksportformat", ["CSV", "Excel"])
        
        if st.button("Last ned data"):
            if export_format == "CSV":
                csv_data = io.StringIO()
                if not all_reports.empty:
                    csv_data.write("Rapporter:\n")
                    all_reports.to_csv(csv_data, index=False)
                    csv_data.write("\n\n")
                if not login_history.empty:
                    csv_data.write("Påloggingshistorikk:\n")
                    login_history.to_csv(csv_data, index=False)
                
                st.download_button(
                    label="Last ned CSV",
                    data=csv_data.getvalue(),
                    file_name="rapporter_og_paalogginger.csv",
                    mime="text/csv",
                )
            else:  # Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    if not all_reports.empty:
                        all_reports.to_excel(writer, sheet_name='Rapporter', index=False)
                    if not login_history.empty:
                        login_history.to_excel(writer, sheet_name='Påloggingshistorikk', index=False)
                
                st.download_button(
                    label="Last ned Excel",
                    data=output.getvalue(),
                    file_name="rapporter_og_paalogginger.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        
        # Preview data
        st.subheader("Forhåndsvisning av data")
        if not all_reports.empty:
            st.write("Rapporter:")
            st.dataframe(all_reports)
        if not login_history.empty:
            st.write("Påloggingshistorikk:")
            st.dataframe(login_history)
    else:
        st.info("Ingen data å laste ned for den valgte perioden.")  

# Tunbrøyting functions

def handle_tun():
    st.title("Håndter tunbrøyting bestillinger")
    
    # Vis statistikk
    total_bestillinger = count_bestillinger()
    st.write(f"Totalt antall bestillinger: {total_bestillinger}")
    
    # Rediger bestilling
    vis_rediger_bestilling()

    # Slett bestilling
    st.subheader("Slett bestilling")
    bestilling_id_slett = st.number_input("Skriv inn ID på bestillingen du vil slette", min_value=1, key="slett_id")
    if st.button("Slett bestilling"):
        if slett_bestilling(bestilling_id_slett):
            st.success(f"Bestilling {bestilling_id_slett} er slettet.")
        else:
            st.error("Kunne ikke slette bestillingen. Vennligst sjekk ID og prøv igjen.")

    # Vis statistikk
    if total_bestillinger > 0:
        st.subheader("Statistikk")
        vis_tunbroyting_statistikk(hent_bestillinger())

# Helper functions
def login_page():
    st.title("Logg inn")
    user_id = st.text_input("Skriv inn bruker-ID")
    password = st.text_input("Skriv inn passord", type="password")
    if st.button("Logg inn"):
        if authenticate_user(user_id, password):
            customer = get_customer_by_id(user_id)
            if customer is not None:
                st.session_state.authenticated = True
                st.session_state.username = user_id
                st.success(f"Innlogget som {customer['Name']}")
                st.rerun()
            else:
                st.error("Brukerinformasjon ikke funnet. Kontakt administrator.")
        else:
            st.error("Ugyldig bruker-ID eller passord")
            log_failed_attempt(user_id)

def display_live_plowmap():
    st.title("Live Brøytekart")
    st.components.v1.html(
        '<iframe style="height: 100vh; width: 100vw;" src="https://plowman-new.xn--snbryting-m8ac.net/nb/share/Y3VzdG9tZXItMTM=" title="Live brøytekart"></iframe>',
        height=600,
        scrolling=True
    )

def manage_alerts():
    st.subheader("Administrer Advarsler")

    # Hent eksisterende varsler
    alerts = get_alerts()

    # Vis eksisterende varsler
    st.write("Eksisterende varsler:")
    for alert in alerts.to_dict('records'):  # Konverter DataFrame til liste av ordbøker
        with st.expander(f"{alert['type']} - {alert['datetime']}"):
            st.write(f"Melding: {alert['comment']}")
            st.write(f"Utløper: {alert['expiry_date']}")
            st.write(f"Målgruppe: {alert['target_group']}")
            
            # Oppdater status
            new_status = st.selectbox("Status", ["Aktiv", "Inaktiv", "Utløpt"], 
                                      index=["Aktiv", "Inaktiv", "Utløpt"].index(alert['status']),
                                      key=f"status_{alert['id']}")
            if st.button("Oppdater status", key=f"update_{alert['id']}"):
                if update_alert_status(alert['id'], new_status, st.session_state.username):
                    st.success("Status oppdatert")
                else:
                    st.error("Feil ved oppdatering av status")
            
            # Slett varsel
            if st.button("Slett varsel", key=f"delete_{alert['id']}"):
                if delete_alert(alert['id']):
                    st.success("Varsel slettet")
                else:
                    st.error("Feil ved sletting av varsel")

    # Opprett nytt varsel
    st.write("---")
    st.write("Opprett nytt varsel:")
    alert_type = st.selectbox("Varseltype", ["Generelt", "Brøyting", "Strøing", "Vedlikehold", "Annet"])
    message = st.text_area("Varselmelding")
    expiry_date = st.date_input("Utløpsdato", min_value=datetime.now().date())
    target_group = st.multiselect("Målgruppe", ["Alle brukere", "Årsabonnenter", "Ukentlige abonnenter", "Ikke-abonnenter"])

    if st.button("Opprett varsel"):
        if message and target_group:
            if save_alert(alert_type, message, expiry_date.isoformat(), target_group, st.session_state.username):
                st.success("Varsel opprettet")
            else:
                st.error("Feil ved opprettelse av varsel")
        else:
            st.warning("Vennligst fyll ut alle feltene")

def vis_tunbroyting_statistikk(bestillinger):
    st.subheader("Statistikk og visualiseringer")

    # Logg antall bestillinger for feilsøking
    st.write(f"Totalt antall bestillinger: {len(bestillinger)}")

    # Konverter datoer til datetime
    bestillinger['ankomst_dato'] = pd.to_datetime(bestillinger['ankomst_dato']).dt.date
    bestillinger['avreise_dato'] = pd.to_datetime(bestillinger['avreise_dato']).dt.date

    # Antall bestillinger per dag
    daily_counts = bestillinger['ankomst_dato'].value_counts().sort_index().reset_index()
    daily_counts.columns = ['ankomst_dato', 'count']
    
    # Logg daglige tellinger for feilsøking
    st.write("Daglige tellinger:")
    st.write(daily_counts)

    fig_daily = px.bar(daily_counts, x='ankomst_dato', y='count', 
                       title='Antall bestillinger per dag',
                       labels={'ankomst_dato': 'Dato', 'count': 'Antall bestillinger'})
    fig_daily.update_layout(bargap=0.2)
    fig_daily.update_yaxes(dtick=1)  # Sett y-akse intervall til 1
    st.plotly_chart(fig_daily)

    # Fordeling av abonnement typer
    abonnement_counts = bestillinger['abonnement_type'].value_counts()
    fig_abonnement = px.pie(values=abonnement_counts.values, names=abonnement_counts.index, 
                            title='Fordeling av abonnement typer')
    st.plotly_chart(fig_abonnement)

    # Bestillinger per rode (hvis tilgjengelig)
    if 'rode' in bestillinger.columns:
        rode_counts = bestillinger['rode'].value_counts()
        fig_rode = px.bar(x=rode_counts.index, y=rode_counts.values, 
                          title='Antall bestillinger per rode',
                          labels={'x': 'Rode', 'y': 'Antall bestillinger'})
        st.plotly_chart(fig_rode)
    else:
        st.info("Informasjon om 'rode' er ikke tilgjengelig for statistikk.")

    # Nøkkeltall
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Totalt antall bestillinger", len(bestillinger))
    with col2:
        st.metric("Unike brukere", bestillinger['bruker'].nunique())
    with col3:
        if 'avreise_dato' in bestillinger.columns and 'ankomst_dato' in bestillinger.columns:
            # Beregn gjennomsnittlig opphold
            bestillinger['opphold'] = (bestillinger['avreise_dato'] - bestillinger['ankomst_dato']).dt.days
            avg_stay = bestillinger['opphold'].mean()
            st.metric("Gjennomsnittlig opphold (dager)", round(avg_stay, 1))
        else:
            st.metric("Gjennomsnittlig opphold", "Ikke tilgjengelig")

    # Vis rådata for feilsøking
    st.subheader("Rådata for feilsøking")
    st.write(bestillinger)
  
def vis_rediger_bestilling():
    st.header("Rediger bestilling")
    
    max_id = get_max_bestilling_id()
    total_bestillinger = count_bestillinger()
    st.write(f"Totalt antall aktive bestillinger: {total_bestillinger}")
    st.write(f"Høyeste bestillings-ID: {max_id}")
    
    bestilling_id = st.number_input("Skriv inn bestillings-ID for redigering", min_value=1, max_value=max(max_id, 1))
    
    eksisterende_data = hent_bestilling(bestilling_id)
    
    if eksisterende_data is not None:
        st.success(f"Bestilling funnet med ID {bestilling_id}")
        with st.form("rediger_bestilling_form"):
            nye_data = {}
            nye_data['bruker'] = st.text_input("Bruker", value=eksisterende_data['bruker'])
            nye_data['ankomst_dato'] = st.date_input("Ankomstdato", value=pd.to_datetime(eksisterende_data['ankomst_dato']).date())
            nye_data['ankomst_tid'] = st.time_input("Ankomsttid", value=pd.to_datetime(eksisterende_data['ankomst_tid']).time())
            nye_data['avreise_dato'] = st.date_input("Avreisetato", value=pd.to_datetime(eksisterende_data['avreise_dato']).date() if pd.notnull(eksisterende_data['avreise_dato']) else None)
            nye_data['avreise_tid'] = st.time_input("Avreisetid", value=pd.to_datetime(eksisterende_data['avreise_tid']).time() if pd.notnull(eksisterende_data['avreise_tid']) else None)
            nye_data['abonnement_type'] = st.selectbox("Abonnementstype", options=['Ukentlig ved bestilling', 'Årsabonnement'], index=['Ukentlig ved bestilling', 'Årsabonnement'].index(eksisterende_data['abonnement_type']))
            
            submitted = st.form_submit_button("Oppdater bestilling")
            
            if submitted:
                if validere_bestilling(nye_data):
                    if oppdater_bestilling_i_database(bestilling_id, nye_data):
                        st.success(f"Bestilling {bestilling_id} er oppdatert!")
                    else:
                        st.error("Det oppstod en feil under oppdatering av bestillingen.")
                else:
                    st.error("Ugyldig input. Vennligst sjekk datoene og prøv igjen.")
    else:
        st.warning(f"Ingen aktiv bestilling funnet med ID {bestilling_id}")
    
    # Velg periode for visning av bestillinger
    st.subheader("Vis bestillinger for periode")
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=datetime.now(TZ).date())
    with col2:
        end_date = st.date_input("Til dato", value=start_date + timedelta(days=7))

    # Hent og vis bestillinger for valgt periode
    bestillinger = hent_bestillinger_for_periode(start_date, end_date)
    if not bestillinger.empty:
        st.dataframe(bestillinger)
    else:
        st.info("Ingen bestillinger funnet for valgt periode.")

def hent_bestillinger_for_periode(start_date, end_date):
    try:
        with get_tunbroyting_connection() as conn:
            query = """
            SELECT * FROM tunbroyting_bestillinger 
            WHERE (ankomst_dato BETWEEN ? AND ?) OR (avreise_dato BETWEEN ? AND ?)
            ORDER BY ankomst_dato, ankomst_tid
            """
            df = pd.read_sql_query(query, conn, params=(start_date, end_date, start_date, end_date))
        
        if df.empty:
            logger.info("Ingen bestillinger funnet for valgt periode.")
            return pd.DataFrame()

        logger.info(f"Hentet {len(df)} bestillinger for perioden {start_date} til {end_date}.")

        # Konverter dato- og tidskolonner
        for col in ['ankomst_dato', 'avreise_dato']:
            df[col] = pd.to_datetime(df[col], errors='coerce')
        
        for col in ['ankomst_tid', 'avreise_tid']:
            df[col] = pd.to_datetime(df[col], format='%H:%M:%S', errors='coerce').dt.time
        
        # Kombiner dato og tid til datetime-objekter
        df['ankomst'] = df.apply(lambda row: pd.Timestamp.combine(row['ankomst_dato'], row['ankomst_tid']) if pd.notnull(row['ankomst_dato']) and pd.notnull(row['ankomst_tid']) else pd.NaT, axis=1)
        df['avreise'] = df.apply(lambda row: pd.Timestamp.combine(row['avreise_dato'], row['avreise_tid']) if pd.notnull(row['avreise_dato']) and pd.notnull(row['avreise_tid']) else pd.NaT, axis=1)
        
        # Sett tidssone
        for col in ['ankomst', 'avreise']:
            df[col] = df[col].dt.tz_localize(TZ, ambiguous='NaT', nonexistent='NaT')

        return df

    except Exception as e:
        logger.error(f"Feil ved henting av bestillinger for periode: {str(e)}", exc_info=True)
        return pd.DataFrame()

def validere_bestilling(data):
    if data['avreise_dato'] is None or data['avreise_tid'] is None:
        return True  # Hvis avreisedato eller -tid ikke er satt, er bestillingen gyldig
    
    ankomst = datetime.combine(data['ankomst_dato'], data['ankomst_tid'])
    avreise = datetime.combine(data['avreise_dato'], data['avreise_tid'])
    
    return avreise > ankomst

def vis_aktive_bestillinger():
    st.subheader("Oversikt over aktive tunbrøytingsbestillinger")
    
    # Hent alle bestillinger
    bestillinger = hent_bestillinger()
    
    # Filtreringsmuligheter
    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("Fra dato", value=datetime.now(TZ).date())
    with col2:
        end_date = st.date_input("Til dato", value=datetime.now(TZ).date() + timedelta(days=30))
    with col3:
        abonnement_type = st.multiselect("Abonnement type", options=bestillinger['abonnement_type'].unique())

    # Filtrer bestillinger
    mask = (bestillinger['ankomst_dato'].dt.date >= start_date) & (bestillinger['ankomst_dato'].dt.date <= end_date)
    if abonnement_type:
        mask &= bestillinger['abonnement_type'].isin(abonnement_type)
    
    filtered_bestillinger = bestillinger[mask]

    # Sorter bestillinger
    sort_column = st.selectbox("Sorter etter", options=['ankomst_dato', 'bruker', 'abonnement_type'])
    sort_order = st.radio("Sorteringsrekkefølge", options=['Stigende', 'Synkende'])
    
    filtered_bestillinger = filtered_bestillinger.sort_values(by=sort_column, ascending=(sort_order == 'Stigende'))

    # Vis dataframe
    st.dataframe(filtered_bestillinger)

    # Vis statistikk
    st.subheader("Statistikk")
    st.write(f"Totalt antall aktive bestillinger: {len(filtered_bestillinger)}")
    st.write(f"Antall årsabonnementer: {len(filtered_bestillinger[filtered_bestillinger['abonnement_type'] == 'Årsabonnement'])}")
    st.write(f"Antall ukentlige bestillinger: {len(filtered_bestillinger[filtered_bestillinger['abonnement_type'] == 'Ukentlig ved bestilling'])}")

# def vis_stroing_kart(bestillinger, mapbox_token):
#     cabin_coordinates = get_cabin_coordinates()
#     current_date = datetime.now(TZ).date()
    
#     # Debug: Vis antall bestillinger og koordinater
#     st.write(f"Debug: Antall bestillinger: {len(bestillinger)}")
#     st.write(f"Debug: Antall koordinater: {len(cabin_coordinates)}")

#     # Prepare data for the map
#     latitudes, longitudes, texts, colors, sizes = [], [], [], [], []
#     color_map = {
#         "Pending": "orange",
#         "Completed": "green",
#         "Cancelled": "red"
#     }

#     for coord in cabin_coordinates:
#         cabin_id = coord['cabin_id']
#         lat, lon = float(coord['latitude']), float(coord['longitude'])
        
#         if lat != 0 and lon != 0 and not (pd.isna(lat) or pd.isna(lon)):
#             latitudes.append(lat)
#             longitudes.append(lon)
            
#             cabin_bookings = bestillinger[bestillinger['bruker'] == str(cabin_id)]
#             if not cabin_bookings.empty:
#                 latest_booking = cabin_bookings.iloc[0]
#                 status = latest_booking['status']
#                 color = color_map.get(status, "gray")
#                 size = 12 if status == "Pending" else 10
#                 text = f"Hytte: {cabin_id}<br>Status: {status}<br>Dato: {latest_booking['onske_dato'].strftime('%Y-%m-%d')}"
#             else:
#                 color = "gray"
#                 size = 8
#                 text = f"Hytte: {cabin_id}<br>Ingen bestilling"
            
#             colors.append(color)
#             sizes.append(size)
#             texts.append(text)

#     # Create the map
#     fig = go.Figure()

#     fig.add_trace(go.Scattermapbox(
#         lat=latitudes,
#         lon=longitudes,
#         mode='markers',
#         marker=go.scattermapbox.Marker(
#             size=sizes,
#             color=colors,
#             opacity=0.8,
#         ),
#         text=texts,
#         hoverinfo='text'
#     ))

#     fig.update_layout(
#         title="Kart over strøingsbestillinger",
#         mapbox_style="streets",
#         mapbox=dict(
#             accesstoken=mapbox_token,
#             center=dict(lat=sum(latitudes)/len(latitudes), lon=sum(longitudes)/len(longitudes)),
#             zoom=13
#         ),
#         showlegend=False,
#         height=600,
#         margin={"r":0,"t":30,"l":0,"b":0}
#     )

#     st.plotly_chart(fig, use_container_width=True)
#     # Debug: Vis data brukt for kartet
#     st.write("Debug: Data brukt for kartet:")
#     st.write(pd.DataFrame({
#         'latitude': latitudes,
#         'longitude': longitudes,
#         'text': texts,
#         'color': colors,
#         'size': sizes
#     }))

#     # Legend
#     st.write("Forklaring på fargekoder:")
#     col1, col2, col3, col4 = st.columns(4)
#     with col1:
#         st.markdown('<div style="background-color: orange; height: 20px; width: 20px; display: inline-block;"></div> Venter', unsafe_allow_html=True)
#     with col2:
#         st.markdown('<div style="background-color: green; height: 20px; width: 20px; display: inline-block;"></div> Utført', unsafe_allow_html=True)
#     with col3:
#         st.markdown('<div style="background-color: red; height: 20px; width: 20px; display: inline-block;"></div> Kansellert', unsafe_allow_html=True)
#     with col4:
#         st.markdown('<div style="background-color: gray; height: 20px; width: 20px; display: inline-block;"></div> Ingen bestilling', unsafe_allow_html=True)

def update_stroing_status_ui(row, index):
    print(f"Debug: Entering update_stroing_status_ui function for bestilling {row['id']}")
    st.write(f"Debug: Entering update_stroing_status_ui function for bestilling {row['id']}")
    
    current_status = get_status_display(row['status'])
    print(f"Debug: Current status: {current_status}")
    st.write(f"Debug: Current status: {current_status}")
    
    new_status = st.selectbox(
        "Velg ny status",
        list(STATUS_MAPPING.keys()),
        index=list(STATUS_MAPPING.keys()).index(current_status),
        key=f"status_{row['id']}_{index}"
    )
    print(f"Debug: New status selected: {new_status}")
    st.write(f"Debug: New status selected: {new_status}")
    
    if st.button("Oppdater status", key=f"update_{row['id']}_{index}"):
        print(f"Debug: Update button clicked for bestilling {row['id']}")
        st.write(f"Debug: Update button clicked for bestilling {row['id']}")
        
        if st.checkbox(f"Er du sikker på at du vil endre status for bestilling {row['id']} til {new_status}?", key=f"confirm_{row['id']}_{index}"):
            try:
                success, message = update_stroing_status(row['id'], new_status)
                print(f"Debug: update_stroing_status returned: success={success}, message={message}")
                st.write(f"Debug: update_stroing_status returned: success={success}, message={message}")
                
                if success:
                    if new_status == "Utført":
                        utfort_av = st.session_state.username
                        print(f"Debug: Calling update_stroing_status with {row['id']}, {new_status}, {utfort_av}")
                        st.write(f"Debug: Calling update_stroing_status with {row['id']}, {new_status}, {utfort_av}")
                        update_stroing_status(row['id'], new_status, utfort_av=utfort_av)
                    
                    st.success(f"Status oppdatert for bestilling (Hytte {row['bruker']})")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(f"Feil ved oppdatering av status for bestilling (Hytte {row['bruker']}): {message}")
            except Exception as e:
                print(f"Debug: Exception occurred: {str(e)}")
                st.error(f"Uventet feil oppstod: {str(e)}")
                st.write(f"Debug: Exception occurred: {str(e)}")
        else:
            st.info("Oppdatering avbrutt. Bekreft for å gjennomføre endringen.")
    else:
        print("Debug: Update button not clicked")
        st.write("Debug: Update button not clicked")
             
def delete_stroing_bestilling_ui(row, index):
    if st.button("Slett bestilling", key=f"delete_{row['id']}_{index}"):
        if slett_stroing_bestilling(row['id']):
            st.success(f"Bestilling for Hytte {row['bruker']} er slettet")
            st.rerun()
        else:
            st.error(f"Feil ved sletting av bestilling for Hytte {row['bruker']}")

def display_bookings(username):
    previous_bookings = hent_bruker_bestillinger(username)
    
    if not previous_bookings.empty:
        for _, booking in previous_bookings.iterrows():
            with st.expander(f"Bestilling - {booking['ankomst_dato']}"):
                st.write(f"Ankomst: {booking['ankomst_dato']} {booking['ankomst_tid']}")
                if pd.notnull(booking['avreise_dato']):
                    st.write(f"Avreise: {booking['avreise_dato']} {booking['avreise_tid']}")
                st.write(f"Type: {booking['abonnement_type']}")
    else:
        st.info("Du har ingen tidligere bestillinger.")

def display_stroing_bookings(username):
    st.subheader("Dine tidligere strøing-bestillinger")
    
    previous_bookings = hent_bruker_stroing_bestillinger(username)
    
    if previous_bookings.empty:
        st.info("Du har ingen tidligere strøing-bestillinger.")
    else:
        for _, booking in previous_bookings.iterrows():
            with st.expander(f"Bestilling - Ønsket dato: {booking['onske_dato'].strftime('%Y-%m-%d')}"):
                st.write(f"Bestilt: {booking['bestillings_dato'].strftime('%Y-%m-%d %H:%M')}")
                st.write(f"Ønsket dato: {booking['onske_dato'].strftime('%Y-%m-%d')}")
        
def display_recent_feedback():
    st.subheader("Nylige rapporter")
    end_date = datetime.now(TZ)
    start_date = end_date - timedelta(days=7)
    recent_feedback = get_feedback(start_date.isoformat(), end_date.isoformat())
    
    if not recent_feedback.empty:
        # Sett status for ny feedback til 'Ny'
        recent_feedback.loc[recent_feedback['status'].isnull(), 'status'] = 'Ny'
        
        recent_feedback = recent_feedback.sort_values('datetime', ascending=False)
        
        st.write(f"Viser {len(recent_feedback)} rapporter fra de siste 7 dagene:")
        
        for _, row in recent_feedback.iterrows():
            icon = icons.get(row['type'], "❓")
            status = row['status']
            status_color = STATUS_COLORS.get(status, STATUS_COLORS['default'])
            date_str = row['datetime'].strftime('%Y-%m-%d %H:%M') if pd.notnull(row['datetime']) else 'Ukjent dato'
            
            with st.expander(f"{icon} {row['type']} - {date_str}"):
                st.markdown(f"<span style='color:{status_color};'>●</span> **Status:** {status}", unsafe_allow_html=True)
                st.write(f"**Rapportert av:** {row['innsender']}")
                st.write(f"**Kommentar:** {row['comment']}")
                if pd.notnull(row['status_changed_at']):
                    st.write(f"**Status oppdatert:** {row['status_changed_at'].strftime('%Y-%m-%d %H:%M')}")
    else:
        st.info("Ingen rapporter i de siste 7 dagene.")

def get_cabin_coordinates():
    customer_db = load_customer_database()
    return [
        {
            "cabin_id": row["Id"],
            "name": row["Name"],
            "latitude": row["Latitude"],
            "longitude": row["Longitude"],
            "subscription": row["Subscription"]
        }
        for _, row in customer_db.iterrows()
    ]
 
def save_feedback(feedback_type, datetime_str, comment, cabin_identifier, hidden, is_alert=False):
    try:
        query = """INSERT INTO feedback (type, datetime, comment, innsender, status, status_changed_at, hidden, is_alert) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        initial_status = "Aktiv" if "Aktiv" in STATUS_COLORS else "Innmeldt"
        params = (feedback_type, datetime_str, comment, cabin_identifier, initial_status, datetime.now(TZ).isoformat(), hidden, is_alert)
        
        # st.write(f"Debug: SQL Query: {query}")
        # st.write(f"Debug: Params: {params}")
        
        execute_query('feedback', query, params)
        
        logger.info(f"Feedback saved successfully: {feedback_type}, {datetime_str}, Cabin: {cabin_identifier}, hidden: {hidden}, is_alert: {is_alert}")
        return True
    except Exception as e:
        logger.error(f"Error saving feedback: {str(e)}", exc_info=True)
        # st.write(f"Debug: Error in save_feedback: {str(e)}")
        return False

def display_feedback_dashboard():
    st.subheader("Feedback Dashboard")

    # Beregn datoer for de siste 7 dagene pluss morgendagen
    end_date = datetime.now(TZ).date() + timedelta(days=1)  # Inkluderer morgendagen
    start_date = end_date - timedelta(days=7)  # 8 dager totalt, inkludert i dag og i morgen

    # Dato-velgere for periode, med standard verdier satt til beregnet intervall
    col1, col2 = st.columns(2)
    with col1:
        selected_start_date = st.date_input("Fra dato", value=start_date, max_value=end_date)
    with col2:
        selected_end_date = st.date_input("Til dato", value=end_date, min_value=selected_start_date)

    # Konverter datoene til datetime med klokkeslett
    start_datetime = datetime.combine(selected_start_date, datetime.min.time()).replace(tzinfo=TZ)
    end_datetime = datetime.combine(selected_end_date, datetime.max.time()).replace(tzinfo=TZ)

    # Hent feedback-data for den valgte perioden
    feedback_data = get_feedback(start_date=start_datetime.isoformat(), end_date=end_datetime.isoformat(), include_hidden=False)

    if feedback_data.empty:
        st.warning(f"Ingen feedback-data tilgjengelig for perioden {selected_start_date} til {selected_end_date}.")
        return

    # Forbered data for grafer
    feedback_data['datetime'] = pd.to_datetime(feedback_data['datetime'])
    feedback_data.loc[feedback_data['status'].isnull() | (feedback_data['status'] == 'Innmeldt'), 'status'] = 'Ny'

    # Opprett et fullstendig datointervall inkludert dager uten feedback
    full_date_range = pd.date_range(start=selected_start_date, end=selected_end_date, freq='D')
    daily_counts = feedback_data.groupby(feedback_data['datetime'].dt.date).size().reindex(full_date_range, fill_value=0).reset_index()
    daily_counts.columns = ['date', 'count']

    # Opprett stolpediagram for feedback over tid
    fig_bar = px.bar(daily_counts, x='date', y='count', title="Antall feedback over tid")
    fig_bar.update_xaxes(title_text="Dato", tickformat="%Y-%m-%d")
    fig_bar.update_yaxes(title_text="Antall feedback", dtick=1)
    fig_bar.update_layout(bargap=0.2)
    st.plotly_chart(fig_bar)

    # Vis totalt antall feedback-elementer
    st.info(f"Totalt {len(feedback_data)} feedback-elementer for perioden {selected_start_date} til {selected_end_date}")

    # Legg til feilsøkingsinformasjon
    if st.checkbox("Vis rådata for grafen"):
        st.write("Rådata for grafen:")
        st.write(daily_counts)

    # Legg til CSV-nedlastingsknapp
    if not feedback_data.empty:
        csv = feedback_data.to_csv(index=False)
        st.download_button(
            label="Last ned som CSV",
            data=csv,
            file_name="feedback_data.csv",
            mime="text/csv",
        )
    
def dump_debug_info():
    logger.info("Dumping debug info")
    
    customer_db = load_customer_database()
    logger.info(f"Total number of customers: {len(customer_db)}")
    
    if 'Type' in customer_db.columns:
        logger.info(f"Customer types: {customer_db['Type'].value_counts().to_dict()}")
    else:
        logger.warning("'Type' column not found in customer database")
    
    logger.info("Passwords:")
    for user_id in st.secrets["passwords"]:
        logger.info(f"User ID: {user_id} has a password set")
    
    logger.info("Bestillinger:")
    bestillinger = hent_bestillinger()
    if bestillinger.empty:
        logger.info("Ingen bestillinger funnet.")
    else:
        for _, row in bestillinger.iterrows():
            logger.info(f"Bestilling ID: {row['id']}, Bruker: {row['bruker']}, "
                        f"Ankomst dato: {row['ankomst_dato']}, Ankomst tid: {row['ankomst_tid']}, "
                        f"Avreise dato: {row['avreise_dato']}, Avreise tid: {row['avreise_tid']}, "
                        f"Kombinert ankomst: {row['ankomst']}, Kombinert avreise: {row['avreise']}, "
                        f"Type: {row['abonnement_type']}")
        
        logger.info("Kolonnetyper:")
        for col in bestillinger.columns:
            logger.info(f"{col}: {bestillinger[col].dtype}")
        
# Hovedfunksjonene for appen
def create_menu(customer_name, is_admin=False):
    with st.sidebar:
        st.success(f"Innlogget som {customer_name}")

        main_menu_options = [
            "Værdata",
            "Bestill Tunbrøyting",
            "Bestill Strøing",
            "Tunkart",
            "Live Brøytekart",
            "Gi feedback"
        ]
        if is_admin:
            main_menu_options.append("Administrasjon")

        selected = option_menu(
            "Hovedmeny",
            main_menu_options,
            icons=['cloud-sun', 'snow', 'moisture', 'map', 'truck', 'chat-dots', 'gear'],
            menu_icon="cast",
            default_index=0,
        )

        admin_choice = None
        if selected == "Administrasjon" and is_admin:
            admin_choice = option_menu(
                "",
                ["Dashbord", "Håndter feedback", "Håndter tun", "Håndter strøing", "Last ned rapporter", "Håndter Advarsler"],
                icons=['graph-up', 'cloud-upload', 'eye', 'list-check', 'wrench', 'download', 'exclamation-triangle'],
                menu_icon="cast",
                default_index=0,
            )

        if st.button("🚪 Logg ut"):
            st.session_state.authenticated = False
            st.session_state.username = None
            st.rerun()

    return selected, admin_choice

def main():
    dump_debug_info()
    create_all_tables()
    update_login_history_table()
    update_database_schema()
    initialize_database()  # Dette vil nå slette eksisterende stroing.db og opprette en ny
    check_session_timeout()
    check_cabin_user_consistency()
    validate_customers_and_passwords()
    verify_stroing_data()

    logger.info("Application setup complete")

    config = st.secrets

    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = None
        st.session_state.is_admin = False

    if not st.session_state.authenticated:
        login_page()
    else:
        customer = get_customer_by_id(st.session_state.username)
        if customer is None:
            st.error("Kunne ikke finne brukerinformasjon")
            st.session_state.authenticated = False
            st.session_state.is_admin = False
            st.rerun()
        else:
            st.session_state.is_admin = customer.get('Type', 'Customer').lower() == 'admin'
            selected, admin_choice = create_menu(customer['Name'], st.session_state.is_admin)

            if selected == "Værdata":
                display_weather_data()
            elif selected == "Bestill Tunbrøyting":
                bestill_tunbroyting()
            elif selected == "Bestill Strøing":
                bestill_stroing()
                display_stroing_bookings(st.session_state.username)
            elif selected == "Tunkart":
                vis_tunbroyting_oversikt()
            elif selected == "Live Brøytekart":
                display_live_plowmap()
            elif selected == "Gi feedback":
                give_feedback()
            elif selected == "Administrasjon" and st.session_state.is_admin:
                if admin_choice == "Dashbord":
                    show_dashboard(include_hidden=True)
                elif admin_choice == "Håndter feedback":
                    handle_user_feedback()
                elif admin_choice == "Håndter tun":
                    vis_rediger_bestilling()
                elif admin_choice == "Håndter strøing":
                    admin_stroing_page()
                elif admin_choice == "Last ned rapporter":
                    download_reports(include_hidden=True)
                elif admin_choice == "Håndter Advarsler":
                    admin_alert()

if __name__ == "__main__":
    main()
    