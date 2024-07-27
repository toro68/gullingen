import streamlit as st
import requests
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

# Function to fetch GPS data
def fetch_gps_data():
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



# Function to validate snow depths
def validate_snow_depths(snow_depths):
    logger.info("Starting function: validate_snow_depths")
    snow_depths = np.array(snow_depths)
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

# Function to smooth snow depths
def smooth_snow_depths(snow_depths):
    logger.info("Starting function: smooth_snow_depths")
    if np.all(np.isnan(snow_depths)):
        return snow_depths
    timestamps = np.arange(len(snow_depths))
    valid_indices = ~np.isnan(snow_depths)
    if np.sum(valid_indices) < 2:
        return snow_depths
    smoothed = lowess(snow_depths[valid_indices], timestamps[valid_indices], frac=0.1, is_sorted=True)
    result = np.full_like(snow_depths, np.nan)
    result[valid_indices] = smoothed[:, 1]
    logger.info("Completed function: smooth_snow_depths")
    return result

# Function to handle missing data
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

# Function to create a downloadable graph
def create_downloadable_graph(timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, smoothed_snow_depths, confidence_intervals, missing_periods, alarms, start_time, end_time, data_points, missing_data_count):
    logger.info("Starting function: create_downloadable_graph")
    
    # Ensure that all series have the same number of elements as timestamps
    assert len(timestamps) == len(temperatures) == len(precipitations) == len(snow_depths) == len(wind_speeds)

    # Use only non-NaN data for plotting
    valid_indices = ~np.isnan(snow_depths)

    fig, axes = plt.subplots(6, 1, figsize=(14, 28), sharex=True)
    plt.rcParams.update({'font.size': 14})

    fig.suptitle(f"Værdata for Gullingen værstasjon (SN46220)\nPeriode: {start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}", fontsize=22, fontweight='bold')

    # Plotting temperature data
    axes[0].plot(timestamps, temperatures, 'r-', linewidth=2)
    axes[0].set_ylabel('Temperatur (°C)', fontsize=16)
    axes[0].set_title('Temperatur', fontsize=18)
    axes[0].grid(True, linestyle=':', alpha=0.6)

    # Plotting precipitation data
    axes[1].bar(timestamps, precipitations, width=0.02, align='center', color='b', alpha=0.7)
    axes[1].set_ylabel('Nedbør (mm)', fontsize=16)
    axes[1].set_title('Nedbør', fontsize=18)
    axes[1].grid(True, linestyle=':', alpha=0.6)

    # Plotting estimated snow precipitation
    axes[2].bar(timestamps, snow_precipitations, width=0.02, align='center', color='m', alpha=0.7)
    axes[2].set_ylabel('Antatt snønedbør (mm)', fontsize=16)
    axes[2].set_title('Antatt snønedbør (Temp ≤ 1,5°C og økende snødybde)', fontsize=18)
    axes[2].grid(True, linestyle=':', alpha=0.6)

    # Plotting snow depth data
    if not np.all(np.isnan(snow_depths)):
        valid_indices = ~np.isnan(snow_depths)
        axes[3].plot(timestamps[valid_indices], snow_depths[valid_indices], 'o', label='Rå snødybde data', markersize=4)
        axes[3].plot(timestamps[valid_indices], smoothed_snow_depths[valid_indices], '-', label='Glattet snødybde data', linewidth=2)
        axes[3].fill_between(timestamps[valid_indices], 
                             confidence_intervals[0][valid_indices], 
                             confidence_intervals[1][valid_indices], 
                             color='gray', alpha=0.2, label='Konfidensintervall')
        
        max_snow_depth = np.nanmax(snow_depths)
        axes[3].set_ylim(0, max_snow_depth * 1.1 if not np.isnan(max_snow_depth) and max_snow_depth > 0 else 10)
    else:
        axes[3].text(0.5, 0.5, 'Ingen snødybdedata tilgjengelig', ha='center', va='center', transform=axes[3].transAxes)

    # Highlighting missing data periods
    for period in missing_periods:
        axes[3].axvspan(period[0], period[1], color='yellow', alpha=0.3, label='Manglende data' if period == missing_periods[0] else "")

    axes[3].set_ylabel('Snødybde (cm)', fontsize=16)
    axes[3].set_title('Snødybde', fontsize=18)
    axes[3].grid(True, linestyle=':', alpha=0.6)
    axes[3].legend(loc='best')

    max_snow_depth = np.nanmax(snow_depths)
    axes[3].set_ylim(0, max_snow_depth * 1.1 if not np.isnan(max_snow_depth) and max_snow_depth > 0 else 10)

    # Plotting wind speed data
    axes[4].plot(timestamps, wind_speeds, 'g-', linewidth=2)
    axes[4].set_ylabel('Vindhastighet (m/s)', fontsize=16)
    axes[4].set_title('Vindhastighet', fontsize=18)
    axes[4].grid(True, linestyle=':', alpha=0.6)

    # Plotting snow drift alarms
    alarm_times = [mdates.date2num(alarm) for alarm in alarms]
    axes[5].scatter(alarm_times, [1] * len(alarm_times), color='r', marker='x', s=100, label='Snøfokk-alarm')
    axes[5].set_yticks([])
    axes[5].set_title('Snøfokk-alarmer', fontsize=18)
    axes[5].grid(True, linestyle=':', alpha=0.6)
    axes[5].legend(loc='upper right')
    
    for ax in axes[:6]:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
        ax.tick_params(axis='x', rotation=45, labelsize=12)
        ax.tick_params(axis='y', labelsize=12)

    fig.tight_layout(rect=[0, 0.03, 1, 0.97])

    fig.text(0.99, 0.01, f'Data hentet: {datetime.now(ZoneInfo("Europe/Oslo")).strftime("%d.%m.%Y %H:%M")}\nAntall datapunkter: {data_points}\nManglende datapunkter: {missing_data_count}', ha='right', va='bottom', fontsize=12)
    fig.text(0.5, 0.01, 'Snøfokk-alarm: Vind > 7 m/s, nedbør < 0.1 mm, endring i snødybde ≥ 0.2 cm, og temperatur < -2°C', ha='center', va='bottom', fontsize=12, color='red')

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
    img_buffer.seek(0)

    img_str = base64.b64encode(img_buffer.getvalue()).decode()
    plt.close(fig)

    logger.info("Completed function: create_downloadable_graph")
    return img_str

