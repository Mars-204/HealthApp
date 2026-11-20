"""SQLite storage. One file, created on first use."""
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("HEALTH_DB", "data/health.db"))

SCHEMA = """
-- Every Garmin response, untouched. Lets us re-parse later without calling Garmin.
CREATE TABLE IF NOT EXISTS raw_garmin (
    endpoint   TEXT NOT NULL,
    item_key   TEXT NOT NULL,          -- date range or activity id
    fetched_at TEXT NOT NULL,
    payload    TEXT NOT NULL,          -- JSON
    PRIMARY KEY (endpoint, item_key)
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id       INTEGER PRIMARY KEY,
    name              TEXT,
    start_local       TEXT,            -- 'YYYY-MM-DD HH:MM:SS'
    start_date        TEXT,            -- 'YYYY-MM-DD'
    type_key          TEXT,            -- running, lap_swimming, soccer, ...
    distance_m        REAL,
    duration_s        REAL,            -- includes rests
    moving_s          REAL,            -- excludes rests
    avg_speed_mps     REAL,
    calories          REAL,
    avg_hr            REAL,
    max_hr            REAL,
    steps             INTEGER,
    training_load     REAL,
    aerobic_te        REAL,
    anaerobic_te      REAL,
    vo2max            REAL,            -- only present on some activities
    -- swimming
    active_lengths    INTEGER,
    pool_length_m     REAL,            -- derived: distance / lengths
    strokes           REAL,
    avg_swolf         REAL,
    -- heart-rate zone seconds
    hr_z1_s REAL, hr_z2_s REAL, hr_z3_s REAL, hr_z4_s REAL, hr_z5_s REAL,
    raw               TEXT             -- full activity JSON
);
CREATE INDEX IF NOT EXISTS idx_act_date ON activities(start_date);
CREATE INDEX IF NOT EXISTS idx_act_type ON activities(type_key);

CREATE TABLE IF NOT EXISTS daily_metrics (
    date                TEXT PRIMARY KEY,   -- 'YYYY-MM-DD'
    steps               INTEGER,
    steps_goal          INTEGER,
    distance_m          REAL,
    kcal_resting        INTEGER,
    kcal_active         INTEGER,
    kcal_total          INTEGER,
    hr_min              INTEGER,
    hr_max              INTEGER,
    hr_resting          INTEGER,
    intensity_goal      INTEGER,
    moderate_min        INTEGER,
    vigorous_min        INTEGER,
    stress_avg          INTEGER,
    body_battery_min    INTEGER,
    body_battery_max    INTEGER,
    body_battery_latest INTEGER,
    respiration_avg     INTEGER,
    raw                 TEXT
);

CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,        -- swim_session, run_longest, ride_longest, physique, vo2max
    priority    INTEGER NOT NULL,     -- 1 = most important
    start_value REAL,                 -- metres for distance goals
    target_value REAL,                -- metres for distance goals; NULL until set
    start_date  TEXT NOT NULL,
    deadline    TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS meals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    eaten_at   TEXT NOT NULL,
    eaten_date TEXT NOT NULL,
    photo_path TEXT,
    note       TEXT,
    weight_g   REAL,
    items      TEXT,                  -- JSON list of {name, grams, kcal, protein_g, carbs_g, fat_g}
    kcal       REAL,
    protein_g  REAL,
    carbs_g    REAL,
    fat_g      REAL,
    confidence TEXT,
    source     TEXT                   -- ai, custom_food, manual
);
CREATE INDEX IF NOT EXISTS idx_meals_date ON meals(eaten_date);

CREATE TABLE IF NOT EXISTS custom_foods (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kcal_100g    REAL NOT NULL,
    protein_100g REAL NOT NULL,
    carbs_100g   REAL NOT NULL,
    fat_100g     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS body_log (
    date       TEXT PRIMARY KEY,
    weight_kg  REAL,
    waist_cm   REAL,
    photo_path TEXT,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS recommendations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind       TEXT NOT NULL,         -- exercise, physique
    content    TEXT NOT NULL          -- JSON
);

CREATE TABLE IF NOT EXISTS sync_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,               -- 1 = every step worked
    summary     TEXT                   -- JSON: counts and errors
);
"""


def data_dir() -> Path:
    """Folder for photos, next to the database file."""
    return DB_PATH.parent


def connect(path=None) -> sqlite3.Connection:
    path = Path(path) if path is not None else DB_PATH
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
