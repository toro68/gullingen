import io
import streamlit as st

from constants import TZ
from alert_utils import handle_alerts_ui, get_alerts

from logging_config import get_logger

logger = get_logger(__name__)

# Administrasjonsfunksjoner

def admin_broytefirma_page():
    st.title("Administrer feedback, tunbrøyting og strøing")

    if st.session_state.user_id in ["Fjbs Drift"]:
        admin_menu()
    else:
        st.error("Du har ikke tilgang til denne siden")
       
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
    st.info("Last ned alle data for tun, strøing, feedback og alerts ved å trykke på knappen 'Last ned data'")
    
    TZ = ZoneInfo("Europe/Oslo")

    # Date range selection
    end_date = datetime.now(TZ).date()
    start_date = end_date - timedelta(days=30)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Fra dato", value=start_date)
    with col2:
        end_date = st.date_input("Til dato", value=end_date)

    start_datetime = datetime.combine(start_date, datetime.min.time()).replace(
        tzinfo=TZ
    )
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

    # Fetch data
    feedback_data = get_feedback(
        start_datetime.isoformat(),
        end_datetime.isoformat(),
        include_hidden=include_hidden,
    )
    tunbroyting_data = hent_bestillinger()
    stroing_data = hent_stroing_bestillinger()
    login_history = (
        get_login_history(start_datetime, end_datetime)
        if "Påloggingshistorikk" in data_types
        else pd.DataFrame()
    )

    if (
        feedback_data.empty
        and tunbroyting_data.empty
        and stroing_data.empty
        and login_history.empty
    ):
        st.warning(f"Ingen data tilgjengelig for perioden {start_date} til {end_date}.")
        return

    # Data preprocessing
    if not feedback_data.empty:
        try:
            feedback_data["datetime"] = pd.to_datetime(
                feedback_data["datetime"], format="ISO8601"
            )
        except ValueError:
            try:
                feedback_data["datetime"] = pd.to_datetime(
                    feedback_data["datetime"], format="mixed"
                )
            except ValueError as e:
                st.error(f"Kunne ikke konvertere datoer: {str(e)}")
                st.write("Rådata for datoer:")
                st.write(feedback_data["datetime"].head())
                return

        feedback_data.loc[
            feedback_data["status"].isnull() | (feedback_data["status"] == "Innmeldt"),
            "status",
        ] = "Ny"
        feedback_data["date"] = feedback_data["datetime"].dt.date

        admin_alerts = feedback_data[
            feedback_data["type"].str.contains("Admin varsel", na=False)
        ]
        user_feedback = feedback_data[
            ~feedback_data["type"].str.contains("Admin varsel", na=False)
        ]

    if not tunbroyting_data.empty:
        tunbroyting_data["ankomst_dato"] = pd.to_datetime(
            tunbroyting_data["ankomst_dato"], format="mixed"
        ).dt.tz_localize(TZ)

    if not login_history.empty:
        login_history["login_time"] = pd.to_datetime(
            login_history["login_time"]
        ).dt.tz_convert(TZ)
        login_history["date"] = login_history["login_time"].dt.date

    # Summary statistics
    st.header("Oppsummering")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric(
            "Totalt antall Feedback",
            len(feedback_data) if not feedback_data.empty else 0,
        )
    with col2:
        st.metric("Admin-varsler", len(admin_alerts) if not feedback_data.empty else 0)
    with col3:
        st.metric(
            "Brukerfeedback", len(user_feedback) if not feedback_data.empty else 0
        )
    with col4:
        today = pd.Timestamp.now(tz=TZ).floor("D")
        active_tunbroyting = tunbroyting_data[
            (tunbroyting_data["ankomst_dato"].notna())
            & (tunbroyting_data["ankomst_dato"].dt.date >= today.date())
        ]
        st.metric(
            "Aktive tunbrøytingsbestillinger",
            len(active_tunbroyting) if not tunbroyting_data.empty else 0,
        )
    with col5:
        st.metric(
            "Aktive strøingsbestillinger",
            len(stroing_data) if not stroing_data.empty else 0,
        )

    # Export options
    st.header("Eksportalternativer")
    export_format = st.radio("Velg eksportformat", ["CSV", "Excel"])

    if st.button("Last ned data"):
        if export_format == "CSV":
            csv_data = io.StringIO()
            if "Bruker-feedback" in data_types and not user_feedback.empty:
                csv_data.write("Bruker-feedback:\n")
                user_feedback.to_csv(csv_data, index=False)
                csv_data.write("\n\n")
            if "Admin-varsler" in data_types and not admin_alerts.empty:
                csv_data.write("Admin-varsler:\n")
                admin_alerts.to_csv(csv_data, index=False)
                csv_data.write("\n\n")
            if "Tunbrøyting" in data_types and not tunbroyting_data.empty:
                csv_data.write("Tunbrøyting:\n")
                tunbroyting_data.to_csv(csv_data, index=False)
                csv_data.write("\n\n")
            if "Strøing" in data_types and not stroing_data.empty:
                csv_data.write("Strøing:\n")
                stroing_data.to_csv(csv_data, index=False)
                csv_data.write("\n\n")
            if "Påloggingshistorikk" in data_types and not login_history.empty:
                csv_data.write("Påloggingshistorikk:\n")
                login_history.to_csv(csv_data, index=False)

            st.download_button(
                label="Last ned CSV",
                data=csv_data.getvalue(),
                file_name="samlet_rapport.csv",
                mime="text/csv",
            )
        else:  # Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                if "Bruker-feedback" in data_types and not user_feedback.empty:
                    user_feedback.to_excel(
                        writer, sheet_name="Bruker-feedback", index=False
                    )
                if "Admin-varsler" in data_types and not admin_alerts.empty:
                    admin_alerts.to_excel(
                        writer, sheet_name="Admin-varsler", index=False
                    )
                if "Tunbrøyting" in data_types and not tunbroyting_data.empty:
                    tunbroyting_data.to_excel(
                        writer, sheet_name="Tunbrøyting", index=False
                    )
                if "Strøing" in data_types and not stroing_data.empty:
                    stroing_data.to_excel(writer, sheet_name="Strøing", index=False)
                if "Påloggingshistorikk" in data_types and not login_history.empty:
                    login_history.to_excel(
                        writer, sheet_name="Påloggingshistorikk", index=False
                    )

            st.download_button(
                label="Last ned Excel",
                data=output.getvalue(),
                file_name="samlet_rapport.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            
    # Data visualization
    #st.header("Datavisualisering")

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

    if "Bruker-feedback" in data_types and not user_feedback.empty:
        st.subheader("Brukerfeedback Oversikt")
        user_type_counts = user_feedback["type"].value_counts()
        fig_user_pie = px.pie(
            values=user_type_counts.values,
            names=user_type_counts.index,
            title="Fordeling av brukerfeedback typer",
        )
        st.plotly_chart(fig_user_pie, use_container_width=True)

        user_status_counts = user_feedback["status"].value_counts()
        fig_user_bar = px.bar(
            x=user_status_counts.index,
            y=user_status_counts.values,
            title="Antall brukerfeedback per status",
            labels={"x": "Status", "y": "Antall"},
            color=user_status_counts.index,
            color_discrete_map=STATUS_COLORS,
        )
        st.plotly_chart(fig_user_bar, use_container_width=True)

        user_daily_counts = (
            user_feedback.groupby("date").size().reset_index(name="count")
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
    if "Bruker-feedback" in data_types and not user_feedback.empty:
        st.subheader("Bruker-feedback:")
        st.dataframe(user_feedback)
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

    TZ = ZoneInfo("Europe/Oslo")

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

