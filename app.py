import io
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from statsmodels.nonparametric.smoothers_lowess import lowess

import plotly.graph_objects as go
from plotly.subplots import make_subplots

import streamlit as st
from streamlit_echarts import st_echarts

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
STATION_ID = "SN46220"
API_URL = "https://frost.met.no/observations/v0.jsonld"
ELEMENTS = "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),max_wind_speed(wind_from_direction PT1H),max(wind_speed_of_gust PT1H),min(wind_speed P1M),wind_speed,surface_temperature,relative_humidity,dew_point_temperature"
TIME_RESOLUTION = "PT1H"
GPS_URL = "https://kart.irute.net/fjellbergsskardet_busses.json?_=1657373465172"
TZ = ZoneInfo("Europe/Oslo")

# Database functions
def get_db_connection(db_name):
    return sqlite3.connect(f'{db_name}.db')

def get_feedback_connection():
    return get_db_connection('feedback')

def get_tunbroyting_connection():
    return get_db_connection('tunbroyting')

def get_stroing_connection():
    return get_db_connection('stroing')

def create_all_tables():
    # Create feedback table
    with get_feedback_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS feedback
                     (id INTEGER PRIMARY KEY,
                      type TEXT,
                      datetime TEXT,
                      comment TEXT,
                      innsender TEXT)''')
        logger.info("Feedback table created or already exists.")

    # Create tunbroyting table
    with get_tunbroyting_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger
                     (id INTEGER PRIMARY KEY,
                      bruker TEXT,
                      ankomst_dato TEXT,
                      ankomst_tid TEXT,
                      avreise_dato TEXT,
                      avreise_tid TEXT,
                      abonnement_type TEXT)''')
        logger.info("Tunbrøyting bestillinger table created or already exists.")

    # Create stroing table
    with get_stroing_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS stroing_bestillinger
                     (id INTEGER PRIMARY KEY,
                      bruker TEXT,
                      bestillings_dato TEXT,
                      onske_dato TEXT,
                      kommentar TEXT,
                      status TEXT)''')
        logger.info("Strøing bestillinger table created or already exists.")

    # Create login_history table
    with get_db_connection('login_history') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS login_history
                     (id INTEGER PRIMARY KEY,
                      username TEXT,
                      login_time TEXT)''')
        logger.info("Login history table created or already exists.")
    
    logger.info("All tables have been created or verified.")

# Authentication functions
def find_username_by_code(code):
    for username, user_code in st.secrets["auth_codes"]["users"].items():
        if user_code.lower().strip() == code.lower().strip():
            return username.strip()
    return None

def authenticate_user(code):
    users = st.secrets["auth_codes"]["users"]
    for username, user_code in users.items():
        if user_code.lower().strip() == code.lower().strip():
            log_login(username)  # Logg påloggingen
            return username
    return None

def get_login_history(start_date, end_date):
    with get_db_connection('login_history') as conn:
        query = "SELECT * FROM login_history WHERE login_time BETWEEN ? AND ? ORDER BY login_time DESC"
        df = pd.read_sql_query(query, conn, params=(start_date.isoformat(), end_date.isoformat()))
    df['login_time'] = pd.to_datetime(df['login_time']).dt.tz_convert(TZ)
    return df

# Weather data functions
def fetch_gps_data():
    try:
        response = requests.get(GPS_URL)
        response.raise_for_status()
        gps_data = response.json()
        all_eq_dicts = gps_data.get('features', [])
        
        gps_entries = []
        for eq_dict in all_eq_dicts:
            date_str = eq_dict['properties'].get('Date')
            if date_str:
                try:
                    gps_entry = {
                        'BILNR': eq_dict['properties'].get('BILNR'),
                        'Date': datetime.strptime(date_str, '%H:%M:%S %d.%m.%Y').replace(tzinfo=TZ)
                    }
                    gps_entries.append(gps_entry)
                except ValueError as e:
                    logger.error(f"Date parsing error: {e}")
        
        return gps_entries
    except requests.RequestException as e:
        logger.error(f"Error fetching GPS data: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error in fetch_gps_data: {e}")
        return []

