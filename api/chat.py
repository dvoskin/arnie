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
from db.queries import resolve_user, get_recent_conversations, save_user_location
from core.chat_service import run_chat_turn
from core.platform import serialize_response, WIRE_VERSION
from api.auth import current_identity, verify_session_token
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])

# The iOS app's platform tag — flows into the prompt/context builders and turn
# telemetry. Defined once here so the whole native surface is consistent.
PLATFORM = "ios"

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

    @field_validator("message")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("message must not be empty")
        return v


class PhotoChatRequest(BaseModel):
    image_base64: str
    caption: str = ""

    @field_validator("image_base64")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("image_base64 must not be empty")
        return v


class VoiceChatRequest(BaseModel):
    audio_base64: str
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


# ── Shared core ──────────────────────────────────────────────────────────────
async def _coached_reply(identity: str, text: str, source_type: str,
                         lat: Optional[float] = None,
                         lng: Optional[float] = None) -> dict:
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
                # Reverse-geocode the city if the row doesn't have one yet.
                # The street-precision readback uses a separate cached call
                # inside context_builder — no need to fetch it here.
                city = user.city
                if not city:
                    try:
                        from core.geocode import reverse as _reverse_geocode
                        city = await _reverse_geocode(lat, lng)
                    except Exception:
                        city = None
                await save_user_location(db, user_id=user.id, lat=lat, lng=lng,
                                          city=city)
                # Re-read so the turn sees the just-saved coords without a
                # stale-cache surprise (save_user_location may keep an existing
                # user-set city over the freshly geocoded one).
                user = await resolve_user(db, identity)
            try:
                turn = await run_chat_turn(
                    db, user, text, platform=PLATFORM, source_type=source_type
                )
            except Exception as e:
                logger.error(f"chat turn failed (identity={identity}): {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="coaching turn failed")

    payload = serialize_response(turn.response)
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
        lat=req.lat, lng=req.lng,
    )


@router.post("/chat/photo")
async def chat_photo(req: PhotoChatRequest, identity: str = Depends(current_identity)):
    """Analyse a photo via the Vision pipeline and log it through the coaching turn.

    Mirrors the Telegram photo path: classify+extract → a tagged block → fed to the
    coach as a `[Photo received]` message (source_type "photo" so logged entries are
    flagged from_photo). Same reply shape as /chat.
    """
    try:
        image_data = base64.b64decode(req.image_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image_base64")
    if not image_data:
        raise HTTPException(status_code=400, detail="Empty image")

    from multimodal.image_handler import process_photo
    analysis = await process_photo(image_data, req.caption or "")
    if not analysis:
        raise HTTPException(status_code=422, detail="Could not analyse the image")

    caption_part = f" Caption: {req.caption}" if req.caption else ""
    combined = f"[Photo received]{caption_part}\n\n{analysis}"
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
    return raw


@router.get("/chat/history")
async def chat_history(identity: str = Depends(current_identity), limit: int = 40):
    """Recent conversation as a flat, chronological message list so the app can
    restore the thread on launch. Each stored turn → one user message (cleaned) +
    its Arnie bubbles (split on the ||| separator). Each message carries the
    turn's `timestamp` (ISO-8601) so the client can render date dividers and
    "minutes ago" labels."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        rows = await get_recent_conversations(db, user.id, limit=limit)

    messages: list[dict] = []
    for row in reversed(rows):  # get_recent_conversations is newest-first → chronological
        # `timestamp` is the SQLAlchemy column on ConversationLog. Send it as
        # ISO-8601 so the iOS contract (Date) parses it via ISO8601DateFormatter.
        # All bubbles in a single turn share the row timestamp — fine because
        # they arrive together; the client only needs gap detection between turns.
        ts_iso = row.timestamp.isoformat() if row.timestamp else None

        user_text = _display_user_text(row)
        if user_text:
            msg = {"author": "user", "text": user_text, "created_at": ts_iso}
            # Flag voice turns so the client can restore a voice-style bubble
            # (transcript shown, no playback — the audio isn't persisted) instead
            # of a plain text bubble.
            raw = (row.raw_message or "").strip()
            if row.source_type == "voice" or raw.startswith("[Voice note]:"):
                msg["voice"] = True
            messages.append(msg)

        # Typed inline cards for this turn (stored as JSON on the row). Attach
        # them to the turn's LAST Arnie bubble so they render beneath the reply,
        # mirroring the live order (text bubbles, then cards).
        cards = []
        if getattr(row, "cards_json", None):
            try:
                cards = json.loads(row.cards_json) or []
            except Exception:
                cards = []

        bubbles = [b.strip() for b in (row.response or "").split("|||") if b.strip()]
        for i, bubble in enumerate(bubbles):
            m = {"author": "arnie", "text": bubble, "created_at": ts_iso}
            if cards and i == len(bubbles) - 1:
                m["cards"] = cards
            messages.append(m)
        # Card-only turn (no text bubbles) — still surface the cards.
        if cards and not bubbles:
            messages.append({"author": "arnie", "text": "", "created_at": ts_iso, "cards": cards})

    return {"v": WIRE_VERSION, "messages": messages}


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
            try:
                identity = verify_session_token((data or {}).get("token") or "")
            except HTTPException:
                await ws.send_json({"type": "error", "detail": "unauthorized"})
                await ws.close(code=4401)
                return
            if not message:
                await ws.send_json({"type": "error", "detail": "empty message"})
                continue
            await _stream_turn(ws, identity, message)
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.error(f"chat stream error: {e}", exc_info=True)
        try:
            await ws.close(code=1011)
        except Exception:
            pass


async def _stream_turn(ws: WebSocket, identity: str, message: str) -> None:
    lock = _locks.setdefault(identity, asyncio.Lock())
    async with lock:
        async with AsyncSessionLocal() as db:
            user = await resolve_user(db, identity)

            async def on_bubble(text: str) -> None:
                await ws.send_json({"type": "bubble", "text": text})

            try:
                turn = await run_chat_turn(
                    db, user, message, platform=PLATFORM, source_type=PLATFORM,
                    on_text_bubble=on_bubble,
                )
            except Exception as e:
                logger.error(f"stream turn failed (identity={identity}): {e}", exc_info=True)
                await ws.send_json({"type": "error", "detail": "coaching turn failed"})
                return

    # `done` carries only bubbles NOT already streamed (e.g. a dashboard link added
    # after the stream), plus reaction/effect/buttons/link/meta.
    done = serialize_response(turn.response)
    done["bubbles"] = turn.response.bubbles[turn.streamed_bubble_count:]
    done["type"] = "done"
    done["meta"] = TurnMeta(
        in_onboarding=turn.in_onboarding,
        just_completed=turn.just_completed,
    ).model_dump()
    await ws.send_json(done)
