import requests
from datetime import datetime
import logging
import streamlit as st
from constants import TZ, GPS_URL

from logging_config import get_logger

logger = get_logger(__name__)

def fetch_gps_data():
    try:
        response = requests.get(GPS_URL)
        response.raise_for_status()
        gps_data = response.json()
        all_eq_dicts = gps_data.get('features', [])
        
        gps_entries = []
        for eq_dict in all_eq_dicts:
            date_str = eq_dict['properties'].get('Date')
            if date_str:
                try:
                    gps_entry = {
                        'BILNR': eq_dict['properties'].get('BILNR'),
                        'Date': datetime.strptime(date_str, '%H:%M:%S %d.%m.%Y').replace(tzinfo=TZ)
                    }
                    gps_entries.append(gps_entry)
                except ValueError as e:
                    st.error(f"Feil ved parsing av dato: {e}")
        
        return gps_entries
    except requests.RequestException as e:
        st.error(f"Feil ved henting av GPS-data: {e}")
        return []
    except Exception as e:
        st.error(f"Uventet feil i fetch_gps_data: {e}")
        return []

def get_last_gps_activity():
    gps_entries = fetch_gps_data()
    if gps_entries:
        # Sorter GPS-innslag etter dato i synkende rekkefølge
        sorted_entries = sorted(gps_entries, key=lambda x: x['Date'], reverse=True)
        
        # Hent den nyeste datoen
        last_activity = sorted_entries[0]['Date']
        
        return last_activity
    else:
        st.warning("Ingen GPS-data funnet.")
        return None

def get_gps_coordinates():
    try:
        gps_entries = fetch_gps_data()
        if not gps_entries:
            st.warning("Ingen GPS-data funnet.")
            return []

        coordinates = []
        for entry in gps_entries:
            try:
                # Sjekk om 'geometry' og 'coordinates' eksisterer
                if 'geometry' in entry and 'coordinates' in entry['geometry']:
                    lat, lon = entry['geometry']['coordinates']
                    bilnr = entry['properties'].get('BILNR', 'Ukjent')
                    date = entry['properties'].get('Date', 'Ukjent dato')
                    coordinates.append((lat, lon, bilnr, date))
                else:
                    logger.warning(f"Manglende koordinater for innslag: {entry}")
            except Exception as e:
                logger.error(f"Feil ved behandling av GPS-innslag: {e}")
                st.error(f"Feil ved behandling av GPS-data: {e}")

        if not coordinates:
            st.warning("Ingen gyldige GPS-koordinater funnet i dataene.")
        
        return coordinates

    except Exception as e:
        logger.error(f"Uventet feil i get_gps_coordinates: {e}")
        st.error(f"Uventet feil ved henting av GPS-koordinater: {e}")
        return []
    
def display_gps_data(start_date, end_date):
    gps_entries = fetch_gps_data()

    with st.expander("Siste GPS aktivitet"):
        if gps_entries:
            # Konverter til DataFrame
            df = pd.DataFrame(gps_entries)

            # Sorter etter dato og få den siste aktiviteten for hver BILNR
            latest_activities = (
                df.sort_values("Date").groupby("BILNR").last().reset_index()
            )

            # Formater dato for visning
            latest_activities["Formatted Date"] = latest_activities["Date"].dt.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            # Vis dataframe med siste aktivitet for hver GPS
            st.dataframe(
                latest_activities[["BILNR", "Formatted Date"]], hide_index=True
            )

            # Vis antall unike GPS-enheter
            st.write(f"Antall unike GPS-enheter: {len(latest_activities)}")
        else:
            st.write("Ingen GPS-aktivitet funnet.")    