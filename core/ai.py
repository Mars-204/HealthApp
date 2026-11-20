"""Google Gemini calls: meal photos, physique feedback, training plans.

Every call returns a validated pydantic object. The model name comes from the
GEMINI_MODEL environment variable (default below); `client` can be injected for tests.
"""
import json
import os
import re

from pydantic import BaseModel

DEFAULT_MODEL = "gemini-2.5-flash"


class AIError(Exception):
    """Raised with a message that is safe to show to the user."""


# ---- response schemas (kept simple: no Optional/Literal, which schemas handle unevenly) ----
class FoodItem(BaseModel):
    name: str
    grams: float
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float


class MealEstimate(BaseModel):
    items: list[FoodItem]
    scale_reading_g: float = 0      # 0 = no scale display readable in the photo
    confidence: str = "medium"      # low, medium or high
    notes: str = ""


class ExerciseItem(BaseModel):
    activity: str
    duration_min: int
    intensity: str                  # easy, moderate or hard
    why: str


class ExercisePlan(BaseModel):
    summary: str
    today: list[ExerciseItem]
    this_week: list[ExerciseItem]
    cautions: list[str]


class MuscleFocus(BaseModel):
    muscle_group: str
    observation: str
    priority: str                   # high, medium or low
    exercises: list[str]


class PhysiqueFeedback(BaseModel):
    overall: str
    focus_areas: list[MuscleFocus]
    training_notes: list[str]
    limits: str


def get_client():
    from google import genai
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise AIError("GEMINI_API_KEY is not set. Add it to your .env file.")
    return genai.Client(api_key=key)


def _clean(text: str) -> str:
    text = (text or "").strip()
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()


def generate_json(prompt: str, schema, images=(), client=None, model=None):
    """images: iterable of (bytes, mime_type). Returns an instance of `schema`."""
    from google.genai import types
    client = client or get_client()
    model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    parts = [types.Part.from_bytes(data=b, mime_type=m) for b, m in images] + [prompt]
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema, temperature=0.2)
    try:
        resp = client.models.generate_content(model=model, contents=parts, config=config)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            raise AIError("Gemini's free quota is used up for now. Try again later "
                          "(daily limits reset at midnight Pacific time).") from e
        if "API key" in msg or "401" in msg or "403" in msg or "PERMISSION" in msg:
            raise AIError("Gemini rejected the API key. Check GEMINI_API_KEY.") from e
        if "404" in msg or "not found" in msg.lower():
            raise AIError(f"Model '{model}' was not found. Set GEMINI_MODEL to a current "
                          "model name from Google AI Studio.") from e
        raise AIError(f"Gemini request failed: {msg[:200]}") from e
    try:
        return schema.model_validate_json(_clean(resp.text))
    except Exception as e:
        raise AIError("Gemini returned an answer in an unexpected format. Please try again.") from e


# ---- prompts ----
def meal_prompt(note: str, weight_g: float | None, custom_foods: list[dict]) -> str:
    known = "\n".join(
        f"- {f['name']}: {f['kcal_100g']} kcal, {f['protein_100g']} g protein, "
        f"{f['carbs_100g']} g carbs, {f['fat_100g']} g fat per 100 g" for f in custom_foods
    ) or "(none)"
    return f"""You are a nutrition assistant. Identify each food item in the photo and estimate its
weight and nutrition. Be realistic, not optimistic.

User note: {note or '(none)'}
Total food weight stated by the user: {f'{weight_g} g' if weight_g else 'not given'}.
If a kitchen scale display is visible, read it and put the number in scale_reading_g; else use 0.
The user zeroes the scale with the empty plate on it, so the reading is the food only.

The user's own foods. If an item matches one of these, use these values per 100 g:
{known}

Rules:
- One entry per distinct food. grams, kcal, protein_g, carbs_g and fat_g are for the portion eaten.
- kcal should roughly equal 4*protein + 4*carbs + 9*fat.
- confidence is "low", "medium" or "high". Use "low" when portions or ingredients are unclear.
- notes: one short sentence on anything uncertain (hidden oil, sauces, unclear display)."""


def estimate_meal_ai(image_bytes: bytes, mime: str, note: str, weight_g, custom_foods, client=None) -> MealEstimate:
    return generate_json(meal_prompt(note, weight_g, custom_foods), MealEstimate,
                         images=[(image_bytes, mime)], client=client)


def exercise_plan(context: dict, client=None) -> ExercisePlan:
    prompt = f"""You are a cautious endurance and strength coach. Use ONLY the data below.
Goal priority: 1 swim, 2 physique (gymnast build), 3 marathon, 4 long bike ride.

DATA (JSON):
{json.dumps(context, indent=2, default=str)}

Write a plan for today and a suggested outline for the rest of this week.
Rules:
- Swim is the priority; put swim progression first. Keep weekly distance increases at or below about 15%.
- Respect any ramp_warnings in the data by suggesting less, not more.
- If body_battery_latest is under 30 or resting HR is 5+ bpm above its 7-day average, suggest recovery.
- Include strength work for the physique goal, counted inside the weekly load, not on top of it.
- Use remaining nutrition numbers if present (e.g. protein still needed), in the 'why' text.
- At most 3 items for today. Short, concrete, no medical claims or diagnoses.
- cautions: 0 to 3 short warnings (overtraining, shoulders, rest). Plain English."""
    return generate_json(prompt, ExercisePlan, client=client)


def physique_feedback(photos, reference, context: dict, client=None) -> PhysiqueFeedback:
    """photos / reference: lists of (bytes, mime). reference may be empty."""
    prompt = f"""You are a gymnastics strength coach reviewing progress photos.
{'The FIRST image is the target reference physique. The remaining images are the person\'s current photos.' if reference else 'All images are the person\'s current photos; no reference was given.'}

Context (JSON): {json.dumps(context, default=str)}

Task: compare visible muscle development and proportions with a lean gymnast build and name
2 to 4 muscle groups to prioritise, each with 2 to 4 specific exercises (e.g. ring support holds,
pull-up and dip progressions, L-sit, hollow body work) and a priority of high, medium or low.

Rules:
- Do NOT give a body-fat percentage, weight estimate, or any judgement of attractiveness.
- Describe only what is visible; say so when pose, lighting or clothing limits the view.
- Training must fit alongside heavy swim and running volume, so keep suggestions realistic.
- Never encourage crash dieting or extreme leanness. If the goal seems unhealthy, say to speak to a doctor.
- 'limits' must briefly explain what photo-based feedback cannot tell. Plain English."""
    imgs = list(reference) + list(photos)
    return generate_json(prompt, PhysiqueFeedback, images=imgs, client=client)
