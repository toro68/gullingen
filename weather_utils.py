import numpy as np
import pandas as pd
import requests
from datetime import datetime
from statsmodels.nonparametric.smoothers_lowess import lowess
import logging
from constants import TZ, STATION_ID, API_URL, ELEMENTS, TIME_RESOLUTION
from gps_utils import get_last_gps_activity
from util_functions import get_date_range
from logging_config import get_logger

logger = get_logger(__name__)

def fetch_and_process_data(client_id, date_start, date_end):
    try:
        # Valider at date_start er før date_end
        if date_start >= date_end:
            error_message = f"Ugyldig tidsperiode: Startdatoen ({date_start}) må være før sluttdatoen ({date_end})."
            logger.error(error_message)
            return {'error': error_message}
        params = {
            "sources": STATION_ID,
            "elements": ELEMENTS,
            "timeresolutions": TIME_RESOLUTION,
            "referencetime": f"{date_start}/{date_end}"
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
        ]).set_index('timestamp')

        if df.empty:
            raise ValueError("Ingen data kunne konverteres til DataFrame")

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
    data_series = pd.Series(data, index=timestamps)
    if method == 'time':
        interpolated = data_series.interpolate(method='time')
    elif method == 'linear':
        interpolated = data_series.interpolate(method='linear')
    else:
        interpolated = data_series.interpolate(method='nearest')
    return interpolated.to_numpy()

# def calculate_snow_precipitations(temperatures, precipitations, snow_depths):
#     snow_precipitations = np.zeros_like(temperatures)
#     for i in range(len(temperatures)):
#         if temperatures[i] is not None and not np.isnan(temperatures[i]):
#             condition1 = temperatures[i] <= 1.5 and i > 0 and not np.isnan(snow_depths[i]) and not np.isnan(snow_depths[i-1]) and snow_depths[i] > snow_depths[i-1]
#             condition2 = temperatures[i] <= 0 and not np.isnan(precipitations[i]) and precipitations[i] > 0
#             if condition1 or condition2:
#                 snow_precipitations[i] = precipitations[i] if not np.isnan(precipitations[i]) else 0
#     return snow_precipitations

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