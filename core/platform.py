"""
Platform abstraction layer.

The same coaching logic runs across Telegram and iMessage. They differ only in
HOW a response is rendered:

  Telegram  → HTML bold, inline/reply keyboards, message reactions, inline link buttons
  iMessage  → plain text, tapback reactions, screen effects, plain URLs

A Response is platform-agnostic. Each PlatformAdapter renders it using that
platform's native strengths. Build a Response once, send it anywhere.

This is the single seam between coaching logic and delivery. All outbound
communication flows through here so the two platforms can never drift apart
on presentation again.
"""
from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Semantic reaction / effect names
# ─────────────────────────────────────────────────────────────────────────────
# Coaching logic speaks in intent ("celebrate this", "love that"), not in
# platform-specific codes. Adapters translate intent → native rendering.

class React:
    """Semantic reactions. Adapters map these to native reactions."""
    LOVE      = "love"       # ❤️  — name given, goal hit, PR
    LIKE      = "like"       # 👍  — solid answer, progress logged
    LAUGH     = "laugh"      # 😂  — funny food choice / situation
    EMPHASIZE = "emphasize"  # ‼️  — important callout


class FX:
    """Semantic screen effects. iMessage-only; other platforms ignore."""
    CELEBRATE = "celebrate"  # balloons  — onboarding done, big milestone
    SLAM      = "slam"       # impact    — a PR
    FIREWORKS = "fireworks"  # fireworks — streak / major win
    LASERS    = "lasers"     # lasers    — hype moment
    LOUD      = "loud"       # loud      — making an entrance (intro)


@dataclass
class Button:
    """A quick-reply or link option. Adapters render natively."""
    label: str
    value: Optional[str] = None   # text sent back when tapped (defaults to label)
    url: Optional[str] = None     # if set, this is a link button

    @property
    def send_value(self) -> str:
        return self.value if self.value is not None else self.label


import re as _re_platform

# Tool-call markup the model must NEVER show the user. Under a heavy prompt an
# older model sometimes writes its function-call SYNTAX as text instead of
# executing it (Denys #7129, 2026-07-20: "<invoke name=log_food><parameter
# name=food_name>Огурец…" shipped as his reply). Stripped on the way out at the
# single chokepoint every bubble passes through — closed blocks AND any dangling
# truncated fragment. The conversation pipeline separately RECOVERS the intended
# log from the markup (see extract_leaked_tool_calls).
_TOOL_XML_BLOCK = _re_platform.compile(r"<invoke\b.*?</invoke>", _re_platform.S | _re_platform.I)
_TOOL_XML_FRAG = _re_platform.compile(
    r"</?(?:invoke|parameter)\b[^>]*>?|<invoke\b.*$", _re_platform.S | _re_platform.I)


def _strip_tool_xml(s: str) -> str:
    """Remove any leaked tool-call markup from user-facing text."""
    if s and ("<invoke" in s.lower() or "<parameter" in s.lower()):
        s = _TOOL_XML_BLOCK.sub("", s)
        s = _TOOL_XML_FRAG.sub("", s)
    return s


def _sanitize_bubble(s: str) -> str:
    """
    Enforce the no-em-dash brand rule deterministically. The model is told "no em
    dashes" but keeps producing them, so we strip them on the way out: an em dash is
    almost always a parenthetical or clause break, which a comma handles cleanly.
    (En dashes / hyphens are left alone so number ranges like "12-13%" survive.)
    Also strips any leaked tool-call XML so function-call syntax never ships.
    """
    s = _strip_tool_xml(s or "")
    s = s.replace(" — ", ", ").replace("—", ", ")
    # No tildes either (same deterministic brand rule as the em dash): the model
    # is told not to use "~" but keeps writing "~230 cal". Convert an approximating
    # tilde to the word "about" (honest, keeps the estimate signal); drop a stray ~.
    s = _re_platform.sub(r"~\s*(?=\d)", "about ", s)
    s = s.replace("~", "")
    # Strip leaked INTERNAL entry IDs — "#2032" from a dedup/tool result the model
    # echoed ("logged 13:12 (33s ago) #2032"). Users must NEVER see internal
    # identifiers (Chaya 2026-07-21). 2+ digits so a legit "#1"/"day #2" survives; DB
    # entry ids are multi-digit in practice. Also tidy a now-dangling space before a
    # closing bracket/period.
    s = _re_platform.sub(r"\s*#\d{2,}\b", "", s)
    s = _re_platform.sub(r"\s+([)\].,])", r"\1", s)
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip()


