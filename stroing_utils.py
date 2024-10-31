import sqlite3
import pandas as pd
import traceback
import math
import altair as alt
import matplotlib.pyplot as plt

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import streamlit as st

from db_utils import get_db_connection

from constants import TZ

from logging_config import get_logger

logger = get_logger(__name__)

# Helper functions
def validate_date(date_string: str) -> bool:
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def update_stroing_table_structure():
    with get_db_connection('stroing') as conn:
        cursor = conn.cursor()
        try:
            # Lag en ny tabell uten 'status'-kolonnen
            cursor.execute('''
                CREATE TABLE stroing_bestillinger_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bruker TEXT NOT NULL,
                    bestillings_dato TEXT NOT NULL,
                    onske_dato TEXT NOT NULL
                )
            ''')
            
            # Kopier data fra den gamle tabellen til den nye
            cursor.execute('''
                INSERT INTO stroing_bestillinger_new (id, bruker, bestillings_dato, onske_dato)
                SELECT id, bruker, bestillings_dato, onske_dato FROM stroing_bestillinger
            ''')
            
            # Slett den gamle tabellen
            cursor.execute('DROP TABLE stroing_bestillinger')
            
            # Gi den nye tabellen det gamle navnet
            cursor.execute('ALTER TABLE stroing_bestillinger_new RENAME TO stroing_bestillinger')
            
            conn.commit()
            logger.info("Successfully updated stroing_bestillinger table structure")
            return True
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating stroing_bestillinger table structure: {e}")
            return False
        
# Create
def lagre_stroing_bestilling(user_id: str, onske_dato: str) -> bool:
    try:
        with get_db_connection('stroing') as conn:
            c = conn.cursor()
            bestillings_dato = datetime.now(TZ).isoformat()
            
            c.execute('''
            INSERT INTO stroing_bestillinger 
            (bruker, bestillings_dato, onske_dato)
            VALUES (?, ?, ?)
            ''', (user_id, bestillings_dato, onske_dato))
            
            conn.commit()
        
        logger.info(f"Ny strøingsbestilling lagret for bruker: {user_id}")
        return True
    except sqlite3.Error as e:
        logger.error(f"SQLite-feil ved lagring av strøingsbestilling: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Uventet feil ved lagring av strøingsbestilling: {str(e)}")
        return False

def bestill_stroing():
    if "title" not in st.session_state:
        st.session_state["title"] = "Bestill Strøing"
    st.title(st.session_state["title"])
    
    # Informasjonstekst
    st.info(
        """
    Strøing av stikkveier i Fjellbergsskardet Hyttegrend - Sesong 2024/2025

    - Vi strør veiene når brøytekontakten vurderer det som nødvendig og effektivt ut fra værforholdene. 
    - Hovedveien (Gullingvegen-Tjernet) blir alltid prioritert. Resten strøs på bestilling.
    - Ønsker du strøing av stikkveien din, kan du bestille dette her. 
    - Priser: Du betaler 500 kroner for sesongen, pluss 150 kroner for hver gang det strøs. 
    
    Tips ved glatte forhold:
    - Bruk piggdekk/kjetting
    - Ha med litt strøsand, spade og tau i bilen. 
    - Bruk strøsandkassene. Må stroppes etter bruk!
    - Brodder til beina
    """
    )

    # Generer liste med dagens dato og de neste 4 dagene
    today = datetime.now(TZ).date()
    available_dates = [today + timedelta(days=i) for i in range(5)]

    onske_dato = st.selectbox(
        "Velg dato for strøing:",
        available_dates,
        format_func=lambda x: x.strftime("%d.%m.%Y (%A)"),  # Viser ukedag i parentes
    )

    if onske_dato == today:
        st.warning(
            "Det tas forbehold om godkjenning fra brøytekontakten."
        )
    elif onske_dato.weekday() >= 5:  # Lørdag eller søndag
        st.warning("Det tas forbehold om godkjenning fra brøytekontakten.")

    if st.button("Bestill Strøing"):
        result = lagre_stroing_bestilling(st.session_state.user_id, onske_dato.isoformat())
        if result:
            st.success("Bestilling av strøing er registrert!")
            logger.info(f"Strøing order successfully registered for user {st.session_state.user_id}")
        else:
            st.error("Det oppstod en feil ved registrering av bestillingen. Vennligst prøv igjen senere.")
            logger.error(f"Failed to register strøing order for user {st.session_state.user_id}")

        st.info("Merk: Du vil bli fakturert kun hvis strøing utføres.")

    # Vis tidligere bestillinger én gang, med overskrift
    display_stroing_bookings(st.session_state.user_id, show_header=True)
    
