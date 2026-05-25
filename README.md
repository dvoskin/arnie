# Arnie v0.1

A messaging-native AI fitness, nutrition, and performance coach.  
Persistent memory. Natural language logging. Adaptive coaching.

---

## Quick Start

### 1. Clone and install dependencies

```bash
cd arnie
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=...    # from @BotFather on Telegram
ANTHROPIC_API_KEY=...     # for Claude (LLM + vision)
OPENAI_API_KEY=...        # for Whisper voice transcription (optional)
```

### 3. Run Arnie

```bash
python main.py
```

Arnie uses **polling mode** by default — no public URL or webhook setup needed for local development.

---

## Architecture

```
arnie/
├── main.py                      Entry point
├── bot/
│   └── telegram_handler.py      All Telegram message routing
├── core/
│   ├── llm.py                   Anthropic / OpenAI wrapper with tool use
│   └── context_builder.py       Assembles system context per request
├── db/
│   ├── database.py              SQLAlchemy async engine
│   ├── models.py                All DB models (users, logs, food, exercise…)
│   └── queries.py               Helper query functions
├── handlers/
│   ├── onboarding.py            Onboarding system prompt + completion check
│   ├── tool_executor.py         Execute LLM tool calls → DB writes
│   ├── daily_closeout.py        End-of-day summary generation
│   └── pacing.py                Deterministic pacing calculations
├── memory/
│   ├── memory_manager.py        Read/write per-user markdown memory files
│   └── reflection.py            Decide what to persist (runs ~10% of turns)
├── multimodal/
│   ├── voice_handler.py         Voice note transcription (Whisper)
│   └── image_handler.py        Image analysis (Claude vision)
├── scheduler/
│   └── proactive_scheduler.py  Hourly reminder check (opt-in)
├── skills/                      Markdown skill files (coaching logic docs)
└── users/                       Per-user memory files (git-ignored)
```

---

## What Arnie Can Do

### Log naturally
```
"Had chicken and rice for lunch"
"Bench press 225 for 3 sets of 5"
"Weight 191.4 this morning"
"30 min incline walk"
"1 litre of water"
```

### Voice and photos
Send a voice note — Arnie transcribes it.  
Send a food photo or nutrition label — Arnie reads it.  
Send a scale photo — Arnie logs the weight.

### Commands
```
/log        See today's full log
/summary    Quick macro summary with remaining targets
/closeday   Close the day and get a coaching analysis
/help       Command reference
```

### Adaptive memory
Arnie remembers your patterns, preferences, and recurring struggles across sessions.  
Memory is stored in `users/{telegram_id}/arnie_memory.md`.

### Proactive reminders (opt-in)
Enable by telling Arnie: "Turn on proactive reminders."  
Arnie will send protein pacing nudges, workout reminders, and closeout prompts
based on your timezone and wake/sleep schedule.

---

## Database

SQLite (`arnie.db`) with these tables:

| Table | Purpose |
|---|---|
| `users` | Profile, goals, onboarding status |
| `user_preferences` | Coaching style, targets, reminder settings |
| `daily_logs` | Daily macro/workout totals |
| `food_entries` | Individual food logs with macros |
| `exercise_entries` | Individual exercise logs |
| `body_metrics` | Weight / body composition history |
| `conversation_logs` | Full message history (for context window) |
| `memory_updates` | Audit trail of memory changes |
| `skills` | Skill registry (optional) |

The schema supports historical retrieval, trend analysis, and future dashboards.

---

## Configuration

All configuration via `.env`. Key variables:

| Variable | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | required | From @BotFather |
| `ANTHROPIC_API_KEY` | required | Main LLM + image vision |
| `OPENAI_API_KEY` | optional | Required for voice transcription |
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `DEFAULT_MODEL` | `claude-sonnet-4-6` | Any Claude model |
| `DATABASE_URL` | `sqlite+aiosqlite:///arnie.db` | SQLite by default |

---

## Onboarding

First-time users are walked through setup conversationally.  
Arnie collects: name, age, sex, height, weight, goals, training experience,
dietary preferences, injuries, coaching preferences, and timezone.

No forms — just natural chat. Data is saved incrementally via `update_profile` tool calls.

---

## Skills System

Skill files in `skills/` document coaching logic in plain markdown.  
Each skill defines: purpose, trigger conditions, logic, response format, and examples.

Current skills:
- `daily_closeout.md` — end-of-day summaries
- `aggressive_cut_day.md` — deficit day management  
- `travel_damage_control.md` — staying on track while travelling
- `weigh_in_analysis.md` — weight trend interpretation
- `workout_builder.md` — workout generation
- `grocery_recommendation.md` — shopping list generation

Skills can be referenced in system prompts or evolved into active tool functions later.

---

## MVP Limitations (v0.1)

- No web dashboard
- No Redis / vector DB (SQL only)
- No multi-user auth (Telegram ID is the identity)
- Proactive reminders fire hourly — accuracy ±1 hour
- Image MIME type is assumed JPEG (Telegram always converts to JPEG)

---

## Next Steps

- [ ] Web dashboard (FastAPI + simple HTML)
- [ ] Calorie/macro database integration (USDA / Open Food Facts)
- [ ] Streak tracking
- [ ] Weekly progress reports
- [ ] Training programme management
- [ ] WhatsApp / Discord adapters
- [ ] Vector search for memory (when memory files grow large)