# Function to fetch and process weather data
@st.cache_data(ttl=3600)
def fetch_and_process_data(client_id, date_start, date_end):
    logger.info("Starting function: fetch_and_process_data")
    try:
        url = "https://frost.met.no/observations/v0.jsonld"
        params = {
            "sources": "SN46220",
            "elements": "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),wind_speed",
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
                'precipitation': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'sum(precipitation_amount PT1H)'), np.nan),
                'snow_depth': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'surface_snow_thickness'), np.nan),
                'wind_speed': next((obs['value'] for obs in item['observations'] if obs['elementId'] == 'wind_speed'), np.nan)
            }
            for item in data.get('data', [])
        ]).set_index('timestamp')

        logger.info(f"Created DataFrame with shape: {df.shape}")
        logger.info(f"DataFrame columns: {df.columns}")
        logger.info(f"Sample of temperature data: {df['temperature'].head()}")

        df.index = pd.to_datetime(df.index).tz_localize(ZoneInfo("Europe/Oslo"), nonexistent='shift_forward', ambiguous='NaT')

        df['temperature'] = handle_missing_data(df.index, df['temperature'], method='time')
        df['precipitation'] = handle_missing_data(df.index, df['precipitation'], method='nearest')
        df['snow_depth'] = handle_missing_data(df.index, df['snow_depth'], method='linear')
        df['wind_speed'] = handle_missing_data(df.index, df['wind_speed'], method='time')

        timestamps = df.index.to_numpy()
        temperatures = df['temperature'].to_numpy()
        precipitations = df['precipitation'].to_numpy()
        snow_depths = df['snow_depth'].to_numpy()
        wind_speeds = df['wind_speed'].to_numpy()

        snow_depths = validate_snow_depths(snow_depths)
        smoothed_snow_depths = smooth_snow_depths(snow_depths)

        confidence_intervals = (
            smoothed_snow_depths - 1.96 * np.nanstd(snow_depths),
            smoothed_snow_depths + 1.96 * np.nanstd(snow_depths)
        )
        missing_periods = identify_missing_periods(timestamps, snow_depths)
        snow_precipitations = calculate_snow_precipitations(temperatures, precipitations, snow_depths)

        alarms = snow_drift_alarm(timestamps, wind_speeds, precipitations, snow_depths, temperatures)
        data_points = len(timestamps)
        missing_data_count = np.isnan(snow_depths).sum()

        img_str = create_downloadable_graph(
            timestamps, temperatures, precipitations, snow_depths, snow_precipitations, 
            wind_speeds, smoothed_snow_depths, confidence_intervals, missing_periods, alarms,
            pd.to_datetime(date_start), pd.to_datetime(date_end), data_points, missing_data_count
        )

        logger.info("Completed function: fetch_and_process_data")
        return {
            'img_str': img_str,
            'timestamps': timestamps,
            'temperatures': temperatures,
            'precipitations': precipitations,
            'snow_depths': snow_depths,
            'snow_precipitations': snow_precipitations,
            'wind_speeds': wind_speeds,
            'missing_periods': missing_periods,
            'alarms': alarms
        }

    except Exception as e:
        logger.error(f"Data processing error: {e}")
        return None

