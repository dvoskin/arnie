"""
Native chat API — the surface the iOS app talks to.

  POST /api/v1/chat         — send a text message, get Arnie's coached reply
  POST /api/v1/chat/photo   — send a photo (base64), logged via the Vision pipeline

Thin transport shell. All coaching logic lives in core/chat_service; the reply
shape is the semantic wire contract from core/platform.serialize_response. Adding a
WebSocket streaming endpoint later reuses the SAME service + serializer — only the
framing changes.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from db.database import AsyncSessionLocal
from db.queries import resolve_user, get_recent_conversations, get_recent_conversations_linked, save_user_location
from core.chat_service import run_chat_turn
from core.platform import serialize_response, WIRE_VERSION
from api.auth import current_identity, verify_session_token
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])

# The iOS app's platform tag — flows into the prompt/context builders and turn
# telemetry. Defined once here so the whole native surface is consistent.
PLATFORM = "ios"


def _voice_replies_enabled() -> bool:
    """When true, a voice-note turn's reply carries a spoken (TTS) audio field
    the client can play back. Same flag the Telegram path uses. Requires
    OPENAI_API_KEY. Defaults OFF."""
    import os
    return os.getenv("VOICE_REPLIES_ENABLED", "false").lower() in ("true", "1", "yes")

# Per-identity pipeline lock. Guarantees two turns for the same user can never
# overlap (the duplicate-log / duplicate-onboarding-question bug class), matching
# the per-user locks the Telegram and iMessage handlers already hold. In-process
# only — fine for a single web worker; revisit if the API scales horizontally.
_locks: dict[str, asyncio.Lock] = {}


# Auth is the shared `current_identity` dependency from api.auth — one identity
# for every native surface (chat + dashboard data).


# ── Wire models ──────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    # Optional live coordinates. iOS attaches these with every message so the
    # backend always has fresh lat/lng before the turn runs. Replaces the
    # previous separate POST /api/v1/location flow, which raced the chat turn
    # (location posted ~14s AFTER the user asked "what's near me?") and left
    # Arnie answering "I don't have your location." `None` = client didn't send.
    # When present, persisted via save_user_location BEFORE the LLM sees the
    # message, so the LOCATION line in context is current to this turn.
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    # Stable per-send id the client generates once and reuses on auto-retry. When
    # present, the backend dedupes a retried send deterministically (replays the
    # first reply instead of re-running + double-logging). Optional + backward-
    # compatible: older clients omit it and fall back to the text-window heuristic.
    client_msg_id: Optional[str] = Field(default=None, max_length=128)

    @field_validator("message")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("message must not be empty")
        return v


class PhotoChatRequest(BaseModel):
    # Cap the base64 payload (~13.3MB base64 ≈ 10MB decoded) so an oversized or
    # malicious body is rejected by Pydantic BEFORE it's fully decoded into
    # memory + sent to the vision model. Client photos downscale to a few hundred
    # KB, so this only ever trips abuse.
    image_base64: str = Field(..., max_length=13_400_000)
    # Optional multi-image turn (client ≥219): every photo of the SAME subject
    # (two angles of a plate, label + plated portion) analysed in ONE vision
    # call. When present, this supersedes image_base64 — which clients still
    # send (first photo) so the payload also works on older servers. Capped at
    # 4 photos; same per-photo size bound as image_base64.
    images_base64: Optional[list[str]] = Field(None, max_length=4)
    caption: str = ""

    @field_validator("image_base64")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("image_base64 must not be empty")
        return v

    @field_validator("images_base64")
    @classmethod
    def _each_bounded(cls, v):
        if v is None:
            return v
        v = [s.strip() for s in v if (s or "").strip()]
        if not v:
            return None
        for s in v:
            if len(s) > 13_400_000:
                raise ValueError("each image must be under ~10MB decoded")
        return v


class VoiceChatRequest(BaseModel):
    # ~27MB base64 ≈ 20MB decoded — generous for a voice note, rejects abuse
    # before Whisper transcription runs on it.
    audio_base64: str = Field(..., max_length=27_000_000)
    filename: str = "voice.m4a"

    @field_validator("audio_base64")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("audio_base64 must not be empty")
        return v


class TurnMeta(BaseModel):
    in_onboarding: bool
    just_completed: bool


def _turn_tools(turn) -> list[str]:
    """Unique tool names fired this turn, in call order — drives the iOS tool
    chips ("Logged", "Reviewed your week", …). The client owns the name→label
    mapping and filtering; the wire just reports raw names. Additive: clients
    that ignore `tools` are unaffected."""
    seen: list[str] = []
    for tc in (getattr(turn, "tool_calls", None) or []):
        name = tc.get("name") if isinstance(tc, dict) else None
        if name and name not in seen:
            seen.append(name)
    return seen


async def _backfill_city(identity: str, lat: float, lng: float) -> None:
    """Reverse-geocode the user's city OFF the turn path (fire-and-forget from
    _coached_reply). Fills users.city only if it's still empty — a user-set or
    concurrently-set city always wins. Fully swallowed: location niceties must
    never surface an error."""
    try:
        from core.geocode import reverse as _reverse_geocode
        city = await _reverse_geocode(lat, lng)
        if not city:
            return
        async with AsyncSessionLocal() as db:
            user = await resolve_user(db, identity)
            if user and not user.city:
                user.city = city
                await db.commit()
    except Exception:
        pass


# ── Shared core ──────────────────────────────────────────────────────────────
async def _coached_reply(identity: str, text: str, source_type: str,
                         lat: Optional[float] = None,
                         lng: Optional[float] = None,
                         client_msg_id: Optional[str] = None) -> dict:
    """Resolve the user, run one coaching turn under the per-identity lock, and
    return the serialized wire payload + turn metadata. Shared by every chat entry.

    When the client attached fresh lat/lng (iOS CoreLocation, web browser
    Geolocation), persist them BEFORE run_chat_turn so the turn's context
    builder sees the up-to-date Location: ON FILE line. Replaces the prior
    racey two-call flow ("post location, then send message") that lost the
    first ask whenever iOS posted location AFTER the chat send."""
    lock = _locks.setdefault(identity, asyncio.Lock())
    async with lock:
        async with AsyncSessionLocal() as db:
            user = await resolve_user(db, identity)
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                # Persist coords NOW; the city reverse-geocode is network I/O
                # that used to run inline HERE — while holding the per-user
                # lock — stalling the coaching turn 100-500ms whenever the
                # geocoder was slow. It now backfills in the background; the
                # next context build reads it. (The street-precision readback
                # uses a separate cached call inside context_builder.)
                await save_user_location(db, user_id=user.id, lat=lat, lng=lng,
                                          city=user.city)
                if not user.city:
                    asyncio.create_task(_backfill_city(identity, lat, lng))
                # Re-read so the turn sees the just-saved coords without a
                # stale-cache surprise.
                user = await resolve_user(db, identity)
            try:
                turn = await run_chat_turn(
                    db, user, text, platform=PLATFORM, source_type=source_type,
                    idempotency_key=(f"ios:{client_msg_id}" if client_msg_id else None),
                )
            except Exception as e:
                logger.error(f"chat turn failed (identity={identity}): {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="coaching turn failed")

    payload = serialize_response(turn.response)
    payload["tools"] = _turn_tools(turn)

    # ── Voice-in → voice-out (iOS) ────────────────────────────────────────────
    # When the user sent a voice note, attach a spoken version of the reply as
    # base64 audio so the app can play it back alongside the text bubbles. Purely
    # ADDITIVE — clients that ignore audio_base64 are unaffected. Gated by
    # VOICE_REPLIES_ENABLED; requires OPENAI_API_KEY. Best-effort: a TTS failure
    # never blocks the text reply.
    if source_type == "voice" and _voice_replies_enabled():
        try:
            from core.llm import strip_for_speech, text_to_speech
            spoken = strip_for_speech("|||".join(turn.response.bubbles))
            if spoken:
                audio = await text_to_speech(spoken, voice="onyx")
                if audio:
                    payload["audio_base64"] = base64.b64encode(audio).decode("ascii")
                    payload["audio_mime"] = "audio/mpeg"
        except Exception as e:
            logger.warning(f"iOS voice reply synth failed (text sent): {e}")
    # Stable identity of this turn's ConversationLog row — the client stamps it
    # on the live bubbles so history reloads dedup by id, not text/timestamp.
    payload["log_id"] = getattr(turn, "log_id", None)
    payload["meta"] = TurnMeta(
        in_onboarding=turn.in_onboarding,
        just_completed=turn.just_completed,
    ).model_dump()
    return payload


# ── Endpoints ────────────────────────────────────────────────────────────────
@router.post("/chat")
async def chat(req: ChatRequest, identity: str = Depends(current_identity)):
    """Run one coaching turn and return the semantic wire payload + turn metadata.

    Optional lat/lng on the request body — when present, persisted to the user
    row before the turn runs so "what's near me?" sees current coordinates in
    the same call (no separate POST /api/v1/location → race window).

    Response shape (see core.platform.serialize_response for the bubble contract):
      { v, bubbles, reaction, effect, buttons, link, meta: { in_onboarding, just_completed } }
    """
    return await _coached_reply(
        identity, req.message, source_type=PLATFORM,
        lat=req.lat, lng=req.lng, client_msg_id=req.client_msg_id,
    )


@router.post("/chat/photo")
async def chat_photo(req: PhotoChatRequest, identity: str = Depends(current_identity)):
    """Analyse a photo via the Vision pipeline and log it through the coaching turn.

    Mirrors the Telegram photo path: classify+extract → a tagged block → fed to the
    coach as a `[Photo received]` message (source_type "photo" so logged entries are
    flagged from_photo). Same reply shape as /chat.
    """
    # Multi-image turn when the client sent one; single legacy field otherwise.
    raw_list = req.images_base64 or [req.image_base64]
    images: list[bytes] = []
    for b64 in raw_list:
        try:
            data = base64.b64decode(b64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid image_base64")
        if data:
            images.append(data)
    if not images:
        raise HTTPException(status_code=400, detail="Empty image")

    from multimodal.image_handler import process_photo
    analysis = await process_photo(images if len(images) > 1 else images[0],
                                   req.caption or "")
    if not analysis:
        raise HTTPException(status_code=422, detail="Could not analyse the image")

    caption_part = f" Caption: {req.caption}" if req.caption else ""
    photo_tag = "[Photo received]" if len(images) == 1 else f"[{len(images)} photos received]"
    combined = f"{photo_tag}{caption_part}\n\n{analysis}"
    return await _coached_reply(identity, combined, source_type="photo")


@router.post("/chat/voice")
async def chat_voice(req: VoiceChatRequest, identity: str = Depends(current_identity)):
    """Transcribe a voice note and log it through the coaching turn. Mirrors the
    Telegram voice path: transcribe → `[Voice note]: <transcript>` → coach
    (source_type "voice"). Same reply shape as /chat."""
    try:
        audio = base64.b64decode(req.audio_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audio_base64")
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio")

    # Whisper occasionally returns "" for ultra-short or silent clips. Log the
    # payload size so a 422 from here is debuggable (matches what client sent).
    logger.info(f"chat/voice: identity={identity} bytes={len(audio)} filename={req.filename!r}")

    from multimodal.voice_handler import process_voice
    transcript = await process_voice(audio, req.filename or "voice.m4a")
    if not transcript:
        # 422 = the audio was decoded fine but Whisper couldn't make sense of it
        # (silence, noise, missing API key, etc). Give the client a structured
        # detail so the chat UI can show "didn't catch that" instead of "Server
        # returned 422".
        raise HTTPException(status_code=422, detail="empty_transcript")

    return await _coached_reply(identity, f"[Voice note]: {transcript}", source_type="voice")


# ── History ──────────────────────────────────────────────────────────────────
def _display_user_text(row) -> Optional[str]:
    """Clean a stored raw_message for display in chat history. Photo/voice turns
    stored an internal tagged message, not what the user 'said'."""
    raw = (row.raw_message or "").strip()
    if row.source_type == "photo" or raw.startswith("[Photo received]"):
        return "📷 Photo"
    if raw.startswith("[Voice note]:"):
        return raw[len("[Voice note]:"):].strip() or "🎤 Voice note"
    if raw in ("", "[start]"):
        return None  # skip system/intro rows
    # Dashboard/card edits store an internal tag ("[edit_food_entry]",
    # "[delete_food_entry]") as the user side — never render it as a user
    # bubble. Arnie's one-line acknowledgment still shows, so the change is
    # surfaced without any internal-looking text.
    if row.source_type in ("dashboard_edit", "dashboard_delete"):
        return None
    if raw.startswith("[") and raw.endswith("]"):
        return None
    return raw


@router.get("/chat/history")
async def chat_history(identity: str = Depends(current_identity), limit: int = 40):
    # Clamp the client-supplied limit — an unbounded value forces a large ordered
    # scan + full-thread serialization across all linked identities (mirrors the
    # groups endpoint's cap).
    limit = max(1, min(limit, 200))
    """Recent conversation as a flat, chronological message list so the app can
    restore the thread on launch. Each stored turn → one user message (cleaned) +
    its Arnie bubbles (split on the ||| separator). Each message carries the
    turn's `timestamp` (ISO-8601) so the client can render date dividers and
    "minutes ago" labels."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        # Merge the turns from EVERY identity linked to this account (Telegram +
        # iMessage + iOS) so the app shows one unified thread — a user can chat on
        # Telegram and review the same conversation here.
        rows = await get_recent_conversations_linked(db, user, limit=limit)

    messages: list[dict] = []
    for row in reversed(rows):  # newest-first → chronological
        # A regenerate REPLACED this reply — the new turn is the reply; the
        # superseded one never renders again (ChatGPT-style swap, not a stack).
        if getattr(row, "superseded_by", None):
            continue
        # `timestamp` is the SQLAlchemy column on ConversationLog. Send it as
        # ISO-8601 so the iOS contract (Date) parses it via ISO8601DateFormatter.
        # All bubbles in a single turn share the row timestamp — fine because
        # they arrive together; the client only needs gap detection between turns.
        ts_iso = row.timestamp.isoformat() if row.timestamp else None
        # The surface this turn happened on, so the app can tag each bubble with a
        # small platform marker (telegram / imessage / ios). Normalize web→ios.
        plat = row.platform or "telegram"
        if plat == "web":
            plat = "ios"

        user_text = _display_user_text(row)
        if user_text:
            # `log_id` = the ConversationLog row id — the STABLE identity the
            # client dedups against on history reloads (text/timestamp matching
            # kept missing edge cases → foreground duplicate bubbles). Same id
            # is shared by every message of the turn; pair with the segment
            # position for a per-bubble key.
            msg = {"author": "user", "text": user_text, "created_at": ts_iso,
                   "platform": plat, "log_id": row.id}
            # Flag voice turns so the client can restore a voice-style bubble
            # (transcript shown, no playback — the audio isn't persisted) instead
            # of a plain text bubble.
            raw = (row.raw_message or "").strip()
            if row.source_type == "voice" or raw.startswith("[Voice note]:"):
                msg["voice"] = True
            messages.append(msg)

        # Typed inline cards for this turn (stored as JSON on the row). Attach
        # them to the turn's FIRST Arnie bubble so they render AFTER the lead-in
        # and BEFORE the close — mirroring the live path (which splits the merged
        # reply at the first paragraph break and drops the card between the halves).
        # Attaching to the last bubble instead made reloaded turns show the card
        # detached at the very end, even when it was woven mid-reply live.
        cards = []
        if getattr(row, "cards_json", None):
            try:
                cards = json.loads(row.cards_json) or []
            except Exception:
                cards = []

        bubbles = [b.strip() for b in (row.response or "").split("|||") if b.strip()]
        for i, bubble in enumerate(bubbles):
            m = {"author": "arnie", "text": bubble, "created_at": ts_iso,
                 "platform": plat, "log_id": row.id}
            if cards and i == 0:
                m["cards"] = cards
            if getattr(row, "feedback", None):
                m["feedback"] = row.feedback
            messages.append(m)
        # Card-only turn (no text bubbles) — still surface the cards.
        if cards and not bubbles:
            messages.append({"author": "arnie", "text": "", "created_at": ts_iso,
                             "cards": cards, "platform": plat, "log_id": row.id})
        # The persisted reasoning receipt rides the turn's LAST message so the
        # client re-attaches "Arnie's Thoughts" at the end of the turn on restore.
        if getattr(row, "reasoning_json", None) and messages \
                and messages[-1].get("author") == "arnie":
            try:
                messages[-1]["reasoning"] = json.loads(row.reasoning_json)
            except Exception:
                pass

    return {"v": WIRE_VERSION, "messages": messages}


