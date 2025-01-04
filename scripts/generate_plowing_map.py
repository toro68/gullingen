#!/usr/bin/env python3
"""
Dette scriptet genererer et statisk kart over hyttene med fargekoding for abonnementstype.
Kartet bruker sirkel-markører med hyttenummer og forskjellige farger for ulike abonnementstyper.
"""

import os
from pathlib import Path
import pandas as pd
import folium
from folium import plugins

# Sett opp paths
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
CUSTOMERS_FILE = DATA_DIR / "customers.csv"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "kart.html"

def load_customer_data():
    """Laster kundedata fra CSV-filen."""
    if not CUSTOMERS_FILE.exists():
        raise FileNotFoundError(f"Kunne ikke finne {CUSTOMERS_FILE}")
    
    return pd.read_csv(CUSTOMERS_FILE)

def create_map(data):
    """Oppretter kartet med markører for hver hytte."""
    # Sett fast senterpunkt for kartet (midt i hyttefeltet)
    center_lat = 59.39184  # Midt i hyttefeltet
    center_lon = 6.42908   # Midt i hyttefeltet
    
    # Opprett basiskart med OpenStreetMap som standard
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles='OpenStreetMap'  # Bruker OpenStreetMap som standard
    )
    
    # Legg til alternative kartlag
    folium.TileLayer(
        tiles='cartodbpositron',
        name='Lyst bakgrunnskart',
        attr='© CartoDB',
        control=True
    ).add_to(m)
    
    # Legg til OpenStreetMap Norway for ekstra veidetaljer
    folium.TileLayer(
        tiles='https://opencache.statkart.no/gatekeeper/gk/gk.open_gmaps?layers=topo4&zoom={z}&x={x}&y={y}',
        name='Topografisk (Kartverket)',
        attr='© Kartverket',
        control=True
    ).add_to(m)
    
    # Legg til satellittkart som alternativ
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        name='Satellitt',
        attr='© Esri',
        control=True
    ).add_to(m)
    
    # Legg til lagkontroll
    folium.LayerControl().add_to(m)
    
    # Legg til markører for hver hytte
    for _, row in data.iterrows():
        # Bestem farge og abonnementstype
        if row['Subscription'] == 'star_white':
            color = '#4B9CD3'  # Lysere blå (#4B9CD3)
            abo_type = 'Årsabonnement'
        elif row['Subscription'] == 'star_red':
            color = 'red'
            abo_type = 'Ukentlig ved bestilling'
        else:
            color = 'gray'
            abo_type = 'Ingen abonnement'
        
        # Opprett sirkelmarkør med hyttenummer og abonnementstype
        folium.CircleMarker(
            location=[row['Latitude'], row['Longitude']],
            radius=10,
            popup=folium.Popup(
                f"Hytte {row['customer_id']}<br>{abo_type}",
                show=False  # Viser bare ved klikk
            ),
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            weight=2
        ).add_to(m)
        
        # Legg til permanent tekst med hyttenummer
        folium.map.Marker(
            location=[row['Latitude'], row['Longitude']],
            icon=folium.DivIcon(
                html=f'<div style="font-size: 12pt; color: white; text-shadow: 1px 1px 2px black;">{row["customer_id"]}</div>',
                icon_size=(25, 25),
                icon_anchor=(0, 0)
            )
        ).add_to(m)
    
    # Legg til tegnforklaring
    legend_html = '''
    <div style="position: fixed; bottom: 50px; left: 50px; z-index: 1000; 
         background-color: white; padding: 10px; border: 2px solid grey; 
         border-radius: 5px;">
        <p><strong>Tegnforklaring:</strong></p>
        <p><span style="color: #4B9CD3;">●</span> Årsabonnement</p>
        <p><span style="color: red;">●</span> Ukentlig ved bestilling</p>
        <p><span style="color: gray;">●</span> Ingen abonnement</p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    # Legg til målestokk
    folium.plugins.MeasureControl().add_to(m)
    
    return m

def main():
    """Hovedfunksjon som genererer kartet."""
    try:
        print("Laster kundedata...")
        data = load_customer_data()
        
        print("Genererer kart...")
        map_obj = create_map(data)
        
        print(f"Lagrer kart til {OUTPUT_FILE}...")
        map_obj.save(str(OUTPUT_FILE))
        
        print("Kart generert vellykket!")
        print(f"Åpne {OUTPUT_FILE} i en nettleser for å se resultatet.")
        
    except Exception as e:
        print(f"Feil ved generering av kart: {str(e)}")
        raise

if __name__ == "__main__":
    main() 