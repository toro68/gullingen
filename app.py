import streamlit as st
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from statsmodels.nonparametric.smoothers_lowess import lowess
import logging
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Constants ---
STATION_ID = "SN46220"
API_URL = "https://frost.met.no/observations/v0.jsonld"
ELEMENTS = "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),max_wind_speed(wind_from_direction PT1H),max(wind_speed_of_gust PT1H),min(wind_speed P1M),wind_speed,surface_temperature,relative_humidity,dew_point_temperature"
TIME_RESOLUTION = "PT1H"
GPS_URL = "https://kart.irute.net/fjellbergsskardet_busses.json?_=1657373465172"
TZ = ZoneInfo("Europe/Oslo")

# --- Helper Functions ---

# Definer vindretningskategorier
wind_directions = {
    'N': (337.5, 22.5),
    'NØ': (22.5, 67.5),
    'Ø': (67.5, 112.5),
    'SØ': (112.5, 157.5),
    'S': (157.5, 202.5),
    'SV': (202.5, 247.5),
    'V': (247.5, 292.5),
    'NV': (292.5, 337.5)
}

# Funksjon for å kategorisere vindretninger
def categorize_direction(degree):
    for direction, (min_deg, max_deg) in wind_directions.items():
        if min_deg <= degree < max_deg or (direction == 'N' and (degree >= 337.5 or degree < 22.5)):
            return direction
    return 'Ukjent'

def fetch_gps_data():
    logger.info("Fetching GPS data")
    
    try:
        response = requests.get(GPS_URL)
        response.raise_for_status()
        gps_data = response.json()
        all_eq_dicts = gps_data['features']
        
        gps_entries = []
        for eq_dict in all_eq_dicts:
            date_str = eq_dict['properties']['Date']
            gps_entry = {
                'BILNR': eq_dict['properties']['BILNR'],
                'Date': datetime.strptime(date_str, '%H:%M:%S %d.%m.%Y').replace(tzinfo=TZ)
            }
            gps_entries.append(gps_entry)
        
        logger.info("Successfully fetched and processed GPS data")
        return gps_entries
    except requests.RequestException as e:
        logger.error(f"Error fetching GPS data: {e}")
        return []
    except ValueError as e:
        logger.error(f"Date parsing error: {e}")
        return []

def validate_data(data):
    logger.info("Starting function: validate_data")
    data = np.array(data, dtype=float)
    if np.all(np.isnan(data)):
        return data
    median = np.nanmedian(data)
    std = np.nanstd(data)
    lower_bound = median - 5 * std
    upper_bound = median + 5 * std
    data[(data < lower_bound) | (data > upper_bound)] = np.nan
    logger.info("Completed function: validate_data")
    return data

def smooth_data(data):
    logger.info("Starting function: smooth_data")
    if np.all(np.isnan(data)):
        return data
    timestamps = np.arange(len(data))
    valid_indices = ~np.isnan(data)
    if np.sum(valid_indices) < 2:
        return data
    smoothed = lowess(data[valid_indices], timestamps[valid_indices], frac=0.1, it=0)
    result = np.full_like(data, np.nan)
    result[valid_indices] = smoothed[:, 1]
    logger.info("Completed function: smooth_data")
    return result

def handle_missing_data(timestamps, data, method='time'):
    logger.info(f"Starting function: handle_missing_data with method {method}")
    data_series = pd.Series(data, index=timestamps)
    if method == 'time':
        interpolated = data_series.interpolate(method='time')
    elif method == 'linear':
        interpolated = data_series.interpolate(method='linear')
    else:
        interpolated = data_series.interpolate(method='nearest')
    logger.info("Completed function: handle_missing_data")
    return interpolated.to_numpy()