# Read
@st.cache_data(ttl=60)  # Cache data for 60 sekunder
def hent_og_behandle_data():
    alle_bestillinger = hent_stroing_bestillinger()
    dagens_dato = datetime.now(TZ).date()
    sluttdato = dagens_dato + timedelta(days=4)
    daglig_aktivitet = {dagen.date(): 0 for dagen in pd.date_range(dagens_dato, sluttdato)}
    
    for _, bestilling in alle_bestillinger.iterrows():
        onske_dato = bestilling['onske_dato'].date()
        if onske_dato in daglig_aktivitet:
            daglig_aktivitet[onske_dato] += 1
    
    aktivitet_df = pd.DataFrame.from_dict(daglig_aktivitet, orient='index', columns=['Antall bestillinger'])
    aktivitet_df.index = pd.to_datetime(aktivitet_df.index)
    aktivitet_df.index = aktivitet_df.index.strftime('%Y-%m-%d')
    aktivitet_df.index.name = 'Dato'
    
    return aktivitet_df, alle_bestillinger

def hent_stroing_bestillinger():
    try:
        with get_db_connection('stroing') as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            ORDER BY onske_dato DESC, bestillings_dato DESC
            """
            df = pd.read_sql_query(query, conn)
        
        # Konverter dato-kolonner til datetime
        for col in ['bestillings_dato', 'onske_dato']:
            df[col] = pd.to_datetime(df[col])
        
        # Logg kolonnenavnene
        logger.info(f"Kolonner i stroing_bestillinger: {df.columns.tolist()}")
        
        return df
    except Exception as e:
        logger.error(f"Feil ved henting av strøing-bestillinger: {str(e)}")
        return pd.DataFrame()
       
def hent_bruker_stroing_bestillinger(user_id):
    try:
        with get_db_connection('stroing') as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            WHERE bruker = ? 
            ORDER BY bestillings_dato DESC
            """
            df = pd.read_sql_query(query, conn, params=(user_id,))
        
        # Konverter dato-kolonner til datetime
        for col in ['bestillings_dato', 'onske_dato']:
            df[col] = pd.to_datetime(df[col])
        
        return df
    except Exception as e:
        logger.error(f"Feil ved henting av strøing-bestillinger for bruker {user_id}: {str(e)}")
        return pd.DataFrame()
    
def hent_stroing_bestilling(bestilling_id: int) -> Optional[Dict[str, Any]]:
    try:
        with get_db_connection('stroing') as conn:
            query = "SELECT * FROM stroing_bestillinger WHERE id = ?"
            cursor = conn.cursor()
            cursor.execute(query, (bestilling_id,))
            result = cursor.fetchone()
            if result:
                return dict(zip([column[0] for column in cursor.description], result))
            return None
    except Exception as e:
        logger.error(f"Feil ved henting av strøingsbestilling {bestilling_id}: {str(e)}")
        return None

# def hent_utforte_stroingsbestillinger() -> pd.DataFrame:
#     try:
#         with get_db_connection('stroing') as conn:
#             query = """
#             SELECT * FROM stroing_bestillinger 
#             WHERE utfort_dato IS NOT NULL
#             ORDER BY utfort_dato DESC
#             """
#             df = pd.read_sql_query(query, conn)
        
