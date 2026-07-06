from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, Date, UniqueConstraint, Index,
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
    # Last shared Telegram location (one-time share or live-location). Nullable —
    # most users never share. Used by find_nearby_places to search "around them"
    # and to reverse-geocode a city/timezone. NOT continuous tracking: only set
    # when the user actively shares, refreshed on each new share.
    lat = Column(Float)
    lng = Column(Float)
    location_updated_at = Column(DateTime)  # when lat/lng were last refreshed (UTC)
    channel_preference = Column(String)     # "telegram" | "imessage" — where proactive reminders go (linked users)
    primary_goal = Column(String)          # cut / bulk / maintain / performance / health
    training_experience = Column(String)   # beginner / intermediate / advanced
    # Daily occupational / non-training activity — distinct from training
    # experience above. ACSM tier labels: sedentary, lightly_active,
    # moderately_active, very_active. NOT yet wired into compute_macro_targets()
    # (which still uses a single 1.4 multiplier); this column captures the
    # signal so users can populate it ahead of the math switching over.
    non_training_activity = Column(String)
    dietary_preferences = Column(String)
    injuries = Column(Text)
    # Free-form "brain dump" the user types/dictates during native onboarding —
    # everything they want Arnie to know in their own words (nutrition, lifestyle,
    # history, motivation). Feeds the personalized opening intro and Arnie's
    # ongoing context. Distinct from the AI-generated `user_bio`.
    brain_dump = Column(Text)
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
    # AI-generated profile bio (narrative text, refreshed when attributes change significantly)
    user_bio = Column(Text)
    user_bio_updated_at = Column(DateTime)

    # Proactive engagement state — persisted so it survives deploys
    nudges_sent = Column(Text, default="")          # comma-separated day-1 warmup slot keys fired
    whoop_last_notified = Column(String)            # date string of last whoop recovery ping
    weekly_recap_week = Column(String)              # iso year-week of last weekly recap sent
    # Cross-platform continuity — this channel resolves to a canonical user
    linked_to_user_id = Column(Integer)             # if set, this identity points at another user
    link_code = Column(String)                      # active one-time code this user generated
    link_code_expires = Column(DateTime)            # when that code expires
    # Apple Sign-in subject. Set when the iOS app exchanges an Apple identity
    # token via POST /api/v1/auth/session. Distinct from telegram_id (the
    # platform-identity string) — a user's telegram_id may stay "ios:<uuid>"
    # even after Apple binding, so resolve_user keeps working. apple_sub
    # exists so a future cross-device sign-in (same Apple ID, different
    # device) can find the right user row via find_user_by_apple_sub.
    apple_sub = Column(String, unique=True, index=True)
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
    device_tokens = relationship("DeviceToken", back_populates="user",
                                 cascade="all, delete-orphan")
    pending_questions = relationship("PendingQuestion", back_populates="user",
                                     cascade="all, delete-orphan")
    workout_program = relationship("WorkoutProgram", back_populates="user",
                                   uselist=False, cascade="all, delete-orphan")
    user_attributes = relationship("UserAttribute", back_populates="user",
                                   cascade="all, delete-orphan")


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
    carb_target = Column(Integer)
    fat_target = Column(Integer)
    preferred_language = Column(String)  # e.g. "Spanish", "French" — null means English/auto
    food_logging_mode = Column(String, default="moderate")  # quick / moderate / strict
    # Coach home dashboard layout — JSON {"order":[...],"hidden":[...]} synced from
    # the iOS Customize screen so a user's reordered / hidden metric sections follow
    # them across devices. Null = client uses its default order with everything shown.
    coach_layout = Column(Text)

    user = relationship("User", back_populates="preferences")


class DailyLog(Base):
    __tablename__ = "daily_logs"
    # One log per user per day. Without this, a concurrent check-then-insert in
    # get_or_create_today_log (chat + native_data + quick_log + water all create
    # "today's log" on launch) can race in two rows for the same date — and
    # get_today_log's scalar_one_or_none() then raises MultipleResultsFound,
    # 500ing every coaching turn for that user (incident 2026-06-20, user 26).
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_log_user_date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    date = Column(Date, nullable=False)
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
    water_entries = relationship("WaterEntry", back_populates="daily_log",
                                 cascade="all, delete-orphan")