def validate_data(data):
    data = np.array(data, dtype=float)
    if np.all(np.isnan(data)):
        return data
    median = np.nanmedian(data)
    std = np.nanstd(data)
    lower_bound = median - 5 * std
    upper_bound = median + 5 * std
    data[(data < lower_bound) | (data > upper_bound)] = np.nan
    return data

def smooth_data(data):
    if np.all(np.isnan(data)):
        return data
    timestamps = np.arange(len(data))
    valid_indices = ~np.isnan(data)
    if np.sum(valid_indices) < 2:
        return data
    smoothed = lowess(data[valid_indices], timestamps[valid_indices], frac=0.1, it=0)
    result = np.full_like(data, np.nan)
    result[valid_indices] = smoothed[:, 1]
    return result

def handle_missing_data(timestamps, data, method='time'):
    data_series = pd.Series(data, index=timestamps)
    if method == 'time':
        interpolated = data_series.interpolate(method='time')
    elif method == 'linear':
        interpolated = data_series.interpolate(method='linear')
    else:
        interpolated = data_series.interpolate(method='nearest')
    return interpolated.to_numpy()

def fetch_and_process_data(client_id, date_start, date_end):
    try:
        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start}/{date_end}"
        }
        response = requests.get(API_URL, params=params, auth=(client_id, ""))
        response.raise_for_status()
        data = response.json()

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
        logger.error(f"Request error: {e}")
        return None
    except Exception as e:
        logger.error(f"Data processing error: {e}")
        return None

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

# Feedback functions
def save_feedback(feedback_type, datetime_str, comment, innsender, conn=None):
    try:
        if conn is None:
            conn = get_feedback_connection()
        with conn:
            c = conn.cursor()
            c.execute("INSERT INTO feedback (type, datetime, comment, innsender) VALUES (?, ?, ?, ?)",
                      (feedback_type, datetime_str, comment, innsender))
        logger.info(f"Feedback saved successfully: {feedback_type}, {datetime_str}, {innsender}")
        return True
    except Exception as e:
        logger.error(f"Error saving feedback: {str(e)}", exc_info=True)
        return False

def get_feedback(start_date, end_date):
    start_date = pd.Timestamp(start_date)
    end_date = pd.Timestamp(end_date)

    with get_feedback_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM feedback WHERE datetime BETWEEN ? AND ? ORDER BY datetime DESC",
                  (start_date.isoformat(), end_date.isoformat()))
        feedback = c.fetchall()
    
    df = pd.DataFrame(feedback, columns=['id', 'type', 'datetime', 'comment', 'innsender'])
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True).dt.tz_convert(TZ)
    df = df.dropna(subset=['datetime'])
    
    return df

def delete_feedback(feedback_id):
    with get_feedback_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
        conn.commit()
    logger.info(f"Deleted feedback with id: {feedback_id}")

# Tunbrøyting functions
def lagre_bestilling(username, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type, conn=None):
    if conn is None:
        conn = get_tunbroyting_connection()
    with conn:
        c = conn.cursor()
        c.execute('''INSERT INTO tunbroyting_bestillinger 
                     (bruker, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type)
                     VALUES (?, ?, ?, ?, ?, ?)''', 
                  (username, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, abonnement_type))
    logger.info(f"Ny tunbrøyting bestilling lagret for bruker: {username}")

def hent_bestillinger():
    with get_tunbroyting_connection() as conn:
        return pd.read_sql_query("SELECT * FROM tunbroyting_bestillinger", conn)

def hent_bruker_bestillinger(username):
    with get_tunbroyting_connection() as conn:
        query = """
        SELECT * FROM tunbroyting_bestillinger 
        WHERE bruker = ? 
        ORDER BY ankomst_dato DESC, ankomst_tid DESC
        """
        df = pd.read_sql_query(query, conn, params=(username,))
    return df

# Strøing functions
def lagre_stroing_bestilling(username, onske_dato, kommentar, conn=None):
    if conn is None:
        conn = get_stroing_connection()
    with conn:
        c = conn.cursor()
        bestillings_dato = datetime.now(TZ).isoformat()
        c.execute('''INSERT INTO stroing_bestillinger 
                     (bruker, bestillings_dato, onske_dato, kommentar, status)
                     VALUES (?, ?, ?, ?, ?)''', 
                  (username, bestillings_dato, onske_dato, kommentar, "Pending"))
    logger.info(f"Ny strøing bestilling lagret for bruker: {username}")

