"""Daily nutrition targets, what is left today, and the context sent to the AI coach."""
import json
from datetime import date, datetime, timedelta

from core import goals as G
from core.meals import eaten_on

MODES = {"maintain": 0, "lose": -400, "gain": 300}   # kcal/day relative to maintenance

# (name, kcal, protein_g, carbs_g, fat_g) per serving; common-food approximations
FOODS = [
    ("3 eggs", 234, 19, 1, 16),
    ("200 g Greek yogurt (plain)", 130, 20, 8, 1),
    ("100 g cooked chicken breast", 165, 31, 0, 4),
    ("1 can tuna (about 110 g drained)", 120, 26, 0, 1),
    ("150 g cooked lentils", 175, 14, 30, 1),
    ("200 g cottage cheese", 180, 22, 6, 8),
    ("1 banana", 105, 1, 27, 0),
    ("1 apple", 95, 0, 25, 0),
    ("30 g almonds", 175, 6, 6, 15),
]


def get_setting(conn, key, default=None):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(conn, key, value) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) "
                 "DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()


def latest_weight(conn):
    r = conn.execute("SELECT weight_kg FROM body_log WHERE weight_kg IS NOT NULL "
                     "ORDER BY date DESC LIMIT 1").fetchone()
    return r["weight_kg"] if r else None


def daily_targets(conn, today: date | None = None):
    """Maintenance = average total burn over the last 7 days (Garmin), adjusted by mode.
    Protein from body weight. Returns None until both data points exist."""
    today = today or date.today()
    rows = conn.execute(
        "SELECT kcal_total FROM daily_metrics WHERE date < ? AND kcal_total IS NOT NULL "
        "ORDER BY date DESC LIMIT 7", (today.isoformat(),)).fetchall()
    weight = latest_weight(conn)
    if not rows or not weight:
        return None
    maintenance = sum(r["kcal_total"] for r in rows) / len(rows)
    mode = get_setting(conn, "mode", "maintain")
    kcal = maintenance + MODES.get(mode, 0)
    protein = float(get_setting(conn, "protein_per_kg", 1.8)) * weight
    fat = 0.25 * kcal / 9
    carbs = max(kcal - protein * 4 - fat * 9, 0) / 4
    return {"kcal": round(kcal), "protein_g": round(protein), "fat_g": round(fat),
            "carbs_g": round(carbs), "mode": mode, "maintenance": round(maintenance),
            "days_used": len(rows), "weight_kg": weight}


def remaining(targets: dict, eaten: dict) -> dict:
    return {k: round(targets[k] - eaten[k]) for k in ("kcal", "protein_g", "carbs_g", "fat_g")}


def food_suggestions(rem: dict, n: int = 3) -> list[str]:
    """Foods that close the protein gap without blowing the calorie budget."""
    if rem["protein_g"] <= 5:
        return []
    budget = rem["kcal"] if rem["kcal"] > 0 else 150
    ranked = sorted(FOODS, key=lambda f: f[2] / max(f[1], 1), reverse=True)
    fits = [f for f in ranked if f[2] >= 6 and f[1] <= max(budget, 130)]
    return [f"{f[0]} (about {f[2]} g protein, {f[1]} kcal)" for f in fits[:n]]


def steps_left(conn, today: date | None = None):
    today = (today or date.today()).isoformat()
    r = conn.execute("SELECT steps, steps_goal FROM daily_metrics WHERE date=?", (today,)).fetchone()
    if not r or not r["steps_goal"]:
        return None
    return max(r["steps_goal"] - (r["steps"] or 0), 0)


def ai_context(conn, today: date | None = None) -> dict:
    """Facts for the AI coach. All numbers come from your data, not from the model."""
    today = today or date.today()
    ctx = {"today": today.isoformat(), "weekday": today.strftime("%A"), "goals": [],
           "weekly_volume_km": {}, "ramp_warnings": []}
    for g in G.list_goals(conn):
        ev = G.evaluate(conn, g, today)
        entry = {"priority": g["priority"], "name": g["name"], "status": ev["status"],
                 "deadline": g["deadline"]}
        if ev["kind"] == "distance":
            entry.update(best_km=round(ev["current"] / 1000, 2), target_km=round(ev["target"] / 1000, 1),
                         planned_by_now_km=round(ev["expected_now"] / 1000, 2),
                         planned_in_4_weeks_km=round(ev["milestone_4w"] / 1000, 2))
        ctx["goals"].append(entry)
    for label, types in (("swim", G.SWIM_TYPES), ("run", G.RUN_TYPES), ("ride", G.RIDE_TYPES)):
        vol = G.weekly_volume(conn, types, weeks=5, today=today)
        ctx["weekly_volume_km"][label] = [round(m / 1000, 2) for _, m in vol]
        w = G.ramp_warning(vol)
        if w:
            ctx["ramp_warnings"].append(f"{label}: {w}")
    ctx["weekly_volume_note"] = "oldest to newest; the last entry is the current partial week"
    rows = conn.execute("SELECT date, hr_resting, body_battery_latest, steps, steps_goal FROM daily_metrics "
                        "ORDER BY date DESC LIMIT 8").fetchall()
    if rows:
        latest = rows[0]
        prior = [r["hr_resting"] for r in rows[1:] if r["hr_resting"]]
        ctx["body_battery_latest"] = latest["body_battery_latest"]
        ctx["resting_hr_latest"] = latest["hr_resting"]
        ctx["resting_hr_7day_avg"] = round(sum(prior) / len(prior), 1) if prior else None
    t = daily_targets(conn, today)
    if t:
        ctx["remaining_nutrition_today"] = remaining(t, eaten_on(conn, today.isoformat()))
    return ctx


def save_recommendation(conn, kind: str, obj) -> None:
    conn.execute("INSERT INTO recommendations (created_at, kind, content) VALUES (?,?,?)",
                 (datetime.now().isoformat(timespec="seconds"), kind, obj.model_dump_json()))
    conn.commit()


def latest_recommendation(conn, kind: str):
    r = conn.execute("SELECT created_at, content FROM recommendations WHERE kind=? "
                     "ORDER BY id DESC LIMIT 1", (kind,)).fetchone()
    return (r["created_at"], json.loads(r["content"])) if r else None