# Function to identify missing periods in the data
def identify_missing_periods(timestamps, snow_depths):
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

# Function to calculate snow precipitation
def calculate_snow_precipitations(temperatures, precipitations, snow_depths):
    logger.info("Starting function: calculate_snow_precipitations")
    snow_precipitations = []
    for i in range(len(temperatures)):
        if temperatures[i] is not None and temperatures[i] <= 1.5:
            if i > 0 and snow_depths[i] > snow_depths[i-1]:
                snow_precipitations.append(precipitations[i])
            else:
                snow_precipitations.append(0)
        else:
            snow_precipitations.append(0)
    logger.info("Completed function: calculate_snow_precipitations")
    return snow_precipitations

# Function to identify snow drift alarms with new criteria
def snow_drift_alarm(timestamps, wind_speeds, precipitations, snow_depths, temperatures):
    logger.info("Starting function: snow_drift_alarm")
    alarms = []
    for i in range(1, len(timestamps)):
        if (wind_speeds[i] > 7 and
            precipitations[i] < 0.1 and
            not np.isnan(snow_depths[i-1]) and not np.isnan(snow_depths[i]) and
            abs(snow_depths[i] - snow_depths[i-1]) >= 0.2 and
            not np.isnan(temperatures[i]) and temperatures[i] < -2):
            alarms.append(timestamps[i])
    logger.info("Completed function: snow_drift_alarm")
    return alarms

# Function to get date range based on user choice
def get_date_range(choice):
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

# Function to export data to CSV
def export_to_csv(timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, alarms):
    logger.info("Starting function: export_to_csv")
    df = pd.DataFrame({
        'Timestamp': timestamps,
        'Temperature': temperatures,
        'Precipitation': precipitations,
        'Snow Depth': snow_depths,
        'Snow Precipitation': snow_precipitations,
        'Wind Speed': wind_speeds,
        'Snow Drift Alarm': ['x' if ts in alarms else '' for ts in timestamps]
    })
    logger.info("Completed function: export_to_csv")
    return df.to_csv(index=False).encode('utf-8')

