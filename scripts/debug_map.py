#!/usr/bin/env python3
"""
Dette scriptet feilsøker problemer med tunbrøytingskartet.
Det sjekker spesifikt:
1. Om bestillingene blir hentet for riktig dato
2. Om koordinatene er riktige
3. Om filtreringen fungerer som den skal
4. Om datohåndteringen er korrekt
5. Om duplikate bestillinger håndteres riktig
6. Om alle hytter vises på kartet
"""

import sys
from datetime import datetime
from pathlib import Path
import pandas as pd

# Legg til prosjektets rotmappe i Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from utils.core.config import TZ
from utils.core.util_functions import filter_todays_bookings
from utils.services.tun_utils import get_bookings, hent_aktive_bestillinger_for_dag
from utils.services.map_utils import get_cabin_coordinates, vis_dagens_tunkart


def debug_bookings_for_date(test_date):
    """Sjekker bestillinger for en spesifikk dato"""
    print(f"\n=== DEBUG BESTILLINGER FOR {test_date.strftime('%d.%m.%Y')} ===")
    
    # 1. Hent alle bestillinger
    alle_bestillinger = get_bookings()
    print(f"\nTotalt antall bestillinger: {len(alle_bestillinger)}")
    
    if not alle_bestillinger.empty:
        # Sjekk duplikate bestillinger
        print("\nSjekker duplikate bestillinger...")
        duplikater = alle_bestillinger.groupby(['customer_id', 'ankomst_dato']).size()
        duplikater = duplikater[duplikater > 1]
        if not duplikater.empty:
            print("\nFant duplikate bestillinger:")
            for (hytte, dato), antall in duplikater.items():
                print(f"Hytte {hytte} har {antall} bestillinger på {dato}")
        
        # Vis alle bestillinger
        print("\nAlle bestillinger:")
        for _, booking in alle_bestillinger.iterrows():
            print(f"\nHytte: {booking['customer_id']}")
            print(f"Type: {booking['abonnement_type']}")
            print(f"Ankomst: {booking['ankomst_dato']}")
            print(f"Avreise: {booking['avreise_dato']}")
    
    # 2. Sjekk aktive bestillinger for test-datoen
    aktive = hent_aktive_bestillinger_for_dag(test_date.date())
    print(f"\nAktive bestillinger for datoen: {len(aktive)}")
    
    if not aktive.empty:
        print("\nAktive bestillinger:")
        for _, booking in aktive.iterrows():
            print(f"\nHytte: {booking['customer_id']}")
            print(f"Type: {booking['abonnement_type']}")
            print(f"Ankomst: {booking['ankomst_dato']}")
            print(f"Avreise: {booking['avreise_dato']}")
            
    return aktive


def debug_coordinates():
    """Sjekker koordinater for hyttene"""
    print("\n=== DEBUG KOORDINATER ===")
    
    coords = get_cabin_coordinates()
    print(f"\nAntall hytter med koordinater: {len(coords)}")
    
    if coords:
        print("\nEksempel på koordinater:")
        for cabin_id, (lat, lon) in list(coords.items())[:3]:
            print(f"Hytte {cabin_id}: ({lat}, {lon})")
            
        # Sjekk etter ugyldige koordinater
        invalid = []
        for cabin_id, (lat, lon) in coords.items():
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                invalid.append((cabin_id, lat, lon))
        
        if invalid:
            print("\nFant ugyldige koordinater:")
            for cabin_id, lat, lon in invalid:
                print(f"Hytte {cabin_id}: ({lat}, {lon})")
                
        # Sjekk om alle hytter har koordinater
        bestillinger = get_bookings()
        if not bestillinger.empty:
            mangler_coords = []
            for _, booking in bestillinger.iterrows():
                if str(booking['customer_id']) not in coords:
                    mangler_coords.append(booking['customer_id'])
            if mangler_coords:
                print("\nHytter med bestillinger som mangler koordinater:")
                for hytte in mangler_coords:
                    print(f"Hytte {hytte}")
                
    return coords