class FoodEntry(Base):
    __tablename__ = "food_entries"
    # Day-view joins fetch entries by daily_log_id constantly; Postgres does not
    # auto-index FK columns. Paired with alembic b3c4d5e6f7a8.
    __table_args__ = (
        Index("ix_food_entries_daily_log", "daily_log_id"),
    )

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
    # T2.3 — meal timing + alcohol + micronutrient + photo flags. Enable
    # meal-grouped display, alcohol-aware coaching, and photo-confidence
    # heuristics downstream. Nullable for backward compat with existing rows.
    meal_type = Column(String)               # breakfast|lunch|dinner|snack|pre_workout|post_workout
    meal_time = Column(DateTime)             # when consumed (not when logged)
    alcohol_units = Column(Float)            # for alcohol-aware coaching
    micronutrients_json = Column(Text)       # {"iron": 2.1, "vitamin_d": 400, ...}
    micros_estimated = Column(Boolean, default=False)  # micros came from LLM fallback, not a DB match
    from_photo = Column(Boolean, default=False)
    # NOVA-style processing class set by the model at log time (whole |
    # processed | ultra_processed). The health score prefers this over its
    # food-name keyword proxy. Nullable — older rows fall back to keywords.
    processing_level = Column(String)

    daily_log = relationship("DailyLog", back_populates="food_entries")


class ExerciseEntry(Base):
    __tablename__ = "exercise_entries"
    # Same join pattern as FoodEntry. Paired with alembic b3c4d5e6f7a8.
    __table_args__ = (
        Index("ix_exercise_entries_daily_log", "daily_log_id"),
    )

    id = Column(Integer, primary_key=True)
    daily_log_id = Column(Integer, ForeignKey("daily_logs.id"))
    timestamp = Column(DateTime, server_default=func.now())
    exercise_name = Column(String)
    sets = Column(Integer)
    reps = Column(String)        # e.g. "5" or "5,5,5,4"
    weight = Column(Float)
    # Per-set load (kg). Parallel CSV to `reps` — e.g. "102,107,107" for a
    # pyramid set. Optional: when null the single `weight` value applies to
    # every set (the common case).
    weights = Column(String)
    rir = Column(Integer)        # reps in reserve
    duration_minutes = Column(Float)
    cardio_type = Column(String)
    calories_burned_estimate = Column(Float)
    notes = Column(Text)
    source_type = Column(String, default="text")
    # When the workout actually HAPPENED (user-specified time-of-day, or a wearable
    # workout's start time). `timestamp` is when it was logged; this is when it
    # occurred. Nullable — display/sort falls back to `timestamp` when absent.
    occurred_at = Column(DateTime)
    # External dedup key for entries auto-created from a wearable (e.g.
    # "whoop:<workout_id>"). Lets repeated syncs upsert instead of duplicating.
    source_ref = Column(String, index=True)
    # Average heart rate (bpm) for the session — populated from a wearable workout
    # (WHOOP / Apple Health); null for manual logs.
    avg_hr = Column(Integer)

    daily_log = relationship("DailyLog", back_populates="exercise_entries")