#         for col in ['bestillings_dato', 'onske_dato', 'utfort_dato']:
#             df[col] = pd.to_datetime(df[col])
        
#         return df
#     except Exception as e:
#         logger.error(f"Feil ved henting av utførte strøingsbestillinger: {str(e)}")
#         return pd.DataFrame()
        
def count_stroing_bestillinger():
    with get_db_connection('stroing') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stroing_bestillinger")
        return cursor.fetchone()[0]

# Delete
# def slett_stroingsbestilling(bestilling_id):
#     try:
#         query = "DELETE FROM stroing_bestillinger WHERE id = ?"
#         with get_db_connection('stroing') as conn:
#             cursor = conn.cursor()
#             cursor.execute(query, (bestilling_id,))
#             conn.commit()
#         logger.info(f"Strøingsbestilling med ID {bestilling_id} ble slettet.")
#         return True
#     except Exception as e:
#         logger.error(f"Feil ved sletting av strøingsbestilling {bestilling_id}: {str(e)}")
#         return False

def admin_stroing_page():
    st.title("Håndter Strøing")

    # Sett opp datovelgere
    today = datetime.now(TZ).date()
    default_end_date = today + timedelta(days=7)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=today)
    with col2:
        end_date = st.date_input("Til dato", value=default_end_date, min_value=start_date)

    # Vis valgt periode
    st.write(f"Viser bestillinger fra {start_date} til {end_date}")

    try:
        # Hent data direkte fra database
        with get_db_connection('stroing') as conn:
            query = """
            SELECT * FROM stroing_bestillinger 
            ORDER BY onske_dato DESC, bestillings_dato DESC
            """
            all_bestillinger = pd.read_sql_query(query, conn)

        # Sikre at vi har data å jobbe med
        if all_bestillinger.empty:
            st.warning("Ingen strøingsbestillinger funnet.")
            return

        # Konverter datokolonner til datetime og håndter potensielle feil
        try:
            # Først, forsøk å parse datoene som ISO format
            all_bestillinger['bestillings_dato'] = pd.to_datetime(
                all_bestillinger['bestillings_dato'], 
                format='ISO8601', 
                errors='coerce'
            )
            all_bestillinger['onske_dato'] = pd.to_datetime(
                all_bestillinger['onske_dato'], 
                format='ISO8601', 
                errors='coerce'
            )
        except Exception as e:
            logger.warning(f"ISO8601 parsing failed, trying flexible parsing: {str(e)}")
            # Hvis ISO parsing feiler, prøv fleksibel parsing
            all_bestillinger['bestillings_dato'] = pd.to_datetime(
                all_bestillinger['bestillings_dato'], 
                errors='coerce'
            )
            all_bestillinger['onske_dato'] = pd.to_datetime(
                all_bestillinger['onske_dato'], 
                errors='coerce'
            )

        # Fjern rader med ugyldige datoer
        invalid_dates = all_bestillinger[
            all_bestillinger['onske_dato'].isna() | 
            all_bestillinger['bestillings_dato'].isna()
        ]
        
        if not invalid_dates.empty:
            st.warning(f"Fant {len(invalid_dates)} bestillinger med ugyldige datoer. Disse vil bli ekskludert.")
            with st.expander("Vis bestillinger med ugyldige datoer"):
                st.dataframe(invalid_dates[['id', 'bruker', 'bestillings_dato', 'onske_dato']])

        # Fjern rader med ugyldige datoer og reset index
        valid_bestillinger = all_bestillinger.dropna(subset=['onske_dato', 'bestillings_dato']).copy()
        valid_bestillinger.reset_index(drop=True, inplace=True)

        # Konverter 'onske_dato' til date for filtrering
        valid_bestillinger['onske_dato_date'] = valid_bestillinger['onske_dato'].dt.date

        # Filtrer bestillinger for den valgte perioden
        bestillinger = valid_bestillinger[
            (valid_bestillinger['onske_dato_date'] >= start_date) &
            (valid_bestillinger['onske_dato_date'] <= end_date)
        ]

        if bestillinger.empty:
            st.warning(f"Ingen gyldige strøingsbestillinger funnet for perioden {start_date} til {end_date}.")
            return

        # Beregn dager til (sikrere versjon)
        bestillinger['dager_til'] = (bestillinger['onske_dato'] - pd.Timestamp(today)).dt.days.astype('int32')

        # Vis daglig oppsummering
        st.subheader("Daglig oppsummering")
        daily_summary = bestillinger.groupby('onske_dato_date').size().reset_index(name="antall")
        for _, row in daily_summary.iterrows():
            st.write(f"{row['onske_dato_date']}: {row['antall']} bestilling(er)")

        # Vis detaljert oversikt over bestillinger
        st.subheader("Detaljert oversikt over strøingsbestillinger")
        for _, row in bestillinger.iterrows():
            col1, col2, col3 = st.columns([3, 2, 2])
            with col1:
                st.write(f"Hytte: {row['bruker']}")
            with col2:
                st.write(f"Bestilt: {row['bestillings_dato'].date()}")
            with col3:
                st.write(f"Ønsket dato: {row['onske_dato'].date()}")

        # Eksporter til CSV
        export_df = bestillinger[['id', 'bruker', 'bestillings_dato', 'onske_dato', 'dager_til']].copy()
        csv = export_df.to_csv(index=False)
        st.download_button(
            label="Last ned som CSV",
            data=csv,
            file_name=f"stroingsbestillinger_{start_date}_{end_date}.csv",
            mime="text/csv",
        )

    except Exception as e:
        st.error(f"En feil oppstod: {str(e)}")
        logger.error(f"Error in admin_stroing_page: {str(e)}", exc_info=True)
        st.code(traceback.format_exc())
        