def debug_filtering(test_date, bestillinger):
    """Tester filtreringsfunksjonen"""
    print(f"\n=== DEBUG FILTRERING FOR {test_date.strftime('%d.%m.%Y')} ===")
    
    if bestillinger.empty:
        print("Ingen bestillinger å filtrere")
        return None
    
    # Konverter datoer til datetime med tidssone
    for col in ['ankomst_dato', 'avreise_dato']:
        if col in bestillinger.columns:
            bestillinger[col] = pd.to_datetime(bestillinger[col])
            if bestillinger[col].dt.tz is None:
                bestillinger[col] = bestillinger[col].dt.tz_localize(TZ)
    
    # Test filtrering
    filtrerte = filter_todays_bookings(bestillinger)
    print(f"\nAntall bestillinger etter filtrering: {len(filtrerte)}")
    
    if not filtrerte.empty:
        # Sjekk om vi har duplikater etter filtrering
        duplikater = filtrerte.groupby('customer_id').size()
        duplikater = duplikater[duplikater > 1]
        if not duplikater.empty:
            print("\nFant duplikate bestillinger etter filtrering:")
            for hytte, antall in duplikater.items():
                print(f"Hytte {hytte} har {antall} aktive bestillinger")
        
        print("\nFiltrerte bestillinger:")
        for _, booking in filtrerte.iterrows():
            print(f"\nHytte: {booking['customer_id']}")
            print(f"Type: {booking['abonnement_type']}")
            print(f"Ankomst: {booking['ankomst_dato']}")
            print(f"Avreise: {booking['avreise_dato']}")
            
    return filtrerte


def debug_map_generation(test_date, bestillinger, coords):
    """Tester generering av kartet"""
    print(f"\n=== DEBUG KARTGENERERING FOR {test_date.strftime('%d.%m.%Y')} ===")
    
    if bestillinger.empty:
        print("Ingen bestillinger å vise på kartet")
        return
        
    # Test kartgenerering med dummy token
    test_token = "dummy_token"
    fig = vis_dagens_tunkart(
        bestillinger, 
        test_token, 
        f"Test kart for {test_date.strftime('%d.%m.%Y')}"
    )
    
    if fig is None:
        print("Kunne ikke generere kart")
        return
        
    print("\nKartgenerering vellykket")
    print(f"Antall datapunkter på kartet: {len(fig.data)}")
    
    # Analyser markører på kartet
    markers = {
        'blue': 0,  # Årsabonnement
        'red': 0,   # Ukentlig
        'gray': 0   # Inaktive
    }
    
    for trace in fig.data:
        if hasattr(trace, 'marker') and hasattr(trace.marker, 'color'):
            color = trace.marker.color
            if color in markers:
                markers[color] += 1
                
    print("\nMarkører på kartet:")
    print(f"Årsabonnement (blå): {markers['blue']}")
    print(f"Ukentlig (rød): {markers['red']}")
    print(f"Inaktive (grå): {markers['gray']}")
    
    # Sjekk om alle hytter er på kartet
    total_hytter = len(coords)
    total_markorer = sum(markers.values())
    if total_markorer != total_hytter:
        print(f"\nADVARSEL: Kartet viser {total_markorer} hytter, men vi har {total_hytter} hytter med koordinater")


def debug_timezone_handling(test_date):
    """Tester tidssonebehandling"""
    print(f"\n=== DEBUG TIDSSONER FOR {test_date.strftime('%d.%m.%Y')} ===")
    
    # Hent bestillinger
    bestillinger = get_bookings()
    if bestillinger.empty:
        print("Ingen bestillinger å teste")
        return
        
    # Sjekk tidssoner i datokolonner
    for col in ['ankomst_dato', 'avreise_dato']:
        if col in bestillinger.columns:
            print(f"\nSjekker tidssoner for {col}:")
            
            # Konverter til datetime hvis ikke allerede gjort
            if not pd.api.types.is_datetime64_any_dtype(bestillinger[col]):
                bestillinger[col] = pd.to_datetime(bestillinger[col])
            
            # Tell bestillinger uten tidssone
            mangler_tz = bestillinger[bestillinger[col].dt.tz is None]
            antall_mangler = len(mangler_tz)
            if antall_mangler > 0:
                print(f"Fant {antall_mangler} bestillinger uten tidssone:")
                for _, booking in mangler_tz.iterrows():
                    print(f"Hytte {booking['customer_id']}: {booking[col]}")
            else:
                print("Alle bestillinger har tidssone")
                
            # Vis unike tidssoner
            har_tz = bestillinger[bestillinger[col].dt.tz is not None]
            if not har_tz.empty:
                unike_tz = har_tz[col].dt.tz.unique()
                print("\nUnike tidssoner funnet:")
                for tz in unike_tz:
                    print(f"- {tz}")


