import pandas as pd
import numpy as np
from datetime import timedelta
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from alert_utils import get_alerts
from weather_utils import (
    get_weather_data_for_period, 
    get_latest_alarms, 
    fetch_and_process_data, 
    get_csv_download_link,
    get_available_columns,
    get_default_columns
)

from logging_config import get_logger
from util_functions import get_date_range

logger = get_logger(__name__)

# Funksjoner for å vise data og grensesnitt
@st.cache_data
def get_cached_weather_data(client_id, start_date, end_date):
    return get_weather_data_for_period(client_id, start_date, end_date)

def display_weather_data(df):
    """
    Viser værdata i form av grafer og tabeller
    
    Args:
        df (pandas.DataFrame): DataFrame med værdata
    """
    try:
        if df is None or df.empty:
            st.error("Ingen værdata mottatt. Vennligst sjekk tilkoblingen og prøv igjen.")
            return

        # Opprett faner for ulike seksjoner
        tab1, tab2, tab3 = st.tabs(["🌡️ Hovedgraf", "📊 Andre værdata", "📈 Værstatistikk"])

        with tab1:
            st.subheader("Væroversikt")
            fig = create_improved_graph(df)
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False}
            )

        with tab2:
            st.subheader("Andre værdata")
            display_additional_data(df, df.columns)

        with tab3:
            st.subheader("Værstatistikk")
            display_weather_statistics(df, df.columns)

    except Exception as e:
        st.error(f"Uventet feil ved visning av værdata: {str(e)}")
        logger.error(f"Uventet feil i display_weather_data: {str(e)}", exc_info=True)

