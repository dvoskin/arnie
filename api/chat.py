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
import os

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from db.database import AsyncSessionLocal
from db.queries import resolve_user, get_recent_conversations, get_recent_conversations_linked, save_user_location
from core.chat_service import run_chat_turn
from core.platform import Response, serialize_response, WIRE_VERSION, _sanitize_bubble
from api.auth import current_identity, verify_session_token
from core.mutation_contract import mutation_turn
# Shared with the Telegram and iMessage handlers — the coalescing rules and
# their concurrency guarantees are one implementation, not three. The module
# imports only asyncio and logging, so this pulls in no bot dependencies.
from bot.message_debounce import is_running as _debounce_running
from bot.message_debounce import schedule_message as _debounce
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

def _debounce_seconds() -> float:
    """The quiet window before a coalesced turn runs.

    Shorter than the bots' 2.0s on purpose: they are push surfaces where a
    pause is invisible, while an iOS user is watching the screen they just
    typed into. Long enough to catch a thought sent in two or three pieces,
    short enough that a single message does not feel held.

    This never delays the indicator — that frame goes out on receipt — so the
    window costs perceived latency only on turns it is actively merging.
    """
    import os
    try:
        return max(0.0, float(os.getenv("IOS_DEBOUNCE_SECONDS", "1.5")))
    except (TypeError, ValueError):
        return 1.5


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


async def _open_food_clarifications(db, user) -> list[dict]:
    """Food items Arnie is still waiting on an answer about, after this turn.

    These rows already exist — they back the [PENDING CLARIFICATION] prompt
    block — but they never reached the wire, so a turn that logged two of four
    items streamed a macro card for the two that landed and the client had no
    way to say the rest was still open. The card read as "the whole meal is in"
    (Danny, 2026-08-03).

    Read AFTER the turn, so anything the turn just resolved is already gone, and
    anything it newly asked is already here. Best-effort: a failure here reports
    an empty list and the client simply shows no marker — it never costs a reply.
    """
    try:
        from db.queries import get_open_pending_questions
        from core.context_builder import serialize_pending_clarifications
        rows = await get_open_pending_questions(db, user.id)
        food_mode = (getattr(user.preferences, "food_logging_mode", None)
                     if user.preferences else None)
        return serialize_pending_clarifications(rows, food_mode=food_mode)
    except Exception as e:
        logger.warning(f"pending clarification serialize failed: {e}")
        return []


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


#: How long a message will wait behind the same person's previous turn before
#: we answer instead of queueing. The turn budget is 60 s, so without a bound a
#: burst of three messages can leave someone staring at a spinner for minutes —
#: which is exactly what happened (12.8 s of server work, ~3 minutes on the
#: phone, because the receipt only times the turn and not the wait in front of
#: it). Short enough that a normal turn (3-13 s) never reaches it.
_LOCK_WAIT_S = float(os.getenv("CHAT_LOCK_WAIT_S", "22") or 22)

#: A HEADS UP, NOT AN ERROR. Nothing failed and nothing was lost — their
#: message simply arrived while the previous one was still being worked. The
#: line should read like a person saying "hang on", so it varies rather than
#: repeating one canned string at someone sending several things in a row.
_STILL_WORKING = (
    "Hang on, still finishing your last one.|||Send that again in a few seconds "
    "and I'll pick it straight up.",
    "One sec, I'm still logging what you just sent.|||Resend that in a moment.",
    "Give me a beat, still working through the message before this.|||Fire it "
    "again shortly and I'll catch it.",
    "Still catching up on your last one.|||Try that again in a few seconds.",
    "Working on the one before this — didn't want to leave you hanging."
    "|||Resend and I'll get it.",
)


