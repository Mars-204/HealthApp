"""Physique: weight and waist log, progress photos, AI muscle-group focus."""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from core import ai
from core.daily_plan import ai_context, latest_recommendation, save_recommendation
from core.db import connect, data_dir

load_dotenv()
st.set_page_config(page_title="Physique", page_icon="💪", layout="centered")
from core.auth import require_login
require_login()
conn = connect()
has_key = bool(os.environ.get("GEMINI_API_KEY"))
folder = data_dir() / "physique"
folder.mkdir(parents=True, exist_ok=True)

st.title("Physique")

# ---- measurements ----
st.subheader("Log weight and waist")
with st.form("body"):
    a, b = st.columns(2)
    w = a.number_input("Weight (kg)", 0.0, 300.0, 0.0, 0.1)
    waist = b.number_input("Waist (cm)", 0.0, 200.0, 0.0, 0.5)
    if st.form_submit_button("Save") and (w or waist):
        conn.execute("INSERT INTO body_log (date, weight_kg, waist_cm) VALUES (?,?,?) "
                     "ON CONFLICT(date) DO UPDATE SET weight_kg=COALESCE(excluded.weight_kg, weight_kg), "
                     "waist_cm=COALESCE(excluded.waist_cm, waist_cm)",
                     (date.today().isoformat(), w or None, waist or None))
        conn.commit()
        st.rerun()
log = pd.read_sql("SELECT date, weight_kg, waist_cm FROM body_log ORDER BY date", conn)
if len(log):
    cols = [c for c in ("weight_kg", "waist_cm") if log[c].notna().any()]
    fig = px.line(log, x="date", y=cols, markers=True)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=240, legend_title_text="")
    st.plotly_chart(fig, width="stretch")

# ---- photos ----
st.subheader("Photos and focus areas")
st.warning("Photo feedback sends your body photos to Google Gemini. Google's free tier can use "
           "submitted content to improve its products. Only continue if you are comfortable with "
           "that; cropping out your face is a good idea.")
agree = st.checkbox("I understand and want to send photos to Google")

ref = st.file_uploader("Target reference image (optional)", type=["jpg", "jpeg", "png", "webp"], key="ref")
cur = st.file_uploader("Your current photos (front, side, back; up to 3)", type=["jpg", "jpeg", "png", "webp"],
                       accept_multiple_files=True, key="cur")
if cur:
    st.image([c.getvalue() for c in cur[:3]], width=150)
if ref and cur:
    st.caption("Side by side, for your own comparison (this stays on your screen):")
    c1, c2 = st.columns(2)
    c1.image(ref.getvalue(), caption="Target")
    c2.image(cur[0].getvalue(), caption="Now")

if st.button("Save photos to my log", disabled=not cur):
    for i, c in enumerate(cur[:3]):
        (folder / f"{date.today()}_{i}.jpg").write_bytes(c.getvalue())
    conn.execute("INSERT INTO body_log (date, photo_path) VALUES (?,?) ON CONFLICT(date) "
                 "DO UPDATE SET photo_path=excluded.photo_path",
                 (date.today().isoformat(), str(folder / f"{date.today()}_0.jpg")))
    conn.commit()
    st.success("Saved on this computer only.")

if st.button("Get muscle-group focus from Gemini", disabled=not (has_key and agree and cur), type="primary"):
    photos = [(c.getvalue(), c.type or "image/jpeg") for c in cur[:3]]
    reference = [(ref.getvalue(), ref.type or "image/jpeg")] if ref else []
    ctx = {k: v for k, v in ai_context(conn).items() if k in ("goals", "weekly_volume_km", "ramp_warnings")}
    try:
        with st.spinner("Reviewing photos..."):
            fb = ai.physique_feedback(photos, reference, ctx)
        save_recommendation(conn, "physique", fb)
        st.rerun()
    except ai.AIError as e:
        st.error(str(e))
if not has_key:
    st.info("Add GEMINI_API_KEY to your .env file to enable photo feedback.")

saved = latest_recommendation(conn, "physique")
if saved:
    when, fb = saved
    st.caption(f"Generated {when.replace('T', ' ')}")
    st.write(fb["overall"])
    for f in fb["focus_areas"]:
        with st.container(border=True):
            st.markdown(f"**{f['muscle_group']}** ({f['priority']} priority)")
            st.write(f["observation"])
            st.write("Exercises: " + ", ".join(f["exercises"]))
    for n in fb["training_notes"]:
        st.write(f"- {n}")
    st.caption(fb["limits"])