def hent_stroing_bestillinger():
    with get_stroing_connection() as conn:
        return pd.read_sql_query("SELECT * FROM stroing_bestillinger", conn)

def hent_bruker_stroing_bestillinger(username):
    with get_stroing_connection() as conn:
        query = """
        SELECT * FROM stroing_bestillinger 
        WHERE bruker = ? 
        ORDER BY bestillings_dato DESC
        """
        df = pd.read_sql_query(query, conn, params=(username,))
    return df

def update_stroing_status(bestilling_id, new_status, conn=None):
    if conn is None:
        conn = get_stroing_connection()
    with conn:
        c = conn.cursor()
        c.execute("UPDATE stroing_bestillinger SET status = ? WHERE id = ?", (new_status, bestilling_id))
    logger.info(f"Oppdatert status for bestilling {bestilling_id} til {new_status}")

# Helper functions
def categorize_direction(degree):
    if pd.isna(degree):
        return 'Ukjent'
    degree = float(degree)
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
    for direction, (min_deg, max_deg) in wind_directions.items():
        if min_deg <= degree < max_deg or (direction == 'N' and (degree >= 337.5 or degree < 22.5)):
            return direction
    return 'Ukjent'

def neste_fredag():
    today = datetime.now(TZ).date()
    days_ahead = 4 - today.weekday()  # Fredag er 4
    if days_ahead <= 0:  # Hvis det er fredag eller senere, gå til neste uke
        days_ahead += 7
    return today + timedelta(days=days_ahead)

# Streamlit app functions
def login_page():
    st.title("Logg inn")
    code = st.text_input("Skriv inn kode", type="password")
    if st.button("Logg inn"):
        username = authenticate_user(code)
        if username:
            st.session_state.authenticated = True
            st.session_state.username = username
            st.success(f"Innlogget som {username}")
            st.rerun()
        else:
            st.error("Ugyldig kode")

def log_login(username):
    with get_db_connection('login_history') as conn:
        c = conn.cursor()
        login_time = datetime.now(TZ).isoformat()
        c.execute("INSERT INTO login_history (username, login_time) VALUES (?, ?)", (username, login_time))
        conn.commit()
    logger.info(f"Logged login for user: {username}")

