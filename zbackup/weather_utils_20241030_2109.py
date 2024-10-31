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

logger = get_logger(__name__)

def fetch_and_process_data(client_id, date_start, date_end):
    try:
        # Konverter til datetime hvis det er strings
        if isinstance(date_start, str):
            date_start = datetime.fromisoformat(date_start)
        if isinstance(date_end, str):
            date_end = datetime.fromisoformat(date_end)

        # Sjekk at datoene ikke er i fremtiden
        current_time = datetime.now(TZ)
        if date_end > current_time:
            date_end = current_time
        if date_start > current_time:
            raise ValueError("Startdato kan ikke være i fremtiden")

        # Valider at date_start er før date_end
        if date_start >= date_end:
            error_message = f"Ugyldig tidsperiode: Startdatoen ({date_start}) må være før sluttdatoen ({date_end})."
            logger.error(error_message)
            return {'error': error_message}

        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start.isoformat()}/{date_end.isoformat()}"
        }
        response = requests.get(API_URL, params=params, auth=(client_id, ""))
        response.raise_for_status()
        data = response.json()

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

        # Sørg for at timestamp er indeks og at den er sortert
        if 'timestamp' in df.columns:
            df = df.set_index('timestamp')
        df = df.sort_index()
        
        # Fjern eventuelle duplikate indekser FØR tidssonekonvertering
        df = df[~df.index.duplicated(keep='first')]
        
        # Sett tidssone
        df.index = pd.to_datetime(df.index).tz_localize(TZ, nonexistent='shift_forward', ambiguous='NaT')
        
        # Fjern eventuelle NaN-verdier i indeksen ETTER tidssonekonvertering
        df = df[df.index.notnull()]
        
        # Sørg for at alle kolonner har samme lengde som indeksen
        for column in df.columns:
            if len(df[column]) != len(df.index):
                logger.warning(f"Kolonne {column} har ulik lengde ({len(df[column])}) sammenlignet med indeksen ({len(df.index)})")
                # Juster kolonnen til å matche indeksen
                df[column] = df[column].reindex(df.index)

        # Håndter manglende data for hver kolonne
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
        error_message = f"Nettverksfeil ved henting av data: {str(e)}"
        logger.error(error_message)
        return {'error': error_message}

    except ValueError as e:
        error_message = f"Feil i databehandling: {str(e)}"
        logger.error(error_message)
        return {'error': error_message}

    except Exception as e:
        error_message = f"Uventet feil ved datahenting eller -behandling: {str(e)}"
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