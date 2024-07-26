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
import streamlit.components.v1 as components

# Function to validate snow depths
def validate_snow_depths(snow_depths):
    snow_depths = np.array(snow_depths)
    # Remove negative snow depths which are considered invalid
    snow_depths[snow_depths < 0] = np.nan

    if np.all(np.isnan(snow_depths)):
        return snow_depths

    # Calculate median and standard deviation for filtering outliers
    season_median = np.nanmedian(snow_depths)
    season_std = np.nanstd(snow_depths)
    lower_bound = max(0, season_median - 3 * season_std)
    upper_bound = season_median + 3 * season_std

    # Set snow depths outside the bounds to NaN
    snow_depths[(snow_depths < lower_bound) | (snow_depths > upper_bound)] = np.nan

    return snow_depths

# Function to smooth snow depths
def smooth_snow_depths(snow_depths):
    if np.all(np.isnan(snow_depths)):
        return snow_depths

    timestamps = np.arange(len(snow_depths))
    # Using LOWESS to smooth the snow depths data
    smoothed = lowess(snow_depths, timestamps, frac=0.1, missing='drop')
    return smoothed[:, 1]

# Function to handle missing data
def handle_missing_data(timestamps, data):
    data_series = pd.Series(data, index=timestamps)
    # Interpolating missing data using time and linear methods
    interpolated = data_series.interpolate(method='time').interpolate(method='linear')
    interpolated[interpolated < 0] = 0  # Ensure no negative values remain
    return interpolated.to_numpy()

# Function to create a downloadable graph
def create_downloadable_graph(timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, smoothed_snow_depths, confidence_intervals, missing_periods, alarms, start_time, end_time, data_points, missing_data_count):
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
        axes[3].plot(timestamps, snow_depths, 'o', label='Rå snødybde data', markersize=4)
        axes[3].plot(timestamps, smoothed_snow_depths, '-', label='Glattet snødybde data', linewidth=2)
        axes[3].fill_between(timestamps, confidence_intervals[0], confidence_intervals[1], color='gray', alpha=0.2, label='Konfidensintervall')

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
    fig.text(0.5, 0.01, 'Snøfokk-alarm: Vind > 5 m/s, ingen nedbør, endring i snødybde, og temperatur < 0°C', ha='center', va='bottom', fontsize=12, color='red')

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
    img_buffer.seek(0)

    img_str = base64.b64encode(img_buffer.getvalue()).decode()
    plt.close(fig)

    return img_str

# Function to fetch and process data
def fetch_and_process_data(client_id, date_start, date_end):
    try:
        url = "https://frost.met.no/observations/v0.jsonld"
        params = {
            "sources": "SN46220",
            "elements": "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),wind_speed",
            "timeresolutions": "PT1H",
            "referencetime": f"{date_start}/{date_end}"
        }
        response = requests.get(url, params=params, auth=(client_id, ""))
        response.raise_for_status()  # Raise an error for bad status codes
        data = response.json()
    except requests.RequestException as e:
        st.error(f"Request error: {e}")
        return None

    try:
        # Process data
        timestamps, temperatures, precipitations, snow_depths, wind_speeds = [], [], [], [], []
        for item in data.get('data', []):
            time_str = item['referenceTime'].rstrip('Z')
            time = datetime.fromisoformat(time_str)
            observations = {obs['elementId']: obs['value'] for obs in item['observations']}
            
            timestamps.append(time)
            temperatures.append(observations.get('air_temperature', np.nan))
            precipitations.append(observations.get('sum(precipitation_amount PT1H)', 0))
            snow_depths.append(observations.get('surface_snow_thickness', np.nan))
            wind_speeds.append(observations.get('wind_speed', np.nan))

        df = pd.DataFrame({
            'timestamp': timestamps,
            'temperature': temperatures,
            'precipitation': precipitations,
            'snow_depth': snow_depths,
            'wind_speed': wind_speeds
        }).set_index('timestamp')

        df = df.resample('H').asfreq()
        timestamps, temperatures, precipitations, snow_depths, wind_speeds = df.index.to_numpy(), df['temperature'].to_numpy(), df['precipitation'].to_numpy(), df['snow_depth'].to_numpy(), df['wind_speed'].to_numpy()

        snow_depths = validate_snow_depths(snow_depths)
        snow_depths = handle_missing_data(timestamps, snow_depths)
        smoothed_snow_depths = smooth_snow_depths(snow_depths)

        confidence_intervals = (smoothed_snow_depths - 1.96 * np.nanstd(snow_depths), smoothed_snow_depths + 1.96 * np.nanstd(snow_depths))
        missing_periods = identify_missing_periods(timestamps, snow_depths)
        snow_precipitations = calculate_snow_precipitations(temperatures, precipitations, snow_depths)

        alarms = snow_drift_alarm(timestamps, wind_speeds, precipitations, snow_depths, temperatures)
        data_points, missing_data_count = len(timestamps), np.isnan(snow_depths).sum()

        img_str = create_downloadable_graph(
            timestamps, temperatures, precipitations, snow_depths, snow_precipitations, 
            wind_speeds, smoothed_snow_depths, confidence_intervals, missing_periods, alarms,
            pd.to_datetime(date_start), pd.to_datetime(date_end), data_points, missing_data_count
        )

        return img_str, timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, missing_periods, alarms

    except KeyError as e:
        st.error(f"Data processing error: Missing key {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None

# Function to identify missing periods in the data
def identify_missing_periods(timestamps, snow_depths):
    missing_periods = []
    nan_indices = np.where(np.isnan(snow_depths))[0]
    if len(nan_indices) > 0:
        current_period = [timestamps[nan_indices[0]], timestamps[nan_indices[0]]]
        for idx in nan_indices[1:]:
            # Check if the next NaN is contiguous to the current period
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

# Function to identify snow drift alarms
def snow_drift_alarm(timestamps, wind_speeds, precipitations, snow_depths, temperatures):
    alarms = []

    for i in range(1, len(timestamps)):
        # Check if wind speed is over 5 m/s
        if wind_speeds[i] > 5:
            # Check if there is no precipitation
            if precipitations[i] == 0:
                # Check if there is a change in snow depth
                if not np.isnan(snow_depths[i-1]) and not np.isnan(snow_depths[i]):
                    if snow_depths[i] != snow_depths[i-1]:
                        # Check if the temperature is below 0°C
                        if not np.isnan(temperatures[i]) and temperatures[i] < 0:
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
        # Calculating the previous Friday
        start_time = now - timedelta(days=(now.weekday() - 4) % 7)
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    elif choice == 'ss':
        # Calculating the previous Sunday
        start_time = now - timedelta(days=now.weekday() + 1)
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        return None, None

    return start_time.isoformat(timespec='hours'), now.isoformat(timespec='hours')

# Function to export data to CSV
def export_to_csv(timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, alarms):
    # Convert data to a DataFrame for easier CSV export
    df = pd.DataFrame({
        'Timestamp': timestamps,
        'Temperature': temperatures,
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

            # CSV download button
            csv_data = export_to_csv(timestamps, temperatures, precipitations, snow_depths, snow_precipitations, wind_speeds, alarms)
            st.download_button(label="Last ned data som CSV", data=csv_data, file_name="weather_data.csv", mime="text/csv")

        else:
            st.error("Ingen data tilgjengelig for valgt periode.")

    except Exception as e:
        st.error(f"Feil ved henting eller behandling av data: {e}")




if __name__ == "__main__":
    main()