def display_weather_data():
    st.title("Værdata for Gullingen")

    period_options = [
        "Siste 24 timer", "Siste 7 dager", "Siste 12 timer", "Siste 4 timer", 
        "Siden sist fredag", "Siden sist søndag", "Egendefinert periode", 
        "Siste GPS-aktivitet til nå"
    ]

    period = st.selectbox("Velg en periode:", options=period_options, key="weather_period_select")

    client_id = st.secrets["api_keys"]["client_id"]

    if period == "Egendefinert periode":
        col1, col2 = st.columns(2)
        with col1:
            date_start = st.date_input("Startdato", datetime.now(TZ) - timedelta(days=7), key="custom_start_date")
        with col2:
            date_end = st.date_input("Sluttdato", datetime.now(TZ), key="custom_end_date")

        if date_end <= date_start:
            st.error("Sluttdatoen må være etter startdatoen.")
            return

        date_start_isoformat = datetime.combine(date_start, datetime.min.time()).replace(tzinfo=TZ).isoformat()
        date_end_isoformat = datetime.combine(date_end, datetime.max.time()).replace(tzinfo=TZ).isoformat()
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
            st.error(f"Ugyldig periodevalg: {period}")
            return

    st.write(f"Henter data fra {date_start_isoformat} til {date_end_isoformat}")

    try:
        with st.spinner('Henter og behandler data...'):
            weather_data = fetch_and_process_data(client_id, date_start_isoformat, date_end_isoformat)
            gps_data = fetch_gps_data() if period != "Siste GPS-aktivitet til nå" else gps_data
            feedback_data = get_feedback(date_start_isoformat, date_end_isoformat)

        if weather_data and 'df' in weather_data:
            df = weather_data['df']
            st.write(f"Antall datapunkter: {len(df)}")
            st.write(f"Manglende datapunkter: {df.isna().sum().sum()}")
            st.write(f"Antall snøfokk-alarmer: {df['snow_drift_alarm'].sum()}")
            st.write(f"Antall glatt vei / slush-alarmer: {df['slippery_road_alarm'].sum()}")
            
            # Create and display the graph
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

            st.subheader("Rapporterte føreforhold")
    
            if not feedback_data.empty:
                feedback_data = feedback_data.sort_values('datetime', ascending=False)
                
                icons = {
                    "Glatt vei": "🧊",
                    "Slush": "🌊",
                    "Gjenblåst vei": "💨",
                    "Annet": "❓"
                }
                
                for _, row in feedback_data.iterrows():
                    icon = icons.get(row['type'], "❓")
                    with st.expander(f"{icon} {row['type']} - {row['datetime'].strftime('%Y-%m-%d %H:%M')}"):
                        st.write(f"**Rapportert av:** {row['innsender']}")
                        st.write(f"**Kommentar:** {row['comment']}")
                
                report_summary = feedback_data['type'].value_counts()
                st.subheader("Sammendrag av rapporter")
                chart_options = {
                    "tooltip": {"trigger": "item"},
                    "legend": {"top": "5%", "left": "center"},
                    "series": [{
                        "name": "Rapporttyper",
                        "type": "pie",
                        "radius": ["40%", "70%"],
                        "avoidLabelOverlap": False,
                        "itemStyle": {
                            "borderRadius": 10,
                            "borderColor": "#fff",
                            "borderWidth": 2
                        },
                        "label": {"show": False, "position": "center"},
                        "emphasis": {
                            "label": {"show": True, "fontSize": "40", "fontWeight": "bold"}
                        },
                        "labelLine": {"show": False},
                        "data": [{"value": v, "name": k} for k, v in report_summary.items()]
                    }]
                }
                st_echarts(options=chart_options, height="400px")
            else:
                st.info("Ingen rapporterte føreforhold i valgt periode.")

            # Display GPS activity data
            with st.expander("Siste GPS aktivitet"):
                if gps_data:
                    gps_df = pd.DataFrame(gps_data)
                    st.dataframe(gps_df)
                else:
                    st.write("Ingen GPS-aktivitet i den valgte perioden.")
            
            # Display snow drift alarms
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

            # Display slippery road alarms
            with st.expander("Glatt vei / slush-alarmer"):
                st.write("Alarmene er basert på værdata og ikke direkte observasjoner.")
                st.write("Kriterier: Temperatur > 0°C, nedbør > 1.5 mm, snødybde ≥ 20 cm, og synkende snødybde.")
                slippery_road_alarms = df[df['slippery_road_alarm'] == 1]
                if not slippery_road_alarms.empty:
                    st.dataframe(slippery_road_alarms[['air_temperature', 'precipitation_amount', 'surface_snow_thickness']])
                    st.write(f"Totalt antall glatt vei / slush-alarmer: {len(slippery_road_alarms)}")
                else:
                    st.write("Ingen glatt vei / slush-alarmer i den valgte perioden.")

            # Kollapsible menyer for ekstra data
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
            
            # CSV download button
            st.download_button(
                label="Last ned data som CSV",
                data=df.to_csv(index=True).encode('utf-8'),
                file_name="weather_data.csv",
                mime="text/csv",
            )

        else:
            logger.error("No data available")
            st.error("Kunne ikke hente værdata. Vennligst sjekk loggene for mer informasjon.")

    except Exception as e:
        logger.error(f"Feil ved henting eller behandling av data: {e}")
        st.error(f"Feil ved henting eller behandling av data: {e}")

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

    # Alarmer
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
    
    total_counts = sum(values)
    percentages = [count / total_counts * 100 for count in values]
    
    for direction, percentage in zip(directions, percentages):
        direction_data = df[df['wind_direction_category'] == direction]
        fig.add_trace(go.Scatter(
            x=direction_data.index, 
            y=direction_data['wind_from_direction'],
            mode='markers',
            name=f"{direction} ({percentage:.1f}%)",
            marker=dict(size=5, symbol='triangle-up')
        ), row=7, col=1)

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
        margin=dict(l=50, r=50, t=100, b=100)
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