class FeedbackRequest(BaseModel):
    log_id: int
    rating: Optional[str] = None  # "up" | "down" | null (clear a prior rating)

    @field_validator("rating")
    @classmethod
    def _valid_rating(cls, v):
        if v not in (None, "up", "down"):
            raise ValueError("rating must be 'up', 'down', or null")
        return v


@router.post("/chat/feedback")
async def chat_feedback(req: FeedbackRequest, identity: str = Depends(current_identity)):
    """Store the user's thumbs verdict on one reply (the app's per-turn 👍/👎).

    Idempotent upsert on the turn's ConversationLog row; re-rating overwrites,
    null clears. Scoped to the caller's linked identities — you can only rate
    your own turns. This is the raw reply-quality signal for review tooling."""
    from sqlalchemy import select
    from db.models import User, ConversationLog

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        canonical_id = user.linked_to_user_id or user.id
        id_rows = await db.execute(
            select(User.id).where(
                (User.id == canonical_id) | (User.linked_to_user_id == canonical_id)
            )
        )
        ids = set(id_rows.scalars().all()) or {user.id}
        row = await db.get(ConversationLog, req.log_id)
        if row is None or row.user_id not in ids:
            raise HTTPException(status_code=404, detail="turn not found")
        row.feedback = req.rating
        await db.commit()
    return {"ok": True, "log_id": req.log_id, "rating": req.rating}


