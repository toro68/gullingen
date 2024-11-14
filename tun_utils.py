import pandas as pd
from datetime import datetime, time, timedelta
import streamlit as st
from db_utils import get_db_connection, fetch_data
import logging
import sqlite3
from typing import Optional, Dict, Any
from config import TZ

logger = logging.getLogger(__name__)

def get_bookings(start_date=None, end_date=None):
    logger.info(f"Starting get_bookings with start_date={start_date}, end_date={end_date}")
    
    try:
        query = """
            SELECT id, bruker, ankomst_dato, ankomst_tid, 
                   avreise_dato, avreise_tid, abonnement_type 
            FROM tunbroyting_bestillinger
        """
        
        df = fetch_data('tunbroyting', query)
        
        if df is None or df.empty:
            logger.info("No bookings found")
            return pd.DataFrame(columns=[
                'id', 'bruker', 'ankomst_dato', 'ankomst_tid', 
                'avreise_dato', 'avreise_tid', 'abonnement_type',
                'ankomst', 'avreise'
            ])
        
        df = df.copy()
        
        try:
            # Konverter dato-kolonner
            for col in ['ankomst_dato', 'avreise_dato']:
                df[col] = pd.to_datetime(df[col], errors='coerce')
            
            # Konverter tid-kolonner
            for col in ['ankomst_tid', 'avreise_tid']:
                df[col] = pd.to_datetime(df[col], format='%H:%M:%S', errors='coerce').dt.time
            
            # Kombiner dato og tid
            for prefix in ['ankomst', 'avreise']:
                dato_col = f'{prefix}_dato'
                tid_col = f'{prefix}_tid'
                df[prefix] = df.apply(
                    lambda row: pd.Timestamp.combine(
                        row[dato_col],
                        row[tid_col]
                    ) if pd.notnull(row[dato_col]) and row[tid_col] is not None 
                    else pd.NaT,
                    axis=1
                )
            
            # Legg til tidssone
            df['ankomst'] = df['ankomst'].dt.tz_localize('Europe/Oslo')
            df['avreise'] = df['avreise'].dt.tz_localize('Europe/Oslo')
            
        except Exception as e:
            logger.error(f"Error processing dates: {str(e)}")
            df['ankomst'] = pd.NaT
            df['avreise'] = pd.NaT
        
        # Filtrer på dato hvis spesifisert
        if start_date:
            df = df[df['ankomst'] >= pd.to_datetime(start_date)].copy()
        if end_date:
            df = df[df['ankomst'] <= pd.to_datetime(end_date)].copy()
        
        logger.info(f"Successfully processed {len(df)} bookings")
        return df
        
    except Exception as e:
        logger.error(f"Error in get_bookings: {str(e)}", exc_info=True)
        return pd.DataFrame()