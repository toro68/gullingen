import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta
from statsmodels.nonparametric.smoothers_lowess import lowess
import logging
from constants import TZ, STATION_ID, API_URL, ELEMENTS, TIME_RESOLUTION
from gps_utils import get_last_gps_activity
from util_functions import get_date_range
from logging_config import get_logger
import base64
import streamlit as st

logger = get_logger(__name__)

def fetch_raw_weather_data(client_id, date_start, date_end):
    """Henter rådata fra API-et"""
    try:
        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start.isoformat()}/{date_end.isoformat()}"
        }
        response = requests.get(API_URL, params=params, auth=(client_id, ""))
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Nettverksfeil ved henting av data: {str(e)}")
        raise

def create_dataframe_from_raw_data(data):
    """Konverterer rådata til DataFrame"""
    try:
        st.write("Debug: Starter create_dataframe_from_raw_data")
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
        ])
        st.write(f"Debug: Opprettet DataFrame med kolonner: {df.columns.tolist()}")
        return df
        
    except Exception as e:
        st.error(f"Feil i create_dataframe_from_raw_data: {str(e)}")
        logger.error(f"Feil i create_dataframe_from_raw_data: {str(e)}", exc_info=True)
        raise

def process_dataframe(df):
    """Prosesserer DataFrame med tidssone og indeks"""
    if 'timestamp' in df.columns:
        df = df.set_index('timestamp')
    df = df.sort_index()
    
    # Fjern duplikater og håndter tidssone
    df = df[~df.index.duplicated(keep='first')]
    df.index = pd.to_datetime(df.index).tz_localize(TZ, nonexistent='shift_forward', ambiguous='NaT')
    df = df[df.index.notnull()]
    
    return df

def handle_missing_and_validate(df):
    """Håndterer manglende data og validerer verdier"""
    processed_data = {}
    for column in df.columns:
        if len(df[column]) != len(df.index):
            logger.warning(f"Kolonne {column} har ulik lengde ({len(df[column])}) sammenlignet med indeksen ({len(df.index)})")
            df[column] = df[column].reindex(df.index)
        
        processed_data[column] = pd.to_numeric(df[column], errors='coerce')
        processed_data[column] = validate_data(processed_data[column])
        processed_data[column] = handle_missing_data(df.index, processed_data[column], method='time')
    
    return pd.DataFrame(processed_data, index=df.index)

def calculate_derived_values(df):
    """Beregner avledede verdier"""
    try:
        st.write("Debug: Starter calculate_derived_values")
        st.write(f"Debug: Kolonner før beregning: {df.columns.tolist()}")
        
        # Sjekk om nødvendige kolonner finnes
        required_columns = ['air_temperature', 'precipitation_amount', 'surface_snow_thickness']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            st.error(f"Mangler nødvendige kolonner for beregning: {missing_columns}")
            return df
        
        # Beregn snønedbør
        df['snow_precipitation'] = calculate_snow_precipitations(
            df['air_temperature'].values,
            df['precipitation_amount'].values,
            df['surface_snow_thickness'].values
        )
        
        # Beregn alarmer
        df = calculate_snow_drift_alarms(df)
        df = calculate_slippery_road_alarms(df)
        
        st.write(f"Debug: Kolonner etter beregning: {df.columns.tolist()}")
        return df
        
    except Exception as e:
        st.error(f"Feil i calculate_derived_values: {str(e)}")
        logger.error(f"Feil i calculate_derived_values: {str(e)}", exc_info=True)
        return df

def smooth_dataframe(df):
    """Utfører glatting av data"""
    smoothed_data = {}
    for column in df.columns:
        if column not in ['snow_drift_alarm', 'slippery_road_alarm', 'snow_precipitation']:
            smoothed_data[column] = smooth_data(df[column].values)
        else:
            smoothed_data[column] = df[column]
    
    smoothed_df = pd.DataFrame(smoothed_data, index=df.index)
    smoothed_df['wind_direction_category'] = smoothed_df['wind_from_direction'].apply(categorize_direction)
    return smoothed_df

