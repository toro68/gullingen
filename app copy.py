import streamlit as st
import requests
import seaborn as sns
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from statsmodels.nonparametric.smoothers_lowess import lowess
import io
import base64
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Constants ---
STATION_ID = "SN46220"
API_URL = "https://frost.met.no/observations/v0.jsonld"
ELEMENTS = "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),wind_speed,surface_temperature,relative_humidity,dew_point_temperature"
TIME_RESOLUTION = "PT1H"
GPS_URL = "https://kart.irute.net/fjellbergsskardet_busses.json?_=1657373465172"
TZ = ZoneInfo("Europe/Oslo")

# --- Helper Functions ---

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
    # Removed the -100 threshold
    if np.all(np.isnan(data)):
        return data
    median = np.nanmedian(data)
    std = np.nanstd(data)
    lower_bound = median - 5 * std  # Increased from 3 to 5
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


def create_downloadable_graph(df, start_time, end_time):
    logger.info("Starting function: create_downloadable_graph")
    
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, axes = plt.subplots(8, 1, figsize=(16, 40), sharex=True, facecolor='#F0F0F0')
    plt.rcParams.update({'font.size': 12, 'font.weight': 'bold'})

    fig.suptitle(f"Værdata for Gullingen værstasjon ({STATION_ID})\nPeriode: {start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}", 
                 fontsize=24, fontweight='bold', y=0.95)

    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#F7DC6F', '#C39BD3', '#7FB3D5']
    titles = ['Temperatur', 'Nedbør', 'Snødybde', 'Vindhastighet', 'Overflatetemperatur', 'Relativ luftfuktighet', 'Duggpunkt', 'Alarmer']
    ylabels = ['Temperatur (°C)', 'Nedbør (mm)', 'Snødybde (cm)', 'Vindhastighet (m/s)', 'Temperatur (°C)', 'Luftfuktighet (%)', 'Temperatur (°C)', '']

    for ax, title, ylabel, color, column in zip(axes, titles, ylabels, colors, 
                                                ['air_temperature', 'precipitation_amount', 'surface_snow_thickness', 'wind_speed', 
                                                 'surface_temperature', 'relative_humidity', 'dew_point_temperature', 'alarms']):
        ax.set_title(title, fontsize=18, fontweight='bold', color=color, 
                     bbox=dict(facecolor='white', edgecolor=color, boxstyle='round,pad=0.5'))
        ax.set_ylabel(ylabel, fontsize=14, fontweight='bold', color=color)
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        if column != 'alarms':
            if column == 'precipitation_amount':
                ax.bar(df.index, df[column], width=0.02, align='center', color=color, alpha=0.7)
            else:
                ax.plot(df.index, df[column], color=color, linewidth=2)
                ax.fill_between(df.index, df[column], alpha=0.3, color=color)
        else:
            snow_drift_alarms = df[df['snow_drift_alarm'] == 1].index
            slippery_road_alarms = df[df['slippery_road_alarm'] == 1].index
            ax.eventplot(snow_drift_alarms, lineoffsets=1, linelengths=0.5, linewidths=2, colors='red', label='Snøfokk-alarm')
            ax.eventplot(slippery_road_alarms, lineoffsets=0.5, linelengths=0.5, linewidths=2, colors='blue', label='Glatt vei / slush-alarm')
            ax.set_ylim(0, 1.5)
            ax.set_yticks([])
            ax.legend(loc='upper right', fancybox=True, shadow=True)

    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
        ax.tick_params(axis='x', rotation=45, labelsize=10)
        ax.tick_params(axis='y', labelsize=10)

    fig.tight_layout(rect=[0, 0.03, 1, 0.95])

    fig.text(0.01, 0.01, 'Snøfokk-alarm: Vind > 6 m/s, temp ≤ -1°C, lite nedbør, endring i snødybde\n'
                         'Glatt vei / slush-alarm: Temp > 0°C, nedbør > 1.5 mm, snødybde ≥ 20 cm, synkende snødybde', 
             ha='left', va='bottom', fontsize=10, style='italic')

    fig.text(0.99, 0.01, f'Data hentet: {datetime.now(TZ).strftime("%d.%m.%Y %H:%M")}\n'
                         f'Antall datapunkter: {len(df)}\nManglende datapunkter: {df.isna().sum().sum()}', 
             ha='right', va='bottom', fontsize=10, style='italic')

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
    img_buffer.seek(0)

    img_str = base64.b64encode(img_buffer.getvalue()).decode()
    plt.close(fig)

    logger.info(f"Image string length: {len(img_str)}")
    logger.info("Completed function: create_downloadable_graph")
    return img_str

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
    except requests.RequestException as e:
        logger.error(f"Request error: {e}")
        return None

    try:
        df = pd.DataFrame([
            {
                'timestamp': datetime.fromisoformat(item['referenceTime'].rstrip('Z')),
                'air_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'air_temperature'), np.nan),
                'precipitation_amount': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'sum(precipitation_amount PT1H)'), np.nan),
                'surface_snow_thickness': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_snow_thickness'), np.nan),
                'wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'wind_speed'), np.nan),
                'surface_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_temperature'), np.nan),
                'relative_humidity': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'relative_humidity'), np.nan),
                'dew_point_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'dew_point_temperature'), np.nan)
            }
            for item in data.get('data', [])
        ]).set_index('timestamp')

        logger.info(f"Created DataFrame with shape: {df.shape}")
        logger.info(f"DataFrame columns: {df.columns}")

        df.index = pd.to_datetime(df.index).tz_localize(TZ, nonexistent='shift_forward', ambiguous='NaT')

        for column in df.columns:
            df[column] = pd.to_numeric(df[column], errors='coerce')
            df[column] = validate_data(df[column])
            df[column] = handle_missing_data(df.index, df[column], method='time')
        
        # Calculate alarms using raw data
        df = calculate_snow_drift_alarms(df)
        df = calculate_slippery_road_alarms(df)
        
        # Then smooth the data for visualization
        for column in df.columns:
            if column not in ['snow_drift_alarm', 'slippery_road_alarm']:
                df[column] = smooth_data(df[column])

        img_str = create_downloadable_graph(df, pd.to_datetime(date_start), pd.to_datetime(date_end))

        logger.info("Completed function: fetch_and_process_data")
        return {'df': df, 'img_str': img_str}

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