def debug_database():
    """Sjekker databasen direkte"""
    print("\n=== DEBUG DATABASE ===")
    
    try:
        from utils.db.connection import get_db_connection
        
        with get_db_connection("tunbroyting") as conn:
            cursor = conn.cursor()
            
            # Sjekk tabellstruktur
            print("\nTabellstruktur:")
            cursor.execute("PRAGMA table_info(tunbroyting_bestillinger)")
            for col in cursor.fetchall():
                print(f"- {col[1]}: {col[2]}")
            
            # Sjekk alle bestillinger
            print("\nAlle rader i databasen:")
            cursor.execute("""
                SELECT id, customer_id, ankomst_dato, avreise_dato, 
                       abonnement_type, created_at, updated_at
                FROM tunbroyting_bestillinger
                ORDER BY ankomst_dato
            """)
            rows = cursor.fetchall()
            
            if rows:
                for row in rows:
                    print("\nBestilling:")
                    print(f"ID: {row[0]}")
                    print(f"Hytte: {row[1]}")
                    print(f"Ankomst: {row[2]}")
                    print(f"Avreise: {row[3]}")
                    print(f"Type: {row[4]}")
                    print(f"Opprettet: {row[5]}")
                    print(f"Oppdatert: {row[6]}")
            else:
                print("Ingen bestillinger funnet i databasen")
                
            # Sjekk om vi har noen ugyldige datoer
            print("\nSjekker etter ugyldige datoer...")
            cursor.execute("""
                SELECT id, customer_id, ankomst_dato, avreise_dato
                FROM tunbroyting_bestillinger
                WHERE ankomst_dato NOT LIKE '____-__-__ __:__:__'
                   OR (avreise_dato IS NOT NULL 
                       AND avreise_dato NOT LIKE '____-__-__ __:__:__')
            """)
            ugyldige = cursor.fetchall()
            if ugyldige:
                print("\nFant ugyldige datoformater:")
                for row in ugyldige:
                    print(f"ID {row[0]} (Hytte {row[1]}):")
                    print(f"Ankomst: {row[2]}")
                    print(f"Avreise: {row[3]}")
            
            # Sjekk etter overlappende bestillinger
            print("\nSjekker etter overlappende bestillinger...")
            cursor.execute("""
                WITH overlapp AS (
                    SELECT a.id as id1, 
                           b.id as id2,
                           a.customer_id,
                           a.ankomst_dato as ankomst1,
                           a.avreise_dato as avreise1,
                           b.ankomst_dato as ankomst2,
                           b.avreise_dato as avreise2
                    FROM tunbroyting_bestillinger a
                    JOIN tunbroyting_bestillinger b ON a.customer_id = b.customer_id
                    WHERE a.id < b.id
                    AND (
                        (a.ankomst_dato BETWEEN b.ankomst_dato AND COALESCE(b.avreise_dato, b.ankomst_dato))
                        OR
                        (COALESCE(a.avreise_dato, a.ankomst_dato) BETWEEN b.ankomst_dato AND COALESCE(b.avreise_dato, b.ankomst_dato))
                    )
                )
                SELECT * FROM overlapp
            """)
            overlappende = cursor.fetchall()
            if overlappende:
                print("\nFant overlappende bestillinger:")
                for row in overlappende:
                    print(f"\nHytte {row[2]}:")
                    print(f"Bestilling 1 (ID {row[0]}): {row[3]} -> {row[4]}")
                    print(f"Bestilling 2 (ID {row[1]}): {row[5]} -> {row[6]}")
            
    except Exception as e:
        print(f"Feil ved databasesjekk: {str(e)}")
        raise


def main():
    """Hovedfunksjon som kjører alle debug-funksjonene"""
    try:
        print("\nStarter feilsøking av tunbrøytingskart...")
        
        # 1. Debug databasen
        debug_database()
        
        # Test dato (07.01.2025)
        test_date = datetime(2025, 1, 7, tzinfo=TZ)
        
        # 2. Debug bestillinger
        aktive_bestillinger = debug_bookings_for_date(test_date)
        
        # 3. Debug koordinater
        coords = debug_coordinates()
        
        # 4. Debug filtrering
        if aktive_bestillinger is not None:
            filtrerte = debug_filtering(test_date, aktive_bestillinger)
            
            # 5. Debug kartgenerering
            if filtrerte is not None and coords is not None:
                debug_map_generation(test_date, filtrerte, coords)
        
        # 6. Debug tidssonebehandling
        debug_timezone_handling(test_date)
        
        print("\nFeilsøking fullført!")
        
    except Exception as e:
        print(f"\nFeil under feilsøking: {str(e)}")
        raise


if __name__ == "__main__":
    main() 