def fetch_and_process_data(client_id, date_start, date_end):
    """Hovedfunksjon for å hente og prosessere værdata"""
    try:
        # Valider datoer
        current_time = datetime.now(TZ)
        if isinstance(date_start, str):
            date_start = datetime.fromisoformat(date_start)
        if isinstance(date_end, str):
            date_end = datetime.fromisoformat(date_end)
            
        if date_end > current_time:
            date_end = current_time
        if date_start > current_time:
            raise ValueError("Startdato kan ikke være i fremtiden")
        if date_start >= date_end:
            raise ValueError(f"Ugyldig tidsperiode: Startdatoen ({date_start}) må være før sluttdatoen ({date_end}).")

        # Hent og prosesser data
        raw_data = fetch_raw_weather_data(client_id, date_start, date_end)
        df = create_dataframe_from_raw_data(raw_data)
        df = process_dataframe(df)
        df = handle_missing_and_validate(df)
        df = calculate_derived_values(df)
        df = smooth_dataframe(df)

        return {'df': df}

    except Exception as e:
        error_message = f"Feil ved datahenting eller -behandling: {str(e)}"
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

def get_latest_alarms(client_id: str) -> dict:
    """
    Henter siste glatt vei-alarm og snøfokk-alarm fra værdata.
    
    Returns:
        dict: Dictionary med siste alarmer og tidspunkt
    """
    try:
        # Hent data for siste 7 dager
        end_date = datetime.now(TZ)
        start_date = end_date - timedelta(days=7)
        
        weather_data = fetch_and_process_data(client_id, start_date, end_date)
        
        if not weather_data or 'error' in weather_data or 'df' not in weather_data:
            logger.error("Kunne ikke hente værdata for alarmer")
            return None
            
        df = weather_data['df']
        
        # Finn siste alarmer
        last_slippery = df[df['slippery_road_alarm'] == 1].iloc[-1] if any(df['slippery_road_alarm'] == 1) else None
        last_snowdrift = df[df['snow_drift_alarm'] == 1].iloc[-1] if any(df['snow_drift_alarm'] == 1) else None
        
        result = {
            'slippery_road': {
                'time': last_slippery.name.strftime('%d.%m.%Y kl %H:%M') if last_slippery is not None else None,
                'temp': f"{last_slippery['air_temperature']:.1f}°C" if last_slippery is not None else None,
                'precipitation': f"{last_slippery['precipitation_amount']:.1f}mm" if last_slippery is not None else None
            },
            'snow_drift': {
                'time': last_snowdrift.name.strftime('%d.%m.%Y kl %H:%M') if last_snowdrift is not None else None,
                'wind': f"{last_snowdrift['wind_speed']:.1f}m/s" if last_snowdrift is not None else None,
                'temp': f"{last_snowdrift['air_temperature']:.1f}°C" if last_snowdrift is not None else None
            }
        }
        
        return result
        
    except Exception as e:
        logger.error(f"Feil ved henting av alarmer: {str(e)}")
        return None
    
def calculate_snow_precipitations(temperatures, precipitations, snow_depths):
    snow_precipitations = np.zeros_like(temperatures)
    for i in range(len(temperatures)):
        if temperatures[i] is not None and not np.isnan(temperatures[i]):
            condition1 = (
                temperatures[i] <= 1.5
                and i > 0
                and not np.isnan(snow_depths[i])
                and not np.isnan(snow_depths[i - 1])
                and snow_depths[i] > snow_depths[i - 1]
            )
            condition2 = (
                temperatures[i] <= 0
                and not np.isnan(precipitations[i])
                and precipitations[i] > 0
            )
            if condition1 or condition2:
                snow_precipitations[i] = (
                    precipitations[i] if not np.isnan(precipitations[i]) else 0
                )
    return snow_precipitations

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
    """
    Håndterer manglende data i tidsserien.
    
    Args:
        timestamps: Tidsindeks
        data: Data-array
        method: Interpoleringsmetode ('time', 'linear', eller 'nearest')
    
    Returns:
        numpy.array: Interpolert dataserie
    """
    try:
        # Opprett pandas Series med timestamps som indeks
        data_series = pd.Series(data, index=timestamps)
        
        # Fjern eventuelle NaN-verdier fra indeksen
        data_series = data_series[~data_series.index.isna()]
        
        # Sjekk om vi har nok data til interpolering
        if len(data_series) < 2:
            return data
            
        # Interpoler manglende verdier
        if method == 'time':
            interpolated = data_series.interpolate(method='time', limit_direction='both')
        elif method == 'linear':
            interpolated = data_series.interpolate(method='linear', limit_direction='both')
        else:
            interpolated = data_series.interpolate(method='nearest', limit_direction='both')
            
        # Fyll eventuelle gjenværende NaN-verdier med nærmeste gyldige verdi
        interpolated = interpolated.ffill().bfill()
        
        return interpolated.to_numpy()
        
    except Exception as e:
        logger.error(f"Feil ved interpolering av data: {str(e)}")
        return data  # Returner original data hvis interpolering feiler