# Database initialization and maintenance
def verify_stroing_data():
    with get_db_connection('stroing') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stroing_bestillinger")
        data = cursor.fetchall()
        logger.info(f"Current entries in stroing_bestillinger: {len(data)}")
        for row in data:
            logger.info(f"Row: {row}")

# Visninger
def display_stroing_bookings(user_id, show_header=False):
    if show_header:
        st.subheader("Dine tidligere strøing-bestillinger")

    previous_bookings = hent_bruker_stroing_bestillinger(user_id)

    if previous_bookings.empty:
        st.info("Du har ingen tidligere strøing-bestillinger.")
    else:
        for _, booking in previous_bookings.iterrows():
            with st.expander(
                f"Bestilling - Ønsket dato: {booking['onske_dato'].strftime('%Y-%m-%d')}"
            ):
                st.write(
                    f"Bestilt: {booking['bestillings_dato'].strftime('%Y-%m-%d %H:%M')}"
                )
                st.write(f"Ønsket dato: {booking['onske_dato'].strftime('%Y-%m-%d')}")
                
def vis_tidligere_stroingsbestillinger(bruker_id):
    bestillinger = hent_bruker_stroing_bestillinger(bruker_id)
    
    if bestillinger.empty:
        st.info("Du har ingen tidligere strøing-bestillinger.")
    else:
        st.subheader("Dine tidligere strøing-bestillinger")
        
        for _, bestilling in bestillinger.iterrows():
            with st.expander(f"Bestilling - Ønsket dato: {bestilling['onske_dato'].date()}"):
                st.write(f"Bestilt: {bestilling['bestillings_dato'].strftime('%Y-%m-%d %H:%M')}")
                st.write(f"Ønsket dato: {bestilling['onske_dato'].date()}")

    # Hent alle strøingsbestillinger
    alle_bestillinger = hent_stroing_bestillinger()

    # Beregn datointervallet
    today = datetime.now(TZ).date()
    date_range = [today + timedelta(days=i) for i in range(5)]

    # Filtrer bestillinger for de neste 5 dagene
    relevante_bestillinger = alle_bestillinger[
        (alle_bestillinger['onske_dato'].dt.date >= today) &
        (alle_bestillinger['onske_dato'].dt.date <= date_range[-1])
    ]

    # Lag en DataFrame med alle datoer og antall bestillinger
    date_df = pd.DataFrame({'dato': date_range})
    bestillinger_per_dag = relevante_bestillinger.groupby(relevante_bestillinger['onske_dato'].dt.date).size().reset_index(name='antall')
    bestillinger_per_dag.columns = ['dato', 'antall']

    # Kombiner dataframes for å inkludere dager uten bestillinger
    full_df = pd.merge(date_df, bestillinger_per_dag, on='dato', how='left').fillna(0)
    full_df['antall'] = full_df['antall'].astype(int)

    # Lag Altair chart
    chart = alt.Chart(full_df).mark_bar().encode(
        x=alt.X('dato:T', title='Dato', axis=alt.Axis(format='%d.%m', labelAngle=-45)),
        y=alt.Y('antall:Q', title='Antall bestillinger'),
        tooltip=['dato', 'antall']
    ).properties(
        width=600,
        height=400,
        title='Strøingsbestillinger de neste 5 dagene'
    )

    # Vis grafen
    st.altair_chart(chart, use_container_width=True)

    # Vis totalt antall bestillinger
    total_bestillinger = full_df['antall'].sum()
    st.info(f"Totalt antall bestillinger for perioden: {total_bestillinger}")

