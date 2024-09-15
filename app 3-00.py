import streamlit as st
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from statsmodels.nonparametric.smoothers_lowess import lowess
import logging
import plotly.graph_objects as go
import plotly.subplots as sp

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_gps_data():
    """
    Fetch and process GPS data from the specified URL.
    """
    logger.info("Fetching GPS data")
    try:
        url = "https://kart.irute.net/fjellbergsskardet_busses.json?_=1657373465172"
        response = requests.get(url)
        response.raise_for_status()
        gps_data = response.json()
        all_eq_dicts = gps_data['features']
        
        gps_entries = []
        for eq_dict in all_eq_dicts:
            date_str = eq_dict['properties']['Date']
            gps_entry = {
                'BILNR': eq_dict['properties']['BILNR'],
                'Date': datetime.strptime(date_str, '%H:%M:%S %d.%m.%Y').replace(tzinfo=ZoneInfo("Europe/Oslo"))
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

def validate_snow_depths(snow_depths):
    """
    Validate and clean snow depth data.
    """
    logger.info("Starting function: validate_snow_depths")
    snow_depths = np.array(snow_depths, dtype=float)
    snow_depths[snow_depths < 0] = np.nan
    if np.all(np.isnan(snow_depths)):
        return snow_depths
    season_median = np.nanmedian(snow_depths)
    season_std = np.nanstd(snow_depths)
    lower_bound = max(0, season_median - 3 * season_std)
    upper_bound = season_median + 3 * season_std
    snow_depths[(snow_depths < lower_bound) | (snow_depths > upper_bound)] = np.nan
    logger.info("Completed function: validate_snow_depths")
    return snow_depths

def smooth_snow_depths(snow_depths):
    """
    Apply LOWESS smoothing to snow depth data.
    """
    logger.info("Starting function: smooth_snow_depths")
    if np.all(np.isnan(snow_depths)):
        return snow_depths
    timestamps = np.arange(len(snow_depths))
    valid_indices = ~np.isnan(snow_depths)
    if np.sum(valid_indices) < 2:
        return snow_depths
    smoothed = lowess(snow_depths[valid_indices], timestamps[valid_indices], frac=0.1, it=0)
    result = np.full_like(snow_depths, np.nan)
    result[valid_indices] = smoothed[:, 1]
    logger.info("Completed function: smooth_snow_depths")
    return result

def handle_missing_data(timestamps, data, method='time'):
    """
    Handle missing data using specified interpolation method.
    """
    logger.info(f"Starting function: handle_missing_data with method {method}")
    data_series = pd.Series(data, index=timestamps)
    interpolated = data_series.interpolate(method=method)
    logger.info("Completed function: handle_missing_data")
    return interpolated.to_numpy()

@st.cache_data(ttl=3600)
def fetch_and_process_data(client_id, date_start, date_end):
    """
    Fetch and process weather data from the API.
    """
    logger.info("Starting function: fetch_and_process_data")
    try:
        url = "https://frost.met.no/observations/v0.jsonld"
        params = {
            "sources": "SN46220",
            "elements": "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),wind_speed,surface_temperature,relative_humidity,dew_point_temperature",
            "timeresolutions": "PT1H",
            "referencetime": f"{date_start}/{date_end}"
        }
        logger.info(f"Sending request with params: {params}")
        response = requests.get(url, params=params, auth=(client_id, ""))
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
                'temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'air_temperature'), np.nan),
                'snow_depth': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_snow_thickness'), np.nan),
                'precipitation': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'sum(precipitation_amount PT1H)'), np.nan),
                'wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'wind_speed'), np.nan),
                'surface_temperature': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_temperature'), np.nan),
                'relative_humidity': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'relative_humidity'), np.nan),
                'dew_point': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'dew_point_temperature'), np.nan)
            }
            for item in data.get('data', [])
        ]).set_index('timestamp')

        df.index = pd.to_datetime(df.index).tz_localize(ZoneInfo("Europe/Oslo"), nonexistent='shift_forward', ambiguous='NaT')

        for column in df.columns:
            df[column] = pd.to_numeric(df[column], errors='coerce')
            df[column] = handle_missing_data(df.index, df[column], method='time')

        snow_depths = validate_snow_depths(df['snow_depth'].to_numpy())
        smoothed_snow_depths = smooth_snow_depths(snow_depths)

        confidence_intervals = (
            smoothed_snow_depths - 1.96 * np.nanstd(snow_depths),
            smoothed_snow_depths + 1.96 * np.nanstd(snow_depths)
        )
        missing_periods = identify_missing_periods(df.index, snow_depths)
        snow_precipitations = calculate_snow_precipitations(df['temperature'].to_numpy(), df['precipitation'].to_numpy(), snow_depths)

        alarms = snow_drift_alarm(df.index, df['wind_speed'].to_numpy(), df['precipitation'].to_numpy(), snow_depths, df['temperature'].to_numpy())
        slippery_road_alarms = identify_slippery_roads(df.index, df['temperature'].to_numpy(), df['precipitation'].to_numpy(), snow_depths)

        logger.info("Completed function: fetch_and_process_data")
        return {
            'timestamps': df.index,
            'temperatures': df['temperature'].to_numpy(),
            'precipitations': df['precipitation'].to_numpy(),
            'snow_depths': snow_depths,
            'snow_precipitations': snow_precipitations,
            'wind_speeds': df['wind_speed'].to_numpy(),
            'surface_temperatures': df['surface_temperature'].to_numpy(),
            'relative_humidities': df['relative_humidity'].to_numpy(),
            'dew_points': df['dew_point'].to_numpy(),
            'smoothed_snow_depths': smoothed_snow_depths,
            'confidence_intervals': confidence_intervals,
            'missing_periods': missing_periods,
            'alarms': alarms,
            'slippery_road_alarms': slippery_road_alarms
        }

    except Exception as e:
        logger.error(f"Data processing error: {e}")
        return None

