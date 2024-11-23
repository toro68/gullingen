def display_admin_dashboard():
    """Viser admin dashboard med feedback oversikt"""
    try:
        st.title("🎛️ Feedback Dashboard")
        
        tab1, tab2, tab3 = st.tabs([
            "📊 Feedback Oversikt",
            "🚜 Vedlikehold",
            "📈 Statistikk"
        ])
        
        with tab1:
            display_feedback_overview()
            
        with tab2:
            st.info("Vedlikeholdsfane under utvikling")
                
        with tab3:
            st.info("Statistikkfane under utvikling")

    except Exception as e:
        logger.error(f"Feil i admin dashboard: {str(e)}", exc_info=True)
        st.error("Det oppstod en feil ved lasting av dashboardet")