def get_weather_data_for_period(client_id, start_date, end_date):
    return fetch_and_process_data(client_id, start_date, end_date)

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

def get_default_columns():
    """
    Returnerer standardkolonnene som skal vises som standard
    """
    return [
        'air_temperature',
        'precipitation_amount',
        'wind_speed',
        'surface_snow_thickness',
        'snow_drift_alarm',
        'slippery_road_alarm'
    ]

def get_available_columns():
    """
    Returnerer alle tilgjengelige kolonner med norske navn
    """
    return {
        'air_temperature': 'Lufttemperatur (°C)',
        'precipitation_amount': 'Nedbør (mm)',
        'surface_snow_thickness': 'Snødybde (cm)',
        'wind_speed': 'Vindhastighet (m/s)',
        'max_wind_speed': 'Maks vindkast (m/s)',
        'min_wind_speed': 'Min vindhastighet (m/s)',
        'wind_from_direction': 'Vindretning (grader)',
        'wind_direction_category': 'Vindretning',
        'surface_temperature': 'Bakketemperatur (°C)',
        'relative_humidity': 'Relativ luftfuktighet (%)',
        'dew_point_temperature': 'Duggpunkt (°C)',
        'snow_drift_alarm': 'Snøfokk-alarm',
        'slippery_road_alarm': 'Glatt vei-alarm',
        'snow_precipitation': 'Snønedbør (mm)',
        'snow_depth_change': 'Endring i snødybde (cm)'
    }

def get_csv_download_link(df: pd.DataFrame, selected_columns: list = None) -> str:
    """
    Genererer en nedlastingslink for værdata i CSV-format med valgte kolonner
    
    Args:
        df (pd.DataFrame): DataFrame med værdata
        selected_columns (list): Liste med kolonner som skal inkluderes
        
    Returns:
        str: HTML-kode for nedlastingslink eller feilmelding
    """
    try:
        # Bruk standardkolonner hvis ingen er valgt
        if selected_columns is None:
            selected_columns = get_default_columns()
            
        # Kopier DataFrame og filtrer kolonner
        export_df = df[selected_columns].copy()
        
        # Bruk mapping fra get_available_columns
        column_mapping = get_available_columns()
        export_df = export_df.rename(columns={col: column_mapping[col] for col in selected_columns})
        
        # Formater tidsstempel
        export_df.index = export_df.index.strftime('%d.%m.%Y %H:%M')
        export_df.index.name = 'Tidspunkt'
        
        # Rund av numeriske verdier til én desimal
        numeric_columns = export_df.select_dtypes(include=['float64', 'float32']).columns
        export_df[numeric_columns] = export_df[numeric_columns].round(1)
        
        # Konverter alarmer til Ja/Nei
        if 'Snøfokk-alarm' in export_df.columns:
            export_df['Snøfokk-alarm'] = export_df['Snøfokk-alarm'].map({1: 'Ja', 0: 'Nei'})
        if 'Glatt vei-alarm' in export_df.columns:
            export_df['Glatt vei-alarm'] = export_df['Glatt vei-alarm'].map({1: 'Ja', 0: 'Nei'})
        
        # Generer CSV-string med semikolon som separator og komma som desimaltegn
        csv = export_df.to_csv(sep=';', decimal=',', encoding='utf-8-sig')
        
        # Generer filnavn med tidsstempel
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M')
        filename = f"vaerdata_{timestamp}.csv"
        
        # Konverter til base64
        b64 = base64.b64encode(csv.encode()).decode()
        
        # Lag HTML nedlastingslink med CSS-styling
        href = f'''
        <a href="data:file/csv;base64,{b64}" 
           download="{filename}" 
           class="download-link"
           style="display: inline-block; 
                  padding: 0.5em 1em; 
                  color: white; 
                  background-color: #0066cc; 
                  text-decoration: none; 
                  border-radius: 4px;">
            📥 Last ned værdata (CSV)
        </a>
        '''
        
        return href
    
    except Exception as e:
        logger.error(f"Feil ved generering av nedlastingslink: {str(e)}")
        return "Kunne ikke generere nedlastingslink. Vennligst prøv igjen senere."