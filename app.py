import streamlit as st
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from statsmodels.nonparametric.smoothers_lowess import lowess
import io
import base64
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Data fetching and processing ---

def fetch_weather_data(client_id, date_start, date_end):
    """Henter værdata fra MET.no API."""
    url = "https://frost.met.no/observations/v0.jsonld"
    params = {
        "sources": "SN46220",
        "elements": "air_temperature,surface_snow_thickness,sum(precipitation_amount PT1H),wind_speed",
        "timeresolutions": "PT1H",
        "referencetime": f"{date_start}/{date_end}"
    }
    response = requests.get(url, params=params, auth=(client_id, ""))
    response.raise_for_status()
    return response.json()

def process_weather_data(data):
    """Behandler værdata og returnerer en Pandas DataFrame."""
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

    df.index = pd.to_datetime(df.index).tz_localize(ZoneInfo("Europe/Oslo"), nonexistent='shift_forward', ambiguous='NaT')
    df = df.astype({'temperature': 'float', 'precipitation': 'float', 'snow_depth': 'float', 'wind_speed': 'float'})
    df = df.interpolate(method='linear')
    return df

def fetch_gps_data():
    """Henter GPS-data fra irute.net."""
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

# --- Alarm-relaterte funksjoner ---

def calculate_snow_precipitation(df):
    """Beregner antatt snønedbør basert på temperatur og nedbør."""
    df['snow_precipitation'] = 0
    df.loc[(df['temperature'] <= 1.5) & (df['snow_depth'].diff() > 0) |
           (df['temperature'] <= 0) & (df['precipitation'] > 0), 'snow_precipitation'] = df['precipitation']
    return df

def identify_snow_drift_alarms(df):
    """Identifiserer snøfokk-alarmer basert på værdata."""
    alarms = []
    for i in range(1, len(df)):
        if (df['wind_speed'][i] > 6 and df['precipitation'][i] < 0.1 and 
            abs(df['snow_depth'][i] - df['snow_depth'][i-1]) >= 1.0 and 
            df['temperature'][i] <= -1.0):
            alarms.append(df.index[i])
        elif (df['wind_speed'][i] > 6 and df['precipitation'][i] >= 0.1 and 
              df['snow_depth'][i] - df['snow_depth'][i-1] <= -0.5 and 
              df['temperature'][i] <= -1.0):
            alarms.append(df.index[i])
    return alarms

def identify_slippery_roads(df):
    """Identifiserer glatte veier/slush-alarmer basert på værdata."""
    alarms = []
    for i in range(1, len(df)):
        if (df['temperature'][i] > 0 and df['precipitation'][i] > 1.5 and 
            df['snow_depth'][i] >= 20 and df['snow_depth'][i] < df['snow_depth'][i-1]):
            alarms.append(df.index[i])
    return alarms

# --- Funksjon for å generere nedlastbar graf ---