# Main function to run the Streamlit app
def main():
    st.title("Værdata og GPS aktivitet")

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
        
        if weather_data and 'img_str' in weather_data:
            st.image(f"data:image/png;base64,{weather_data['img_str']}", use_column_width=True)
            st.download_button(label="Last ned grafen", data=base64.b64decode(weather_data['img_str']), file_name="weather_data.png", mime="image/png")

            st.write(f"Antall datapunkter: {len(weather_data['timestamps'])}")
            st.write(f"Manglende datapunkter: {len(weather_data['missing_periods'])} perioder med manglende data.")

            csv_data = export_to_csv(weather_data['timestamps'], weather_data['temperatures'], weather_data['precipitations'], 
                                     weather_data['snow_depths'], weather_data['snow_precipitations'], weather_data['wind_speeds'], weather_data['alarms'])
            st.download_button(label="Last ned data som CSV", data=csv_data, file_name="weather_data.csv", mime="text/csv")

            # Display summary statistics
            st.subheader("Oppsummering av data")
            summary_df = pd.DataFrame({
                'Statistikk': ['Gjennomsnitt', 'Median', 'Minimum', 'Maksimum'],
                'Temperatur (°C)': [
                    f"{np.nanmean(weather_data['temperatures']):.1f}" if not np.all(np.isnan(weather_data['temperatures'])) else 'N/A',
                    f"{np.nanmedian(weather_data['temperatures']):.1f}" if not np.all(np.isnan(weather_data['temperatures'])) else 'N/A',
                    f"{np.nanmin(weather_data['temperatures']):.1f}" if not np.all(np.isnan(weather_data['temperatures'])) else 'N/A',
                    f"{np.nanmax(weather_data['temperatures']):.1f}" if not np.all(np.isnan(weather_data['temperatures'])) else 'N/A'
                ],
                'Nedbør (mm)': [
                    f"{np.nanmean(weather_data['precipitations']):.1f}" if not np.all(np.isnan(weather_data['precipitations'])) else 'N/A',
                    f"{np.nanmedian(weather_data['precipitations']):.1f}" if not np.all(np.isnan(weather_data['precipitations'])) else 'N/A',
                    f"{np.nanmin(weather_data['precipitations']):.1f}" if not np.all(np.isnan(weather_data['precipitations'])) else 'N/A',
                    f"{np.nanmax(weather_data['precipitations']):.1f}" if not np.all(np.isnan(weather_data['precipitations'])) else 'N/A'
                ],
                'Snødybde (cm)': [
                    f"{np.nanmean(weather_data['snow_depths']):.1f}" if not np.all(np.isnan(weather_data['snow_depths'])) else 'N/A',
                    f"{np.nanmedian(weather_data['snow_depths']):.1f}" if not np.all(np.isnan(weather_data['snow_depths'])) else 'N/A',
                    f"{np.nanmin(weather_data['snow_depths']):.1f}" if not np.all(np.isnan(weather_data['snow_depths'])) else 'N/A',
                    f"{np.nanmax(weather_data['snow_depths']):.1f}" if not np.all(np.isnan(weather_data['snow_depths'])) else 'N/A'
                ],
                'Vindhastighet (m/s)': [
                    f"{np.nanmean(weather_data['wind_speeds']):.1f}" if not np.all(np.isnan(weather_data['wind_speeds'])) else 'N/A',
                    f"{np.nanmedian(weather_data['wind_speeds']):.1f}" if not np.all(np.isnan(weather_data['wind_speeds'])) else 'N/A',
                    f"{np.nanmin(weather_data['wind_speeds']):.1f}" if not np.all(np.isnan(weather_data['wind_speeds'])) else 'N/A',
                    f"{np.nanmax(weather_data['wind_speeds']):.1f}" if not np.all(np.isnan(weather_data['wind_speeds'])) else 'N/A'
                ]
            })
            st.table(summary_df)

            # Display GPS activity data
            st.subheader("GPS aktivitet")
            if gps_data:
                gps_df = pd.DataFrame(gps_data)
                st.dataframe(gps_df)
            else:
                st.write("Ingen GPS-aktivitet i den valgte perioden.")
            
            # Display snow drift alarms
            st.subheader("Snøfokk-alarmer")
            if weather_data['alarms']:
                alarm_df = pd.DataFrame({
                    'Tidspunkt': weather_data['alarms'],
                    'Temperatur (°C)': [weather_data['temperatures'][np.where(weather_data['timestamps'] == alarm)[0][0]] for alarm in weather_data['alarms']],
                    'Vindhastighet (m/s)': [weather_data['wind_speeds'][np.where(weather_data['timestamps'] == alarm)[0][0]] for alarm in weather_data['alarms']],
                    'Snødybde (cm)': [weather_data['snow_depths'][np.where(weather_data['timestamps'] == alarm)[0][0]] for alarm in weather_data['alarms']]
                })
                st.dataframe(alarm_df)
            else:
                st.write("Ingen snøfokk-alarmer i den valgte perioden.")

        else:
            st.error("Ingen data eller grafbilde tilgjengelig for valgt periode.")

    except Exception as e:
        logger.error(f"Feil ved henting eller behandling av data: {e}")
        st.error(f"Feil ved henting eller behandling av data: {e}")

if __name__ == "__main__":
    main()
