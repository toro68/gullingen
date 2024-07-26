import streamlit as st
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from statsmodels.nonparametric.smoothers_lowess import lowess
import io
import base64
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Function to validate snow depths
def validate_snow_depths(snow_depths):
    snow_depths = np.array(snow_depths)
    snow_depths[snow_depths < 0] = np.nan  # Set negative values to NaN

    if np.all(np.isnan(snow_depths)):
        return snow_depths

    season_median = np.nanmedian(snow_depths)
    season_std = np.nanstd(snow_depths)
    lower_bound = max(0, season_median - 3 * season_std)
    upper_bound = season_median + 3 * season_std

    snow_depths[(snow_depths < lower_bound) | (snow_depths > upper_bound)] = np.nan
    return snow_depths

# Function to smooth snow depths
def smooth_snow_depths(snow_depths):
    if np.all(np.isnan(snow_depths)):
        return snow_depths

    timestamps = np.arange(len(snow_depths))
    smoothed = lowess(snow_depths, timestamps, frac=0.1, missing='drop')
    return smoothed[:, 1]

# Function to handle missing data
def handle_missing_data(timestamps, data, method='time'):
    data_series = pd.Series(data, index=timestamps)
    if method == 'time':
        interpolated = data_series.interpolate(method='time')
    elif method == 'linear':
        interpolated = data_series.interpolate(method='linear')
    else:
        interpolated = data_series.interpolate(method='nearest')
    
    interpolated[interpolated < 0] = 0  # Ensure no negative values remain
    return interpolated.to_numpy()

# Function to create a downloadable graph
def create_downloadable_graph(timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, smoothed_snow_depths, confidence_intervals, missing_periods, alarms, start_time, end_time, data_points, missing_data_count):
    fig, axes = plt.subplots(6, 1, figsize=(14, 28), sharex=True)

    plt.rcParams.update({'font.size': 14})

    fig.suptitle(f"Værdata for Gullingen værstasjon (SN46220)\nPeriode: {start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}", fontsize=22, fontweight='bold')

    axes[0].plot(timestamps, temperatures, 'r-', linewidth=2)
    axes[0].set_ylabel('Temperatur (°C)', fontsize=16)
    axes[0].set_title('Temperatur', fontsize=18)
    axes[0].grid(True, linestyle=':', alpha=0.6)

    # Rest of the plotting code...

    return img_str

# Function to fetch and process data
@st.cache_data(ttl=3600)  # Cache the data for 1 hour
def fetch_and_process_data(client_id, date_start, date_end):
    url = f"https://frost.met.no/observations/v0.jsonld"
    params = {
        "sources": "SN46220",
        "elements": "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),wind_speed",
        "timeresolutions": "PT1H",
        "referencetime": f"{date_start}/{date_end}"
    }
    r = requests.get(url, params=params, auth=(client_id, ""))
    if r.status_code != 200:
        raise Exception(f"Error: {r.status_code} - {r.text}")

    data = r.json()
    timestamps = []
    temperatures = []
    precipitations = []
    snow_depths = []
    wind_speeds = []

    for item in data['data']:
        time_str = item['referenceTime'].rstrip('Z')
        time = datetime.fromisoformat(time_str)
        observations = {obs['elementId']: obs['value'] for obs in item['observations']}

        timestamps.append(time)
        temperatures.append(observations.get('air_temperature', np.nan))
        precipitations.append(observations.get('sum(precipitation_amount PT1H)', 0))
        snow_depths.append(observations.get('surface_snow_thickness', np.nan))
        wind_speeds.append(observations.get('wind_speed', np.nan))

    # Use DataFrame to handle the data and ensure all series have the same length
    df = pd.DataFrame({
        'timestamp': timestamps,
        'temperature': temperatures,
        'precipitation': precipitations,
        'snow_depth': snow_depths,
        'wind_speed': wind_speeds
    }).set_index('timestamp')

    # Fill out any missing timestamps
    df = df.resample('H').asfreq()

    timestamps = df.index
    temperatures = df['temperature'].to_numpy()
    precipitations = df['precipitation'].to_numpy()
    snow_depths = df['snow_depth'].to_numpy()
    wind_speeds = df['wind_speed'].to_numpy()

    # Rest of the processing...

    return img_str, timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, missing_periods, alarms

# Function to identify missing periods in the data
def identify_missing_periods(timestamps, snow_depths):
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
    return missing_periods

# Function to calculate snow precipitation
def calculate_snow_precipitations(temperatures, precipitations, snow_depths):
    snow_precipitations = []
    for i in range(len(temperatures)):
        if temperatures[i] is not None and temperatures[i] <= 1.5:
            if i > 0 and snow_depths[i] > snow_depths[i-1]:
                snow_precipitations.append(precipitations[i])
            else:
                snow_precipitations.append(0)
        else:
            snow_precipitations.append(0)
    return snow_precipitations