def create_improved_graph(df):
    fig = make_subplots(
        rows=7, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=(
            "Alarmer", "Temperatur (°C)", "Nedbør (mm)", "Antatt snønedbør (mm)", 
            "Snødybde (cm)", "Vindhastighet (m/s)", "Vindretning"
        )
    )

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']

    # Alarmer (moved to the top)
    snow_drift_alarms = df[df['snow_drift_alarm'] == 1].index
    slippery_road_alarms = df[df['slippery_road_alarm'] == 1].index
    
    fig.add_trace(go.Scatter(x=snow_drift_alarms, y=[1]*len(snow_drift_alarms), mode='markers', 
                             name='Snøfokk-alarm', marker=dict(symbol='triangle-up', size=10, color='blue')),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=slippery_road_alarms, y=[0]*len(slippery_road_alarms), mode='markers', 
                             name='Glatt vei-alarm', marker=dict(symbol='triangle-down', size=10, color='red')),
                  row=1, col=1)

    # Temperatur
    temp_above_zero = [t if t > 0 else None for t in df['air_temperature']]
    temp_below_zero = [t if t <= 0 else None for t in df['air_temperature']]
    
    fig.add_trace(go.Scatter(x=df.index, y=temp_above_zero, mode='lines', name='Over 0°C',
                             line=dict(color='red', width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=temp_below_zero, mode='lines', name='Under 0°C',
                             line=dict(color='blue', width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=[df.index[0], df.index[-1]], y=[0, 0], mode='lines', name='0°C',
                             line=dict(color='black', width=1, dash='dash')), row=2, col=1)

    # Nedbør
    precip_rain = [p if t > 0.3 else 0 for p, t in zip(df['precipitation_amount'], df['air_temperature'])]
    precip_snow = [p if t <= 0 else 0 for p, t in zip(df['precipitation_amount'], df['air_temperature'])]
    precip_sleet = [p if 0 < t <= 0.3 else 0 for p, t in zip(df['precipitation_amount'], df['air_temperature'])]

    fig.add_trace(go.Bar(x=df.index, y=precip_rain, name='Regn (>0.3°C)',
                         marker_color='red'), row=3, col=1)
    fig.add_trace(go.Bar(x=df.index, y=precip_snow, name='Snø (≤0°C)',
                         marker_color='blue'), row=3, col=1)
    fig.add_trace(go.Bar(x=df.index, y=precip_sleet, name='Sludd (0-0.3°C)',
                         marker_color='purple'), row=3, col=1)
    
    # Antatt snønedbør
    fig.add_trace(go.Bar(x=df.index, y=df['snow_precipitation'], name='Antatt snønedbør',
                         marker_color=colors[2]), row=4, col=1)
    
    # Snødybde
    fig.add_trace(go.Scatter(x=df.index, y=df['surface_snow_thickness'], mode='lines', name='Snødybde',
                             line=dict(color=colors[3], width=2)), row=5, col=1)
    
    # Vindhastighet
    fig.add_trace(go.Scatter(x=df.index, y=df['wind_speed'], mode='lines', name='Gjennomsnittlig vindhastighet',
                             line=dict(color='purple', width=2)), row=6, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['max_wind_speed'], mode='lines', name='Maks vindhastighet',
                             line=dict(color='red', width=1)), row=6, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['min_wind_speed'], mode='lines', name='Min vindhastighet',
                             line=dict(color='blue', width=1)), row=6, col=1)
    
    # Vindretning
    wind_direction_counts = df['wind_direction_category'].value_counts()
    directions = ['N', 'NØ', 'Ø', 'SØ', 'S', 'SV', 'V', 'NV']
    values = [wind_direction_counts.get(d, 0) for d in directions]
    
    for direction in directions:
        direction_data = df[df['wind_direction_category'] == direction]
        fig.add_trace(go.Scatter(
            x=direction_data.index, 
            y=direction_data['wind_from_direction'],
            mode='markers',
            name=direction,
            marker=dict(size=5, symbol='triangle-up')
        ), row=7, col=1)

    # Update y-axis for wind direction
    fig.update_yaxes(row=7, col=1, 
                     range=[0, 360],
                     dtick=45,
                     ticktext=directions, 
                     tickvals=[0, 45, 90, 135, 180, 225, 270, 315],
                     title_text="Vindretning")

    # Update layout
    fig.update_layout(
        height=2100,
        plot_bgcolor='rgba(240,240,240,0.8)',
        barmode='stack',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.1,
            xanchor="center",
            x=0.5,
            font=dict(size=10)
        ),
        margin=dict(l=50, r=50, t=100, b=100)  # Increase bottom margin to accommodate legend
    )
    
    fig.update_xaxes(
        tickformat="%d.%m %H:%M",
        gridcolor='rgba(0,0,0,0.1)',
        title_text="Dato og tid",
        title_font=dict(size=12),
        title_standoff=15
    )

    # Update y-axes
    for i in range(1, 8):
        fig.update_yaxes(
            row=i, col=1,
            gridcolor='rgba(0,0,0,0.1)',
            title_font=dict(size=14),
            title_standoff=10
        )
    
    # Specific updates for wind direction y-axis
    fig.update_yaxes(row=7, col=1, 
                     range=[360, 0],  # Invert the axis
                     dtick=45,
                     ticktext=['N', 'NØ', 'Ø', 'SØ', 'S', 'SV', 'V', 'NV'], 
                     tickvals=[0, 45, 90, 135, 180, 225, 270, 315],
                     title_text="Vindretning")

    # Add explanatory text for wind direction
    fig.add_annotation(
        text="Vindretning vises i grader og kategorier. Triangler peker i vindretningen.",
        xref="paper", yref="paper",
        x=0.5, y=0.01,  # Adjusted position to bottom of the figure
        showarrow=False,
        font=dict(size=10)
    )
    
    return fig

