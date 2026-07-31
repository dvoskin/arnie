"""A voice corpus — what Arnie actually says, by message shape.

§8 of the scorecard was UNKNOWN because there was nothing to measure against.
This is the something. It is NOT sampled from production (the only tool that did
that, `extract_replay_corpus.py`, writes beta-user transcripts into a PUBLIC
repo and is banned). It is instead the DETERMINISTIC voice — the bubbles the
code ships verbatim, imported from their real source so the corpus can never
drift from what actually sends — plus a curated set of representative examples
for the shapes an LLM turn produces (a log confirmation, a recap, a nudge, a
milestone, a question), written in Arnie's shipped voice.

Each case is `(shape, text)` where text is the raw ||| bubble string BEFORE the
platform seam. `scripts/voice_audit.py` runs `core.voice.check_voice` over each,
pre- and post-seam, so we can see two things at once: how much the seam is doing
(pre-seam violations it fixes) and what it CANNOT fix (content the author has to
get right — a joke emoji, helpdesk filler, a piled-on exclamation).
"""
from __future__ import annotations

from core.recovery import RECOVERY_BUBBLES


def _real_deterministic() -> list[tuple[str, str]]:
    """The bubbles the product ships verbatim, pulled from their real source so
    this corpus is a mirror, not a transcription that rots."""
    out: list[tuple[str, str]] = []
    for kind, pool in RECOVERY_BUBBLES.items():
        for bubble in pool:
            out.append((f"recovery:{kind}", bubble))
    # Proactive: the legacy-user city asks and morning greetings, verbatim from
    # scheduler/proactive_scheduler (kept in sync by test_voice_corpus_is_current).
    out += [
        ("proactive:city_ask", "Quick one, what city are you in?|||Just so my check-ins land during your day and not at 3am 😅"),
        ("proactive:city_ask", "Hey, what city you based in these days?|||Want to make sure I'm hitting you up at sane hours, not the middle of the night."),
        ("proactive:city_ask", "Random q, where are you based?|||Lets me time my check-ins to your day instead of blowing up your phone at 2am."),
        ("proactive:morning", "Good morning Sam ☀️|||What's your weight this morning?"),
        ("proactive:morning", "Morning Sam 💪|||What's the scale showing today?"),
        ("proactive:morning", "morning Sam.|||what've you had so far? let's get the day on the board."),
    ]
    # Onboarding: the hand-coded intro bubbles, verbatim from handlers/onboarding.
    out += [
        ("onboarding:intro", "good to meet you, Sam ☺️|||fastest way to get me up to speed: fire off a voice note or a messy paragraph.|||weight, training, how you eat, injuries, what you're chasing, any deadline, whatever's relevant. i'll pull out what matters."),
        ("onboarding:set", "alright, you're set ✅|||send me what you've eaten today, rough is totally fine. let's get the first one down."),
    ]
    return out


#: Representative LLM-shaped turns, written in Arnie's shipped voice. These are
#: the shapes the model produces after being told the voice — the corpus a
#: renderer regression would show up in. Deliberately include a few that a
#: careless author might get wrong (a joke emoji, a "let me know if", a "Logged."
#: one-word bubble) so the linter's content rules are exercised, not just passed.
_CURATED: list[tuple[str, str]] = [
    # ── single-item log confirmations ────────────────────────────────────────
    ("log:single", "Chicken and rice, 620 cal and 52g protein on the board.|||You're at 1,240 for the day, protein's tracking well."),
    ("log:single", "Got the Greek yogurt down, 150 cal, 15g protein.|||Solid protein-forward snack, right where you want it."),
    ("log:single", "Banana logged, 105 cal.|||Nice quick one before the session."),
    ("log:single", "Two eggs and toast, 280 cal, 18g protein.|||Good start, keep the protein coming through lunch."),
    # ── multi-item meals ─────────────────────────────────────────────────────
    ("log:multi", "Logged the whole plate: salmon, quinoa, and roasted veg.|||That's 640 cal and 44g protein, strong dinner."),
    ("log:multi", "Burrito bowl with double chicken, chips, and a side of guac, all in.|||1,020 cal, but 58g protein carrying it, worth it."),
    # ── day recap ────────────────────────────────────────────────────────────
    ("recap:day", "📋 Sunday, June 14|||Oatmeal and berries, 320 cal|||Chicken wrap, 540 cal|||Salmon and rice, 610 cal|||Total: 1,470 cal, 118g protein"),
    ("recap:day", "You landed at 1,820 cal and 140g protein today.|||That's a clean day, protein goal hit with room to spare."),
    # ── macro / target status ────────────────────────────────────────────────
    ("status:macros", "You've got 460 cal left and 38g of protein to go.|||A chicken breast and some rice closes both out."),
    ("status:macros", "Protein's done for the day at 165g.|||Calories have a little headroom if you want a snack."),
    # ── forward-move nudge ───────────────────────────────────────────────────
    ("nudge", "You're 30g of protein short with dinner left.|||Lean into a protein-heavy plate and you're set."),
    ("nudge", "Two days without a workout logged.|||What does today look like, even 20 minutes counts."),
    # ── milestones: PR, streak, goal ─────────────────────────────────────────
    ("milestone:pr", "That's a bench PR, 5 pounds over your last best.|||Strength is trending up, the volume's paying off."),
    ("milestone:streak", "Seven days logged in a row.|||This is the consistency that moves the scale, keep it rolling."),
    ("milestone:goal", "You hit your goal weight this morning.|||Real work got you here, let's talk about holding it."),
    # ── weight / workout logs ────────────────────────────────────────────────
    ("log:weight", "Got it, 182 this morning.|||Down 1.2 from last week, steady and sustainable."),
    ("log:workout", "Logged the push session: bench, overhead press, and dips.|||Good volume, that's the pattern that builds."),
    # ── question back ────────────────────────────────────────────────────────
    ("ask", "What did lunch look like today?|||Even a rough estimate keeps the day honest."),
    ("ask", "How'd the squats feel at that weight?|||Trying to figure out if we push it next week."),
    # ── correction / edit acknowledgement ────────────────────────────────────
    ("ack:edit", "Fixed it, that's 3 eggs not 2 now.|||Puts you at 1,310 for the day."),
    ("ack:edit", "Swapped it to whole milk, updated the macros.|||Small change, you're still on track."),
    # ── deliberate content violations (must be CAUGHT by the linter) ─────────
    ("bad:joke_emoji", "Bold choice on the donut 😅|||We'll balance it at dinner."),
    ("bad:helpdesk", "Your macros are updated.|||Let me know if you need anything else."),
    ("bad:robotic", "Logged."),
    ("bad:exclamation", "Huge day!!|||Protein smashed!!"),
]


def corpus() -> list[tuple[str, str]]:
    """The full corpus: real deterministic bubbles + curated representative
    turns. `(shape, text)` with text the raw pre-seam ||| string."""
    return _real_deterministic() + _CURATED


#: Shapes whose examples are intentional violations, excluded from the "shipped
#: voice is clean" gate — they exist to prove the linter bites.
NEGATIVE_SHAPES = frozenset({"bad:joke_emoji", "bad:helpdesk", "bad:robotic",
                             "bad:exclamation"})
