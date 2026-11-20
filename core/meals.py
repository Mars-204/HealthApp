"""Meal estimation and storage.

Pipeline: user's custom food (if named + weighed) -> Gemini vision estimate ->
totals recomputed here (never trusting the model's arithmetic) -> editable result -> save.
"""
import json
from datetime import datetime

from core import ai
from core.db import data_dir

MACROS = ("kcal", "protein_g", "carbs_g", "fat_g")


def list_custom_foods(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM custom_foods ORDER BY name")]


def add_custom_food(conn, name, kcal, protein, carbs, fat) -> None:
    conn.execute(
        "INSERT INTO custom_foods (name, kcal_100g, protein_100g, carbs_100g, fat_100g) "
        "VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET kcal_100g=excluded.kcal_100g, "
        "protein_100g=excluded.protein_100g, carbs_100g=excluded.carbs_100g, fat_100g=excluded.fat_100g",
        (name.strip(), kcal, protein, carbs, fat))
    conn.commit()


def totals(items: list[dict]) -> dict:
    return {k: round(sum(float(i.get(k) or 0) for i in items), 1) for k in MACROS}


def match_custom_food(note: str, foods: list[dict]):
    note = (note or "").lower()
    # longest name first so "chicken curry" wins over "chicken"
    for f in sorted(foods, key=lambda f: -len(f["name"])):
        if f["name"].lower() in note:
            return f
    return None


def item_from_custom(food: dict, grams: float) -> dict:
    k = grams / 100
    return {"name": food["name"], "grams": grams, "kcal": round(food["kcal_100g"] * k, 1),
            "protein_g": round(food["protein_100g"] * k, 1),
            "carbs_g": round(food["carbs_100g"] * k, 1), "fat_g": round(food["fat_100g"] * k, 1)}


def scale_to_weight(items: list[dict], target_g: float) -> list[dict]:
    """Scale every item so the grams add up to target_g (portions keep their ratio)."""
    current = sum(i["grams"] for i in items)
    if current <= 0 or target_g <= 0:
        return items
    f = target_g / current
    return [{**i, **{k: round(i[k] * f, 1) for k in ("grams", *MACROS)}} for i in items]


def estimate_meal(image_bytes, mime, note, weight_g, conn, client=None) -> dict:
    """Return {items, totals, confidence, notes, source, scale_reading_g}."""
    foods = list_custom_foods(conn)
    match = match_custom_food(note, foods)
    if match and weight_g:
        items = [item_from_custom(match, weight_g)]
        return {"items": items, "totals": totals(items), "confidence": "high",
                "notes": f"Used your saved food '{match['name']}'.", "source": "custom_food",
                "scale_reading_g": 0}

    est = ai.estimate_meal_ai(image_bytes, mime, note, weight_g, foods, client=client)
    items = [i.model_dump() for i in est.items]
    notes, confidence = est.notes, (est.confidence or "medium").lower()

    target = weight_g or (est.scale_reading_g or 0)
    listed = sum(i["grams"] for i in items)
    if target and listed and abs(target - listed) / target > 0.05:
        items = scale_to_weight(items, target)
        notes = (notes + " " if notes else "") + (
            f"Portions scaled to the {'weight you entered' if weight_g else 'scale reading'} "
            f"({target:.0f} g).")

    t = totals(items)
    macro_kcal = 4 * t["protein_g"] + 4 * t["carbs_g"] + 9 * t["fat_g"]
    if t["kcal"] and abs(macro_kcal - t["kcal"]) / t["kcal"] > 0.25:
        confidence = "low"
        notes = (notes + " " if notes else "") + "Calories and macros don't add up; please check the numbers."
    return {"items": items, "totals": t, "confidence": confidence, "notes": notes,
            "source": "ai", "scale_reading_g": est.scale_reading_g}


def save_meal(conn, items, note="", weight_g=None, confidence="", source="manual",
              photo_bytes=None, when=None) -> int:
    when = when or datetime.now()
    photo_path = None
    if photo_bytes:
        folder = data_dir() / "meals"
        folder.mkdir(parents=True, exist_ok=True)
        photo_path = str(folder / f"{when:%Y%m%d_%H%M%S}.jpg")
        with open(photo_path, "wb") as f:
            f.write(photo_bytes)
    t = totals(items)
    cur = conn.execute(
        "INSERT INTO meals (eaten_at, eaten_date, photo_path, note, weight_g, items, kcal, "
        "protein_g, carbs_g, fat_g, confidence, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (when.isoformat(timespec="seconds"), when.date().isoformat(), photo_path, note, weight_g,
         json.dumps(items), t["kcal"], t["protein_g"], t["carbs_g"], t["fat_g"], confidence, source))
    conn.commit()
    return cur.lastrowid


def eaten_on(conn, day: str) -> dict:
    r = conn.execute("SELECT COALESCE(SUM(kcal),0) kcal, COALESCE(SUM(protein_g),0) protein_g, "
                     "COALESCE(SUM(carbs_g),0) carbs_g, COALESCE(SUM(fat_g),0) fat_g "
                     "FROM meals WHERE eaten_date=?", (day,)).fetchone()
    return {k: round(r[k], 1) for k in MACROS}


def meals_on(conn, day: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM meals WHERE eaten_date=? ORDER BY eaten_at", (day,))]
