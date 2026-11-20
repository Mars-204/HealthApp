"""What is left today, plus an AI training plan."""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
from dotenv import load_dotenv

from core import ai
from core.daily_plan import (MODES, ai_context, daily_targets, food_suggestions, get_setting,
                             latest_recommendation, remaining, save_recommendation, set_setting,
                             steps_left)
from core.db import connect
from core.meals import eaten_on

load_dotenv()
st.set_page_config(page_title="Today", page_icon="📅", layout="centered")
from core.auth import require_login
require_login()
conn = connect()
has_key = bool(os.environ.get("GEMINI_API_KEY"))
today = date.today()

st.title("Today")

targets = daily_targets(conn, today)
if not targets:
    st.info("Targets need two things: a few days of synced Garmin data and your weight "
            "(log it on the Physique page).")
else:
    eaten = eaten_on(conn, today.isoformat())
    rem = remaining(targets, eaten)
    st.caption(f"Target = your average burn over the last {targets['days_used']} days "
               f"({targets['maintenance']} kcal), mode: {targets['mode']}. "
               "General guidance, not medical or dietetic advice.")
    for label, key, unit in (("Calories", "kcal", "kcal"), ("Protein", "protein_g", "g"),
                             ("Carbs", "carbs_g", "g"), ("Fat", "fat_g", "g")):
        frac = min(eaten[key] / targets[key], 1.0) if targets[key] else 0
        st.write(f"**{label}**: {eaten[key]:.0f} of {targets[key]} {unit} ({rem[key]} left)")
        st.progress(frac)
    if rem["kcal"] < -150:
        st.warning(f"You are about {-rem['kcal']} kcal over today's target.")
    ideas = food_suggestions(rem)
    if ideas:
        st.subheader("To close the protein gap")
        for i in ideas:
            st.write(f"- {i}")
    sl = steps_left(conn, today)
    if sl:
        st.write(f"**Steps left:** {sl:,} (about {sl // 100} minutes of walking)")

st.subheader("Training plan from Gemini")
st.caption("Only your summary numbers are sent (goal status, weekly distances, recovery), no photos.")
if st.button("Get today's plan", disabled=not has_key, type="primary"):
    try:
        with st.spinner("Thinking..."):
            plan = ai.exercise_plan(ai_context(conn, today))
        save_recommendation(conn, "exercise", plan)
        st.rerun()
    except ai.AIError as e:
        st.error(str(e))
if not has_key:
    st.info("Add GEMINI_API_KEY to your .env file to enable the plan.")

saved = latest_recommendation(conn, "exercise")
if saved:
    when, plan = saved
    st.caption(f"Generated {when.replace('T', ' ')}")
    st.write(plan["summary"])
    for sec, title in (("today", "Today"), ("this_week", "Rest of the week")):
        if plan[sec]:
            st.markdown(f"**{title}**")
            for x in plan[sec]:
                st.write(f"- **{x['activity']}**, {x['duration_min']} min, {x['intensity']}: {x['why']}")
    for c in plan["cautions"]:
        st.warning(c)

with st.expander("Settings"):
    mode = st.selectbox("Calorie mode", list(MODES), index=list(MODES).index(get_setting(conn, "mode", "maintain")))
    ppk = st.number_input("Protein per kg of body weight (g)", 1.2, 2.4, float(get_setting(conn, "protein_per_kg", 1.8)), 0.1)
    if st.button("Save settings"):
        set_setting(conn, "mode", mode)
        set_setting(conn, "protein_per_kg", ppk)
        st.rerun()
    st.caption("Heavy endurance training plus a calorie deficit is hard to recover from; "
               "'maintain' is the safe default.")
