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
    proactive_messaging_enabled = Column(Boolean, default=False)
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


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True)
    skill_name = Column(String, unique=True)
    description = Column(Text)
    trigger_conditions = Column(Text)
    markdown_path = Column(String)
