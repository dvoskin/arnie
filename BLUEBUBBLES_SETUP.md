# Arnie on iMessage — BlueBubbles Setup Guide

This guide gets Arnie receiving and replying to iMessages on your Mac using
[BlueBubbles Server](https://bluebubbles.app/) + a free Cloudflare Tunnel.

Total setup time: ~30 minutes.

---

## What you need

| Item | Notes |
|------|-------|
| Mac (macOS 12+) | Must stay **on and awake** — this is the iMessage relay |
| Signed into iMessage | With the Apple ID you want Arnie to use |
| Render account | Where Arnie is deployed |
| Cloudflare account | Free tier is enough |

---

## Step 1 — Install BlueBubbles Server on your Mac

1. Download **BlueBubbles Server** from [bluebubbles.app/downloads](https://bluebubbles.app/downloads/).
2. Open the `.dmg`, drag to Applications, and launch it.
3. Grant **Full Disk Access** when prompted (required for iMessage database access):
   - System Preferences → Privacy & Security → Full Disk Access → add BlueBubbles Server
4. BlueBubbles will ask for a **server password** — choose something strong and save it.
   This becomes `BLUEBUBBLES_PASSWORD` on Render.

---

## Step 2 — Create a Cloudflare Tunnel (free public URL for your Mac)

> This exposes your Mac's BlueBubbles port (1234) to the internet so Render can
> deliver webhook events to it.

### Install cloudflared

```bash
brew install cloudflare/cloudflare/cloudflared
```

### Authenticate once

```bash
cloudflared tunnel login
```

A browser window opens — log in to your Cloudflare account.

### Create a named tunnel

```bash
cloudflared tunnel create arnie-bb
```

Copy the **Tunnel ID** shown (you'll need it in a moment).

### Create a config file

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <YOUR_TUNNEL_ID>
credentials-file: /Users/<your-username>/.cloudflared/<YOUR_TUNNEL_ID>.json

ingress:
  - hostname: arnie-bb.yourdomain.com   # or use a free *.trycloudflare.com URL below
    service: http://localhost:1234
  - service: http_status:404
```

**If you don't own a domain**, use a temporary free URL instead:

```bash
cloudflared tunnel --url http://localhost:1234
```

This prints something like `https://random-word-word.trycloudflare.com` — use that
as your `BLUEBUBBLES_URL` (free, no Cloudflare account needed, but URL changes on restart).

### Start the tunnel (permanent — run on login)

```bash
cloudflared tunnel run arnie-bb
```

To auto-start on login:

```bash
brew services start cloudflare/cloudflare/cloudflared
```

Your Mac's BlueBubbles Server is now reachable at:
`https://arnie-bb.yourdomain.com` (or your trycloudflare.com URL).

---

## Step 3 — Configure BlueBubbles Server

1. Open BlueBubbles Server → **Settings** tab.
2. Under **Server**, verify the port is **1234**.
3. Under **Webhooks**, add a new webhook:
   - **URL**: `https://arnie.onrender.com/imessage`
   - **Events**: check `New Message`
4. Save.

> Arnie's Render URL is `https://arnie.onrender.com` by default — replace
> `arnie.onrender.com` with whatever your Render service URL actually is.

---

## Step 4 — Set env vars on Render

Go to your **Render dashboard → arnie-bot → Environment** and add:

| Key | Value |
|-----|-------|
| `BLUEBUBBLES_URL` | Your Cloudflare Tunnel URL, e.g. `https://arnie-bb.yourdomain.com` |
| `BLUEBUBBLES_PASSWORD` | The password you set in BlueBubbles Server |
| `BLUEBUBBLES_WEBHOOK_SECRET` | A random secret string (see below) |

### Generating a webhook secret

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output into both:
- Render env var `BLUEBUBBLES_WEBHOOK_SECRET`
- BlueBubbles Server → Settings → Webhook secret (if it supports it)

> If BlueBubbles Server doesn't have a webhook secret field, leave
> `BLUEBUBBLES_WEBHOOK_SECRET` blank — Arnie will skip signature verification.

After adding the vars, click **Save Changes**. Render will redeploy automatically.

---

## Step 5 — Test the integration

### Send a test message

From any iPhone, text the Apple ID / phone number your Mac is signed into with:

```
hi
```

You should get Arnie's onboarding message back within a few seconds.

### Check Render logs

In your Render dashboard → **arnie-bot → Logs**, you should see:

```
INFO:bot.imessage_handler:iMessage pipeline: +15551234567 → "hi"
```

If you see `BlueBubbles not configured`, the env vars haven't propagated yet — wait
1–2 minutes and try again.

---

## Step 6 — Keep your Mac alive

BlueBubbles only works when your Mac is on and iMessage is logged in.

Recommended settings:
- **System Preferences → Battery → Power Adapter** → set "Prevent automatic sleeping" to ON
- **Screen Saver** → never (or set a long delay)
- BlueBubbles Server will prompt you to enable "Launch at Login" — say yes

---

## Architecture summary

```
iPhone user
    │ iMessage
    ▼
Apple Servers
    │ iMessage (E2E encrypted)
    ▼
Your Mac (BlueBubbles Server, port 1234)
    │ HTTP POST /imessage (webhook)
    ▼
Cloudflare Tunnel
    │ HTTPS
    ▼
Render (Arnie) ← runs_imessage_pipeline() → Claude API
    │ HTTP POST /api/v1/message/text
    ▼
Cloudflare Tunnel
    │
Your Mac (BlueBubbles) → Apple → iPhone user receives reply
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No reply received | Check Render logs for errors. Confirm `BLUEBUBBLES_URL` is reachable: `curl https://your-url/api/v1/ping?password=yourpassword` |
| "BlueBubbles not configured" in logs | Env vars not set or Render hasn't redeployed yet |
| 403 on `/imessage` | Webhook secret mismatch — set both Render var and BlueBubbles Server to the same value, or clear both to disable signature checking |
| Cloudflare tunnel drops | Use `brew services restart cloudflare/cloudflare/cloudflared`; for reliability, buy a cheap domain and set up a DNS-managed tunnel |
| iMessage not delivering | Your Mac must be signed into iMessage with the same Apple ID that owns the phone number/email you're texting |
| "isFromMe" loop | Already handled — Arnie ignores its own outbound messages |

---

## What users experience

Users text the number/email your Mac is signed into with, exactly like texting anyone.
Arnie responds in plain text — all the same coaching, food logging, workout tracking,
and proactive check-ins work identically to Telegram. No app to download.

iMessage users are stored in the database with `telegram_id = "im:+15551234567"` so
their data is completely separate from Telegram users but uses the same DB schema.
