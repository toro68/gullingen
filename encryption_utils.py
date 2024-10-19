import streamlit as st
#import Fernet

def encrypt_data(data):
    f = Fernet(st.secrets["encryption_key"])
    return f.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data):
    f = Fernet(st.secrets["encryption_key"])
    return f.decrypt(encrypted_data.encode()).decode()