"""Pull data from the Garmin Personal API into SQLite.

Rules: store raw JSON first, upsert everything (safe to run twice),
and never let one failing endpoint stop the others.
"""
import json
import os
from datetime import date, datetime, timedelta

from core.db import connect

FIRST_SYNC_DAYS = 30   # how far back the very first sync goes
OVERLAP_DAYS = 2       # re-fetch recent days; Garmin revises them after late watch syncs
PAGE = 50


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _f(d, key):
    v = d.get(key)
    return float(v) if v is not None else None


def normalize_activity(a: dict) -> dict:
    """Map one Garmin activity JSON object to a row of the activities table."""
    start_local = a.get("startTimeLocal")
    lengths = a.get("activeLengths")
    distance = _f(a, "distance")
    # Garmin's poolLength is in cm even though it says "meter" (25 m pool -> 2500),
    # so derive pool length from distance / lengths instead.
    pool_m = round(distance / lengths, 1) if (lengths and distance) else None
    return {
        "activity_id": a["activityId"],
        "name": a.get("activityName"),
        "start_local": start_local,
        "start_date": start_local[:10] if start_local else None,
        "type_key": (a.get("activityType") or {}).get("typeKey"),
        "distance_m": distance,
        "duration_s": _f(a, "duration"),
        "moving_s": _f(a, "movingDuration"),
        "avg_speed_mps": _f(a, "averageSpeed"),
        "calories": _f(a, "calories"),
        "avg_hr": _f(a, "averageHR"),
        "max_hr": _f(a, "maxHR"),
        "steps": a.get("steps"),
        "training_load": _f(a, "activityTrainingLoad"),
        "aerobic_te": _f(a, "aerobicTrainingEffect"),
        "anaerobic_te": _f(a, "anaerobicTrainingEffect"),
        # Field name is a guess; confirm on a real running activity.
        "vo2max": _f(a, "vO2MaxValue"),
        "active_lengths": lengths,
        "pool_length_m": pool_m,
        "strokes": _f(a, "strokes"),
        "avg_swolf": _f(a, "averageSwolf"),
        "hr_z1_s": _f(a, "hrTimeInZone_1"),
        "hr_z2_s": _f(a, "hrTimeInZone_2"),
        "hr_z3_s": _f(a, "hrTimeInZone_3"),
        "hr_z4_s": _f(a, "hrTimeInZone_4"),
        "hr_z5_s": _f(a, "hrTimeInZone_5"),
        "raw": json.dumps(a),
    }


def _g(d, *keys):
    """Safe nested lookup: _g(d, 'movement', 'steps', 'value')."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def normalize_daily(d: dict) -> dict:
    """Map one entry of the daily_summaries response to a daily_metrics row."""
    return {
        "date": d["calendarDate"],
        "steps": _g(d, "movement", "steps", "value"),
        "steps_goal": _g(d, "movement", "steps", "goal"),
        "distance_m": _g(d, "movement", "steps", "distanceInMeters"),
        "kcal_resting": _g(d, "calories", "burnedResting"),
        "kcal_active": _g(d, "calories", "burnedActive"),
        "kcal_total": _g(d, "calories", "burnedTotal"),
        "hr_min": _g(d, "heartRate", "minValue"),
        "hr_max": _g(d, "heartRate", "maxValue"),
        "hr_resting": _g(d, "heartRate", "restingValue"),
        "intensity_goal": _g(d, "intensityMinutes", "goal"),
        "moderate_min": _g(d, "intensityMinutes", "moderate"),
        "vigorous_min": _g(d, "intensityMinutes", "vigorous"),
        "stress_avg": _g(d, "stress", "avgLevel"),
        "body_battery_min": _g(d, "bodyBattery", "minValue"),
        "body_battery_max": _g(d, "bodyBattery", "maxValue"),
        "body_battery_latest": _g(d, "bodyBattery", "latestValue"),
        "respiration_avg": _g(d, "respiration", "avgValue"),
        "raw": json.dumps(d),
    }


def upsert_daily(conn, row: dict) -> None:
    cols = list(row)
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "date")
    conn.execute(
        f"INSERT INTO daily_metrics ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(date) DO UPDATE SET {updates}",
        row,
    )


def _daily_list(resp) -> list:
    """Accept a list, or a dict wrapping one; keep only entries with a date."""
    if isinstance(resp, dict):
        resp = next((v for v in resp.values() if isinstance(v, list)), [])
    return [d for d in resp if isinstance(d, dict) and "calendarDate" in d]


def upsert_activity(conn, row: dict) -> None:
    cols = list(row)
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "activity_id")
    conn.execute(
        f"INSERT INTO activities ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(activity_id) DO UPDATE SET {updates}",
        row,
    )


def save_raw(conn, endpoint: str, item_key: str, payload) -> None:
    conn.execute(
        "INSERT INTO raw_garmin (endpoint, item_key, fetched_at, payload) "
        "VALUES (?,?,?,?) ON CONFLICT(endpoint, item_key) DO UPDATE SET "
        "fetched_at=excluded.fetched_at, payload=excluded.payload",
        (endpoint, item_key, _now(), json.dumps(payload)),
    )


def last_successful_sync(conn):
    r = conn.execute(
        "SELECT started_at FROM sync_log WHERE ok=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return datetime.fromisoformat(r["started_at"]) if r else None


def needs_sync(conn, max_age_minutes: int = 30) -> bool:
    last = last_successful_sync(conn)
    return last is None or datetime.now() - last > timedelta(minutes=max_age_minutes)


def _activity_list(resp) -> list:
    """The response shape isn't documented; accept a list or a dict wrapper."""
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for key in ("activities", "activityList", "items"):
            if isinstance(resp.get(key), list):
                return resp[key]
    return []