def fetch_and_process_data(client_id, date_start, date_end):
    logger.info("Starting function: fetch_and_process_data")
    try:
        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start}/{date_end}"
        }
        logger.info(f"Sending request with params: {params}")
        response = requests.get(API_URL, params=params, auth=(client_id, ""))
        response.raise_for_status()
        data = response.json()
        logger.info(f"Received data with {len(data.get('data', []))} entries")

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
            for item in data.get('data', [])
        ]).set_index('timestamp')

        logger.info(f"Created DataFrame with shape: {df.shape}")
        logger.info(f"DataFrame columns: {df.columns}")

        df.index = pd.to_datetime(df.index).tz_localize(TZ, nonexistent='shift_forward', ambiguous='NaT')

        # Create a new dictionary to store processed data
        processed_data = {}

        for column in df.columns:
            processed_data[column] = pd.to_numeric(df[column], errors='coerce')
            processed_data[column] = validate_data(processed_data[column])
            processed_data[column] = handle_missing_data(df.index, processed_data[column], method='time')

        # Create a new DataFrame with processed data
        processed_df = pd.DataFrame(processed_data, index=df.index)

        # Calculate snow precipitation
        processed_df['snow_precipitation'] = calculate_snow_precipitations(
            processed_df['air_temperature'].values,
            processed_df['precipitation_amount'].values,
            processed_df['surface_snow_thickness'].values
        )

        # Calculate alarms using processed data
        processed_df = calculate_snow_drift_alarms(processed_df)
        processed_df = calculate_slippery_road_alarms(processed_df)
        
        # Smooth the data for visualization
        smoothed_data = {}
        for column in processed_df.columns:
            if column not in ['snow_drift_alarm', 'slippery_road_alarm', 'snow_precipitation']:
                smoothed_data[column] = smooth_data(processed_df[column].values)
            else:
                smoothed_data[column] = processed_df[column]
        
        # Create a new DataFrame with smoothed data
        smoothed_df = pd.DataFrame(smoothed_data, index=processed_df.index)

        # Kategoriser vindretninger
        smoothed_df['wind_direction_category'] = smoothed_df['wind_from_direction'].apply(categorize_direction)

        logger.info("Completed function: fetch_and_process_data")
        return {'df': smoothed_df}

    except requests.RequestException as e:
        logger.error(f"Request error: {e}")
        return None
    except Exception as e:
        logger.error(f"Data processing error: {e}")
        return None
    
def get_date_range(choice):
    logger.info(f"Starting function: get_date_range with choice {choice}")
    now = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    if choice == '7d':
        start_time = now - timedelta(days=7)
    elif choice == '3d':
        start_time = now - timedelta(days=3)
    elif choice == '24h':
        start_time = now - timedelta(hours=24)
    elif choice == '12h':
        start_time = now - timedelta(hours=12)
    elif choice == '4h':
        start_time = now - timedelta(hours=4)
    elif choice == 'sf':
        start_time = now - timedelta(days=(now.weekday() - 4) % 7)
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    elif choice == 'ss':
        start_time = now - timedelta(days=now.weekday() + 1)
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        logger.error(f"Invalid choice: {choice}")
        return None, None
    logger.info(f"Date range: {start_time.isoformat()} to {now.isoformat()}")
    return start_time.isoformat(), now.isoformat()

def export_to_csv(df):
    logger.info("Starting function: export_to_csv")
    csv_data = df.to_csv(index=True).encode('utf-8')
    logger.info("Completed function: export_to_csv")
    return csv_data

def calculate_snow_drift_alarms(df):
    logger.info("Starting function: calculate_snow_drift_alarms")
    df['snow_depth_change'] = df['surface_snow_thickness'].diff()
    conditions = [
        df['wind_speed'] > 6,
        df['air_temperature'] <= -1,
        ((df['precipitation_amount'] <= 0.1) & (df['surface_snow_thickness'].diff().fillna(0).abs() >= 1)) | 
        ((df['precipitation_amount'] > 0.1) & (df['surface_snow_thickness'].diff().fillna(0) <= -0.5))
    ]
    df['snow_drift_alarm'] = np.all(conditions, axis=0).astype(int)
    
    logger.info(f"Number of alarms: {df['snow_drift_alarm'].sum()}")
    logger.info(f"Conditions met: Wind > 6: {conditions[0].sum()}, Temp <= -1: {conditions[1].sum()}, Precipitation and snow depth: {conditions[2].sum()}")
    
    return df