@dataclass
class Response:
    """
    A platform-agnostic coaching response.

    bubbles    — list of short message bubbles, sent in sequence
    reaction   — a React.* applied to the user's incoming message (if supported)
    effect     — an FX.* applied to one bubble (iMessage screen effect)
    effect_idx — which bubble gets the effect (0 = first, -1 = last)
    buttons    — quick-reply choices (Telegram keyboard; iMessage folds into text)
    link       — (label, url) shown prominently (Telegram inline button; iMessage URL)
    """
    bubbles: list[str] = field(default_factory=list)
    reaction: Optional[str] = None
    effect: Optional[str] = None
    effect_idx: int = -1
    buttons: Optional[list[Button]] = None
    link: Optional[tuple[str, str]] = None
    # Typed inline cards for native clients (iOS macro/exercise cards, future
    # charts/maps/tables). Each card is `{type, payload}`. Empty by default;
    # populated when a tool result produces a structured artifact worth showing
    # as a card instead of (or alongside) a text bubble. Telegram/iMessage
    # adapters ignore this — chat-bot transports have no card concept.
    cards: list[dict] = field(default_factory=list)
    # A newly-earned badge this turn (core/achievements.py wire block:
    # {primary: {id,title,line,icon,tier}, new: [ids], celebrate: bool}).
    # iOS drives its celebration overlay from this; other transports ignore it.
    achievement: Optional[dict] = None
    # True when this turn's tools EDITED the training program (day override,
    # targets, add/remove exercise) — iOS refetches the program card so the
    # plan the user just changed in chat is what they see on Coach. Other
    # transports ignore it.
    program_updated: bool = False
    # The turn's reasoning receipt — REAL artifacts (context read, each tool
    # step, checks applied), never model narration. iOS renders it behind a
    # collapsed "How I got this" disclosure. None on trivial turns.
    reasoning: "Optional[dict]" = None

    @classmethod
    def from_text(cls, text: str, **kwargs) -> "Response":
        """Build a Response by splitting raw text on the ||| bubble separator.
        Em dashes are stripped here — it's a hard brand rule the model keeps breaking,
        so enforce it deterministically at the one place all bubbles flow through."""
        # Fix ||| mistakenly placed inside numbers (e.g. "6|||000" → "6,000").
        # This fires only when ||| sits between two digit characters — never intentional.
        text = re.sub(r'(\d)\|\|\|(\d)', r'\1,\2', text or "")
        bubbles = [_sanitize_bubble(b) for b in (text or "").split("|||")]
        bubbles = [b for b in bubbles if b]
        if not bubbles:
            bubbles = ["still here. what's the move?"]
        return cls(bubbles=bubbles, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Base adapter
# ─────────────────────────────────────────────────────────────────────────────

# Inter-bubble delay — fast enough to feel like rapid texting
_BUBBLE_DELAY = 0.35


class PlatformAdapter(ABC):
    """Renders a Response using a platform's native capabilities."""

    name: str = "unknown"
    capabilities: set[str] = set()   # {"reactions","effects","buttons","html","links"}

    def supports(self, cap: str) -> bool:
        return cap in self.capabilities

    @abstractmethod
    async def send(self, response: Response) -> None:
        """Render and deliver the response."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Telegram adapter
# ─────────────────────────────────────────────────────────────────────────────

# Telegram message-reaction emoji (Bot API 7.0+). Best-effort — degrades silently.
_TG_REACTION = {
    React.LOVE: "❤️", React.LIKE: "👍", React.LAUGH: "😂", React.EMPHASIZE: "🔥",
}


class TelegramAdapter(PlatformAdapter):
    name = "telegram"
    capabilities = {"reactions", "buttons", "html", "links"}

    def __init__(self, bot, chat_id: int, reply_to_message_id: Optional[int] = None):
        self.bot = bot
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id

    def _fmt(self, text: str) -> dict:
        """Prepare a bubble for Telegram HTML mode."""
        import html as _html
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^-{3,}\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
        _TAG = re.compile(r'(</?(?:b|i|u|s|code|pre)>)', re.IGNORECASE)
        parts = _TAG.split(text)
        escaped = ''.join(
            p if _TAG.fullmatch(p) else _html.escape(p) for p in parts
        )
        return {"text": escaped.strip(), "parse_mode": "HTML"}

    async def send(self, response: Response) -> None:
        # Reaction on the user's message (best-effort — needs Bot API 7.0+)
        if response.reaction and self.reply_to_message_id:
            emoji = _TG_REACTION.get(response.reaction)
            if emoji:
                try:
                    from telegram import ReactionTypeEmoji
                    await self.bot.set_message_reaction(
                        chat_id=self.chat_id,
                        message_id=self.reply_to_message_id,
                        reaction=[ReactionTypeEmoji(emoji=emoji)],
                    )
                except Exception:
                    pass  # older API / not permitted — skip silently

        # Build reply markup for the LAST bubble (buttons or link)
        reply_markup = self._build_markup(response)

        n = len(response.bubbles)
        for i, bubble in enumerate(response.bubbles):
            kwargs = self._fmt(bubble)
            if i == n - 1 and reply_markup is not None:
                kwargs["reply_markup"] = reply_markup
            try:
                await self.bot.send_message(chat_id=self.chat_id, **kwargs)
            except Exception as e:
                logger.error(f"Telegram send failed: {e}")
            if i < n - 1:
                await asyncio.sleep(_BUBBLE_DELAY)

    def _build_markup(self, response: Response):
        from telegram import (
            InlineKeyboardMarkup, InlineKeyboardButton,
            ReplyKeyboardMarkup,
        )
        if response.link:
            label, url = response.link
            return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])
        if response.buttons:
            # Reply keyboard — one button per row, tappable quick-replies
            rows = [[b.label] for b in response.buttons]
            return ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# iMessage adapter (BlueBubbles)
# ─────────────────────────────────────────────────────────────────────────────

# Semantic React.* values ARE the BlueBubbles reaction strings ("love","like",
# "laugh","emphasize") — passed straight through. Only these four are used.
_IM_REACTIONS = {React.LOVE, React.LIKE, React.LAUGH, React.EMPHASIZE}
# Semantic → iMessage effect id
_IM_EFFECT = {
    FX.CELEBRATE: "com.apple.MobileSMS.expressivesend.balloons",
    FX.SLAM:      "com.apple.MobileSMS.expressivesend.impact",
    FX.FIREWORKS: "com.apple.MobileSMS.expressivesend.fireworks",
    FX.LASERS:    "com.apple.MobileSMS.expressivesend.lasers",
    FX.LOUD:      "com.apple.MobileSMS.expressivesend.loud",
}


class IMessageAdapter(PlatformAdapter):
    name = "imessage"
    capabilities = {"reactions", "effects", "links"}

    def __init__(self, chat_guid: str, reply_to_guid: Optional[str] = None):
        self.chat_guid = chat_guid
        self.reply_to_guid = reply_to_guid

    async def send(self, response: Response) -> None:
        from bot.imessage_handler import (
            bb_send_text, bb_send_text_with_effect, bb_send_reaction, _to_plain,
        )

        # Always log the reaction decision so we can see exactly why one fires or not
        logger.info(
            f"IM send: reaction={response.reaction or '-'} "
            f"reply_to={'yes' if self.reply_to_guid else 'NONE'} "
            f"effect={response.effect or '-'} bubbles={len(response.bubbles)}"
        )

        # Reaction (tapback) on the user's incoming message — awaited (not fire-and-forget)
        # so it can't be dropped and its result is always logged.
        if response.reaction in _IM_REACTIONS and self.reply_to_guid:
            await bb_send_reaction(self.chat_guid, self.reply_to_guid, response.reaction)

        # Fold buttons into the last bubble as natural text (iMessage has no keyboards)
        bubbles = list(response.bubbles)
        if response.buttons and bubbles:
            opts = "  ".join(b.label for b in response.buttons)
            # only append if the options aren't already in the text
            if not any(b.label.lower() in bubbles[-1].lower() for b in response.buttons):
                bubbles[-1] = f"{bubbles[-1]}\n{opts}"

        # Link → append as plain URL bubble
        if response.link:
            label, url = response.link
            bubbles.append(url)

        effect_id = _IM_EFFECT.get(response.effect) if response.effect else None
        eidx = response.effect_idx
        if eidx < 0:
            eidx = len(bubbles) + eidx

        n = len(bubbles)
        for i, bubble in enumerate(bubbles):
            plain = _to_plain(bubble)
            if effect_id and i == eidx:
                await bb_send_text_with_effect(self.chat_guid, plain, effect_id)
            else:
                await bb_send_text(self.chat_guid, plain)
            if i < n - 1:
                await asyncio.sleep(_BUBBLE_DELAY)


# ─────────────────────────────────────────────────────────────────────────────
# JSON wire format — the contract for native clients (the iOS app)
# ─────────────────────────────────────────────────────────────────────────────
# Telegram/iMessage adapters render a Response into platform-native chrome (HTML,
# tapbacks, keyboards). A native app does its OWN rendering, so the wire format is
# kept SEMANTIC: bubbles are plain text, reactions/effects are semantic names
# (React.* / FX.*). The client decides how to draw them — bold, haptics, confetti,
# whatever feels native. This is the single source of truth for that contract.
#
# Versioned so the app and server can evolve independently: bump WIRE_VERSION on a
# breaking shape change and let the client branch on `v`.

WIRE_VERSION = 1


def serialize_response(response: Response) -> dict:
    """Serialize a platform-agnostic Response to the JSON wire contract.

    Pure and side-effect free — safe to call from a request handler or a future
    WebSocket frame builder. Optional fields are emitted as null (not omitted) so
    the client always sees a stable shape.
    """
    return {
        "v": WIRE_VERSION,
        "bubbles": list(response.bubbles),
        "reaction": response.reaction,  # semantic React.* name or None
        "effect": (
            {"name": response.effect, "bubble_idx": response.effect_idx}
            if response.effect else None
        ),
        "buttons": (
            [{"label": b.label, "value": b.send_value, "url": b.url}
             for b in response.buttons]
            if response.buttons else None
        ),
        "link": (
            {"label": response.link[0], "url": response.link[1]}
            if response.link else None
        ),
        # Optional typed cards. Always emitted (possibly empty list) so the
        # client always sees a stable shape — lenient decode lets older clients
        # ignore unknown card `type` values for forward compatibility.
        "cards": list(response.cards),
        # Newly-earned badge this turn (or null) — older clients ignore it.
        "achievement": response.achievement,
        # Program edited this turn — older clients ignore it.
        "program_updated": bool(getattr(response, "program_updated", False)),
        # Reasoning receipt (or null) — older clients ignore it.
        "reasoning": getattr(response, "reasoning", None),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding reaction map — defined ONCE, used by both platforms
# ─────────────────────────────────────────────────────────────────────────────

def onboarding_reaction(field_saved: str) -> Optional[str]:
    """
    Given the profile field a user just provided during onboarding,
    return the semantic reaction to apply to their message.
    """
    return {
        "name":                React.LOVE,
        "current_weight_kg":   React.LIKE,
        "height_cm":           React.LIKE,
        "primary_goal":        React.LIKE,
        "training_experience": React.LIKE,
        "calorie_target":      React.LOVE,
    }.get(field_saved)


# ─────────────────────────────────────────────────────────────────────────────
# Coaching-moment detection — shared by both platforms
# ─────────────────────────────────────────────────────────────────────────────
# Reactions (tapbacks) are subtle — they can fire often and feel delightful.
# Effects (screen animations) are dramatic — reserved for genuine milestones,
# so they keep their punch and never feel gimmicky.

_PR_SIGNALS       = ("pr", "personal best", "personal record", "new max",
                     "all-time", "first time you", "first time at")
_GOAL_HIT_SIGNALS = ("hit your goal", "hit your target", "you're there",
                     "goal weight", "reached your goal", "hit goal")
_PROTEIN_WIN      = ("nailed it", "protein nailed", "hit your protein",
                     "protein's done", "smashed your protein", "protein goal")
_CLEAN_DAY        = ("clean day", "perfect day", "that's the day", "locked in",
                     "right on track", "right where you want")
_MOMENTUM         = ("on track", "on pace", "solid day", "solid week",
                     "good pace", "that tracks", "love it")
_FUNNY            = ("lol", "😂", "interesting choice", "respect", "classic",
                     "bold move", "no judgment", "we've all been there")
_STREAK           = ("days in a row", "straight days", "streak", "consistency")


@dataclass
class Moment:
    reaction: Optional[str] = None
    effect: Optional[str] = None
    effect_idx: int = -1


def detect_moment(response_text: str, tool_calls: list,
                  first_food: bool = False,
                  user_text: str = "",
                  wrote: bool = True) -> Moment:
    """
    Decide what reaction / effect (if any) a coaching response warrants.
    Pure function — used by both Telegram and iMessage adapters for consistency.
    Priority order: milestones (effect) first, then lighter reactions.

    first_food — the caller (conversation.py, which can see the DB) says this
    turn logged the user's FIRST-EVER food. The single most important log in
    the product (activation cliff = food logging) gets the celebration
    regardless of what the reply text happens to say.

    user_text — the USER's message. The laugh tapback keys off THEIR humor,
    never Arnie's own quips (he laughed at his own jokes — Danny 07-19).
    wrote — did a log tool actually WRITE this turn? Dramatic effects need a
    real event behind them; goal/streak language merely restated (a recheck,
    a summary) downgrades to the reaction alone, no fireworks.
    """
    t = (response_text or "").lower()
    ut = (user_text or "").lower()
    names = {tc.get("name") for tc in (tool_calls or [])}
    has_exercise = "log_exercise" in names
    has_food = "log_food" in names

    # ── Milestones (reaction + dramatic effect) ──────────────────────────────
    if first_food and has_food:
        return Moment(React.LOVE, FX.CELEBRATE, -1)      # first-ever food → ❤️ + balloons

    if has_exercise and any(s in t for s in _PR_SIGNALS):
        if wrote:
            return Moment(React.LOVE, FX.SLAM, 0)        # PR → ❤️ + slam
        return Moment(React.LOVE)

    if any(s in t for s in _GOAL_HIT_SIGNALS):
        if wrote:
            return Moment(React.LOVE, FX.FIREWORKS, -1)  # goal weight → ❤️ + fireworks
        return Moment(React.LOVE)

    if any(s in t for s in _STREAK):
        if wrote:
            return Moment(React.LOVE, FX.FIREWORKS, -1)  # streak → ❤️ + fireworks
        return Moment(React.LOVE)

    if any(s in t for s in _PROTEIN_WIN):
        if wrote:
            return Moment(React.LOVE, FX.CELEBRATE, -1)  # protein goal → ❤️ + balloons
        return Moment(React.LOVE)

    if any(s in t for s in _CLEAN_DAY):
        if wrote:
            return Moment(React.LOVE, FX.CELEBRATE, -1)  # clean day → ❤️ + balloons
        return Moment(React.LOVE)

    # ── Lighter reactions (tapback only, no effect) ──────────────────────────
    # Laugh at THEIR joke, never Arnie's own — keyed off the user's message.
    if any(s in ut for s in _FUNNY) or "haha" in ut or "хаха" in ut:
        return Moment(React.LAUGH)                        # funny moment → 😂

    if has_exercise:
        return Moment(React.LIKE)                         # logged a workout → 👍

    if any(s in t for s in _MOMENTUM):
        return Moment(React.LIKE)                         # positive momentum → 👍

    return Moment()