def create_improved_graph(df):
    """
    Lager en forbedret graf med værdata
    
    Args:
        df (pd.DataFrame): DataFrame med værdata
    """
    fig = make_subplots(
        rows=6,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=(
            "Lufttemperatur",
            "Nedbør",
            "Antatt snønedbør",
            "Snødybde",
            "Vind",
            "Alarmer",
        ),
    )

    trace_data = {}
    
    # Legg kun til spor for kolonner som finnes i DataFrame
    if 'air_temperature' in df.columns:
        trace_data["Lufttemperatur"] = {
            "data": df["air_temperature"],
            "color": "darkred",
            "type": "scatter",
            "row": 1,
            "units": "°C",
        }
    
    if 'precipitation_amount' in df.columns:
        trace_data["Nedbør"] = {
            "data": df["precipitation_amount"],
            "color": "blue",
            "type": "bar",
            "row": 2,
            "units": "mm",
        }
    
    if 'snow_precipitation' in df.columns:
        trace_data["Antatt snønedbør"] = {
            "data": df["snow_precipitation"],
            "color": "lightblue",
            "type": "bar",
            "row": 3,
            "units": "mm",
        }
    
    if 'surface_snow_thickness' in df.columns:
        trace_data["Snødybde"] = {
            "data": df["surface_snow_thickness"],
            "color": "cyan",
            "type": "scatter",
            "row": 4,
            "units": "cm",
        }
    
    if 'wind_speed' in df.columns:
        trace_data["Vindhastighet"] = {
            "data": df["wind_speed"],
            "color": "green",
            "type": "scatter",
            "row": 5,
            "units": "m/s",
        }
    
    if 'max_wind_speed' in df.columns:
        trace_data["Maks vindhastighet"] = {
            "data": df["max_wind_speed"],
            "color": "darkgreen",
            "type": "scatter",
            "row": 5,
            "units": "m/s",
        }

    # Legg til spor for tilgjengelige data
    for title, data in trace_data.items():
        hovertemplate = (
            f"{title}<br>"
            f"Verdi: %{{y:.1f}} {data['units']}<br>"
            f"Tid: %{{x|%Y-%m-%d %H:%M}}"
        )
        if data["type"] == "scatter":
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=data["data"],
                    name=title,
                    line=dict(color=data["color"]),
                    hovertemplate=hovertemplate,
                ),
                row=data["row"],
                col=1,
            )
        elif data["type"] == "bar":
            fig.add_trace(
                go.Bar(
                    x=df.index,
                    y=data["data"],
                    name=title,
                    marker_color=data["color"],
                    hovertemplate=hovertemplate,
                ),
                row=data["row"],
                col=1,
            )

    # Add freezing point reference line for temperature if temperature data exists
    if 'air_temperature' in df.columns:
        fig.add_hline(y=0, line_dash="dash", line_color="blue", row=1, col=1)

    # Add alarm traces if they exist
    if 'snow_drift_alarm' in df.columns:
        snow_drift_alarms = df[df["snow_drift_alarm"] == 1]
        fig.add_trace(
            go.Scatter(
                x=snow_drift_alarms.index,
                y=[1] * len(snow_drift_alarms),
                mode="markers",
                name="Snøfokk-alarm",
                marker=dict(symbol="star", size=12, color="blue"),
                hovertemplate="Snøfokk-alarm<br>%{x|%Y-%m-%d %H:%M}",
            ),
            row=6,
            col=1,
        )

    if 'slippery_road_alarm' in df.columns:
        slippery_road_alarms = df[df["slippery_road_alarm"] == 1]
        fig.add_trace(
            go.Scatter(
                x=slippery_road_alarms.index,
                y=[0.5] * len(slippery_road_alarms),
                mode="markers",
                name="Glatt vei-alarm",
                marker=dict(symbol="triangle-up", size=12, color="red"),
                hovertemplate="Glatt vei-alarm<br>%{x|%Y-%m-%d %H:%M}",
            ),
            row=6,
            col=1,
        )

    # Determine x-axis ticks based on the data period
    date_range = df.index.max() - df.index.min()
    if date_range <= timedelta(days=1):
        dtick = "H2"  # Every 2 hours
        tickformat = "%H:%M"
    elif date_range <= timedelta(days=7):
        dtick = "D1"  # Daily
        tickformat = "%d.%m"
    elif date_range <= timedelta(days=31):
        dtick = "D7"  # Weekly
        tickformat = "%d.%m"
    else:
        dtick = "M1"  # Monthly
        tickformat = "%b %Y"

    # Update layout
    fig.update_layout(
        height=1400,
        title_text="Værdataoversikt",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=50, b=50),
    )

    # Update x and y axes
    for i in range(1, 7):
        fig.update_xaxes(
            title_text="Dato" if i == 6 else "",
            type="date",
            tickformat=tickformat,
            dtick=dtick,
            tickangle=45,
            row=i,
            col=1,
        )
        if i < 6:  # Skip the last row (alarms)
            available_titles = list(trace_data.keys())
            if i - 1 < len(available_titles):
                title = available_titles[i - 1]
                units = trace_data[title]["units"]
                fig.update_yaxes(title_text=f"{title} ({units})", row=i, col=1)
            else:
                fig.update_yaxes(title_text="", row=i, col=1)

    # Special case for the alarms row
    fig.update_yaxes(
        title_text="Alarmer",
        row=6,
        col=1,
        tickmode="array",
        tickvals=[0, 0.5, 1],
        ticktext=["", "Glatt vei", "Snøfokk"],
    )

    # Ensure each subplot uses its own y-axis
    for i in range(1, 7):
        fig.update_yaxes(matches=None, row=i, col=1)

    # Add annotations for extreme values
    if 'air_temperature' in df.columns:
        max_temp_idx = df["air_temperature"].idxmax()
        min_temp_idx = df["air_temperature"].idxmin()
        
        fig.add_annotation(
            x=max_temp_idx,
            y=df.loc[max_temp_idx, "air_temperature"],
            text=f"Max: {df.loc[max_temp_idx, 'air_temperature']:.1f}°C",
            showarrow=True,
            arrowhead=2,
            row=1,
            col=1,
        )
        fig.add_annotation(
            x=min_temp_idx,
            y=df.loc[min_temp_idx, "air_temperature"],
            text=f"Min: {df.loc[min_temp_idx, 'air_temperature']:.1f}°C",
            showarrow=True,
            arrowhead=2,
            row=1,
            col=1,
        )

    if 'max_wind_speed' in df.columns:
        max_wind_idx = df["max_wind_speed"].idxmax()
        fig.add_annotation(
            x=max_wind_idx,
            y=df.loc[max_wind_idx, "max_wind_speed"],
            text=f"Max: {df.loc[max_wind_idx, 'max_wind_speed']:.1f} m/s",
            showarrow=True,
            arrowhead=2,
            row=5,
            col=1,
        )

    return fig