def calculate_slippery_road_alarms(df):
    logger.info("Starting function: calculate_slippery_road_alarms")
    conditions = [
        df['air_temperature'] > 0,
        df['precipitation_amount'] > 1.5,
        df['surface_snow_thickness'] >= 20,
        df['surface_snow_thickness'].diff().fillna(0) < 0
    ]
    df['slippery_road_alarm'] = np.all(conditions, axis=0).astype(int)
    
    logger.info(f"Number of alarms: {df['slippery_road_alarm'].sum()}")
    logger.info(f"Conditions met: Temp > 0: {conditions[0].sum()}, Precip > 1.5: {conditions[1].sum()}, Snow depth >= 20: {conditions[2].sum()}, Decreasing snow: {conditions[3].sum()}")
    
    return df

def calculate_snow_precipitations(temperatures, precipitations, snow_depths):
    logger.info("Starting function: calculate_snow_precipitations")
    snow_precipitations = np.zeros_like(temperatures)
    for i in range(len(temperatures)):
        if temperatures[i] is not None and not np.isnan(temperatures[i]):
            # Condition 1: Temperature ≤ 1.5°C and increasing snow depth
            condition1 = temperatures[i] <= 1.5 and i > 0 and not np.isnan(snow_depths[i]) and not np.isnan(snow_depths[i-1]) and snow_depths[i] > snow_depths[i-1]
            
            # Condition 2: Temperature ≤ 0°C and any precipitation
            condition2 = temperatures[i] <= 0 and not np.isnan(precipitations[i]) and precipitations[i] > 0
            
            if condition1 or condition2:
                snow_precipitations[i] = precipitations[i] if not np.isnan(precipitations[i]) else 0
    logger.info("Completed function: calculate_snow_precipitations")
    return snow_precipitations

# --- Main App ---