# ── Streaming (WebSocket) ────────────────────────────────────────────────────
@router.websocket("/chat/stream")
async def chat_stream(ws: WebSocket):
    """Streaming chat. Each inbound frame is {token, message}; the reply streams
    back as {type:"bubble", text} frames as the model produces each bubble, then a
    final {type:"done", ...} frame carrying any remaining bubbles + reaction/effect/
    buttons/link/meta. Reuses run_turn's bubble streamer — same brain, live framing.
    The connection stays open for the whole conversation (one turn per inbound frame).
    """
    await ws.accept()
    try:
        while True:
            data = await ws.receive_json()
            message = ((data or {}).get("message") or "").strip()
            client_msg_id = ((data or {}).get("client_msg_id") or "").strip() or None
            try:
                identity = verify_session_token((data or {}).get("token") or "")
            except HTTPException:
                await ws.send_json({"type": "error", "detail": "unauthorized"})
                await ws.close(code=4401)
                return
            if not message:
                await ws.send_json({"type": "error", "detail": "empty message"})
                continue
            await _stream_turn(ws, identity, message, client_msg_id=client_msg_id)
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.error(f"chat stream error: {e}", exc_info=True)
        try:
            await ws.close(code=1011)
        except Exception:
            pass


async def _stream_turn(ws: WebSocket, identity: str, message: str,
                       client_msg_id: Optional[str] = None) -> None:
    lock = _locks.setdefault(identity, asyncio.Lock())
    async with lock:
        async with AsyncSessionLocal() as db:
            user = await resolve_user(db, identity)

            async def on_bubble(text: str) -> None:
                await ws.send_json({"type": "bubble", "text": text})

            async def on_tool_start(tools: list) -> None:
                # Mid-action heads-up so the iOS thinking indicator can morph
                # ("Thinking…" → "Logging…"). Additive; clients that ignore
                # "tool" frames are unaffected.
                await ws.send_json({"type": "tool", "tools": tools})

            async def on_card(cards: list) -> None:
                # The log card, streamed the instant the row is written — BEFORE
                # the follow-up voicing pass — so it lands seconds sooner instead
                # of riding the final done-frame. Clients that ignore "card"
                # frames are unaffected (the done-frame still carries the cards
                # for them). The done-frame dedups these via streamed_card_ids.
                await ws.send_json({"type": "card", "cards": cards})

            try:
                turn = await run_chat_turn(
                    db, user, message, platform=PLATFORM, source_type=PLATFORM,
                    on_text_bubble=on_bubble, on_tool_start=on_tool_start,
                    on_card=on_card,
                    idempotency_key=(f"ios:{client_msg_id}" if client_msg_id else None),
                )
            except Exception as e:
                logger.error(f"stream turn failed (identity={identity}): {e}", exc_info=True)
                await ws.send_json({"type": "error", "detail": "coaching turn failed"})
                return

    # `done` carries only bubbles NOT already streamed (e.g. a dashboard link added
    # after the stream), plus reaction/effect/buttons/link/meta.
    done = serialize_response(turn.response)
    done["bubbles"] = turn.response.bubbles[turn.streamed_bubble_count:]
    # Cards already streamed early (log cards, sent via the "card" frame right
    # after the write) are dropped here so the client doesn't render them twice.
    _early_ids = set(getattr(turn, "streamed_card_ids", None) or [])
    if _early_ids:
        done["cards"] = [c for c in done.get("cards", [])
                         if (c.get("payload") or {}).get("entry_id") not in _early_ids
                         and c.get("entry_id") not in _early_ids]
    done["tools"] = _turn_tools(turn)
    done["type"] = "done"
    # Same stable turn identity as the REST path — see payload["log_id"] there.
    done["log_id"] = getattr(turn, "log_id", None)
    done["meta"] = TurnMeta(
        in_onboarding=turn.in_onboarding,
        just_completed=turn.just_completed,
    ).model_dump()
    await ws.send_json(done)