def feedback_page():
    st.title("Rapporter vær- og føreforhold")

    feedback_type = st.selectbox("Type observasjon", ["Glatt vei", "Slush", "Gjenblåst vei", "Annet"], key="feedback_type_select")
    
    observation_date = st.date_input("Dato for observasjon", key="observation_date")
    observation_time = st.time_input("Tidspunkt for observasjon", key="observation_time")

    observation_datetime = datetime.combine(observation_date, observation_time)
    observation_datetime = observation_datetime.replace(tzinfo=TZ)
    
    comment = st.text_area("Kommentar")

    if st.button("Send rapport"):
        if not comment:
            st.error("Vennligst fyll ut kommentarfeltet.")
        else:
            try:
                save_feedback(feedback_type, observation_datetime.isoformat(), comment, st.session_state.username)
                st.success("Rapport sendt inn. Takk for ditt bidrag!")
            except Exception as e:
                st.error("Det oppstod en feil ved lagring av rapporten. Vennligst prøv igjen senere.")
                logger.error(f"Error saving feedback: {str(e)}")

    # Display recent feedback
    st.subheader("Nylige rapporter")
    display_recent_feedback()

def bestill_tunbroyting():
    st.title("Bestill Tunbrøyting")

    abonnement_type = st.radio("Velg abonnement type", ["Årsabonnement", "Ukentlig"], key="abonnement_type_radio")

    col1, col2 = st.columns(2)
    
    with col1:
        if abonnement_type == "Ukentlig":
            ankomst_dato = neste_fredag()
            st.write(f"Ankomstdato (neste fredag): {ankomst_dato}")
        else:
            ankomst_dato = st.date_input("Velg ankomstdato", min_value=datetime.now(TZ).date())
        
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

    if st.button("Bestill Tunbrøyting"):
        lagre_bestilling(
            st.session_state.username,
            ankomst_dato.isoformat(), 
            ankomst_tid.isoformat(),
            avreise_dato.isoformat() if avreise_dato else None,
            avreise_tid.isoformat() if avreise_tid else None,
            abonnement_type
        )
        st.success("Bestilling av tunbrøyting er registrert!")

    st.subheader("Dine tidligere bestillinger")
    display_bookings(st.session_state.username)

def bestill_stroing():
    st.title("Bestill Strøing")
    
    onske_dato = st.date_input("Ønsket dato for strøing", min_value=datetime.now(TZ).date())
    kommentar = st.text_area("Kommentar eller spesielle instruksjoner")

    if st.button("Bestill Strøing"):
        lagre_stroing_bestilling(st.session_state.username, onske_dato.isoformat(), kommentar)
        st.success("Bestilling av strøing er registrert!")

    st.subheader("Dine tidligere strøing-bestillinger")
    display_stroing_bookings(st.session_state.username)

def admin_broytefirma_page():
    st.title("Administrer observasjoner, tunbrøyting og strøing")

    if st.session_state.username in ["Fjbs Drift", "199, Tungland"]:
        admin_menu()
    elif st.session_state.username == "Brøytefirma":
        vis_bestillinger()
        admin_stroing_page()
    else:
        st.error("Du har ikke tilgang til denne siden")

def admin_menu():
    admin_choice = st.radio("Velg funksjon", ["Håndter observasjoner", "Vis tunbestillinger", "Håndter strøing-bestillinger", "Last ned alle rapporter"], key="admin_menu_radio")

    if admin_choice == "Håndter observasjoner":
        handle_observations()
    elif admin_choice == "Vis tunbestillinger":
        vis_bestillinger()
    elif admin_choice == "Håndter strøing-bestillinger":
        admin_stroing_page()
    elif admin_choice == "Last ned alle rapporter":
        download_reports()

