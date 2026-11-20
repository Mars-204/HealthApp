"""Goal progress. Distance goals are measured from synced activities.

Progress    = (current - start) / (target - start), clipped to 0..1
Expected    = start * (target/start) ** (elapsed/total): steady percentage growth,
              the usual way to build a long swim, run or ride.
"""
from datetime import date, datetime, timedelta

SWIM_TYPES = {"lap_swimming", "open_water_swimming"}
# Running/cycling type keys are assumed; the Goals page lists the types found in your data.
RUN_TYPES = {"running", "trail_running", "treadmill_running", "track_running", "virtual_run"}
RIDE_TYPES = {"cycling", "road_biking", "indoor_cycling", "mountain_biking",
              "gravel_cycling", "virtual_ride"}
TYPE_MAP = {"swim_session": SWIM_TYPES, "run_longest": RUN_TYPES, "ride_longest": RIDE_TYPES}

DEADLINE = "2027-03-31"


def default_goals(today: date) -> list[dict]:
    s = today.isoformat()
    return [
        dict(name="Swim 5.5 km in one session (stops allowed)", type="swim_session", priority=1,
             start_value=850, target_value=5500, start_date=s, deadline=DEADLINE,
             notes="Total distance in one session, rests allowed."),
        dict(name="Gymnast physique", type="physique", priority=2, start_value=None,
             target_value=None, start_date=s, deadline=None,
             notes="Needs a reference image and a first progress photo."),
        dict(name="Run a marathon (42.2 km)", type="run_longest", priority=3,
             start_value=5000, target_value=42195, start_date=s, deadline=DEADLINE,
             notes="Finish goal; a time target can be added later."),
        dict(name="Cycle 150 km in one ride", type="ride_longest", priority=4,
             start_value=0, target_value=150000, start_date=s, deadline=DEADLINE,
             notes="Baseline = your first recorded ride."),
        dict(name="VO2 max", type="vo2max", priority=5, start_value=None,
             target_value=None, start_date=s, deadline=None,
             notes="Waiting for the first Garmin reading (needs outdoor runs)."),
    ]


def seed_default_goals(conn, today: date | None = None) -> int:
    if conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0]:
        return 0
    goals = default_goals(today or date.today())
    for g in goals:
        cols = list(g)
        conn.execute(f"INSERT INTO goals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [g[c] for c in cols])
    conn.commit()
    return len(goals)


def list_goals(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM goals ORDER BY priority, id")]


def sessions(conn, types, since: str) -> list[tuple[str, float]]:
    """(date, distance_m) for activities of the given types on/after `since`, oldest first."""
    marks = ", ".join("?" * len(types))
    rows = conn.execute(
        f"SELECT start_date, distance_m FROM activities WHERE type_key IN ({marks}) "
        "AND start_date >= ? AND distance_m IS NOT NULL ORDER BY start_local",
        [*types, since]).fetchall()
    return [(r["start_date"], r["distance_m"]) for r in rows]


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def evaluate(conn, goal: dict, today: date | None = None) -> dict:
    today = today or date.today()
    gtype = goal["type"]
    if gtype not in TYPE_MAP:
        label = {"physique": "Waiting for a reference image and your first progress photo.",
                 "vo2max": "No VO2 max reading from Garmin yet."}.get(gtype, "Not tracked yet.")
        return {"kind": "waiting", "status": "Waiting for data", "message": label}
    if not goal["target_value"] or not goal["deadline"]:
        return {"kind": "waiting", "status": "Target not set", "message": "Set a target and deadline."}

    sess = sessions(conn, TYPE_MAP[gtype], goal["start_date"])
    start = goal["start_value"] or 0
    if start <= 0:
        if not sess:
            return {"kind": "waiting", "status": "No baseline yet",
                    "message": "Your first recorded session sets the baseline."}
        start = sess[0][1]
    target = float(goal["target_value"])
    best = max((d for _, d in sess), default=0)
    current = max(start, best)

    d0 = date.fromisoformat(goal["start_date"])
    d1 = date.fromisoformat(goal["deadline"])
    total_days = max((d1 - d0).days, 1)
    frac = _clip((today - d0).days / total_days)

    def expected_at(f):
        return start * (target / start) ** f if target > start else target

    expected = expected_at(frac)
    progress = 1.0 if target <= start else _clip((current - start) / (target - start))
    weeks_left = max((d1 - today).days, 0) / 7
    ratio = current / expected if expected else 1.0
    if current >= target:
        status = "Achieved"
    elif today > d1:
        status = "Deadline passed"
    elif ratio >= 1.05:
        status = "Ahead of plan"
    elif ratio >= 0.9:
        status = "On track"
    elif ratio >= 0.75:
        status = "Slightly behind"
    else:
        status = "Behind"

    total_weeks = total_days / 7
    growth = (target / start) ** (1 / total_weeks) - 1 if target > start and total_weeks else 0.0
    milestone_frac = _clip((today + timedelta(days=28) - d0).days / total_days)
    n = 20
    curve = [((d0 + timedelta(days=round(total_days * i / n))).isoformat(),
              expected_at(i / n)) for i in range(n + 1)]
    return {"kind": "distance", "status": status, "start": start, "current": current,
            "target": target, "progress": progress, "expected_now": expected,
            "weeks_left": weeks_left, "weekly_growth_needed": growth,
            "milestone_4w": expected_at(milestone_frac), "sessions": sess, "curve": curve}


def weekly_volume(conn, types, weeks: int = 6, today: date | None = None) -> list[tuple[str, float]]:
    """Metres per Monday-start week, oldest first; the last entry is the current partial week."""
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    first = this_monday - timedelta(weeks=weeks - 1)
    marks = ", ".join("?" * len(types))
    rows = conn.execute(
        f"SELECT start_date, distance_m FROM activities WHERE type_key IN ({marks}) "
        "AND start_date >= ? AND distance_m IS NOT NULL", [*types, first.isoformat()]).fetchall()
    out = []
    for i in range(weeks):
        ws = first + timedelta(weeks=i)
        we = ws + timedelta(days=7)
        total = sum(r["distance_m"] for r in rows if ws.isoformat() <= r["start_date"] < we.isoformat())
        out.append((ws.isoformat(), total))
    return out


def ramp_warning(volumes: list[tuple[str, float]], limit: float = 0.15) -> str | None:
    """Compare the last two COMPLETE weeks (the final entry is the partial current week)."""
    if len(volumes) < 3:
        return None
    prev, last = volumes[-3][1], volumes[-2][1]
    if prev > 0 and last > prev * (1 + limit):
        return (f"Last week's volume rose {100 * (last / prev - 1):.0f}% on the week before. "
                f"Keep weekly increases under about {limit:.0%} to lower injury risk.")
    return None
