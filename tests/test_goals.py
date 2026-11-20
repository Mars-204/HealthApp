"""Run:  python tests/test_goals.py"""
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import connect
from core.sync import normalize_activity, upsert_activity
from core.goals import (seed_default_goals, list_goals, evaluate, weekly_volume,
                        ramp_warning, SWIM_TYPES)

conn = connect(":memory:")
TODAY = date(2026, 11, 20)
assert seed_default_goals(conn, TODAY) == 5
assert seed_default_goals(conn, TODAY) == 0, "seeding twice must not duplicate"
goals = {g["type"]: g for g in list_goals(conn)}
assert [g["priority"] for g in list_goals(conn)] == [1, 2, 3, 4, 5]

def act(i, d, typ, dist):
    upsert_activity(conn, normalize_activity({"activityId": i, "startTimeLocal": f"{d} 10:00:00",
        "activityType": {"typeKey": typ}, "distance": dist, "duration": dist}))

# Day 0: your real 450 m swim is below the 850 m starting level -> no progress, on track
act(1, "2026-11-20", "lap_swimming", 450.0)
ev = evaluate(conn, goals["swim_session"], TODAY)
assert ev["current"] == 850 and ev["progress"] == 0 and ev["status"] == "On track", ev
assert 0.10 < ev["weekly_growth_needed"] < 0.11, ev["weekly_growth_needed"]

# Mid-way: 1,800 m swim by 20 Jan
act(2, "2027-01-20", "lap_swimming", 1800.0)
ev = evaluate(conn, goals["swim_session"], date(2027, 1, 20))
assert ev["current"] == 1800 and 0 < ev["progress"] < 0.25
assert ev["status"] in ("On track", "Behind", "Slightly behind"), ev["status"]

# Achieved
act(3, "2027-03-20", "lap_swimming", 5600.0)
assert evaluate(conn, goals["swim_session"], date(2027, 3, 21))["status"] == "Achieved"

# Cycling: no baseline until a ride exists
assert evaluate(conn, goals["ride_longest"], TODAY)["status"] == "No baseline yet"
act(4, "2026-11-25", "cycling", 30000.0)
ev = evaluate(conn, goals["ride_longest"], date(2026, 11, 26))
assert ev["start"] == 30000 and ev["current"] == 30000

# Placeholders
assert evaluate(conn, goals["physique"], TODAY)["status"] == "Waiting for data"
assert evaluate(conn, goals["vo2max"], TODAY)["kind"] == "waiting"

# Weekly ramp: 1000 m then 1500 m in two complete weeks -> +50% warning
conn2 = connect(":memory:")
for i, (d, m) in enumerate([("2026-11-02", 1000.0), ("2026-11-09", 1500.0), ("2026-11-17", 500.0)]):
    upsert_activity(conn2, normalize_activity({"activityId": i, "startTimeLocal": f"{d} 10:00:00",
        "activityType": {"typeKey": "lap_swimming"}, "distance": m}))
vol = weekly_volume(conn2, SWIM_TYPES, weeks=4, today=date(2026, 11, 18))
assert ramp_warning(vol) and "50%" in ramp_warning(vol), vol
print("goal tests passed")
