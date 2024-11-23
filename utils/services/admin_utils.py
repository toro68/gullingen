import io
import traceback
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.core.config import TZ, get_current_time, safe_to_datetime, format_date
from utils.core.logging_config import get_logger
from utils.services.alert_utils import get_alerts, handle_alerts_ui
from utils.services.feedback_utils import get_feedback
from utils.services.tun_utils import get_bookings
from utils.core.auth_utils import get_login_history
from utils.services.stroing_utils import (
    get_stroing_bestillinger,
    hent_stroing_bestillinger
)

# Lazy imports
def get_login_data(start_date=None, end_date=None, limit: int = 1000):
    """
    Henter innloggingsdata for admin-visning.
    
    Args:
        start_date: Valgfri startdato for filtrering
        end_date: Valgfri sluttdato for filtrering
        limit: Maksimalt antall rader som skal hentes
    """
    return get_login_history(start_date=start_date, end_date=end_date, limit=limit)

logger = get_logger(__name__)

# Administrasjonsfunksjoner
def admin_alert():
    handle_alerts_ui()

    # Legg til feilsøkingsinformasjon
    if st.checkbox("Vis feilsøkingsinformasjon"):
        st.write("Rådata for dagens varsler:")
        st.write(get_alerts(only_today=True))
        st.write("Rådata for alle aktive varsler:")
        st.write(get_alerts(include_expired=False))
        st.write("SQL-spørring brukt for å hente varsler:")
        query = "SELECT * FROM feedback WHERE is_alert = 1 ORDER BY datetime DESC"
        st.code(query)

