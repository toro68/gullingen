import pytest
import streamlit as st

def test_streamlit_session_state(mock_streamlit):
    """Test at Streamlit session state er korrekt initialisert"""
    assert "authenticated" in st.session_state
    assert st.session_state["authenticated"] is False

def test_streamlit_config():
    """Test at Streamlit konfigurasjon er satt opp"""
    assert st.get_option("theme.primaryColor") is not None 