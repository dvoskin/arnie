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

    @classmethod
    def from_text(cls, text: str, **kwargs) -> "Response":
        """Build a Response by splitting raw text on the ||| bubble separator."""
        bubbles = [b.strip() for b in (text or "").split("|||") if b.strip()]
        if not bubbles:
            bubbles = ["done."]
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

# Semantic → BlueBubbles tapback code
_IM_TAPBACK = {
    React.LOVE: 2000, React.LIKE: 2001, React.LAUGH: 2003, React.EMPHASIZE: 2004,
}
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

        # Reaction (tapback) on the user's incoming message
        if response.reaction and self.reply_to_guid:
            code = _IM_TAPBACK.get(response.reaction)
            if code:
                asyncio.create_task(bb_send_reaction(self.reply_to_guid, code))

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