def vis_graf_stroing():
    st.subheader("Oversikt over strøingsbestillinger")
    st.info(
        """
        Strøing av veier i Fjellbergsskardet Hyttegrend utføres basert på bestillinger og værforhold.
        Hovedveien til kryss Kalvaknutvegen prioriteres alltid, mens stikkveier strøs ved bestilling. 
        """
    )

    aktivitet_df, alle_bestillinger = hent_og_behandle_data()

    # Logg informasjon om alle_bestillinger
    logger.info(f"Kolonner i alle_bestillinger: {alle_bestillinger.columns.tolist()}")
    logger.info(f"Antall rader i alle_bestillinger: {len(alle_bestillinger)}")

    if aktivitet_df.empty:
        st.info("Ingen strøingsbestillinger funnet for perioden.")
        return

    st.subheader("Daglig oversikt over strøingsbestillinger")
    st.table(aktivitet_df)

    st.subheader("Daglige strøingsbestillinger")
    
    y_min = 0
    y_max = aktivitet_df['Antall bestillinger'].max()
    y_max = max(5, math.ceil(y_max))
    
    chart = alt.Chart(aktivitet_df.reset_index()).mark_bar().encode(
        x=alt.X('Dato:O', axis=alt.Axis(labelAngle=0)),
        y=alt.Y('Antall bestillinger:Q', axis=alt.Axis(tickCount=y_max+1), scale=alt.Scale(domain=[y_min, y_max]))
    ).properties(width=600, height=400)

    # Bruk en unik nøkkel basert på nåværende tid for å tvinge oppdatering
    st.altair_chart(chart, use_container_width=True, key=f"stroing_chart_{datetime.now().timestamp()}")

    totalt_antall = aktivitet_df['Antall bestillinger'].sum()
    
    st.subheader("Oppsummering")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Totalt antall bestillinger", totalt_antall)
    
    # Sjekk om 'bruker' kolonnen eksisterer før vi prøver å bruke den
    if 'bruker' in alle_bestillinger.columns:
        unike_brukere = alle_bestillinger['bruker'].nunique()
        with col2:
            st.metric("Antall unike brukere", unike_brukere)
        st.info(f"{unike_brukere} unike brukere har lagt inn strøingsbestillinger for denne perioden.")
    else:
        logger.warning("'bruker' kolonne ikke funnet i alle_bestillinger")
        st.warning("Kunne ikke beregne antall unike brukere på grunn av manglende data.")