def unified_report_page(include_hidden=False):
    st.title("Dashbord for rapporter")
    st.info(
        "Last ned alle data for tun, strøing, feedback og alerts ved å trykke på knappen 'Last ned data'"
    )

    # Date range selection med riktig tidssone
    end_date = get_current_time().date()
    start_date = (end_date - timedelta(days=30))

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=start_date)
    with col2:
        end_date = st.date_input("Til dato", value=end_date)

    # Konverter til datetime med riktig tidssone
    start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=TZ)
    end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)

    # Data type selection
    data_types = st.multiselect(
        "Velg datatyper",
        [
            "Bruker-feedback",
            "Admin-varsler",
            "Tunbrøyting",
            "Strøing",
            "Påloggingshistorikk",
        ],
        default=["Bruker-feedback", "Admin-varsler", "Tunbrøyting", "Strøing"],
    )

    # st.write("Debug: Valgte datatyper:", data_types)  # Debug utskrift

    # Initialize all dataframes
    feedback_data = pd.DataFrame()
    tunbroyting_data = pd.DataFrame()
    stroing_data = pd.DataFrame()
    login_history = pd.DataFrame()
    admin_alerts = pd.DataFrame()

    # Fetch data
    if "Bruker-feedback" in data_types:
        feedback_data = get_feedback(
            start_datetime.isoformat(),
            end_datetime.isoformat(),
            include_hidden=include_hidden,
        )
        st.write("Debug: Hentet bruker-feedback data")  # Debug utskrift

    if "Tunbrøyting" in data_types:
        tunbroyting_data = get_bookings()
        st.write("Debug: Hentet tunbrøyting data")  # Debug utskrift

    if "Strøing" in data_types:
        stroing_data = get_stroing_bestillinger(
            start_date=format_date(start_datetime, "database", "datetime"),
            end_date=format_date(end_datetime, "database", "datetime")
        )
        st.write("Debug: Hentet strøing data")  # Debug utskrift

    if "Påloggingshistorikk" in data_types:
        login_history = get_login_history(start_datetime, end_datetime)
        st.write("Debug: Hentet påloggingshistorikk")  # Debug utskrift

    if "Admin-varsler" in data_types:
        admin_alerts = get_alerts(only_today=False, include_expired=True)
        st.write("Debug: Hentet admin-varsler")  # Debug utskrift
        # st.subheader("Admin-varsler")
        # admin_alert()

    # Data preprocessing
    if not feedback_data.empty:
        feedback_data["datetime"] = pd.to_datetime(
            feedback_data["datetime"]
        ).dt.tz_convert(TZ)
        feedback_data["date"] = feedback_data["datetime"].dt.date

    if not tunbroyting_data.empty:
        if "ankomst_dato" in tunbroyting_data.columns:
            tunbroyting_data["ankomst_dato"] = pd.to_datetime(
                tunbroyting_data["ankomst_dato"], format="mixed"
            ).dt.tz_localize(TZ)
        elif "ankomst" in tunbroyting_data.columns:
            tunbroyting_data["ankomst"] = pd.to_datetime(
                tunbroyting_data["ankomst"], format="mixed"
            ).dt.tz_localize(TZ)
            tunbroyting_data["ankomst_dato"] = tunbroyting_data["ankomst"].dt.date

    if not login_history.empty:
        login_history["login_time"] = pd.to_datetime(
            login_history["login_time"]
        ).dt.tz_convert(TZ)
        login_history["date"] = login_history["login_time"].dt.date

    if not admin_alerts.empty:
        admin_alerts["datetime"] = pd.to_datetime(
            admin_alerts["datetime"]
        ).dt.tz_convert(TZ)
        admin_alerts["date"] = admin_alerts["datetime"].dt.date

    # Check if all data is empty
    if all(
        df.empty
        for df in [
            feedback_data,
            tunbroyting_data,
            stroing_data,
            login_history,
            admin_alerts,
        ]
    ):
        st.warning(f"Ingen data tilgjengelig for perioden {start_date} til {end_date}.")
        return

    # Export options
    st.header("Eksportalternativer")
    export_format = st.radio("Velg eksportformat", ["CSV", "Excel"])

    if st.button("Last ned data"):
        try:
            st.write("Debug: Starter nedlasting av data")  # Debug utskrift
            if export_format == "CSV":
                csv_data = io.StringIO()
                for data_type, df in [
                    ("Bruker-feedback", feedback_data),
                    ("Admin-varsler", admin_alerts),
                    ("Tunbrøyting", tunbroyting_data),
                    ("Strøing", stroing_data),
                    ("Påloggingshistorikk", login_history),
                ]:
                    st.write(f"Debug: Prosesserer {data_type}")  # Debug utskrift
                    if data_type in data_types and not df.empty:
                        csv_data.write(f"{data_type}:\n")
                        df.to_csv(csv_data, index=False)
                        csv_data.write("\n\n")

                st.download_button(
                    label="Last ned CSV",
                    data=csv_data.getvalue(),
                    file_name="samlet_rapport.csv",
                    mime="text/csv",
                )
            else:  # Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                    for data_type, df in [
                        ("Bruker-feedback", feedback_data),
                        ("Admin-varsler", admin_alerts),
                        ("Tunbrøyting", tunbroyting_data),
                        ("Strøing", stroing_data),
                        ("Påloggingshistorikk", login_history),
                    ]:
                        st.write(
                            f"Debug: Prosesserer {data_type} for Excel"
                        )  # Debug utskrift
                        if data_type in data_types and not df.empty:
                            df.to_excel(writer, sheet_name=data_type, index=False)

                st.download_button(
                    label="Last ned Excel",
                    data=output.getvalue(),
                    file_name="samlet_rapport.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            st.success("Data lastet ned vellykket!")
        except Exception as e:
            st.error(f"En feil oppstod under nedlasting av data: {str(e)}")
            logger.error("Error during data download: %s", str(e), exc_info=True)
            st.write(
                "Debug: Exception stacktrace:", traceback.format_exc()
            )  # Debug utskrift

    # Data visualization
    st.header("Datavisualisering")

    if "Admin-varsler" in data_types and not admin_alerts.empty:
        st.subheader("Admin-varsler Oversikt")
        admin_type_counts = admin_alerts["type"].value_counts()
        fig_admin_pie = px.pie(
            values=admin_type_counts.values,
            names=admin_type_counts.index,
            title="Fordeling av admin-varsel typer",
        )
        st.plotly_chart(fig_admin_pie, use_container_width=True)

        admin_daily_counts = (
            admin_alerts.groupby("date").size().reset_index(name="count")
        )
        fig_admin_line = px.line(
            admin_daily_counts,
            x="date",
            y="count",
            title="Antall admin-varsler over tid",
        )
        fig_admin_line.update_xaxes(title_text="Dato")
        fig_admin_line.update_yaxes(title_text="Antall admin-varsler")
        st.plotly_chart(fig_admin_line, use_container_width=True)

    if "Bruker-feedback" in data_types and not feedback_data.empty:
        st.subheader("Brukerfeedback Oversikt")
        user_type_counts = feedback_data["type"].value_counts()
        fig_user_pie = px.pie(
            values=user_type_counts.values,
            names=user_type_counts.index,
            title="Fordeling av brukerfeedback typer",
        )
        st.plotly_chart(fig_user_pie, use_container_width=True)

        user_status_counts = feedback_data["status"].value_counts()
        fig_user_bar = px.bar(
            x=user_status_counts.index,
            y=user_status_counts.values,
            title="Antall brukerfeedback per status",
            labels={"x": "Status", "y": "Antall"},
            color=user_status_counts.index,
        )
        st.plotly_chart(fig_user_bar, use_container_width=True)

        user_daily_counts = (
            feedback_data.groupby("date").size().reset_index(name="count")
        )
        fig_user_line = px.line(
            user_daily_counts,
            x="date",
            y="count",
            title="Antall brukerfeedback over tid",
        )
        fig_user_line.update_xaxes(title_text="Dato")
        fig_user_line.update_yaxes(title_text="Antall brukerfeedback")
        st.plotly_chart(fig_user_line, use_container_width=True)

    if "Påloggingshistorikk" in data_types and not login_history.empty:
        st.subheader("Påloggingsanalyse")
        fig_login = px.histogram(login_history, x="date", title="Pålogginger over tid")
        st.plotly_chart(fig_login)

        success_rate = (login_history["success"].sum() / len(login_history)) * 100
        st.metric("Vellykket påloggingsrate", f"{success_rate:.2f}%")

    # Preview data
    st.header("Forhåndsvisning av data")
    if "Bruker-feedback" in data_types and not feedback_data.empty:
        st.subheader("Bruker-feedback:")
        st.dataframe(feedback_data)
    if "Admin-varsler" in data_types and not admin_alerts.empty:
        st.subheader("Admin-varsler:")
        st.dataframe(admin_alerts)
    if "Tunbrøyting" in data_types and not tunbroyting_data.empty:
        st.subheader("Tunbrøyting:")
        st.dataframe(tunbroyting_data)
    if "Strøing" in data_types and not stroing_data.empty:
        st.subheader("Strøing:")
        st.dataframe(stroing_data)
    if "Påloggingshistorikk" in data_types and not login_history.empty:
        st.subheader("Påloggingshistorikk:")
        st.dataframe(login_history)

    # Vis totalt antall elementer
    st.info(f"Viser data for perioden {start_date} til {end_date}")


def download_reports(include_hidden=False):
    st.subheader("Last ned rapporter og påloggingshistorikk")

    # Date range selection
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Fra dato",
            value=datetime(2020, 1, 1),
            min_value=datetime(2020, 1, 1),
            max_value=datetime.now(TZ),
        )
    with col2:
        end_date = st.date_input(
            "Til dato",
            value=datetime.now(TZ),
            min_value=datetime(2020, 1, 1),
            max_value=datetime.now(TZ),
        )

    start_datetime = datetime.combine(start_date, datetime.min.time()).replace(
        tzinfo=TZ
    )
    end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=TZ)

    # Data type selection
    data_types = st.multiselect(
        "Velg datatyper",
        ["Rapporter", "Påloggingshistorikk"],
        default=["Rapporter", "Påloggingshistorikk"],
    )

    # Fetch data
    all_reports = (
        get_feedback(
            start_datetime.isoformat(),
            end_datetime.isoformat(),
            include_hidden=include_hidden,
        )
        if "Rapporter" in data_types
        else pd.DataFrame()
    )
    login_history = (
        get_login_history(start_datetime, end_datetime)
        if "Påloggingshistorikk" in data_types
        else pd.DataFrame()
    )

    if not all_reports.empty or not login_history.empty:
        # Data preprocessing
        if not all_reports.empty:
            all_reports["datetime"] = pd.to_datetime(
                all_reports["datetime"]
            ).dt.tz_convert(TZ)
            all_reports["date"] = all_reports["datetime"].dt.date

        if not login_history.empty:
            login_history["login_time"] = pd.to_datetime(
                login_history["login_time"]
            ).dt.tz_convert(TZ)
            login_history["date"] = login_history["login_time"].dt.date

        # Data visualization
        if not all_reports.empty:
            st.subheader("Rapportanalyse")
            fig1 = px.histogram(all_reports, x="date", title="Rapporter over tid")
            st.plotly_chart(fig1)

            fig2 = px.pie(all_reports, names="type", title="Fordeling av rapporttyper")
            st.plotly_chart(fig2)

        if not login_history.empty:
            st.subheader("Påloggingsanalyse")
            fig3 = px.histogram(login_history, x="date", title="Pålogginger over tid")
            st.plotly_chart(fig3)

            success_rate = (login_history["success"].sum() / len(login_history)) * 100
            st.metric("Vellykket påloggingsrate", f"{success_rate:.2f}%")

        # Export options
        st.subheader("Eksportalternativer")
        export_format = st.radio("Velg eksportformat", ["CSV", "Excel"])

        if st.button("Last ned data"):
            if export_format == "CSV":
                csv_data = io.StringIO()
                if not all_reports.empty:
                    csv_data.write("Rapporter:\n")
                    all_reports.to_csv(csv_data, index=False)
                    csv_data.write("\n\n")
                if not login_history.empty:
                    csv_data.write("Påloggingshistorikk:\n")
                    login_history.to_csv(csv_data, index=False)

                st.download_button(
                    label="Last ned CSV",
                    data=csv_data.getvalue(),
                    file_name="rapporter_og_paalogginger.csv",
                    mime="text/csv",
                )
            else:  # Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                    if not all_reports.empty:
                        all_reports.to_excel(
                            writer, sheet_name="Rapporter", index=False
                        )
                    if not login_history.empty:
                        login_history.to_excel(
                            writer, sheet_name="Påloggingshistorikk", index=False
                        )

                st.download_button(
                    label="Last ned Excel",
                    data=output.getvalue(),
                    file_name="rapporter_og_paalogginger.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        # Preview data
        st.subheader("Forhåndsvisning av data")
        if not all_reports.empty:
            st.write("Rapporter:")
            st.dataframe(all_reports)
        if not login_history.empty:
            st.write("Påloggingshistorikk:")
            st.dataframe(login_history)
    else:
        st.info("Ingen data å laste ned for den valgte perioden.")


def admin_stroing_overview():
    """Viser oversikt over strøing for administratorer"""
    try:
        st.subheader("Strøing Administrasjon")

        # Vis aktive bestillinger
        active_orders = hent_stroing_bestillinger()
        if not active_orders.empty:
            st.write("Aktive bestillinger:")
            st.dataframe(active_orders)

            # Last ned data
            if st.button("Last ned strøingsdata"):
                csv = active_orders.to_csv(index=False)
                st.download_button(
                    "Last ned CSV", csv, "stroing_bestillinger.csv", "text/csv"
                )

        return True

    except Exception as e:
        logger.error(f"Feil i strøing-administrasjon: {str(e)}")
        return False

def display_status(status):
    return status  # Returner bare status-teksten direkte