class BodyMetric(Base):
    __tablename__ = "body_metrics"
    # Weight-trend reads (context build every turn) filter user_id and sort by
    # timestamp. Paired with alembic b3c4d5e6f7a8.
    __table_args__ = (
        Index("ix_body_metrics_user_ts", "user_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    weight_kg = Column(Float)
    bodyfat_estimate = Column(Float)
    waist_cm = Column(Float)
    photo_reference = Column(String)
    # T2.5 — when/how the weight was taken. Material for trend interpretation:
    # a "morning_fasted" reading is the gold standard; "post_meal" / "evening"
    # carry noise that should temper the coaching response.
    context = Column(String)  # morning_fasted | post_meal | evening | post_workout | unknown
    # Where the reading came from. A user's deliberate weigh-in ("manual" — chat
    # tool, web /weight, iOS quick-log) is the headline; a passive wearable sync
    # ("apple_health") is a separate parallel row that must never clobber it.
    # Source-aware so a HealthKit reading taken minutes after a manual one stops
    # stacking a near-but-not-identical duplicate (Danny 84.73 manual vs 85.28
    # apple_health, 2026-06-27). server_default backfills existing rows to manual.
    source = Column(String, default="manual", server_default="manual")  # manual | apple_health
    timestamp = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="body_metrics")


class WaterEntry(Base):
    """
    T2.4 — Timestamped hydration log.

    DailyLog.total_water_ml stays as a cached aggregate (updated on each
    log_water call) for backward compatibility with the existing dashboard
    and context display. WaterEntry rows are the canonical source: enables
    timing-aware coaching ("you haven't had water since noon"), per-meal
    hydration patterns, and morning/post-workout context.

    daily_log_id is nullable because a water log MAY arrive before today's
    DailyLog row is materialized (rare, defensive).
    """
    __tablename__ = "water_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    daily_log_id = Column(Integer, ForeignKey("daily_logs.id"), nullable=True)
    amount_ml = Column(Float, nullable=False)
    context = Column(String)  # morning | with_meal | post_workout | during_workout | random
    source_type = Column(String, default="text")
    timestamp = Column(DateTime, server_default=func.now())

    user = relationship("User")
    daily_log = relationship("DailyLog", back_populates="water_entries")


class SupplementIntake(Base):
    """One row = the user took a given supplement on a given LOCAL day.

    The supplement *regimen* (what they take) lives in the brain as
    `health_supplement_*` UserAttributes — Arnie learns those from chat. This
    table is the daily ADHERENCE log layered on top: the Coach "Stack" card lists
    each active supplement and toggles a row here for "taken today". Keyed by the
    supplement's attribute_key so it stays stable across display-name edits.

    UNIQUE (user_id, supplement_key, intake_date) makes the toggle idempotent —
    marking taken twice is a no-op; un-taking deletes the row.
    """
    __tablename__ = "supplement_intakes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    supplement_key = Column(String, nullable=False)   # e.g. "health_supplement_fish_oil"
    supplement_name = Column(String)                  # snapshot of the display name
    intake_date = Column(Date, nullable=False)        # user-local calendar day
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "supplement_key", "intake_date",
                         name="uq_supplement_intake_user_key_date"),
    )

    user = relationship("User")


