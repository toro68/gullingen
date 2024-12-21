# gps_utils.py
# Hensikten er å hente ut dato og tidspunkt for siste brøyting, 
# dvs da GPS ble slått av. Og vise dette i display_gps_data
import json
import logging
import re
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Union

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup, Tag

from utils.core.config import TZ
from utils.core.logging_config import get_logger

logger = get_logger(__name__)

def parse_date(date_str):
    """Parse date string from various formats."""
    try:
        # Fjern $D prefix hvis det finnes
        if date_str.startswith('$D'):
            date_str = date_str[2:]
            
        # Prøv ulike datoformater
        formats = [
            '%Y-%m-%dT%H:%M:%S.%fZ',  # ISO format med millisekunder
            '%Y-%m-%dT%H:%M:%SZ',     # ISO format uten millisekunder
            '%Y-%m-%d %H:%M:%S',      # Standard datetime format
            '%Y-%m-%d'                 # Bare dato
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
                
        raise ValueError(f"Kunne ikke parse dato: {date_str}")
        
    except Exception as e:
        logger.debug(f"Feil ved parsing av dato '{date_str}': {e}")
        raise

def debug_date_data():
    """Debug-funksjon for å vise all datoinformasjon fra GPS-dataene."""
    try:
        logger.info("=== START DEBUG DATE DATA ===")
        
        # Hent GeoJSON data
        geojson_data = get_geojson_data()
        logger.info(f"GeoJSON data hentet: {'Ja' if geojson_data else 'Nei'}")
        
        if not geojson_data or "features" not in geojson_data:
            logger.info("Ingen features funnet i GeoJSON data")
            return
            
        # Analyser features
        logger.info(f"Antall features funnet: {len(geojson_data['features'])}")
        
        for i, feature in enumerate(geojson_data["features"]):
            logger.info(f"\nFeature {i+1}:")
            
            # Sjekk properties
            properties = feature.get("properties", {})
            logger.info(f"Properties nøkler: {list(properties.keys())}")
            
            # Vis alle dato-relaterte felter
            date_fields = ["lastUpdated", "Date", "timestamp", "created_at", "updated_at"]
            for field in date_fields:
                if field in properties:
                    logger.info(f"{field}: {properties[field]}")
            
            # Vis andre relevante felter
            if "BILNR" in properties:
                logger.info(f"BILNR: {properties['BILNR']}")
                
        logger.info("=== END DEBUG DATE DATA ===")
        
    except Exception as e:
        logger.error(f"Feil i debug_date_data: {e}")
        logger.error(traceback.format_exc())

def get_geojson_data() -> Dict:
    """Henter GeoJSON-data fra den eksterne nettsiden."""
    try:
        url = "https://plowman-new.xn--snbryting-m8ac.net/nb/share/Y3VzdG9tZXItMTM="
        response = requests.get(url, timeout=10)
        
        if not response.ok:
            print(f"Feil ved henting av data. Status: {response.status_code}")
            return {}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        scripts = soup.find_all('script')
        
        print(f"\nSøker gjennom {len(scripts)} script-tagger...")
        
        for i, script in enumerate(scripts):
            if not script.string:
                continue
                
            content = script.string.strip()
            
            # Vi vet at script 29 inneholder dataene
            if i == 28:  # 0-basert indeks for script 29
                print("\nAnalyserer script 29:")
                
                if 'self.__next_f.push' in content:
                    # Fjern JavaScript wrapper
                    content = content.replace('self.__next_f.push([1,"', '')
                    content = content.replace('"])', '')
                    # Fjern escaping
                    content = content.replace('\\"', '"')
                    
                    # Finn geojson-objektet
                    if '"geojson":' in content:
                        start_idx = content.find('"geojson":') + len('"geojson":')
                        
                        # Finn slutten av JSON-objektet ved å telle krøllparenteser
                        brace_count = 0
                        in_string = False
                        escape_next = False
                        end_idx = start_idx
                        
                        for idx, char in enumerate(content[start_idx:], start=start_idx):
                            if escape_next:
                                escape_next = False
                                continue
                                
                            if char == '\\':
                                escape_next = True
                                continue
                                
                            if char == '"' and not escape_next:
                                in_string = not in_string
                                continue
                                
                            if not in_string:
                                if char == '{':
                                    brace_count += 1
                                elif char == '}':
                                    brace_count -= 1
                                    if brace_count == 0:
                                        end_idx = idx + 1
                                        break
                        
                        try:
                            json_str = content[start_idx:end_idx]
                            print(f"\nEkstrahert JSON ({len(json_str)} tegn):")
                            print(f"Start: {json_str[:100]}")
                            print(f"Slutt: {json_str[-100:]}")
                            
                            data = json.loads(json_str)
                            if 'type' in data and 'features' in data:
                                print(f"\nSuksess! Fant {len(data['features'])} features")
                                return data
                            
                        except json.JSONDecodeError as e:
                            print(f"JSON parsing feilet: {str(e)}")
                            print(f"På posisjon: {e.pos}")
                            print(f"Linje: {e.lineno}, Kolonne: {e.colno}")
                            
        print("Ingen gyldig GPS-data funnet")
        return {}
        
    except Exception as e:
        print(f"Feil ved henting av GeoJSON-data: {str(e)}")
        import traceback
        print(f"Stacktrace:\n{traceback.format_exc()}")
        return {}

def fetch_gps_data() -> Optional[datetime]:
    """Henter siste brøytetidspunkt fra GeoJSON-data."""
    try:
        # Hent GeoJSON-data
        geojson_data = get_geojson_data()
        
        if not geojson_data or "features" not in geojson_data:
            logger.warning("Ingen gyldige GeoJSON-data funnet")
            return None
            
        # Finn nyeste tidspunkt
        latest_timestamp = None
        for feature in geojson_data["features"]:
            if "properties" in feature and "lastUpdated" in feature["properties"]:
                timestamp = feature["properties"]["lastUpdated"]
                if timestamp:  # Sjekk at datoen ikke er None
                    clean_timestamp = timestamp.replace('$D', '')
                    if not latest_timestamp or clean_timestamp > latest_timestamp:
                        latest_timestamp = clean_timestamp
        
        if latest_timestamp:
            return datetime.strptime(latest_timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
        return None
        
    except Exception as e:
        logger.error(f"Feil ved henting av GPS-data: {e}")
        return None

def get_last_gps_activity() -> Optional[datetime]:
    """Henter tidspunktet for siste GPS-aktivitet (brøyting)."""
    try:
        # Hent GeoJSON data ved hjelp av eksisterende funksjon
        geojson_data = get_geojson_data()
        
        if not geojson_data or "features" not in geojson_data:
            logger.warning("Ingen GPS-data funnet")
            return None
            
        # Finn nyeste tidspunkt
        latest_timestamp = None
        for feature in geojson_data.get("features", []):
            ts = feature.get("properties", {}).get("lastUpdated")
            if ts:
                clean_ts = ts.replace('$D', '')
                try:
                    dt = datetime.strptime(clean_ts, '%Y-%m-%dT%H:%M:%S.%fZ')
                    if latest_timestamp is None or dt > latest_timestamp:
                        latest_timestamp = dt
                except ValueError:
                    continue
        
        return latest_timestamp
        
    except Exception as e:
        logger.error(f"Feil ved henting av siste GPS-aktivitet: {e}")
        logger.error(traceback.format_exc())
        return None

def get_gps_coordinates():
    try:
        geojson_data = get_geojson_data()  # Hent GeoJSON-data
        if not geojson_data or "features" not in geojson_data:
            st.warning("Ingen GPS-data funnet.")
            return []

        coordinates = []
        for feature in geojson_data.get("features", []):
            try:
                geometry = feature.get("geometry", {})
                properties = feature.get("properties", {})
                
                if not geometry or not properties:
                    continue
                    
                coords = geometry.get("coordinates", [])
                if len(coords) != 2:
                    continue
                    
                lat, lon = coords
                bilnr = str(properties.get("BILNR", "Ukjent"))
                date = str(properties.get("lastUpdated", "Ukjent dato"))
                coordinates.append((float(lat), float(lon), bilnr, date))
                
            except Exception as e:
                logger.error(f"Feil ved behandling av GPS-innslag: {e}")
                continue

        if not coordinates:
            st.warning("Ingen gyldige GPS-koordinater funnet i dataene.")

        return coordinates

    except Exception as e:
        logger.error(f"Uventet feil i get_gps_coordinates: {e}")
        st.error(f"Uventet feil ved henting av GPS-koordinater: {e}")
        return []

def display_gps_data(start_date, end_date):
    """Viser siste GPS-aktivitet for brøyting."""
    geojson_data = get_geojson_data()

    with st.expander("Siste brøyteaktivitet"):
        if geojson_data and "features" in geojson_data:
            try:
                # Samle alle datoer med tilhørende BILNR
                activities = []
                for feature in geojson_data["features"]:
                    properties = feature.get("properties", {})
                    if "lastUpdated" in properties and "BILNR" in properties:
                        try:
                            date = parse_date(properties["lastUpdated"])
                            if date:
                                activities.append({
                                    "BILNR": properties["BILNR"],
                                    "Date": date
                                })
                        except ValueError:
                            continue

                if activities:
                    # Konverter til DataFrame
                    df = pd.DataFrame(activities)
                    
                    # Finn siste aktivitet per BILNR
                    latest_activities = df.sort_values("Date").groupby("BILNR").last().reset_index()
                    
                    # Formater dato for visning
                    latest_activities["Sist aktiv"] = latest_activities["Date"].dt.strftime(
                        "%d.%m.%Y kl. %H:%M"
                    )
                    
                    # Vis dataframe
                    st.dataframe(
                        latest_activities[["BILNR", "Sist aktiv"]], 
                        hide_index=True
                    )
                    
                    st.write(f"Antall aktive brøytebiler: {len(latest_activities)}")
                else:
                    st.write("Ingen gyldig brøyteaktivitet funnet.")
                    
            except Exception as e:
                logger.error(f"Feil ved visning av brøytedata: {e}")
                st.error("Kunne ikke vise brøytedata.")
        else:
            st.write("Ingen brøyteaktivitet registrert.")

def display_last_activity():
    last_activity = get_last_gps_activity()
    if isinstance(last_activity, datetime):
        formatted_time = last_activity.strftime("%d.%m.%Y kl. %H:%M")
        st.markdown(
            """
            <div style='padding: 10px; background-color: #f0f2f6; border-radius: 10px; margin: 10px 0;'>
                <h3 style='margin: 0; color: #1f2937;'>
                    🚜 Siste brøyting: <span style='color: #2563eb;'>{}</span>
                </h3>
            </div>
            """.format(formatted_time),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div style='padding: 10px; background-color: #f0f2f6; border-radius: 10px; margin: 10px 0;'>
                <h3 style='margin: 0; color: #1f2937;'>
                    🚜 Siste brøyting: <span style='color: #6b7280;'>Ingen data tilgjengelig</span>
                </h3>
            </div>
            """,
            unsafe_allow_html=True,
        )

def setup_debug_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def print_gps_debug():
    """Kjør denne funksjonen direkte fra kommandolinjen for å se GPS-data."""
    logger = setup_debug_logging()
    
    print("\n=== GPS DATA DEBUG ===")
    
    try:
        url = "https://plowman-new.xn--snbryting-m8ac.net/nb/share/Y3VzdG9tZXItMTM="
        print(f"\nHenter data fra: {url}")
        
        response = requests.get(url)
        print(f"Status kode: {response.status_code}")
        print(f"Content type: {response.headers.get('content-type')}")
        
        # Lagre raw response for inspeksjon
        print("\nRaw response preview:")
        print(response.text[:500])
        
        soup = BeautifulSoup(response.text, 'html.parser')
        scripts = soup.find_all('script')
        
        print(f"\nFant {len(scripts)} script-tagger")
        
        for i, script in enumerate(scripts):
            print(f"\nScript {i+1}:")
            if script.string:
                content = script.string.strip()
                print(f"Lengde: {len(content)} tegn")
                print(f"Start av innhold: {content[:200]}")
                
                if 'features' in content or 'geometry' in content:
                    print("!!! Potensiell GeoJSON funnet !!!")
                    print(f"Relevant del: {content[:500]}")
        
        print("\n=== SLUTT GPS DEBUG ===")
        
    except Exception as e:
        print(f"Feil: {str(e)}")
        import traceback
        print(traceback.format_exc())

def debug_gps_data():
    print("\n=== DEBUG GPS DATA ===")
    geojson_data = get_geojson_data()
    print(f"GeoJSON data: {json.dumps(geojson_data, indent=2)}")
    print("=== END DEBUG ===\n")

def parse_geojson(data: Dict) -> List[Dict]:
    """Parser GeoJSON-data og returnerer en liste med løypesegmenter."""
    løyper = []
    
    for feature in data.get('features', []):
        properties = feature.get('properties', {})
        geometry = feature.get('geometry', {})
        
        if geometry.get('type') != 'LineString':
            continue
            
        løype = {
            'id': feature.get('id'),
            'navn': properties.get('name'),
            'sist_oppdatert': properties.get('lastUpdated'),
            'koordinater': geometry.get('coordinates', [])
        }
        
        løyper.append(løype)
        
    return løyper

def get_latest_plowing_time(geojson_data):
    latest_timestamp = None
    for feature in geojson_data.get('features', []):
        timestamp = feature.get('properties', {}).get('lastUpdated')
        print(f"Fant tidspunkt: {timestamp}")  # Debug print
        if timestamp:
            clean_timestamp = timestamp.replace('$D', '')
            print(f"Renset tidspunkt: {clean_timestamp}")  # Debug print
            if not latest_timestamp or clean_timestamp > latest_timestamp:
                latest_timestamp = clean_timestamp
                print(f"Nytt siste tidspunkt: {latest_timestamp}")  # Debug print
    return latest_timestamp

if __name__ == "__main__":
    import json
    from datetime import datetime

    import requests
    from bs4 import BeautifulSoup
    
    print("\nHenter brøytedata fra Fjellbergsskardet...")
    
    try:
        url = "https://plowman-new.xn--snbryting-m8ac.net/nb/share/Y3VzdG9tZXItMTM="
        response = requests.get(url, timeout=10)
        
        if not response.ok:
            print(f"Feil ved henting av data. Status: {response.status_code}")
            exit(1)
            
        soup = BeautifulSoup(response.text, 'html.parser')
        scripts = soup.find_all('script')
        
        for script in scripts:
            if script.string and 'self.__next_f.push' in script.string:
                content = script.string.strip()
                if '"geojson":' in content:
                    start = content.find('"geojson":') + len('"geojson":')
                    end = content.find('"}])', start)
                    json_str = content[start:end]
                    data = json.loads(json_str)
                    
                    latest = None
                    for f in data.get("features", []):
                        ts = f.get("properties", {}).get("lastUpdated")
                        if ts:
                            clean_ts = ts.replace('$D', '')
                            if not latest or clean_ts > latest:
                                latest = clean_ts
                    
                    if latest:
                        dt = datetime.strptime(latest, '%Y-%m-%dT%H:%M:%S.%fZ')
                        print(f"\n🚜 Sist brøytet: {dt.strftime('%d.%m.%Y kl. %H:%M')}\n")
                        exit(0)
        
        print("\n❌ Fant ingen brøytedata\n")
        
    except Exception as e:
        print(f"\n❌ Feil: {str(e)}\n")
        exit(1)