def handle_observations():
    st.subheader("Håndter observasjoner")
    
    start_date = pd.Timestamp('1900-01-01', tz=TZ)
    end_date = pd.Timestamp.now(tz=TZ)
    
    feedback_data = get_feedback(start_date.isoformat(), end_date.isoformat())

    if feedback_data.empty:
        st.write("Ingen observasjoner å vise.")
    else:
        feedback_data = feedback_data.sort_values(by=['datetime'], ascending=False)

        for _, row in feedback_data.iterrows():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**{row['datetime'].strftime('%Y-%m-%d %H:%M:%S %Z')}** - {row['type']}")
                st.write(f"Rapportert av: {row['innsender']}")
                st.write(f"Kommentar: {row['comment']}")
            with col2:
                if st.button("Slett", key=f"delete_{row['id']}"):
                    delete_feedback(row['id'])
                    st.success("Observasjon slettet.")
                    st.rerun()

            st.write("---")

def vis_bestillinger():
    st.subheader("Alle Tunbrøyting Bestillinger")
    
    bestillinger = hent_bestillinger()
    if bestillinger.empty:
        st.write("Ingen bestillinger å vise.")
    else:
        bestillinger['ankomst_dato'] = pd.to_datetime(bestillinger['ankomst_dato']).dt.strftime('%Y-%m-%d')
        bestillinger['ankomst_tid'] = pd.to_datetime(bestillinger['ankomst_tid']).dt.strftime('%H:%M')
        bestillinger['avreise_dato'] = pd.to_datetime(bestillinger['avreise_dato']).dt.strftime('%Y-%m-%d')
        bestillinger['avreise_tid'] = pd.to_datetime(bestillinger['avreise_tid']).dt.strftime('%H:%M')
        
        users = st.secrets["auth_codes"]["users"]
        bestillinger['Hytte'] = bestillinger['bruker'].apply(lambda x: next((k for k, v in users.items() if v == x), x))

        st.checkbox("Vis kun dagens bestillinger", key="vis_dagens_bestillinger")

        if st.session_state.vis_dagens_bestillinger:
            bestillinger = bestillinger.sort_values(by=['Hytte'], ascending=True)
        else:
            bestillinger = bestillinger.sort_values(by=['id'], ascending=False)

        st.dataframe(bestillinger)

    if st.session_state.username == "Fjbs Drift":
        st.subheader("Administrer bestillinger")

        for _, row in bestillinger.iterrows():
            if st.button(f"Slett bestilling {row['id']}"):
                slett_bestilling(row['id'])
                st.success(f"Bestilling {row['id']} slettet.")
                st.rerun()

def admin_stroing_page():
    st.title("Administrer Strøing-bestillinger")

    bestillinger = hent_stroing_bestillinger()
    if bestillinger.empty:
        st.write("Ingen strøing-bestillinger å vise.")
    else:
        bestillinger['bestillings_dato'] = pd.to_datetime(bestillinger['bestillings_dato']).dt.strftime('%Y-%m-%d %H:%M')
        bestillinger['onske_dato'] = pd.to_datetime(bestillinger['onske_dato']).dt.strftime('%Y-%m-%d')
        
        users = st.secrets["auth_codes"]["users"]
        bestillinger['Hytte'] = bestillinger['bruker'].apply(lambda x: next((k for k, v in users.items() if v == x), x))

        st.dataframe(bestillinger)

    if st.session_state.username in ["Fjbs Drift", "199, Tungland"]:
        st.subheader("Oppdater bestillingsstatus")
        for _, row in bestillinger.iterrows():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"Bestilling {row['id']} - {row['Hytte']}")
            with col2:
                new_status = st.selectbox(f"Status for bestilling {row['id']}", 
                                          ["Pending", "Completed", "Cancelled"], 
                                          index=["Pending", "Completed", "Cancelled"].index(row['status']),
                                          key=f"status_{row['id']}")
                if new_status != row['status']:
                    update_stroing_status(row['id'], new_status)
                    st.success(f"Status oppdatert for bestilling {row['id']}")
                    st.rerun()
                    