def display_additional_data(df, available_columns):
    """Viser tilleggsdata basert på tilgjengelige kolonner"""
    if 'surface_temperature' in available_columns:
        with st.expander("🌡️ Overflatetemperatur - på bakken"):
            st.line_chart(df["surface_temperature"])
            st.write(f"Gjennomsnitt: {df['surface_temperature'].mean():.1f}°C")
            st.write(f"Minimum: {df['surface_temperature'].min():.1f}°C")
            st.write(f"Maksimum: {df['surface_temperature'].max():.1f}°C")

    if 'relative_humidity' in available_columns:
        with st.expander("💧 Relativ luftfuktighet"):
            st.line_chart(df["relative_humidity"])
            st.write(f"Gjennomsnitt: {df['relative_humidity'].mean():.1f}%")
            st.write(f"Minimum: {df['relative_humidity'].min():.1f}%")
            st.write(f"Maksimum: {df['relative_humidity'].max():.1f}%")

    if 'dew_point_temperature' in available_columns:
        with st.expander("❄️ Duggpunkt"):
            st.line_chart(df["dew_point_temperature"])
            st.write(f"Gjennomsnitt: {df['dew_point_temperature'].mean():.1f}°C")
            st.write(f"Minimum: {df['dew_point_temperature'].min():.1f}°C")
            st.write(f"Maksimum: {df['dew_point_temperature'].max():.1f}°C")

    display_alarms(df, available_columns)
    display_wind_data(df, available_columns)

def display_wind_data(df, available_columns):
    """Viser vinddata hvis tilgjengelig"""
    required_columns = ['wind_speed', 'max_wind_speed', 'wind_direction_category']
    if not all(col in available_columns for col in required_columns):
        return

    with st.expander("Detaljert vinddata"):
        st.subheader("Vindhastighetsprofil")
        wind_fig = go.Figure()
        wind_fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["wind_speed"],
                mode="lines",
                name="Gjennomsnittlig vindhastighet",
            )
        )
        wind_fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["max_wind_speed"],
                mode="lines",
                name="Maks vindhastighet",
            )
        )
        wind_fig.update_layout(
            title="Vindhastighetsprofil over tid",
            xaxis_title="Tid",
            yaxis_title="Vindhastighet (m/s)",
        )
        st.plotly_chart(wind_fig)

        if 'wind_direction_category' in available_columns:
            st.subheader("Vindretningsfordeling")
            wind_direction_counts = df["wind_direction_category"].value_counts()
            directions = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
            values = [wind_direction_counts.get(d, 0) for d in directions]

            wind_direction_fig = go.Figure(
                data=[
                    go.Barpolar(r=values, theta=directions, marker_color="rgb(106,81,163)")
                ]
            )
            wind_direction_fig.update_layout(
                title="Fordeling av vindretninger",
                polar=dict(
                    radialaxis=dict(visible=True, range=[0, max(values)]),
                    angularaxis=dict(direction="clockwise"),
                ),
            )
            st.plotly_chart(wind_direction_fig)

def display_alarms(df, available_columns):
    with st.expander("Snøfokk-alarmer"):
        st.write("Alarmene er basert på værdata og ikke direkte observasjoner")
        st.write("Kriterier: Vind > 6 m/s, temperatur ≤ -1°C, og enten:")
        st.write("1) nedbør  0.1 mm og endring i snødybde ≥ 1.0 cm, eller")
        st.write("2) nedbør > 0.1 mm og minking i snødybde ≥ 0.5 cm")
        snow_drift_alarms = df[df["snow_drift_alarm"] == 1]
        if not snow_drift_alarms.empty:
            st.dataframe(
                snow_drift_alarms[
                    [
                        "air_temperature",
                        "wind_speed",
                        "surface_snow_thickness",
                        "precipitation_amount",
                        "snow_depth_change",
                    ]
                ]
            )
            st.write(f"Totalt antall snøfokk-alarmer: {len(snow_drift_alarms)}")
        else:
            st.write("Ingen snøfokk-alarmer i den valgte perioden.")

    with st.expander("Glatt vei / slush-alarmer"):
        st.write("Alarmene er basert på værdata og ikke direkte observasjoner.")
        st.write(
            "Kriterier: Temperatur > 0°C, nedbør > 1.5 mm, snødybde ≥ 20 cm, og synkende snødybde."
        )
        slippery_road_alarms = df[df["slippery_road_alarm"] == 1]
        if not slippery_road_alarms.empty:
            st.dataframe(
                slippery_road_alarms[
                    [
                        "air_temperature",
                        "precipitation_amount",
                        "surface_snow_thickness",
                    ]
                ]
            )
            st.write(
                f"Totalt antall glatt vei / slush-alarmer: {len(slippery_road_alarms)}"
            )
        else:
            st.write("Ingen glatt vei / slush-alarmer i den valgte perioden.")

