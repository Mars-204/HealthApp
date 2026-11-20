"""Log a meal: photo + note + weight -> editable estimate -> save."""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core import ai
from core.db import connect
from core.meals import (add_custom_food, estimate_meal, list_custom_foods, meals_on,
                        save_meal, totals)

load_dotenv()
st.set_page_config(page_title="Log meal", page_icon="🍽️", layout="centered")
from core.auth import require_login
require_login()
conn = connect()
has_key = bool(os.environ.get("GEMINI_API_KEY"))
COLS = ["name", "grams", "kcal", "protein_g", "carbs_g", "fat_g"]

st.title("Log a meal")
st.caption("Photos are sent to Google Gemini for the estimate. On the free tier, Google may use "
           "submitted content to improve its products, so avoid photos with people or documents in them.")
if not has_key:
    st.info("No GEMINI_API_KEY found, so AI estimates are off. You can still enter a meal by hand below.")

photo = st.file_uploader("Photo of your meal (include the scale display if you can)",
                         type=["jpg", "jpeg", "png", "webp"])
if photo:
    st.image(photo, width="stretch")
note = st.text_input("What is it? (optional)", placeholder="chicken curry with rice")
weight = st.number_input("Food weight in grams (optional, overrides what the AI reads)",
                         min_value=0.0, step=10.0, value=0.0)

if st.button("Estimate with AI", disabled=not (has_key and photo), type="primary"):
    mime = photo.type or "image/jpeg"
    try:
        with st.spinner("Analysing the photo..."):
            res = estimate_meal(photo.getvalue(), mime, note, weight or None, conn)
        st.session_state["estimate"] = res
    except ai.AIError as e:
        st.error(str(e))

est = st.session_state.get("estimate")
st.subheader("Review and edit")
if est:
    st.write(f"Confidence: **{est['confidence']}**" + (f". {est['notes']}" if est["notes"] else ""))
    start_df = pd.DataFrame(est["items"], columns=COLS)
else:
    st.caption("Fill in the table yourself, or run the AI estimate above.")
    start_df = pd.DataFrame([{c: ("" if c == "name" else 0.0) for c in COLS}])

edited = st.data_editor(start_df, num_rows="dynamic", width="stretch", hide_index=True)
items = [r for r in edited.fillna(0).to_dict("records") if str(r.get("name", "")).strip()]
t = totals(items)
st.write(f"**Total:** {t['kcal']:.0f} kcal · protein {t['protein_g']:.0f} g · "
         f"carbs {t['carbs_g']:.0f} g · fat {t['fat_g']:.0f} g")

if st.button("Save meal", disabled=not items):
    save_meal(conn, items, note=note, weight_g=weight or None,
              confidence=est["confidence"] if est else "manual",
              source=est["source"] if est else "manual",
              photo_bytes=photo.getvalue() if photo else None)
    st.session_state.pop("estimate", None)
    st.success("Saved.")
    st.rerun()

st.divider()
st.subheader("Today's meals")
today_meals = meals_on(conn, date.today().isoformat())
if not today_meals:
    st.write("Nothing logged yet.")
for m in today_meals:
    st.write(f"{m['eaten_at'][11:16]}: {m['note'] or 'meal'}: **{m['kcal']:.0f} kcal**, "
             f"{m['protein_g']:.0f} g protein")

with st.expander("My foods (used before the AI guesses)"):
    foods = list_custom_foods(conn)
    if foods:
        st.dataframe(pd.DataFrame(foods).drop(columns=["id"]), hide_index=True, width="stretch")
    with st.form("custom_food"):
        n = st.text_input("Name")
        a, b = st.columns(2)
        k = a.number_input("kcal per 100 g", min_value=0.0)
        p = b.number_input("protein per 100 g", min_value=0.0)
        c1, c2 = st.columns(2)
        cb = c1.number_input("carbs per 100 g", min_value=0.0)
        f = c2.number_input("fat per 100 g", min_value=0.0)
        if st.form_submit_button("Save food") and n.strip():
            add_custom_food(conn, n, k, p, cb, f)
            st.rerun()
    st.caption("If the name appears in your note and you enter a weight, the AI is skipped.")