def create_downloadable_graph(df, alarms, slippery_road_alarms):
    """Genererer en graf med værdata og alarmer, og returnerer den som en base64-kodet streng."""
    plt.style.use('seaborn-whitegrid')
    fig, axes = plt.subplots(6, 1, figsize=(16, 32), sharex=True, facecolor='#F0F0F0')
    plt.rcParams.update({'font.size': 12, 'font.weight': 'bold'})

    fig.suptitle(f"Værdata for Gullingen værstasjon (SN46220)\nPeriode: {df.index[0].strftime('%d.%m.%Y %H:%M')} - {df.index[-1].strftime('%d.%m.%Y %H:%M')}", 
                 fontsize=24, fontweight='bold', y=0.95)

    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#F7DC6F']
    titles = ['Temperatur', 'Nedbør', 'Antatt snønedbør', 'Snødybde', 'Vindhastighet', 'Alarmer']
    ylabels = ['Temperatur (°C)', 'Nedbør (mm)', 'Antatt snønedbør (mm)', 'Snødybde (cm)', 'Vindhastighet (m/s)', '']

    for ax, title, ylabel, color in zip(axes, titles, ylabels, colors):
        ax.set_title(title, fontsize=18, fontweight='bold', color=color, 
                     bbox=dict(facecolor='white', edgecolor=color, boxstyle='round,pad=0.5'))
        ax.set_ylabel(ylabel, fontsize=14, fontweight='bold', color=color)
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    # Temperatur
    axes[0].plot(df.index, df['temperature'], color=colors[0], linewidth=2)
    axes[0].fill_between(df.index, df['temperature'], alpha=0.3, color=colors[0])

    # Nedbør
    axes[1].bar(df.index, df['precipitation'], width=0.02, align='center', color=colors[1], alpha=0.7)

    # Antatt snønedbør
    axes[2].bar(df.index, df['snow_precipitation'], width=0.02, align='center', color=colors[2], alpha=0.7)

    # Snødybde
    axes[3].plot(df.index, df['snow_depth'], '.', label='Rå data', markersize=4, color=colors[3], alpha=0.5)
    smoothed = lowess(df['snow_depth'], np.arange(len(df)), frac=0.1, it=0)
    axes[3].plot(df.index, smoothed[:, 1], '-', label='Glattet data', linewidth=2, color=colors[3])
    axes[3].fill_between(df.index, 
                         smoothed[:, 1] - 1.96 * np.nanstd(df['snow_depth']), 
                         smoothed[:, 1] + 1.96 * np.nanstd(df['snow_depth']), 
                         color=colors[3], alpha=0.2, label='Konfidensintervall')

    axes[3].legend(loc='upper right', fancybox=True, shadow=True)

    # Vindhastighet
    axes[4].plot(df.index, df['wind_speed'], color=colors[4], linewidth=2)

    # Alarmer
    alarm_times = [mdates.date2num(alarm) for alarm in alarms]
    slippery_road_times = [mdates.date2num(alarm) for alarm in slippery_road_alarms]
    
    axes[5].eventplot(alarm_times, lineoffsets=1, linelengths=0.5, linewidths=2, colors='red', label='Snøfokk-alarm')
    axes[5].eventplot(slippery_road_times, lineoffsets=0.5, linelengths=0.5, linewidths=2, colors='blue', label='Glatt vei / slush-alarm')
    
    axes[5].set_ylim(0, 1.5)
    axes[5].set_yticks([])
    axes[5].legend(loc='upper right', fancybox=True, shadow=True)

    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
        ax.tick_params(axis='x', rotation=45, labelsize=10)
        ax.tick_params(axis='y', labelsize=10)

    fig.tight_layout(rect=[0, 0.03, 1, 0.95])

    # Legg til forklaringer for alarmene
    fig.text(0.01, 0.01, 'Snøfokk-alarm: Vind > 6 m/s, temp ≤ -1°C, lite nedbør, endring i snødybde\n'
                         'Glatt vei / slush-alarm: Temp > 0°C, nedbør > 1.5 mm, snødybde ≥ 20 cm, synkende snødybde', 
             ha='left', va='bottom', fontsize=10, style='italic')

    fig.text(0.99, 0.01, f'Data hentet: {datetime.now(ZoneInfo("Europe/Oslo")).strftime("%d.%m.%Y %H:%M")}\n'
                         f'Antall datapunkter: {len(df)}\nManglende datapunkter: {df['snow_depth'].isna().sum()} perioder med manglende data', 
             ha='right', va='bottom', fontsize=10, style='italic')

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight')
    img_buffer.seek(0)

    img_str = base64.b64encode(img_buffer.getvalue()).decode()
    plt.close(fig)
    return img_str

# --- Hovedfunksjonen for Streamlit-appen ---