def display_weather_statistics(df, available_columns):
    """Viser statistikk for tilgjengelige kolonner"""
    stats_columns = {
        'air_temperature': 'Lufttemperatur (°C)',
        'precipitation_amount': 'Nedbør (mm)',
        'snow_precipitation': 'Antatt snønedbør (mm)',
        'surface_snow_thickness': 'Snødybde (cm)',
        'wind_speed': 'Vindhastighet (m/s)',
        'max_wind_speed': 'Maks vindhastighet (m/s)'
    }
    
    stats_data = {'Statistikk': ["Gjennomsnitt", "Median", "Minimum", "Maksimum", "Sum"]}
    
    for col, name in stats_columns.items():
        if col in available_columns:
            values = [
                f"{df[col].mean():.1f}",
                f"{df[col].median():.1f}",
                f"{df[col].min():.1f}",
                f"{df[col].max():.1f}",
                f"{df[col].sum():.1f}" if col in ['precipitation_amount', 'snow_precipitation'] else "N/A"
            ]
            stats_data[name] = values
    
    stats = pd.DataFrame(stats_data)
    st.table(stats)

def display_alarms_homepage():
    # Vis siste væralarmer
    try:
        client_id = st.secrets["api_keys"]["client_id"]
        latest_alarms = get_latest_alarms(client_id)
        
        if latest_alarms:
            with st.expander("Siste væralarmer", expanded=True):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("️ Siste glatt vei-alarm")
                    if latest_alarms['slippery_road']['time']:
                        st.write(f"Tidspunkt: {latest_alarms['slippery_road']['time']}")
                        st.write(f"Temperatur: {latest_alarms['slippery_road']['temp']}")
                        st.write(f"Nedbør: {latest_alarms['slippery_road']['precipitation']}")
                    else:
                        st.info("Ingen glatt vei-alarmer siste 7 dager")
                
                with col2:
                    st.subheader("❄️ Siste snøfokk-alarm")
                    if latest_alarms['snow_drift']['time']:
                        st.write(f"Tidspunkt: {latest_alarms['snow_drift']['time']}")
                        st.write(f"Vindhastighet: {latest_alarms['snow_drift']['wind']}")
                        st.write(f"Temperatur: {latest_alarms['snow_drift']['temp']}")
                    else:
                        st.info("Ingen snøfokk-alarmer siste 7 dager")
    except Exception as e:
        logger.error(f"Feil ved visning av væralarmer: {str(e)}")

def handle_weather_page():
    """
    Hovedfunksjon for å håndtere værdatavisningen.
    """
    client_id = st.secrets["api_keys"]["client_id"]
    
    # Legg til kolonnevelger
    st.sidebar.header("Innstillinger")
    
    available_columns = get_available_columns()
    default_columns = get_default_columns()
    
    selected_columns = st.sidebar.multiselect(
        "Velg kolonner som skal vises:",
        options=list(available_columns.keys()),
        default=default_columns,
        format_func=lambda x: available_columns[x]
    )
    
    period_options = [
        "Siste 24 timer",
        "Siste 7 dager",
        "Siste 12 timer",
        "Siste 4 timer",
        "Siden sist fredag",
        "Siden sist søndag",
        "Egendefinert periode",
        "Siste GPS-aktivitet til nå",
    ]
    period = st.selectbox("Velg en periode:", options=period_options)
    
    # Her bruker vi get_date_range fra util_functions
    start_date, end_date = get_date_range(period)
    
    if start_date is None or end_date is None:
        st.error(f"Kunne ikke hente datoområde for perioden: {period}")
    else:
        st.write(f"Henter data fra: {start_date.strftime('%d.%m.%Y kl. %H:%M')} til: {end_date.strftime('%d.%m.%Y kl. %H:%M')}")
        
        weather_data = fetch_and_process_data(client_id, start_date, end_date)
        if 'error' in weather_data:
            st.error(f"Feil ved henting av værdata: {weather_data['error']}")
        elif 'df' in weather_data:
            df = weather_data['df']
            
            # Filtrer DataFrame basert på valgte kolonner
            filtered_df = df[selected_columns]
            display_weather_data(filtered_df)

            # Generer nedlastingslink med valgte kolonner
            download_link = get_csv_download_link(df, selected_columns)
            st.markdown(download_link, unsafe_allow_html=True)
        else:
            st.error("Uventet feilformat fra værdatahenting")
