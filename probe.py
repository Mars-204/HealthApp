# probe.py
import json, os
from datetime import date, timedelta
from pathlib import Path
from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator
from dotenv import load_dotenv
load_dotenv()
out = Path("probe_output"); out.mkdir(exist_ok=True)
end = date.today(); start = end - timedelta(days=7)

with PersonalApiAuthenticator() as auth:
    token = auth.obtain_token(os.environ["GARMIN_PERSONAL_API_KEY"])

calls = {
    "daily_summaries": lambda c: c.get_daily_summaries(start, end),
    "steps": lambda c: c.get_daily_steps(start, end),
    "heart_rate": lambda c: c.get_daily_heart_rate(end),
    "sleep": lambda c: c.get_daily_sleep(end),
    "activities": lambda c: c.search_activities(start=0, limit=20),
    "weight": lambda c: c.get_weight_measurements(start, end),
    "food_logs": lambda c: c.get_daily_food_logs(end),
    "fitness_age": lambda c: c.get_fitness_age(end),
}

with GarminPersonalApiClient(token.access_token) as client:
    for name, fn in calls.items():
        try:
            (out / f"{name}.json").write_text(json.dumps(fn(client), indent=2))
            print("ok  ", name)
        except Exception as e:
            print("FAIL", name, e)