import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.core.config import TZ
from utils.core.logging_config import get_logger
from utils.db.db_utils import get_db_connection
from utils.services.alert_utils import get_alerts

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
            st.error(
                "Ingen værdata mottatt. Vennligst sjekk tilkoblingen og prøv igjen."
            )
            return

        # Opprett faner for ulike seksjoner
        tab1, tab2, tab3 = st.tabs(
            ["🌡️ Hovedgraf", "📊 Andre værdata", "📈 Værstatistikk"]
        )

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
    # La brukeren velge hvilke grafer som skal vises
    available_plots = {
        "Lufttemperatur": True,
        "Nedbør": True,
        "Antatt snønedbør": True,
        "Snødybde": True,
        "Vind": True,
        "Alarmer": True,
    }

    selected_plots = st.multiselect(
        "Velg grafer som skal vises:",
        options=list(available_plots.keys()),
        default=list(available_plots.keys()),
    )

    # Beregn antall subplot rows basert på valgte grafer
    num_rows = len(selected_plots)
    if num_rows == 0:
        st.warning("Velg minst én graf å vise")
        return None

    fig = make_subplots(
        rows=num_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=selected_plots,
    )

    # Mapping mellom plot navn og row nummer
    row_mapping = {plot: i + 1 for i, plot in enumerate(selected_plots)}

    trace_data = {}

    # Legg kun til spor for valgte grafer og kolonner som finnes i DataFrame
    if "Lufttemperatur" in selected_plots and "air_temperature" in df.columns:
        trace_data["Lufttemperatur"] = {
            "data": df["air_temperature"],
            "color": "darkred",
            "type": "scatter",
            "row": row_mapping["Lufttemperatur"],
            "units": "°C",
        }

    if "Nedbør" in selected_plots and "precipitation_amount" in df.columns:
        trace_data["Nedbør"] = {
            "data": df["precipitation_amount"],
            "color": "blue",
            "type": "bar",
            "row": row_mapping["Nedbør"],
            "units": "mm",
        }

    if "Antatt snønedbør" in selected_plots and "snow_precipitation" in df.columns:
        trace_data["Antatt snønedbør"] = {
            "data": df["snow_precipitation"],
            "color": "lightblue",
            "type": "bar",
            "row": row_mapping["Antatt snønedbør"],
            "units": "mm",
        }

    if "Snødybde" in selected_plots and "surface_snow_thickness" in df.columns:
        trace_data["Snødybde"] = {
            "data": df["surface_snow_thickness"],
            "color": "cyan",
            "type": "scatter",
            "row": row_mapping["Snødybde"],
            "units": "cm",
        }

    if "Vind" in selected_plots and "max_wind_speed" in df.columns:
        trace_data["Vind"] = {
            "data": df["max_wind_speed"],
            "color": "purple",
            "type": "scatter",
            "row": row_mapping["Vind"],
            "units": "m/s",
        }

    if "Vind" in selected_plots and "max_wind_speed" in df.columns:
        trace_data["Maks vindhastighet"] = {
            "data": df["max_wind_speed"],
            "color": "darkgreen",
            "type": "scatter",
            "row": row_mapping["Vind"],
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
    if "Lufttemperatur" in selected_plots and "air_temperature" in df.columns:
        fig.add_hline(
            y=0,
            line_dash="dash",
            line_color="blue",
            row=row_mapping["Lufttemperatur"],
            col=1,
        )

    # Add alarm traces if they exist and if alarms are selected
    if "Alarmer" in selected_plots:
        if "snow_drift_alarm" in df.columns:
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
                row=row_mapping["Alarmer"],
                col=1,
            )

        if "slippery_road_alarm" in df.columns:
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
                row=row_mapping["Alarmer"],
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
        height=200 * num_rows,  # Juster høyde basert på antall grafer
        title_text="Værdataoversikt",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=50, b=50),
    )

    # Update x and y axes
    for i in range(1, num_rows + 1):
        fig.update_xaxes(
            title_text="Dato" if i == num_rows else "",
            type="date",
            tickformat=tickformat,
            dtick=dtick,
            tickangle=45,
            row=i,
            col=1,
        )
        if selected_plots[i - 1] != "Alarmer":  # Skip the alarms row
            available_titles = list(trace_data.keys())
            if i - 1 < len(available_titles):
                title = available_titles[i - 1]
                units = trace_data[title]["units"]
                fig.update_yaxes(title_text=f"{title} ({units})", row=i, col=1)
            else:
                fig.update_yaxes(title_text="", row=i, col=1)

    # Special case for the alarms row
    if "Alarmer" in selected_plots:
        alarm_row = row_mapping["Alarmer"]
        fig.update_yaxes(
            title_text="Alarmer",
            row=alarm_row,
            col=1,
            tickmode="array",
            tickvals=[0, 0.5, 1],
            ticktext=["", "Glatt vei", "Snøfokk"],
        )

    # Ensure each subplot uses its own y-axis
    for i in range(1, num_rows + 1):
        fig.update_yaxes(matches=None, row=i, col=1)

    # Add annotations for extreme values
    if "Lufttemperatur" in selected_plots and "air_temperature" in df.columns:
        max_temp_idx = df["air_temperature"].idxmax()
        min_temp_idx = df["air_temperature"].idxmin()

        fig.add_annotation(
            x=max_temp_idx,
            y=df.loc[max_temp_idx, "air_temperature"],
            text=f"Max: {df.loc[max_temp_idx, 'air_temperature']:.1f}°C",
            showarrow=True,
            arrowhead=2,
            row=row_mapping["Lufttemperatur"],
            col=1,
        )
        fig.add_annotation(
            x=min_temp_idx,
            y=df.loc[min_temp_idx, "air_temperature"],
            text=f"Min: {df.loc[min_temp_idx, 'air_temperature']:.1f}°C",
            showarrow=True,
            arrowhead=2,
            row=row_mapping["Lufttemperatur"],
            col=1,
        )

    if "Vind" in selected_plots and "max_wind_speed" in df.columns:
        max_wind_idx = df["max_wind_speed"].idxmax()
        fig.add_annotation(
            x=max_wind_idx,
            y=df.loc[max_wind_idx, "max_wind_speed"],
            text=f"Max: {df.loc[max_wind_idx, 'max_wind_speed']:.1f} m/s",
            showarrow=True,
            arrowhead=2,
            row=row_mapping["Vind"],
            col=1,
        )

    return fig


