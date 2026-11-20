"""Run:  python tests/test_ai_meals.py    (no internet or API key needed: Gemini is faked)"""
import json, os, sys, tempfile
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HEALTH_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")

from core import ai
from core.db import connect
from core.meals import (estimate_meal, add_custom_food, save_meal, eaten_on, totals, scale_to_weight)
from core.sync import normalize_daily, upsert_daily
from core.daily_plan import (daily_targets, remaining, food_suggestions, set_setting, ai_context)


class Fake:
    """Stands in for google.genai.Client."""
    def __init__(self, payload): self.payload, self.calls = payload, []
    @property
    def models(self): return self
    def generate_content(self, model, contents, config):
        self.calls.append((model, contents))
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return type("R", (), {"text": text})()


conn = connect()
IMG = b"\xff\xd8fake-jpeg"

# 1) AI estimate, scaled to the weight the user typed
fake = Fake({"items": [
    {"name": "chicken curry", "grams": 200, "kcal": 300, "protein_g": 25, "carbs_g": 10, "fat_g": 18},
    {"name": "rice", "grams": 100, "kcal": 130, "protein_g": 3, "carbs_g": 28, "fat_g": 0.3}],
    "scale_reading_g": 0, "confidence": "medium", "notes": ""})
r = estimate_meal(IMG, "image/jpeg", "curry and rice", 450, conn, client=fake)
assert abs(sum(i["grams"] for i in r["items"]) - 450) < 1, r["items"]
assert r["source"] == "ai" and "scaled" in r["notes"].lower()
assert abs(r["totals"]["kcal"] - 645) < 2, r["totals"]       # 430 kcal x 1.5
assert fake.calls and "450" in fake.calls[0][1][-1]           # weight reached the prompt

# 2) macros that disagree with calories -> confidence forced to low
bad = Fake({"items": [{"name": "x", "grams": 100, "kcal": 900, "protein_g": 5, "carbs_g": 5, "fat_g": 1}],
            "confidence": "high"})
r = estimate_meal(IMG, "image/jpeg", "", None, conn, client=bad)
assert r["confidence"] == "low" and "add up" in r["notes"]

# 3) fenced JSON from the model is still parsed
fenced = Fake("```json\n" + json.dumps({"items": [{"name": "egg", "grams": 50, "kcal": 78,
        "protein_g": 6.3, "carbs_g": 0.6, "fat_g": 5.3}], "confidence": "high"}) + "\n```")
assert estimate_meal(IMG, "image/jpeg", "egg", None, conn, client=fenced)["items"][0]["name"] == "egg"

# 4) custom food + weight skips the AI entirely
add_custom_food(conn, "Mum's dal", 120, 8, 18, 2)
never = Fake("should not be called")
r = estimate_meal(IMG, "image/jpeg", "my mum's dal for lunch".replace("my mum", "Mum"), 250, conn, client=never)
assert r["source"] == "custom_food" and not never.calls and r["totals"]["kcal"] == 300.0, r

# 5) errors become friendly AIErrors
for payload, word in [("not json at all", "unexpected format")]:
    try: estimate_meal(IMG, "image/jpeg", "", None, conn, client=Fake(payload)); raise SystemExit("no error")
    except ai.AIError as e: assert word in str(e)
class Quota(Fake):
    def generate_content(self, **k): raise RuntimeError("429 RESOURCE_EXHAUSTED")
try: estimate_meal(IMG, "image/jpeg", "", None, conn, client=Quota({}))
except ai.AIError as e: assert "quota" in str(e).lower()

# 6) saving and daily totals
save_meal(conn, r["items"], "dal", 250, "high", "custom_food", photo_bytes=IMG)
assert eaten_on(conn, date.today().isoformat())["kcal"] == 300.0
assert list((Path(os.environ["HEALTH_DB"]).parent / "meals").glob("*.jpg"))

# 7) targets need Garmin burn + weight, then remaining + suggestions
today = date(2026, 11, 20)
assert daily_targets(conn, today) is None
for i in range(1, 8):
    upsert_daily(conn, normalize_daily({"calendarDate": f"2026-11-{20 - i:02d}",
        "calories": {"burnedTotal": 2400}}))
conn.execute("INSERT INTO body_log (date, weight_kg) VALUES ('2026-11-19', 70)"); conn.commit()
t = daily_targets(conn, today)
assert t["kcal"] == 2400 and t["protein_g"] == 126 and t["days_used"] == 7, t
set_setting(conn, "mode", "lose")
assert daily_targets(conn, today)["kcal"] == 2000
rem = remaining(t, {"kcal": 1500, "protein_g": 60, "carbs_g": 150, "fat_g": 50})
assert rem["protein_g"] == 66 and rem["kcal"] == 900
sugg = food_suggestions(rem)
assert sugg and all("protein" in s for s in sugg)
assert food_suggestions({"kcal": 500, "protein_g": 2, "carbs_g": 0, "fat_g": 0}) == []

# 8) coach: context carries your numbers; plan parses
from core.goals import seed_default_goals
seed_default_goals(conn, today)
ctx = ai_context(conn, today)
assert ctx["goals"][0]["name"].startswith("Swim") and "remaining_nutrition_today" in ctx
plan_fake = Fake({"summary": "Easy swim today.", "today": [{"activity": "Swim", "duration_min": 40,
    "intensity": "easy", "why": "Build base"}], "this_week": [], "cautions": ["Rest shoulders"]})
plan = ai.exercise_plan(ctx, client=plan_fake)
assert plan.today[0].activity == "Swim" and "swim" in plan_fake.calls[0][1][-1].lower()

# 9) physique feedback: reference image goes first, then photos
phys = Fake({"overall": "ok", "focus_areas": [{"muscle_group": "Lats", "observation": "x",
    "priority": "high", "exercises": ["Pull-ups"]}], "training_notes": [], "limits": "Photos only."})
fb = ai.physique_feedback([(IMG, "image/jpeg")], [(b"REF", "image/jpeg")], {}, client=phys)
parts = phys.calls[0][1]
assert fb.focus_areas[0].muscle_group == "Lats" and len(parts) == 3
assert parts[0].inline_data.data == b"REF"
print("ai + meals tests passed")