class ConversationLog(Base):
    __tablename__ = "conversation_logs"
    # The hottest read path in the app: every turn's history fetch, the
    # scheduler's per-user recency window, and proactive routing all filter
    # user_id + order by timestamp. Paired with alembic b3c4d5e6f7a8.
    __table_args__ = (
        Index("ix_conversation_logs_user_ts", "user_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    raw_message = Column(Text)
    parsed_intent = Column(String)
    response = Column(Text)
    timestamp = Column(DateTime, server_default=func.now())
    source_type = Column(String, default="text")
    platform = Column(String, default="telegram")   # "telegram" | "imessage" | "web"
    skills_fired = Column(String)                    # comma-separated skill names that triggered
    # JSON-encoded list of typed inline cards emitted this turn (macro/recap/log/
    # suggestion cards). Persisted so native clients can rehydrate the rich cards
    # when restoring history — without this the transcript reloads text-only and
    # the cards vanish. Null/empty for turns with no cards and for chat-bot turns.
    cards_json = Column(Text)
    # Per-send idempotency key — a stable unique id for the inbound request this
    # turn answered: the iOS client's UUID, Telegram's update_id, or iMessage's
    # message GUID (channel-prefixed). A client retry / webhook redelivery reuses
    # the SAME key, so the entry path can recognize it deterministically and replay
    # (or skip) instead of re-running the turn and double-writing logs. Nullable:
    # legacy rows and any caller that doesn't supply one fall back to the text-window
    # heuristic in chat_service. Indexed for the per-turn lookup.
    idempotency_key = Column(String, index=True)

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
    # Enforce the "one row per user per day" the docstring promises — upsert_health_snapshot
    # is the same check-then-insert race class as daily_logs (see uq_daily_log_user_date).
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_health_snapshot_user_date"),
    )

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
    # The re-ask loop scans open questions (answered_at IS NULL) per user every
    # scheduler tick. Paired with alembic b3c4d5e6f7a8.
    __table_args__ = (
        Index("ix_pending_questions_user_open", "user_id", "answered_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)  # profile_stats | goal_check | weight_checkin | generic | food_clarification
    question = Column(Text, nullable=False)             # the text Arnie asked
    item_referenced = Column(String)                    # what the question is about (e.g. "chicken sandwich") — used by food_clarification
    tier = Column(String, default="casual")             # casual | goal_critical — scales follow-up urgency
    hook_style = Column(String, default="question")     # question | engagement — controls re-ask framing
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
    micros_100_json = Column(Text)  # per-100g micronutrient panel (vitamins/minerals/fats)
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

    LEGACY-ish: this table backs the iOS web "AI Profile → Workout program"
    parser flow + the conversation-history auto-fill (api/app.py). It stores
    one program per user, raw_text + program_json (nested days).

    The science-based program builder writes to a DIFFERENT table
    (`generated_workout_programs`) so multiple builder-generated programs and
    parsed splits can coexist without overwriting each other. The two tables
    share intent (a user's training plan) but live separate lifecycles.
    """
    __tablename__ = "workout_programs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    raw_text = Column(Text)          # original free-text paste
    program_json = Column(Text)      # JSON string: {split_name, focus, rotation, days[]}
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="workout_program")


class GeneratedWorkoutProgram(Base):
    """
    Science-based workout program built by skills/fitness/program_builder.

    Multiple rows per user — every time Arnie builds a new program, a new row
    is inserted and any prior `active=True` row is flipped to `active=False`.
    History is preserved (you can see what the user was running 2 months ago).

    Columns reflect the inputs the builder honors (goal/days/split/equipment/
    experience/weak_points) so the program can be regenerated or diffed.

    Sessions hang off `sessions` relationship — one row per training day,
    each carrying the prescribed exercises as JSON (`exercises_json`).
    """
    __tablename__ = "generated_workout_programs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     index=True, nullable=False)
    name = Column(String, nullable=False)            # "Push / Pull / Legs", "Upper / Lower (4 d/wk)"
    goal = Column(String, nullable=False)            # hypertrophy | strength | general
    days_per_week = Column(Integer, nullable=False)  # 2..7
    split = Column(String, nullable=False)           # ppl | upper_lower | full_body | bro | custom
    equipment_csv = Column(String, default="")       # CSV: barbell,dumbbell,cable,machine,bodyweight
    experience_level = Column(String, default="intermediate")  # beginner | intermediate | advanced
    weak_points_csv = Column(String, default="")     # CSV of muscle ids the user wants biased
    rationale = Column(Text, default="")             # evidence-grounded paragraph
    weekly_volume_json = Column(Text, default="{}")  # JSON: {muscle: weekly_sets}
    notes = Column(Text, default="")                 # user-stated constraints
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    sessions = relationship(
        "GeneratedWorkoutSession",
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="GeneratedWorkoutSession.position",
    )


class GeneratedWorkoutSession(Base):
    """One training day within a GeneratedWorkoutProgram.

    `position` is 1-indexed within the week (1..days_per_week).
    `exercises_json` is a list of:
        {canonical, sets, reps, rir, rest_seconds, notes}
    See skills/fitness/program_builder.serialize_sessions_for_db().
    """
    __tablename__ = "generated_workout_sessions"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer,
                        ForeignKey("generated_workout_programs.id", ondelete="CASCADE"),
                        index=True, nullable=False)
    position = Column(Integer, nullable=False)
    name = Column(String, nullable=False)            # "Push A", "Lower B"
    focus_csv = Column(String, default="")           # CSV of muscle ids
    exercises_json = Column(Text, nullable=False)    # JSON list

    program = relationship("GeneratedWorkoutProgram", back_populates="sessions")


class UserAttribute(Base):
    """
    Flexible per-user attribute store (EAV pattern).

    Captures everything Arnie learns about a user that doesn't have a fixed
    column: supplements, biomarkers, training habits, lifestyle details,
    behavioral patterns, custom tracked metrics — anything.

    New attribute types are rows, never new columns. The system grows without
    migrations.

    attribute_key naming: {category}_{noun}_{qualifier?}
      e.g. nutrition_diet_style, fitness_training_time,
           health_supplement_zinc_mg, lifestyle_wake_time,
           behavior_motivation_driver, custom_anything

    relevance_tier controls context injection:
      core        → always injected into every Arnie conversation
      daily       → injected when updated within the last 7 days
      contextual  → injected when the conversation topic matches category
      archive     → stored, never auto-injected (old lab tests, past injuries)
    """
    __tablename__ = "user_attributes"
    # One row per (user, attribute_key) — the upsert layer relies on this, and the
    # migration enforces it. Declared here so model and migration stay in lockstep
    # (alembic check / create_all both honor it).
    __table_args__ = (
        UniqueConstraint("user_id", "attribute_key", name="uq_user_attribute_key"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    attribute_key = Column(String, nullable=False, index=True)   # canonical key
    display_name = Column(String)                                 # human label
    value = Column(Text, nullable=False)                          # always string
    value_type = Column(String, default="string")                 # float|int|string|bool
    unit = Column(String)                                         # "mg", "hours", "lbs"
    category = Column(String, nullable=False)                     # nutrition|fitness|health|lifestyle|behavior|mental|custom
    relevance_tier = Column(String, default="contextual")         # core|daily|contextual|archive
    attribute_status = Column(String, default="active")           # active|discontinued|historical
    source = Column(String, default="conversation")               # conversation|user_stated|wearable|onboarding
    confidence = Column(String, default="inferred")               # confirmed|inferred|needs_verification
    last_value = Column(Text)                                     # previous value (for bio: "was X, now Y")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="user_attributes")


class PreRegistration(Base):
    """
    Stores profile data collected via the landing-page onboarding form.
    When a user hits /start SETUP-XXXXXX on Telegram, we consume this record
    and pre-populate their profile so they skip conversational onboarding.
    Codes expire after 48 hours and are one-time-use.
    """
    __tablename__ = "pre_registrations"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, index=True, nullable=False)
    profile_json = Column(Text, nullable=False)   # JSON: name, age, sex, height_cm, weight_kg, primary_goal, training_experience, dietary_preferences
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)  # null until redeemed
    telegram_id = Column(String, nullable=True)    # set when consumed
    created_at = Column(DateTime, server_default=func.now())


class DeviceToken(Base):
    """
    A push-notification device token registered by a client (today: APNs from
    the iOS app; later potentially FCM from Android). Many-to-one with users:
    one user can have several devices (iPhone + iPad). The token itself is
    UNIQUE because a physical device generates exactly one token per
    APNs/FCM install — if the same token shows up under a different user
    (someone signed in to a new account on the same device), upsert
    REASSIGNS user_id rather than creating a duplicate.

    Lives in its own table (not on users) because of the 1:N + lifecycle:
    tokens rotate (APNs can rotate a device's token at any time), tokens get
    revoked (sign-out, app uninstall reported by APNs feedback), and the
    sender wants a clean "give me all live tokens for user X" query path.
    """
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # The opaque push token from APNs (hex, 64 chars) or FCM (longer). Indexed
    # + unique so upsert can do a single-row lookup and reassign cleanly.
    token = Column(String, nullable=False, unique=True, index=True)
    # "apns" today. Lets the sender pick the right transport when Android lands.
    platform = Column(String, nullable=False, default="apns")
    # "production" (App Store / TestFlight) or "sandbox" (Debug builds). APNs
    # uses different host names for each; the sender routes by this column.
    environment = Column(String, nullable=False, default="production")
    created_at = Column(DateTime, server_default=func.now())
    # Refreshed on every re-register (every app launch in the typical flow) so
    # the sender can age out tokens that haven't reported in for a long time.
    last_seen_at = Column(DateTime, server_default=func.now())
    # Set when the client explicitly revokes (sign-out) or APNs tells us the
    # token is dead (HTTP 410 from api.push.apple.com). The sender filters
    # revoked tokens out of the recipient list. Keeping the row instead of
    # deleting it preserves history + lets us reactivate if the same token
    # re-registers (the upsert path clears revoked_at).
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="device_tokens")