def main():
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
            weather_data = fetch_weather_data(client_id, date_start_isoformat, date_end_isoformat)
            gps_data = fetch_gps_data() if period != "Siste GPS-aktivitet til nå" else gps_data
            df = process_weather_data(weather_data)
            df = calculate_snow_precipitation(df)
            alarms = identify_snow_drift_alarms(df)
            slippery_road_alarms = identify_slippery_roads(df)
        
        if not df.empty:
            img_str = create_downloadable_graph(df, alarms, slippery_road_alarms)
            st.image(f"data:image/png;base64,{img_str}", use_column_width=True)
            st.download_button(label="Last ned grafen", data=base64.b64decode(img_str), file_name="weather_data.png", mime="image/png")

            st.write(f"Antall datapunkter: {len(df)}")
            st.write(f"Manglende datapunkter: {df['snow_depth'].isna().sum()} perioder med manglende data.")

            csv_data = df.to_csv(index=True, encoding='utf-8')
            st.download_button(label="Last ned data som CSV", data=csv_data, file_name="weather_data.csv", mime="text/csv")

            st.subheader("Oppsummering av data")
            summary_df = pd.DataFrame({
                'Statistikk': ['Gjennomsnitt', 'Median', 'Minimum', 'Maksimum', 'Total'],
                'Temperatur (°C)': [df['temperature'].mean(), df['temperature'].median(), df['temperature'].min(), df['temperature'].max(), 'N/A'],
                'Nedbør (mm)': [df['precipitation'].mean(), df['precipitation'].median(), df['precipitation'].min(), df['precipitation'].max(), df['precipitation'].sum()],
                'Antatt snønedbør (mm)\n(Temp ≤ 1,5°C og økende snødybde, eller Temp ≤ 0°C)': [df['snow_precipitation'].mean(), df['snow_precipitation'].median(), df['snow_precipitation'].min(), df['snow_precipitation'].max(), df['snow_precipitation'].sum()],
                'Snødybde (cm)': [df['snow_depth'].mean(), df['snow_depth'].median(), df['snow_depth'].min(), df['snow_depth'].max(), 'N/A'],
                'Vindhastighet (m/s)': [df['wind_speed'].mean(), df['wind_speed'].median(), df['wind_speed'].min(), df['wind_speed'].max(), 'N/A']
            })
            st.table(summary_df)

            # Display GPS activity data
            st.subheader("Siste GPS aktivitet")
            if gps_data:
                gps_df = pd.DataFrame(gps_data)
                st.dataframe(gps_df)
            else:
                st.write("Ingen GPS-aktivitet i den valgte perioden.")

            # Display snow drift alarms
            st.subheader("Snøfokk-alarmer")
            st.write("Alarmene er basert på værdata og ikke direkte observasjoner.")
            if alarms:
                alarm_df = pd.DataFrame(alarms, columns=['Tidspunkt'])
                alarm_df['Temperatur (°C)'] = alarm_df['Tidspunkt'].map(lambda x: df.loc[x, 'temperature'])
                alarm_df['Vindhastighet (m/s)'] = alarm_df['Tidspunkt'].map(lambda x: df.loc[x, 'wind_speed'])
                alarm_df['Snødybde (cm)'] = alarm_df['Tidspunkt'].map(lambda x: df.loc[x, 'snow_depth'])
                alarm_df['Nedbør (mm)'] = alarm_df['Tidspunkt'].map(lambda x: df.loc[x, 'precipitation'])
                alarm_df['Endring i snødybde (cm)'] = alarm_df['Tidspunkt'].shift(-1).map(lambda x: df.loc[x, 'snow_depth'] - df.loc[alarm_df['Tidspunkt'].shift(1), 'snow_depth'])
                st.dataframe(alarm_df)
            else:
                st.write("Ingen snøfokk-alarmer i den valgte perioden.")

            # Display slippery road alarms
            st.subheader("Regn 👉🏻👉🏻👉🏻 Glatt vei / slush-alarmer")
            st.write("Kriterier: Temperatur > 0°C, nedbør > 1.5 mm, snødybde ≥ 20 cm, og synkende snødybde.")
            st.write("Alarmene er basert på værdata og ikke direkte observasjoner.")
            if slippery_road_alarms:
                slippery_road_df = pd.DataFrame(slippery_road_alarms, columns=['Tidspunkt'])
                slippery_road_df['Temperatur (°C)'] = slippery_road_df['Tidspunkt'].map(lambda x: df.loc[x, 'temperature'])
                slippery_road_df['Nedbør (mm)'] = slippery_road_df['Tidspunkt'].map(lambda x: df.loc[x, 'precipitation'])
                slippery_road_df['Snødybde (cm)'] = slippery_road_df['Tidspunkt'].map(lambda x: df.loc[x, 'snow_depth'])
                slippery_road_df['Endring i snødybde (cm)'] = slippery_road_df['Tidspunkt'].shift(-1).map(lambda x: df.loc[x, 'snow_depth'] - df.loc[slippery_road_df['Tidspunkt'].shift(1), 'snow_depth'])
                st.dataframe(slippery_road_df)
            else:
                st.write("Ingen glatt vei / slush-alarmer i den valgte perioden.")

        else:
            st.error("Kunne ikke hente data. Vennligst sjekk loggene for mer informasjon.")

    except Exception as e:
        logger.error(f"Feil ved henting eller behandling av data: {e}")
        st.error(f"Feil ved henting eller behandling av data: {e}")

if __name__ == "__main__":
    main()