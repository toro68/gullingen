#!/usr/bin/env python3
import json
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo  # For tidssonekonvertering

import requests
from bs4 import BeautifulSoup

print("\nHenter siste brøytetidspunkt fra Fjellbergsskardet...")

try:
    url = "https://plowman-new.xn--snbryting-m8ac.net/nb/share/Y3VzdG9tZXItMTM="
    response = requests.get(url, timeout=10)
    
    if not response.ok:
        print(f"Feil ved henting av data. Status: {response.status_code}")
        exit(1)
        
    soup = BeautifulSoup(response.text, 'html.parser')
    scripts = soup.find_all('script')
    
    if len(scripts) >= 29:
        script = scripts[28]  # Script 29 (indeks 28)
        if script.string:
            content = script.string.strip()
            
            if 'self.__next_f.push' in content:
                content = content.replace('self.__next_f.push([1,"', '')
                content = content.replace('"])', '')
                content = content.replace('\\"', '"')
                
                if '{"dictionary"' in content:
                    start = content.find('{"dictionary"')
                    end = content.rfind('}') + 1
                    json_str = content[start:end]
                    data = json.loads(json_str)
                    
                    # Finn siste tidspunkt
                    latest_timestamp = None
                    for f in data.get('geojson', {}).get("features", []):
                        ts = f.get("properties", {}).get("lastUpdated")
                        if ts:
                            clean_ts = ts.replace('$D', '')
                            try:
                                # Debug utskrift før konvertering
                                dt_utc = datetime.strptime(clean_ts, '%Y-%m-%dT%H:%M:%S.%fZ')
                                print(f"\nDebug - Original UTC time: {dt_utc}")
                                
                                # Parse til UTC først
                                dt = datetime.strptime(clean_ts, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=ZoneInfo('UTC'))
                                print(f"Debug - With UTC timezone: {dt}")
                                
                                # Konverter til Oslo-tid
                                dt = dt.astimezone(ZoneInfo('Europe/Oslo'))
                                print(f"Debug - Converted to Oslo time: {dt}")
                                
                                if not latest_timestamp or dt > latest_timestamp:
                                    latest_timestamp = dt
                            except ValueError:
                                continue
                    
                    if latest_timestamp:
                        print(f"\n🚜 Siste brøyting: {latest_timestamp.strftime('%d.%m.%Y kl. %H:%M')}\n")
                        exit(0)
    
    print("\n❌ Fant ingen brøytedata\n")
    
except Exception as e:
    print(f"\n❌ Feil: {str(e)}\n")
    print("\nDetaljer:")
    print(traceback.format_exc())
    exit(1) 