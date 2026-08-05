from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, Date, UniqueConstraint, Index, text,
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
    # Oura OAuth tokens (per-user). NOTE: Oura refresh tokens are single-use —
    # every refresh rotates them, so oura_refresh_token is rewritten on each sync.
    oura_access_token = Column(Text)
    oura_refresh_token = Column(Text)
    oura_token_expires_at = Column(DateTime)
    whoop_user_id = Column(String)
    # Subscription
    subscription_status = Column(String, default="trial")  # trial / active / cancelled / expired
    stripe_customer_id = Column(String, unique=True)
    trial_ends_at = Column(DateTime)
    subscription_ends_at = Column(DateTime)
    # Extended profile — sport and unit preference
    sport = Column(String)                          # e.g. "basketball", "boxing", "running"
    units_preference = Column(String, default="imperial")  # "imperial" | "metric"
    # User-chosen profile icon — a single emoji from the iOS curated picker
    # (falls back to the name-initial disc everywhere when null).
    avatar_emoji = Column(String)
    # AI-generated profile bio (narrative text, refreshed when attributes change significantly)
    user_bio = Column(Text)
    user_bio_updated_at = Column(DateTime)

    # Proactive engagement state — persisted so it survives deploys
    nudges_sent = Column(Text, default="")          # comma-separated day-1 warmup slot keys fired
    whoop_last_notified = Column(String)            # date string of last whoop recovery ping
    weekly_recap_week = Column(String)              # iso year-week of last weekly recap sent
    # Cross-platform continuity — this channel resolves to a canonical user
    linked_to_user_id = Column(Integer, index=True)  # canonical pointer; indexed — filtered 2×/turn (context build) + history + every scheduler tick (alembic ee66ff770011)
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
    # Activation gates — when this user earned each tab. Null = still locked.
    # Set once by core/activation.py when the threshold is crossed and NEVER
    # cleared (deleting a food entry must not re-lock a tab). Existing users
    # are grandfathered by the migration that added these columns.
    log_unlocked_at = Column(DateTime)
    coach_unlocked_at = Column(DateTime)
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
    threads = relationship("UserThread", back_populates="user",
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


class Achievement(Base):
    """An earned badge — quiet trophies, loud moments. One row per badge per
    user (the unique constraint makes awarding naturally idempotent); the
    registry of what each badge_id means lives in core/achievements.py, so
    adding badges never touches the schema."""
    __tablename__ = "achievements"
    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_achievement_user_badge"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    badge_id = Column(String, nullable=False)
    earned_at = Column(DateTime, server_default=func.now())


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
    # auto-index FK columns. Paired with alembic 0a1b2c3d4e5f.
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


class LedgerEvent(Base):
    """Append-only history for the ledger — ALL logging domains
    (FOOD_LEDGER_V2 Phase 2; Danny 2026-07-24: fitness rides the same system).

    Corrections create EVENTS instead of only overwriting state: created /
    updated / deleted rows carrying the entry's state (or the applied changes)
    at event time, scoped by domain (food | exercise | weight | water | …).
    Current state stays materialized on the domain tables for performance;
    this table gives reliable undo (a deleted event carries the full payload
    to restore from), debugging, correction-frequency analytics, and
    protection against silent corruption.

    entry_id is deliberately NOT a foreign key — events must survive the
    entry's deletion (that is the point of the deleted event), and its meaning
    is per-domain (food → food_entries.id, exercise → exercise_entries.id).
    """
    __tablename__ = "ledger_events"
    __table_args__ = (
        Index("ix_ledger_events_user_time", "user_id", "created_at"),
        Index("ix_ledger_events_domain_entry", "domain", "entry_id"),
        Index("ix_ledger_events_turn", "turn_id"),
        # One `created` event per entry, enforced by the database (invariant
        # I3; migration ledgerdedup001). `domain` is part of the key because
        # entry ids come from independent per-domain sequences. Partial: only
        # creations are one-per-entry — updates/deletes legitimately repeat.
        Index("uq_ledger_events_created_entry", "domain", "entry_id",
              unique=True,
              postgresql_where=text(
                  "event_type = 'created' AND entry_id IS NOT NULL"),
              sqlite_where=text(
                  "event_type = 'created' AND entry_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    domain = Column(String, nullable=False, server_default="food")
    # Canonical transaction identity (core/turn_identity, alembic turnid001):
    # which inbound turn produced this write. Null for historical events and
    # non-turn writes (health imports, background jobs).
    turn_id = Column(String)
    entry_id = Column(Integer)               # domain entry id at event time
    daily_log_id = Column(Integer)           # day the entry belonged to
    event_type = Column(String, nullable=False)  # created | updated | deleted
    payload_json = Column(Text)              # entry state / changes at event time
    source = Column(String)                  # structured_food:vX | legacy | ...
    created_at = Column(DateTime, server_default=func.now())


class IdempotencyRecord(Base):
    """One logical write request, claimed exactly once (invariant I18).

    The direct-write surfaces — the iOS tap-log endpoints above all — had no
    identity for a REQUEST, only for the rows it produced. So a double tap, a
    mobile retry on a flaky network, or an OS-level replay wrote the food
    twice: two `created` events, two entries, a day total counting a banana
    the user ate once. Nothing in the schema could tell the second delivery
    from a second banana, because nothing recorded that a request had already
    been served.

    The key is supplied by the CLIENT and scoped by (channel, user, command)
    so two surfaces can never collide on the same opaque uuid. Only the client
    knows whether a second identical request is a retry or a second helping —
    which is why an ABSENT key never triggers deduplication. A missing key
    means "I cannot tell you", and the safe answer to that is to write the
    food, not to silently drop it.

    `fingerprint` is a hash of the request payload. A key replayed with a
    DIFFERENT payload is not a retry, it is a client bug losing someone's
    food, and it fails loudly (409) instead of returning the wrong result.

    Enforcement is the unique index on `key`, not this docstring: the helper
    is insert-first precisely so that two racing workers resolve against the
    database rather than against each other.
    """
    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index("uq_idempotency_key", "key", unique=True),
        Index("ix_idempotency_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    # "<channel>:<command>:<user_id>:<client key>" — see core/idempotency.
    key = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    command = Column(String, nullable=False)     # log_food | log_exercise | ...
    channel = Column(String, nullable=False)     # ios | telegram | web | ...
    # The canonical turn this request became (core/turn_identity), so an
    # idempotency record joins the ledger events it produced.
    turn_id = Column(String, index=True)
    fingerprint = Column(String, nullable=False)  # sha256 of the request payload
    status = Column(String, nullable=False, server_default="in_progress")
    # Where the committed result lives, so a replay returns the ORIGINAL row
    # rather than re-deriving one.
    result_entry_id = Column(Integer)
    result_daily_log_id = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)


class TurnMetric(Base):
    """One completed request, summarised so latency outlives the logs.

    `RequestTrace` emits a good line — total, per-stage breakdown, outcome,
    build — and a line is not a dataset. Render retains logs for days, the
    question "did p95 regress after that deploy" is asked in weeks, and the
    +54% p50 regression flagged 2026-07-30 was never explained because by the
    time anyone looked the evidence had rotated away.

    Deliberately a SUMMARY, not a span store. One row per request with the
    stage breakdown as JSON: enough to compute percentiles by route, channel
    and stage, cheap enough to write on every turn, and small enough that
    retention is a delete rather than a project. If per-span querying is ever
    needed, this table is what will justify it.

    Carries `build_sha` because a latency comparison across a deploy is the
    whole point, and `turn_id` because a slow p99 is worth joining back to the
    request that produced it.
    """
    __tablename__ = "turn_metrics"
    __table_args__ = (
        Index("ix_turn_metrics_time", "created_at"),
        Index("ix_turn_metrics_route_time", "command", "created_at"),
        Index("ix_turn_metrics_turn", "turn_id"),
    )

    id = Column(Integer, primary_key=True)
    turn_id = Column(String)
    user_id = Column(Integer)
    channel = Column(String)
    command = Column(String)              # the route, in RequestTrace terms
    outcome = Column(String)              # ok | conflict | error:<Class>
    total_ms = Column(Integer)
    stages_json = Column(Text)            # {"claim": 2, "write": 80, ...}
    build_sha = Column(String)
    created_at = Column(DateTime, server_default=func.now())


class DeliveryAttempt(Base):
    """What actually happened when we tried to reach a user.

    Until this existed, a proactive `conversation_logs` row meant "we reached
    the send function" — it covered a delivered push, a provider rejection, a
    user with no registered device, a swallowed exception, and a message the
    kill switch stopped. Three things were built on that row and all three
    inherited the ambiguity: the 24h cadence budget, the silence streak, and
    engagement analysis. A user whose pushes all fail was rate-limited as
    though they were being reached.

    One row per attempt, so a fan-out to three devices that half-fails is
    legible instead of averaged into a boolean. `accepted` means a provider
    took responsibility; `delivered` is deliberately separate and unset, so a
    receipt callback can land later without redefining what accepted meant.
    """
    __tablename__ = "delivery_attempts"
    __table_args__ = (
        Index("ix_delivery_attempts_user_time", "user_id", "attempted_at"),
        Index("ix_delivery_attempts_status", "status"),
        Index("ix_delivery_attempts_turn", "turn_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    #: The canonical turn that generated the message, so a delivery joins the
    #: request that produced it — the same id the ledger and traces carry.
    turn_id = Column(String)
    slot_key = Column(String)                  # which nudge this was
    channel = Column(String, nullable=False)   # ios | telegram | imessage
    provider = Column(String)                  # apns | telegram | imessage
    #: NEVER the token or address itself. A short reference (device row id,
    #: last four) is enough to correlate without putting a credential in a
    #: table that analytics will read.
    destination_reference = Column(String)
    attempt_number = Column(Integer, server_default="1")
    status = Column(String, nullable=False)    # see core/delivery
    provider_message_id = Column(String)
    failure_code = Column(String)
    failure_detail = Column(Text)              # redacted
    token_invalidated = Column(Boolean, server_default="0")
    attempted_at = Column(DateTime, server_default=func.now())
    accepted_at = Column(DateTime)
    delivered_at = Column(DateTime)
    build_sha = Column(String)


class BackgroundJob(Base):
    """Durable post-turn work (P0.7, architecture review 2026-07-24).

    Profile synthesis and memory reflection used to run as detached
    asyncio.create_task calls: a deploy, crash or process shutdown dropped
    them silently, with no retry — so whether a durable fact got remembered
    depended on process luck. A row here survives all three. The in-process
    task stays the FAST path; the row is the guarantee, swept by the
    scheduler for anything left pending or failed.

    dedup_key collapses repeats (same user + kind within a window) so a busy
    conversation doesn't queue twenty profile rebuilds.
    """
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_due", "status", "next_attempt_at"),
        Index("ix_background_jobs_user", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String, nullable=False)          # profile_update | reflection
    payload_json = Column(Text)
    status = Column(String, nullable=False, server_default="pending")  # pending|done|failed
    attempts = Column(Integer, server_default="0")
    dedup_key = Column(String)
    last_error = Column(Text)
    next_attempt_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    # OUTBOX FIELDS (2026-07-31). This table already was an outbox in all but
    # name — durable, retried, backed off, deduped. What it could not do was
    # say WHICH turn queued the work, which build queued it, or which worker
    # holds it right now.
    #
    # `turn_id` is the same canonical id the ledger event and request trace
    # carry, so post-commit work joins the request that caused it instead of
    # floating free. `build_sha` answers "which deploy queued this" for a job
    # that fails days later.
    #
    # `claimed_at` plus the `processing` status is what makes more than one
    # worker safe: claiming used to be a plain SELECT, so two sweepers would
    # both pick up the same row and do the work twice. Harmless for the two
    # idempotent job kinds that existed, not harmless for delivery.
    turn_id = Column(String, index=True)
    build_sha = Column(String)
    claimed_at = Column(DateTime)


class ProcessedTurn(Base):
    """Durable exactly-once for structured food commits (FOOD_LEDGER_V2 Phase 2).

    One row per (user, idempotency key) claimed at commit time. A resend,
    double-tap, cross-device race, or post-restart redelivery of the same
    (message, plan) finds the claim and is answered from it instead of writing
    a second meal. The in-process TTL registry (core/food_ledger) stays as the
    fast path; this table is what survives restarts. Rows are time-scoped by
    the reader (a key older than the dedup window no longer blocks — the same
    'had a banana' tomorrow is a new turn).
    """
    __tablename__ = "processed_turns"
    __table_args__ = (
        UniqueConstraint("user_id", "idem_key", name="uq_processed_turn_key"),
        Index("ix_processed_turns_user_time", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    idem_key = Column(String, nullable=False)
    result_summary = Column(Text)            # what the turn did (item names)
    created_at = Column(DateTime, server_default=func.now())


class ExerciseEntry(Base):
    __tablename__ = "exercise_entries"
    # Same join pattern as FoodEntry. Paired with alembic 0a1b2c3d4e5f.
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
    #: The training SESSION these sets belong to — the fitness analogue of a
    #: meal group. One row is one set; five rows of `sets=1` for the same
    #: movement are one exercise inside one workout, and nothing used to say
    #: so, leaving every consumer to re-infer it from names and clock times.
    #: Live surfaces (rest timer, form cues, an in-progress view) need a
    #: session to attach to, and the ledger needs one to describe.
    #:
    #: NULL on historic rows, deliberately: there is no session we can honestly
    #: reconstruct for them, and inventing one from timestamps would bake in
    #: exactly the guesswork this removes. Readers treat NULL as "its own".
    workout_group_id = Column(String, index=True)

    daily_log = relationship("DailyLog", back_populates="exercise_entries")


class HealthImportTombstone(Base):
    """A source_ref the user DELETED — auto-import must never resurrect it.

    Apple Health uses replace-on-sync and WHOOP upserts by ref, so without a
    tombstone a deleted auto-imported workout reappears on the next sync
    (Danny's 25-min 'Workout', 2026-07-24). Written by delete_exercise_entry
    whenever the removed row carries a source_ref; honored by both ingests.
    Paired with alembic hlthtomb0001.
    """
    __tablename__ = "health_import_tombstones"
    __table_args__ = (
        UniqueConstraint("user_id", "source_ref", name="uq_tombstone_user_ref"),
    )
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_ref = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class BodyMetric(Base):
    __tablename__ = "body_metrics"
    # Weight-trend reads (context build every turn) filter user_id and sort by
    # timestamp. Paired with alembic 0a1b2c3d4e5f.
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
    # user_id + order by timestamp. Paired with alembic 0a1b2c3d4e5f.
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
    # User's verdict on this reply — "up" / "down" / NULL (no rating). Set from
    # the app's per-turn thumbs; the raw signal for reply-quality review.
    # Paired with alembic migration (add_convlog_feedback).
    feedback = Column(String)
    # The turn's reasoning receipt ("Arnie's Thoughts") as JSON — steps +
    # duration_ms, assembled deterministically at turn end. Persisted so the
    # disclosure survives history reloads. Null for pure-chat turns.
    reasoning_json = Column(Text)
    # Set when a [REGENERATE] turn replaced this reply — points at the new
    # ConversationLog row. Superseded rows are hidden from history (the
    # regenerate REPLACES the reply, ChatGPT-style, instead of stacking).
    superseded_by = Column(Integer)
    # THE CANONICAL TURN IDENTITY — the same value `core/turn_identity` stamps
    # (via the contextvar) on every ledger_events row this turn wrote. This
    # column is what makes turn⋈operation a join instead of a prefix
    # heuristic: before it, the master audit (2026-07-30 §9) could not verify
    # "a narrated success has a matching operation" at all, because the turn
    # id lived only on the ledger side in three inconsistent formats.
    # Nullable: historic rows, and surfaces not yet routed through a turn.
    # Paired with alembic migration turnjoin001.
    turn_id = Column(String, index=True)

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


class PendingOperation(Base):
    """A multi-turn operation, durable across restarts and workers.

    NOT `conversation.payload_json`. That is a question's payload on a
    pending_questions row; this is the OPERATION, with its own lifecycle,
    revision and concurrency control.

    `status` holds the full operation lifecycle. `storage_status` is a
    PROJECTION kept for cheap open/closed queries — five operation states share
    "active", so reconstructing `status` from it is guessing, and doing so is
    the one thing this pair must never be used for.
    """
    __tablename__ = "pending_operations"
    __table_args__ = (
        Index("ix_pending_operations_open", "user_id", "domain",
              "storage_status"),
    )

    id = Column(Integer, primary_key=True)
    operation_id = Column(String, nullable=False, unique=True)
    user_id = Column(Integer, nullable=False)
    domain = Column(String, nullable=False, server_default="food")

    status = Column(String, nullable=False)
    storage_status = Column(String, nullable=False, server_default="active")
    #: Incremented whenever semantic content changes. Every write is
    #: conditional on the revision the writer read, so a stale update fails
    #: rather than overwriting a newer one.
    revision = Column(Integer, nullable=False, server_default="0")
    source_turn_id = Column(String, nullable=True)

    #: Versioned JSON. An unknown future field must not break a read.
    canonical_payload = Column(Text, nullable=True)
    unresolved_fields = Column(Text, nullable=True)
    assumptions = Column(Text, nullable=True)
    mode = Column(String, nullable=True)

    answer_claim_key = Column(String, nullable=True)
    commit_key = Column(String, nullable=True)

    attempt_count = Column(Integer, nullable=False, server_default="0")
    max_attempts = Column(Integer, nullable=False, server_default="3")
    last_error = Column(Text, nullable=True)
    terminal_reason = Column(String, nullable=True)

    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True)
    committed_at = Column(DateTime, nullable=True)


class MealCommit(Base):
    """One ledger mutation, made unrepeatable by the database.

    `pending_store.claim()` guarantees one consumer of the clarification
    ANSWER. This guarantees one WRITE of the meal that follows — a different
    promise, and the gap between them is a real sequence: claim, commit, crash
    before marking consumed, retry, commit again.

    An application check cannot arbitrate that (two workers both read "not
    committed" and both write), so uniqueness is a CONSTRAINT.

    `result_payload` exists so a duplicate can be answered with what the FIRST
    attempt produced. Skipping silently leaves the caller unable to tell
    "already done" from "nothing happened".
    """
    __tablename__ = "meal_commits"
    __table_args__ = (
        UniqueConstraint("operation_id", "operation_revision",
                         name="uq_meal_commits_operation_revision"),
        Index("ix_meal_commits_user", "user_id", "created_at"),
    )

    commit_id = Column(Integer, primary_key=True)
    operation_id = Column(String, nullable=False)
    #: A corrected meal is a NEW mutation of the SAME operation. The revision
    #: lets that through while still refusing a duplicate of either.
    operation_revision = Column(Integer, nullable=False, server_default="0")
    commit_key = Column(String, nullable=True)
    status = Column(String, nullable=False, server_default="claimed")
    result_payload = Column(Text, nullable=True)
    user_id = Column(Integer, nullable=False)
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
    # scheduler tick. Paired with alembic 0a1b2c3d4e5f.
    __table_args__ = (
        Index("ix_pending_questions_user_open", "user_id", "answered_at"),
        # "One open row per (user, kind) is the norm; the reminders layer
        # enforces that" — now the DATABASE enforces it (invariant I2,
        # migration pendinguniq001), per (user, kind, PURPOSE):
        # `item_referenced` is part of the key because the clarification
        # kinds legitimately hold one open row per item (the sandwich's
        # cook-method question and the salad's dressing question coexist).
        # COALESCE folds NULL/'' together so ref-less kinds stay strictly
        # one-per-kind. record_pending_question's get-then-insert race and
        # any writer that skips the helper hit this instead of stacking.
        Index("uq_pending_open_per_user_kind", "user_id", "kind",
              text("COALESCE(item_referenced, '')"),
              unique=True,
              postgresql_where=text("answered_at IS NULL"),
              sqlite_where=text("answered_at IS NULL")),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)  # profile_stats | goal_check | weight_checkin | generic | food_clarification
    question = Column(Text, nullable=False)             # the text Arnie asked
    item_referenced = Column(String)                    # what the question is about (e.g. "chicken sandwich") — used by food_clarification
    tier = Column(String, default="casual")             # casual | goal_critical — scales follow-up urgency
    hook_style = Column(String, default="question")     # question | engagement — controls re-ask framing
    # ASK-FIRST hold only: JSON of the log_food tool inputs HELD on turn 1, so the
    # answer turn can replay them DETERMINISTICALLY if the model loops instead of
    # committing — never lose a held meal. NULL for every other pending kind.
    payload_json = Column(Text)
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
    # THE LABEL'S OWN SERVING, verbatim — "3 pieces (30 g)", "about 30 chips
    # (28 g)". Open Food Facts publishes it, `off.search` already returns it,
    # and `normalize.serving_unit_mass` already turns it into grams-per-unit —
    # for THIS product, off THIS record. It was simply never stored, so every
    # repeat log of a branded food arrived holding per-100g and nothing else.
    #
    # That is what makes a counted portion unanswerable. "5 twizzlers" has no
    # mass, and with no serving panel to divide, the model's calorie guess
    # becomes the anchor with nothing able to check it: 2026-07-31 logged five
    # Twizzlers at 323 cal, which is the per-100g density, against 162 from the
    # label. Three users hit the same shape in 30 days, in both directions —
    # two 16 oz lattes logged as 200 cal understated by half.
    #
    # Absence stays meaningful. A panel with a mass but no count ("50 g") or
    # neither ("") parses to None, and the portion stays unscalable — which the
    # ask ladder can act on and a guess cannot.
    serving_text = Column(String)
    confidence = Column(String, default="estimated")  # exact|likely|estimated|user-confirmed
    user_confirmed = Column(Boolean, default=False)
    # Which authority tier produced these numbers the FIRST time. This row is
    # written automatically after every successful lookup, so most rows are a
    # cache of our own answer rather than anything the user vouched for — and
    # without this column there was no way to tell the two apart after the
    # fact. A cached generic that re-enters as a user regular outranks the
    # actual product label forever; see resolver tier order.
    origin_tier = Column(String)  # SourceTier label, e.g. "generic_exact"
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


class UserThread(Base):
    """
    An open loop Arnie is tracking — the time-bound, followed-through slice of
    the memory graph. Complements UserAttribute (the durable, timeless "knowing
    you" slice): an attribute is "likes sushi"; a THREAD is "Hamptons trip next
    weekend", "trying to fix breakfast", "resting a tweaked shoulder a week", "I
    promised to check on tonight's workout" — something with a status that
    OPENS, gets woven into coaching, and eventually CLOSES.

    This is the memory-graph SPINE (Stage 1). Kinds are stored as a string, not
    an enum, so a new coaching situation never needs a migration. Over later
    stages pending_questions + schedule_check_in fold into this store; for now it
    runs alongside them (extend, don't duplicate — see docs/MEMORY_GRAPH.md).

    Lifecycle:
      open    → created; surfaces in the [OPEN THREADS] context block every turn
      done    → resolved (they reported back / it happened) — stops surfacing
      dropped → cancelled / no longer relevant
      expired → past expires_at with no resolution (garbage-collected)

    Stage 1 STORES next_touch_at but never acts on it; Stage 2's proactive
    scheduler scans (status, next_touch_at) to follow up the day before an event
    etc. The indexes below serve both the per-turn open-threads read and that
    future scan.
    """
    __tablename__ = "user_threads"
    __table_args__ = (
        Index("ix_user_threads_user_status", "user_id", "status"),
        Index("ix_user_threads_touch", "status", "next_touch_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # event|intention|habit|constraint|promise|watch_item|decision|experiment|milestone|state|other
    kind = Column(String, nullable=False)
    summary = Column(Text, nullable=False)          # "Hamptons trip with wife + baby, high-end restaurants"
    details = Column(Text)                           # optional JSON/text extras (location, related refs)
    status = Column(String, default="open", nullable=False)  # open|done|dropped|expired
    salience = Column(Integer, default=3)           # 1..5 — how much it should shape coaching
    source = Column(String, default="stated")       # stated|inferred|researched — provenance kind
    origin_platform = Column(String)                # ios|telegram|imessage
    provenance_log_id = Column(Integer)             # conversation_logs.id that created it (soft ref, no FK coupling)
    start_at = Column(DateTime)                     # when the thing happens/starts
    due_at = Column(DateTime)                       # deadline
    next_touch_at = Column(DateTime)                # when to proactively surface (Stage 2)
    expires_at = Column(DateTime)                   # auto-close after this (GC)
    last_referenced_at = Column(DateTime)           # last time it surfaced / was mentioned
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="threads")


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


class Group(Base):
    """A community space (2026-07-06, Groups v1). Two kinds:
      'open'     — normal group chat, every member sees every message.
      'feedback' — a private line to the team: members see ONLY their own
                   messages; admins (GROUP_ADMIN_USER_IDS) see everything.
    Launch set: 'Beta Insiders' (open) + 'Feedback' (feedback), seeded
    idempotently by api/groups.ensure_default_groups."""
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(String)
    emoji = Column(String, default="👥")   # lightweight avatar until images exist
    kind = Column(String, nullable=False, default="open")  # open | feedback
    created_at = Column(DateTime, server_default=func.now())


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member"),
        Index("ix_group_members_user", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    joined_at = Column(DateTime, server_default=func.now())


class GroupMessage(Base):
    __tablename__ = "group_messages"
    # Chat pagination reads (group_id, id DESC) — covered from day one.
    __table_args__ = (
        Index("ix_group_messages_group", "group_id", "id"),
        Index("ix_group_messages_user", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    # Direct reply (v1.1) — inline quoted reply, not a separate thread surface.
    reply_to_id = Column(Integer, ForeignKey("group_messages.id"), nullable=True)
    # Photo message (v1.2) — a downscaled JPEG as base64, served lazily via the
    # per-message image endpoint (never inlined into the page payload). Beta-
    # scale storage choice; swap to object storage when rooms grow.
    image_b64 = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class GroupMessageReaction(Base):
    """One emoji per (message, user, emoji) — tap toggles (v1.1). Reactions
    inherit the message's visibility: if you can see the message you see its
    reactions, which is what lets a member see the team ❤️ on their feedback."""
    __tablename__ = "group_message_reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", "emoji", name="uq_group_reaction"),
        Index("ix_group_reactions_message", "message_id"),
    )

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("group_messages.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    emoji = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class UserFoodPreference(Base):
    """What a phrase means for THIS user (directive 14).

    "my Fairlife" is Core Power Elite 14 oz. "my yogurt" is Chobani Zero Sugar
    vanilla. "turkey slices" are the thin Boar's Head ones at about 0.8 oz each.
    Once a question has been answered the same way enough times, asking it again
    is the system failing to learn.

    Deliberately NOT a nutrition cache. It stores the identity and the portion
    defaults; the resolver still prices them. A cached number goes stale when a
    product is reformulated — a cached identity does not, and the existing
    UserFoodMatch already covers nutrition caching with its own staleness rules.

    Promotion is guarded: a preference is not created from a single occurrence.
    See skills/nutrition/preferences.py for the rule and its reasoning.
    """
    __tablename__ = "user_food_preferences"
    __table_args__ = (
        # One row per (user, phrase) — a second would make "which default
        # applies" undecidable.
        UniqueConstraint("user_id", "trigger_term",
                         name="uq_user_food_pref_term"),
        Index("ix_user_food_prefs_user", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    trigger_term = Column(String, nullable=False)   # normalized user phrase

    canonical_name = Column(String)
    brand = Column(String)
    product_line = Column(String)
    variant = Column(String)
    package_amount = Column(Float)
    package_unit = Column(String)

    default_consumed_fraction = Column(Float)
    default_unit_mass_g = Column(Float)

    confirmations = Column(Integer, server_default="0", nullable=False)
    contradictions = Column(Integer, server_default="0", nullable=False)
    confidence = Column(Float, server_default="0", nullable=False)
    promoted_at = Column(DateTime)          # null until the rule is satisfied
    last_confirmed_at = Column(DateTime)
    last_contradicted_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())


class FoodCorrection(Base):
    """A correction, kept as evidence (directive 15).

    When a user says "no, it was the Elite bottle" the entry gets fixed and the
    information is currently thrown away — so the same mis-pick happens again
    next week. This row keeps what was said, what we chose, what they meant, and
    the full candidate ranking at decision time.

    The ranking is the part that makes it useful: "why did it pick that?" is
    unanswerable after the fact without it, and improving alias maps or scoring
    from remembered complaints is guesswork.
    """
    __tablename__ = "food_corrections"
    __table_args__ = (
        Index("ix_food_corrections_user_time", "user_id", "created_at"),
        Index("ix_food_corrections_field", "field_name"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    turn_id = Column(String)
    staged_item_id = Column(String)
    entry_id = Column(Integer)              # not an FK: survives the entry

    original_text = Column(String)
    ambiguity_type = Column(String)
    field_name = Column(String)
    chosen_value = Column(String)
    corrected_value = Column(String)
    chosen_candidate_id = Column(String)
    corrected_candidate_id = Column(String)
    candidate_ranking_json = Column(Text)
    mode = Column(String)
    via_alias = Column(String)
    created_at = Column(DateTime, server_default=func.now())