def download_reports():
    st.subheader("Last ned rapporter og påloggingshistorikk")
    
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=datetime(2020, 1, 1), min_value=datetime(2020, 1, 1), max_value=datetime.now(TZ))
    with col2:
        end_date = st.date_input("Til dato", value=datetime.now(TZ), min_value=datetime(2020, 1, 1), max_value=datetime.now(TZ))
    
    start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
    end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)
    
    all_reports = get_feedback(start_datetime.isoformat(), end_datetime.isoformat())
    login_history = get_login_history(start_datetime, end_datetime)
    
    if not all_reports.empty or not login_history.empty:
        # Prepare reports CSV
        if not all_reports.empty:
            all_reports['datetime'] = all_reports['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
            reports_csv = all_reports.to_csv(index=False)
        else:
            reports_csv = "Ingen rapporter for den valgte perioden."
        
        # Prepare login history CSV
        if not login_history.empty:
            login_history['login_time'] = login_history['login_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
            login_csv = login_history.to_csv(index=False)
        else:
            login_csv = "Ingen pålogginger for den valgte perioden."
        
        # Combine both CSVs
        combined_csv = f"Rapporter:\n{reports_csv}\n\nPåloggingshistorikk:\n{login_csv}"
        
        st.download_button(
            label="Last ned rapporter og påloggingshistorikk som CSV",
            data=combined_csv,
            file_name="rapporter_og_paalogginger.csv",
            mime="text/csv",
        )
        
        st.write("Forhåndsvisning av rapportdata:")
        if not all_reports.empty:
            st.dataframe(all_reports)
        else:
            st.info("Ingen rapporter å vise for den valgte perioden.")
        
        st.write("Forhåndsvisning av påloggingshistorikk:")
        if not login_history.empty:
            st.dataframe(login_history)
        else:
            st.info("Ingen pålogginger å vise for den valgte perioden.")
    else:
        st.info("Ingen data å laste ned for den valgte perioden.")

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
    previous_bookings = hent_bruker_stroing_bestillinger(username)
    
    if not previous_bookings.empty:
        for _, booking in previous_bookings.iterrows():
            with st.expander(f"Bestilling - {booking['bestillings_dato']}"):
                st.write(f"Bestilt: {booking['bestillings_dato']}")
                st.write(f"Ønsket dato: {booking['onske_dato']}")
                st.write(f"Kommentar: {booking['kommentar']}")
                st.write(f"Status: {booking['status']}")
    else:
        st.info("Du har ingen tidligere strøing-bestillinger.")

def display_recent_feedback():
    end_date = datetime.now(TZ)
    start_date = end_date - timedelta(days=7)
    recent_feedback = get_feedback(start_date.isoformat(), end_date.isoformat())
    
    if not recent_feedback.empty:
        recent_feedback = recent_feedback.sort_values('datetime', ascending=False)
        
        st.write(f"Viser {len(recent_feedback)} rapporter fra de siste 7 dagene:")
        
        for _, row in recent_feedback.iterrows():
            date_str = row['datetime'].strftime('%Y-%m-%d %H:%M %Z') if pd.notnull(row['datetime']) else 'Ukjent dato'
            st.write(f"**{date_str}** - {row['type']}")
            st.write(f"Rapportert av: {row['innsender']}")
            st.write(f"Kommentar: {row['comment']}")
            st.write("---")
    else:
        st.info("Ingen rapporterte føreforhold i de siste 7 dagene.")

def get_date_range(choice):
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
    return start_time.isoformat(), now.isoformat()

def slett_bestilling(bestilling_id):
    with get_tunbroyting_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM tunbroyting_bestillinger WHERE id = ?", (bestilling_id,))
        conn.commit()
    logger.info(f"Slettet bestilling med id: {bestilling_id}")

def main():
    st.set_page_config(layout="wide")
    
    create_all_tables()

    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = None

    if not st.session_state.authenticated:
        login_page()
    else:
        st.sidebar.success(f"Innlogget som {st.session_state.username}")
        
        menu = ["Værdata", "Rapporter føreforhold", "Bestill Tunbrøyting", "Bestill Strøing", "Admin/Brøytefirma"]
        choice = st.sidebar.radio("Meny", menu)

        if choice == "Værdata":
            display_weather_data()
        elif choice == "Rapporter føreforhold":
            feedback_page()
        elif choice == "Bestill Tunbrøyting":
            bestill_tunbroyting()
        elif choice == "Bestill Strøing":
            bestill_stroing()
        elif choice == "Admin/Brøytefirma":
            admin_broytefirma_page()

        if st.sidebar.button("Logg ut"):
            st.session_state.authenticated = False
            st.session_state.username = None
            st.rerun()

if __name__ == "__main__":
    main()