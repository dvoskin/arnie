from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, Date,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String)
    age = Column(Integer)
    sex = Column(String)
    height_cm = Column(Float)
    current_weight_kg = Column(Float)
    goal_weight_kg = Column(Float)
    timezone = Column(String, default="UTC")
    city = Column(String)                   # free-form home city/region → resolves timezone
    channel_preference = Column(String)     # "telegram" | "imessage" — where proactive reminders go (linked users)
    primary_goal = Column(String)          # cut / bulk / maintain / performance / health
    training_experience = Column(String)   # beginner / intermediate / advanced
    dietary_preferences = Column(String)
    injuries = Column(Text)
    onboarding_completed = Column(Boolean, default=False)
    webhook_token = Column(String, unique=True, index=True)
    # Whoop OAuth tokens (per-user)
    whoop_access_token = Column(Text)
    whoop_refresh_token = Column(Text)
    whoop_token_expires_at = Column(DateTime)
    whoop_user_id = Column(String)
    # Subscription
    subscription_status = Column(String, default="trial")  # trial / active / cancelled / expired
    stripe_customer_id = Column(String, unique=True)
    trial_ends_at = Column(DateTime)
    subscription_ends_at = Column(DateTime)
    # Extended profile — sport and unit preference
    sport = Column(String)                          # e.g. "basketball", "boxing", "running"
    units_preference = Column(String, default="imperial")  # "imperial" | "metric"
    # Proactive engagement state — persisted so it survives deploys
    nudges_sent = Column(Text, default="")          # comma-separated day-1 warmup slot keys fired
    whoop_last_notified = Column(String)            # date string of last whoop recovery ping
    weekly_recap_week = Column(String)              # iso year-week of last weekly recap sent
    # Cross-platform continuity — this channel resolves to a canonical user
    linked_to_user_id = Column(Integer)             # if set, this identity points at another user
    link_code = Column(String)                      # active one-time code this user generated
    link_code_expires = Column(DateTime)            # when that code expires
    # Open coaching loop — one active daily mission, auto-evaluated against the log
    active_mission = Column(String)                 # human-readable mission text
    mission_metric = Column(String)                 # protein|calories|workouts|steps
    mission_target = Column(Float)                  # numeric target for the metric
    mission_date = Column(String)                   # date string the mission is for
    created_at = Column(DateTime, server_default=func.now())

    preferences = relationship("UserPreferences", back_populates="user", uselist=False,
                               cascade="all, delete-orphan")
    daily_logs = relationship("DailyLog", back_populates="user", cascade="all, delete-orphan")
    body_metrics = relationship("BodyMetric", back_populates="user", cascade="all, delete-orphan")
    conversation_logs = relationship("ConversationLog", back_populates="user",
                                     cascade="all, delete-orphan")
    memory_updates = relationship("MemoryUpdate", back_populates="user",
                                  cascade="all, delete-orphan")
    health_snapshots = relationship("HealthSnapshot", back_populates="user",
                                    cascade="all, delete-orphan")
    wearable_devices = relationship("WearableDevice", back_populates="user",
                                    cascade="all, delete-orphan")
    wearable_metrics = relationship("WearableMetric", back_populates="user",
                                    cascade="all, delete-orphan")
    pending_questions = relationship("PendingQuestion", back_populates="user",
                                     cascade="all, delete-orphan")
    workout_program = relationship("WorkoutProgram", back_populates="user",
                                   uselist=False, cascade="all, delete-orphan")


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    coaching_style = Column(String, default="balanced")       # strict / balanced / supportive
    accountability_level = Column(String, default="medium")   # low / medium / high
    pacing_enabled = Column(Boolean, default=True)
    reminder_frequency = Column(String, default="moderate")   # none / light / moderate / heavy
    preferred_response_length = Column(String, default="medium")  # short / medium / long
    profanity_tolerance = Column(Boolean, default=False)
    proactive_messaging_enabled = Column(Boolean, default=True)
    wake_time = Column(String, default="07:00")
    sleep_time = Column(String, default="23:00")
    calorie_target = Column(Integer)
    protein_target = Column(Integer)
    preferred_language = Column(String)  # e.g. "Spanish", "French" — null means English/auto

    user = relationship("User", back_populates="preferences")