def identify_missing_periods(timestamps, snow_depths):
    """
    Identify periods of missing data in snow depth measurements.
    """
    logger.info("Starting function: identify_missing_periods")
    missing_periods = []
    nan_indices = np.where(np.isnan(snow_depths))[0]
    if len(nan_indices) > 0:
        current_period = [timestamps[nan_indices[0]], timestamps[nan_indices[0]]]
        for idx in nan_indices[1:]:
            if np.abs(timestamps[idx] - current_period[1]) <= np.timedelta64(1, 'h'):
                current_period[1] = timestamps[idx]
            else:
                missing_periods.append(current_period)
                current_period = [timestamps[idx], timestamps[idx]]
        missing_periods.append(current_period)
    logger.info("Completed function: identify_missing_periods")
    return missing_periods

def calculate_snow_precipitations(temperatures, precipitations, snow_depths):
    """
    Calculate snow precipitation based on temperature and precipitation data.
    """
    logger.info("Starting function: calculate_snow_precipitations")
    condition1 = (temperatures <= 1.5) & (np.roll(snow_depths, 1) < snow_depths)
    condition2 = (temperatures <= 0) & (precipitations > 0)
    snow_precipitations = np.where(condition1 | condition2, precipitations, 0)
    logger.info("Completed function: calculate_snow_precipitations")
    return snow_precipitations

def snow_drift_alarm(timestamps, wind_speeds, precipitations, snow_depths, temperatures):
    """
    Identify periods of potential snow drift based on weather conditions.
    """
    logger.info("Starting function: snow_drift_alarm")
    condition1 = (wind_speeds > 6) & (precipitations < 0.1) & (np.abs(np.diff(snow_depths, prepend=snow_depths[0])) >= 1.0) & (temperatures <= -1.0)
    condition2 = (wind_speeds > 6) & (precipitations >= 0.1) & (np.diff(snow_depths, prepend=snow_depths[0]) <= -0.5) & (temperatures <= -1)
    alarm_indices = np.where(condition1 | condition2)[0]
    alarms = timestamps[alarm_indices]
    logger.info("Completed function: snow_drift_alarm")
    return alarms

def identify_slippery_roads(timestamps, temperatures, precipitations, snow_depths):
    """
    Identify periods of potential slippery road conditions.
    """
    logger.info("Starting function: identify_slippery_roads")
    condition = (temperatures > 0) & (precipitations > 0.5) & (snow_depths >= 20) & (np.diff(snow_depths, prepend=snow_depths[0]) < 0)
    alarm_indices = np.where(condition)[0]
    alarms = timestamps[alarm_indices]
    logger.info("Completed function: identify_slippery_roads")
    return alarms

def get_date_range(choice):
    """
    Get date range based on user choice.
    """
    logger.info(f"Starting function: get_date_range with choice {choice}")
    now = datetime.now(ZoneInfo("Europe/Oslo")).replace(minute=0, second=0, microsecond=0)
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

