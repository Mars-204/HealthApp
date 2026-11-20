"""Optional password gate. Set APP_PASSWORD in .env to turn it on.

A light barrier for your home network, not strong security: there is no lockout
beyond a short delay. Keep the app off the public internet (use Tailscale for remote access).
"""
import hmac
import os
import time

import streamlit as st
from dotenv import load_dotenv


def require_login() -> None:
    """Call right after st.set_page_config on every page."""
    load_dotenv()
    password = os.environ.get("APP_PASSWORD")
    if not password or st.session_state.get("authed"):
        return
    st.title("Health")
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        if hmac.compare_digest(entered.encode(), password.encode()):
            st.session_state["authed"] = True
            st.rerun()
        time.sleep(1)
        st.error("Wrong password.")
    st.stop()
