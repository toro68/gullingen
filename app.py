import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import streamlit.components.v1 as components
from statsmodels.nonparametric.smoothers_lowess import lowess

st.set_page_config(layout="wide")

def validate_snow_depths(snow_depths):
    snow_depths = np.array(snow_depths)
    snow_depths[snow_depths < 0] = np.nan  # Remove negative snow depths
    if np.all(np.isnan(snow_depths)):
        return snow_depths

    season_median = np.nanmedian(snow_depths)
    season_std = np.nanstd(snow_depths)
    lower_bound = max(0, season_median - 3 * season_std)
    upper_bound = season_median + 3 * season_std

    snow_depths[(snow_depths < lower_bound) | (snow_depths > upper_bound)] = np.nan
    return snow_depths

def smooth_snow_depths(snow_depths):
    if np.all(np.isnan(snow_depths)):
        return snow_depths

    timestamps = np.arange(len(snow_depths))
    smoothed = lowess(snow_depths, timestamps, frac=0.1, missing='drop')
    return smoothed[:, 1]

def handle_missing_data(timestamps, data):
    data_series = pd.Series(data, index=timestamps)
    interpolated = data_series.interpolate(method='time').interpolate(method='linear')
    interpolated[interpolated < 0] = 0
    return interpolated.to_numpy()