class DailyLog(Base):
    __tablename__ = "daily_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    date = Column(Date, nullable=False)
    status = Column(String, default="open")  # open / closed
    total_calories = Column(Float, default=0)
    total_protein = Column(Float, default=0)
    total_carbs = Column(Float, default=0)
    total_fats = Column(Float, default=0)
    total_steps = Column(Integer)
    total_water_ml = Column(Float, default=0)
    workout_completed = Column(Boolean, default=False)
    cardio_completed = Column(Boolean, default=False)
    sleep_hours = Column(Float)
    recovery_score = Column(Integer)  # 1-10
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="daily_logs")
    food_entries = relationship("FoodEntry", back_populates="daily_log",
                                cascade="all, delete-orphan")
    exercise_entries = relationship("ExerciseEntry", back_populates="daily_log",
                                    cascade="all, delete-orphan")


class FoodEntry(Base):
    __tablename__ = "food_entries"

    id = Column(Integer, primary_key=True)
    daily_log_id = Column(Integer, ForeignKey("daily_logs.id"))
    timestamp = Column(DateTime, server_default=func.now())
    raw_input = Column(Text)
    parsed_food_name = Column(String)
    quantity = Column(String)
    calories = Column(Float)
    protein = Column(Float)
    carbs = Column(Float)
    fats = Column(Float)
    fiber = Column(Float)
    sugar = Column(Float)
    sodium = Column(Float)
    estimated_flag = Column(Boolean, default=False)
    confidence_score = Column(Float)   # 0.0 – 1.0
    source_type = Column(String, default="text")  # text / voice / image

    daily_log = relationship("DailyLog", back_populates="food_entries")


class ExerciseEntry(Base):
    __tablename__ = "exercise_entries"

    id = Column(Integer, primary_key=True)
    daily_log_id = Column(Integer, ForeignKey("daily_logs.id"))
    timestamp = Column(DateTime, server_default=func.now())
    exercise_name = Column(String)
    sets = Column(Integer)
    reps = Column(String)        # e.g. "5" or "5,5,5,4"
    weight = Column(Float)
    rir = Column(Integer)        # reps in reserve
    duration_minutes = Column(Float)
    cardio_type = Column(String)
    calories_burned_estimate = Column(Float)
    notes = Column(Text)
    source_type = Column(String, default="text")

    daily_log = relationship("DailyLog", back_populates="exercise_entries")


class BodyMetric(Base):
    __tablename__ = "body_metrics"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    weight_kg = Column(Float)
    bodyfat_estimate = Column(Float)
    waist_cm = Column(Float)
    photo_reference = Column(String)
    timestamp = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="body_metrics")


class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    raw_message = Column(Text)
    parsed_intent = Column(String)
    response = Column(Text)
    timestamp = Column(DateTime, server_default=func.now())
    source_type = Column(String, default="text")
    platform = Column(String, default="telegram")   # "telegram" | "imessage" | "web"
    skills_fired = Column(String)                    # comma-separated skill names that triggered

    user = relationship("User", back_populates="conversation_logs")


class MemoryUpdate(Base):
    __tablename__ = "memory_updates"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    update_summary = Column(Text)
    reasoning = Column(Text)
    timestamp = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="memory_updates")


class HealthSnapshot(Base):
    """One row per user per day — upserted when Apple Health webhook fires."""
    __tablename__ = "health_snapshots"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    steps = Column(Integer)
    active_calories = Column(Float)
    resting_calories = Column(Float)
    sleep_hours = Column(Float)
    sleep_deep_hours = Column(Float)
    sleep_rem_hours = Column(Float)
    resting_hr = Column(Float)
    avg_hr = Column(Float)
    hrv = Column(Float)
    stand_hours = Column(Integer)
    exercise_minutes = Column(Integer)
    # Whoop-specific fields
    recovery_score = Column(Integer)         # 0–100, from Whoop
    strain = Column(Float)                   # 0–21, from Whoop
    skin_temp_celsius = Column(Float)
    spo2_percentage = Column(Float)
    # Extended sleep metrics (Whoop sleep score)
    respiratory_rate = Column(Float)         # breaths/min during sleep
    sleep_performance_pct = Column(Float)    # Whoop sleep quality score 0–100
    sleep_need_hours = Column(Float)         # hours Whoop says you needed
    sleep_efficiency_pct = Column(Float)     # % of time in bed actually sleeping
    # Workout summary (JSON: [{sport, strain, duration_min, avg_hr, max_hr, calories}])
    whoop_workouts = Column(Text)
    source = Column(String, default="apple_health")  # "apple_health" or "whoop"
    received_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="health_snapshots")


