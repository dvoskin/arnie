# Handoff — 2026-07-31 (B7 admin/security pass)

Continues `docs/SESSION_HANDOFF_0731.md`. That handoff's "Next, in order" put
**B7 security** first as the largest closable item. This pass closed the admin
surface and both spoofable webhooks. Read this, then the updated
`docs/MARKET_READINESS_SCORECARD.md` §10.

Everything below was verified by a test or a live probe, not remembered.

## Where the work is

Branch `dvoskin/b7-admin-security` @ `5d75ce6`, cut from `origin/main` @
`50ba640`. **Committed locally, not pushed, not deployed.** `/health` still
reads `26e36539c86e` — this is stacked behind the same 13+ undeployed commits B1
is about. Full shuffled suite green at this SHA (6407 tests, exit 0, seed 4242).

```bash
python scripts/endpoint_inventory.py          # the new evidence — 131 routes classified
pytest tests/test_admin_auth.py tests/test_webhook_signatures.py \
       tests/test_ratelimit.py tests/test_endpoint_inventory.py -q
```

## What B7 asked, and what each answer is

The four questions from the parent handoff: admin/debug inventory, credentials
out of query strings, rate limits, webhook signatures.

**1. Inventory — `scripts/endpoint_inventory.py`.** Walks the LIVE route table
(after every router is mounted), not a grep, and classifies each route by auth
mechanism, whether a credential rides in the URL, and whether it is rate
limited. `--json` for machine output, `--strict` to exit 1 on a finding.
`tests/test_endpoint_inventory.py` freezes the result so a regression fails CI.
Baseline before this pass: **66 findings**. After: **37**, and the 37 are two
known things (below).

**2. Admin credentials out of the URL — DONE.** All 12 `/admin*` endpoints took
`ADMIN_TOKEN` as `?token=`, and the dashboard HTML embedded it in every link and
a 303 redirect — so the token was in browser history, copied links, and every
proxy access-log line. Now one `require_admin` dependency reads, in order: the
`X-Admin-Token` header, a SESSION_SECRET-signed HttpOnly cookie, or — as a
deprecated, logged fallback — `?token=`. `GET /admin` trades a `?token=`
bootstrap for the cookie and 303-redirects to a clean `/admin`; every in-page
link is now tokenless. Proven end to end in `test_admin_auth.py` (the rendered
dashboard HTML contains no `token=`).

**3. Rate limits — DONE.** New `core/ratelimit.py`: one in-process limiter plus
honest client-IP resolution. The admin gate (60/min/IP) now fronts the token
check, so a brute-forcer trips 429 whether or not a guess is right. The session
mint (30/min) and pairing-code exchange (20/min) were **unbounded** and now
aren't. The two pre-existing hand-rolled per-IP dicts (`/imessage/start`,
`/api/preregister`) were folded into the shared limiter.

> **The proxy bug this fixes:** uvicorn runs with no `--proxy-headers`, so
> `request.client.host` is Render's proxy — every caller shared ONE bucket. The
> limiter reads `X-Forwarded-For` only when `TRUST_PROXY_HEADERS=true`. **Danny
> must set that env var** or per-IP limiting is really per-deployment.

**4. Webhook signatures.**
- **Telegram — DONE.** Was `token != getenv(...)`, a non-constant-time compare
  of a secret. Now `hmac.compare_digest`, plus an enforced
  `X-Telegram-Bot-Api-Secret-Token` when `TELEGRAM_WEBHOOK_SECRET` is set
  (`main.py` registers it at `set_webhook`).
- **iMessage/BlueBubbles — FIXED, but gated on a Danny action (read this).**
  `verify_bb_signature` **failed open** when `BLUEBUBBLES_WEBHOOK_SECRET` was
  unset. **A live probe on 2026-07-31 confirmed production accepts unsigned
  POSTs to `/imessage`** — i.e. anyone can inject an inbound iMessage and make
  Arnie process a turn as any phone number. It now **fails closed** (mirrors the
  Stripe webhook one function over). Secret is read at call time, so setting it
  takes effect with no redeploy.

## ⚠ The one thing that can break prod on deploy

The iMessage fix means: **if `dvoskin/b7-admin-security` deploys while
`BLUEBUBBLES_WEBHOOK_SECRET` is unset, all inbound iMessage 403s.** Before
deploying this branch, do ONE of:

1. **Preferred:** set `BLUEBUBBLES_WEBHOOK_SECRET` on Render **and** the same
   value in the BlueBubbles server's webhook config. Then it enforces — hole
   closed.
2. **Bridge:** set `IMESSAGE_WEBHOOK_ALLOW_UNSIGNED=true` to keep today's
   open behaviour while you configure BlueBubbles. (Deliberately not in
   `render.yaml` — it is a temporary, visible opt-out of the security fix.)

## Danny's env checklist (the dashboard is authoritative, not render.yaml)

The `NUTRITION_RESOLVER_MODE` incident proved render.yaml is reference-only for
this service. These are declared there now, but **must be set in the Render
dashboard**:

| var | why | if wrong |
|---|---|---|
| `BLUEBUBBLES_WEBHOOK_SECRET` | arms the iMessage signature check | unset + deploy → iMessage inbound 403s |
| `TRUST_PROXY_HEADERS=true` | rate limits key on the real client, not the proxy | unset → one shared bucket for everyone |
| `SESSION_SECRET` | signs session tokens AND the admin cookie | unset → **public** dev secret, every token forgeable |
| `DEV_AUTH_ENABLED=false` | disables device-provider sign-in | true → `provider=device` mints a session for ANY identity, no credential |

`SESSION_SECRET` is almost certainly already set (a script held the prod value —
see the parent handoff), but it was never *declared*, so it was one dashboard
edit from silently reverting to the public fallback. Confirm it.

## What's still open (scope, not this pass)

**36 capability tokens still ride in the URL.** Two shapes:
`/api/food/log?token=…` (the iOS logging API authenticates with the per-user
webhook token as a query param) and `/dashboard/{token}` (capability URLs).
Path/query tokens land in access logs and `Referer`. Moving them to a header is
a coordinated iOS+server change — the `/api/v1/*` surface (70 routes, Bearer
session) already shows the target shape. Counted and frozen at 36 by
`test_endpoint_inventory.py`; that number moving is the signal to revisit.

## Next, in order (unchanged from the parent, minus B7)

1. **B6 voice** — `CoachMessagePlan` + one renderer + a 150-turn corpus.
2. **B2** — 57 of 60 user-visible mutations off the contract;
   `mutation_inventory.py` ranks them.
3. **B9/B10** — backup restore + rollback rehearsal (ops, needs Danny).
4. **B1** — still the highest-value single action: deploy. Now 14+ commits.

## Files touched

New: `core/ratelimit.py`, `scripts/endpoint_inventory.py`,
`tests/test_endpoint_inventory.py`, `tests/test_ratelimit.py`,
`tests/test_webhook_signatures.py`, `audits/endpoint_inventory.json`.
Changed: `api/app.py` (admin dependency + telegram webhook + limiter refactor),
`api/auth.py` (admin cookie sign/verify), `api/auth_routes.py` (mint + pairing
limits), `bot/imessage_handler.py` (fail closed), `main.py` (secret_token),
`render.yaml` (4 security keys), `tests/test_admin_auth.py` (rewritten
behavioural), `docs/MARKET_READINESS_SCORECARD.md` (§10 + B7 row).