def display_additional_data(df, available_columns):
    """Viser tilleggsdata basert på tilgjengelige kolonner"""
    if "surface_temperature" in available_columns:
        with st.expander("🌡️ Overflatetemperatur - på bakken"):
            st.line_chart(df["surface_temperature"])
            st.write(f"Gjennomsnitt: {df['surface_temperature'].mean():.1f}°C")
            st.write(f"Minimum: {df['surface_temperature'].min():.1f}°C")
            st.write(f"Maksimum: {df['surface_temperature'].max():.1f}°C")

    if "relative_humidity" in available_columns:
        with st.expander("💧 Relativ luftfuktighet"):
            st.line_chart(df["relative_humidity"])
            st.write(f"Gjennomsnitt: {df['relative_humidity'].mean():.1f}%")
            st.write(f"Minimum: {df['relative_humidity'].min():.1f}%")
            st.write(f"Maksimum: {df['relative_humidity'].max():.1f}%")

    if "dew_point_temperature" in available_columns:
        with st.expander("❄️ Duggpunkt"):
            st.line_chart(df["dew_point_temperature"])
            st.write(f"Gjennomsnitt: {df['dew_point_temperature'].mean():.1f}°C")
            st.write(f"Minimum: {df['dew_point_temperature'].min():.1f}°C")
            st.write(f"Maksimum: {df['dew_point_temperature'].max():.1f}°C")

    display_alarms(df, available_columns)
    display_wind_data(df, available_columns)


def display_wind_data(df, available_columns):
    """Viser vinddata hvis tilgjengelig"""
    # Endre required_columns til kun å sjekke max_wind_speed
    required_columns = ["max_wind_speed"]
    if not all(col in available_columns for col in required_columns):
        return

    with st.expander("Detaljert vinddata"):
        st.subheader("Vindhastighetsprofil")
        wind_fig = go.Figure()
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


def display_alarms(df, available_columns):
    with st.expander("Snøfokk-alarmer"):
        st.write("Alarmene er basert på værdata og ikke direkte observasjoner")
        st.write("Kriterier: Vind > 6 m/s, temperatur ≤ -1°C, og enten:")
        st.write("1) nedbør  0.1 mm og endring i snødybde ≥ 1.0 cm, eller")
        st.write("2) nedbør > 0.1 mm og minking i snødybde ≥ 0.5 cm")
        snow_drift_alarms = df[df["snow_drift_alarm"] == 1]
        if not snow_drift_alarms.empty:
            columns_to_show = [
                "air_temperature",
                "max_wind_speed",
                "surface_snow_thickness",
                "precipitation_amount",
            ]

            # Legg til snow_depth_change hvis den finnes
            if "snow_depth_change" in snow_drift_alarms.columns:
                columns_to_show.append("snow_depth_change")

            # Filtrer kun kolonner som faktisk finnes i DataFrame
            available_columns = [
                col for col in columns_to_show if col in snow_drift_alarms.columns
            ]

            st.dataframe(snow_drift_alarms[available_columns])
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
        "air_temperature": "Lufttemperatur (°C)",
        "precipitation_amount": "Nedbør (mm)",
        "snow_precipitation": "Antatt snønedbør (mm)",
        "surface_snow_thickness": "Snødybde (cm)",
        "max_wind_speed": "Maks vindhastighet (m/s)",
    }

    stats_data = {
        "Statistikk": ["Gjennomsnitt", "Median", "Minimum", "Maksimum", "Sum"]
    }

    for col, name in stats_columns.items():
        if col in available_columns:
            values = [
                f"{df[col].mean():.1f}",
                f"{df[col].median():.1f}",
                f"{df[col].min():.1f}",
                f"{df[col].max():.1f}",
                (
                    f"{df[col].sum():.1f}"
                    if col in ["precipitation_amount", "snow_precipitation"]
                    else "N/A"
                ),
            ]
            stats_data[name] = values

    stats = pd.DataFrame(stats_data)
    st.table(stats)

def handle_weather_page():
    """
    Hovedfunksjon for å håndtere værdatavisningen.
    """
    client_id = st.secrets["api_keys"]["client_id"]

    # Bruk heller default kolonner direkte
    selected_columns = get_default_columns()

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
        st.write(
            f"Henter data fra: {start_date.strftime('%d.%m.%Y kl. %H:%M')} til: {end_date.strftime('%d.%m.%Y kl. %H:%M')}"
        )

        weather_data = fetch_and_process_data(client_id, start_date, end_date)
        if "error" in weather_data:
            st.error(f"Feil ved henting av værdata: {weather_data['error']}")
        elif "df" in weather_data:
            df = weather_data["df"]

            # Filtrer DataFrame basert på valgte kolonner
            filtered_df = df[selected_columns]
            display_weather_data(filtered_df)

            # Generer nedlastingslink med valgte kolonner
            download_link = get_csv_download_link(df, selected_columns)
            st.markdown(download_link, unsafe_allow_html=True)
        else:
            st.error("Uventet feilformat fra værdatahenting")