# --- Main App ---

def main():
    st.set_page_config(layout="wide")
    st.title("Værdata for Gullingen")

    period = st.selectbox(
        "Velg en periode:",
        ["Siste 24 timer", "Siste 7 dager", "Siste 12 timer", "Siste 4 timer", "Siden sist fredag", "Siden sist søndag", "Egendefinert periode", "Siste GPS-aktivitet til nå"]
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
        
        if weather_data and 'img_str' in weather_data:
            logger.info(f"Attempting to display image. Image string length: {len(weather_data['img_str'])}")
            st.image(f"data:image/png;base64,{weather_data['img_str']}", use_column_width=True)
            st.download_button(label="Last ned grafen", data=base64.b64decode(weather_data['img_str']), file_name="weather_data.png", mime="image/png")

            df = weather_data['df']
            st.write(f"Antall datapunkter: {len(df)}")
            st.write(f"Manglende datapunkter: {df.isna().sum().sum()}")
            st.write(f"Antall snøfokk-alarmer: {df['snow_drift_alarm'].sum()}")
            st.write(f"Antall glatt vei / slush-alarmer: {df['slippery_road_alarm'].sum()}")
            
            # Display a sample of the data
            st.write("Sample of the data:")
            st.write(df.head())

            csv_data = export_to_csv(df)
            st.download_button(label="Last ned data som CSV", data=csv_data, file_name="weather_data.csv", mime="text/csv")

            # Display summary statistics
            st.subheader("Oppsummering av data")
            summary_df = pd.DataFrame({
                'Statistikk': ['Gjennomsnitt', 'Median', 'Minimum', 'Maksimum', 'Total'],
                'Temperatur (°C)': [
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
                ]
            })
            st.table(summary_df)

            # Collapsible sections for additional data
            with st.expander("Overflatetemperatur"):
                st.line_chart(df['surface_snow_thickness'])
                st.write(f"Gjennomsnitt: {df['surface_temperature'].mean():.1f}°C")
                st.write(f"Minimum: {df['surface_temperature'].min():.1f}°C")
                st.write(f"Maksimum: {df['surface_temperature'].max():.1f}°C")

            with st.expander("Relativ luftfuktighet"):
                st.line_chart(df['relative_humidity'])
                st.write(f"Gjennomsnitt: {df['relative_humidity'].mean():.1f}%")
                st.write(f"Minimum: {df['relative_humidity'].min():.1f}%")
                st.write(f"Maksimum: {df['relative_humidity'].max():.1f}%")

            with st.expander("Duggpunkt"):
                st.line_chart(df['dew_point_temperature'])
                st.write(f"Gjennomsnitt: {df['dew_point_temperature'].mean():.1f}°C")
                st.write(f"Minimum: {df['dew_point_temperature'].min():.1f}°C")
                st.write(f"Maksimum: {df['dew_point_temperature'].max():.1f}°C")

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


        else:
            logger.error("No image data available")
            st.error("Kunne ikke generere graf. Vennligst sjekk loggene for mer informasjon.")

    except Exception as e:
        logger.error(f"Feil ved henting eller behandling av data: {e}")
        st.error(f"Feil ved henting eller behandling av data: {e}")

if __name__ == "__main__":
    main()