def snow_drift_alarm(timestamps, wind_speeds, precipitations, snow_depths, temperatures):
    alarms = []
    for i in range(1, len(timestamps)):
        if wind_speeds[i] > 5 and precipitations[i] == 0:
            if not np.isnan(snow_depths[i-1]) and not np.isnan(snow_depths[i]):
                if snow_depths[i] != snow_depths[i-1]:
                    if not np.isnan(temperatures[i]) and temperatures[i] < 0:
                        alarms.append(timestamps[i])
    return alarms

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
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        st.error(f"Request error: {e}")
        return None

    try:
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

        return timestamps, temperatures, precipitations, snow_depths, smoothed_snow_depths, confidence_intervals, snow_precipitations, wind_speeds, missing_periods, alarms

    except KeyError as e:
        st.error(f"Data processing error: Missing key {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None

def get_date_range(choice):
    now = datetime.now(ZoneInfo("Europe/Oslo")).replace(minute=0, second=0, microsecond=0)
    if choice == 'Siste 7 dager':
        start_time = now - timedelta(days=7)
    elif choice == 'Siste 24 timer':
        start_time = now - timedelta(hours=24)
    elif choice == 'Siste 12 timer':
        start_time = now - timedelta(hours=12)
    elif choice == 'Siste 4 timer':
        start_time = now - timedelta(hours=4)
    elif choice == 'Siden sist fredag':
        start_time = now - timedelta(days=(now.weekday() - 4) % 7)
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    elif choice == 'Siden sist søndag':
        start_time = now - timedelta(days=now.weekday() + 1)
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        return None, None

    return start_time.isoformat(), now.isoformat()

def export_to_csv(timestamps, temperatures, precipitations, snow_depths, smoothed_snow_depths, snow_precipitations, wind_speeds, alarms):
    alarm_flags = ['x' if timestamp in alarms else '' for timestamp in timestamps]
    df = pd.DataFrame({
        'Timestamp': timestamps,
        'Temperature': temperatures,
        'Precipitation': precipitations,
        'Snow Depth': snow_depths,
        'Smoothed Snow Depth': smoothed_snow_depths,
        'Snow Precipitation': snow_precipitations,
        'Wind Speed': wind_speeds,
        'Snow Drift Alarm': alarm_flags
    })
    return df.to_csv(index=False).encode('utf-8')

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

def main():
    st.title("Værdata for Gullingen værstasjon (SN46220)")
    
    custom_period = st.checkbox("Egendefinert periode")
    client_id = st.secrets["api_keys"]["client_id"]

    date_start_isoformat, date_end_isoformat = None, None

    if custom_period:
        st.subheader("Egendefinert periode")
        default_start = (datetime.now(ZoneInfo("Europe/Oslo")) - timedelta(days=7)).strftime('%d-%m-%Y %H:%M')
        st.write("Format: DD-MM-ÅÅÅÅ TT:00 (Eksempel: 07-02-2024 07:00)")
        date_start = st.text_input("Starttidspunkt", default_start)
        date_end = st.text_input("Sluttidspunkt (eller 'nå')", "nå")

        try:
            oslo_tz = ZoneInfo("Europe/Oslo")
            date_end_isoformat = (datetime.now(oslo_tz).replace(minute=0, second=0, microsecond=0).isoformat()
                                  if date_end.lower() == 'nå'
                                  else datetime.strptime(date_end, "%d-%m-%Y %H:%M").replace(tzinfo=oslo_tz).isoformat())
            date_start_isoformat = datetime.strptime(date_start, "%d-%m-%Y %H:%M").replace(tzinfo=oslo_tz).isoformat()

            if date_end_isoformat <= date_start_isoformat:
                st.error("Sluttidspunktet må være etter starttidspunktet.")
                return
        except ValueError:
            st.error("Ugyldig datoformat. Sørg for at minuttene er satt til 00. Prøv igjen.")
            return
    else:
        period = st.selectbox(
            "Velg en periode:",
            ["Siste 24 timer", "Siste 7 dager", "Siste 12 timer", "Siste 4 timer", "Siden sist fredag", "Siden sist søndag"]
        )
        date_start_isoformat, date_end_isoformat = get_date_range(period)

    if date_start_isoformat and date_end_isoformat:
        data = fetch_and_process_data(client_id, date_start_isoformat, date_end_isoformat)
        if data:
            timestamps, temperatures, precipitations, snow_depths, smoothed_snow_depths, confidence_intervals, snow_precipitations, wind_speeds, missing_periods, alarms = data

            # Ensure timestamps are in datetime format
            timestamps = pd.to_datetime(timestamps)

            # Set the x-axis range for all figures
            x_range = [timestamps.min(), timestamps.max()]

            # Plotting with Plotly
            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(x=timestamps, y=temperatures, mode='lines+markers', name='Temperature (°C)', line=dict(color='firebrick')))
            fig1.update_layout(title="Temperature Over Time", xaxis_title="Date", yaxis_title="Temperature (°C)", xaxis=dict(range=x_range), hovermode="x unified")

            fig2 = go.Figure()
            fig2.add_trace(go.Bar(x=timestamps, y=precipitations, name='Precipitation (mm)', marker_color='royalblue'))
            fig2.update_layout(title="Precipitation Over Time", xaxis_title="Date", yaxis_title="Precipitation (mm)", xaxis=dict(range=x_range), hovermode="x unified")

            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=timestamps, y=snow_depths, mode='markers', name='Snow Depth (raw)', marker=dict(color='darkblue')))
            fig3.add_trace(go.Scatter(x=timestamps, y=smoothed_snow_depths, mode='lines', name='Snow Depth (smoothed)', line=dict(color='cyan')))
            fig3.update_layout(title="Snow Depth Over Time", xaxis_title="Date", yaxis_title="Snow Depth (cm)", xaxis=dict(range=x_range), hovermode="x unified")

            fig4 = go.Figure()
            fig4.add_trace(go.Bar(x=timestamps, y=snow_precipitations, name='Snow Precipitation (mm)', marker_color='lightblue'))
            fig4.update_layout(title="Estimated Snow Precipitation Over Time", xaxis_title="Date", yaxis_title="Snow Precipitation (mm)", xaxis=dict(range=x_range), hovermode="x unified")

            fig5 = go.Figure()
            fig5.add_trace(go.Scatter(x=timestamps, y=wind_speeds, mode='lines+markers', name='Wind Speed (m/s)', line=dict(color='green')))
            fig5.update_layout(title="Wind Speed Over Time", xaxis_title="Date", yaxis_title="Wind Speed (m/s)", xaxis=dict(range=x_range), hovermode="x unified")

            fig6 = go.Figure()
            alarm_times = [timestamp for timestamp in timestamps if timestamp in alarms]
            fig6.add_trace(go.Scatter(x=alarm_times, y=[1] * len(alarm_times), mode='markers', marker=dict(color='red', size=3), name='Snow Drift Alarm'))
            fig6.update_layout(title="Snow Drift Alarms", xaxis_title="Date", yaxis=dict(visible=False), xaxis=dict(range=x_range), hovermode="x unified")

            st.plotly_chart(fig1, use_container_width=True)
            st.plotly_chart(fig2, use_container_width=True)
            st.plotly_chart(fig3, use_container_width=True)
            st.plotly_chart(fig4, use_container_width=True)
            st.plotly_chart(fig5, use_container_width=True)
            st.plotly_chart(fig6, use_container_width=True)

            st.write(f"Antall datapunkter: {len(timestamps)}")
            st.write(f"Manglende datapunkter: {len(missing_periods)} perioder med manglende data.")

            # CSV download button
            csv_data = export_to_csv(timestamps, temperatures, precipitations, snow_depths, smoothed_snow_depths, snow_precipitations, wind_speeds, alarms)
            st.download_button(label="Last ned data som CSV", data=csv_data, file_name="weather_data.csv", mime="text/csv")

        else:
            st.error("Ingen data tilgjengelig for valgt periode.")
    
    # Adding the iframe at the bottom of the page
    components.iframe(
        "https://plowman-new.xn--snbryting-m8ac.net/nb/share/Y3VzdG9tZXItMTM=",
        height=800,  # Set to a fixed height to ensure consistent layout
        width="100%",  # Full width
        scrolling=True  # Allow scrolling if the iframe content overflows
    )

if __name__ == "__main__":
    main()