def create_interactive_graph(weather_data):
    """
    Create an interactive graph using Plotly with separate subplots for each selected element.
    """
    df = pd.DataFrame({
        'Timestamp': weather_data['timestamps'],
        'Temperatur': weather_data['temperatures'],
        'Nedbør': weather_data['precipitations'],
        'Snødybde': weather_data['snow_depths'],
        'Vindhastighet': weather_data['wind_speeds'],
        'Overflatetemperatur': weather_data['surface_temperatures'],
        'Luftfuktighet': weather_data['relative_humidities'],
        'Duggpunkt': weather_data['dew_points']
    })
    df.set_index('Timestamp', inplace=True)

    st.sidebar.header("Velg værdata å vise")
    selected_elements = st.sidebar.multiselect(
        "Velg elementer",
        options=df.columns.tolist(),
        default=['Temperatur', 'Nedbør', 'Snødybde', 'Vindhastighet']
    )

    if not selected_elements:
        st.warning("Vennligst velg minst ett element å vise.")
        return

    fig = sp.make_subplots(rows=len(selected_elements), cols=1, 
                           shared_xaxes=True, 
                           vertical_spacing=0.05,
                           subplot_titles=selected_elements)

    for i, element in enumerate(selected_elements, start=1):
        if element == 'Nedbør':
            fig.add_trace(go.Bar(x=df.index, y=df[element], name=element), row=i, col=1)
        else:
            fig.add_trace(go.Scatter(x=df.index, y=df[element], mode='lines', name=element), row=i, col=1)
        
        fig.update_yaxes(title_text=element, row=i, col=1)

    fig.update_layout(
        height=300 * len(selected_elements),
        title="Værdata for valgte elementer",
        showlegend=False,
        hovermode="x unified"
    )
    
    fig.update_xaxes(title_text="Tidspunkt", row=len(selected_elements), col=1)

    st.plotly_chart(fig, use_container_width=True)

    st.write("""
    **Forklaring:**
    - **Temperatur**: Lufttemperatur målt i °C.
    - **Nedbør**: Mengde nedbør målt i mm per time.
    - **Snødybde**: Tykkelse på snølaget målt i cm.
    - **Vindhastighet**: Vindens hastighet målt i m/s.
    - **Overflatetemperatur**: Temperaturen på bakken målt i °C.
    - **Luftfuktighet**: Relativ luftfuktighet målt i %.
    - **Duggpunkt**: Temperaturen hvor luftfuktigheten kondenserer, målt i °C.
    """)