class Feedback(Base):
    """User-submitted bug reports and feature suggestions."""
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String, default="other")  # bug / feature / other
    text = Column(Text, nullable=False)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class PendingQuestion(Base):
    """
    An open conversational loop — a question Arnie asked that's awaiting an answer.

    This is the backing state for context-aware follow-ups: when an important
    question goes unanswered, the reminders module re-asks it (tone scaled by
    `tier`) instead of nagging on a blind timer. Resolution is data-driven where
    possible (e.g. a "profile_stats" question is answered once the stats land);
    otherwise it's closed when the user re-engages.

    Lifecycle:
      asked       → row created with answered_at=NULL, asked_at=now
      followed up → follow_up_count incremented, last_asked_at bumped
      answered    → answered_at set (stops all follow-ups)

    Kept deliberately small (audit §8 "E. Pending conversation state"). One open
    row per (user, kind) is the norm; the reminders layer enforces that.
    """
    __tablename__ = "pending_questions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)  # profile_stats | goal_check | weight_checkin | generic
    question = Column(Text, nullable=False)             # the text Arnie asked
    tier = Column(String, default="casual")             # casual | goal_critical — scales follow-up urgency
    asked_at = Column(DateTime, server_default=func.now())   # first time asked
    last_asked_at = Column(DateTime, server_default=func.now())  # most recent (re-)ask
    follow_up_count = Column(Integer, default=0)        # how many times we've re-asked
    answered_at = Column(DateTime)                      # NULL until resolved
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="pending_questions")


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True)
    skill_name = Column(String, unique=True)
    description = Column(Text)
    trigger_conditions = Column(Text)
    markdown_path = Column(String)


class WearableDevice(Base):
    """
    One row per connected wearable device per user.
    Designed to support multiple devices simultaneously (Whoop + Apple Health + Oura etc).
    OAuth tokens are stored here for device-specific auth flows.
    Note: Legacy whoop_* fields on User remain for backward compatibility.
    """
    __tablename__ = "wearable_devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    device_type = Column(String, nullable=False)  # "whoop" | "apple_health" | "oura" | "garmin" | "fitbit"
    device_id = Column(String)                    # device-specific identifier from provider
    connected_at = Column(DateTime, server_default=func.now())
    last_sync_at = Column(DateTime)
    sync_status = Column(String, default="active")  # "active" | "error" | "disconnected" | "pending"
    error_message = Column(Text)
    # OAuth credentials (device-specific — keeps User table clean)
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_expires_at = Column(DateTime)
    # Flexible JSON blob for device-specific config / metadata
    metadata_json = Column(Text)

    user = relationship("User", back_populates="wearable_devices")


class WearableMetric(Base):
    """
    Time-series store for intraday wearable measurements.

    Uses a flexible (metric_type, value, unit) schema so any wearable can
    store any metric without schema migrations. Daily summaries live in
    HealthSnapshot; this table holds the raw time-series data.

    Supported metric_type values (non-exhaustive — add freely):
        heart_rate, hrv, steps, calories_active, calories_resting,
        spo2, skin_temp, respiratory_rate, stress_score, strain,
        recovery_score, sleep_stage, body_battery, vo2max,
        blood_glucose (future), hydration (future)
    """
    __tablename__ = "wearable_metrics"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    device_type = Column(String, nullable=False)   # source device
    metric_type = Column(String, nullable=False)   # what was measured
    value = Column(Float, nullable=False)
    unit = Column(String)                          # "bpm", "ms", "steps", "%", "°C", etc.
    recorded_at = Column(DateTime, nullable=False) # when the device measured it
    received_at = Column(DateTime, server_default=func.now())  # when we stored it

    user = relationship("User", back_populates="wearable_metrics")


class UserFoodMatch(Base):
    """
    Per-user 'food memory' — recurring foods matched to USDA data so Arnie
    recognizes a user's staples and reuses accurate nutrition over time.
    Keyed by the user + normalized food name.
    """
    __tablename__ = "user_food_matches"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name_norm = Column(String, nullable=False, index=True)  # lowercased food name
    display_name = Column(String)                           # what to call it
    fdc_id = Column(String)                                 # USDA FoodData Central id
    # per-100g nutrient profile from USDA (or user-confirmed)
    cal_100 = Column(Float)
    protein_100 = Column(Float)
    carbs_100 = Column(Float)
    fat_100 = Column(Float)
    fiber_100 = Column(Float)
    sugar_100 = Column(Float)
    sodium_100 = Column(Float)
    confidence = Column(String, default="estimated")  # exact|likely|estimated|user-confirmed
    user_confirmed = Column(Boolean, default=False)
    times_used = Column(Integer, default=1)
    last_used = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")


class WorkoutProgram(Base):
    """
    Structured workout split for a user — parsed from free-text via AI.
    Stores both the original raw paste and the structured JSON representation.
    One active program per user (upserted on update).
    """
    __tablename__ = "workout_programs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    raw_text = Column(Text)          # original free-text paste
    program_json = Column(Text)      # JSON string: {split_name, focus, rotation, days[]}
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="workout_program")
