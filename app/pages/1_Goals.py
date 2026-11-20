"""Goals page."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plotly.graph_objects as go
import streamlit as st

from core.db import connect
from core.goals import (RIDE_TYPES, RUN_TYPES, SWIM_TYPES, TYPE_MAP, evaluate,
                        list_goals, ramp_warning, seed_default_goals, weekly_volume)

st.set_page_config(page_title="Goals", page_icon="🎯", layout="centered")
from core.auth import require_login
require_login()
conn = connect()
st.title("Goals")

goals = list_goals(conn)
if not goals:
    st.write("No goals yet.")
    if st.button("Create my starting goals"):
        seed_default_goals(conn)
        st.rerun()
    st.stop()

STATUS_ICON = {"Achieved": "✅", "Ahead of plan": "🟢", "On track": "🟢",
               "Slightly behind": "🟡", "Behind": "🔴", "Deadline passed": "⚪"}
km = lambda m: m / 1000

for g in goals:
    ev = evaluate(conn, g)
    with st.container(border=True):
        st.subheader(f"{g['priority']}. {g['name']}")
        if ev["kind"] == "waiting":
            st.write(f"⏳ **{ev['status']}**: {ev['message']}")
            continue

        st.progress(ev["progress"])
        st.write(f"{STATUS_ICON.get(ev['status'], '')} **{ev['status']}**: "
                 f"best so far {km(ev['current']):.2f} km of {km(ev['target']):.1f} km "
                 f"({ev['progress']:.0%})")
        c1, c2, c3 = st.columns(3)
        c1.metric("Weeks left", f"{ev['weeks_left']:.0f}")
        c2.metric("Target by now", f"{km(ev['expected_now']):.2f} km")
        c3.metric("In 4 weeks", f"{km(ev['milestone_4w']):.2f} km")
        st.caption(f"To finish by {g['deadline']} your longest session needs to grow "
                   f"about {ev['weekly_growth_needed']:.0%} per week.")

        fig = go.Figure()
        fig.add_scatter(x=[d for d, _ in ev["curve"]], y=[km(m) for _, m in ev["curve"]],
                        mode="lines", name="Plan", line=dict(dash="dash"))
        if ev["sessions"]:
            fig.add_scatter(x=[d for d, _ in ev["sessions"]], y=[km(m) for _, m in ev["sessions"]],
                            mode="markers", name="Your sessions", marker=dict(size=9))
        fig.add_hline(y=km(ev["target"]), line_dash="dot")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=260,
                          yaxis_title="km", legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        types = {"swim_session": SWIM_TYPES, "run_longest": RUN_TYPES,
                 "ride_longest": RIDE_TYPES}[g["type"]]
        warn = ramp_warning(weekly_volume(conn, types))
        if warn:
            st.warning(warn)

with st.expander("Edit targets and deadlines"):
    for g in goals:
        if g["type"] not in TYPE_MAP:
            continue
        with st.form(f"edit_{g['id']}"):
            st.write(f"**{g['name']}**")
            t = st.number_input("Target (km)", min_value=0.1, value=km(g["target_value"] or 1000.0),
                                step=0.5, key=f"t{g['id']}")
            s = st.number_input("Starting level (km)", min_value=0.0, value=km(g["start_value"] or 0.0),
                                step=0.05, key=f"s{g['id']}")
            d = st.date_input("Deadline", value=date.fromisoformat(g["deadline"]) if g["deadline"]
                              else date(2027, 3, 31), key=f"d{g['id']}")
            if st.form_submit_button("Save"):
                conn.execute("UPDATE goals SET target_value=?, start_value=?, deadline=? WHERE id=?",
                             (t * 1000, s * 1000, d.isoformat(), g["id"]))
                conn.commit()
                st.rerun()

with st.expander("Activity types found in your data"):
    rows = conn.execute("SELECT type_key, COUNT(*) n FROM activities GROUP BY type_key ORDER BY n DESC").fetchall()
    st.write(", ".join(f"{r['type_key']} ({r['n']})" for r in rows) or "No activities synced yet.")
    st.caption("If a running or cycling type is missing from the goals, tell me its name.")