def _still_working_line(seed: str) -> str:
    """Deterministic by content, so the same message never flips wording on a
    retry, and two different messages in a burst do not read as a stuck loop."""
    return _STILL_WORKING[sum(ord(c) for c in (seed or "x")) % len(_STILL_WORKING)]


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
    # Held ALREADY means a turn is mid-flight, which means this message was
    # typed before that turn's reply reached them — so it answers nothing.
    # Read before awaiting the lock; once we're through it the evidence is gone.
    _unseen = lock.locked()
    # BOUNDED. `async with lock` waits forever, so a message sent behind a slow
    # turn is held for that turn's whole budget with no way to say so.
    try:
        await asyncio.wait_for(lock.acquire(), timeout=_LOCK_WAIT_S)
    except asyncio.TimeoutError:
        logger.info(
            "chat: lock still held after %.0fs for identity=%s — answering with "
            "a heads-up rather than queueing further", _LOCK_WAIT_S, identity)
        _hp = serialize_response(Response(
            bubbles=[b for b in _still_working_line(text).split("|||") if b]))
        _hp["tools"] = []
        return _hp
    try:
        # Set unconditionally, never only-when-true: the task running this
        # request may be a reused one, and a stale True from an earlier turn
        # would tell the model to ignore a question the user really did answer.
        # (`CURRENT_ROUTE` resets in a finally for exactly this reason.)
        from core.turn_identity import PRIOR_REPLY_UNSEEN
        PRIOR_REPLY_UNSEEN.set(_unseen)
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
                    # The stored key keeps its historic prefixed shape (exact-
                    # match replay depends on it); the RAW id rides separately
                    # so make_turn_id doesn't double the channel prefix — the
                    # master audit's "ios:ios:<uuid>" ledger rows.
                    idempotency_key=(f"ios:{client_msg_id}" if client_msg_id else None),
                    client_msg_id=client_msg_id,
                )
            except Exception as e:
                logger.error(f"chat turn failed (identity={identity}): {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="coaching turn failed")
            # Read inside the session — the payload is assembled after it closes.
            pending_clarifications = await _open_food_clarifications(db, user)
    finally:
        lock.release()

    payload = serialize_response(turn.response)
    payload["tools"] = _turn_tools(turn)
    payload["pending_clarifications"] = pending_clarifications

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
    # Regenerate/edit: the row this turn REPLACED. Null on a normal turn.
    # Without it the client had to infer the removal from the id it sent, so a
    # regenerated reply landed while the old message and its card stayed on
    # screen. Optional on the wire — older clients ignore it.
    payload["superseded_log_id"] = getattr(turn, "superseded_log_id", None)
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
        # Dashboard/card edits never render in chat AT ALL (Danny 2026-07-23:
        # "don't reiterate edited foods in the chat"). The rows stay in
        # conversation_logs so the model's context knows the board changed —
        # the Log page itself is the visible record of the edit.
        # ...and a one-tap undo, for the same reason: the user watched it
        # happen on the card they tapped. The row stays so the model's context
        # knows the board moved.
        if row.source_type in ("dashboard_edit", "dashboard_delete",
                               "ledger_undo"):
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
        async with mutation_turn(
            db, channel="ios", command="chat_feedback", user_id=user.id,
            dedup=f"rate:{req.log_id}", claim=False,
        ) as turn:
            await turn.audit(db, "updated", domain="chat_feedback",
                             entry_id=req.log_id,
                             payload={"rating": req.rating},
                             surface="ios:chat")
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
    # Per-connection state for the coalesced turn. The client id is the LAST
    # message's, so idempotency claims what the user actually sent last rather
    # than a fragment they have since added to; `unseen` is sticky across the
    # window (see below) and is consumed by the runner.
    _pending: dict = {"client_msg_id": None, "unseen": False}
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

            # ── COALESCE RAPID-FIRE MESSAGES ─────────────────────────────────
            # Three quick texts used to become three turns and three replies:
            # this loop awaited each one, so a message sent while the previous
            # was still running simply waited its turn and then got answered on
            # its own. Telegram and iMessage have had `schedule_message` since
            # the beginning; iOS never did, which is why it is the surface
            # where "chicken" / "and rice" / "for lunch" reliably produced
            # three separate logs and three separate confirmations.
            #
            # Deliberately NOT awaited: returning to receive_json() at once is
            # what lets the next message arrive in time to join the buffer.
            _key = f"ios:{identity}"
            # Asked BEFORE buffering, because the answer expires: a message
            # arriving mid-run is held for a trailing run that begins after the
            # lock clears, and by then nothing can tell it was composed while a
            # reply was already being written. Sticky across the window — if
            # ANY message in it landed mid-run, the coalesced turn is not a
            # reply to what the user hadn't read.
            if _debounce_running(_key):
                _pending["unseen"] = True
            _pending["client_msg_id"] = client_msg_id

            async def _run_coalesced(combined: str, _id=identity) -> None:
                _unseen = bool(_pending.pop("unseen", False))
                try:
                    await _stream_turn(ws, _id, combined,
                                       client_msg_id=_pending.get("client_msg_id"),
                                       prior_reply_unseen=_unseen)
                except WebSocketDisconnect:
                    pass          # they left mid-window; nothing to deliver to
                except Exception as e:
                    logger.error(f"debounced stream turn failed (identity={_id}): {e}",
                                 exc_info=True)
                    try:
                        await ws.send_json({"type": "error",
                                            "detail": "coaching turn failed"})
                    except Exception:
                        pass

            # The indicator goes out NOW, not when the window closes, so the
            # coalescing pause never reads as a dead app. `_stream_turn` sends
            # the same frame when it starts; re-asserting one UI state is free.
            try:
                await ws.send_json({"type": "tool", "tools": ["thinking"]})
            except Exception:
                pass
            await _debounce(_key, message, _run_coalesced,
                            delay=_debounce_seconds())
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.error(f"chat stream error: {e}", exc_info=True)
        try:
            await ws.close(code=1011)
        except Exception:
            pass


async def _stream_turn(ws: WebSocket, identity: str, message: str,
                       client_msg_id: Optional[str] = None,
                       prior_reply_unseen: Optional[bool] = None) -> None:
    lock = _locks.setdefault(identity, asyncio.Lock())
    # See _coached_reply: a lock already held means they were still typing
    # while the previous turn ran, so this message is not a reply to it.
    #
    # The caller may answer this instead, and must when debouncing: a message
    # buffered mid-run is held for a trailing run that starts AFTER the lock is
    # released, so asking the lock here would say "seen" about a message the
    # user demonstrably typed before the reply existed. Whoever took delivery
    # of the message knows; this function only knows when it got around to it.
    _unseen = (bool(prior_reply_unseen) if prior_reply_unseen is not None
               else lock.locked())
    async with lock:
        # Unconditional for the same reason as the REST path — a reused task
        # must not inherit an earlier turn's answer.
        from core.turn_identity import PRIOR_REPLY_UNSEEN
        PRIOR_REPLY_UNSEEN.set(_unseen)
        async with AsyncSessionLocal() as db:
            user = await resolve_user(db, identity)

            async def on_bubble(text: str) -> None:
                # The iOS streamed wire enforces voice, the same way core/platform
                # does for the Telegram/iMessage wire. The streamer sanitizes the
                # model's bubbles before they reach here, but the heads-up path
                # sends straight to this callback — so without this a heads-up
                # line's em dash or lowercase lead would ship raw. _sanitize_bubble
                # is idempotent, so re-cleaning an already-clean bubble is free.
                await ws.send_json({"type": "bubble", "text": _sanitize_bubble(text)})

            async def on_tool_start(tools: list) -> None:
                # Drives the iOS live indicator. DEFAULT: a NEUTRAL "thinking"
                # status so the indicator stays "Thinking…" the whole turn.
                # (Danny 2026-07-21: the action-specific labels often mismatched
                # the real action — but gating the frame OFF entirely made the
                # indicator vanish, because this is the ONLY frame that reaches
                # the client during the held pass-1 + tools + voice window. So we
                # keep sending it, just neutralized.) STREAM_TOOL_STATUS=true
                # sends the real tool names so it morphs to action labels again
                # once the tool→label mapping is trusted.
                _real = os.getenv("STREAM_TOOL_STATUS", "false").lower() in ("true", "1", "yes")
                try:
                    await ws.send_json({"type": "tool", "tools": tools if _real else ["thinking"]})
                except Exception:
                    pass

            async def on_card(cards: list) -> None:
                # The log card, streamed the instant the row is written — BEFORE
                # the follow-up voicing pass — so it lands seconds sooner instead
                # of riding the final done-frame. Clients that ignore "card"
                # frames are unaffected (the done-frame still carries the cards
                # for them). The done-frame dedups these via streamed_card_ids.
                await ws.send_json({"type": "card", "cards": cards})

            # Show the live indicator IMMEDIATELY, before pass-1. The tool
            # decision can take a few seconds, and on a held food-log turn nothing
            # else reaches the client until the very end — so without an early
            # frame the iOS indicator never appears ("thinking doesn't show",
            # Danny 2026-07-21). A neutral "thinking" token renders the base
            # "Thinking…" state; on_tool_start (or STREAM_TOOL_STATUS) morphs it.
            try:
                await ws.send_json({"type": "tool", "tools": ["thinking"]})
            except Exception:
                pass

            try:
                turn = await run_chat_turn(
                    db, user, message, platform=PLATFORM, source_type=PLATFORM,
                    on_text_bubble=on_bubble, on_tool_start=on_tool_start,
                    on_card=on_card,
                    # Same split as the POST endpoint: prefixed key for exact-
                    # match replay, raw id for turn identity.
                    idempotency_key=(f"ios:{client_msg_id}" if client_msg_id else None),
                    client_msg_id=client_msg_id,
                )
            except Exception as e:
                logger.error(f"stream turn failed (identity={identity}): {e}", exc_info=True)
                await ws.send_json({"type": "error", "detail": "coaching turn failed"})
                return
            # Read inside the session — `done` is assembled after it closes.
            pending_clarifications = await _open_food_clarifications(db, user)

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
    done["pending_clarifications"] = pending_clarifications
    done["type"] = "done"
    # Same stable turn identity as the REST path — see payload["log_id"] there.
    done["log_id"] = getattr(turn, "log_id", None)
    done["superseded_log_id"] = getattr(turn, "superseded_log_id", None)
    done["meta"] = TurnMeta(
        in_onboarding=turn.in_onboarding,
        just_completed=turn.just_completed,
    ).model_dump()
    await ws.send_json(done)
