from datetime import datetime, timedelta
from unittest.mock import patch
import streamlit as st

from conftest import TEST_USER
from utils.core.validation_utils import validate_user_input
from src.app import (
    initialize_app,
    initialize_session_state,
    check_session_timeout,
    display_home_page
)

def test_initialize_session_state(mock_streamlit):
    """Test at session state initialiseres korrekt"""
    initialize_session_state()
    
    assert "authenticated" in st.session_state
    assert "user_id" in st.session_state
    assert "is_admin" in st.session_state
    assert "last_activity" in st.session_state
    assert "app_initialized" in st.session_state
    assert "tz" in st.session_state

@patch("utils.db.db_utils.verify_database_schemas")
@patch("utils.db.db_utils.initialize_database_system")
@patch("utils.db.db_utils.close_all_connections")
def test_initialize_app(mock_close, mock_init, mock_verify, mock_streamlit):
    """Test app initialisering"""
    mock_verify.return_value = True
    mock_init.return_value = True
    
    result = initialize_app()
    assert result is True
    mock_verify.assert_called_once()
    mock_init.assert_called_once()

def test_check_session_timeout(mock_streamlit):
    """Test session timeout sjekk"""
    st.session_state.last_activity = datetime.now().timestamp()
    assert check_session_timeout()
    
    st.session_state.last_activity = (datetime.now() - timedelta(hours=2)).timestamp()
    assert not check_session_timeout()

@patch("utils.services.customer_utils.get_customer_by_id")
def test_display_home_page(mock_get_customer, mock_streamlit):
    """Test visning av hjemmeside"""
    mock_customer = {
        "customer_id": TEST_USER,
        "type": "Standard"
    }
    mock_get_customer.return_value = mock_customer
    
    display_home_page(mock_customer)
    mock_get_customer.assert_called_once_with(TEST_USER)

def test_validate_user_input():
    """Test validering av brukerinput"""
    test_input = {
        "name": 'Test <script>alert("xss")</script>',
        "age": 25,
        "items": ["item1", '<script>alert("xss")</script>'],
        "nested": {"key": '<script>alert("xss")</script>'},
    }

    validated = validate_user_input(test_input)
    assert "<script>" not in validated["name"]
    assert validated["age"] == 25
    assert "<script>" not in validated["items"][1]
    assert "<script>" not in validated["nested"]["key"]
