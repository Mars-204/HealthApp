"""Run:  python tests/test_normalize.py   (uses your two real sample activities)"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import connect
from core.sync import normalize_activity, upsert_activity

SWIM = {"activityId": 25085885376, "activityName": "Pool Swim",
  "startTimeLocal": "2026-11-15 11:57:54", "activityType": {"typeKey": "lap_swimming"},
  "distance": 450.0, "duration": 1449.9859619140625, "movingDuration": 708.4390258789062,
  "calories": 273.0, "averageHR": 129.0, "maxHR": 166.0, "activeLengths": 18,
  "poolLength": 2500.0, "strokes": 293.0, "averageSwolf": 56.0,
  "activityTrainingLoad": 84.71, "hrTimeInZone_1": 290.206}
SOCCER = {"activityId": 25101325783, "activityName": "Friedrichshafen Soccer/Football",
  "startTimeLocal": "2026-11-16 19:29:51", "activityType": {"typeKey": "soccer"},
  "distance": 6744.56, "duration": 5505.01, "movingDuration": 4421.0,
  "calories": 790.0, "averageHR": 129.0, "steps": 7394}

conn = connect(":memory:")
for a in (SWIM, SOCCER):
    upsert_activity(conn, normalize_activity(a))
    upsert_activity(conn, normalize_activity(a))   # twice: must not duplicate

rows = conn.execute("SELECT * FROM activities ORDER BY start_date").fetchall()
assert len(rows) == 2, "upsert created duplicates"
swim = next(r for r in rows if r["type_key"] == "lap_swimming")
assert swim["pool_length_m"] == 25.0, swim["pool_length_m"]
assert swim["start_date"] == "2026-11-15"
assert swim["vo2max"] is None
soccer = next(r for r in rows if r["type_key"] == "soccer")
assert soccer["pool_length_m"] is None and soccer["steps"] == 7394
print("all tests passed")

# ---- daily summary (your real sample, trimmed) ----
from core.sync import normalize_daily, upsert_daily, _daily_list
DAY = {"calendarDate": "2026-11-13",
  "movement": {"steps": {"goal": 6980, "value": 6123, "distanceInMeters": 4800.0}},
  "calories": {"burnedResting": 2074, "burnedActive": 118, "burnedTotal": 2192},
  "heartRate": {"minValue": 52, "maxValue": 99, "restingValue": 58},
  "intensityMinutes": {"goal": 150, "moderate": 0, "vigorous": 0},
  "stress": {"avgLevel": 27},
  "bodyBattery": {"minValue": 42, "maxValue": 58, "latestValue": 42},
  "respiration": {"avgValue": 13}}
for _ in range(2):
    upsert_daily(conn, normalize_daily(DAY))
d = conn.execute("SELECT * FROM daily_metrics").fetchall()
assert len(d) == 1 and d[0]["steps"] == 6123 and d[0]["hr_resting"] == 58
assert d[0]["kcal_total"] == 2192 and d[0]["body_battery_latest"] == 42
assert len(_daily_list([DAY, {"no": "date"}])) == 1
assert len(_daily_list({"dailySummaries": [DAY]})) == 1
print("daily tests passed")