def main():
    """
    Main function to run the Streamlit app.
    """
    st.title("Værdata for Gullingen")

    period = st.selectbox(
        "Velg en periode:",
        ["Siste 24 timer", "Siste 7 dager", "Siste 12 timer", "Siste 4 timer", "Siden sist fredag", "Siden sist søndag", "Egendefinert periode", "Siste GPS-aktivitet til nå"]
    )

    client_id = st.secrets["api_keys"]["client_id"]

    if period == "Egendefinert periode":
        col1, col2 = st.columns(2)
        with col1:
            date_start = st.date_input("Startdato", datetime.now(ZoneInfo("Europe/Oslo")) - timedelta(days=7))
        with col2:
            date_end = st.date_input("Sluttdato", datetime.now(ZoneInfo("Europe/Oslo")))

        if date_end <= date_start:
            st.error("Sluttdatoen må være etter startdatoen.")
            return

        date_start_isoformat = datetime.combine(date_start, datetime.min.time()).replace(tzinfo=ZoneInfo("Europe/Oslo")).isoformat()
        date_end_isoformat = datetime.combine(date_end, datetime.min.time()).replace(tzinfo=ZoneInfo("Europe/Oslo")).isoformat()
    elif period == "Siste GPS-aktivitet til nå":
        gps_data = fetch_gps_data()
        if gps_data:
            last_gps_activity = max(gps_data, key=lambda x: x['Date'])
            date_start_isoformat = last_gps_activity['Date'].isoformat()
            date_end_isoformat = datetime.now(ZoneInfo("Europe/Oslo")).isoformat()
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
        
        if weather_data:
            create_interactive_graph(weather_data)

            st.subheader("Oppsummering av data")
            summary_df = pd.DataFrame({
                'Statistikk': ['Gjennomsnitt', 'Median', 'Minimum', 'Maksimum', 'Total'],
                'Temperatur (°C)': [
                    f"{np.nanmean(weather_data['temperatures']):.1f}",
                    f"{np.nanmedian(weather_data['temperatures']):.1f}",
                    f"{np.nanmin(weather_data['temperatures']):.1f}",
                    f"{np.nanmax(weather_data['temperatures']):.1f}",
                    'N/A'
                ],
                'Nedbør (mm)': [
                    f"{np.nanmean(weather_data['precipitations']):.1f}",
                    f"{np.nanmedian(weather_data['precipitations']):.1f}",
                    f"{np.nanmin(weather_data['precipitations']):.1f}",
                    f"{np.nanmax(weather_data['precipitations']):.1f}",
                    f"{np.nansum(weather_data['precipitations']):.1f}"
                ],
                'Snødybde (cm)': [
                    f"{np.nanmean(weather_data['snow_depths']):.1f}",
                    f"{np.nanmedian(weather_data['snow_depths']):.1f}",
                    f"{np.nanmin(weather_data['snow_depths']):.1f}",
                    f"{np.nanmax(weather_data['snow_depths']):.1f}",
                    'N/A'
                ],
                'Vindhastighet (m/s)': [
                    f"{np.nanmean(weather_data['wind_speeds']):.1f}",
                    f"{np.nanmedian(weather_data['wind_speeds']):.1f}",
                    f"{np.nanmin(weather_data['wind_speeds']):.1f}",
                    f"{np.nanmax(weather_data['wind_speeds']):.1f}",
                    'N/A'
                ]
            })
            st.table(summary_df)

            with st.expander("GPS-aktivitet"):
                if gps_data:
                    st.dataframe(pd.DataFrame(gps_data))
                else:
                    st.write("Ingen GPS-aktivitet i den valgte perioden.")
            
            with st.expander("Snøfokk-alarmer"):
                st.write("Alarmene er basert på værdata og ikke direkte observasjoner")
                st.write("Kriterier: Vind > 6 m/s, temperatur ≤ -1°C, minst 6 cm akkumulert løssnø, og ENTEN nedbør < 1.0 mm og endring i snødybde ≥ 1.0 cm ELLER nedbør ≥ 0.1 mm og minking i snødybde ≥ 0.5 cm.")
                if weather_data['alarms']:
                    alarm_data = []
                    for alarm in weather_data['alarms']:
                        alarm_index = np.where(weather_data['timestamps'] == alarm)[0][0]
                        if alarm_index > 0:
                            snow_depth_change = weather_data['snow_depths'][alarm_index] - weather_data['snow_depths'][alarm_index - 1]
                            snow_depth_change = round(snow_depth_change, 2)
                        else:
                            snow_depth_change = 'N/A'

                        alarm_data.append({
                            'Tidspunkt': alarm,
                            'Temperatur (°C)': weather_data['temperatures'][alarm_index],
                            'Vindhastighet (m/s)': weather_data['wind_speeds'][alarm_index],
                            'Snødybde (cm)': weather_data['snow_depths'][alarm_index],
                            'Nedbør (mm)': weather_data['precipitations'][alarm_index],
                            'Endring i snødybde (cm)': snow_depth_change
                        })

                    st.dataframe(pd.DataFrame(alarm_data))
                else:
                    st.write("Ingen snøfokk-alarmer i den valgte perioden.")

            with st.expander("Glatt vei / slush-alarmer"):
                st.write("Kriterier: Temperatur > 0°C, nedbør > 1.5 mm, snødybde ≥ 20 cm, og synkende snødybde.")
                st.write("Alarmene er basert på værdata og ikke direkte observasjoner.")
                if weather_data['slippery_road_alarms']:
                    slippery_road_data = []
                    for alarm in weather_data['slippery_road_alarms']:
                        alarm_index = np.where(weather_data['timestamps'] == alarm)[0][0]
                        if alarm_index > 0:
                            snow_depth_change = weather_data['snow_depths'][alarm_index] - weather_data['snow_depths'][alarm_index - 1]
                            snow_depth_change = round(snow_depth_change, 2)
                        else:
                            snow_depth_change = 'N/A'

                        slippery_road_data.append({
                            'Tidspunkt': alarm,
                            'Temperatur (°C)': weather_data['temperatures'][alarm_index],
                            'Nedbør (mm)': weather_data['precipitations'][alarm_index],
                            'Snødybde (cm)': weather_data['snow_depths'][alarm_index],
                            'Endring i snødybde (cm)': snow_depth_change
                        })

                    st.dataframe(pd.DataFrame(slippery_road_data))
                else:
                    st.write("Ingen glatt vei / slush-alarmer i den valgte perioden.")

        else:
            st.error("Kunne ikke hente værdata. Vennligst sjekk loggene for mer informasjon.")

    except Exception as e:
        logger.error(f"Feil ved henting eller behandling av data: {e}")
        st.error(f"Feil ved henting eller behandling av data: {e}")

if __name__ == "__main__":
    main()