def main():
    st.set_page_config(layout="wide")
    
    # Updated CSS for dropdown menu
    st.markdown("""
    <style>
    div[data-baseweb="select"] {
        z-index: 999;
    }
    div[data-baseweb="select"] > div {
        max-height: none !important;
    }
    div[data-baseweb="select"] ul {
        max-height: 300px !important;
        padding-top: 0;
        padding-bottom: 0;
    }
    div[data-baseweb="select"] li {
        min-height: 50px;
        display: flex;
        align-items: center;
    }
    .stSelectbox div [data-testid="stMarkdownContainer"] p {
        font-size: 14px;
        margin-bottom: 0px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.title("Værdata for Gullingen")

    period = st.selectbox(
        "Velg en periode:",
        ["Siste 24 timer", "Siste 7 dager", "Siste 12 timer", "Siste 4 timer", 
         "Siden sist fredag", "Siden sist søndag", "Egendefinert periode", 
         "Siste GPS-aktivitet til nå"]
    )

    client_id = st.secrets["api_keys"]["client_id"]

    if period == "Egendefinert periode":
        col1, col2 = st.columns(2)
        with col1:
            date_start = st.date_input("Startdato", datetime.now(TZ) - timedelta(days=7))
        with col2:
            date_end = st.date_input("Sluttdato", datetime.now(TZ))

        if date_end <= date_start:
            st.error("Sluttdatoen må være etter startdatoen.")
            return

        date_start_isoformat = datetime.combine(date_start, datetime.min.time()).replace(tzinfo=TZ).isoformat()
        date_end_isoformat = datetime.combine(date_end, datetime.min.time()).replace(tzinfo=TZ).isoformat()
    elif period == "Siste GPS-aktivitet til nå":
        gps_data = fetch_gps_data()
        if gps_data:
            last_gps_activity = max(gps_data, key=lambda x: x['Date'])
            date_start_isoformat = last_gps_activity['Date'].isoformat()
            date_end_isoformat = datetime.now(TZ).isoformat()
        else:
            st.error("Ingen GPS-aktivitet funnet.")
            return
    else:
        choice_map = {
            "Siste 7 dager": '7d',
            "Siste 12 timer": '12h',
            "Siste 24 timer": '24h',
            "Siste 4 timer": '4h',
            "Siden sist fredag": 'sf',
            "Siden sist søndag": 'ss'
        }
        date_start_isoformat, date_end_isoformat = get_date_range(choice_map[period])
        if not date_start_isoformat or not date_end_isoformat:
            st.error("Ugyldig periodevalg.")
            return

    st.write(f"Henter data fra {date_start_isoformat} til {date_end_isoformat}")

    try:
        with st.spinner('Henter og behandler data...'):
            weather_data = fetch_and_process_data(client_id, date_start_isoformat, date_end_isoformat)
            gps_data = fetch_gps_data() if period != "Siste GPS-aktivitet til nå" else gps_data
        
        if weather_data and 'df' in weather_data:
            df = weather_data['df']
            st.write(f"Antall datapunkter: {len(df)}")
            st.write(f"Manglende datapunkter: {df.isna().sum().sum()}")
            st.write(f"Antall snøfokk-alarmer: {df['snow_drift_alarm'].sum()}")
            st.write(f"Antall glatt vei / slush-alarmer: {df['slippery_road_alarm'].sum()}")
            
            # Create and display the improved graph
            fig = create_improved_graph(df)
            st.plotly_chart(fig, use_container_width=True)

            # Display summary statistics
            st.subheader("Oppsummering av data")
            summary_df = pd.DataFrame({
                'Statistikk': ['Gjennomsnitt', 'Median', 'Minimum', 'Maksimum', 'Total'],
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
                'Gjennomsnittlig vindhastighet (m/s)': [
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
                ],
                'Min vindhastighet (m/s)': [
                    f"{df['min_wind_speed'].mean():.1f}",
                    f"{df['min_wind_speed'].median():.1f}",
                    f"{df['min_wind_speed'].min():.1f}",
                    f"{df['min_wind_speed'].max():.1f}",
                    'N/A'
                ]
            })
            st.table(summary_df)

            # Collapsible sections for additional data
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

            with st.expander("Duggpunkt - Temperaturen hvor luften blir mettet og dugg eller frost kan dannes."):
                st.line_chart(df['dew_point_temperature'])
                st.write(f"Gjennomsnitt: {df['dew_point_temperature'].mean():.1f}°C")
                st.write(f"Minimum: {df['dew_point_temperature'].min():.1f}°C")
                st.write(f"Maksimum: {df['dew_point_temperature'].max():.1f}°C")

            # New expander for detailed wind data
            with st.expander("Detaljert vinddata"):
                st.subheader("Vindhastighetsprofil")
                wind_fig = go.Figure()
                wind_fig.add_trace(go.Scatter(x=df.index, y=df['wind_speed'], mode='lines', name='Gjennomsnittlig vindhastighet'))
                wind_fig.add_trace(go.Scatter(x=df.index, y=df['max_wind_speed'], mode='lines', name='Maks vindhastighet'))
                wind_fig.add_trace(go.Scatter(x=df.index, y=df['min_wind_speed'], mode='lines', name='Min vindhastighet'))
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

            # Display GPS activity data
            with st.expander("Siste GPS aktivitet"):
                if gps_data:
                    gps_df = pd.DataFrame(gps_data)
                    st.dataframe(gps_df)
                else:
                    st.write("Ingen GPS-aktivitet i den valgte perioden.")
            
            # Vis snøfokk-alarmer
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

            # Vis glatt vei / slush-alarmer
            with st.expander("Glatt vei / slush-alarmer"):
                st.write("Alarmene er basert på værdata og ikke direkte observasjoner.")
                st.write("Kriterier: Temperatur > 0°C, nedbør > 1.5 mm, snødybde ≥ 20 cm, og synkende snødybde.")
                slippery_road_alarms = df[df['slippery_road_alarm'] == 1]
                if not slippery_road_alarms.empty:
                    st.dataframe(slippery_road_alarms[['air_temperature', 'precipitation_amount', 'surface_snow_thickness']])
                    st.write(f"Totalt antall glatt vei / slush-alarmer: {len(slippery_road_alarms)}")
                else:
                    st.write("Ingen glatt vei / slush-alarmer i den valgte perioden.")

            # Move the CSV download button to the bottom
            st.write("") # Add some space
            st.write("") # Add more space
            csv_data = export_to_csv(df)
            st.download_button(
                label="Last ned data som CSV",
                data=csv_data,
                file_name="weather_data.csv",
                mime="text/csv"
            )

        else:
            logger.error("No data available")
            st.error("Kunne ikke hente værdata. Vennligst sjekk loggene for mer informasjon.")

    except Exception as e:
        logger.error(f"Feil ved henting eller behandling av data: {e}")
        st.error(f"Feil ved henting eller behandling av data: {e}")

if __name__ == "__main__":
    main()