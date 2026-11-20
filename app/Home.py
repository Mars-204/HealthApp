"""Overview page. Run:  streamlit run app/Home.py"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from core.db import connect
from core.sync import needs_sync, run_sync

load_dotenv()
st.set_page_config(page_title="Health", page_icon="🏃", layout="centered")
from core.auth import require_login
require_login()


def do_sync(days_back=None):
    with st.spinner("Syncing with Garmin..."):
        result = run_sync(days_back=days_back)
    if result["errors"]:
        st.warning("Some data could not be synced: " + "; ".join(
            f"{k}: {v[:120]}" for k, v in result["errors"].items()))
    else:
        st.toast(f"Synced {result['activities']} activities, {result['daily_days']} days")


conn = connect()
has_key = bool(os.environ.get("GARMIN_PERSONAL_API_KEY"))

st.title("Health overview")

# Sync on open (once per browser session) if data is stale, plus a manual button.
if has_key and "auto_synced" not in st.session_state:
    st.session_state["auto_synced"] = True
    if needs_sync(conn):
        do_sync()
        conn = connect()

col1, col2 = st.columns([3, 2])
last = conn.execute(
    "SELECT finished_at, ok FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
if last:
    t = datetime.fromisoformat(last["finished_at"]).strftime("%d %b %H:%M")
    col1.caption(f"Last synced: {t}" + ("" if last["ok"] else " (with errors)"))
else:
    col1.caption("Never synced")
if col2.button("Sync now", disabled=not has_key, width="stretch"):
    do_sync()
    conn = connect()
if not has_key:
    st.info("Add GARMIN_PERSONAL_API_KEY to your .env file to enable syncing.")
st.caption("Data reaches Garmin Connect only after the Garmin phone app syncs your watch.")

daily = pd.read_sql("SELECT * FROM daily_metrics ORDER BY date", conn)
acts = pd.read_sql("SELECT * FROM activities ORDER BY start_local DESC", conn)

if daily.empty:
    st.write("No data yet. Press **Sync now** (or run `python scripts/run_sync.py 60`).")
    st.stop()

latest = daily.iloc[-1]
st.subheader(f"Latest day: {latest['date']}")
a, b = st.columns(2)
a.metric("Steps", f"{int(latest['steps'] or 0):,}",
         help=f"Goal {latest['steps_goal']}" if pd.notna(latest["steps_goal"]) else None)
b.metric("Resting HR", f"{latest['hr_resting']:.0f} bpm" if pd.notna(latest["hr_resting"]) else "n/a")
c, d = st.columns(2)
c.metric("Calories burned", f"{int(latest['kcal_total'] or 0):,} kcal")
d.metric("Body battery", f"{latest['body_battery_latest']:.0f}" if pd.notna(latest["body_battery_latest"]) else "n/a")

recent = daily.tail(14)
fig = px.bar(recent, x="date", y="steps", title="Steps, last 14 days")
if recent["steps_goal"].notna().any():
    fig.add_scatter(x=recent["date"], y=recent["steps_goal"], mode="lines", name="Goal")
fig.update_layout(margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
st.plotly_chart(fig, width="stretch")

hr = recent.dropna(subset=["hr_resting"])
if not hr.empty:
    fig2 = px.line(hr, x="date", y="hr_resting", markers=True, title="Resting heart rate")
    fig2.update_layout(margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig2, width="stretch")

st.subheader("Recent activities")
if acts.empty:
    st.write("No activities synced yet.")
else:
    view = acts.head(10).copy()
    view["Date"] = view["start_date"]
    view["Type"] = view["type_key"].str.replace("_", " ")
    view["Distance (km)"] = (view["distance_m"] / 1000).round(2)
    view["Time (min)"] = (view["duration_s"] / 60).round(0)
    view["Avg HR"] = view["avg_hr"].round(0)
    st.dataframe(view[["Date", "Type", "Distance (km)", "Time (min)", "Avg HR"]],
                 hide_index=True, width="stretch")