def sync_activities(client, conn, start: date, end: date) -> int:
    count, offset = 0, 0
    while True:
        resp = client.search_activities(
            start=offset, limit=PAGE, start_date=start, end_date=end
        )
        items = _activity_list(resp)
        if not items:
            break
        for a in items:
            if "activityId" in a:
                upsert_activity(conn, normalize_activity(a))
                count += 1
        if len(items) < PAGE:
            break
        offset += PAGE
    return count


# Daily endpoints: saved raw until we have seen their real field names.
DAILY_RANGE_CALLS = {
    "daily_summaries": lambda c, s, e: c.get_daily_summaries(s, e),
    "steps": lambda c, s, e: c.get_daily_steps(s, e),
    "stress": lambda c, s, e: c.get_daily_stress(s, e),
    "sleep_summaries": lambda c, s, e: c.get_daily_sleep_summaries(s, e),
    "hrv_summaries": lambda c, s, e: c.get_daily_hrv_summaries(s, e),
}


def run_sync(api_key: str | None = None, days_back: int | None = None) -> dict:
    """Run a full sync. Returns a summary dict; also written to sync_log."""
    from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator

    api_key = api_key or os.environ["GARMIN_PERSONAL_API_KEY"]
    conn = connect()
    started = _now()
    summary = {"activities": 0, "daily_days": 0, "raw_saved": [], "errors": {}}

    last = last_successful_sync(conn)
    if days_back is None:
        days_back = FIRST_SYNC_DAYS if last is None else (
            (datetime.now() - last).days + OVERLAP_DAYS
        )
    end = date.today()
    start = end - timedelta(days=days_back)

    try:
        with PersonalApiAuthenticator() as auth:
            token = auth.obtain_token(api_key)
        with GarminPersonalApiClient(token.access_token) as client:
            try:
                summary["activities"] = sync_activities(client, conn, start, end)
            except Exception as e:  # keep going; report at the end
                summary["errors"]["activities"] = str(e)
            for name, call in DAILY_RANGE_CALLS.items():
                try:
                    data = call(client, start, end)
                    save_raw(conn, name, f"{start}_{end}", data)
                    summary["raw_saved"].append(name)
                    if name == "daily_summaries":
                        days = _daily_list(data)
                        for d in days:
                            upsert_daily(conn, normalize_daily(d))
                        summary["daily_days"] = len(days)
                except Exception as e:
                    summary["errors"][name] = str(e)
        conn.commit()
    except Exception as e:  # token or network failure
        summary["errors"]["auth_or_network"] = str(e)

    ok = 0 if summary["errors"] else 1
    conn.execute(
        "INSERT INTO sync_log (started_at, finished_at, ok, summary) VALUES (?,?,?,?)",
        (started, _now(), ok, json.dumps(summary)),
    )
    conn.commit()
    conn.close()
    return summary