# Function to identify snow drift alarms with new criteria
def snow_drift_alarm(timestamps, wind_speeds, precipitations, snow_depths, temperatures):
    alarms = []

    for i in range(1, len(timestamps)):
        if (wind_speeds[i] > 7 and
            precipitations[i] < 0.1 and
            not np.isnan(snow_depths[i-1]) and not np.isnan(snow_depths[i]) and
            abs(snow_depths[i] - snow_depths[i-1]) >= 0.2 and
            not np.isnan(temperatures[i]) and temperatures[i] < -2):
            alarms.append(timestamps[i])

    return alarms

# Function to get date range based on user choice
def get_date_range(choice):
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
        return None, None

    return start_time.isoformat(), now.isoformat()

# Function to export data to CSV
def export_to_csv(timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, alarms):
    df = pd.DataFrame({
        'Timestamp': timestamps,'Temperature': temperatures,
        'Precipitation': precipitations,
        'Snow Depth': snow_depths,
        'Snow Precipitation': snow_precipitations,
        'Wind Speed': wind_speeds,
        'Snow Drift Alarm': ['x' if ts in alarms else '' for ts in timestamps]
    })
    return df.to_csv(index=False).encode('utf-8')

# Main function to run the Streamlit app
def main():
    st.title("Værdata for Gullingen værstasjon (SN46220)")
    
    # Default selection is "Siste 24 timer"
    period = st.selectbox(
        "Velg en periode:",
        ["Siste 24 timer", "Siste 7 dager", "Siste 12 timer", "Siste 4 timer", "Siden sist fredag", "Siden sist søndag"]
    )

    custom_period = st.checkbox("Egendefinert periode")

    client_id = st.secrets["api_keys"]["client_id"]

    if custom_period:
        st.write("Format: DD-MM-ÅÅÅÅ TT:00 (Eksempel: 07-02-2024 07:00)")
        date_start = st.text_input("Starttidspunkt", "")
        date_end = st.text_input("Sluttidspunkt (eller 'nå')", "")

        try:
            oslo_tz = ZoneInfo("Europe/Oslo")
            date_end_isoformat = (datetime.now(oslo_tz).replace(minute=0, second=0, microsecond=0).isoformat(timespec='hours')
                                  if date_end.lower() == 'nå'
                                  else datetime.strptime(date_end, "%d-%m-%Y %H:%M").replace(tzinfo=oslo_tz).isoformat(timespec='hours'))
            date_start_isoformat = datetime.strptime(date_start, "%d-%m-%Y %H:%M").replace(tzinfo=oslo_tz).isoformat(timespec='hours')

            if date_end_isoformat <= date_start_isoformat:
                st.error("Sluttidspunktet må være etter starttidspunktet.")
                return
        except ValueError:
            st.error("Ugyldig datoformat. Sørg for at minuttene er satt til 00. Prøv igjen.")
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

    try:
        data = fetch_and_process_data(client_id, date_start_isoformat, date_end_isoformat)
        if data:
            img_str, timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, missing_periods, alarms = data

            st.image(f"data:image/png;base64,{img_str}", use_column_width=True)
            st.download_button(label="Last ned grafen", data=base64.b64decode(img_str), file_name="weather_data.png", mime="image/png")

            st.write(f"Antall datapunkter: {len(timestamps)}")
            st.write(f"Manglende datapunkter: {len(missing_periods)} perioder med manglende data.")

            # Display some statistics
            st.subheader("Statistikk")
            st.write(f"Gjennomsnittlig temperatur: {np.mean(temperatures):.1f}°C")
            st.write(f"Maksimal temperatur: {np.max(temperatures):.1f}°C")
            st.write(f"Minimal temperatur: {np.min(temperatures):.1f}°C")
            st.write(f"Total nedbør: {np.sum(precipitations):.1f} mm")
            st.write(f"Maksimal vindhastighet: {np.max(wind_speeds):.1f} m/s")

            # CSV download button
            csv_data = export_to_csv(timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, alarms)
            st.download_button(label="Last ned data som CSV", data=csv_data, file_name="weather_data.csv", mime="text/csv")

            # Display alarms
            if alarms:
                st.subheader("Snøfokk-alarmer")
                for alarm in alarms:
                    st.write(alarm.strftime("%d.%m.%Y %H:%M"))
            else:
                st.write("Ingen snøfokk-alarmer i valgt periode.")

        else:
            st.error("Ingen data tilgjengelig for valgt periode.")

    except Exception as e:
        st.error(f"Feil ved henting eller behandling av data: {e}")

if __name__ == "__main__":
    main()