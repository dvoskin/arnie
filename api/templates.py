"""
HTML template builders for Arnie web pages (extracted from api/app.py).

Pure string functions — no DB, no app.state, no FastAPI deps. Each is called
from exactly one route in api/app.py. Split out so app.py holds API/route logic
and these ~1.6k lines of HTML live on their own (AUDIT #9).
"""
import html
from typing import Optional  # noqa: F401 — kept for parity if signatures evolve


def _dashboard_title(name: str) -> str:
    """Personalized browser-tab title, e.g. 'ArnieOS ⏐ Danny's Dashboard'.
    Falls back to 'Your Dashboard' when no name. Name is HTML-escaped (user-provided)."""
    n = (name or "").strip()
    owner = f"{html.escape(n)}'s" if n else "Your"
    return f"ArnieOS ⏐ {owner} Dashboard"


def _dashboard_html(token: str, name: str = "", bot_username: str = "Arnie_1026_Bot",
                    brain_enabled: bool = False) -> str:
    # Brain tab gating — defaults to OFF so the production environment
    # never renders the half-built /brain/{token} iframe. The CSS rule
    # uses !important so it wins regardless of cascade position, even
    # against a .brain-active body class for full-bleed override. The
    # JS const is read by loadBrainTab below to short-circuit the iframe
    # src write. Flip BRAIN_TAB_ENABLED=true in Render env when the route
    # + page are ready to ship.
    _brain_off_css = (
        "" if brain_enabled
        else "#nav-brain,#bn-brain,#panel-brain{display:none!important}"
    )
    _brain_enabled_js = "true" if brain_enabled else "false"
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>{_dashboard_title(name)}</title>
<!-- favicon served by the dashboard app itself (relative → follows whatever host
     serves the dashboard, incl. app.tryarnie.com). -->
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/favicon.png">
<!-- Social preview: a generic text title only — NO image, NO per-user name. The explicit
     og:title also stops crawlers from falling back to the personalized <title>. -->
<meta property="og:type"   content="website">
<meta property="og:title"  content="Dashboard ⏐ ArnieOS">
<meta name="twitter:card"  content="summary">
<meta name="twitter:title" content="Dashboard ⏐ ArnieOS">
<script>
(function(){{
  var t=localStorage.getItem('arnie-theme')||
    (window.matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');
  document.documentElement.setAttribute('data-theme',t);
}})();
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}

/* ── THEMES ─────────────────────────────────────────────── */
[data-theme="dark"]{{
  --bg:#0c1018;
  --sf:rgba(255,255,255,.05); --sf2:rgba(255,255,255,.09); --sf3:rgba(255,255,255,.14);
  --bd:rgba(255,255,255,.10); --bd2:rgba(255,255,255,.20);
  --ac:#00e676; --ac-rgb:0,230,118; --ac-dim:rgba(0,230,118,.13);
  --bl:#3b82f6; --or:#f97316; --pu:#a855f7; --re:#ef4444; --ye:#eab308;
  --tx:#eef2ff; --tx2:#c8d0e8; --mu:#6b7a99; --di:#3d4a66;
  --sh:none; --hbg:rgba(12,16,24,.92);
  --cgrid:rgba(255,255,255,.05); --ctick:#4a5568; --inp:rgba(255,255,255,.06);
}}
[data-theme="light"]{{
  --bg:#f5f7fa;
  --sf:rgba(255,255,255,.88); --sf2:#eef2f7; --sf3:#e4eaf3;
  --bd:#dde4ef; --bd2:#c4cfdf;
  --ac:#059669; --ac-rgb:5,150,105; --ac-dim:rgba(5,150,105,.10);
  --bl:#2563eb; --or:#ea580c; --pu:#9333ea; --re:#dc2626; --ye:#d97706;
  --tx:#0f172a; --tx2:#334155; --mu:#64748b; --di:#94a3b8;
  --sh:0 1px 3px rgba(0,0,0,.06),0 4px 18px rgba(0,0,0,.05);
  --hbg:rgba(245,247,250,.94);
  --cgrid:#e2e8f0; --ctick:#94a3b8; --inp:#f8fafc;
}}

/* ── BASE ────────────────────────────────────────────────── */
/* Brain-tab feature gate — empty string when enabled, hard-hides
   sidebar nav button, bottom-nav button, and tab panel when off. */
{_brain_off_css}
/* Brain-icon "still learning" flair — tiny pulsing amber dot stuck to the
   top-right of the brain glyph in both sidebar (#nav-brain) and bottom-nav
   (#bn-brain). Hidden by default; renderLearningProgress() flips
   `body.brain-pending` on/off so the dot only shows while the gate is
   locked. Tap still routes to the gate page so users can read what's
   missing — this is just signal, not a barrier. */
#nav-brain .ni-ico,#bn-brain .bn-ico{{position:relative}}
.brain-pending-dot{{
  position:absolute;top:-1px;right:-3px;width:6px;height:6px;border-radius:50%;
  background:#f59e0b;box-shadow:0 0 0 2px var(--bg),0 0 6px rgba(245,158,11,.65);
  display:none;pointer-events:none;
  animation:brainPendingPulse 2.4s ease-in-out infinite;
}}
body.brain-pending .brain-pending-dot{{display:block}}
@keyframes brainPendingPulse{{
  0%,100%{{opacity:.95;transform:scale(1)}}
  50%   {{opacity:.55;transform:scale(.85)}}
}}
html{{background:var(--bg);transition:background .35s,color .3s}}
body{{
  font-family:'Geist',ui-sans-serif,system-ui,-apple-system,sans-serif;
  background:var(--bg);color:var(--tx);min-height:100vh;
  -webkit-font-smoothing:antialiased;overflow-x:hidden;position:relative;
  padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom);
  transition:background .35s,color .3s;letter-spacing:-.005em;
}}
[data-theme="dark"] body::before{{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 70% 55% at 10% 12%,rgba(0,230,118,.10),transparent),
    radial-gradient(ellipse 65% 50% at 90% 78%,rgba(59,130,246,.08),transparent),
    radial-gradient(ellipse 80% 60% at 50% 52%,rgba(90,55,190,.06),transparent);
  animation:mesh 18s ease-in-out infinite alternate;
}}
[data-theme="light"] body::before{{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 70% 55% at 10% 12%,rgba(5,150,105,.04),transparent),
    radial-gradient(ellipse 65% 50% at 90% 78%,rgba(37,99,235,.03),transparent);
}}
@keyframes mesh{{0%{{opacity:.7;transform:scale(1)}}100%{{opacity:1;transform:scale(1.06)}}}}

/* ── SHELL / SIDEBAR ─────────────────────────────────────── */
.shell{{display:grid;grid-template-columns:252px minmax(0,1fr);min-height:100dvh;position:relative;z-index:1}}
.sidebar{{
  position:sticky;top:0;height:100dvh;display:flex;flex-direction:column;
  padding:24px 14px 20px;border-right:1px solid var(--bd);
  background:var(--hbg);backdrop-filter:blur(24px) saturate(140%);
  -webkit-backdrop-filter:blur(24px) saturate(140%);overflow-y:auto;z-index:10;
  transition:background .35s;
}}
[data-theme="light"] .sidebar{{
  background:rgba(255,255,255,.96);
  border-right:1px solid var(--bd);
  box-shadow:2px 0 20px rgba(0,0,0,.06);
}}
.sb-logo{{
  font-family:'Instrument Serif','Times New Roman',serif;
  font-size:21px;letter-spacing:-.01em;color:var(--tx);
  display:inline-flex;align-items:center;gap:9px;padding:2px 10px 0;
}}
.logo-os{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--mu);border:1px solid var(--bd);border-radius:5px;padding:2px 6px;
}}
.sidenav{{display:flex;flex-direction:column;gap:2px;margin-top:28px}}
.nav-section-lbl{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--mu);padding:0 12px;margin:2px 0 8px;font-weight:500;
}}
.navitem{{
  display:flex;align-items:center;gap:13px;padding:11px 12px;
  border-radius:12px;border:1px solid transparent;
  color:var(--tx2);font-size:14px;font-weight:500;cursor:pointer;
  transition:all .18s cubic-bezier(.2,.7,.2,1);
  width:100%;text-align:left;background:transparent;font-family:inherit;position:relative;
}}
.navitem:hover:not(.active){{color:var(--tx);background:var(--sf2)}}
.navitem.active{{
  color:var(--tx);background:linear-gradient(180deg,var(--sf3),var(--sf2));
  border-color:var(--bd);
}}
[data-theme="dark"] .navitem.active{{
  box-shadow:0 1px 0 rgba(255,255,255,.05) inset;
}}
[data-theme="light"] .navitem.active{{
  background:linear-gradient(180deg,#fff,#f8fafc);
  box-shadow:0 1px 3px rgba(0,0,0,.08);
}}
.navitem.active::before{{
  content:'';position:absolute;left:-14px;top:50%;transform:translateY(-50%);
  width:3px;height:22px;border-radius:3px;
  background:var(--ac);
}}
[data-theme="dark"] .navitem.active::before{{box-shadow:0 0 10px var(--ac);}}
.ni-ico{{width:20px;height:20px;display:grid;place-items:center;flex-shrink:0;color:var(--tx2);opacity:.65;transition:color .18s,opacity .18s}}
.navitem.active .ni-ico,.navitem:hover .ni-ico{{color:var(--ac);opacity:1}}
.ni-lbl{{flex:1}}
.ni-meta{{font-family:'Geist Mono','SF Mono',monospace;font-size:9.5px;color:var(--mu);letter-spacing:.04em}}
.navitem.active .ni-meta{{color:var(--tx2)}}
.sb-foot{{margin-top:auto;display:flex;flex-direction:column;gap:8px;padding-top:12px;border-top:1px solid var(--bd)}}
.sb-user{{
  display:flex;align-items:center;gap:11px;padding:11px 12px;
  border-radius:12px;border:1px solid var(--bd);background:var(--sf);
}}
.sb-avatar{{
  width:36px;height:36px;border-radius:50%;flex-shrink:0;
  background:radial-gradient(circle at 35% 30%,#86efac,#6366f1 72%);
  border:1px solid rgba(255,255,255,.18);position:relative;
}}
.sb-avatar::after{{
  content:'';position:absolute;right:-1px;bottom:-1px;
  width:10px;height:10px;border-radius:50%;
  background:var(--ac);border:2px solid var(--bg);
}}
.sb-name{{font-size:13px;font-weight:500;color:var(--tx)}}
.sb-user:hover{{border-color:var(--bd2);background:var(--sf2);}}
.sb-goal{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;letter-spacing:.06em;text-transform:uppercase;color:var(--ac);margin-top:2px;
}}

/* ── MAIN ────────────────────────────────────────────────── */
.main{{min-width:0;overflow-x:clip}}
.main-inner{{padding:0 48px 100px;width:100%;max-width:900px;margin:0 auto}}

/* ── BRAIN TAB — full-bleed override ──────────────────────────
   When the Brain tab is active, the dashboard's max-width column
   gets in the way of the cinematic constellation. We bust the
   iframe out to fill the entire right side of the shell (i.e.
   everything that isn't the sidebar). The pagehead stays so the
   "Arnie's brain | LIVE" title is still readable. */
body.brain-active .pagehead{{display:none}}
body.brain-active #app-load{{display:none}}
body.brain-active footer{{display:none}}
#panel-brain.active{{
  position:fixed;
  top:0;
  left:252px;            /* sidebar width — keep nav visible */
  right:0;
  bottom:0;
  padding:0;
  margin:0;
  z-index:5;
  background:transparent;
}}
#panel-brain #brain-frame-wrap{{
  position:absolute;
  inset:0;
  margin:0;
  border-radius:0;
}}
@media(max-width:760px){{
  /* Mobile: sidebar is hidden, brain fills the entire viewport above
     the bottom nav (.bottomnav lives at the page root). */
  #panel-brain.active{{left:0;bottom:64px}}
}}

/* ── STREAK CHIP — top-right of pagehead ────────────────────────────
   Compact "🔥 X D" indicator showing the user's current consecutive-
   logging streak. Hidden by JS until streak_days ≥ 3 so new users never
   see "1 d" / "2 d" (premature gamification). Uses the same accent
   tokens as .ds-pill.on / .ph-pill so done-state coloring is unified. */
.streak-chip{{
  display:inline-flex;align-items:center;gap:5px;
  padding:6px 10px;border-radius:10px;
  background:var(--ac-dim);border:1px solid rgba(var(--ac-rgb),.28);
  color:var(--ac);
  font-family:'Geist',ui-sans-serif,system-ui,sans-serif;
  font-size:13px;font-weight:600;letter-spacing:-.01em;line-height:1;
  cursor:pointer;transition:all .15s;
  font-variant-numeric:tabular-nums;user-select:none;
  flex-shrink:0;
}}
.streak-chip:hover{{
  background:rgba(var(--ac-rgb),.18);
  border-color:rgba(var(--ac-rgb),.42);
}}
.streak-chip:active{{transform:scale(.96)}}
.streak-ico{{width:12px;height:12px;display:block;flex-shrink:0}}
.streak-unit{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;
  opacity:.75;margin-left:1px;
}}

.hbtn{{
  background:var(--sf2);border:1px solid var(--bd);color:var(--mu);
  width:34px;height:34px;border-radius:10px;cursor:pointer;font-size:14px;
  display:flex;align-items:center;justify-content:center;font-family:inherit;
  transition:all .2s;flex-shrink:0;
}}
.hbtn:hover{{border-color:var(--ac);color:var(--ac)}}
.hbtn:active{{transform:scale(.91)}}
.hbtn.spinning{{color:var(--ac);border-color:var(--ac);animation:hbtn-spin .7s linear infinite}}
@keyframes hbtn-spin{{to{{transform:rotate(360deg)}}}}
#app-load{{text-align:center;padding:80px 20px;color:var(--mu);font-size:14px}}
.tab-panel{{display:none;animation:fadeUp .28s ease}}
.tab-panel.active{{display:block}}

/* ── DAY LAYOUT ──────────────────────────────────────────── */
.day-col{{display:flex;flex-direction:column}}

/* ── MACRO STRIP ─────────────────────────────────────────── */
.macro-strip{{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:10px;}}

/* ── COMPACT DAY STATUS ROW ──────────────────────────────── */
.day-status{{display:flex;align-items:center;gap:6px;margin:8px 0 14px;flex-wrap:wrap}}
.ds-pill{{
  display:inline-flex;align-items:center;gap:5px;padding:5px 10px;
  border-radius:999px;border:1px solid var(--bd);background:var(--sf);
  font-size:11.5px;font-weight:500;color:var(--mu);
}}
.ds-pill.on{{border-color:rgba(var(--ac-rgb),.35);color:var(--tx);background:var(--ac-dim)}}
.ds-pill .tcb{{
  width:15px;height:15px;border-radius:50%;border:1.5px solid var(--di);
  display:grid;place-items:center;flex-shrink:0;font-size:9px;color:transparent;
  background:var(--sf);transition:all .18s;
}}
.ds-pill.on .tcb{{
  border:none;color:#000;
  background:
    radial-gradient(circle at 38% 28%, rgba(255,255,255,.42) 0%, rgba(255,255,255,0) 55%),
    linear-gradient(145deg, rgba(var(--ac-rgb),1) 0%, rgba(var(--ac-rgb),.68) 100%);
  box-shadow:
    0 1.5px 0 rgba(255,255,255,.5) inset,
    0 4px 10px -2px rgba(var(--ac-rgb),.60),
    0 1px 3px rgba(0,0,0,.18);
}}
.ds-share{{
  margin-left:auto;background:transparent;border:1px solid var(--bd);
  border-radius:8px;color:var(--mu);font-size:14px;padding:4px 8px;
  cursor:pointer;transition:all .15s;
}}
.ds-share:hover{{border-color:var(--ac);color:var(--ac)}}

/* ── WHOOP MODULE ────────────────────────────────────────── */
.whoop-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}}
@media(max-width:700px){{.whoop-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:400px){{.whoop-grid{{grid-template-columns:repeat(2,1fr)}}}}
/* Collapsible health sections (Whoop / Apple Health) — sans, accordion, rows */
.hsec{{border:1px solid var(--bd);border-radius:12px;overflow:hidden;background:var(--sf);margin-bottom:8px}}
.hsec:last-child{{margin-bottom:0}}
.hsec-hd{{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer;user-select:none;transition:background .15s}}
.hsec-hd:hover{{background:var(--sf2)}}
.hsec-name{{font-weight:600;font-size:14px;flex:1}}
.hsec-summary{{font-size:13px;color:var(--mu);font-weight:500}}
.hsec-chev{{font-size:11px;color:var(--mu);transition:transform .2s}}
.hsec.open .hsec-chev{{transform:rotate(90deg)}}
.hsec-body{{display:none;border-top:1px solid var(--bd)}}
.hsec.open .hsec-body{{display:block}}
/* Wearable metric cells — clean multi-up grid. Private .w* namespace so the
   habit-heatmap's .hcell/.hgrid day-square styles can't bleed in (the bug that
   put gray boxes behind every Whoop value). */
.wgrid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px 18px;padding:14px 16px;align-items:start}}
@media(max-width:520px){{.wgrid{{grid-template-columns:repeat(2,1fr);gap:15px 12px;padding:13px 15px}}}}
.wcell{{min-width:0}}
.wcell-lbl{{
  font-family:'Geist Mono','SF Mono',monospace;font-size:8.5px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--mu);font-weight:600;margin-bottom:4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}}
.wcell-val{{font-size:14px;font-weight:600;color:var(--tx);letter-spacing:-.01em;
  font-variant-numeric:tabular-nums;word-break:break-word;line-height:1.25}}
.whoop-stat{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;
  padding:14px 14px 12px;display:flex;flex-direction:column;gap:4px;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.whoop-stat-label{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9.5px;font-weight:500;text-transform:uppercase;letter-spacing:.1em;
  color:var(--mu);
}}
.whoop-stat-val{{
  font-family:'Instrument Serif','Times New Roman',serif;
  font-size:24px;line-height:1;letter-spacing:-.02em;color:var(--tx);
}}
.whoop-stat-sub{{
  font-size:11px;color:var(--mu);margin-top:1px;
  font-family:'Geist Mono','SF Mono',monospace;letter-spacing:.02em;
}}
.whoop-stat.whoop-full{{grid-column:1/-1}}
/* Recovery color coding */
.whoop-rec-high .whoop-stat-val{{color:var(--ac)}}
.whoop-rec-mid  .whoop-stat-val{{color:var(--ye)}}
.whoop-rec-low  .whoop-stat-val{{color:var(--re)}}
.macro-cell{{background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:12px 14px;box-shadow:var(--sh);}}
.mc-label{{font-size:9px;font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:var(--mu);margin-bottom:4px;}}
.mc-num{{font-size:26px;font-weight:700;letter-spacing:-.02em;line-height:1.1;color:var(--tx);}}
.mc-sub{{font-size:10px;color:var(--mu);margin-top:3px;line-height:1.3;}}
.mc-bar{{background:var(--sf3);border-radius:999px;height:4px;margin-top:8px;overflow:hidden;}}
.mc-fill{{height:100%;border-radius:999px;transition:width .8s cubic-bezier(.4,0,.2,1);}}
@media(max-width:560px){{.macro-strip{{grid-template-columns:repeat(2,1fr);}}}}

/* ── MACRO CONSUMED / REMAINING TOGGLE ─────────────────────────────
   Small pill sitting above the macro strip — flips the strip between
   "what you've eaten" (default) and "what's left vs target". Persists
   choice in localStorage so toggle survives reloads/tab swaps. */
.macro-header{{display:flex;align-items:center;justify-content:space-between;margin:10px 0 8px}}
.macro-header-lbl{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--mu);font-weight:500;
}}
.macro-toggle-btn{{
  display:inline-flex;align-items:center;gap:5px;
  background:var(--sf);border:1px solid var(--bd);border-radius:8px;
  padding:5px 10px;cursor:pointer;transition:all .18s;
  font-family:'Geist Mono','SF Mono',monospace;font-size:9px;font-weight:500;
  letter-spacing:.06em;text-transform:uppercase;color:var(--mu);user-select:none;
}}
.macro-toggle-btn:hover{{border-color:var(--bd2);color:var(--tx)}}
.macro-toggle-btn.remaining{{
  background:var(--ac-dim);border-color:rgba(var(--ac-rgb),.3);color:var(--ac);
}}
.macro-toggle-dot{{width:5px;height:5px;border-radius:50%;background:currentColor}}

/* ── ACTION TILES — replaces the legacy .day-status row ──────────────
   Two-column compact tile grid. Insights · Share · Workout · Cardio,
   plus a full-width Water tile that only appears when water was logged.
   Workout/Cardio tiles show 3 states via the right-side indicator:
     ✓ done (accent green background, brighter text)
     ● today, pending — soft yellow dot + gentle pulse
     ● past, not logged — muted gray dot, no animation
   Tiles use the same accent / chip tokens as .ds-pill.on so the visual
   language stays unified with the rest of the dashboard. */
.action-tiles{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:0}}
/* On phones, Workout/Cardio (shown only when logged) go full-width each so an
   odd number of visible tiles never leaves a lonely half-row gap. */
@media(max-width:560px){{#tile-workout,#tile-cardio{{grid-column:1/-1}}}}
.atile{{
  display:flex;align-items:center;gap:8px;
  padding:8px 12px;border-radius:10px;
  background:var(--sf);border:1px solid var(--bd);
  font-family:inherit;font-size:12px;font-weight:500;
  color:var(--tx2);cursor:pointer;text-align:left;width:100%;
  transition:background .15s,border-color .15s,color .15s;
  line-height:1.25;
}}
.atile:hover{{background:var(--sf2);border-color:var(--bd2);color:var(--tx)}}
.atile:active{{opacity:.8}}
.atile.done{{
  background:var(--ac-dim);border-color:rgba(var(--ac-rgb),.25);
  color:var(--tx);
}}
.atile-ico{{
  width:14px;height:14px;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;color:var(--mu);
}}
.atile:hover .atile-ico{{color:var(--tx2)}}
.atile.done .atile-ico{{color:var(--ac)}}
.atile-lbl{{
  flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  transition:opacity .2s;
}}
.atile-state{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9.5px;letter-spacing:.05em;color:var(--mu);flex-shrink:0;
}}
.atile.done .atile-state{{color:var(--ac)}}
.atile.full{{grid-column:1/-1}}
.atile-dot{{width:7px;height:7px;border-radius:50%;display:inline-block;flex-shrink:0}}
.atile-dot.today{{
  background:var(--ye);box-shadow:0 0 0 0 rgba(234,179,8,.35);
  animation:atileDotPulse 2.6s ease-in-out infinite;
}}
.atile-dot.past{{background:var(--di);opacity:.7}}
@keyframes atileDotPulse{{
  0%,100%{{box-shadow:0 0 0 0 rgba(234,179,8,.35)}}
  50%{{box-shadow:0 0 0 4px rgba(234,179,8,0)}}
}}
/* Fade the label of pending tiles so "incomplete" reads from typography
   too, not just the dot. */
.atile:has(.atile-dot.today) .atile-lbl{{opacity:.62}}
.atile:has(.atile-dot.past)  .atile-lbl{{opacity:.5}}

/* ── INSIGHTS TILE — distinguished as the AI engine ─────────────────
   Subtle accent gradient + lit-up sparkle icon so the tile reads as
   AI-powered without shouting. The other action tiles (Share / Workout
   / Cardio) keep their muted card look — the contrast is the point.
   Gradient stays low-saturation so dark + light themes both stay tidy.
   Note: no corner dot here on purpose — the macro cells already use
   small dots for target status, and stacking a dot on this tile read
   as visual noise. The gradient + AI pill carry the signal. */
.atile.insights-tile{{
  background:
    linear-gradient(135deg,
      var(--ac-dim) 0%,
      rgba(var(--ac-rgb),.06) 60%,
      rgba(99,102,241,.10) 100%);
  border-color:rgba(var(--ac-rgb),.30);
  color:var(--tx);
  position:relative;overflow:hidden;
}}
.atile.insights-tile:hover{{
  border-color:rgba(var(--ac-rgb),.50);
  background:
    linear-gradient(135deg,
      rgba(var(--ac-rgb),.16) 0%,
      rgba(var(--ac-rgb),.08) 60%,
      rgba(99,102,241,.14) 100%);
}}
.atile.insights-tile .atile-ico{{
  color:var(--ac);
  filter:drop-shadow(0 0 4px rgba(var(--ac-rgb),.45));
  animation:insightsSparkle 3.4s ease-in-out infinite;
}}
@keyframes insightsSparkle{{
  0%,100%{{opacity:1;transform:scale(1)}}
  50%   {{opacity:.78;transform:scale(1.08)}}
}}
/* Tiny "AI" mono pill inline in the label — telegraphs that the tile
   surfaces model-generated content, not a raw data view. */
.atile-ai-tag{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:8px;font-weight:600;letter-spacing:.08em;
  padding:1px 4px;margin-left:6px;border-radius:4px;vertical-align:1px;
  background:rgba(var(--ac-rgb),.18);color:var(--ac);
  border:1px solid rgba(var(--ac-rgb),.30);
}}

/* ── WEIGHT MODULE — cut/bulk users only ─────────────────────────
   Sibling of the macro cells; same card chrome and number ladder, just
   wider (full row). Two-column row: WEIGHT label + value left, delta
   + distance-to-goal right. Thin progress bar tracks start → goal
   traversal. Rendered only when primary_goal is 'cut' or 'bulk' —
   for maintain/performance/health users, weight isn't a primary KPI. */
.weight-module{{
  background:var(--sf);border:1px solid var(--bd);border-radius:12px;
  padding:6px 10px 7px;margin-bottom:9px;box-shadow:var(--sh);
  cursor:pointer;transition:border-color .15s,background .15s;
}}
.weight-module:hover{{border-color:var(--bd2,rgba(255,255,255,.12))}}
.weight-module:focus-visible{{outline:1px solid rgba(var(--ac-rgb),.5);outline-offset:1px}}
/* Inline pending dot — sits before the WEIGHT label. Pulses only when today
   has no weigh-in (toggled via .has-pending on the module). */
.wm-label-row{{display:inline-flex;align-items:center;gap:4px;line-height:1}}
.wm-pending-dot{{
  width:5px;height:5px;border-radius:50%;background:var(--ac);
  box-shadow:0 0 0 0 rgba(var(--ac-rgb),.55);
  animation:wmPendingPulse 2.4s ease-in-out infinite;display:none;
}}
.weight-module.has-pending .wm-pending-dot{{display:inline-block}}
@keyframes wmPendingPulse{{
  0%,100%{{box-shadow:0 0 0 0 rgba(var(--ac-rgb),.45)}}
  50%{{box-shadow:0 0 0 4px rgba(var(--ac-rgb),0)}}
}}
.wm-row{{display:flex;align-items:flex-end;justify-content:space-between;gap:10px}}
.wm-stack-l{{display:flex;flex-direction:column;min-width:0}}
.wm-stack-r{{display:flex;flex-direction:column;align-items:flex-end;gap:1px;text-align:right;flex-shrink:0}}
.wm-label{{
  font-size:8.5px;font-weight:500;text-transform:uppercase;letter-spacing:.06em;
  color:var(--mu);margin-bottom:1px;line-height:1;
}}
.wm-num{{
  font-size:17px;font-weight:600;letter-spacing:-.02em;line-height:1;color:var(--tx);
}}
.wm-unit{{font-size:10.5px;font-weight:500;color:var(--mu);margin-left:1px}}
.wm-delta{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;font-weight:500;letter-spacing:.02em;
  white-space:nowrap;line-height:1.2;color:var(--mu);
}}
.wm-delta-strong{{font-weight:600}}
.wm-delta.down .wm-delta-strong{{color:var(--ac)}}
.wm-delta.up   .wm-delta-strong{{color:var(--or)}}
.wm-delta.flat .wm-delta-strong{{color:var(--mu)}}
.wm-sub{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;color:var(--mu);line-height:1.3;letter-spacing:.02em;
}}
.wm-bar{{background:var(--sf3);border-radius:999px;height:3px;margin-top:5px;overflow:hidden}}
/* Gradient fill — strong contrast so it's actually visible at 3px height.
   Anchored to background-size:100% relative to the BAR (the full track),
   not the fill width, so the gradient reads consistently as a glow that
   builds toward the leading edge regardless of progress. */
.wm-fill{{
  height:100%;border-radius:999px;
  background:linear-gradient(90deg,
    rgba(var(--ac-rgb),.25) 0%,
    rgba(var(--ac-rgb),.65) 50%,
    rgba(var(--ac-rgb),1) 100%);
  background-size:200% 100%;
  background-position:left center;
  box-shadow:0 0 6px rgba(var(--ac-rgb),.35);
  transition:width .8s cubic-bezier(.4,0,.2,1);
}}

/* ETA chip — small accent-tinted pill showing projected goal-met date based on
   server-computed analytics.weeks_to_goal (current weight + configured deficit
   vs goal weight). Sits inline with the wm-sub "X to go" line. Hidden when no
   goal weight, no calorie target, or user is moving away from goal. */
.wm-eta{{
  display:inline-flex;align-items:center;
  margin-left:5px;padding:1.5px 5px;border-radius:4px;
  background:var(--ac-dim);color:var(--ac);
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:8.5px;font-weight:600;letter-spacing:.04em;
  white-space:nowrap;cursor:default;
  border:1px solid rgba(var(--ac-rgb),.25);
}}
.wm-eta.off{{background:rgba(var(--or-rgb,255,150,80),.12);color:var(--or);border-color:rgba(var(--or-rgb,255,150,80),.25)}}

/* No separate Log button — the whole module is the tap target (see
   .weight-module:hover / cursor:pointer above). The pending dot lives
   inline with the WEIGHT label via .wm-label-row. */
.weight-module{{position:relative}}

/* Slide-down log form sits beneath the progress bar. Single row: number input,
   kg/lbs segmented toggle, save. Mirrors the .add-card aesthetic but tighter. */
.wm-logform{{
  display:none;margin-top:10px;padding-top:10px;border-top:1px solid var(--bd);
  align-items:center;gap:8px;animation:fadeUp .22s ease;
}}
.wm-logform.open{{display:flex}}
.wm-logform-inp{{
  flex:1;min-width:0;background:var(--sf2);border:1px solid var(--bd);
  border-radius:8px;padding:7px 10px;color:var(--tx);font-family:inherit;
  font-size:14px;font-weight:600;letter-spacing:-.01em;outline:none;
  transition:border-color .15s,background .15s;
}}
.wm-logform-inp:focus{{border-color:var(--ac);background:var(--sf)}}
.wm-logform-inp::placeholder{{color:var(--di);font-weight:500}}
.wm-unit-toggle{{
  display:inline-flex;background:var(--sf2);border:1px solid var(--bd);
  border-radius:8px;padding:2px;gap:2px;flex-shrink:0;
}}
.wm-unit-toggle button{{
  background:transparent;border:none;color:var(--mu);cursor:pointer;
  font-family:'Geist Mono','SF Mono',monospace;font-size:10px;font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;padding:5px 9px;border-radius:6px;
  transition:color .15s,background .15s;
}}
.wm-unit-toggle button.active{{background:var(--ac-dim);color:var(--ac)}}
.wm-logform-save{{
  background:var(--ac-dim);color:var(--ac);border:1px solid rgba(var(--ac-rgb),.35);
  border-radius:8px;padding:7px 12px;font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  cursor:pointer;flex-shrink:0;transition:background .15s,opacity .15s;
}}
.wm-logform-save:hover{{background:rgba(var(--ac-rgb),.18)}}
.wm-logform-save:disabled{{opacity:.5;cursor:default}}

/* Minimal "logged!" celebration. Number gets a brief pulse, a checkmark fades
   in/out over the right side, and a soft accent ring rides the module border. */
.wm-celebrate .wm-num{{animation:wmNumPulse .9s ease-out}}
.weight-module.wm-celebrate{{animation:wmRing 1.1s ease-out}}
.wm-check{{
  position:absolute;top:8px;right:10px;display:inline-flex;align-items:center;
  gap:5px;font-family:'Geist Mono','SF Mono',monospace;font-size:10px;
  font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--ac);
  opacity:0;pointer-events:none;transition:opacity .18s;
}}
.wm-check.show{{opacity:1;animation:wmCheck 1.4s ease-out forwards}}
@keyframes wmNumPulse{{
  0%{{transform:scale(1);color:var(--tx)}}
  35%{{transform:scale(1.06);color:var(--ac)}}
  100%{{transform:scale(1);color:var(--tx)}}
}}
@keyframes wmRing{{
  0%{{box-shadow:var(--sh),0 0 0 0 rgba(var(--ac-rgb),.45)}}
  60%{{box-shadow:var(--sh),0 0 0 8px rgba(var(--ac-rgb),0)}}
  100%{{box-shadow:var(--sh),0 0 0 0 rgba(var(--ac-rgb),0)}}
}}
/* Mobile: KEEP the two-column row so the module stays as compact as desktop
   (column-stacked it nearly doubled in height). Allow delta + sub to wrap to
   a second line when needed; the side-by-side layout fits even at ~360px
   because the number column is narrow ("220.5 lbs" ≈ 80px). Tighten only
   the inline form so input + unit toggle + Save still sit on one row. */
@media(max-width:760px){{
  .weight-module{{padding:6px 10px 7px}}
  .wm-row{{gap:8px}}
  .wm-stack-r{{flex-shrink:1;min-width:0}}
  .wm-delta,.wm-sub{{white-space:normal}}
  .wm-num{{font-size:17px}}
  .wm-unit{{font-size:10.5px}}
  .wm-check{{top:6px;right:9px}}
  .wm-logform{{gap:6px;margin-top:8px;padding-top:8px}}
  .wm-logform-inp{{padding:7px 10px;font-size:14px}}
  .wm-unit-toggle button{{padding:5px 8px}}
  .wm-logform-save{{padding:7px 10px}}
}}
/* Extra-narrow viewports (< 380px): let the form wrap onto two rows so
   the input gets a full row of breathing room instead of being squeezed.
   Also drop the wm-num one more notch so the row never overflows. */
@media(max-width:380px){{
  .wm-num{{font-size:16px}}
  .wm-delta{{font-size:9.5px}}
  .wm-sub{{font-size:8.5px}}
  .wm-logform{{flex-wrap:wrap}}
  .wm-logform-inp{{flex-basis:100%}}
}}
@keyframes wmCheck{{
  0%{{opacity:0;transform:translateY(2px)}}
  18%{{opacity:1;transform:none}}
  78%{{opacity:1;transform:none}}
  100%{{opacity:0;transform:translateY(-2px)}}
}}
.wm-num{{display:inline-block;transform-origin:left center}}

/* ── BOTTOM NAV (mobile) ─────────────────────────────────── */
.bottomnav{{
  display:none;position:fixed;bottom:0;left:0;right:0;z-index:60;
  justify-content:space-around;gap:4px;
  padding:7px 14px calc(7px + env(safe-area-inset-bottom));
  background:var(--bg);border-top:1px solid var(--bd);
}}
.bn-item{{
  flex:1;display:flex;flex-direction:column;align-items:center;gap:5px;
  background:transparent;border:none;
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--mu);cursor:pointer;padding:6px 0 2px;
  transition:color .18s,transform .18s;
  position:relative;font-weight:500;
}}
.bn-item:hover{{color:var(--tx2)}}
.bn-item:active{{transform:scale(.94)}}
.bn-ico{{
  width:24px;height:24px;display:grid;place-items:center;
  transition:transform .25s cubic-bezier(.34,1.56,.64,1);
}}
.bn-item:hover .bn-ico{{transform:translateY(-1px)}}
.bn-item.active{{color:var(--ac)}}
.bn-item.active .bn-ico{{color:var(--ac)}}
/* Subtle accent halo under the active tile — Apple-Health-style "you
   are here" indicator, no heavy underline bar. */
.bn-item.active::before{{
  content:'';position:absolute;
  top:4px;left:50%;transform:translateX(-50%);
  width:26px;height:26px;border-radius:50%;
  background:var(--ac);opacity:.10;
  filter:blur(9px);
  pointer-events:none;
}}

/* ── CHAT PANEL (opened from the header Chat button · consolidated Telegram + iMessage) ─── */
.cw-panel{{
  position:fixed;z-index:89;top:80px;right:24px;
  width:360px;height:min(540px,72vh);
  display:flex;flex-direction:column;overflow:hidden;
  background:var(--hbg);border:1px solid var(--bd);border-radius:16px;
  box-shadow:0 20px 50px rgba(0,0,0,.40);
  backdrop-filter:blur(24px) saturate(140%);-webkit-backdrop-filter:blur(24px) saturate(140%);
  opacity:0;transform:translateY(-8px) scale(.98);pointer-events:none;
  transition:opacity .2s ease,transform .2s cubic-bezier(.2,.7,.2,1);
}}
.cw-panel.open{{opacity:1;transform:none;pointer-events:auto}}
.cw-head{{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:12px 15px;border-bottom:1px solid var(--bd);flex-shrink:0;
}}
.cw-head-l{{display:flex;align-items:center;gap:9px;min-width:0}}
.cw-status{{width:9px;height:9px;border-radius:50%;flex-shrink:0;background:var(--bl)}}
.cw-title{{font-size:14px;font-weight:600;color:var(--tx);line-height:1.15}}
.cw-sub{{font-size:11px;color:var(--mu);margin-top:1px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.cw-close{{
  background:transparent;border:none;color:var(--mu);
  width:28px;height:28px;border-radius:8px;cursor:pointer;font-size:18px;
  display:grid;place-items:center;flex-shrink:0;transition:color .15s;
}}
.cw-close:hover{{color:var(--tx)}}
/* Scrollbar hidden — the thread scrolls, but no visible track/handle. */
.cw-thread{{
  flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:0;
  scrollbar-width:none;-ms-overflow-style:none;
}}
.cw-thread::-webkit-scrollbar{{display:none}}
.cw-day{{
  align-self:center;margin:14px 0 6px;
  font-family:'Geist Mono','SF Mono',monospace;font-size:9px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--mu);
}}
.cw-row{{display:flex;flex-direction:column;max-width:86%;margin-top:8px}}
.cw-row.me{{align-self:flex-end;align-items:flex-end}}
.cw-row.ar{{align-self:flex-start;align-items:flex-start}}
.cw-bubble{{
  padding:9px 13px;border-radius:17px;font-size:13.5px;line-height:1.45;
  white-space:pre-wrap;word-break:break-word;
}}
.cw-row.ar .cw-bubble{{background:var(--sf2);color:var(--tx);border:1px solid var(--bd);border-bottom-left-radius:5px}}
.cw-row.me .cw-bubble{{background:var(--ac-dim);color:var(--tx);border:1px solid rgba(var(--ac-rgb),.24);border-bottom-right-radius:5px}}
.cw-meta{{
  font-size:9.5px;color:var(--mu);margin-top:4px;padding:0 3px;
  font-family:'Geist Mono','SF Mono',monospace;letter-spacing:.03em;
  display:flex;align-items:center;gap:5px;
}}
.cw-cdot{{width:6px;height:6px;border-radius:50%;flex-shrink:0;background:var(--mu)}}
.cw-cdot.tg{{background:var(--bl)}}
.cw-cdot.im{{background:var(--ac)}}
.cw-state{{margin:auto;text-align:center;color:var(--mu);font-size:13px;padding:24px;line-height:1.55}}
/* Minimal action: opens the Arnie chat in Telegram to start a new message. */
.cw-tg{{
  flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:8px;
  padding:11px 14px;border-top:1px solid var(--bd);
  color:var(--mu);text-decoration:none;font-size:12px;font-weight:500;
  transition:color .15s,background .15s;
}}
.cw-tg:hover{{color:var(--ac);background:var(--ac-dim)}}
.cw-tg svg{{flex-shrink:0;opacity:.85}}
.cw-tg:hover svg{{opacity:1}}
@media(max-width:940px){{
  .cw-panel{{
    top:62px;right:12px;left:12px;
    width:auto;height:min(70vh,500px);
  }}
}}

/* ── RESPONSIVE ──────────────────────────────────────────── */
@media(max-width:940px){{
  .shell{{grid-template-columns:1fr}}
  .sidebar{{display:none}}
  .main-inner{{padding:0 20px 90px;max-width:100%;margin:0}}
  .bottomnav{{display:flex}}
  .pagehead{{padding:14px 0 10px}}
  .profile-grid{{grid-template-columns:1fr}}
  #date-next{{display:none}}   /* today is the latest day — no forward arrow on mobile */
}}
/* Landscape mobile (phones rotated) */
@media(max-width:940px) and (orientation:landscape){{
  .main-inner{{padding:0 24px 70px}}
  .bottomnav{{padding:6px 16px calc(6px + env(safe-area-inset-bottom))}}
  .pagehead{{padding:10px 0 8px}}
  .c2col{{grid-template-columns:1fr 1fr}}
}}
@media(max-width:560px){{
  .main-inner{{padding:0 16px 90px}}
  .ph-sub{{flex-wrap:wrap;gap:5px 8px}}
  .c2col{{grid-template-columns:1fr}}
  .log-row{{grid-template-columns:1fr}}
}}

/* ── SECTION TITLES ─────────────────────────────────────── */
.stitle{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10.5px;font-weight:500;color:var(--mu);text-transform:uppercase;
  letter-spacing:.10em;margin:22px 0 10px;display:flex;align-items:center;gap:10px;
}}
.stitle:first-child{{margin-top:6px}}
.stitle.spaced{{justify-content:space-between}}

/* ── COLLAPSIBLE LOG SECTIONS ───────────────────────────── */
.log-section-hd{{cursor:pointer;user-select:none}}
.log-section-body{{overflow:hidden;transition:max-height .25s cubic-bezier(.4,0,.2,1);max-height:2000px}}
.log-section.collapsed .log-section-body{{max-height:0}}
.log-chevron{{
  background:transparent;border:none;color:var(--mu);cursor:pointer;
  font-size:18px;line-height:1;padding:0;transition:transform .2s;
  font-family:inherit;display:grid;place-items:center;width:20px;
}}
.log-section-hd:hover .log-chevron{{color:var(--tx2)}}
.log-section.collapsed .log-chevron{{transform:rotate(-90deg)}}
/* Desktop: always expanded, hide chevron */
@media(min-width:701px){{
  .log-chevron{{display:none}}
  .log-section-body{{max-height:none!important}}
  .log-section-hd{{cursor:default}}
}}

/* ── PROFILE COLLAPSIBLE SECTIONS ──────────────────────────
   Same visual language as .log-section but collapsed by default
   AND togglable on every screen size (Arnie's brain sections
   should opt-in to detail, not blast it on first load). */
.pf-cat-section{{margin-top:14px}}
.pf-cat-hd{{cursor:pointer;user-select:none}}
.pf-cat-body{{
  overflow:hidden;
  transition:max-height .3s cubic-bezier(.4,0,.2,1);
  max-height:3000px;
}}
.pf-cat-section.collapsed .pf-cat-body{{max-height:0}}
/* Chevron — `‹` glyph, defaults to rotated -90deg (pointing down)
   to cue "tap to expand". Settles to 0deg when expanded. The same
   button serves both .pf-cat-section .collapsed and the standalone
   .pf-chevron.expanded case (Arnie's brain top header). */
.pf-chevron{{
  background:transparent;border:none;color:var(--mu);cursor:pointer;
  font-size:18px;line-height:1;padding:0;font-family:inherit;
  display:grid;place-items:center;width:20px;
  transition:transform .2s,color .15s;transform:rotate(-90deg);
}}
.pf-cat-hd:hover .pf-chevron{{color:var(--tx2)}}
.pf-chevron.expanded,
.pf-cat-section:not(.collapsed) .pf-chevron{{transform:none}}

/* ── ADD FOOD / WORKOUT FORMS ────────────────────────────── */
.add-card{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;
  margin-top:10px;overflow:hidden;backdrop-filter:blur(16px);box-shadow:var(--sh);
}}
.add-inp{{
  display:block;width:100%;background:transparent;border:none;
  border-bottom:1px solid var(--bd);color:var(--tx);font-family:inherit;
  font-size:14px;padding:11px 16px;outline:none;transition:background .15s;
}}
.add-inp:focus{{background:var(--sf2)}}
.add-inp::placeholder{{color:var(--di)}}
.add-macros{{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--bd)}}
.add-mac-field{{border-right:1px solid var(--bd);padding:8px 12px}}
.add-mac-field:last-child{{border-right:none}}
.add-mac-field label{{
  display:block;font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--mu);margin-bottom:4px;
}}
.add-mac-field input{{
  width:100%;background:transparent;border:none;color:var(--tx);
  font-family:inherit;font-size:14px;font-weight:500;outline:none;
}}
.add-mac-field input::placeholder{{color:var(--di)}}
.add-submit{{
  display:block;width:100%;border:none;background:transparent;
  color:var(--ac);font-family:'Geist Mono','SF Mono',monospace;
  font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  padding:11px 16px;cursor:pointer;text-align:left;transition:background .15s;
}}
.add-submit:hover{{background:var(--ac-dim)}}
.add-submit:active{{opacity:.7}}
.add-toggle{{
  width:26px;height:26px;border-radius:8px;border:1px solid var(--bd);
  background:var(--sf2);color:var(--mu);font-size:18px;line-height:1;
  cursor:pointer;font-family:inherit;display:grid;place-items:center;
  transition:all .18s;flex-shrink:0;
}}
.add-toggle:hover{{border-color:var(--ac);color:var(--ac);background:var(--ac-dim)}}
.add-toggle.open{{background:var(--ac-dim);border-color:rgba(var(--ac-rgb),.4);color:var(--ac);transform:rotate(45deg)}}
.ai-pill{{
  background:var(--ac-dim);color:var(--ac);border:1px solid rgba(var(--ac-rgb),.2);
  padding:2px 7px;border-radius:10px;
  font-family:'Geist Mono','SF Mono',monospace;font-size:9px;letter-spacing:.06em;font-weight:500;
}}

/* ── PERIOD NAV (Trends tab) — mirrors .dnav so the Trends
   tab gets the same chip-selector rhythm as Daily's date nav.
   3 fixed chips (7d / 30d / 90d) + right-aligned date-range
   meta line. Hover/active states match .dchip exactly. */
.period-nav{{display:flex;align-items:center;gap:6px;margin-bottom:14px;flex-wrap:wrap}}
.pchip{{
  background:var(--sf);border:1px solid var(--bd);color:var(--mu);
  padding:8px 14px;border-radius:10px;font-family:inherit;
  font-size:12px;font-weight:500;letter-spacing:-.01em;
  cursor:pointer;transition:all .2s;flex-shrink:0;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
  display:inline-flex;align-items:center;gap:5px;
}}
.pchip:hover{{border-color:var(--bd2);color:var(--tx2)}}
.pchip.active{{background:var(--ac-dim);border-color:rgba(var(--ac-rgb),.4);color:var(--tx)}}
.period-meta{{
  margin-left:auto;font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;color:var(--mu);letter-spacing:.06em;text-transform:uppercase;
  white-space:nowrap;
}}

/* One-liner summary that sits below the period chips. Plain mono text,
   no chrome. Three numbers separated by dots. Color tints carry the
   goal-fit signal (--ac toward goal, --re drifting, --tx neutral). */
.trend-line{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:12px;color:var(--mu);letter-spacing:.02em;
  margin:0 0 2px;padding:2px 2px;line-height:1.6;
  display:flex;flex-wrap:wrap;gap:14px;align-items:center;
}}
.trend-line .tl-val{{color:var(--tx)}}
.trend-line .tl-val.up{{color:var(--ac)}}
.trend-line .tl-val.dn{{color:var(--re)}}
.trend-line .tl-dot{{opacity:.35;color:var(--mu)}}

/* ── DATE NAV ────────────────────────────────────────────── */
.dnav{{display:flex;align-items:center;gap:6px;margin-bottom:16px}}
.dscroll{{flex:1;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}}
.dscroll::-webkit-scrollbar{{display:none}}
.darr{{
  background:var(--sf);border:1px solid var(--bd);color:var(--mu);
  width:34px;height:34px;min-width:34px;border-radius:10px;cursor:pointer;
  font-size:15px;display:flex;align-items:center;justify-content:center;
  font-family:inherit;flex-shrink:0;transition:all .2s;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.darr:hover{{border-color:var(--bd2);color:var(--tx)}}
.darr:disabled{{opacity:.3;cursor:default}}
.dchip{{
  background:var(--sf);border:1px solid var(--bd);color:var(--mu);
  padding:8px 14px;border-radius:10px;
  font-family:'Geist Mono','SF Mono',monospace;font-size:11px;font-weight:500;
  white-space:nowrap;cursor:pointer;transition:all .2s;flex-shrink:0;
  display:inline-flex;align-items:center;gap:5px;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.dchip:hover{{border-color:var(--bd2);color:var(--tx2)}}
.dchip.active{{background:var(--ac-dim);border-color:rgba(var(--ac-rgb),.4);color:var(--tx)}}
.today-tag{{
  background:var(--ac);color:#000;
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:8px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;
  padding:1px 5px;border-radius:4px;
}}
[data-theme="light"] .today-tag{{color:#fff}}

/* ── SIMPLE CARD ─────────────────────────────────────────── */
.card{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:16px;
  transition:background .3s,border-color .3s;
}}
.clbl{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10.5px;color:var(--mu);text-transform:uppercase;
  letter-spacing:.10em;margin-bottom:9px;font-weight:500;
}}
.cval{{
  font-family:'Instrument Serif','Times New Roman',serif;
  font-size:34px;font-weight:normal;line-height:1;letter-spacing:-.02em;
}}
.csub{{font-size:12px;color:var(--mu);margin-top:5px;font-weight:400}}
.ptrack{{background:var(--sf2);border-radius:999px;height:3px;margin-top:11px;overflow:hidden}}
.pfill{{height:100%;border-radius:999px;transition:width .8s cubic-bezier(.4,0,.2,1)}}

/* ── STATUS BADGES ───────────────────────────────────────── */
.sbrow{{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}}
.badge{{
  display:inline-flex;align-items:center;gap:4px;
  padding:5px 10px;border-radius:9px;font-size:11px;font-weight:600;
  border:1px solid transparent;
}}
.bg-g{{background:rgba(var(--ac-rgb),.1);color:var(--ac);border-color:rgba(var(--ac-rgb),.2)}}
.bg-n{{background:var(--sf2);color:var(--mu);border-color:var(--bd)}}
.bg-b{{background:rgba(59,130,246,.1);color:var(--bl);border-color:rgba(59,130,246,.2)}}

/* ── MACRO RING ──────────────────────────────────────────── */
.macro-ring-wrap{{
  display:flex;align-items:center;gap:20px;
  background:var(--sf);border:1px solid var(--bd);border-radius:18px;padding:20px;
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);box-shadow:var(--sh);
}}
.macro-ring-canvas{{width:80px;height:80px;min-width:80px;min-height:80px;flex-shrink:0}}
.macro-legend{{flex:1;display:flex;flex-direction:column;gap:8px}}
.mleg{{display:flex;align-items:center;gap:8px;font-size:12px}}
.mleg-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
.mleg-lbl{{color:var(--mu);flex:1;font-weight:400}}
.mleg-val{{font-weight:500;color:var(--tx);font-size:12px}}
.mleg-sub{{font-family:'Geist Mono','SF Mono',monospace;font-size:10px;color:var(--di)}}
.macro-divider{{border:none;border-top:1px solid var(--bd);margin:3px 0}}

/* ── CONSISTENCY HEATMAP ─────────────────────────────────── */
.heat-wrap{{background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:16px;backdrop-filter:blur(16px);box-shadow:var(--sh)}}
.heat-dow{{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-bottom:4px}}
.heat-dow span{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;color:var(--di);text-align:center;font-weight:500;
  text-transform:uppercase;letter-spacing:.06em;
}}
.heat-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}}
.hcell{{height:22px;border-radius:5px;background:var(--sf3);border:1px solid var(--bd);position:relative;transition:transform .15s;cursor:default}}
[data-theme="light"] .hcell{{background:#e4e8f0;border-color:#d0d8e8}}
.hcell:hover{{transform:scale(1.2);z-index:2}}
.hcell.h-on{{background:#22c55e;border-color:#22c55e}}
.hcell.h-off{{background:#f59e0b;border-color:#f59e0b}}
.hcell.h-today{{box-shadow:0 0 0 2px var(--ac)}}
.hcell-wo{{position:absolute;bottom:2px;right:2px;width:3px;height:3px;border-radius:50%;background:rgba(255,255,255,.8)}}
.heat-legend{{
  display:flex;gap:12px;margin-top:9px;font-size:10px;color:var(--di);align-items:center;
  font-family:'Geist Mono','SF Mono',monospace;letter-spacing:.04em;
}}
.hleg-dot{{width:8px;height:8px;border-radius:2px;display:inline-block;flex-shrink:0}}

/* ── GOAL PROGRESS ───────────────────────────────────────── */
.goal-card{{background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:16px;backdrop-filter:blur(16px);box-shadow:var(--sh)}}
.goal-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}}
.goal-title{{font-family:'Instrument Serif','Times New Roman',serif;font-size:24px;font-weight:normal;letter-spacing:-.01em}}
.goal-sub{{font-family:'Geist Mono','SF Mono',monospace;font-size:10px;color:var(--mu);margin-top:4px;letter-spacing:.04em}}
.goal-current{{text-align:right}}
.goal-lbs{{font-family:'Instrument Serif','Times New Roman',serif;font-size:34px;font-weight:normal;line-height:1;letter-spacing:-.02em}}
.goal-lbs-lbl{{font-family:'Geist Mono','SF Mono',monospace;font-size:9px;color:var(--mu);letter-spacing:.08em;text-transform:uppercase;margin-top:2px}}
.goal-track{{position:relative;height:7px;background:var(--sf2);border-radius:999px;margin:12px 0 9px}}
.goal-fill{{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--bl),var(--ac));transition:width .9s cubic-bezier(.4,0,.2,1)}}
.goal-pin{{position:absolute;top:50%;transform:translate(-50%,-50%);width:14px;height:14px;border-radius:50%;border:2px solid var(--bg)}}
.goal-labels{{display:flex;justify-content:space-between;font-family:'Geist Mono','SF Mono',monospace;font-size:10px;color:var(--mu);font-weight:500}}

/* ── STREAK STATS ────────────────────────────────────────── */
.stat-row{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}}
.stat-tile{{background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:16px 10px;text-align:center;backdrop-filter:blur(16px);box-shadow:var(--sh)}}
.stat-num{{font-family:'Instrument Serif','Times New Roman',serif;font-size:40px;font-weight:normal;line-height:1;letter-spacing:-.02em}}
.stat-lbl{{font-family:'Geist Mono','SF Mono',monospace;font-size:10px;color:var(--mu);text-transform:uppercase;letter-spacing:.10em;margin-top:6px;font-weight:500}}

/* ── INSIGHTS ────────────────────────────────────────────── */
.icrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
[data-theme="dark"] .icrd{{background:var(--sf2)}}
.irow{{
  display:flex;align-items:flex-start;gap:10px;
  padding:11px 14px;border-bottom:1px solid var(--bd);
}}
.irow:last-child{{border-bottom:none}}
.iico{{
  font-size:10px;width:6px;height:6px;flex-shrink:0;margin-top:7px;
  background:var(--pu);border-radius:50%;
}}
.itxt{{font-size:13.5px;line-height:1.5;color:var(--tx);font-weight:400}}
.itxt strong{{font-weight:600;color:var(--tx)}}
.iload,.iempty{{
  padding:18px 16px;color:var(--mu);font-size:13.5px;
  text-align:left;line-height:1.55;
}}

/* ── COACH INSIGHTS — minimal collapsible banner (collapsed by default) ─── */
.insights{{margin:0 0 2px}}
.ins-banner{{
  display:flex;align-items:center;gap:10px;width:100%;
  padding:11px 14px;border-radius:12px;cursor:pointer;user-select:none;
  border:1px solid var(--bd2);background:var(--sf2);box-shadow:var(--sh);
  transition:background .15s,border-color .15s,transform .1s;
}}
.ins-banner:hover{{background:var(--sf3);border-color:var(--pu)}}
.ins-banner:active{{transform:scale(.98)}}
.ins-spark{{
  flex-shrink:0;display:grid;place-items:center;color:var(--pu);
  width:28px;height:28px;background:var(--sf3);border-radius:8px;
}}
.ins-head{{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}}
.ins-title{{font-size:13px;font-weight:600;color:var(--tx);letter-spacing:-.01em;white-space:nowrap}}
.ins-preview{{font-size:11px;color:var(--mu);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3;}}
.insights.open .ins-preview{{display:none;}}
.ins-time{{font-size:10px;color:var(--mu);font-family:'Geist Mono','SF Mono',monospace;letter-spacing:.02em;white-space:nowrap}}
.ins-actions{{margin-left:auto;display:flex;align-items:center;gap:2px;flex-shrink:0}}
.ins-refresh{{
  color:var(--mu);font-size:14px;line-height:1;cursor:pointer;
  width:24px;height:24px;display:grid;place-items:center;border-radius:7px;
  transition:color .15s,background .15s;
}}
.ins-refresh:hover{{color:var(--tx2);background:var(--sf3)}}
.ins-chev{{color:var(--tx2);font-size:14px;padding-right:2px;
  transition:transform .22s cubic-bezier(.2,.7,.2,1)}}
.insights.open .ins-chev{{transform:rotate(180deg)}}
/* Inline panel — collapsed by default, expanded when .open is set on
   #ins-day by toggleInsights() / handleInsightsTile(). No chrome on the
   body itself (transparent) — the .icrd inside handles all the card
   styling. Just an animated height wrapper. */
.ins-body{{
  max-height:0;overflow:hidden;
  transition:max-height .3s cubic-bezier(.4,0,.2,1),margin-top .2s;
  background:transparent;border:none;
}}
.insights.open .ins-body{{
  max-height:1600px;margin-top:10px;
}}
/* Panel wrap — single card chrome around the meta row + insights-card.
   Border on the wrap (not the inner card) avoids the double-border that
   plagued the previous version. .icrd inside gets transparent so it
   blends with the wrap. */
.ins-panel-wrap{{
  background:var(--sf);border:1px solid var(--bd);border-radius:12px;
  overflow:hidden;
}}
.ins-meta{{
  display:flex;align-items:center;gap:8px;
  font-family:'Geist Mono','SF Mono',monospace;font-size:9.5px;
  letter-spacing:.06em;text-transform:uppercase;color:var(--mu);
  padding:9px 14px 6px;font-weight:500;
  border-bottom:1px solid var(--bd);
}}
.ins-meta .ins-refresh{{
  margin-left:auto;cursor:pointer;font-size:12px;letter-spacing:0;
  width:20px;height:20px;display:inline-grid;place-items:center;
  border-radius:6px;color:var(--mu);transition:color .15s,background .15s;
}}
.ins-meta .ins-refresh:hover{{color:var(--tx2);background:var(--sf2)}}
/* Inner card: no border/bg/radius — handled by .ins-panel-wrap above. */
.ins-panel-wrap .icrd{{
  background:transparent;border:none;border-radius:0;box-shadow:none;
  backdrop-filter:none;
}}
[data-theme="dark"] .ins-panel-wrap .icrd{{background:transparent}}

/* ── WEARABLE ────────────────────────────────────────────── */
.htile{{
  background:var(--sf);border:1px solid var(--bd);border-radius:12px;
  padding:10px 8px;text-align:center;backdrop-filter:blur(12px);
  box-shadow:var(--sh);transition:background .3s;
}}
.hv{{font-family:'Instrument Serif','Times New Roman',serif;font-size:18px;font-weight:normal;line-height:1;letter-spacing:-.01em}}
.hl{{font-family:'Geist Mono','SF Mono',monospace;font-size:9px;color:var(--mu);text-transform:uppercase;letter-spacing:.08em;margin-top:3px;font-weight:500}}

/* ── WORKOUT GROUPS (Cardio / Strength) — preview-style connected card
   with hairline dividers between rows. Header (.ex-group-hd) is a small
   mono caps label + extending hairline rule. Each .exrow is a flat row
   with name on left + mono meta on right; tap reveals edit/delete. */
.ex-group{{margin-bottom:8px}}
.ex-group:last-child{{margin-bottom:0}}
.ex-group-hd{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;
  color:var(--mu);margin-bottom:4px;display:flex;align-items:center;gap:6px;
}}
.ex-group-hd::after{{content:'';flex:1;height:1px;background:var(--bd)}}
.ex-card{{
  background:var(--sf);border:1px solid var(--bd);
  border-radius:12px;overflow:hidden;
}}
.exrow{{
  display:flex;justify-content:space-between;align-items:baseline;gap:10px;
  padding:7px 13px;border-bottom:1px solid var(--bd);
  cursor:pointer;transition:background .12s;position:relative;
}}
.exrow:last-child{{border-bottom:none}}
.exrow:hover{{background:var(--sf2)}}
.ex-name{{
  font-size:13.5px;font-weight:500;color:var(--tx);
  line-height:1.25;flex:1;min-width:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}}
.ex-meta{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:11px;color:var(--mu);white-space:nowrap;
  flex-shrink:0;letter-spacing:.01em;
}}
.exrow-actions{{display:none;align-items:center;gap:4px;flex-shrink:0}}
.exrow.open .exrow-actions{{display:flex}}
.exrow.open .ex-meta{{display:none}}
.exrow-actions .ibtn{{width:24px;height:24px;font-size:11px}}
.exrow-actions .ibtn.del{{font-size:13px}}
/* Workout log restored to use the original .lcrd + .eg-row layout —
   the .ex-log-wrap / .ex-group / .ex-card / .exrow rules introduced
   during the preview port are no longer referenced by the markup or
   renderer. Left in the stylesheet as harmless dead code; cheap to
   resurrect if we ever want the split-by-category cardio/strength
   layout back. */

/* ── LOG CARDS — preview-style connected list with hairline dividers ──
   Flat informational rows; tap reveals edit/delete via .lrow.open. */
.lcrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:12px;
  overflow:hidden;transition:background .3s;
}}
.lrow{{
  display:flex;align-items:flex-start;gap:10px;
  padding:8px 13px;border-bottom:1px solid var(--bd);
  cursor:pointer;transition:background .12s;
  position:relative;
}}
.lrow:last-child{{border-bottom:none}}
.lrow:hover{{background:var(--sf2)}}
.lrow-main{{flex:1;min-width:0}}
/* Right-aligned mono calorie column — eye scans straight down the
   numbers when comparing rows. */
.lcal{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:12px;font-weight:500;color:var(--tx2);
  white-space:nowrap;flex-shrink:0;align-self:flex-start;
  letter-spacing:.01em;padding-top:1px;
}}
.lcal-unit{{color:var(--mu);font-size:9.5px;margin-left:1px;letter-spacing:.06em}}
/* Secondary meta line: "qty · 34p · 55c · 14f" — bold numbers, muted
   text/separators. tabular-nums keeps macros vertically aligned. */
.lmeta{{
  font-size:11px;color:var(--mu);margin-top:2px;line-height:1.3;
  font-variant-numeric:tabular-nums;
}}
.lmeta .sep{{opacity:.5;margin:0 4px}}
.lmeta b{{color:var(--tx2);font-weight:500}}
/* Edit/delete actions appear only when the row is .open (tapped) so the
   default state stays clean and informational. */
.lrow-actions{{
  display:none;align-items:center;gap:4px;flex-shrink:0;
}}
.lrow.open .lrow-actions{{display:flex}}
.lrow-actions .ibtn{{width:24px;height:24px;font-size:11px}}
.lrow-actions .ibtn.del{{font-size:13px}}
/* Legacy .ficon / .fbody slots kept for backward-compat with any
   non-food usage of .lrow (currently none after the refactor). */
.fbody{{flex:1;min-width:0}}
.lname{{
  font-size:13.5px;font-weight:500;line-height:1.3;word-break:break-word;
  color:var(--tx);display:flex;align-items:center;gap:6px;flex-wrap:wrap;
}}
/* Mobile food rows — modest padding tightening only. Type sizes match
   desktop (overridden again in the ≤560px block below for smaller
   phones if needed). Earlier aggressive shrink (12.5/10/11) made
   the names hard to read on phones — reverted. */
@media(max-width:700px){{
  .lrow{{padding:8px 13px;gap:9px}}
  .lmeta .sep{{margin:0 3px}}
}}
.est-tag{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:8px;letter-spacing:.05em;text-transform:uppercase;
  color:var(--ye);font-weight:500;flex-shrink:0;opacity:.8;
}}
.est-tag::before{{content:'●';font-size:6px;margin-right:2.5px;vertical-align:1px;}}
/* Photo tag — subtle camera glyph next to foods Arnie logged from an
   image. Sits beside the name like the est pill; muted by default so it
   reads as provenance, not a badge. */
.photo-tag{{
  font-size:10px;line-height:1;color:var(--mu);opacity:.7;
  margin-left:1px;vertical-align:1px;flex-shrink:0;
}}
/* Legend row BELOW the food log — footnote-style, surfaces only when an
   estimated item is present. Top-dashed-border separates it from the food
   rows above; subdued opacity so it reads as a footnote, not a header.
   Mirrors the est-tag styling so the connection is visual rather than
   verbal; the explanation text reads in muted body color. */
.est-legend{{
  display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;
  padding:8px 14px 4px;margin:6px 0 -2px;
  font-size:10px;color:var(--mu);line-height:1.3;
  border-top:1px dashed var(--bd);opacity:.75;
}}
.est-tag-static{{opacity:.9;font-size:8.5px}}
.est-legend-txt{{font-weight:400;letter-spacing:.01em}}
.lqty{{font-size:13px;color:var(--mu);margin-top:3px;font-weight:400}}
.lmac{{
  display:flex;gap:0;font-size:12px;margin-top:5px;flex-wrap:wrap;
  font-family:'Geist Mono','SF Mono',monospace;
  align-items:center;
}}
.lmac .lm-sep{{color:var(--di);margin:0 5px;font-size:10px;}}
.lmac .lm-cal{{color:var(--tx2);font-weight:600;font-size:13px;}}
.lmac .lm-macro{{color:var(--mu);font-weight:400;font-size:11px;}}
.lmac b{{font-weight:600}}
.lempty{{
  padding:20px 16px;color:var(--mu);font-size:13.5px;
  text-align:left;line-height:1.5;
}}

/* ── TRAINING PROGRAM ───────────────────────────────────── */
.wp-summary{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;
  padding:15px 16px;backdrop-filter:blur(16px);box-shadow:var(--sh);
}}
.wp-name{{font-size:15px;font-weight:600;letter-spacing:-.01em;margin-bottom:3px}}
.wp-focus{{font-size:13px;color:var(--mu);margin-bottom:13px}}
.wp-rotation{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:16px}}
.wp-chip{{
  font-size:11.5px;font-weight:500;color:var(--tx2);background:var(--sf2);
  border:1px solid var(--bd);border-radius:7px;padding:3px 8px;line-height:1.35;
}}
.wp-days{{display:flex;flex-direction:column;gap:10px}}
.wp-day{{
  border:1px solid var(--bd);border-radius:12px;overflow:hidden;
  background:var(--sf);
}}
.wp-day-hd{{
  display:flex;align-items:center;gap:10px;padding:13px 16px;
  cursor:pointer;user-select:none;transition:background .15s;
}}
.wp-day-hd:hover{{background:var(--sf2)}}
.wp-day-name{{font-weight:600;font-size:14px;flex:1}}
.wp-priority{{
  font-family:'Geist Mono','SF Mono',monospace;font-size:9px;
  letter-spacing:.08em;text-transform:uppercase;padding:2px 7px;
  border-radius:5px;border:1px solid var(--bd);color:var(--mu);
}}
.wp-priority.primary{{color:var(--ac);border-color:rgba(var(--ac-rgb),.3);background:var(--ac-dim)}}
.wp-priority.secondary{{color:var(--ye);border-color:rgba(234,179,8,.3)}}
.wp-chevron{{font-size:11px;color:var(--mu);transition:transform .2s}}
.wp-day.open .wp-chevron{{transform:rotate(90deg)}}
.wp-day-body{{display:none;border-top:1px solid var(--bd);padding:14px 16px}}
.wp-day.open .wp-day-body{{display:block}}
.wp-goals{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}}
.wp-goal{{
  font-size:11.5px;font-weight:500;color:var(--tx2);background:var(--sf2);
  border:1px solid var(--bd);border-radius:7px;padding:3px 8px;
}}
.wp-exlist{{display:flex;flex-direction:column;gap:6px}}
.wp-ex{{display:flex;align-items:flex-start;gap:10px;font-size:13px}}
.wp-ex-dot{{width:6px;height:6px;border-radius:50%;background:var(--ac);flex-shrink:0;margin-top:5px}}
.wp-ex-main{{color:var(--tx)}}
.wp-ex-perf{{font-family:'Geist Mono','SF Mono',monospace;font-size:10.5px;color:var(--mu);margin-top:2px}}
.wp-ex-cat-accessory .wp-ex-dot{{background:var(--bl)}}
.wp-ex-cat-cardio .wp-ex-dot{{background:var(--or)}}
.wp-empty{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;
  padding:28px 20px;text-align:center;color:var(--mu);font-size:14px;
  backdrop-filter:blur(16px);
}}
.wp-empty .wp-empty-hint{{font-size:12px;margin-top:6px;color:var(--di)}}

/* ── PROFILE GRID ────────────────────────────────────────── */
.profile-grid{{display:grid;grid-template-columns:1.1fr .9fr;gap:20px;align-items:start}}
@media(max-width:800px){{.profile-grid{{grid-template-columns:1fr}}}}
.pstack{{display:flex;flex-direction:column}}
.goal-badge,.coach-badge{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  border-radius:8px;padding:3px 10px;font-weight:500;
  word-break:break-word;white-space:normal;line-height:1.4;
  display:inline-block;max-width:100%;
}}
.goal-badge{{color:var(--ac);border:1px solid rgba(var(--ac-rgb),.35)}}
.coach-badge{{color:var(--pu);border:1px solid rgba(168,85,247,.35)}}

/* ── DEVICE CARDS — compact horizontal tiles, 3-up grid ────
   3 columns on desktop, 2 on mobile. Smaller icons + tighter
   padding than the original chunky 2-up cards so the section
   scales when we add Fitbit/Hume/Garmin/etc. No outer .infocrd
   wrapper — each card's border does the visual containment. */
.dev-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}}
.dev-card{{
  display:flex;align-items:center;gap:9px;padding:9px 11px;
  border-radius:11px;border:1px solid var(--bd);background:var(--sf);
  min-width:0;transition:all .2s;text-decoration:none;color:inherit;
}}
.dev-card:hover{{border-color:var(--bd2);background:var(--sf2)}}
.dev-card.dev-link{{cursor:pointer}}
.dev-card.dev-soon{{opacity:.55}}
.dev-logo{{
  width:28px;height:28px;border-radius:8px;flex-shrink:0;
  background:var(--sf2);border:1px solid var(--bd);
  display:grid;place-items:center;font-size:14px;line-height:1;
}}
.dev-body{{min-width:0;display:flex;flex-direction:column;gap:2px}}
.dev-name{{
  font-size:12px;font-weight:500;color:var(--tx);line-height:1.2;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}}
.dev-status{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:8.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--mu);display:inline-flex;align-items:center;gap:4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.2;
}}
.dev-status.dev-live{{color:var(--ac)}}
.dev-dot{{
  width:5px;height:5px;border-radius:50%;
  background:currentColor;box-shadow:0 0 5px currentColor;flex-shrink:0;
}}

/* ── CHART TITLES ────────────────────────────────────────── */
.ctitle{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;font-weight:500;margin-bottom:14px;color:var(--mu);
  text-transform:uppercase;letter-spacing:.14em;
  display:flex;justify-content:space-between;align-items:center;
}}
.ctitle-val{{font-weight:600}}
.erow{{padding:12px 14px;border-bottom:1px solid var(--bd);position:relative}}
/* Grouped exercise rows */
.eg-row{{padding:12px 14px;border-bottom:1px solid var(--bd);cursor:pointer;user-select:none;transition:background .15s}}
.eg-row:last-child{{border-bottom:none}}
.eg-row:hover{{background:var(--sf2)}}
.eg-hd{{display:flex;align-items:center;gap:8px}}
.eg-name{{font-size:14px;font-weight:500;color:var(--tx);flex:1}}
.eg-summary{{font-family:'Geist Mono','SF Mono',monospace;font-size:11px;color:var(--tx2);white-space:nowrap}}
.eg-chevron{{font-size:10px;color:var(--di);transition:transform .18s;flex-shrink:0}}
.eg-row.open .eg-chevron{{transform:rotate(90deg)}}
.eg-sets{{display:none;padding:6px 0 2px}}
.eg-row.open .eg-sets{{display:block}}
.eg-set{{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12.5px;color:var(--tx2)}}
.eg-set-num{{font-family:'Geist Mono','SF Mono',monospace;font-size:10px;color:var(--di);width:24px;flex-shrink:0}}
.eg-set-detail{{font-family:'Geist Mono','SF Mono',monospace;font-size:12px;color:var(--ac)}}
.eg-del{{width:22px;height:22px;border-radius:5px;border:1px solid transparent;background:transparent;color:var(--di);cursor:pointer;font-size:11px;display:grid;place-items:center;transition:all .15s;flex-shrink:0}}
.eg-del:hover{{color:var(--re);border-color:rgba(239,68,68,.3);background:rgba(239,68,68,.08)}}
.food-macros{{display:inline-flex;align-items:center;gap:0;font-family:'Geist Mono','SF Mono',monospace;flex:1;min-width:0;}}
.food-macros .fm-label{{color:var(--mu);font-weight:400;font-size:10.5px;}}
.food-macros .fm-sep{{color:var(--di);margin:0 4px;font-size:10px;}}
.food-macros .fm-val{{font-weight:600;font-size:12px;}}
.food-macros .fm-cal{{color:var(--ac);}}
.food-macros .fm-pro{{color:var(--bl);}}
.food-macros .fm-carb{{color:var(--or);}}
.food-macros .fm-fat{{color:var(--pu);}}
.erow:last-child{{border-bottom:none}}
.ecnt{{display:flex;justify-content:space-between;align-items:center;padding-right:66px;gap:8px}}
.ename{{font-size:14px;font-weight:500;word-break:break-word;flex:1;color:var(--tx)}}
.edet{{font-family:'Geist Mono','SF Mono',monospace;font-size:11px;color:var(--ac);font-weight:500;white-space:nowrap}}

/* ── EDIT / DELETE ───────────────────────────────────────── */
.ract{{position:absolute;top:9px;right:9px;display:flex;gap:4px}}
.ibtn{{
  background:var(--sf2);border:1px solid var(--bd);color:var(--mu);
  width:28px;height:28px;border-radius:8px;cursor:pointer;font-size:12px;
  display:flex;align-items:center;justify-content:center;font-family:inherit;
  transition:all .15s;
}}
.ibtn:active{{transform:scale(.88)}}
.ibtn:hover{{border-color:var(--bd2);color:var(--tx)}}
.ibtn.del:hover{{background:rgba(239,68,68,.12);color:var(--re);border-color:rgba(239,68,68,.4)}}
.eform{{display:grid;gap:8px;margin-top:4px}}
.eform input{{
  background:var(--inp);border:1px solid var(--bd);color:var(--tx);
  padding:8px 10px;border-radius:9px;font-size:13px;font-family:inherit;width:100%;
  transition:border-color .15s;
}}
.eform input:focus{{outline:none;border-color:var(--ac)}}
.emac{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}}
.emc label{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;color:var(--mu);display:block;margin-bottom:3px;
  font-weight:500;text-transform:uppercase;letter-spacing:.08em;
}}
.eact{{display:flex;gap:6px;margin-top:4px}}
.sbtn{{
  background:var(--ac);color:#000;border:none;padding:9px 16px;
  border-radius:10px;font-weight:600;font-size:13px;cursor:pointer;font-family:inherit;
  flex:1;min-height:38px;transition:opacity .15s;
}}
[data-theme="light"] .sbtn{{color:#fff}}
.sbtn:hover{{opacity:.88}}
.cbtn{{
  background:var(--sf2);color:var(--mu);border:1px solid var(--bd);
  padding:9px 16px;border-radius:10px;font-size:13px;cursor:pointer;font-family:inherit;
  min-height:38px;transition:all .15s;
}}
.cbtn:hover{{border-color:var(--bd2);color:var(--tx)}}

/* ── CHARTS ──────────────────────────────────────────────── */
.ccrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:16px;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
.ctitle{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;font-weight:500;margin-bottom:14px;color:var(--mu);
  text-transform:uppercase;letter-spacing:.14em;
}}
.cwrap{{position:relative;height:150px}}
.c2col{{display:grid;grid-template-columns:1fr;gap:12px}}
@media(min-width:600px){{.c2col{{grid-template-columns:1fr 1fr}}}}

/* ── HISTORY TABLE ───────────────────────────────────────── */
.htbl{{width:100%;border-collapse:collapse;font-size:12px}}
.htbl th{{
  font-family:'Geist Mono','SF Mono',monospace;
  color:var(--mu);text-transform:uppercase;letter-spacing:.1em;
  font-size:9.5px;font-weight:500;padding:10px 14px;text-align:left;
  border-bottom:1px solid var(--bd);
}}
.htbl th.r{{text-align:right}}
.htbl td{{padding:11px 14px;border-bottom:1px solid var(--bd);color:var(--tx2);font-size:13px}}
.htbl tr:last-child td{{border-bottom:none}}
.htbl tr:hover td{{background:var(--sf2)}}
.td-date{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:11px;letter-spacing:.04em;color:var(--mu)!important;font-weight:500;
}}
.htbl td.r{{text-align:right;font-family:'Geist Mono','SF Mono',monospace;font-size:12px}}
.td-ok{{color:var(--ac)!important;font-weight:600}}
.td-ov{{color:var(--re)!important;font-weight:600}}

/* ── PROFILE ─────────────────────────────────────────────── */
.infocrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);margin-bottom:9px;transition:background .3s;
}}
.inrow{{
  display:flex;align-items:flex-start;
  gap:12px;padding:13px 16px;border-bottom:1px solid var(--bd);
}}
.inrow:last-child{{border-bottom:none}}
.inlbl{{font-size:13px;color:var(--mu);font-weight:400;flex-shrink:0;min-width:110px;padding-top:2px}}
.inrow-right{{flex:1;display:flex;align-items:flex-start;justify-content:flex-end;gap:6px;min-width:0}}
.inrow-edit{{
  width:22px;height:22px;border-radius:6px;font-size:10px;flex-shrink:0;
  background:var(--sf2);border:1px solid var(--bd);color:var(--mu);
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:all .15s;
}}
.inrow-edit:hover{{border-color:var(--bd2);color:var(--tx)}}
.inrow-x{{
  width:20px;height:20px;border-radius:5px;font-size:10px;flex-shrink:0;
  background:transparent;border:1px solid transparent;color:var(--mu);
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  opacity:.3;transition:all .15s;
}}
.inrow:hover .inrow-x{{opacity:.65}}
.inrow-x:hover{{opacity:1;color:var(--re);border-color:var(--bd);background:var(--sf2)}}
.inval{{
  font-size:13px;font-weight:500;color:var(--tx2);
  text-align:right;word-break:break-word;overflow-wrap:anywhere;flex:1;min-width:0;
}}
.conf-dot{{
  width:5px;height:5px;border-radius:50%;flex-shrink:0;
  align-self:flex-start;margin-top:6px;
}}
/* Basics — compact demographic grid (short scalar values) */
/* Sub-section labels inside the "Your settings" block (Demographics, Goals & targets).
   Lighter weight than .stitle so the section header stays the dominant label. */
.settings-sub{{
  font-family:'Geist Mono','SF Mono',monospace;font-size:9.5px;letter-spacing:.11em;
  text-transform:uppercase;color:var(--mu);font-weight:500;margin:8px 2px 6px;
}}

/* ── "Calculate for me" card — auto-derive calorie + macro targets ───
   Sits below the user-defined goals card on the Profile tab. Title
   bar shows an (i) glyph that toggles the rules panel below. */
.calc-card{{
  background:var(--sf);border:1px solid var(--bd);border-radius:12px;
  padding:11px 14px;margin-top:8px;
}}
.calc-card-hd{{display:flex;align-items:center;gap:8px;margin-bottom:3px}}
.calc-card-title{{font-size:13.5px;font-weight:600;color:var(--tx);flex:1}}
.calc-info-btn{{
  background:transparent;border:1px solid var(--bd);border-radius:7px;
  width:24px;height:24px;display:grid;place-items:center;cursor:pointer;
  color:var(--mu);transition:color .15s,border-color .15s,background .15s;
  font-family:inherit;flex-shrink:0;
}}
.calc-info-btn:hover{{color:var(--ac);border-color:var(--ac);background:var(--ac-dim)}}
.calc-info-btn.active{{color:var(--ac);border-color:rgba(var(--ac-rgb),.4);background:var(--ac-dim)}}
.calc-card-sub{{font-size:12px;color:var(--mu);margin-bottom:10px;line-height:1.4}}
.calc-btn{{
  width:100%;padding:9px;border-radius:10px;border:1px solid rgba(var(--ac-rgb),.35);
  background:var(--ac-dim);color:var(--ac);
  font-family:inherit;font-size:13px;font-weight:600;letter-spacing:.01em;
  cursor:pointer;transition:all .15s;
}}
.calc-btn:hover{{background:rgba(var(--ac-rgb),.18);border-color:rgba(var(--ac-rgb),.55)}}
.calc-btn:active{{transform:scale(.98)}}
.calc-btn:disabled{{opacity:.55;cursor:wait}}

/* Explainer — collapsed by default; .open reveals it with an animated
   height transition. Rules are mono-caps headers + plain text bodies. */
.calc-explain{{
  max-height:0;overflow:hidden;
  transition:max-height .3s cubic-bezier(.4,0,.2,1),margin-top .2s;
  margin-top:0;
}}
.calc-card.open .calc-explain{{max-height:600px;margin-top:12px}}
.calc-rule{{padding-top:8px;margin-top:8px;border-top:1px solid var(--bd)}}
.calc-rule:first-child{{padding-top:0;margin-top:0;border-top:none}}
.calc-rule-h{{
  font-family:'Geist Mono','SF Mono',monospace;font-size:9px;
  letter-spacing:.08em;text-transform:uppercase;color:var(--mu);
  font-weight:600;margin-bottom:4px;
}}
.calc-rule-b{{font-size:12px;color:var(--tx2);line-height:1.5;display:flex;flex-direction:column;gap:3px}}
.calc-rule-b b{{color:var(--tx);font-weight:600}}
.calc-kv{{display:block}}
/* Intro line at the top of the explainer — sets the tone of trust before
   the rules drop. Slightly larger, normal weight, full contrast. */
.calc-intro{{
  font-size:12px;color:var(--tx2);line-height:1.5;
  padding-bottom:10px;margin-bottom:4px;border-bottom:1px solid var(--bd);
}}
/* Citation / source line — smaller, muted, italic. Sits at the bottom of
   each rule body so the verifiable source is always visible. */
.calc-meta{{
  font-size:10.5px;color:var(--mu);font-style:italic;
  margin-top:4px;letter-spacing:.005em;
}}
.calc-meta b{{font-style:normal;color:var(--tx2);font-weight:500}}
/* Inline aside — parenthetical context that doesn't compete with the rule. */
.calc-aside{{color:var(--mu);font-size:11px;font-weight:400}}
/* Macro section headers (Protein / Fat / Carbs) — anchor + one-liner. */
.calc-macro-row{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}}
.calc-macro-row b{{font-size:12px;color:var(--tx);min-width:54px}}
/* Sub-bullet under a macro header — indented, smaller. */
.calc-sub{{padding-left:14px;font-size:11.5px}}
.calc-foot{{
  font-size:10.5px;color:var(--mu);line-height:1.45;
  margin-top:12px;padding-top:10px;border-top:1px dashed var(--bd);
}}
.basics-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:9px}}
.basic-cell{{
  background:var(--sf);border:1px solid var(--bd);border-radius:12px;
  padding:9px 11px;position:relative;backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.basic-lbl{{
  font-family:'Geist Mono','SF Mono',monospace;font-size:8.5px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--mu);margin-bottom:3px;font-weight:500;
}}
.basic-val{{font-size:14px;font-weight:500;color:var(--tx);letter-spacing:-.01em}}
.basic-edit{{
  position:absolute;top:6px;right:6px;width:18px;height:18px;border-radius:5px;
  border:none;background:transparent;color:var(--mu);font-size:10px;cursor:pointer;
  opacity:.35;transition:opacity .15s;display:grid;place-items:center;
}}
.basic-cell:hover .basic-edit{{opacity:1}}
.basic-edit:hover{{background:var(--sf2);color:var(--tx)}}
@media(max-width:560px){{.basics-grid{{grid-template-columns:repeat(2,1fr)}}}}
/* Goals & targets — reuses .basic-cell tiles in two stacked grids:
   meta row (Goal + Goal weight, 2-up) and macros row (Cal/P/C/F, 4-up).
   Mobile collapses macros to 2-col, matching the Demographics grid. */
.goals-meta-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:7px;margin-bottom:7px}}
.macros-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:9px}}
@media(max-width:560px){{.macros-grid{{grid-template-columns:repeat(2,1fr)}}}}
/* Macro tile — same shell as .basic-cell, but the value gets a small color
   dot so the macro signal carries through at a glance (matches the macro
   tiles on the Day tab). Color is driven by --macro-c on the tile. */
.macro-cell .basic-val{{display:flex;align-items:baseline;gap:6px;font-variant-numeric:tabular-nums}}
.macro-cell .basic-val::before{{
  content:"";width:5px;height:5px;border-radius:50%;flex-shrink:0;
  background:var(--macro-c, var(--mu));align-self:center;margin-top:-1px;
}}
.macro-cell .basic-unit{{font-size:10.5px;color:var(--mu);font-weight:400;letter-spacing:.01em}}
/* Goal-pill cell — value renders as a colored pill on the goal-name tile so
   the cut/bulk/maintain/perf/health signal is visible without a separate dot. */
.goal-pill{{
  display:inline-flex;align-items:center;gap:5px;padding:2px 8px;
  border-radius:999px;font-size:12.5px;font-weight:600;line-height:1.4;
  color:var(--goal-c, var(--tx));
  background:color-mix(in oklch, var(--goal-c, var(--tx)) 14%, transparent);
  border:1px solid color-mix(in oklch, var(--goal-c, var(--tx)) 26%, transparent);
}}
/* Standard-skeleton extras: "waiting" dot for empty slots + value chips */
.slot-wait{{
  width:6px;height:6px;border-radius:50%;flex-shrink:0;align-self:center;
  background:#f0a500;opacity:.7;box-shadow:0 0 5px rgba(240,165,0,.5);
}}
.pf-learning{{
  font-size:11px;padding:8px 14px 9px;letter-spacing:.01em;
  border-top:1px solid rgba(220,160,40,.22);
  background:rgba(220,160,40,.07);
  color:#9a7830;
  display:flex;align-items:center;gap:6px;line-height:1.45;
}}
.pf-learn-dot{{
  width:5px;height:5px;border-radius:50%;background:#c49428;
  flex-shrink:0;opacity:.85;margin-top:1px;
}}
.pf-show-more{{
  width:100%;padding:8px 14px;background:none;border:none;
  border-top:1px solid var(--bd);color:var(--mu);font-size:12px;
  cursor:pointer;text-align:center;display:block;font-family:inherit;
  letter-spacing:.01em;transition:color .15s,background .15s;
}}
.pf-show-more:hover{{color:var(--tx);background:var(--sf2)}}
.pf-legend{{
  display:flex;flex-wrap:wrap;gap:6px 15px;margin:15px 2px 2px;
  font-size:10.5px;color:var(--mu);opacity:.7;line-height:1.4;
}}
.pf-legend span{{display:inline-flex;align-items:center;gap:5px}}
.pf-dot{{width:5px;height:5px;border-radius:50%;display:inline-block;flex-shrink:0}}
.pf-x{{font-size:9px;font-style:normal;opacity:.85}}
.chips{{display:flex;flex-wrap:wrap;gap:5px;justify-content:flex-end}}
.chip{{
  font-size:11.5px;font-weight:500;color:var(--tx2);background:var(--sf2);
  border:1px solid var(--bd);border-radius:7px;padding:3px 8px;line-height:1.35;
}}
/* AI read — labeled coaching insights (replaces the paragraph bio) */
.ai-read{{display:flex;flex-direction:column}}
.ai-read-row{{display:flex;gap:11px;padding:9px 0;border-bottom:1px solid var(--bd)}}
.ai-read-row:first-child{{padding-top:0}}
.ai-read-row:last-child{{border-bottom:none;padding-bottom:0}}
.ai-read-tag{{
  font-family:'Geist Mono','SF Mono',monospace;font-size:8.5px;letter-spacing:.13em;
  text-transform:uppercase;color:var(--ac);font-weight:600;min-width:42px;
  flex-shrink:0;padding-top:4px;
}}
.ai-read-txt{{font-size:13.5px;line-height:1.5;color:var(--tx)}}
.ai-pill{{
  font-family:'Geist Mono','SF Mono',monospace;font-size:8px;font-weight:600;
  letter-spacing:.09em;color:var(--ac);border:1px solid var(--ac);border-radius:4px;
  padding:1px 4px;vertical-align:middle;opacity:.75;
}}
.ai-bullets{{margin:0;padding-left:17px;display:flex;flex-direction:column;gap:8px}}
.ai-bullets li{{font-size:13.5px;line-height:1.5;color:var(--tx)}}
.ancrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:16px;
  backdrop-filter:blur(16px);box-shadow:var(--sh);margin-bottom:9px;transition:background .3s;
}}
[data-theme="dark"] .ancrd{{
  background:linear-gradient(135deg,rgba(59,130,246,.06),transparent 60%),var(--sf);
  border-color:rgba(59,130,246,.15);
}}
.antitle{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;color:var(--mu);font-weight:500;text-transform:uppercase;
  letter-spacing:.14em;margin-bottom:12px;
}}
.angrid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}}
@media(min-width:420px){{.angrid{{grid-template-columns:repeat(3,1fr)}}}}
.anitem{{background:var(--sf2);border-radius:12px;padding:12px;border:1px solid var(--bd);transition:background .3s}}
.anval{{font-family:'Instrument Serif','Times New Roman',serif;font-size:28px;font-weight:normal;line-height:1;letter-spacing:-.01em}}
.anlbl{{font-family:'Geist Mono','SF Mono',monospace;font-size:9.5px;color:var(--mu);margin-top:4px;font-weight:500;text-transform:uppercase;letter-spacing:.1em}}
.devrow{{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--bd)}}
.devrow:last-child{{border-bottom:none}}
.devname{{font-size:13px;font-weight:500;flex:1;color:var(--tx)}}
.devst{{font-family:'Geist Mono','SF Mono',monospace;font-size:11px;font-weight:500;letter-spacing:.04em}}
.devst.on{{color:var(--ac)}}
.devst.off{{color:var(--mu)}}

/* ── EXERCISE SETS ───────────────────────────────────────── */
.esets{{display:flex;flex-wrap:wrap;gap:4px;padding:4px 14px 10px;align-items:center}}
.eset-chip{{
  background:var(--sf2);border:1px solid var(--bd);border-radius:7px;
  padding:4px 9px;font-size:11px;font-weight:500;color:var(--tx2);
  font-family:'Geist Mono','SF Mono',monospace;
}}
.eset-chip b{{color:var(--ac)}}
.eset-wt{{font-size:11px;font-weight:600;color:var(--or);margin-right:3px}}

/* ── SHARE BUTTON ────────────────────────────────────────── */
.share-btn{{
  background:var(--sf2);border:1px solid var(--bd);color:var(--mu);
  padding:5px 10px;border-radius:9px;font-size:11px;font-weight:500;
  cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;
  gap:4px;transition:all .2s;flex-shrink:0;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.share-btn:hover{{border-color:var(--ac);color:var(--ac)}}
.share-btn:active{{transform:scale(.93)}}

/* ── INSIGHTS DETAILS ────────────────────────────────────── */
#insights-details summary{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:11px;font-weight:500;color:var(--mu);text-transform:uppercase;
  letter-spacing:.14em;margin:30px 0 0;display:flex;align-items:center;gap:10px;
  justify-content:space-between;
}}
#insights-details summary::-webkit-details-marker{{display:none}}
@media(max-width:940px){{#insights-details{{}} }}

/* ── MISC ────────────────────────────────────────────────── */
footer{{
  text-align:center;padding:16px 12px;color:var(--di);font-size:10px;
  position:relative;z-index:1;
  font-family:'Geist Mono','SF Mono',monospace;letter-spacing:.08em;text-transform:uppercase;
}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
.fade-in{{animation:fadeUp .3s ease}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.spin{{display:inline-block;animation:spin 1s linear infinite}}

/* ── PAGE HEADER ─────────────────────────────────────────── */
.pagehead{{
  position:sticky;top:0;z-index:30;
  display:flex;align-items:center;justify-content:space-between;
  gap:20px;padding:22px 0 14px;margin-bottom:6px;
  backdrop-filter:blur(20px) saturate(160%);
  -webkit-backdrop-filter:blur(20px) saturate(160%);
  background:var(--bg);
}}
.ph-title{{
  font-family:'Instrument Serif','Times New Roman',serif;
  font-size:28px;line-height:1.15;letter-spacing:-.01em;color:var(--tx);font-weight:400;
  display:inline-flex;align-items:baseline;gap:6px;
}}
.logo-arnie{{font-family:'Instrument Serif','Times New Roman',serif;color:var(--tx);font-weight:400}}
/* "OS" rendered as a small mono caps badge next to "Arnie" — matches
   the existing sidebar logo treatment (.logo-os). Reads as a product
   wordmark, not a tagline. */
.logo-os{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--mu);border:1px solid var(--bd);border-radius:5px;
  padding:2px 6px;line-height:1;vertical-align:.18em;font-weight:500;
}}
@media(max-width:940px){{.ph-title{{font-size:26px}}}}
@media(max-width:560px){{.ph-title{{font-size:24px}}}}
.ph-sub{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--mu);margin-top:6px;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap;
}}
.ph-dot{{color:var(--di)}}
/* Goal chip in the subtitle — same accent token as .ds-pill.on / .streak-chip. */
.ph-pill{{
  padding:2px 7px;border-radius:8px;font-size:9px;font-weight:600;letter-spacing:.06em;
  background:var(--ac-dim);color:var(--ac);
  border:1px solid rgba(var(--ac-rgb),.2);
  text-transform:uppercase;
}}
/* .ph-streak (inline ⚡ X-day streak in subtitle) removed — superseded
   by the .streak-chip in the top-right of .ph-actions. */
.ph-actions{{display:flex;gap:8px;align-items:center;flex-shrink:0}}
.ph-log-btn{{
  border:1px solid var(--bd);border-radius:10px;padding:0 13px;height:34px;font-size:13px;
  font-weight:500;color:var(--tx2);background:var(--sf2);
  cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:7px;
  white-space:nowrap;transition:border-color .15s,color .15s,background .15s;flex-shrink:0;
}}
.ph-log-btn:hover{{border-color:var(--ac);color:var(--ac);background:var(--sf3)}}
.ph-log-btn:active{{transform:scale(.95)}}

/* ── STATUS TOGGLES ──────────────────────────────────────── */
.toggles{{display:flex;gap:7px;flex-wrap:wrap;margin-top:16px;margin-bottom:14px}}
.toggle{{
  display:inline-flex;align-items:center;gap:7px;padding:7px 12px;
  border-radius:999px;border:1px solid var(--bd);background:var(--sf);
  color:var(--mu);font-size:12px;font-weight:600;
  font-family:inherit;transition:background .2s,border-color .2s;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.toggle.on{{
  border-color:rgba(var(--ac-rgb),.4);color:var(--tx);
  background:var(--ac-dim);
}}
.toggle.t-click{{cursor:pointer}}
.toggle.t-click:hover{{border-color:var(--bd2);color:var(--tx2)}}
.toggle .tcb{{
  width:15px;height:15px;border-radius:50%;border:1.5px solid var(--di);
  display:grid;place-items:center;flex-shrink:0;font-size:10px;line-height:1;color:transparent;
  background:var(--sf);transition:all .18s;
}}
.toggle.on .tcb{{
  border:none;color:#000;
  background:
    radial-gradient(circle at 38% 28%, rgba(255,255,255,.42) 0%, rgba(255,255,255,0) 55%),
    linear-gradient(145deg, rgba(var(--ac-rgb),1) 0%, rgba(var(--ac-rgb),.68) 100%);
  box-shadow:
    0 1.5px 0 rgba(255,255,255,.5) inset,
    0 4px 10px -2px rgba(var(--ac-rgb),.60),
    0 1px 3px rgba(0,0,0,.18);
}}
[data-theme="light"] .toggle.on .tcb{{color:#fff}}
.share-tgl{{cursor:pointer}}
.share-tgl:hover{{border-color:var(--ac);color:var(--ac)}}

/* ── LOG MODAL ───────────────────────────────────────────── */
.lm-overlay{{
  position:fixed;inset:0;z-index:200;
  background:rgba(0,0,0,.55);backdrop-filter:blur(8px);
  display:flex;align-items:center;justify-content:center;
  padding:20px;animation:fadeUp .18s ease;
}}
.lm-box{{
  background:var(--bg);border:1px solid var(--bd);border-radius:22px;
  width:100%;max-width:500px;overflow:hidden;
  box-shadow:0 28px 70px rgba(0,0,0,.55),0 0 0 1px rgba(255,255,255,.07);
  animation:slideUp .22s cubic-bezier(.2,.7,.2,1);
}}
@keyframes slideUp{{from{{opacity:0;transform:translateY(18px)}}to{{opacity:1;transform:none}}}}
.lm-head{{
  display:flex;align-items:center;justify-content:space-between;
  padding:20px 22px 0;
}}
.lm-title{{
  font-family:'Instrument Serif','Times New Roman',serif;
  font-size:22px;letter-spacing:-.01em;color:var(--tx);
}}
.lm-close{{
  width:30px;height:30px;border-radius:8px;border:1px solid var(--bd);
  background:var(--sf2);color:var(--mu);cursor:pointer;
  display:grid;place-items:center;font-size:16px;line-height:1;
  transition:all .15s;
}}
.lm-close:hover{{border-color:var(--bd2);color:var(--tx)}}
.lm-tabs{{
  display:grid;grid-template-columns:1fr 1fr;gap:8px;
  padding:16px 22px;
}}
.lm-tab{{
  padding:9px;border-radius:10px;border:1px solid var(--bd);
  background:var(--sf2);color:var(--mu);
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;letter-spacing:.1em;text-transform:uppercase;font-weight:500;
  cursor:pointer;transition:all .18s;
}}
.lm-tab.active{{
  background:var(--ac-dim);border-color:rgba(var(--ac-rgb),.4);
  color:var(--tx);
}}
[data-theme="dark"] .lm-tab.active{{box-shadow:0 0 12px rgba(var(--ac-rgb),.15)}}
.lm-body{{padding:0 22px 22px;display:flex;flex-direction:column;gap:12px}}
.lm-field{{display:flex;flex-direction:column;gap:5px}}
.lm-label{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--mu);font-weight:500;
}}
.lm-input{{
  background:var(--sf2);border:1px solid var(--bd);color:var(--tx);
  padding:12px 14px;border-radius:11px;font-size:14px;
  font-family:'Geist',ui-sans-serif,system-ui,sans-serif;
  width:100%;outline:none;letter-spacing:-.005em;
  transition:border-color .15s,box-shadow .15s;
}}
.lm-input::placeholder{{color:var(--di)}}
.lm-input:focus{{
  border-color:rgba(var(--ac-rgb),.5);
  box-shadow:0 0 0 3px rgba(var(--ac-rgb),.1);
}}
.lm-search-wrap{{position:relative}}
.lm-results{{
  position:absolute;top:calc(100% + 6px);left:0;right:0;z-index:10;
  background:var(--bg);border:1px solid var(--bd);border-radius:12px;
  overflow:hidden;max-height:260px;overflow-y:auto;
  box-shadow:0 12px 30px rgba(0,0,0,.3);
}}
.lm-result{{
  padding:11px 14px;cursor:pointer;border-bottom:1px solid var(--bd);
  transition:background .12s;
}}
.lm-result:last-child{{border-bottom:none}}
.lm-result:hover{{background:var(--sf2)}}
.lm-result-name{{
  font-size:14px;font-weight:500;color:var(--tx);line-height:1.3;
  font-family:'Geist',ui-sans-serif,system-ui,sans-serif;letter-spacing:-.005em;
}}
.lm-result-meta{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;color:var(--mu);margin-top:4px;letter-spacing:.04em;
}}
.lm-selected{{
  background:var(--sf2);border:1px solid var(--bd);
  border-radius:12px;padding:12px 14px;
}}
.lm-sel-name{{font-size:14px;font-weight:500;color:var(--tx);margin-bottom:6px}}
.lm-sel-macros{{
  display:flex;gap:12px;
  font-family:'Geist Mono','SF Mono',monospace;font-size:11px;
}}
.lm-sel-macros span{{color:var(--mu)}}
.lm-sel-macros b{{color:var(--tx2);font-weight:600}}
.lm-macro-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}
.lm-type-row{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.lm-type-btn{{
  padding:9px;border-radius:10px;border:1px solid var(--bd);
  background:var(--sf2);color:var(--mu);cursor:pointer;
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;letter-spacing:.08em;text-transform:uppercase;font-weight:500;
  transition:all .15s;
}}
.lm-type-btn.active{{
  background:var(--ac-dim);border-color:rgba(var(--ac-rgb),.4);color:var(--tx);
}}
.lm-submit{{
  background:var(--ac);border:none;border-radius:11px;
  padding:13px;width:100%;font-size:14px;font-weight:600;
  color:#000;cursor:pointer;font-family:inherit;
  transition:opacity .15s,transform .12s;margin-top:4px;
  box-shadow:0 4px 14px rgba(var(--ac-rgb),.35);
}}
[data-theme="light"] .lm-submit{{color:#fff}}
.lm-submit:hover{{opacity:.88;transform:translateY(-1px)}}
.lm-submit:active{{transform:scale(.98)}}
.lm-submit:disabled{{opacity:.45;cursor:not-allowed;transform:none}}
.lm-note{{font-size:12px;color:var(--mu);text-align:center}}
.lm-divider{{height:1px;background:var(--bd);margin:2px 0}}

/* ── Sidebar glass depth ─────────────────────────────────── */
[data-theme="dark"] .sidebar{{
  background:linear-gradient(180deg,rgba(10,14,22,.96),rgba(8,12,20,.90));
  border-right:1px solid rgba(255,255,255,.07);
  box-shadow:2px 0 24px rgba(0,0,0,.4);
}}

/* ── Dark mode card shadow ───────────────────────────────── */
[data-theme="dark"] .card,[data-theme="dark"] .icrd,
[data-theme="dark"] .ccrd,[data-theme="dark"] .goal-card,
[data-theme="dark"] .stat-tile,[data-theme="dark"] .lcrd,
[data-theme="dark"] .ancrd,[data-theme="dark"] .infocrd,
[data-theme="dark"] .dev-card{{
  box-shadow:0 2px 8px rgba(0,0,0,.28);
}}
[data-theme="dark"] .pf-learning{{
  color:#c4a050;background:rgba(220,160,40,.1);border-top-color:rgba(220,160,40,.28);
}}
[data-theme="dark"] .pf-learn-dot{{background:#d4b040}}

/* ═══ MOBILE TYPOGRAPHY + LAYOUT FIXES ═════════════════════ */
@media(max-width:560px){{
  /* Pagehead: hide icon-only buttons EXCEPT the refresh button — it's the
     fastest way to re-pull today's log on mobile (pull-to-refresh isn't
     reliable inside a scrolled tab panel). Sized to sit next to the
     streak chip without crowding it. */
  .pagehead .hbtn{{display:none}}
  .pagehead #refresh-btn{{display:flex;width:30px;height:30px;border-radius:9px;font-size:13px}}
  .pagehead{{padding:10px 0 6px;gap:10px;align-items:center;margin-bottom:4px}}
  .ph-title{{font-size:22px!important;letter-spacing:-.01em}}
  .ph-sub{{font-size:12px;margin-top:3px;gap:8px}}
  .ph-actions{{gap:5px}}
  .ph-log-btn{{padding:0 14px;height:34px;font-size:13px;border-radius:9px}}
  /* Section labels */
  .stitle{{margin:16px 0 8px;font-size:10px;letter-spacing:.11em}}
  /* Cards — two-tier radius: big content cards 14px, small cells 12px (uniform) */
  .cval{{font-size:28px}}
  .clbl{{font-size:9.5px;margin-bottom:5px;letter-spacing:.09em}}
  .card,.lcrd,.infocrd,.ancrd,.pref-card,.goal-card,.stat-tile,.whoop-stat{{border-radius:14px}}
  .basic-cell,.tcell,.anitem{{border-radius:12px}}
  .card{{padding:14px}}
  .heat-wrap{{padding:14px}}
  .macro-ring-wrap{{padding:14px;gap:14px}}
  .csub{{font-size:12px}}
  /* Date nav */
  .dchip{{padding:6px 11px;font-size:11px}}
  .darr{{width:34px;height:34px;border-radius:9px}}
  .dnav{{gap:5px;margin-bottom:12px}}
  /* Still learning */
  #learn-wrap{{margin-top:10px!important}}
  .lrn-card{{padding:9px 12px}}
  .lrn-top{{gap:8px;margin-bottom:6px}}
  /* Today counters — quiet label, clear weighted number, even bars.
     Macro number drops a notch (700 → 600) on mobile — the desktop
     weight reads heavier on phones than intended at smaller pixel
     densities; 600 keeps the value as the dominant element without
     shouting. */
  /* Compact mobile macro layout — label on top, the big number and the
     "/ 180g (67%)" fraction share one baseline-aligned row so the card
     halves vertically. The .mc-num size is preserved; .mc-sub keeps its
     small fraction sizing and just slides next to the number. */
  .macro-cell{{
    padding:10px 12px;
    display:grid;
    grid-template-areas:
      "label label"
      "num   sub"
      "bar   bar";
    grid-template-columns:auto 1fr;
    column-gap:8px;
    align-items:baseline;
  }}
  .mc-label{{grid-area:label;font-size:9px;letter-spacing:.08em;margin-bottom:2px;color:var(--mu);font-weight:500}}
  .mc-num{{grid-area:num;font-size:26px;font-weight:600;line-height:1.1}}
  .mc-sub{{grid-area:sub;font-size:10px;margin-top:0;color:var(--mu);
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  .mc-bar{{grid-area:bar;margin-top:6px;height:3px}}
  /* Coach insights — hide timestamp on narrow screens, tighten banner */
  .ins-time{{display:none}}
  .ins-banner{{padding:10px 12px;gap:8px}}
  .ins-spark{{width:26px;height:26px;border-radius:7px}}
  /* Toggles */
  .toggle{{padding:7px 11px;font-size:12px;gap:6px}}
  .toggles{{gap:6px;margin-bottom:14px}}
  /* Food rows */
  .eg-row{{padding:11px 13px}}
  /* Stats */
  .stat-num{{font-size:38px}}
  .stat-lbl{{font-size:10px}}
  .stat-tile{{padding:18px 10px;border-radius:14px}}
  /* Goal */
  .goal-lbs{{font-size:32px}}
  .goal-title{{font-size:21px}}
  /* Food — readable sizes on phones. Earlier passes over-shrunk these;
     reverted toward the desktop ladder. .lname stays at the desktop
     13.5px (font is fine on phone too — long meal names get the
     compactness from the 8px row padding, not from cramming the type). */
  .ficon{{width:38px;height:38px;font-size:20px;border-radius:10px}}
  .lname{{font-size:13.5px;line-height:1.3;gap:6px}}
  .lmeta{{font-size:11px}}
  .lcal{{font-size:12px}}
  .lcal-unit{{font-size:9.5px}}
  .est-tag{{font-size:8px}}
  /* Insights */
  .itxt{{font-size:14px;line-height:1.5}}
  /* Profile */
  .anval{{font-size:22px}}
  /* Profile info rows */
  .inrow{{padding:11px 14px;gap:10px;align-items:flex-start}}
  .inlbl{{font-size:12px;min-width:80px;padding-top:1px;flex-shrink:0}}
  .inrow-right{{flex:1;display:flex;align-items:flex-start;justify-content:flex-end;gap:6px;min-width:0}}
  .inval{{font-size:13px;text-align:right;word-break:break-word;flex:1;min-width:0}}
  .inrow-edit{{width:20px;height:20px;border-radius:5px;font-size:9px;flex-shrink:0;opacity:.45;border-color:transparent;background:transparent}}
  .inrow-edit:hover{{opacity:1;border-color:var(--bd)!important;background:var(--sf2)!important}}
  /* Badges */
  .goal-badge,.coach-badge{{font-size:9.5px;padding:3px 8px;letter-spacing:.05em}}
  /* Profile grid */
  .profile-grid{{grid-template-columns:1fr;gap:12px}}
  /* Science grid: 2 col on mobile */
  .angrid{{grid-template-columns:repeat(2,1fr)}}
  .anval{{font-size:20px}}
  .anlbl{{font-size:9px}}
  .dev-grid{{grid-template-columns:repeat(2,1fr);gap:6px}}
  /* Main padding */
  .main-inner{{padding:0 18px 90px}}
}}

/* ── Medium breakpoint ───────────────────────────────────── */
@media(max-width:740px) and (min-width:561px){{
  .ph-title{{font-size:23px!important}}
  .cval{{font-size:30px}}
  .stitle{{font-size:10.5px}}
}}

/* ── Bottom nav upgrade ──────────────────────────────────── */
.bottomnav{{
  padding:10px 16px calc(12px + env(safe-area-inset-bottom));
}}
.bn-item{{font-size:9px;gap:4px;padding:6px 0 4px}}
[data-theme="dark"] .bn-item.active .bn-ico{{
  filter:drop-shadow(0 0 6px var(--ac));
}}
.bn-item.active .bn-ico{{transform:translateY(-2px)}}

/* ── Pull-to-feel: subtle press on cards ─────────────────── */
.card:active,.stat-tile:active,.goal-card:active{{
  transform:scale(.985)!important;
}}

/* ── 5-day trend strip ───────────────────────────────────── */
/* 5-day trend cells — pre-edit production styling, restored verbatim
   from 8021b58. Muted by design: --sf2 surface, --tx2 values (not full
   contrast), all arrows in --mu (no green/orange), no mono font on the
   label. The strip reads as quiet ambient context, never competing
   with the macro strip above for attention. */
.trend-strip{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:4px}}
.tcell{{
  background:var(--sf2);border:1px solid var(--bd);border-radius:12px;
  padding:10px 12px;display:flex;flex-direction:column;gap:2px;
}}
.tc-lbl{{font-size:9px;letter-spacing:.06em;text-transform:uppercase;color:var(--mu);font-weight:500}}
.tc-val{{font-size:16px;font-weight:600;color:var(--tx2);line-height:1.1}}
.tc-sub{{font-size:10px;color:var(--mu);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.tc-up{{color:var(--mu)}} .tc-dn{{color:var(--mu)}} .tc-fl{{color:var(--di)}}
.tc-up{{color:var(--mu)}} .tc-dn{{color:var(--mu)}} .tc-fl{{color:var(--di)}}

/* ── Arnie's learning progress ───────────────────────────── */
.lrn-card{{background:var(--sf2);border:1px solid var(--bd);border-radius:14px;padding:11px 14px}}
.lrn-top{{display:flex;align-items:center;gap:9px;margin-bottom:8px}}
.lrn-label{{font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--di);white-space:nowrap}}
.lrn-pct{{font-size:10px;color:var(--di);white-space:nowrap;letter-spacing:.02em}}
.learn-bar{{flex:1;height:2px;border-radius:2px;background:var(--sf3);overflow:hidden}}
.learn-fill{{height:100%;background:var(--ac);border-radius:2px;transition:width .5s ease}}
.learn-chips{{display:flex;flex-wrap:wrap;gap:3px 10px}}
.learn-chip{{font-size:10px;color:var(--mu);transition:color .2s}}
.learn-chip.done{{color:var(--tx2)}}

/* ── "Arnie learned" live ticker ─────────────────────────────
   No card, no chrome — a single line that continuously rolls through
   real things Arnie has picked up (from /api/profile custom attributes).
   The verb AND the fact change every turn, so it reads fresh each time.
   A breathing orb is the only persistent ornament; the motion carries it.
   Tap → the deeper learned view. */
.kii-card{{
  display:flex;align-items:center;gap:10px;
  margin-top:16px;cursor:pointer;-webkit-tap-highlight-color:transparent;
  font-size:14px;line-height:1.4;min-width:0;
}}
.kii-card:active{{opacity:.6}}
/* breathing orb — the "thinking / learning" pulse */
.kii-orb{{position:relative;width:7px;height:7px;flex-shrink:0}}
.kii-orb i{{
  position:absolute;inset:0;border-radius:50%;background:var(--ac);
  box-shadow:0 0 8px rgba(var(--ac-rgb),.9);
  animation:kiiBreath 2.4s ease-in-out infinite;
}}
.kii-orb::after{{
  content:'';position:absolute;inset:0;border-radius:50%;
  border:1.5px solid rgba(var(--ac-rgb),.5);
  animation:kiiPing 2.4s ease-out infinite;
}}
@keyframes kiiBreath{{0%,100%{{transform:scale(.8);opacity:.85}}50%{{transform:scale(1.15);opacity:1}}}}
@keyframes kiiPing{{0%{{transform:scale(.5);opacity:.8}}70%{{opacity:0}}100%{{transform:scale(2.5);opacity:0}}}}
/* the rolling line — masked viewport. Lines are centered (translateY(-50%))
   so a wrapped two-line fact stays balanced against the orb; the roll
   keyframes animate around that centered rest position. */
.kii-roll{{position:relative;flex:1;min-width:0;height:1.4em;overflow:hidden;
  transition:height .45s cubic-bezier(.22,1,.36,1)}}
.kii-line{{
  position:absolute;left:0;top:50%;width:100%;transform:translateY(-50%);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  color:var(--mu);font-weight:500;
}}
.kii-line .kii-v{{ /* rotating verb */
  font-style:normal;font-weight:700;
  background:linear-gradient(90deg,var(--ac),var(--pu));
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
}}
.kii-line .kii-h{{color:var(--tx2);font-weight:600}}   /* the "what" (label) */
.kii-line .kii-val{{color:var(--tx);font-weight:600}}  /* the specific value */
.kii-line.enter{{animation:kiiRollIn .55s cubic-bezier(.22,1,.36,1) both}}
.kii-line.exit{{animation:kiiRollOut .42s cubic-bezier(.55,0,.67,0) both}}
@keyframes kiiRollIn{{
  0%{{opacity:0;transform:translateY(calc(-50% + 1.05em));filter:blur(5px)}}
  100%{{opacity:1;transform:translateY(-50%);filter:blur(0)}}
}}
@keyframes kiiRollOut{{
  0%{{opacity:1;transform:translateY(-50%);filter:blur(0)}}
  100%{{opacity:0;transform:translateY(calc(-50% - 1.05em));filter:blur(5px)}}
}}
@media(prefers-reduced-motion:reduce){{
  .kii-orb i,.kii-orb::after{{animation:none}}
  .kii-line.enter,.kii-line.exit{{animation-duration:.001s}}
}}
/* On phones a single ellipsised line hides the long facts — let it wrap to
   three lines instead. _kiiFit() sizes the roll viewport to the actual line
   height (snug for short facts, taller for long ones); the orb stays centered
   against it. */
@media(max-width:560px){{
  .kii-card{{font-size:13px;margin-top:14px;gap:9px;align-items:center}}
  .kii-line{{
    white-space:normal;
    display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;
  }}
}}

/* ── Settings preference cards (profile tab) ─────────────── */
.pref-card{{background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:13px 16px;margin-bottom:8px;box-shadow:var(--sh)}}
.pref-row{{display:flex;align-items:center;justify-content:space-between}}
.pref-lbl{{font-size:13px;color:var(--tx2);font-weight:400}}
.pref-toggle{{position:relative;display:inline-block;width:38px;height:21px;flex-shrink:0}}
.pref-toggle input{{opacity:0;width:0;height:0}}
.pref-slider{{position:absolute;inset:0;background:var(--sf3);border-radius:21px;cursor:pointer;transition:.25s}}
.pref-slider::before{{content:'';position:absolute;height:15px;width:15px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.25s}}
.pref-toggle input:checked+.pref-slider{{background:var(--ac)}}
.pref-toggle input:checked+.pref-slider::before{{transform:translateX(17px)}}
.pref-range{{-webkit-appearance:none;appearance:none;width:100%;height:3px;border-radius:3px;background:var(--sf3);accent-color:var(--ac);cursor:pointer;outline:none;margin:0}}
.pref-range::-webkit-slider-thumb{{-webkit-appearance:none;appearance:none;width:15px;height:15px;border-radius:50%;background:var(--ac);cursor:pointer;border:none}}
.pref-range::-moz-range-thumb{{width:15px;height:15px;border-radius:50%;background:var(--ac);cursor:pointer;border:none}}
.pref-ticks{{display:flex;justify-content:space-between;margin-top:8px}}
.pref-tick{{font-size:10px;color:var(--mu);flex:1;text-align:center;transition:.18s}}
.pref-tick:first-child{{text-align:left}}
.pref-tick:last-child{{text-align:right}}
.pref-tick.active{{color:var(--ac);font-weight:600}}
.pref-hint{{font-size:11px;color:var(--mu);margin-top:7px}}

/* ── COACHING PREFERENCES SUB-LABELS ──────────────────────
   Title row that sits above each .pref-card in the Coaching
   preferences section. Title Case Geist sans (not the mono
   uppercase .settings-sub used by Demographics/Goals) so the
   labels read at a glance as proper sub-section headers. Flex
   container lets Reminders dock its on/off toggle on the right
   while Logging / Coaching Style have just the label. */
.cp-row{{
  display:flex;align-items:center;justify-content:space-between;
  margin:18px 2px 8px;gap:10px;
}}
.cp-row:first-of-type{{margin-top:10px}}
.cp-label{{
  font-size:13px;font-weight:600;letter-spacing:-.012em;
  color:var(--tx);line-height:1.2;
}}
</style>
</head>
<body>
<div class="shell">

<!-- SIDEBAR -->
<aside class="sidebar">
  <div>
    <div class="sb-logo">Arnie<span class="logo-os">OS</span></div>
    <nav class="sidenav">
      <div class="nav-section-lbl">Dashboard</div>
      <button class="navitem active" id="nav-day" onclick="switchTab('day')">
        <span class="ni-ico"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4.5" width="18" height="16.5" rx="3"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><circle cx="12" cy="15" r="1.8" fill="currentColor" stroke="none"/></svg></span>
        <span class="ni-lbl">Daily</span><span class="ni-meta">Today</span>
      </button>
      <button class="navitem" id="nav-week" onclick="switchTab('week')">
        <span class="ni-ico"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 16l5-5 4 4 8-9"/><path d="M16 6h5v5"/><path d="M3 21h18" opacity=".4"/></svg></span>
        <span class="ni-lbl">Trends</span><span class="ni-meta">30 days</span>
      </button>
      <button class="navitem" id="nav-profile" onclick="switchTab('profile')">
        <span class="ni-ico"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.2 4-6.5 8-6.5s8 2.3 8 6.5"/></svg></span>
        <span class="ni-lbl">Client</span><span class="ni-meta">Profile</span>
      </button>
      <button class="navitem" id="nav-brain" onclick="switchTab('brain')">
        <!-- Anatomical brain silhouette (Lucide-derived): scalloped gyri at
             the top edges read as "brain" at small sizes, central divide
             marks the hemispheres, and a softly pulsing core dot mirrors
             the constellation hub inside the Brain tab. -->
        <span class="ni-ico"><svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>
          <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>
          <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" opacity=".55"/>
          <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none">
            <animate attributeName="r" values="1.5;2.2;1.5" dur="2.6s" repeatCount="indefinite"/>
            <animate attributeName="opacity" values="1;.55;1" dur="2.6s" repeatCount="indefinite"/>
          </circle>
        </svg><span class="brain-pending-dot" aria-hidden="true"></span></span>
        <span class="ni-lbl">Brain</span><span class="ni-meta">Learning</span>
      </button>
    </nav>
  </div>
  <div class="sb-foot">
    <button class="navitem" id="nav-theme" onclick="toggleTheme()">
      <span class="ni-ico" id="sb-theme-ico"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/></svg></span>
      <span class="ni-lbl" id="sb-theme-lbl">Light mode</span>
    </button>
    <div class="sb-user" id="sb-user" style="display:none;cursor:pointer" onclick="switchTab('profile')" title="View profile">
      <div class="sb-avatar"></div>
      <div><div class="sb-name" id="sb-name"></div><div class="sb-goal" id="sb-goal-lbl"></div></div>
    </div>
  </div>
</aside>

<!-- MAIN -->
<div class="main">
<div class="main-inner">

<div class="pagehead">
  <div>
    <div class="ph-title" id="ph-title"></div>
    <div class="ph-sub" id="ph-sub"></div>
  </div>
  <div class="ph-actions">
    <!-- Streak chip — hidden by default; renderStreakChip() reveals when
         profile.streak_days ≥ 3. Tap surfaces a brief toast in production. -->
    <div class="streak-chip" id="streak-chip" style="display:none" onclick="handleStreakTap()" title="Logging streak">
      <svg class="streak-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>
      </svg>
      <span class="streak-num" id="streak-num">0</span>
      <span class="streak-unit">d</span>
    </div>
    <!-- Chat button removed from header — Arnie chat lives in Telegram /
         iMessage; the dashboard surface is read-only + edit-in-place. The
         existing toggleChatWidget() + .cw-panel remain in the file but
         are no longer reachable from the header. -->
    <button class="hbtn" id="theme-btn" onclick="toggleTheme()" title="Toggle theme">&#9790;</button>
    <button class="hbtn" id="refresh-btn" onclick="refreshCurrent(this)" title="Refresh today's data">&#8635;</button>
  </div>
</div>

<div id="app-load">Loading your data&hellip;</div>

  <!-- DAY TAB -->
  <div class="tab-panel active" id="panel-day">

    <!-- DATE NAV -->
    <div class="dnav">
      <button class="darr" id="date-prev" onclick="navDate(-1)" aria-label="Previous day">&#8249;</button>
      <div class="dscroll" id="date-chips"></div>
      <button class="darr" id="date-next" onclick="navDate(1)"  aria-label="Next day">&#8250;</button>
    </div>

    <!-- "ARNIE LEARNED" LIVE TICKER — placed at the very top of the Day tab
         (first thing below the date nav) for maximum attention. One line that
         continuously rolls through real learned facts (from /api/profile custom
         attributes via initLearnReel). Hidden until there are ≥3 facts, so
         brand-new users see the learning-progress card below instead. Taps
         through to the deeper learned view. -->
    <div class="kii-card" id="kii-card" style="display:none"
         role="button" tabindex="0"
         onclick="openLearnReel()" title="What Arnie's picked up about you">
      <span class="kii-orb"><i></i></span>
      <span class="kii-roll" id="kii-roll"><span class="kii-line" id="kii-line"></span></span>
    </div>

    <!-- ARNIE'S LEARNING — shown only for new users, hides at 100% -->
    <div id="learn-wrap" style="display:none;margin-top:12px">
      <div class="lrn-card">
        <div class="lrn-top">
          <span class="lrn-label">Arnie is learning</span>
          <div class="learn-bar"><div class="learn-fill" id="learn-fill" style="width:0%"></div></div>
          <span id="learn-pct" class="lrn-pct"></span>
        </div>
        <div class="learn-chips" id="learn-list"></div>
      </div>
    </div>

    <!-- WEIGHT MODULE — cut/bulk only; hidden by JS otherwise.
         Whole module is one tap target — click anywhere to open the inline
         log form. Pending dot pulses next to the WEIGHT label when today has
         no weigh-in. Form interactions stopPropagation so they don't re-toggle. -->
    <div class="weight-module" id="weight-module"
         onclick="toggleWeightLogForm(event)"
         role="button" tabindex="0"
         style="display:none;margin-top:16px"
         title="Tap to log today's weight">
      <span class="wm-check" id="wm-check" aria-hidden="true">&#10003; logged</span>
      <div class="wm-row">
        <div class="wm-stack-l">
          <div class="wm-label-row">
            <span class="wm-pending-dot" id="wm-pending-dot" aria-hidden="true"></span>
            <span class="wm-label">Weight</span>
          </div>
          <div><span class="wm-num" id="wm-val">&mdash;</span><span class="wm-unit" id="wm-unit">lbs</span></div>
        </div>
        <div class="wm-stack-r">
          <div class="wm-delta down" id="wm-delta">
            <span class="wm-delta-strong"><span id="wm-delta-arrow">→</span> <span id="wm-delta-val">0.0 lbs</span></span> from start
          </div>
          <div class="wm-sub" id="wm-sub"></div>
        </div>
      </div>
      <div class="wm-bar" id="wm-bar-wrap"><div class="wm-fill" id="wm-fill" style="width:0%"></div></div>
      <div class="wm-logform" id="wm-logform" onclick="event.stopPropagation()">
        <input class="wm-logform-inp" id="wm-logform-val" type="number"
               step="0.1" min="20" max="900" inputmode="decimal" placeholder="weight"
               onclick="event.stopPropagation()">
        <div class="wm-unit-toggle" role="tablist" aria-label="Unit">
          <button type="button" id="wm-unit-lbs" class="active"
                  onclick="event.stopPropagation();setWeightLogUnit('lbs')">lbs</button>
          <button type="button" id="wm-unit-kg"
                  onclick="event.stopPropagation();setWeightLogUnit('kg')">kg</button>
        </div>
        <button class="wm-logform-save" id="wm-logform-save"
                onclick="event.stopPropagation();submitWeightLog()" type="button">Save</button>
      </div>
    </div>

    <!-- MACRO HEADER + Consumed/Remaining toggle -->
    <div class="macro-header" style="margin-top:16px">
      <div class="macro-header-lbl">Macros</div>
      <button class="macro-toggle-btn" id="macro-toggle" onclick="toggleMacroView()" type="button">
        <span class="macro-toggle-dot"></span>
        <span id="macro-toggle-lbl">Consumed</span>
      </button>
    </div>

    <!-- MACRO STRIP -->
    <div class="macro-strip" style="margin-top:0">
      <div class="macro-cell">
        <div class="mc-label">Calories</div>
        <div class="mc-num" id="cal-val">&mdash;</div>
        <div class="mc-sub" id="cal-sub"></div>
        <div class="mc-bar"><div class="mc-fill" id="cal-bar" style="background:var(--ac);width:0%"></div></div>
      </div>
      <div class="macro-cell">
        <div class="mc-label">Protein</div>
        <div class="mc-num" id="pro-val">&mdash;</div>
        <div class="mc-sub" id="pro-sub"></div>
        <div class="mc-bar"><div class="mc-fill" id="pro-bar" style="background:var(--bl);width:0%"></div></div>
      </div>
      <div class="macro-cell">
        <div class="mc-label">Carbs</div>
        <div class="mc-num" id="carb-val">&mdash;</div>
        <div class="mc-sub" id="carb-sub"></div>
        <div class="mc-bar"><div class="mc-fill" id="carb-bar" style="background:var(--or);width:0%"></div></div>
      </div>
      <div class="macro-cell">
        <div class="mc-label">Fats</div>
        <div class="mc-num" id="fat-val">&mdash;</div>
        <div class="mc-sub" id="fat-sub"></div>
        <div class="mc-bar"><div class="mc-fill" id="fat-bar" style="background:var(--ye);width:0%"></div></div>
      </div>
    </div>

    <!-- ACTION TILES — Insights · Share are always shown. Workout · Cardio ·
         Water appear only when logged for the viewed day (renderDayTab toggles
         them via _setActivityTile), acting as "✓ logged" confirmation chips
         rather than permanent nudges. On mobile each spans full-width. -->
    <div class="action-tiles" id="action-tiles" style="margin-top:10px">
      <button class="atile insights-tile" id="tile-insights" onclick="handleInsightsTile()" type="button">
        <svg class="atile-ico" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M8 1.4l1.1 3.2 3.2 1.1-3.2 1.1L8 10l-1.1-3.2L3.7 5.7l3.2-1.1z"/>
          <path d="M12.6 9.4l.55 1.45 1.45.55-1.45.55-.55 1.45-.55-1.45L10.6 11.4l1.45-.55z" opacity=".75"/>
        </svg>
        <span class="atile-lbl">Insights<span class="atile-ai-tag">AI</span></span>
        <span class="atile-state" id="tile-insights-state"></span>
      </button>
      <button class="atile" id="tile-share" onclick="shareDay()" type="button">
        <svg class="atile-ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M8 2v9M5 5l3-3 3 3M3 11v2a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-2"/>
        </svg>
        <span class="atile-lbl">Share day</span>
      </button>
      <button class="atile" id="tile-workout" onclick="openLogActivity('strength')" type="button" style="display:none">
        <svg class="atile-ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M3 6v4M13 6v4M5 5v6M11 5v6M1 8h2M13 8h2"/>
        </svg>
        <span class="atile-lbl">Workout</span>
        <span class="atile-state" id="tile-workout-state">—</span>
      </button>
      <button class="atile" id="tile-cardio" onclick="openLogActivity('cardio')" type="button" style="display:none">
        <svg class="atile-ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="11" cy="3" r="1.5"/>
          <path d="M5 14l2-4 2 2 3-4M5 9l-3-2"/>
        </svg>
        <span class="atile-lbl">Cardio</span>
        <span class="atile-state" id="tile-cardio-state">—</span>
      </button>
      <button class="atile full" id="tile-water" style="display:none" type="button">
        <svg class="atile-ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M8 2l3.5 5.5a4.2 4.2 0 1 1-7 0L8 2z"/>
        </svg>
        <span class="atile-lbl">Water</span>
        <span class="atile-state" id="tile-water-state"></span>
      </button>
    </div>

    <!-- AI INSIGHTS — inline expanding panel triggered by the Insights
         action tile above. The old standalone banner header is gone:
         the Insights tile IS the banner now (cleaner — no redundancy).
         Body retains #ins-preview-day + #ins-time-day + #insights-card
         IDs unchanged so the existing fetch/refresh/streaming logic in
         loadInsights / toggleInsights / _stampInsTime keeps working. -->
    <!-- AI INSIGHTS panel: collapsed by default, expanded by the Insights
         action tile via handleInsightsTile()/toggleInsights('day'). The
         meta header (Coach Insights · timestamp · refresh) is OUTSIDE
         #insights-card because renderInsights overwrites that node's
         innerHTML when content streams in. -->
    <div class="insights" id="ins-day" style="margin-top:0">
      <div class="ins-body">
        <div class="ins-panel-wrap">
          <div class="ins-meta">
            <span>Coach Insights</span>
            <span id="ins-time-day"></span>
            <span class="ins-refresh" onclick="refreshInsights()" title="Refresh">&#8635;</span>
          </div>
          <div id="ins-preview-day" style="display:none"></div>
          <div class="icrd fade-in" id="insights-card"><div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div></div>
        </div>
      </div>
    </div>

    <!-- FOOD -->
    <div class="log-section" id="food-section">
      <div class="stitle spaced log-section-hd" onclick="toggleLogSection('food')">
        <span>Food <span id="food-log-count" style="font-weight:400;opacity:.7"></span></span>
        <div style="display:flex;align-items:center;gap:6px">
          <button class="log-chevron" id="food-chevron" title="Collapse">&#8249;</button>
          <button class="add-toggle" id="food-toggle" onclick="event.stopPropagation();toggleAddForm('food')" title="Add food">+</button>
        </div>
      </div>
      <div class="log-section-body" id="food-section-body">
        <div class="add-card" id="food-form" style="display:none">
          <input class="add-inp" id="food-name" placeholder="Food name (e.g. chicken breast)" autocomplete="off">
          <input class="add-inp" id="food-qty" placeholder="Portion (e.g. 200g, 1 cup)">
          <div class="add-macros">
            <div class="add-mac-field"><label>Cal</label><input type="number" id="food-cal" min="0" inputmode="numeric" placeholder="0"></div>
            <div class="add-mac-field"><label>P (g)</label><input type="number" id="food-pro" min="0" inputmode="decimal" placeholder="0"></div>
            <div class="add-mac-field"><label>C (g)</label><input type="number" id="food-carb" min="0" inputmode="decimal" placeholder="0"></div>
            <div class="add-mac-field"><label>F (g)</label><input type="number" id="food-fat" min="0" inputmode="decimal" placeholder="0"></div>
          </div>
          <button class="add-submit" id="food-submit" onclick="submitFoodInline()">Save food</button>
        </div>
        <div class="lcrd" id="food-log"><div class="lempty">Loading&hellip;</div></div>
        <!-- EST legend — footnote at the END of the food log. Explains the
             est pill rendered next to estimated food entries. Hidden by
             default; renderDayTab toggles it visible only when at least
             one item is estimated, so users never see a legend with no
             referent. Top-dashed border + muted opacity reads as footnote
             rather than header. -->
        <div class="est-legend" id="est-legend" style="display:none">
          <span id="est-legend-est" style="display:none;align-items:center;gap:6px">
            <span class="est-tag est-tag-static">est</span>
            <span class="est-legend-txt">= Arnie's best guess. Tap a row to edit.</span>
          </span>
          <span id="est-legend-photo" style="display:none;align-items:center;gap:6px">
            <span class="photo-tag" style="opacity:.85">&#128247;</span>
            <span class="est-legend-txt">= logged from a photo.</span>
          </span>
        </div>
      </div>
    </div>

    <!-- WORKOUTS -->
    <div class="log-section" id="ex-section">
      <div class="stitle spaced log-section-hd" onclick="toggleLogSection('ex')">
        <span>Workouts</span>
        <div style="display:flex;align-items:center;gap:6px">
          <button class="log-chevron" id="ex-chevron" title="Collapse">&#8249;</button>
          <button class="add-toggle" id="ex-toggle" onclick="event.stopPropagation();toggleAddForm('ex')" title="Add workout">+</button>
        </div>
      </div>
      <div class="log-section-body" id="ex-section-body">
        <div class="add-card" id="ex-form" style="display:none">
          <input class="add-inp" id="ex-name" placeholder="Exercise (e.g. bench press, 5k run)" autocomplete="off">
          <div class="add-macros">
            <div class="add-mac-field"><label>Sets</label><input type="number" id="ex-sets" min="1" inputmode="numeric" placeholder="—"></div>
            <div class="add-mac-field"><label>Reps</label><input type="text" id="ex-reps" placeholder="—"></div>
            <div class="add-mac-field"><label>lbs</label><input type="number" id="ex-wt" min="0" inputmode="decimal" placeholder="—"></div>
            <div class="add-mac-field"><label>Min</label><input type="number" id="ex-dur" min="0" inputmode="numeric" placeholder="—"></div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;padding:8px 14px 2px;font-size:13px;color:var(--mu)">
            <input type="checkbox" id="ex-cardio" style="width:15px;height:15px;accent-color:var(--ac)">
            <label for="ex-cardio">Cardio</label>
          </div>
          <button class="add-submit" id="ex-submit" onclick="submitExerciseInline()">Save workout</button>
        </div>
        <div class="lcrd" id="ex-log"><div class="lempty">Loading&hellip;</div></div>
      </div>
    </div>

    <!-- WHOOP / APPLE HEALTH — bottom of day, only when connected. Title is
         the active device name (Whoop / Apple Health) via #health-mod-title.
         Extra top margin separates the module from the workout log above it
         so the wearable data reads as its own zone of the day. -->
    <div id="whoop-module" style="display:none;margin-top:32px">
      <div class="stitle spaced">
        <span style="display:inline-flex;align-items:center"><span id="health-brand" style="display:inline-flex;margin-right:7px"></span><span id="health-mod-title">Whoop</span> <span id="whoop-date" style="font-family:'Geist Mono','SF Mono',monospace;font-weight:400;opacity:.6;font-size:9px;letter-spacing:.04em;margin-left:6px"></span></span>
        <button class="add-toggle" id="whoop-sync-btn" onclick="syncWhoop()" title="Sync" style="font-size:15px;font-family:inherit">&#8635;</button>
      </div>
      <div id="whoop-grid"></div>
    </div>

  </div><!-- /panel-day -->

  <!-- WEEK TAB — refined (minimal).
       Period chips → quiet one-liner → AI banner → charts → goal card.
       The charts are the trends; the one-liner is the takeaway; the AI
       banner is the qualitative read. No headline grid, no heatmap, no
       stats tiles — the surface stays calm. -->
  <div class="tab-panel" id="panel-week">

    <!-- PERIOD NAV — 7 / 30 / 90 day chips. setTrendsPeriod() reslices
         every downstream renderer; the date-range meta updates with it. -->
    <div class="period-nav">
      <button class="pchip" data-period="7"  onclick="setTrendsPeriod(7)">7 days</button>
      <button class="pchip active" data-period="30" onclick="setTrendsPeriod(30)">30 days</button>
      <button class="pchip" data-period="90" onclick="setTrendsPeriod(90)">90 days</button>
      <span class="period-meta" id="period-meta"></span>
    </div>

    <!-- Quiet one-liner — avg cal, weight Δ, workouts. Plain text,
         no chrome. Tints carry the goal-fit signal. -->
    <div class="trend-line" id="trend-line"></div>

    <!-- 5-DAY TREND — moved from the Day tab. Same strip, same renderer;
         lives here so the Day view stays focused on today's logging. -->
    <div id="trend-wrap" style="display:none;margin-top:16px">
      <div class="stitle" style="margin-bottom:8px">5-day trend <span id="trend-days-lbl" style="font-weight:400;opacity:.55;font-size:9px;letter-spacing:.04em"></span></div>
      <div class="trend-strip" id="trend-strip"></div>
    </div>

    <!-- Weekly AI analysis — collapsed banner, expands on tap -->
    <div class="insights" id="ins-week" style="margin-top:14px">
      <div class="ins-banner" onclick="toggleInsights('week')" role="button" tabindex="0" aria-expanded="false">
        <span class="ins-spark"><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2.2l1.7 4.8 4.8 1.7-4.8 1.7L12 15.2l-1.7-4.8L5.5 8.7l4.8-1.7z"/><path d="M18.6 13.4l.82 2.18 2.18.82-2.18.82-.82 2.18-.82-2.18L15.6 16.4l2.18-.82z"/></svg></span>
        <span class="ins-title">Weekly Analysis</span>
        <span class="ins-actions">
          <span class="ins-refresh" onclick="event.stopPropagation();refreshWeekInsights()" title="Refresh">&#8635;</span>
          <span class="ins-chev">&#9662;</span>
        </span>
      </div>
      <div class="ins-body"><div class="icrd fade-in" id="week-insights-card"><div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div></div></div>
    </div>

    <!-- ONE chart — weight. The trend that matters. Calorie + protein
         adherence is summarized in the one-liner + AI banner above. -->
    <div class="ccrd" style="margin-top:14px">
      <div class="ctitle"><span>Weight</span><span id="wt-now-lbl" class="ctitle-val" style="color:var(--pu)"></span></div>
      <div class="cwrap"><canvas id="weightChart"></canvas></div>
    </div>

    <!-- Goal progress — renderGoalProgress() hides this when no
         goal_weight is set, so maintain/performance users get a
         calmer tab. -->
    <div class="goal-card" id="goal-card" style="margin-top:14px"></div>
  </div>

  <!-- PROFILE TAB -->
  <div class="tab-panel" id="panel-profile">

    <!-- ─── YOUR SETTINGS ─── user-controlled facts (demographics + targets).
         Single source of truth for everything the user explicitly sets. Lives
         above Arnie's brain so the structure is unmistakable: settings here,
         learned facts below. -->
    <div class="stitle spaced" style="margin-top:4px">
      <span>Your settings</span>
    </div>

    <div class="settings-sub">Demographics</div>
    <div id="demographics-card" class="basics-grid"></div>

    <div class="settings-sub" style="margin-top:14px">Goals &amp; targets</div>
    <!-- Container is a bare div now — per-tile borders provide the card
         framing. Matches the Demographics section's structure (no .infocrd
         wrapper, tiles do the visual work). -->
    <div id="goals-card"></div>

    <!-- Auto-calculate targets card — sits below the user-defined goals.
         Tap the (i) glyph to reveal the calculation rules; tap the button
         to compute & save the recommended calorie + macro targets from
         BMR + goal + body composition (see compute_auto_macro_targets in
         api/app.py). -->
    <div class="calc-card" id="calc-card">
      <div class="calc-card-hd">
        <div class="calc-card-title">Not sure what to set?</div>
        <button class="calc-info-btn" onclick="toggleCalcInfo()" type="button" aria-label="How is this calculated?" title="How is this calculated?">
          <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="8" cy="8" r="6.5"/>
            <path d="M8 5.5v.01M7.3 7.5h.7v3.5h.7"/>
          </svg>
        </button>
      </div>
      <div class="calc-card-sub">Let Arnie set your calories and macros from your goal + body comp.</div>
      <button class="calc-btn" id="calc-btn" onclick="calculateTargetsForMe()" type="button">Calculate for me</button>
      <!-- Explainer panel — collapsed by default. Industry-standard breakdown
           with citations so users can verify the math against established
           sources (Mifflin-St Jeor, ACSM, ISSN, Dietary Guidelines). -->
      <div class="calc-explain" id="calc-explain">
        <div class="calc-intro">
          The same math evidence-based nutrition coaches use. Four steps, each
          grounded in published standards — no proprietary "secret formula".
        </div>

        <div class="calc-rule">
          <div class="calc-rule-h">Step 1 &nbsp;·&nbsp; Resting metabolic rate</div>
          <div class="calc-rule-b">
            <span class="calc-kv">Mifflin-St Jeor equation — the most accurate BMR estimator validated against indirect calorimetry.</span>
            <span class="calc-kv calc-meta">Inputs: <b>weight, height, age, sex</b>. Source: Mifflin et al., 1990 · adopted by the Academy of Nutrition &amp; Dietetics.</span>
          </div>
        </div>

        <div class="calc-rule">
          <div class="calc-rule-h">Step 2 &nbsp;·&nbsp; Total daily energy</div>
          <div class="calc-rule-b">
            <span class="calc-kv">BMR × <b>1.4</b> — a single conservative multiplier, not derived from your lifting experience.</span>
            <span class="calc-kv calc-aside">Years lifting tells us how to coach you; it doesn't tell us how much you burn outside the gym. Until we ask about your job and weekly activity directly, we use one realistic default: slightly above textbook "lightly active" (1.375) to account for gym sessions, well below "moderate" (1.55) which assumes a non-sedentary occupation.</span>
            <span class="calc-kv calc-aside">Edit the calorie target directly above if you know your real TDEE — manual edits stick and the rest of the macros recompute from your number.</span>
            <span class="calc-kv calc-meta">Source: ACSM Resource Manual activity tiers; conservative calibration per Helms (Muscle &amp; Strength Pyramid) &amp; Lyle McDonald — start lower, adjust by results.</span>
          </div>
        </div>

        <div class="calc-rule">
          <div class="calc-rule-h">Step 3 &nbsp;·&nbsp; Calorie target</div>
          <div class="calc-rule-b">
            <span class="calc-kv">Calorie surplus or deficit applied to TDEE based on your goal.</span>
            <span class="calc-kv"><b>Cut</b> &nbsp;TDEE − 17.5% &nbsp;<span class="calc-aside">mid of the 10–25% deficit range, preserves lean mass</span></span>
            <span class="calc-kv"><b>Maintain</b> &nbsp;TDEE &nbsp;<span class="calc-aside">no surplus, no deficit</span></span>
            <span class="calc-kv"><b>Lean bulk</b> &nbsp;TDEE + 10% &nbsp;<span class="calc-aside">≈ 0.25–0.5 lb/wk lean gain</span></span>
            <span class="calc-kv"><b>Performance</b> &nbsp;TDEE + 5% &nbsp;<span class="calc-aside">output without fat gain</span></span>
            <span class="calc-kv calc-meta">Source: Helms et al. (2014) Evidence-Based Recommendations; Aragon &amp; Schoenfeld (2013).</span>
          </div>
        </div>

        <div class="calc-rule">
          <div class="calc-rule-h">Step 4 &nbsp;·&nbsp; Macros</div>
          <div class="calc-rule-b">
            <span class="calc-kv">Protein anchors first, fat second, carbs fill the remaining calories.</span>
            <span class="calc-kv calc-macro-row">
              <b>Protein</b>
              <span class="calc-aside">1.6–2.2 g/kg for active adults (ISSN, 2017). We use:</span>
            </span>
            <span class="calc-kv calc-sub">· Cut: <b>1.0 g/lb of goal weight</b> &nbsp;<span class="calc-aside">(≈2.2 g/kg)</span></span>
            <span class="calc-kv calc-sub">· Bulk &amp; maintain: <b>0.9 g/lb current</b> &nbsp;<span class="calc-aside">(≈2.0 g/kg)</span></span>
            <span class="calc-kv calc-sub">· Health: <b>30% of calories</b></span>

            <span class="calc-kv calc-macro-row" style="margin-top:6px">
              <b>Fat</b>
              <span class="calc-aside">20–35% kcal (Dietary Guidelines for Americans). We use:</span>
            </span>
            <span class="calc-kv calc-sub">· Cut: <b>0.3 g/lb current</b> &nbsp;<span class="calc-aside">(≈25% kcal)</span></span>
            <span class="calc-kv calc-sub">· Bulk &amp; maintain: <b>0.35 g/lb current</b> &nbsp;<span class="calc-aside">(≈30% kcal)</span></span>
            <span class="calc-kv calc-sub">· Performance: <b>25% of calories</b></span>
            <span class="calc-kv calc-sub">· Health: <b>30% of calories</b></span>

            <span class="calc-kv calc-macro-row" style="margin-top:6px">
              <b>Carbs</b>
              <span class="calc-aside">whatever's left — typically 40–60% kcal, powers training &amp; recovery.</span>
            </span>
          </div>
        </div>

        <div class="calc-foot">
          Re-run any time your weight, goal, or training changes. Tap a target
          row above to override any value — your manual edits stick until you
          tap "Calculate for me" again.
        </div>
      </div>
    </div>

    <!-- ─── COACHING PREFERENCES ─── moved here from the (now removed)
         Coaching tab. Same controls, same JS handlers (renderRemindSettings
         / renderFoodModeSettings / renderCoachingStyleSettings) — just lives
         on the Profile tab now under a top-level section header that mirrors
         "Your settings" structurally: stitle.spaced for the section, then
         .settings-sub labels above each .pref-card. -->
    <div class="stitle spaced" style="margin-top:28px">
      <span>Coaching preferences</span>
    </div>

    <!-- Reminders — toggle lives in the title row so the card itself has
         identical innards to Food logging / Coaching style (slider + ticks
         + hint). When the toggle is off, dim the whole card. -->
    <div class="cp-row">
      <div class="cp-label">Reminders</div>
      <label class="pref-toggle">
        <input type="checkbox" id="remind-toggle" onchange="saveRemindOn(this.checked)">
        <span class="pref-slider"></span>
      </label>
    </div>
    <div class="pref-card" id="remind-card">
      <input type="range" class="pref-range" id="remind-range" min="0" max="3" step="1" value="2"
             oninput="onRemindSlide(this.value)" onchange="commitRemindSlide(this.value)">
      <div class="pref-ticks" id="remind-ticks">
        <span class="pref-tick">Minimal</span>
        <span class="pref-tick">Light</span>
        <span class="pref-tick">Regular</span>
        <span class="pref-tick">All-day</span>
      </div>
      <div class="pref-hint" id="remind-desc"></div>
    </div>

    <div class="cp-row">
      <div class="cp-label">Logging Style</div>
    </div>
    <div class="pref-card" id="food-mode-card">
      <input type="range" class="pref-range" id="food-mode-range" min="0" max="2" step="1" value="1"
             oninput="onFoodSlide(this.value)" onchange="commitFoodSlide(this.value)">
      <div class="pref-ticks" id="food-mode-ticks">
        <span class="pref-tick">Quick</span>
        <span class="pref-tick">Balanced</span>
        <span class="pref-tick">Strict</span>
      </div>
      <div class="pref-hint" id="food-mode-desc"></div>
    </div>

    <div class="cp-row">
      <div class="cp-label">Coaching Style</div>
    </div>
    <div class="pref-card" id="coach-style-card">
      <input type="range" class="pref-range" id="coach-style-range" min="0" max="2" step="1" value="1"
             oninput="onCoachSlide(this.value)" onchange="commitCoachSlide(this.value)">
      <div class="pref-ticks" id="coach-style-ticks">
        <span class="pref-tick">Supportive</span>
        <span class="pref-tick">Balanced</span>
        <span class="pref-tick">Strict</span>
      </div>
      <div class="pref-hint" id="coach-style-desc"></div>
    </div>

    <!-- ─── CONNECTED DEVICES ─── moved up from the bottom of the tab so
         wearable integrations are visible before the dense Arnie's brain
         section. Compact 3-up grid (2-up on mobile) — designed to scale
         when we add more integrations (Fitbit, Hume, Garmin, etc.). The
         #devices-card is a bare div: each .dev-card has its own border
         and the .dev-grid handles layout. -->
    <div class="stitle spaced" style="margin-top:28px">
      <span>Connected devices</span>
    </div>
    <div id="devices-card" style="margin-top:6px"></div>

    <!-- ─── ARNIE'S BRAIN ─── learned facts only. Bio + AI attributes by
         category. NEVER duplicates what's in the settings section above. -->
    <div id="ai-profile-section" style="display:none;margin-top:28px">
      <!-- Top header — mirrors the Day-tab .log-section-hd pattern: label
           on the left, chevron + action buttons on the right inside a flex
           container. Chevron rotates via .expanded class on click. -->
      <div class="stitle spaced pf-cat-hd" style="margin-top:4px" onclick="toggleBio()">
        <span>Arnie's brain <span class="ai-pill">AI</span></span>
        <div style="display:flex;align-items:center;gap:6px">
          <button class="pf-chevron" id="bio-chevron-btn" title="Expand">&#8249;</button>
          <button class="add-toggle" onclick="event.stopPropagation();refreshAIProfile()" title="Refresh">&#8635;</button>
        </div>
      </div>
      <!-- Bio card — collapsed by default -->
      <div class="infocrd" id="ai-bio-card" style="padding:14px 16px;line-height:1.6;font-size:14px;color:var(--tx);display:none"></div>
      <!-- Learned facts grouped by category -->
      <div id="ai-attributes-section"></div>
    </div>
    <div id="ai-profile-loading" style="padding:24px 16px;text-align:center;color:var(--mu);font-size:13px;margin-top:28px">Building Arnie's brain&#8230;</div>
    <div id="ai-profile-empty" style="display:none;padding:16px 0;margin-top:28px">
      <div class="stitle spaced" style="margin-top:4px">
        <span>Arnie's brain <span class="ai-pill">AI</span></span>
      </div>
      <div class="lempty">Keep logging and chatting — Arnie builds this from your interactions. Check back after a few days.</div>
    </div>

    <!-- Training program — collapsed by default to match the Arnie's brain
         category pattern. Uses .pf-cat-section + .pf-cat-hd for the header,
         .pf-cat-body for the collapsible region. The "+" button gets
         event.stopPropagation so it opens the editor without toggling the
         section, and openWorkoutEditor() force-expands the section so the
         editor is actually visible when it slides open. -->
    <div class="pf-cat-section collapsed" id="pf-training-section">
      <div class="stitle spaced pf-cat-hd" style="margin-top:24px" onclick="togglePfCat(this)">
        <span>Training program</span>
        <div style="display:flex;align-items:center;gap:6px">
          <button class="pf-chevron" title="Toggle">&#8249;</button>
          <button class="add-toggle" id="wp-edit-btn" onclick="event.stopPropagation();openWorkoutEditor()" title="Set up / edit">+</button>
        </div>
      </div>
      <div class="pf-cat-body">
        <div id="workout-program-card"><div class="lempty" style="margin-top:6px">No training program saved yet. Tap + to set one up — Arnie will use it in every session.</div></div>
        <div class="add-card" id="workout-editor" style="display:none;margin-top:10px">
          <div style="display:flex;gap:8px;padding:12px 14px;border-bottom:1px solid var(--bd)">
            <button class="add-submit" style="flex:1;text-align:center;padding:10px" onclick="autoFillWorkout()">&#10024; Auto-fill from Arnie chat</button>
          </div>
          <div style="padding:6px 14px;font-family:'Geist Mono','SF Mono',monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--di)">or paste manually</div>
          <textarea class="add-inp" id="workout-raw" rows="10" placeholder="Paste your workout split — exercises, goals, recent lifts, rotation." style="height:160px;resize:vertical;font-size:13px;line-height:1.5"></textarea>
          <div style="display:flex;gap:8px;padding:10px 14px;border-top:1px solid var(--bd)">
            <button class="add-submit" style="flex:1" onclick="saveWorkoutProgram()">&#9889; Parse &amp; save</button>
            <button class="cbtn" onclick="closeWorkoutEditor()">Cancel</button>
          </div>
          <div id="workout-parse-status" style="padding:0 14px 10px;font-size:12px;color:var(--mu)"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- BRAIN TAB —— live mindmap of what Arnie has learned. The iframe loads
       /brain/{token}, which polls /api/profile/{token} every ~20s and
       animates new/changed nodes. Lazy-loaded on first tab open so
       React+Babel from CDN don't slow the dashboard's initial paint.
       Panel breaks out of .main-inner's 900px max-width via the
       body.brain-active CSS block above for a true full-bleed canvas. -->
  <div class="tab-panel" id="panel-brain">
    <div id="brain-frame-wrap">
      <iframe id="brain-frame" title="Arnie's Brain" style="border:0;width:100%;height:100%;display:block;background:transparent" loading="lazy"></iframe>
    </div>
  </div>

  <!-- COACHING TAB removed — controls migrated to the Profile tab above
       under a "Coaching preferences" section. The render functions still
       live in JS unchanged (just called from renderProfileTab now). -->

<footer>Arnie &middot; auto-refresh 5 min</footer>
</div><!-- /main-inner -->
</div><!-- /main -->

<!-- Bottom nav icons refreshed to the preview's Lucide-family set:
     Day = target ring + filled center dot (clear "today" marker)
     Week = simple ascending trend line (focus on the arc, not a literal calendar)
     Profile = refined head + single shoulder arc (fewer path segments)
     Coaching = dual sparkle (same family as the Insights action-tile glyph,
                so AI-coaching content speaks one visual dialect). -->
<nav class="bottomnav">
  <button class="bn-item active" id="bn-day" onclick="switchTab('day')">
    <span class="bn-ico"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none"/></svg></span>Daily
  </button>
  <button class="bn-item" id="bn-week" onclick="switchTab('week')">
    <span class="bn-ico"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 17l5-5 3.5 3.5 8-8.5"/><path d="M15 7h5.5v5.5"/></svg></span>Trends
  </button>
  <button class="bn-item" id="bn-brain" onclick="switchTab('brain')">
    <span class="bn-ico"><svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>
      <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>
      <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" opacity=".55"/>
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none">
        <animate attributeName="r" values="1.5;2.2;1.5" dur="2.6s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="1;.55;1" dur="2.6s" repeatCount="indefinite"/>
      </circle>
    </svg><span class="brain-pending-dot" aria-hidden="true"></span></span>Brain
  </button>
  <button class="bn-item" id="bn-profile" onclick="switchTab('profile')">
    <span class="bn-ico"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8.5" r="3.5"/><path d="M5.5 20.5c.7-3.5 3.4-5.5 6.5-5.5s5.8 2 6.5 5.5"/></svg></span>Client
  </button>
</nav>

</div><!-- /shell -->

<script>
// ── Constants ─────────────────────────────────────────────────────────────
const TOKEN        = '{token}';
const STATS_BASE   = '/api/stats/'    + TOKEN;
const INSIGHTS_API = '/api/insights/' + TOKEN;
const PROFILE_API  = '/api/profile/'  + TOKEN;
// Brain-tab feature gate. Driven by BRAIN_TAB_ENABLED env var on the
// server. Default false in production so the half-built tab never paints,
// and loadBrainTab() below short-circuits before touching the iframe src.
const _BRAIN_ENABLED = {_brain_enabled_js};

// ── State ─────────────────────────────────────────────────────────────────
let _baseData=null, _dayCache={{}}, _viewingDate=null, _todayStr=null;
let _availDates=[], _activeTab='day', calChart, proChart, weightChart;
// Trends-tab period selector — 7 / 30 / 90 day window. renderWeekTab
// re-slices off this. Default 30 matches the sidebar's nav meta label.
let _trendsPeriod=30;

// ── Local date helper (avoids UTC-offset issues with toISOString) ─────────
function _localDate(d){{
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
}}

// ── Theme ─────────────────────────────────────────────────────────────────
(function(){{
  var t=localStorage.getItem('arnie-theme')||
    (window.matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');
  document.documentElement.setAttribute('data-theme',t);
  var btn=document.getElementById('theme-btn');
  if(btn) btn.textContent=t==='dark'?'☾':'☀';
}})();

function updateThemeUI(t){{
  var isDark=t==='dark';
  var btn=document.getElementById('theme-btn');
  if(btn) btn.textContent=isDark?'☾':'☀';
  var lbl=document.getElementById('sb-theme-lbl');
  if(lbl) lbl.textContent=isDark?'Light mode':'Dark mode';
  var ico=document.getElementById('sb-theme-ico');
  if(ico) ico.innerHTML=isDark
    ?'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/></svg>'
    :'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
}}
function toggleTheme(){{
  var html=document.documentElement;
  var next=html.getAttribute('data-theme')==='dark'?'light':'dark';
  html.setAttribute('data-theme',next);
  updateThemeUI(next);
  localStorage.setItem('arnie-theme',next);
  if(_baseData && _activeTab==='week') setTimeout(()=>renderWeekTab(_baseData),50);
  if(typeof postBrainTheme==='function') postBrainTheme(next);
}}

// ── Utils ─────────────────────────────────────────────────────────────────
function esc(s){{
  return String(s??'').replace(/[&<>"']/g,c=>(
    {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}
function escA(s){{return String(s??'').replace(/"/g,'&quot;')}}
function pct(v,t){{return(!t||v==null)?0:Math.min(100,Math.round(v/t*100))}}
function fmt(n){{return n!=null?Number(n).toLocaleString():'—'}}
function fmtDate(d){{
  var[yr,m,day]=d.split('-');
  var label=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m-1]+' '+ +day;
  var curYr=String(new Date().getFullYear());
  return yr===curYr ? label : label+" '"+yr.slice(2);
}}
function countUp(el,target,dur){{
  if(target==null||isNaN(target)){{el.textContent='—';return}}
  dur=dur||700;var t0=performance.now();
  (function tick(now){{
    var p=Math.min((now-t0)/dur,1),e=1-Math.pow(1-p,3);
    el.textContent=Math.round(target*e);
    if(p<1) requestAnimationFrame(tick);
  }})(t0);
}}

// ── API ───────────────────────────────────────────────────────────────────
async function fetchStats(d){{
  var r=await fetch(d?STATS_BASE+'?date='+d:STATS_BASE);
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}}
var _insightsLoaded=false;
var _insightsDate='';  // which date the loaded insights are for

async function fetchInsights(dateStr, period){{
  try{{
    var ctrl=new AbortController();
    var tid=setTimeout(function(){{ctrl.abort();}},25000);
    var qs=[];
    if(dateStr)qs.push('date='+dateStr);
    if(period)qs.push('period='+period);
    var url=INSIGHTS_API+(qs.length?'?'+qs.join('&'):'');
    var r=await fetch(url,{{signal:ctrl.signal}});
    clearTimeout(tid);
    if(!r.ok)return[];
    return((await r.json()).insights||[]).slice(0,4);  // cap 4 bullets
  }}catch(e){{return[]}}
}}

async function loadInsights(){{
  var date=_viewingDate||'';
  // Already loaded for this date? Skip.
  if(_insightsLoaded&&_insightsDate===date)return;
  var ins=await fetchInsights(date);
  _insightsLoaded=!!ins.length;
  _insightsDate=date;
  renderInsights(ins);
}}

// ── Tab switching ─────────────────────────────────────────────────────────
var PAGE_HEADS={{
  week:{{title:'Trends',sub:'LAST 30 DAYS'}},
  profile:{{title:'Client',sub:'PROFILE &amp; SETTINGS'}},
  brain:{{title:"Arnie's brain",sub:'LIVE &mdash; UPDATES AS ARNIE LEARNS'}},
}};
function switchTab(name){{
  _activeTab=name;
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  // brain tab takes over the full main column — toggle a body flag so the
  // pagehead hides and #panel-brain breaks out of the 900px max-width.
  document.body.classList.toggle('brain-active', name==='brain');
  document.querySelectorAll('.navitem[id^="nav-"]').forEach(b=>b.classList.remove('active'));
  var ni=document.getElementById('nav-'+name);if(ni)ni.classList.add('active');
  document.querySelectorAll('.bn-item').forEach(b=>b.classList.remove('active'));
  var bi=document.getElementById('bn-'+name);if(bi)bi.classList.add('active');
  if(name!=='day'){{
    var h=PAGE_HEADS[name]||{{}};
    var pt=document.getElementById('ph-title');var ps=document.getElementById('ph-sub');
    if(pt)pt.textContent=h.title||'';
    if(ps)ps.innerHTML=h.sub||'';
  }}else if(_baseData){{
    renderPageHead(_baseData);
  }}
  if(name==='day') loadInsights();
  if(name==='week'){{if(_baseData)renderWeekTab(_baseData);loadWeekInsights();}}
  if(name==='profile' && _baseData){{renderProfileTab(_baseData);loadWorkoutProgram();loadAIProfile();}}
  if(name==='brain') loadBrainTab();
}}

// Brain tab —— lazy-mount the /brain/{token} iframe on first tab open. We set
// the src exactly once so the React app keeps its state (selected node, view
// toggle, polling timer) across subsequent tab switches. The current dashboard
// theme is passed via ?theme=... so the iframe paints correctly on first
// frame; subsequent toggles are pushed live by postBrainTheme().
var _brainLoaded = false;
function loadBrainTab(){{
  // Feature gate — when BRAIN_TAB_ENABLED is unset in prod env, this
  // returns before touching the iframe src so /brain/{{token}} is never
  // fetched (route doesn't exist in prod yet → would 404).
  if(!_BRAIN_ENABLED) return;
  if(_brainLoaded) return;
  var f = document.getElementById('brain-frame');
  if(!f) return;
  var theme = document.documentElement.getAttribute('data-theme') || 'dark';
  // Pass through ?sim= from the dashboard URL so /dashboard/{{TOKEN}}?sim=full
  // produces a fully-populated brain just like the direct /brain/...?sim=full
  // link does. Keeps the previews consistent for local testing/demos.
  var sim = '';
  try {{
    var p = new URLSearchParams(window.location.search).get('sim');
    if (p) sim = '&sim=' + encodeURIComponent(p);
  }} catch (e) {{}}
  f.src = '/brain/' + encodeURIComponent(TOKEN) + '?theme=' + theme + '&bot={bot_username}' + sim;
  _brainLoaded = true;
}}
// Push the dashboard's current theme into the brain iframe (if it's mounted
// and same-origin). Called from toggleTheme below.
function postBrainTheme(mode){{
  var f = document.getElementById('brain-frame');
  if(!f || !f.contentWindow) return;
  try{{ f.contentWindow.postMessage({{type:'arnie-brain-theme', mode:mode}}, '*'); }}catch(e){{}}
}}

// ── Boot ──────────────────────────────────────────────────────────────────
async function init(){{
  var saved=localStorage.getItem('arnie-theme')||
    (window.matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');
  updateThemeUI(saved);
  try{{
    var data=await fetchStats(null);
    _baseData=data;
    _todayStr=data.viewing_date||data.day?.date||_localDate(new Date());
    _viewingDate=_todayStr;
    var hd=(data.history||[]).map(h=>h.date);
    _availDates=[...new Set([...hd,_todayStr])].sort();
    _dayCache[_todayStr]=data;
    // Sidebar user card
    var nm=data.profile?.name||'';
    var gl=data.profile?.primary_goal||'';
    var wt=data.profile?.current_weight_lbs||'';
    var su=document.getElementById('sb-user');
    var sn=document.getElementById('sb-name');
    var sg=document.getElementById('sb-goal-lbl');
    if(sn)sn.textContent=nm;
    if(sg)sg.textContent=(gl?goalLabel(gl).toUpperCase():'')+(wt?' · '+wt+' LB':'');
    if(su&&nm)su.style.display='flex';
    document.getElementById('app-load').style.display='none';
    renderDateNav();
    renderDayTab(data);
    loadInsights();
    initLogSections();
    initLearnReel();
  }}catch(e){{
    document.getElementById('app-load').textContent='Failed to load — tap ↻ to retry.';
  }}
}}

// ── "Arnie learned" live ticker ───────────────────────────────────────────
// A single line that continuously rolls through real learned facts (from
// /api/profile custom attributes). Both the verb and the fact change each
// turn — "Arnie noticed your weakness…", "Arnie clocked your resting HR…" —
// so it never reads the same twice. Tap → the full learned view.
let _kiiItems=[], _kiiIdx=0, _kiiTimer=null, _kiiPaused=false, _kiiVerb='';
const _KII_DUR=3400;  // ms per fact — quick, so the motion stays lively
// Verbs that read naturally as "Arnie <verb> your <thing>".
const _KII_VERBS=['learned','noticed','remembers','picked up on','clocked','is tracking','locked in'];

// Strip "(2026-06-09, Whoop)"-style provenance tails, soften snake_case keys
// that leak through from storage (rep_then_load → rep then load), and collapse
// whitespace.
function _kiiClean(s){{
  return (s||'')
    .replace(/\s*\([^)]*\d{{4}}[^)]*\)\s*/g,' ')
    .replace(/([a-z0-9])_([a-z0-9])/gi,'$1 $2')
    .replace(/\s+/g,' ').trim();
}}

// One custom attribute → {{what, fact}}, or null if it isn't worth surfacing.
function _kiiHuman(c){{
  var label=(c.label||'').trim();
  if(!label || label.toLowerCase()==='source') return null;
  var fact;
  if(c.chips && c.chips.length){{
    var ch=c.chips.map(function(x){{return _kiiClean(String(x));}}).filter(Boolean);
    if(!ch.length) return null;
    fact=ch.slice(0,3).join('  ·  ');
    if(ch.length>3) fact+='  ·  +'+(ch.length-3)+' more';
  }}else{{
    fact=_kiiClean(String(c.value!=null?c.value:''));
  }}
  if(!fact) return null;
  var lf=fact.toLowerCase();
  if(lf==='true'||lf==='false'||lf==='yes'||lf==='no') return null;  // bare flags read as noise
  if(fact.length>96) return null;  // keep it snappy
  return {{what:label, fact:fact}};
}}

function _kiiShuffle(a){{
  for(var i=a.length-1;i>0;i--){{
    var j=Math.floor(Math.random()*(i+1));var t=a[i];a[i]=a[j];a[j]=t;
  }}
  return a;
}}

// Lowercase a label for "your <label>" — but keep all-caps acronyms (HRV, RIR).
function _kiiLabel(s){{
  return String(s||'').split(' ').map(function(w){{
    return /^[A-Z0-9]{{2,4}}$/.test(w) ? w : w.toLowerCase();
  }}).join(' ');
}}

// A different verb than last time, so consecutive turns never repeat it.
function _kiiNextVerb(){{
  var v;
  do {{ v=_KII_VERBS[Math.floor(Math.random()*_KII_VERBS.length)]; }}
  while(_KII_VERBS.length>1 && v===_kiiVerb);
  _kiiVerb=v; return v;
}}

async function initLearnReel(){{
  var card=document.getElementById('kii-card');
  if(!card) return;
  try{{
    var r=await fetch(PROFILE_API);
    if(!r.ok) return;
    var data=await r.json();
    var custom=(data && data.custom)||[];
    var seen={{}}, items=[];
    custom.forEach(function(c){{
      var it=_kiiHuman(c);
      if(!it) return;
      var k=it.what.toLowerCase();
      if(seen[k]) return; seen[k]=1;
      items.push(it);
    }});
    if(items.length<3) return;            // brand-new users keep the learning-progress card instead
    _kiiItems=_kiiShuffle(items);
    _kiiIdx=0;

    card.style.display='flex';
    card.addEventListener('mouseenter',function(){{_kiiPause(true);}});
    card.addEventListener('mouseleave',function(){{_kiiPause(false);}});
    _kiiRender(true);
  }}catch(e){{}}
}}

// Compose one rolling line: "Arnie <verb> your <label> — <value>".
function _kiiLineHTML(it){{
  return 'Arnie <em class="kii-v">'+esc(_kiiNextVerb())+'</em> your '+
    '<span class="kii-h">'+esc(_kiiLabel(it.what))+'</span> — '+
    '<span class="kii-val">'+esc(it.fact)+'</span>';
}}

function _kiiRender(initial){{
  var roll=document.getElementById('kii-roll');
  if(!roll) return;
  var it=_kiiItems[_kiiIdx];

  if(initial){{
    roll.innerHTML='<span class="kii-line enter" id="kii-line">'+_kiiLineHTML(it)+'</span>';
    _kiiFit(roll, roll.firstChild);
  }}else{{
    // roll the current line up & out, then drop the next one in from below
    var old=roll.querySelector('.kii-line');
    if(old){{ old.classList.remove('enter'); old.classList.add('exit'); old.removeAttribute('id'); }}
    var next=document.createElement('span');
    next.className='kii-line enter'; next.id='kii-line';
    next.innerHTML=_kiiLineHTML(it);
    roll.appendChild(next);
    _kiiFit(roll, next);   // grow/shrink the viewport to the new line (wrapped) height
    setTimeout(function(){{ if(old&&old.parentNode) old.parentNode.removeChild(old); }}, 460);
  }}
  _kiiSchedule();
}}

// Size the roll viewport to the line's rendered height so wrapped (multi-line)
// facts show in full on narrow screens, while short ones stay snug. Desktop
// keeps the line on one row, so this resolves to a single line height there.
function _kiiFit(roll, line){{
  if(!roll || !line) return;
  var h=line.offsetHeight;
  if(h) roll.style.height=h+'px';
}}

function _kiiSchedule(){{
  clearTimeout(_kiiTimer);
  if(_kiiPaused) return;
  _kiiTimer=setTimeout(_kiiAdvance, _KII_DUR);
}}

function _kiiAdvance(){{
  if(!_kiiItems.length) return;
  _kiiIdx=(_kiiIdx+1)%_kiiItems.length;
  _kiiRender(false);
}}

function _kiiPause(on){{
  _kiiPaused=on;
  if(on) clearTimeout(_kiiTimer); else _kiiSchedule();
}}

// Tap the card → the full learned view. Brain tab when enabled, else Profile
// (where every learned attribute lives). Either way: deeper engagement.
function openLearnReel(){{
  switchTab(_BRAIN_ENABLED ? 'brain' : 'profile');
}}

async function refreshCurrent(btn){{
  // Visible tap feedback: spin the icon while the fetch is in flight so
  // the user knows the action took. Auto-clears on completion (success
  // or failure) so a stuck network doesn't leave it spinning forever.
  if(btn) btn.classList.add('spinning');
  delete _dayCache[_viewingDate];
  try{{
    if(_viewingDate===_todayStr){{
      var data=await fetchStats(null);
      _baseData=data;_dayCache[_todayStr]=data;
      renderDayTab(data);
      if(_activeTab==='week') renderWeekTab(data);
      if(_activeTab==='profile') renderProfileTab(data);
    }}else{{
      await loadDayData(_viewingDate);
    }}
  }}catch(e){{}}
  finally{{ if(btn) btn.classList.remove('spinning'); }}
}}

// ── Date nav ──────────────────────────────────────────────────────────────
function renderDateNav(){{
  var el=document.getElementById('date-chips');
  el.innerHTML='';
  var ci=_availDates.indexOf(_viewingDate);
  var s=Math.max(0,ci-2),e=Math.min(_availDates.length-1,ci+2);
  while(e-s<4&&s>0) s--;
  while(e-s<4&&e<_availDates.length-1) e++;
  for(var i=s;i<=e;i++){{
    var d=_availDates[i],chip=document.createElement('button');
    chip.className='dchip'+(d===_viewingDate?' active':'');
    chip.appendChild(document.createTextNode(fmtDate(d)));
    if(d===_todayStr){{
      var tag=document.createElement('span');
      tag.className='today-tag';tag.textContent='Today';chip.appendChild(tag);
    }}
    (function(dd){{chip.onclick=()=>selectDate(dd)}})(d);
    el.appendChild(chip);
  }}
  document.getElementById('date-prev').disabled=ci<=0;
  document.getElementById('date-next').disabled=ci>=_availDates.length-1;
}}

async function navDate(dir){{
  var ci=_availDates.indexOf(_viewingDate),ni=ci+dir;
  if(ni<0||ni>=_availDates.length) return;
  await selectDate(_availDates[ni]);
}}

async function selectDate(d){{
  _viewingDate=d;renderDateNav();
  // Reload insights for the newly selected date
  _insightsLoaded=false;_insightsDate='';
  var el=document.getElementById('insights-card');
  if(el)el.innerHTML='<div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div>';
  var _sp=document.getElementById('ins-preview-day');if(_sp)_sp.textContent='';
  loadInsights();
  if(_dayCache[d]) renderDayTab(_dayCache[d]);
  else await loadDayData(d);
}}

async function loadDayData(d){{
  document.getElementById('food-log').innerHTML='<div class="lempty">Loading…</div>';
  document.getElementById('ex-log').innerHTML='<div class="lempty">Loading…</div>';
  try{{
    var data=await fetchStats(d);
    _dayCache[d]=data;renderDayTab(data);
  }}catch(e){{
    document.getElementById('food-log').innerHTML='<div class="lempty">Failed to load.</div>';
  }}
}}

// ── Arnie's learning progress ─────────────────────────────────────────────
// Tracks `attribute_count` from /api/profile — the same authoritative tally
// the Brain tab's gate uses, so both surfaces tick in lockstep. The in-day
// progress bar is hidden for now; instead we toggle `body.brain-pending` so
// the brain nav icons get a tiny amber dot until the gate (25 facts) opens.
// Tapping still routes to the brain page so users can read what's missing.
function renderLearningProgress(d){{
  var wrap=document.getElementById('learn-wrap');
  if(wrap)wrap.style.display='none';
  var TARGET=25;
  var facts=(typeof d.attribute_count==='number')?d.attribute_count:0;
  if(!facts){{
    var p=d.profile||{{}}, tgt=d.targets||{{}};
    var hist=d.history||[], weights=d.weights||[];
    var loggedDays=hist.filter(function(h){{return (h.calories||0)>0;}}).length;
    var workoutDays=hist.filter(function(h){{return h.workout;}}).length;
    facts=(p.primary_goal && tgt.calories && tgt.protein?10:0)
        +(loggedDays>=3?8:0)+(weights.length>=3?6:0)
        +(workoutDays>=1?5:0)
        +((p.whoop_connected||p.apple_health_connected)?6:0);
  }}
  document.body.classList.toggle('brain-pending', facts<TARGET);
}}

// ── 5-day trend strip ─────────────────────────────────────────────────────
function renderTrendStrip(history, weights, targets){{
  var wrap=document.getElementById('trend-wrap');
  var strip=document.getElementById('trend-strip');
  if(!wrap||!strip)return;

  // Last 5 completed days from history (sorted oldest→newest by the API). A day
  // counts once it has calories logged and isn't today — we don't require a formal
  // /close (most users never close days), and today's in-progress day would skew the
  // trend, so it's excluded until tomorrow.
  var recent=(history||[]).filter(function(h){{
    return (h.calories||0)>0 && h.date!==_todayStr;
  }}).slice(-5);
  if(recent.length<2){{wrap.style.display='none';return;}}

  var lbl=document.getElementById('trend-days-lbl');
  if(lbl)lbl.textContent='LAST '+recent.length+' DAYS';

  function avgOf(arr,key){{
    var vals=arr.map(function(x){{return x[key]||0;}});
    return vals.reduce(function(a,b){{return a+b;}},0)/vals.length;
  }}
  function arrow(delta,thresh){{
    if(delta>thresh)return'<span class="tc-up">↑</span>';
    if(delta<-thresh)return'<span class="tc-dn">↓</span>';
    return'<span class="tc-fl">→</span>';
  }}

  var avgCal=Math.round(avgOf(recent,'calories'));
  var avgPro=Math.round(avgOf(recent,'protein'));
  var calT=targets&&targets.calories;
  var proT=targets&&targets.protein;

  // Calorie trend: compare last 2 vs prior days
  var last2Cal=recent.length>=2?Math.round((recent[recent.length-1].calories+recent[recent.length-2].calories)/2):avgCal;
  var prior3Cal=recent.length>=3?Math.round(avgOf(recent.slice(0,-2),'calories')):avgCal;
  var calDelta=last2Cal-prior3Cal;
  var calArrow=arrow(calDelta,50);
  var calSub=calT?(avgCal.toLocaleString()+'/'+calT.toLocaleString()+' target'):(avgCal.toLocaleString()+' avg');

  // Protein trend
  var last2Pro=recent.length>=2?Math.round((recent[recent.length-1].protein+recent[recent.length-2].protein)/2):avgPro;
  var prior3Pro=recent.length>=3?Math.round(avgOf(recent.slice(0,-2),'protein')):avgPro;
  var proDelta=last2Pro-prior3Pro;
  var proArrow=arrow(proDelta,5);
  var proSub=proT?(avgPro+'g/'+proT+'g target'):(avgPro+'g avg');

  // Weight trend: last two weight entries (API already oldest→newest)
  var wArr=(weights||[]).slice(-5);
  var wtHtml='—';var wtSub='no weigh-ins';var wtArrow='';
  if(wArr.length>=2){{
    var oldest=wArr[0].lbs,newest=wArr[wArr.length-1].lbs;
    var wDelta=newest-oldest;
    wtHtml=newest.toFixed(1);
    wtSub=(wDelta>=0?'+':'')+wDelta.toFixed(1)+' lb over '+wArr.length+' entries';
    wtArrow=arrow(wDelta,0.2);
  }}else if(wArr.length===1){{
    wtHtml=wArr[0].lbs.toFixed(1);wtSub='1 weigh-in';
  }}

  strip.innerHTML=
    '<div class="tcell">'+
      '<div class="tc-lbl">Calories</div>'+
      '<div class="tc-val">'+calArrow+' '+avgCal.toLocaleString()+'</div>'+
      '<div class="tc-sub">'+esc(calSub)+'</div>'+
    '</div>'+
    '<div class="tcell">'+
      '<div class="tc-lbl">Protein</div>'+
      '<div class="tc-val">'+proArrow+' '+avgPro+'g</div>'+
      '<div class="tc-sub">'+esc(proSub)+'</div>'+
    '</div>'+
    '<div class="tcell">'+
      '<div class="tc-lbl">Weight</div>'+
      '<div class="tc-val">'+wtArrow+' '+esc(String(wtHtml))+'</div>'+
      '<div class="tc-sub">'+esc(wtSub)+'</div>'+
    '</div>';

  wrap.style.display='block';
}}

// ── Settings: Reminders ───────────────────────────────────────────────────
var _REMIND_DESCS={{
  none:'Morning only',
  light:'Morning & evening',
  moderate:'A few times a day',
  heavy:'All day',
}};
// Shown under the reminders toggle when it's ON but a durable scheduler gate is
// silently blocking delivery (reminders_blocked_reason from the stats payload).
var _REMIND_BLOCKED_MSGS={{
  no_timezone:'Tell Arnie your city to start getting check-ins',
  not_on_allowlist:'Reminders are paused for your account',
  linked_secondary:'Check-ins come to your other linked chat',
  globally_off:'Reminders are temporarily paused',
}};
var _FOOD_DESCS={{
  quick:'Logs fast, rarely asks',
  moderate:'Asks on big swings',
  strict:'Always confirms portions',
}};

var _REMIND_TIERS=['none','light','moderate','heavy'];
var _FOOD_TIERS=['quick','moderate','strict'];
var _COACH_TIERS=['supportive','balanced','strict'];
var _COACH_DESCS={{
  supportive:'Encouraging and empathetic — motivates without pressure',
  balanced:'Mix of support and accountability',
  strict:'Direct, data-focused, holds you to your targets',
}};

function _setTicks(wrapId,idx){{
  var wrap=document.getElementById(wrapId);
  if(!wrap)return;
  var ticks=wrap.querySelectorAll('.pref-tick');
  for(var i=0;i<ticks.length;i++)ticks[i].classList.toggle('active',i===idx);
}}

function renderRemindSettings(p){{
  var on=!!p.reminders_on;
  var blocked=p.reminders_blocked_reason||null;
  var tog=document.getElementById('remind-toggle');
  if(tog)tog.checked=on;
  var freq=p.reminder_frequency||'moderate';
  var idx=Math.max(0,_REMIND_TIERS.indexOf(freq));
  var rng=document.getElementById('remind-range');
  // Keep the toggle ON (it honestly reflects the saved opt-in) but dim the
  // frequency control when a durable gate is blocking delivery — the slider
  // can't change anything until the block clears.
  if(rng){{rng.value=idx;rng.disabled=!on||!!blocked;}}
  // Dim the whole card now that the toggle moved out into the title row.
  // (Was the inner #remind-freq-wrap; that wrapper no longer exists.)
  var card=document.getElementById('remind-card');
  if(card)card.style.opacity=(on&&!blocked)?'1':'.4';
  _setTicks('remind-ticks',idx);
  var desc=document.getElementById('remind-desc');
  if(desc)desc.textContent=(on&&blocked)?(_REMIND_BLOCKED_MSGS[blocked]||'')
                                         :(_REMIND_DESCS[freq]||'');
}}

function renderFoodModeSettings(p){{
  var mode=p.food_logging_mode||'moderate';
  var idx=Math.max(0,_FOOD_TIERS.indexOf(mode));
  var rng=document.getElementById('food-mode-range');
  if(rng)rng.value=idx;
  _setTicks('food-mode-ticks',idx);
  var desc=document.getElementById('food-mode-desc');
  if(desc)desc.textContent=_FOOD_DESCS[mode]||'';
}}
function renderCoachingStyleSettings(p){{
  var style=p.coaching_style||'balanced';
  var idx=Math.max(0,_COACH_TIERS.indexOf(style));
  var rng=document.getElementById('coach-style-range');
  if(rng)rng.value=idx;
  _setTicks('coach-style-ticks',idx);
  var desc=document.getElementById('coach-style-desc');
  if(desc)desc.textContent=_COACH_DESCS[style]||'';
}}

// Live preview while dragging (no save)
function onRemindSlide(v){{
  var tier=_REMIND_TIERS[+v]||'moderate';
  _setTicks('remind-ticks',+v);
  var desc=document.getElementById('remind-desc');
  if(desc)desc.textContent=_REMIND_DESCS[tier]||'';
}}
function onFoodSlide(v){{
  var tier=_FOOD_TIERS[+v]||'moderate';
  _setTicks('food-mode-ticks',+v);
  var desc=document.getElementById('food-mode-desc');
  if(desc)desc.textContent=_FOOD_DESCS[tier]||'';
}}
function onCoachSlide(v){{
  var tier=_COACH_TIERS[+v]||'balanced';
  _setTicks('coach-style-ticks',+v);
  var desc=document.getElementById('coach-style-desc');
  if(desc)desc.textContent=_COACH_DESCS[tier]||'';
}}

async function _patchPref(field,value){{
  try{{
    await fetch('/api/profile/'+TOKEN,{{
      method:'PATCH',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{field:field,value:value}}),
    }});
  }}catch(e){{}}
}}

async function saveRemindOn(checked){{
  if(_baseData&&_baseData.profile)_baseData.profile.reminders_on=checked;
  var rng=document.getElementById('remind-range');
  if(rng)rng.disabled=!checked;
  // Dim the card — was #remind-freq-wrap, now the card itself since the
  // toggle moved into the title row above.
  var card=document.getElementById('remind-card');
  if(card)card.style.opacity=checked?'1':'.4';
  await _patchPref('proactive_messaging_enabled',checked?'true':'false');
}}

// Commit on release
function commitRemindSlide(v){{
  var tier=_REMIND_TIERS[+v]||'moderate';
  if(_baseData&&_baseData.profile)_baseData.profile.reminder_frequency=tier;
  _patchPref('reminder_frequency',tier);
}}
function commitFoodSlide(v){{
  var tier=_FOOD_TIERS[+v]||'moderate';
  if(_baseData&&_baseData.profile)_baseData.profile.food_logging_mode=tier;
  _patchPref('food_logging_mode',tier);
}}
function commitCoachSlide(v){{
  var tier=_COACH_TIERS[+v]||'balanced';
  if(_baseData&&_baseData.profile)_baseData.profile.coaching_style=tier;
  _patchPref('coaching_style',tier);
}}

// ── Day tab ───────────────────────────────────────────────────────────────
// ── Macro energy ring ─────────────────────────────────────────────────────
var _macroRing=null;
function renderMacroRing(day){{
  var p=day.protein||0, c=day.carbs||0, f=day.fats||0;
  var pCal=Math.round(p*4), cCal=Math.round(c*4), fCal=Math.round(f*9);
  var macroCal=pCal+cCal+fCal;
  // Total mirrors the Calories tile above. Logged calories are the source of
  // truth (coach/USDA owned, stored per entry), NOT re-derived from macros.
  // The gap vs the macro sum (fiber, alcohol, rounding) becomes an "Other" slice
  // so the ring always adds up to the same number shown in the tile.
  var total=(day.calories!=null)?day.calories:macroCal;
  var other=total-macroCal;
  var showOther=other>=5;

  var lg=document.getElementById('macro-legend');
  if(lg) lg.innerHTML=
    '<div class="mleg"><div class="mleg-dot" style="background:#3b82f6"></div>'+
      '<span class="mleg-lbl">Protein</span><div><span class="mleg-val">'+p+'g</span> <span class="mleg-sub">'+pCal+' kcal</span></div></div>'+
    '<div class="mleg"><div class="mleg-dot" style="background:#f59e0b"></div>'+
      '<span class="mleg-lbl">Carbs</span><div><span class="mleg-val">'+c+'g</span> <span class="mleg-sub">'+cCal+' kcal</span></div></div>'+
    '<div class="mleg"><div class="mleg-dot" style="background:#ec4899"></div>'+
      '<span class="mleg-lbl">Fats</span><div><span class="mleg-val">'+f+'g</span> <span class="mleg-sub">'+fCal+' kcal</span></div></div>'+
    (showOther?('<div class="mleg"><div class="mleg-dot" style="background:#6b7280"></div>'+
      '<span class="mleg-lbl">Other</span><div><span class="mleg-sub">'+other+' kcal</span></div></div>'):'')+
    '<hr class="macro-divider">'+
    '<div class="mleg"><span class="mleg-lbl" style="color:var(--tx);font-weight:700">Total</span>'+
      '<span class="mleg-val">'+total+' kcal</span></div>';

  if(_macroRing) _macroRing.destroy();
  var canvas=document.getElementById('macroRing');if(!canvas)return;
  var empty=!total;
  var ringData=empty?[1]:(showOther?[pCal||0.01,cCal||0.01,fCal||0.01,other]:[pCal||0.01,cCal||0.01,fCal||0.01]);
  var ringColors=empty?['var(--sf2)']:(showOther?['#3b82f6','#f59e0b','#ec4899','#6b7280']:['#3b82f6','#f59e0b','#ec4899']);
  _macroRing=new Chart(canvas,{{
    type:'doughnut',
    data:{{datasets:[{{
      data:ringData,
      backgroundColor:ringColors,
      borderWidth:0,borderRadius:empty?0:4,
    }}]}},
    options:{{
      responsive:true,
      maintainAspectRatio:true,
      cutout:'70%',
      plugins:{{legend:{{display:false}},tooltip:{{enabled:false}}}},
      animation:{{duration:empty?0:600,easing:'easeInOutQuart'}},
    }}
  }});
}}

// ── 28-day consistency heatmap ────────────────────────────────────────────
function renderHeatmap(history,targets){{
  var grid=document.getElementById('heat-grid');if(!grid)return;
  var today=new Date();today.setHours(0,0,0,0);
  var calT=targets.calories,html='';
  // Build 28-day cell array (oldest first)
  var cells=[];
  for(var i=27;i>=0;i--){{
    var d=new Date(today);d.setDate(d.getDate()-i);
    var ds=_localDate(d);
    var log=history.find(function(h){{return h.date===ds;}})||null;
    cells.push({{ds:ds,log:log,isToday:i===0}});
  }}
  // Monday-anchor: pad empty cells so first day lands in correct column
  // JS getDay(): 0=Sun,1=Mon,2=Tue,...,6=Sat → Mon-anchored: (getDay()+6)%7
  var firstDay=new Date(today);firstDay.setDate(firstDay.getDate()-27);
  var startCol=(firstDay.getDay()+6)%7;
  for(var p=0;p<startCol;p++){{
    html+='<div class="hcell" style="visibility:hidden;pointer-events:none"></div>';
  }}
  cells.forEach(function(cell){{
    var cls='hcell';
    var tt=cell.ds;
    if(cell.log){{
      var onT=calT&&cell.log.calories>=calT*.85&&cell.log.calories<=calT*1.12;
      cls+=(onT?' h-on':' h-off');
      tt=cell.ds+': '+cell.log.calories+'cal'+(cell.log.workout?' 💪':'');
    }}
    if(cell.isToday)cls+=' h-today';
    var woDot=(cell.log&&cell.log.workout)?'<div class="hcell-wo"></div>':'';
    html+='<div class="'+cls+'" title="'+tt+'">'+woDot+'</div>';
  }});
  grid.innerHTML=html;
}}

// ── Goal progress tracker ─────────────────────────────────────────────────
function renderGoalProgress(profile,weights){{
  var card=document.getElementById('goal-card');if(!card)return;
  var cur=profile.current_weight_lbs,goal=profile.goal_weight_lbs;
  if(!cur||!goal){{card.style.display='none';return;}}
  card.style.display='';
  var startW=weights&&weights.length?weights[0].lbs:cur;
  var totalChg=Math.abs(startW-goal);
  var pct=totalChg>0?Math.min(100,Math.abs(startW-cur)/totalChg*100):0;
  var lbsLeft=Math.abs(cur-goal).toFixed(1);
  var an=profile.analytics||{{}};
  var cutting=goal<cur;
  var etaStr=an.weeks_to_goal?'~'+Math.round(an.weeks_to_goal)+' weeks to goal':'';
  var paceStr=an.daily_vs_tdee?(an.daily_vs_tdee>0?'+':'')+an.daily_vs_tdee+' cal/day vs TDEE':'';
  var subStr=[etaStr,paceStr].filter(Boolean).join(' · ');

  card.innerHTML=
    '<div class="goal-header">'+
      '<div><div class="goal-title">'+(cutting?'⬇':'⬆')+' '+lbsLeft+' lbs to goal</div>'+
      '<div class="goal-sub">'+esc(subStr)+'</div></div>'+
      '<div class="goal-current"><div class="goal-lbs">'+cur+'</div>'+
      '<div class="goal-lbs-lbl">lbs now</div></div>'+
    '</div>'+
    '<div class="goal-track">'+
      '<div class="goal-fill" style="width:'+pct.toFixed(1)+'%"></div>'+
      '<div class="goal-pin" style="left:0;background:#555"></div>'+
      '<div class="goal-pin" style="left:'+pct.toFixed(1)+'%;background:var(--ac)"></div>'+
      '<div class="goal-pin" style="left:100%;background:var(--bl)"></div>'+
    '</div>'+
    '<div class="goal-labels">'+
      '<span>'+startW.toFixed(1)+' lb</span>'+
      '<span style="color:var(--ac)">'+cur+' ← now</span>'+
      '<span>'+goal+' lb</span>'+
    '</div>';
}}

// ── Streak & stats tiles ──────────────────────────────────────────────────
function renderStreakStats(history,targets){{
  var today=new Date();today.setHours(0,0,0,0);
  var logDates=new Set(history.map(function(h){{return h.date;}}));
  var streak=0,check=new Date(today);
  while(true){{
    var ds=_localDate(check);
    if(logDates.has(ds)){{streak++;check.setDate(check.getDate()-1);}}else break;
  }}
  // Period-aware: workouts + avg cal count over _trendsPeriod days so the
  // tile reflects whatever the chip selector is showing above.
  var windowDays=_trendsPeriod||30;
  var winAgo=new Date(today);winAgo.setDate(winAgo.getDate()-windowDays);
  var winStr=_localDate(winAgo);
  var workouts=history.filter(function(h){{return h.date>=winStr&&h.workout;}}).length;
  // Past days only — today's totals are still moving. No open/closed state any more.
  var todayStr=_localDate(today);
  var past=history.filter(function(h){{return h.date>=winStr&&h.date<todayStr;}});
  var avgCal=past.length?Math.round(past.reduce(function(s,h){{return s+h.calories;}},0)/past.length):null;

  var el=document.getElementById('stat-streak');if(el)el.textContent=streak;
  el=document.getElementById('stat-workouts');if(el)el.textContent=workouts;
  el=document.getElementById('stat-avg-cal');if(el)el.textContent=avgCal?avgCal.toLocaleString():'—';
}}

function renderPageHead(d){{
  var pt=document.getElementById('ph-title');
  var ps=document.getElementById('ph-sub');
  if(!pt||!ps)return;
  // Brand-forward header: ArnieOS logotype as the title; subtitle just
  // shows day-of-week · date. Goal + name pills retired — the user's
  // goal is implicit in the dashboard's tone (cut shows weight module,
  // etc.) and their name is in the streak chip's title attribute. Less
  // clutter, more breath.
  var now=new Date();
  pt.innerHTML = '<span class="logo-arnie">Arnie</span><span class="logo-os">OS</span>';
  var dayName  = now.toLocaleDateString('en-US',{{weekday:'long'}});
  var shortDate= now.toLocaleDateString('en-US',{{month:'short',day:'numeric'}});
  ps.innerHTML =
    '<span>'+esc(dayName)+'</span>'+
    '<span class="ph-dot">·</span>'+
    '<span>'+esc(shortDate)+'</span>';
}}

function toggleLogSection(type){{
  var sec=document.getElementById(type+'-section');
  if(!sec)return;
  // On desktop chevrons are hidden and sections stay open
  if(window.innerWidth>700)return;
  var wasCollapsed=sec.classList.contains('collapsed');
  sec.classList.toggle('collapsed');
  // If expanding and add form is open, close it to avoid double-animation
  if(wasCollapsed){{
    var form=document.getElementById(type+'-form');
    var btn=document.getElementById(type+'-toggle');
    if(form&&form.style.display!=='none'){{
      form.style.display='none';
      if(btn)btn.classList.remove('open');
    }}
  }}
}}

function initLogSections(){{
  // Sections start expanded — chevron is still available to collapse manually
}}

function toggleAddForm(type){{
  var form=document.getElementById(type+'-form');
  var btn=document.getElementById(type+'-toggle');
  if(!form||!btn)return;
  var open=form.style.display==='none'||!form.style.display;
  form.style.display=open?'block':'none';
  btn.classList.toggle('open',open);
  if(open){{
    setTimeout(function(){{
      var first=form.querySelector('input');
      if(first){{form.scrollIntoView({{behavior:'smooth',block:'nearest'}});first.focus();}}
    }},60);
  }}
}}

// ── Log food (inline forms) ───────────────────────────────
async function submitFoodInline(){{
  var name=(document.getElementById('food-name').value||'').trim();
  if(!name){{document.getElementById('food-name').focus();return;}}
  var btn=document.getElementById('food-submit');
  btn.textContent='Saving…';btn.disabled=true;
  try{{
    var body={{
      name,
      quantity:(document.getElementById('food-qty').value||'').trim()||null,
      calories:parseFloat(document.getElementById('food-cal').value)||0,
      protein:parseFloat(document.getElementById('food-pro').value)||0,
      carbs:parseFloat(document.getElementById('food-carb').value)||0,
      fats:parseFloat(document.getElementById('food-fat').value)||0,
      estimated:true,
      log_date:_viewingDate!==_todayStr?_viewingDate:undefined,
    }};
    var r=await fetch('/api/food/log?token='+TOKEN,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
    if(!r.ok)throw new Error('HTTP '+r.status);
    // clear form
    ['food-name','food-qty','food-cal','food-pro','food-carb','food-fat'].forEach(id=>{{document.getElementById(id).value='';}});
    toggleAddForm('food');
    delete _dayCache[_viewingDate];
    await loadDayData(_viewingDate);
  }}catch(e){{alert('Failed to save: '+e.message);}}
  finally{{btn.textContent='+ Add food';btn.disabled=false;}}
}}

// ── Log workout ───────────────────────────────────────────
async function submitExerciseInline(){{
  var name=(document.getElementById('ex-name').value||'').trim();
  if(!name){{document.getElementById('ex-name').focus();return;}}
  var btn=document.getElementById('ex-submit');
  btn.textContent='Saving…';btn.disabled=true;
  try{{
    var sets=parseInt(document.getElementById('ex-sets').value)||null;
    var reps=(document.getElementById('ex-reps').value||'').trim()||null;
    var wt=parseFloat(document.getElementById('ex-wt').value)||null;
    var dur=parseFloat(document.getElementById('ex-dur').value)||null;
    var isCardio=document.getElementById('ex-cardio').checked;
    var body={{name,sets,reps,weight_lbs:wt,duration_minutes:dur,is_cardio:isCardio,
      log_date:_viewingDate!==_todayStr?_viewingDate:undefined}};
    var r=await fetch('/api/exercise/log?token='+TOKEN,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
    if(!r.ok)throw new Error('HTTP '+r.status);
    ['ex-name','ex-sets','ex-reps','ex-wt','ex-dur'].forEach(id=>{{document.getElementById(id).value='';}});
    document.getElementById('ex-cardio').checked=false;
    toggleAddForm('ex');
    delete _dayCache[_viewingDate];
    await loadDayData(_viewingDate);
  }}catch(e){{alert('Failed to save: '+e.message);}}
  finally{{btn.textContent='+ Add workout';btn.disabled=false;}}
}}

// Insights tile — true toggle. Tap once opens the inline panel (and
// scrolls it into view); tap again collapses it. Reuses production
// toggleInsights('day') so all the fetch / refresh / streaming logic
// stays unchanged.
function handleInsightsTile(){{
  var banner = document.getElementById('ins-day');
  if(!banner) return;
  var wasOpen = banner.classList.contains('open');
  try{{ toggleInsights('day'); }}catch(e){{}}
  if(!wasOpen){{ banner.scrollIntoView({{behavior:'smooth', block:'center'}}); }}
}}

// Workout / Cardio tiles — opens the existing #ex-form (add-workout
// form already in the Workouts section), expands the form if it's
// collapsed, pre-checks the cardio checkbox when "cardio" is requested,
// scrolls the form into view, and focuses the exercise name input so
// the user can start typing immediately. One handler covers both tiles.
function openLogActivity(kind){{
  var form = document.getElementById('ex-form');
  if(!form) return;
  // Make sure the Workouts section is expanded (it can be collapsed on
  // mobile). If we have a toggle helper, use it; else show directly.
  var section = document.getElementById('ex-section');
  if(section && section.classList.contains('collapsed')){{
    try{{ toggleLogSection('ex'); }}catch(e){{}}
  }}
  // Reveal the form (it may be hidden by display:none).
  if(form.style.display === 'none' || !form.style.display){{
    try{{ toggleAddForm('ex'); }}catch(e){{ form.style.display=''; }}
  }}
  var cb = document.getElementById('ex-cardio');
  if(cb) cb.checked = (kind === 'cardio');
  form.scrollIntoView({{behavior:'smooth', block:'center'}});
  var nameInput = document.getElementById('ex-name');
  if(nameInput) setTimeout(function(){{ nameInput.focus(); }}, 350);
}}

// Macro Consumed / Remaining toggle — flips the macro strip between
// what's been eaten (default) and what's left vs target. Choice persists
// in localStorage so the user's preference survives reloads / tab swaps.
// Snapshots the last-rendered consumed values so the toggle is fully
// client-side (no extra API call). The macro renderer below repopulates
// the snapshot every time it draws, so toggling stays correct as the day
// progresses and new entries land.
var _macroView = localStorage.getItem('arnie-macro-view') || 'consumed';
var _macroSnap = {{cal:null, pro:null, carb:null, fat:null,
                   tCal:null, tPro:null, tCarb:null, tFat:null}};

function toggleMacroView(){{
  _macroView = (_macroView === 'consumed') ? 'remaining' : 'consumed';
  localStorage.setItem('arnie-macro-view', _macroView);
  applyMacroView();
}}

function applyMacroView(){{
  var btn = document.getElementById('macro-toggle');
  var lbl = document.getElementById('macro-toggle-lbl');
  if(!btn || !lbl) return;
  var rem = _macroView === 'remaining';
  btn.classList.toggle('remaining', rem);
  lbl.textContent = rem ? 'Remaining' : 'Consumed';

  var s = _macroSnap;
  function setCell(numId, subId, val, tgt, color){{
    var nEl = document.getElementById(numId);
    var sEl = document.getElementById(subId);
    if(!nEl) return;
    if(val == null){{ nEl.textContent='—'; if(sEl) sEl.textContent=''; return; }}
    if(rem){{
      if(tgt == null){{
        nEl.textContent = '—';
        if(sEl) sEl.textContent = 'no target';
      }}else{{
        var left = Math.max(0, tgt - val);
        nEl.textContent = (numId === 'cal-val') ? left.toLocaleString() : (left + 'g');
        // Per-tile label — old code hardcoded "protein left" for every
        // non-calorie tile, which read wrong for carbs/fats once those
        // targets started getting populated.
        if(sEl){{
          var _leftLbl = {{'cal-val':'calories left',
                          'pro-val':'protein left',
                          'carb-val':'carbs left',
                          'fat-val':'fat left'}}[numId] || 'left';
          sEl.textContent = _leftLbl;
        }}
      }}
    }}else{{
      nEl.textContent = (numId === 'cal-val') ? val.toLocaleString() : (val + 'g');
      if(sEl){{
        if(tgt) sEl.textContent = '/ ' + (numId === 'cal-val' ? tgt.toLocaleString() : tgt+'g') + ' (' + Math.round(val/tgt*100) + '%)';
        else    sEl.textContent = (numId === 'cal-val') ? 'kcal' : 'grams';
      }}
    }}
  }}
  setCell('cal-val', 'cal-sub', s.cal, s.tCal);
  setCell('pro-val', 'pro-sub', s.pro, s.tPro);
  // Carbs/Fats only meaningful in consumed mode (no targets usually); in
  // remaining mode we just show "—" with a "no target" sub.
  setCell('carb-val','carb-sub', s.carb, s.tCarb);
  setCell('fat-val', 'fat-sub',  s.fat,  s.tFat);
}}

// Streak chip — only surfaced when ≥ STREAK_MIN_DAYS so new users never
// see "1 d" / "2 d" (premature gamification). Driven entirely by the
// server-computed profile.streak_days from /api/stats.
var STREAK_MIN_DAYS = 3;
function renderStreakChip(d){{
  var chip = document.getElementById('streak-chip');
  if(!chip) return;
  var days = (d && d.profile && d.profile.streak_days) || 0;
  if(days < STREAK_MIN_DAYS){{ chip.style.display='none'; return; }}
  chip.style.display = '';
  var n = document.getElementById('streak-num'); if(n) n.textContent = String(days);
  chip.title = days + '-day logging streak';
}}
function handleStreakTap(){{
  // No-op for now; production may surface a popover with the last 14 days
  // as filled / empty dots. Toast is intentionally minimal.
  var chip = document.getElementById('streak-chip');
  if(!chip) return;
  var days = chip.querySelector('#streak-num');
  var txt = (days ? days.textContent : '') + '-day logging streak';
  console.log(txt);
}}

// Weight Module — cut/bulk only. Computes delta from earliest weigh-in
// to most recent, and percent traversal toward goal_weight_lbs. Falls
// back to profile.current_weight_lbs when the weights[] array is empty
// (new users, or users who haven't logged a weigh-in to the dashboard
// yet) — that way the module still surfaces the goal context as soon
// as a goal is set, instead of waiting for the first weigh-in. Hides
// entirely for maintain/performance/health goals.
function renderWeightModule(d){{
  var module = document.getElementById('weight-module');
  if(!module) return;
  var p = (d && d.profile) || {{}};
  var goal = p.primary_goal || '';
  var eligible = goal === 'cut' || goal === 'bulk';
  if(!eligible){{ module.style.display='none'; return; }}
  var weights = (d && d.weights) || [];
  var fallbackWeight = p.current_weight_lbs;
  // Hide only when we have NEITHER a weigh-in history NOR a profile weight.
  if(!weights.length && !fallbackWeight){{ module.style.display='none'; return; }}
  module.style.display = '';

  var hasHistory = weights.length > 0;
  var current = hasHistory ? weights[weights.length-1].lbs : fallbackWeight;
  var start = hasHistory ? weights[0].lbs : current;  // 0 delta when no history
  var delta = current - start;
  var isCut = goal === 'cut';
  // "down" class = going the right direction (accent green), "up" = wrong
  // direction (orange), "flat" = no meaningful change. Class name reflects
  // semantic, not literal arrow direction.
  var goingRightWay = (isCut && delta < 0) || (!isCut && delta > 0);
  var deltaCls = Math.abs(delta) < 0.2 ? 'flat' : (goingRightWay ? 'down' : 'up');

  var valEl = document.getElementById('wm-val');
  if(valEl) valEl.textContent = current.toFixed(1);

  var deltaEl = document.getElementById('wm-delta');
  if(hasHistory){{
    if(deltaEl){{ deltaEl.className = 'wm-delta ' + deltaCls; deltaEl.style.display=''; }}
    var arrowEl = document.getElementById('wm-delta-arrow');
    if(arrowEl) arrowEl.textContent = Math.abs(delta) < 0.2 ? '→' : (delta < 0 ? '↓' : '↑');
    var dvEl = document.getElementById('wm-delta-val');
    if(dvEl) dvEl.textContent = Math.abs(delta).toFixed(1) + ' lbs';
  }}else{{
    // No weigh-in history yet — hide the delta line so we don't show
    // "→ 0.0 lbs from start" which reads confusingly.
    if(deltaEl) deltaEl.style.display='none';
  }}

  var goalLbs = p.goal_weight_lbs;
  var subEl = document.getElementById('wm-sub');
  var fillEl = document.getElementById('wm-fill');
  var barWrap = document.getElementById('wm-bar-wrap');
  if(goalLbs){{
    // Goal set → show distance-to-goal + progress bar.
    var totalDistance = Math.abs(start - goalLbs);
    var traveled = Math.abs(start - current);
    var remaining = Math.max(0, Math.abs(current - goalLbs));
    var pctv = totalDistance ? Math.max(0, Math.min(100, (traveled/totalDistance)*100)) : 0;

    // ETA chip — server-computed weeks_to_goal turned into a projected date.
    // Only surfaced when the user is moving the right direction at a non-zero
    // pace; otherwise the date would be misleading (or infinite).
    var an = p.analytics || {{}};
    var paceLabel = an.pace_label || '';
    var rightWay = (isCut && paceLabel === 'deficit') || (!isCut && paceLabel === 'surplus');
    var etaChip = '';
    if(an.weeks_to_goal && an.weeks_to_goal > 0 && rightWay){{
      var eta = new Date();
      eta.setDate(eta.getDate() + an.weeks_to_goal * 7);
      var MOS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      var label = MOS[eta.getMonth()] + ' ' + eta.getDate();
      // Year suffix only when projection crosses into a later calendar year —
      // keeps the chip terse for near-term goals, unambiguous for long ones.
      var nowYr = new Date().getFullYear();
      if(eta.getFullYear() !== nowYr) label += " '" + String(eta.getFullYear()).slice(2);
      var paceTxt = an.pace_lbs_per_week ? an.pace_lbs_per_week + ' lb/wk' : '';
      var tip = 'Projected goal date at ' + paceTxt + ' ' + paceLabel +
                ' · updates with your weigh-ins and target';
      etaChip = ' <span class="wm-eta" title="' + esc(tip) + '">~' + label + '</span>';
    }}else if(an.weeks_to_goal === 0 || (goalLbs && remaining < 0.5)){{
      etaChip = ' <span class="wm-eta" title="Goal hit">goal ✓</span>';
    }}else if(an.daily_vs_tdee != null && !rightWay && Math.abs(an.daily_vs_tdee) > 50){{
      // User is going the wrong way (cutting on a surplus, or bulking on a
      // deficit). Don't pretend ETA is calculable — flag it so they know.
      etaChip = ' <span class="wm-eta off" title="Current cal target is moving you away from goal">off-pace</span>';
    }}

    if(subEl){{
      subEl.innerHTML = remaining.toFixed(1) + ' to go &nbsp;→&nbsp; ' + goalLbs.toFixed(1) + etaChip;
      subEl.style.cursor = '';
      subEl.onclick = null;
    }}
    if(barWrap) barWrap.style.display = '';
    if(fillEl) fillEl.style.width = pctv + '%';
  }}else{{
    // No goal weight set → bar would be meaningless. Hide it entirely and
    // show a tappable prompt to add one. Tap routes to the Profile tab
    // where the goal-weight field lives.
    if(barWrap) barWrap.style.display = 'none';
    if(subEl){{
      subEl.innerHTML = 'Set a goal weight in <span style="color:var(--ac)">Profile →</span>';
      subEl.style.cursor = 'pointer';
      subEl.onclick = function(){{ try{{ switchTab('profile'); }}catch(e){{}} }};
    }}
  }}

  // Pending indicator: cut/bulk users who haven't weighed in today get a
  // pulsing dot inline with the WEIGHT label. Toggled via .has-pending on
  // the module (the whole module is the tap target now — no separate Log
  // button). Only meaningful when viewing today; past days are immutable
  // and the dot would just confuse.
  if(module){{
    var loggedToday = false;
    for(var i=0;i<weights.length;i++){{
      if(weights[i] && weights[i].date === _todayStr){{ loggedToday = true; break; }}
    }}
    var showPending = (_viewingDate === _todayStr) && !loggedToday;
    module.classList.toggle('has-pending', showPending);
    module.title = showPending
      ? 'Tap to log today\\'s weight' : 'Tap to update today\\'s weight';
    // Keep the input pre-populated with the most recent reading so a quick
    // tap-and-save doesn't require typing the digits over again.
    var inp = document.getElementById('wm-logform-val');
    if(inp && !inp.value){{
      var unit = _weightLogUnit || 'lbs';
      inp.value = unit === 'kg' ? (current/2.20462).toFixed(1) : current.toFixed(1);
    }}
  }}
}}

// ── Weight log form (compact inline) ──────────────────────────
// Single shared unit state across renders. lbs is the default because the
// dashboard renders weights in lbs everywhere else; user can flip per-input.
var _weightLogUnit = 'lbs';
function setWeightLogUnit(u){{
  if(u !== 'kg' && u !== 'lbs') return;
  var inp = document.getElementById('wm-logform-val');
  // Convert the current input value so the user doesn't lose their typing
  // when they flip units mid-entry.
  if(inp && inp.value){{
    var v = parseFloat(inp.value);
    if(!isNaN(v)){{
      if(_weightLogUnit === 'lbs' && u === 'kg') inp.value = (v/2.20462).toFixed(1);
      if(_weightLogUnit === 'kg' && u === 'lbs') inp.value = (v*2.20462).toFixed(1);
    }}
  }}
  _weightLogUnit = u;
  var lbsBtn = document.getElementById('wm-unit-lbs');
  var kgBtn  = document.getElementById('wm-unit-kg');
  if(lbsBtn) lbsBtn.classList.toggle('active', u === 'lbs');
  if(kgBtn)  kgBtn.classList.toggle('active', u === 'kg');
}}
function toggleWeightLogForm(ev){{
  // Whole module is the tap target now. Form interactions stopPropagation
  // upstream so clicks inside the input/toggle/save don't re-toggle the form.
  var form = document.getElementById('wm-logform');
  var module = document.getElementById('weight-module');
  if(!form || !module) return;
  var willOpen = !form.classList.contains('open');
  form.classList.toggle('open', willOpen);
  module.classList.toggle('wm-open', willOpen);
  if(willOpen){{
    var inp = document.getElementById('wm-logform-val');
    if(inp){{ inp.focus(); inp.select && inp.select(); }}
  }}
}}
async function submitWeightLog(){{
  var inp = document.getElementById('wm-logform-val');
  var btn = document.getElementById('wm-logform-save');
  if(!inp || !btn) return;
  var raw = parseFloat(inp.value);
  if(isNaN(raw) || raw <= 0){{ inp.focus(); return; }}
  // Sanity bounds — generous, just to catch typos like a stray digit. Convert
  // before bounds-check so kg entries don't trip the lbs ceiling.
  var lbs = _weightLogUnit === 'kg' ? raw * 2.20462 : raw;
  if(lbs < 50 || lbs > 900){{
    alert('That weight looks off — double-check the number and unit.');
    return;
  }}
  btn.disabled = true;
  var originalLabel = btn.textContent;
  btn.textContent = 'Saving…';
  try{{
    var r = await fetch('/api/weight/log?token=' + TOKEN, {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ weight: raw, unit: _weightLogUnit }}),
    }});
    if(!r.ok) throw new Error('HTTP ' + r.status);
    weightCelebrate();
    // Clear the input so the next render re-populates it with the freshly
    // logged reading. Close the form. Then refresh the day so the module
    // re-renders with the new reading + cleared pending dot.
    inp.value = '';
    setTimeout(function(){{
      var form = document.getElementById('wm-logform');
      var module = document.getElementById('weight-module');
      if(form) form.classList.remove('open');
      if(module) module.classList.remove('wm-open');
    }}, 200);
    delete _dayCache[_viewingDate];
    await loadDayData(_viewingDate);
  }}catch(e){{
    alert('Failed to save: ' + e.message);
  }}finally{{
    btn.disabled = false;
    btn.textContent = originalLabel;
  }}
}}
// Minimal celebrate: a soft accent ring around the module + a 1-beat pulse
// on the weight number + a fading "✓ logged" chip in the top-right. No
// confetti, no sound — the requirement was "super minimal".
function weightCelebrate(){{
  var module = document.getElementById('weight-module');
  var check  = document.getElementById('wm-check');
  if(!module) return;
  module.classList.remove('wm-celebrate');
  // Force reflow so re-adding the class restarts the animation.
  void module.offsetWidth;
  module.classList.add('wm-celebrate');
  if(check){{
    check.classList.remove('show');
    void check.offsetWidth;
    check.classList.add('show');
  }}
  setTimeout(function(){{
    module.classList.remove('wm-celebrate');
    if(check) check.classList.remove('show');
  }}, 1500);
}}

function renderDayTab(d){{
  if(_activeTab==='day') renderPageHead(d);
  renderStreakChip(d);
  renderWeightModule(d);
  var isToday=_viewingDate===_todayStr;
  var day=d.day||{{}},tgt=d.targets||{{}};
  var cp=pct(day.calories,tgt.calories),pp=pct(day.protein,tgt.protein);

  var calEl=document.getElementById('cal-val');
  if(day.calories!=null) countUp(calEl,day.calories);
  else calEl.textContent='—';
  var calSub=document.getElementById('cal-sub');if(calSub)calSub.textContent=tgt.calories?'/ '+tgt.calories+' ('+cp+'%)':'kcal';
  var calBar=document.getElementById('cal-bar');if(calBar)calBar.style.width=cp+'%';

  var proEl=document.getElementById('pro-val');if(proEl)proEl.textContent=day.protein!=null?day.protein+'g':'—';
  var proSub=document.getElementById('pro-sub');if(proSub)proSub.textContent=tgt.protein?'/ '+tgt.protein+'g ('+pp+'%)':'grams';
  var proBar=document.getElementById('pro-bar');if(proBar)proBar.style.width=pp+'%';
  var carbEl=document.getElementById('carb-val');if(carbEl)carbEl.textContent=day.carbs!=null?day.carbs+'g':'—';
  var carbSub=document.getElementById('carb-sub');if(carbSub)carbSub.textContent=tgt.carbs?'/ '+tgt.carbs+'g ('+pct(day.carbs,tgt.carbs)+'%)':'grams';
  var carbBar=document.getElementById('carb-bar');if(carbBar)carbBar.style.width=pct(day.carbs,tgt.carbs)+'%';
  var fatEl=document.getElementById('fat-val');if(fatEl)fatEl.textContent=day.fats!=null?day.fats+'g':'—';
  var fatSub=document.getElementById('fat-sub');if(fatSub)fatSub.textContent=tgt.fats?'/ '+tgt.fats+'g ('+pct(day.fats,tgt.fats)+'%)':'grams';
  var fatBar=document.getElementById('fat-bar');if(fatBar)fatBar.style.width=pct(day.fats,tgt.fats)+'%';
  // Hide the progress bar on macros without a target (carbs/fats) — an empty grey
  // track reads as unfinished UI. Only Calories/Protein carry targets.
  [['cal-bar',tgt.calories],['pro-bar',tgt.protein],['carb-bar',tgt.carbs],['fat-bar',tgt.fats]]
    .forEach(function(x){{var f=document.getElementById(x[0]);if(f)f.parentNode.style.display=x[1]?'':'none';}});

  // Snapshot current macro values + targets so the Consumed/Remaining toggle
  // can flip the display client-side. Re-applied immediately so if the user
  // is in remaining-mode, new data swaps to remaining values instead of
  // briefly flashing the consumed numbers.
  _macroSnap = {{
    cal: day.calories, pro: day.protein, carb: day.carbs, fat: day.fats,
    tCal: tgt.calories, tPro: tgt.protein, tCarb: tgt.carbs, tFat: tgt.fats,
  }};
  applyMacroView();

  // ── Action tiles: Workout / Cardio state ─────────────────────────
  // Only shown when logged for the viewed day — a "✓ logged" confirmation
  // chip, not a permanent nudge. Hidden entirely otherwise.
  function _setActivityTile(tileId, stateId, done){{
    var tile = document.getElementById(tileId);
    var slot = document.getElementById(stateId);
    if(!tile || !slot) return;
    if(done){{
      tile.style.display = '';
      tile.classList.add('done');
      slot.className = 'atile-state';
      slot.textContent = '✓';
    }}else{{
      tile.style.display = 'none';
      tile.classList.remove('done');
    }}
  }}
  _setActivityTile('tile-workout', 'tile-workout-state', !!day.workout_completed);
  _setActivityTile('tile-cardio',  'tile-cardio-state',  !!day.cardio_completed);
  var wb2=document.getElementById('tile-water');
  var wbState=document.getElementById('tile-water-state');
  if(wb2){{
    // Water is opt-in — only show the tile when the user actually logs it,
    // so it's never a permanent "No water" guilt-chip for people who don't
    // track it. When shown, it's full-width below the Workout/Cardio row.
    if(day.water_ml>0){{
      var wAmt=day.water_ml>=1000?(day.water_ml/1000).toFixed(1)+' L':Math.round(day.water_ml)+' ml';
      wb2.style.display='';
      wb2.classList.add('done');
      if(wbState) wbState.textContent = wAmt;
    }}else{{
      wb2.style.display='none';
    }}
  }}

  var fe=day.food_entries||[];
  var flc=document.getElementById('food-log-count');
  if(flc)flc.textContent=fe.length?fe.length+' item'+(fe.length!==1?'s':''):'';
  document.getElementById('food-log').innerHTML=fe.length?fe.map(renderFoodRow).join('')
    :'<div class="lempty">'+(isToday?'Nothing logged yet — tap + to add a meal.':'Nothing logged this day.')+'</div>';
  // EST + photo legend — each line surfaces only when at least one row
  // carries that marker, so users learn the glyph on the day they first
  // encounter it instead of staring at unexplained chrome.
  var _estLeg=document.getElementById('est-legend');
  var _hasEst=fe.some(function(f){{return f.estimated;}});
  var _hasPhoto=fe.some(function(f){{return f.from_photo;}});
  var _legEst=document.getElementById('est-legend-est');
  if(_legEst) _legEst.style.display=_hasEst?'inline-flex':'none';
  var _legPhoto=document.getElementById('est-legend-photo');
  if(_legPhoto) _legPhoto.style.display=_hasPhoto?'inline-flex':'none';
  if(_estLeg) _estLeg.style.display=(_hasEst||_hasPhoto)?'flex':'none';
  var ee=day.exercise_entries||[];
  document.getElementById('ex-log').innerHTML=ee.length?renderGroupedExercises(ee)
    :'<div class="lempty">'+(isToday?'No workouts logged yet — tap + to add one.':'No workouts logged this day.')+'</div>';

  // Whoop module
  var health=d.health||[];
  var snap=health.find(function(h){{return h.date===_viewingDate;}}) || (health.length?health[0]:null);
  renderWhoopModule(snap, d.profile);

  // Arnie's learning progress — uses the stats payload. The 5-day trend
  // strip now lives on the Trends tab; renderWeekTab() calls renderTrendStrip.
  renderLearningProgress(d);
}}

// ── Whoop sync from dashboard ─────────────────────────────────────────────
async function syncWhoop(){{
  var btn=document.getElementById('whoop-sync-btn');
  var grid=document.getElementById('whoop-grid');
  if(btn){{btn.innerHTML='<span class="spin">&#9675;</span>';btn.disabled=true;}}
  if(grid)grid.innerHTML='<div style="color:var(--mu);font-size:13px;padding:8px 0">Syncing…</div>';
  try{{
    var r=await fetch('/api/whoop/sync/'+TOKEN,{{method:'POST'}});
    var data=await r.json();
    if(data.days>0){{
      // Reload day data to get fresh Whoop snapshot
      delete _dayCache[_viewingDate];
      await loadDayData(_viewingDate);
    }}else{{
      if(grid)grid.innerHTML='<div style="color:var(--mu);font-size:13px;padding:8px 0">Whoop has not processed your data yet — try again after 9am, or check that your band synced.</div>';
    }}
  }}catch(e){{
    if(grid)grid.innerHTML='<div style="color:var(--re);font-size:13px;padding:8px 0">Sync failed — try /whoop sync in Telegram.</div>';
  }}finally{{
    if(btn){{btn.innerHTML='&#8635;';btn.disabled=false;}}
  }}
}}

// ── Collapsible health-section helpers (shared by Whoop + Apple Health) ────
function toggleHsec(id){{var el=document.getElementById('hsec-'+id);if(el)el.classList.toggle('open');}}
function hrow(label,val,valColor){{
  if(val==null||val==='')return '';
  return '<div class="inrow"><span class="inlbl">'+esc(label)+'</span>'+
    '<div class="inrow-right"><span class="inval"'+(valColor?' style="color:'+valColor+'"':'')+'>'+
    esc(String(val))+'</span></div></div>';
}}
function hsec(id,name,summary,rows,open){{
  if(!rows)return '';
  return '<div class="hsec'+(open?' open':'')+'" id="hsec-'+id+'">'+
    '<div class="hsec-hd" onclick="toggleHsec(\\''+id+'\\')">'+
    '<span class="hsec-name">'+esc(name)+'</span>'+
    (summary?'<span class="hsec-summary">'+esc(summary)+'</span>':'')+
    '<span class="hsec-chev">&#9658;</span></div>'+
    '<div class="hsec-body">'+rows+'</div></div>';
}}
// Compact cell for the 3-up metric grid (short values).
function hcell(label,val,valColor){{
  if(val==null||val==='')return '';
  return '<div class="wcell"><div class="wcell-lbl">'+esc(label)+'</div>'+
    '<div class="wcell-val"'+(valColor?' style="color:'+valColor+'"':'')+'>'+
    esc(String(val))+'</div></div>';
}}
function grid3(cells){{ return cells?'<div class="wgrid">'+cells+'</div>':''; }}
// On phones, start every wearable section collapsed — a clean stack of tappable
// headers instead of one tall, ragged grid. Desktop keeps Activity open.
function wIsMobile(){{ return (window.innerWidth||document.documentElement.clientWidth||9999)<=520; }}
// Subtle brand hints: Whoop's recovery-ring gauge; Apple's tri-color activity rings.
var WHOOP_MARK='<svg width="15" height="15" viewBox="0 0 24 24" style="display:block">'+
  '<circle cx="12" cy="12" r="8" fill="none" style="stroke:var(--sf2)" stroke-width="3.2"/>'+
  '<circle cx="12" cy="12" r="8" fill="none" style="stroke:var(--ac)" stroke-width="3.2" '+
  'stroke-dasharray="40 12" stroke-linecap="round" transform="rotate(-90 12 12)"/></svg>';
var APPLE_MARK='<svg width="15" height="15" viewBox="0 0 24 24" style="display:block">'+
  '<circle cx="12" cy="12" r="9" fill="none" stroke="#fa114f" stroke-width="2.6"/>'+
  '<circle cx="12" cy="12" r="6" fill="none" stroke="#92e82a" stroke-width="2.6"/>'+
  '<circle cx="12" cy="12" r="3" fill="none" stroke="#1ad4fd" stroke-width="2.6"/></svg>';

// ── Whoop stats module — RESTORED to original pre-edit production
// design: 4 sub-accordions (Activity / Workouts / Recovery / Sleep),
// Whoop-OR-Apple priority, per-device title. The renderWhoopCard /
// renderAppleCard helpers from the preview port have been removed. */
function renderWhoopModule(snap, profile){{
  var mod=document.getElementById('whoop-module');
  var grid=document.getElementById('whoop-grid');
  var dateEl=document.getElementById('whoop-date');
  var titleEl=document.getElementById('health-mod-title');
  var syncBtn=document.getElementById('whoop-sync-btn');
  if(!mod||!grid)return;

  // Whoop takes priority (richer data). Apple Health users get a simple panel.
  if(!profile||!profile.whoop_connected){{
    if(profile&&profile.apple_health_connected){{
      renderAppleHealthModule(snap,mod,grid,dateEl,titleEl,syncBtn);
    }}else{{
      mod.style.display='none';
    }}
    return;
  }}

  if(titleEl)titleEl.textContent='Whoop';
  var brandEl=document.getElementById('health-brand'); if(brandEl)brandEl.innerHTML=WHOOP_MARK;
  if(syncBtn)syncBtn.style.display='';
  mod.style.display='block';

  if(!snap||snap.source!=='whoop'){{
    if(dateEl)dateEl.textContent='';
    grid.innerHTML='<div style="color:var(--mu);font-size:13px;padding:4px 0">No data for this day — tap &#8635; to sync, or check that your Whoop band has synced to the app.</div>';
    return;
  }}

  mod.style.display='block';
  if(dateEl)dateEl.textContent=snap.date||'';

  function fmtSleep(h){{
    if(!h)return null;
    var hrs=Math.floor(h),mins=Math.round((h-hrs)*60);
    return hrs+'h'+(mins>0?' '+mins+'m':'');
  }}

  var recZone=snap.recovery_score!=null?(snap.recovery_score>=67?'Green':snap.recovery_score>=34?'Yellow':'Red'):null;
  var recColor=snap.recovery_score!=null?(snap.recovery_score>=67?'var(--ac)':snap.recovery_score>=34?'var(--ye)':'var(--re)'):null;

  var recovery=grid3(
    hcell('Recovery',snap.recovery_score!=null?snap.recovery_score+'%':null,recColor)+
    hcell('Zone',recZone,recColor)+
    hcell('HRV',snap.hrv!=null?snap.hrv+'ms':null)+
    hcell('Resting HR',snap.resting_hr!=null?snap.resting_hr+'bpm':null));

  var sleep=grid3(
    hcell('Sleep',fmtSleep(snap.sleep_hours),'var(--bl)')+
    hcell('Quality',snap.sleep_performance_pct!=null?Math.round(snap.sleep_performance_pct)+'%':null)+
    hcell('Efficiency',snap.sleep_efficiency_pct!=null?Math.round(snap.sleep_efficiency_pct)+'%':null)+
    hcell('Deep',fmtSleep(snap.sleep_deep_hours))+
    hcell('REM',fmtSleep(snap.sleep_rem_hours))+
    hcell('Need',fmtSleep(snap.sleep_need_hours))+
    hcell('Resp rate',snap.respiratory_rate!=null?snap.respiratory_rate.toFixed(1):null)+
    hcell('SpO2',snap.spo2_percentage!=null?snap.spo2_percentage.toFixed(1)+'%':null)+
    hcell('Skin temp',snap.skin_temp_celsius!=null?snap.skin_temp_celsius.toFixed(1)+'°C':null));

  var activity=grid3(
    hcell('Strain',snap.strain!=null?snap.strain.toFixed(1)+'/21':null,'var(--bl)')+
    hcell('Avg HR',snap.avg_hr!=null?snap.avg_hr+'bpm':null)+
    hcell('Steps',snap.steps?snap.steps.toLocaleString():null)+
    hcell('Active cal',snap.active_calories?Math.round(snap.active_calories)+'':null,'var(--or)'));

  var workouts='',woCount=0;
  if(snap.whoop_workouts){{
    try{{
      var wos=JSON.parse(snap.whoop_workouts);
      wos.forEach(function(w){{
        woCount++;
        var sub=[];
        if(w.strain!=null)sub.push(w.strain.toFixed(1)+' strain');
        if(w.duration_min)sub.push(w.duration_min+'min');
        if(w.avg_hr)sub.push('HR '+w.avg_hr);
        if(w.calories)sub.push(w.calories+' cal');
        workouts+=hrow(w.sport,sub.join(' · ')||'—');
      }});
    }}catch(e){{}}
  }}

  grid.innerHTML=
    (hsec('activity','Activity',snap.strain!=null?snap.strain.toFixed(1)+' strain':'',activity,!wIsMobile())+
     hsec('workouts','Workouts',woCount?(woCount+(woCount>1?' sessions':' session')):'',workouts,false)+
     hsec('recovery','Recovery',snap.recovery_score!=null?snap.recovery_score+'%':'',recovery,false)+
     hsec('sleep','Sleep',fmtSleep(snap.sleep_hours)||'',sleep,false))
    ||'<div style="color:var(--mu);font-size:13px;padding:8px 0">No data for this day yet — run /whoop sync in Telegram.</div>';
}}

// ── Apple Health module — simple panel (push-only, no sync button) ─────────
function renderAppleHealthModule(snap,mod,grid,dateEl,titleEl,syncBtn){{
  if(titleEl)titleEl.textContent='Apple Health';
  var brandEl=document.getElementById('health-brand'); if(brandEl)brandEl.innerHTML=APPLE_MARK;
  if(syncBtn)syncBtn.style.display='none';  // Apple Health is push-only — nothing to sync
  mod.style.display='block';

  if(!snap||snap.source!=='apple_health'){{
    if(dateEl)dateEl.textContent='';
    grid.innerHTML='<div style="color:var(--mu);font-size:13px;padding:4px 0">No Apple Health data for this day yet — it syncs automatically each morning.</div>';
    return;
  }}
  if(dateEl)dateEl.textContent=snap.date||'';

  function fmtSleep(h){{
    if(!h)return null;
    var hrs=Math.floor(h),mins=Math.round((h-hrs)*60);
    return hrs+'h'+(mins>0?' '+mins+'m':'');
  }}

  // Same collapsible format as Whoop, fewer metrics (Apple Health platform limits).
    var recovery=grid3(
    hcell('Resting HR',snap.resting_hr!=null?snap.resting_hr+'bpm':null)+
    hcell('Avg HR',snap.avg_hr!=null?snap.avg_hr+'bpm':null)+
    hcell('HRV',snap.hrv!=null?snap.hrv+'ms':null));

  var activity=grid3(
    hcell('Steps',snap.steps!=null?snap.steps.toLocaleString():null)+
    hcell('Active cal',snap.active_calories!=null?Math.round(snap.active_calories)+'':null,'var(--or)')+
    hcell('Resting cal',snap.resting_calories!=null?Math.round(snap.resting_calories)+'':null)+
    hcell('Exercise',snap.exercise_minutes!=null?snap.exercise_minutes+' min':null,'var(--ac)')+
    hcell('Stand',snap.stand_hours!=null?snap.stand_hours+' hr':null));

  var sleep=grid3(
    hcell('Sleep',fmtSleep(snap.sleep_hours),'var(--bl)')+
    hcell('Deep',fmtSleep(snap.sleep_deep_hours))+
    hcell('REM',fmtSleep(snap.sleep_rem_hours)));

  grid.innerHTML=
    (hsec('ah-recovery','Recovery',snap.resting_hr!=null?snap.resting_hr+'bpm':'',recovery,false)+
     hsec('ah-activity','Activity',snap.steps!=null?snap.steps.toLocaleString():'',activity,!wIsMobile())+
     hsec('ah-sleep','Sleep',fmtSleep(snap.sleep_hours)||'',sleep,false))
    ||'<div style="color:var(--mu);font-size:13px;padding:8px 0">No Apple Health data for this day yet — it syncs automatically each morning.</div>';
}}

function renderHealthGrid(h){{
  var tiles=[];
  if(h.recovery_score!=null){{
    var rec=h.recovery_score;
    var col=rec>=67?'var(--ac)':rec>=34?'var(--ye)':'var(--re)';
    var r=20,circ=2*Math.PI*r,dash=(rec/100)*circ,gap=circ-dash;
    tiles.push(
      '<div class="htile">'+
      '<svg viewBox="0 0 56 56" style="width:52px;height:52px;margin:0 auto;display:block">'+
      '<circle cx="28" cy="28" r="'+r+'" fill="none" stroke="var(--sf2)" stroke-width="4"/>'+
      '<circle cx="28" cy="28" r="'+r+'" fill="none" stroke="'+col+'" stroke-width="4"'+
        ' stroke-dasharray="'+dash.toFixed(1)+' '+gap.toFixed(1)+'"'+
        ' stroke-linecap="round" transform="rotate(-90 28 28)"/>'+
      '<text x="28" y="33" text-anchor="middle" font-size="11" font-weight="800"'+
        ' font-family="Inter,sans-serif" fill="'+col+'">'+rec+'%</text>'+
      '</svg><div class="hl">Recovery</div></div>'
    );
  }}
  function tile(v,l,c){{
    return '<div class="htile"><div class="hv" style="color:'+c+'">'+esc(v)+'</div><div class="hl">'+esc(l)+'</div></div>';
  }}
  if(h.hrv!=null)         tiles.push(tile(h.hrv+'ms',            'HRV',     'var(--pu)'));
  if(h.resting_hr!=null)  tiles.push(tile(h.resting_hr+'bpm',    'Rest HR', 'var(--bl)'));
  if(h.sleep_hours!=null) tiles.push(tile((+h.sleep_hours).toFixed(1)+'h','Sleep','var(--ac)'));
  if(h.strain!=null)      tiles.push(tile((+h.strain).toFixed(1),'Strain',  'var(--or)'));
  if(h.steps!=null)       tiles.push(tile((+h.steps).toLocaleString(),'Steps','var(--ye)'));
  document.getElementById('health-grid').innerHTML=tiles.join('');
}}

// ── Week tab ──────────────────────────────────────────────────────────────
// Minimal Trends tab — one chart (weight), one quiet text summary,
// the AI banner, and the goal card. The cal/protein bar charts that
// used to live here were retired during the refinement pass because
// they made the surface visually loud; that info lives in the
// one-liner + AI banner now, and per-day detail is on the Daily tab.
function renderWeekTab(d){{
  var dk=document.documentElement.getAttribute('data-theme')!=='light';
  var hist=(d.history||[]).slice(-_trendsPeriod);
  var weights=d.weights||[];
  var cutoff=hist.length?hist[0].date:null;
  var weightsInPeriod=cutoff?weights.filter(w=>w.date>=cutoff):weights.slice();
  var curW=weightsInPeriod.length?weightsInPeriod[weightsInPeriod.length-1].lbs:(weights.length?weights[weights.length-1].lbs:null);
  var wEl2=document.getElementById('wt-now-lbl');if(wEl2)wEl2.textContent=curW?curW+' LB NOW':'';
  _renderTrendsMeta(hist);
  renderTrendLine(d, hist, weightsInPeriod);
  // 5-day trend strip — relocated from the Day tab. Uses the full history
  // (not the period slice) so the "last 5 logged days" recap stays stable
  // regardless of the 7/30/90 chip selection.
  renderTrendStrip(d.history||[], d.weights||[], d.targets||{{}});
  var tick=dk?'#4a5568':'#94a3b8',grid=dk?'rgba(255,255,255,.05)':'#e2e8f0';
  var opts={{
    responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{grid:{{display:false}},ticks:{{color:tick,font:{{size:9}},maxRotation:0,autoSkip:true,maxTicksLimit:8}}}},
      y:{{grid:{{color:grid}},ticks:{{color:tick,font:{{size:10}}}},beginAtZero:true}}
    }}
  }};

  if(weightChart) weightChart.destroy();
  var wD=weightsInPeriod;
  weightChart=new Chart(document.getElementById('weightChart'),{{
    type:'line',
    data:{{
      labels:wD.map(w=>w.date.slice(5)),
      datasets:[
        {{
          data:wD.map(w=>w.lbs),
          borderColor:dk?'#f97316':'#ea580c',
          backgroundColor:dk?'rgba(249,115,22,.08)':'rgba(234,88,12,.06)',
          borderWidth:2.5,pointRadius:3,pointBackgroundColor:dk?'#f97316':'#ea580c',
          fill:true,tension:0.35,
        }},
        ...(d.profile?.goal_weight_lbs&&wD.length?[{{
          type:'line',data:Array(wD.length).fill(d.profile.goal_weight_lbs),
          borderColor:dk?'rgba(0,230,118,.35)':'rgba(5,150,105,.4)',
          borderDash:[4,4],borderWidth:1.5,pointRadius:0,fill:false,
        }}]:[])
      ]
    }},
    options:{{...opts,scales:{{...opts.scales,y:{{...opts.scales.y,beginAtZero:false}}}}}},
  }});

  renderGoalProgress(d.profile||{{}}, d.weights||[]);
}}

// ── Trends meta + summary helpers ────────────────────────────────────────
// _renderTrendsMeta — updates the date-range label next to the chips and
// the sidebar nav meta. That's it — the rest of the chrome is gone.
function _renderTrendsMeta(hist){{
  var rangeStr='';
  if(hist.length){{
    var fmt=function(s){{var dd=new Date(s+'T00:00:00');return dd.toLocaleDateString('en-US',{{month:'short',day:'numeric'}});}};
    rangeStr=fmt(hist[0].date)+' — '+fmt(hist[hist.length-1].date);
  }}
  var elMeta=document.getElementById('period-meta');if(elMeta)elMeta.textContent=rangeStr;
  var elNav=document.querySelector('#nav-week .ni-meta');if(elNav)elNav.textContent=_trendsPeriod+' days';
}}

// renderTrendLine — the quiet one-line summary that replaces the 4-up
// macro-strip. Three numbers (avg cal / weight Δ / workouts) tinted
// green if they move toward the user's primary goal, red if they don't,
// muted if neutral. Plain mono text, no chrome.
function renderTrendLine(d,hist,weightsInPeriod){{
  var el=document.getElementById('trend-line');if(!el)return;
  var tgt=d.targets||{{}};
  var prof=d.profile||{{}};
  var loggedCal=hist.filter(h=>h.calories>0);
  var avgCal=loggedCal.length?Math.round(loggedCal.reduce((s,h)=>s+h.calories,0)/loggedCal.length):0;
  var workouts=hist.filter(h=>h.workout).length;
  var perWk=_trendsPeriod?(workouts/(_trendsPeriod/7)).toFixed(1):'0';

  var parts=[];
  // Avg cal — green if moving toward goal, red if drifting, neutral otherwise.
  var calCls='tl-val';
  if(tgt.calories){{
    var diff=avgCal-tgt.calories;
    var pct=Math.abs(diff)/tgt.calories;
    var calOK=(prof.primary_goal==='cut'&&diff<0)||(prof.primary_goal==='bulk'&&diff>0)||(pct<0.05);
    calCls='tl-val '+(calOK?'up':'dn');
  }}
  parts.push('<span><span class="'+calCls+'">'+avgCal.toLocaleString()+'</span> cal / day</span>');

  // Weight delta — only when we have ≥2 weigh-ins in the window.
  if(weightsInPeriod.length>=2){{
    var startW=weightsInPeriod[0].lbs, curW=weightsInPeriod[weightsInPeriod.length-1].lbs;
    var wd=curW-startW;
    var wdStr=(wd>=0?'+':'')+wd.toFixed(1)+' lb';
    var cutOK=prof.primary_goal==='cut'&&wd<0;
    var bulkOK=prof.primary_goal==='bulk'&&wd>0;
    var maintOK=prof.primary_goal!=='cut'&&prof.primary_goal!=='bulk'&&Math.abs(wd)<1.5;
    var wCls='tl-val '+((cutOK||bulkOK||maintOK)?'up':'dn');
    parts.push('<span><span class="'+wCls+'">'+wdStr+'</span> weight</span>');
  }}

  // Workouts — ≥3/wk reads as green, <1/wk red, otherwise neutral.
  var woCls='tl-val '+(parseFloat(perWk)>=3?'up':parseFloat(perWk)<1?'dn':'');
  parts.push('<span><span class="'+woCls+'">'+workouts+'</span> workouts · '+perWk+'/wk</span>');

  el.innerHTML=parts.join('<span class="tl-dot">·</span>');
}}

// setTrendsPeriod — chip handler. Updates the chip active state and
// re-runs renderWeekTab against the cached _baseData so the chip switch
// feels instant (no network round-trip).
function setTrendsPeriod(n){{
  _trendsPeriod=n;
  document.querySelectorAll('.pchip').forEach(function(c){{
    c.classList.toggle('active', parseInt(c.dataset.period,10)===n);
  }});
  if(_baseData) renderWeekTab(_baseData);
}}

// ── Profile tab ───────────────────────────────────────────────────────────
var _PEDIT={{
  'Name':'name','Age':'age',
  'Current weight':'current_weight_lbs','Goal weight':'goal_weight_lbs',
  'Goal':'primary_goal','Experience':'training_experience',
  'Diet':'dietary_preferences','Injuries':'injuries',
  'Timezone':'timezone','Coaching style':'coaching_style',
}};
var _TEDIT={{'Calorie target':'calorie_target','Protein target':'protein_target','Calories':'calorie_target','Protein':'protein_target','Carbs':'carb_target','Fat':'fat_target'}};

function _pslug(l){{return l.toLowerCase().replace(/[^a-z0-9]/g,'_');}}

function _inrow(l,v,fldMap,color){{
  var fld=fldMap[l];
  var rawVal=v!=null?String(v):'';
  var dispTxt=rawVal.replace(/_/g,' ');
  var dispVal=color?'<span class="inval" style="color:'+color+'">'+esc(dispTxt)+'</span>'
                   :'<span class="inval">'+esc(dispTxt)+'</span>';
  var editBtn=fld?'<button class="ibtn inrow-edit" onclick="editProw(\\'pr-'+_pslug(l)+'\\',\\''+escA(fld)+'\\',\\''+escA(rawVal)+'\\')">&#9998;</button>':'';
  return '<div class="inrow" id="pr-'+_pslug(l)+'">'+
    '<span class="inlbl">'+esc(l)+'</span>'+
    '<div class="inrow-right">'+dispVal+editBtn+'</div>'+
    '</div>';
}}

// ── Training program ─────────────────────────────────────────────────────────
var _wpCache=null;

async function loadWorkoutProgram(){{
  try{{
    var r=await fetch('/api/workout/'+TOKEN);
    if(!r.ok)return;
    var data=await r.json();
    _wpCache=data;
    renderWorkoutProgram(data.program, data.raw_text||'');
  }}catch(e){{}}
}}

function renderWorkoutProgram(p, rawText){{
  var el=document.getElementById('workout-program-card');
  var editBtn=document.getElementById('wp-edit-btn');
  if(!el)return;
  if(!p){{
    el.innerHTML='<div class="wp-empty">No training program set up yet.<div class="wp-empty-hint">Tap + to paste your split — Arnie will parse it automatically.</div></div>';
    if(editBtn){{editBtn.textContent='+';editBtn.classList.remove('open');}}
    return;
  }}
  if(editBtn){{editBtn.innerHTML='&#9998;';editBtn.classList.remove('open');}}

  var priorityClass={{primary:'primary',secondary:'secondary'}}

  var rotHtml=(p.rotation||[]).map(function(d){{
    return '<span class="wp-chip">'+esc(d)+'</span>';
  }}).join('');

  var daysHtml=(p.days||[]).map(function(day,i){{
    var pri=day.priority||'';
    var priHtml=pri?'<span class="wp-priority '+esc(priorityClass[pri]||'')+'">'+esc(pri)+'</span>':'';
    var goalsHtml=(day.goals||[]).map(function(g){{return '<span class="wp-goal">'+esc(g)+'</span>';}}).join('');
    var exHtml=(day.exercises||[]).map(function(ex){{
      var catCls='wp-ex-cat-'+(ex.category||'main');
      var perf=ex.recent_performance?'<div class="wp-ex-perf">'+esc(ex.recent_performance)+'</div>':'';
      return '<div class="wp-ex '+catCls+'"><div class="wp-ex-dot"></div><div><div class="wp-ex-main">'+esc(ex.name)+'</div>'+perf+'</div></div>';
    }}).join('');
    return '<div class="wp-day" id="wpd-'+i+'">'+
      '<div class="wp-day-hd" onclick="toggleWpDay('+i+')">'+
      '<span class="wp-day-name">'+esc(day.name)+'</span>'+
      priHtml+
      '<span class="wp-chevron">&#9658;</span>'+
      '</div>'+
      '<div class="wp-day-body">'+
      (goalsHtml?'<div class="wp-goals">'+goalsHtml+'</div>':'')+
      '<div class="wp-exlist">'+exHtml+'</div>'+
      (day.notes?'<div style="margin-top:10px;font-size:12px;color:var(--mu)">'+esc(day.notes)+'</div>':'')+
      '</div></div>';
  }}).join('');

  el.innerHTML='<div class="wp-summary">'+
    '<div class="wp-name">'+esc(p.split_name||'Training Split')+'</div>'+
    (p.focus?'<div class="wp-focus">'+esc(p.focus)+'</div>':'')+
    (rotHtml?'<div class="wp-rotation">'+rotHtml+'</div>':'')+
    '<div class="wp-days">'+daysHtml+'</div>'+
    '</div>';
}}

function toggleWpDay(i){{
  var d=document.getElementById('wpd-'+i);
  if(d)d.classList.toggle('open');
}}

function openWorkoutEditor(){{
  var btn=document.getElementById('wp-edit-btn');
  var ed=document.getElementById('workout-editor');
  var ta=document.getElementById('workout-raw');
  if(!ed)return;
  var isOpen=ed.style.display!=='none';
  if(isOpen){{closeWorkoutEditor();return;}}
  // Force-expand the parent .pf-cat-section if it's collapsed — otherwise
  // the editor opens inside a max-height:0 container and the user sees
  // nothing happen. The "+" button uses stopPropagation so it doesn't
  // toggle the section twice, but it DOES need to explicitly expand
  // the section the first time.
  var sec=document.getElementById('pf-training-section');
  if(sec)sec.classList.remove('collapsed');
  if(_wpCache&&_wpCache.raw_text)ta.value=_wpCache.raw_text;
  ed.style.display='block';
  if(btn)btn.classList.add('open');
  setTimeout(function(){{ta.focus();}},60);
}}

function closeWorkoutEditor(){{
  var btn=document.getElementById('wp-edit-btn');
  var ed=document.getElementById('workout-editor');
  if(ed)ed.style.display='none';
  if(btn)btn.classList.remove('open');
  var st=document.getElementById('workout-parse-status');
  if(st)st.textContent='';
}}

async function saveWorkoutProgram(){{
  var rawText=(document.getElementById('workout-raw').value||'').trim();
  if(!rawText)return;
  var btn=document.querySelector('#workout-editor .add-submit');
  var status=document.getElementById('workout-parse-status');
  if(btn){{btn.textContent='&#9889; Parsing…';btn.disabled=true;}}
  if(status)status.textContent='Sending to Arnie for parsing…';
  try{{
    var r=await fetch('/api/workout/'+TOKEN+'/parse',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{raw_text:rawText}})
    }});
    if(!r.ok)throw new Error('HTTP '+r.status);
    var data=await r.json();
    _wpCache={{program:data.program,raw_text:rawText}};
    renderWorkoutProgram(data.program,rawText);
    closeWorkoutEditor();
  }}catch(e){{
    if(status)status.textContent='Parse failed — check your input and try again.';
  }}finally{{
    if(btn){{btn.innerHTML='&#9889; Parse &amp; save';btn.disabled=false;}}
  }}
}}

async function autoFillWorkout(){{
  var status=document.getElementById('workout-parse-status');
  var btn=document.querySelector('#workout-editor .add-submit');
  var autoBtn=document.querySelector('#workout-editor button:first-child');
  if(autoBtn){{autoBtn.textContent='&#9675; Reading your Arnie history…';autoBtn.disabled=true;}}
  if(status)status.textContent='';
  try{{
    var r=await fetch('/api/workout/'+TOKEN+'/auto-fill',{{method:'POST'}});
    if(!r.ok)throw new Error('HTTP '+r.status);
    var data=await r.json();
    if(!data.program){{
      if(status)status.textContent=data.reason||'Not enough workout info in your chat history yet — paste it manually.';
      return;
    }}
    _wpCache={{program:data.program,raw_text:''}};
    renderWorkoutProgram(data.program,'');
    closeWorkoutEditor();
  }}catch(e){{
    if(status)status.textContent='Auto-fill failed — try pasting manually instead.';
  }}finally{{
    if(autoBtn){{autoBtn.innerHTML='&#10024; Auto-fill from Arnie chat';autoBtn.disabled=false;}}
  }}
}}

async function deleteWorkoutProgram(){{
  if(!confirm('Remove your training program?'))return;
  await fetch('/api/workout/'+TOKEN,{{method:'DELETE'}});
  _wpCache=null;
  renderWorkoutProgram(null,'');
}}

// Profile tab renders the connected-devices card (needs /api/stats connection flags)
// plus the settings cards for reminders and food logging mode (sourced from d.profile).
function renderProfileTab(d){{
  var p=d.profile||{{}};
  var tgt=d.targets||{{}};

  // Coaching preferences — moved from the removed Coaching tab. These three
  // settings have their own DOM nodes inside #panel-profile now; the existing
  // render functions read state from the profile dict and update the controls
  // in place. No new state plumbing; just invoking the old renderers from here.
  renderRemindSettings(p);
  renderFoodModeSettings(p);
  renderCoachingStyleSettings(p);

  // Demographics — who the user is. Renders into the compact grid at the top
  // of the "Your settings" section. Editable cells use editBasic (same flow
  // as before, just owned by renderProfileTab now instead of renderAIProfile).
  var dem=document.getElementById('demographics-card');
  if(dem){{
    function _ht(){{
      if(p.height_ft) return p.height_ft;
      if(p.height_cm) return Math.round(p.height_cm)+' cm';
      return null;
    }}
    // ALL six demographics rows are now editable so "Calculate for me" can
    // never get stuck on a missing-field error the user can't fix in the UI.
    // Sex normalizes server-side (any reasonable spelling → male/female/other),
    // Height accepts "5'10", "5 10", or plain inches. Daily activity uses a
    // 4-option picklist (sedentary / lightly / moderately / very active) —
    // currently captured-only, not yet wired into compute_macro_targets().
    var _actLabel = {{
      sedentary:          'Sedentary',
      lightly_active:     'Lightly active',
      moderately_active:  'Moderately active',
      very_active:        'Very active',
    }};
    // Timezone display — strip continent prefix for compactness ("America/Los_Angeles"
    // → "Los Angeles") since the cell is narrow. Editor preserves the full IANA value.
    function _tzDisp(tz){{
      if(!tz || tz==='UTC') return null;
      var parts=String(tz).split('/');
      return parts[parts.length-1].replace(/_/g,' ');
    }}
    var rows=[
      {{label:'Name',           value:p.name||null,                                edit:'name',              raw:p.name||''}},
      {{label:'Age',            value:p.age?p.age+' yrs':null,                    edit:'age',               raw:p.age||''}},
      {{label:'Sex',            value:(p.sex?String(p.sex).charAt(0).toUpperCase()+String(p.sex).slice(1):null), edit:'sex',     raw:p.sex||''}},
      {{label:'Height',         value:_ht(),                                       edit:'height_in',         raw:p.height_ft||''}},
      {{label:'Current weight', value:p.current_weight_lbs!=null?(p.current_weight_lbs+' lbs'):null, edit:'current_weight_lbs', raw:p.current_weight_lbs!=null?String(p.current_weight_lbs):''}},
      {{label:'Daily activity',  value:p.non_training_activity?_actLabel[p.non_training_activity]||p.non_training_activity:null, edit:'non_training_activity', raw:p.non_training_activity||''}},
      {{label:'Timezone',       value:_tzDisp(p.timezone),                         edit:'timezone',          raw:p.timezone||''}},
    ];
    // Always render all 5 cells (empty value renders as "—") so the user can
    // edit missing values too. The basic-edit pencil is always visible.
    dem.innerHTML=rows.map(function(r){{
      var id='pd-'+r.label.toLowerCase().replace(/[^a-z0-9]/g,'_');
      var disp = (r.value!=null && r.value!=='') ? r.value : '—';
      var muted = (r.value==null || r.value==='') ? ' style="color:var(--mu);font-weight:400"' : '';
      var eb=r.edit
        ? '<button class="basic-edit" onclick="editBasic(\\''+id+'\\',\\''+escA(r.edit)+'\\',\\''+escA(r.raw)+'\\',\\''+escA(r.label)+'\\')">&#9998;</button>'
        : '';
      return '<div class="basic-cell" id="'+id+'">'+
        '<div class="basic-lbl">'+esc(r.label)+'</div>'+
        '<div class="basic-val"'+muted+'>'+esc(disp)+'</div>'+eb+'</div>';
    }}).join('');
  }}

  // Goals & targets card — visually unified with Demographics:
  // top row of two .basic-cell tiles (Goal + Goal weight) above a 4-up
  // grid of macro tiles (Cal/P/C/F). Macros use a color dot per macro that
  // mirrors the Day-tab macro tiles; Goal renders as a colored pill so the
  // cut/bulk/perf/health signal is visible at a glance.
  // The cell IDs stay 'pg-*' for editProw discovery (editProw can find the
  // label via either .inlbl or .basic-lbl now — see editProw below).
  var gc=document.getElementById('goals-card');
  if(gc){{
    var goalColor={{cut:'var(--re)',bulk:'var(--ac)',maintain:'var(--mu)',performance:'var(--or)',health:'var(--bl)'}}[p.primary_goal]||'var(--tx)';
    var goalDisp=goalLabel(p.primary_goal);

    // Meta tile (Goal / Goal weight) — value renders plain. Goal cell wraps
    // value in a goal-pill so the goal type pops without a separate badge.
    function metaTile(lbl,disp,raw,field,asPill,pillColor){{
      var id='pg-'+lbl.toLowerCase().replace(/[^a-z0-9]/g,'_');
      var hasVal=raw!=null&&raw!=='';
      var val = hasVal
        ? (asPill
            ? '<span class="goal-pill" style="--goal-c:'+pillColor+'">'+esc(disp)+'</span>'
            : esc(disp))
        : '<span style="color:var(--mu);font-weight:400">—</span>';
      var eb='<button class="basic-edit" onclick="editProw(\\''+id+'\\',\\''+escA(field)+'\\',\\''+escA(raw||'')+'\\')">&#9998;</button>';
      return '<div class="basic-cell" id="'+id+'">'+
        '<div class="basic-lbl">'+esc(lbl)+'</div>'+
        '<div class="basic-val">'+val+'</div>'+eb+'</div>';
    }}

    // Macro tile — colored dot + value + unit. Color drives --macro-c on
    // the tile so the ::before dot picks it up via CSS.
    function macroTile(lbl,num,unit,field,col){{
      var id='pg-'+lbl.toLowerCase().replace(/[^a-z0-9]/g,'_');
      var hasVal=num!=null&&num!=='';
      var inner = hasVal
        ? (esc(String(num))+'<span class="basic-unit">'+esc(unit)+'</span>')
        : '<span style="color:var(--mu);font-weight:400">—</span>';
      var eb='<button class="basic-edit" onclick="editProw(\\''+id+'\\',\\''+escA(field)+'\\',\\''+escA(num!=null?String(num):'')+'\\')">&#9998;</button>';
      return '<div class="basic-cell macro-cell" id="'+id+'" style="--macro-c:'+col+'">'+
        '<div class="basic-lbl">'+esc(lbl)+'</div>'+
        '<div class="basic-val">'+inner+'</div>'+eb+'</div>';
    }}

    gc.innerHTML=
      '<div class="goals-meta-grid">'+
        metaTile('Goal',        goalDisp,                                              p.primary_goal||'',                                  'primary_goal',    true, goalColor)+
        metaTile('Goal weight', p.goal_weight_lbs!=null?(p.goal_weight_lbs+' lbs'):'', p.goal_weight_lbs!=null?String(p.goal_weight_lbs):'','goal_weight_lbs', false, null)+
      '</div>'+
      '<div class="macros-grid">'+
        macroTile('Calories', tgt.calories, 'kcal', 'calorie_target', 'var(--tx)')+
        macroTile('Protein',  tgt.protein,  'g',    'protein_target', 'var(--ac)')+
        macroTile('Carbs',    tgt.carbs,    'g',    'carb_target',    'var(--or)')+
        macroTile('Fat',      tgt.fats,     'g',    'fat_target',     'var(--ye)')+
      '</div>';
  }}

  var dc=document.getElementById('devices-card');
  if(!dc) return;
  // Shortened labels — the compact cards truncate via CSS, so we use
  // terse status text instead of long calls-to-action. Onboarding +
  // chat handle the actual "how to connect" copy.
  var appleGuide='/health/apple/guide?token='+encodeURIComponent(TOKEN);
  var devs=[
    {{name:'Apple Health',icon:'♥',live:p.apple_health_connected,label:p.apple_health_connected?'Syncing':'Set up',href:appleGuide}},
    {{name:'Whoop',icon:'〰',live:p.whoop_connected,label:p.whoop_connected?'Connected':'Not connected'}},
    {{name:'Fitbit',icon:'⊕',live:false,label:'Coming soon',soon:true}},
    {{name:'Hume',icon:'◉',live:false,label:'Coming soon',soon:true}},
  ];
  dc.innerHTML=
    '<div class="dev-grid">'+devs.map(function(d){{
      var cls='dev-card'+(d.soon?' dev-soon':'')+(d.href?' dev-link':'');
      var open=d.href?'<a class="'+cls+'" href="'+escA(d.href)+'">':'<div class="'+cls+'">';
      var close=d.href?'</a>':'</div>';
      return open+
        '<div class="dev-logo">'+d.icon+'</div>'+
        '<div class="dev-body">'+
        '<div class="dev-name">'+esc(d.name)+'</div>'+
        '<div class="dev-status'+(d.live?' dev-live':'')+'">'+
        (d.live?'<span class="dev-dot"></span>':'')+esc(d.label)+
        '</div></div>'+close;
    }}).join('')+'</div>';
}}

// ── AI Profile ────────────────────────────────────────────────────────────
// Global: must live outside renderAIProfile so onclick="pfToggleMore(this)" resolves.
function pfToggleMore(btn) {{
  var extra = btn.previousElementSibling;
  var isOpen = extra.style.display !== 'none';
  extra.style.display = isOpen ? 'none' : '';
  btn.textContent = isOpen ? ('Show ' + btn.dataset.n + ' more') : 'Show less';
}}

var _aiProfileLoaded = false;

const CATEGORY_LABELS = {{
  goals: 'Goals', nutrition: 'Nutrition', fitness: 'Fitness',
  health: 'Health & Supplements', lifestyle: 'Lifestyle',
  behavior: 'Behavior', mental: 'Mental', custom: 'Custom Tracking',
}};
const CONF_COLORS = {{ confirmed: 'var(--ac)', inferred: 'var(--mu)', needs_verification: '#f0a500' }};
// User-facing labels for goal values. DB still stores 'cut'/'bulk' (don't change —
// LLM prompts, tests, and existing user records all reference those keys), but
// the UI shows plain-English equivalents. Mirror of memory/profile_view._GOAL_LABELS.
const GOAL_LABELS = {{
  cut: 'Losing weight', bulk: 'Gaining weight', maintain: 'Maintain',
  performance: 'Performance', health: 'Health',
}};
function goalLabel(v){{ return GOAL_LABELS[v] || (v ? String(v).charAt(0).toUpperCase()+String(v).slice(1) : ''); }}
// Enum edit fields → fixed option vocabularies (picklist instead of free text).
// Free-text/numeric fields (name, weight, injuries, diet…) keep their input;
// learned attributes aren't manually edited (they backfill from conversation).
const EDIT_OPTIONS = {{
  primary_goal: ['cut','bulk','maintain','performance','health'],
  training_experience: ['beginner','intermediate','advanced'],
  coaching_style: ['strict','balanced','supportive'],
}};

function renderAIProfile(data) {{
  var loadEl = document.getElementById('ai-profile-loading');
  var emptyEl = document.getElementById('ai-profile-empty');
  var section = document.getElementById('ai-profile-section');

  if (loadEl) loadEl.style.display = 'none';

  // hasAI checks ONLY for AI-learned content (bio + learned attributes).
  // Demographics are no longer part of this check — they live in the settings
  // section above and always render regardless of what Arnie has learned.
  var hasStd = !!(data && data.standard && Object.keys(data.standard).length);
  var hasAI  = !!(data && (data.bio || hasStd));

  // No AI data yet → show empty state, hide the section. Your settings card
  // above (rendered by renderProfileTab) still appears — settings are independent.
  if (!hasAI) {{
    if (section) section.style.display = 'none';
    if (emptyEl) emptyEl.style.display = 'block';
    return;
  }}

  if (section) section.style.display = 'block';
  if (emptyEl) emptyEl.style.display = 'none';

  // Bio
  var bioEl = document.getElementById('ai-bio-card');
  if (bioEl) {{
    if (data && data.bio) {{
      // Parse "Label: insight" lines into the AI-read panel; fall back to a
      // plain paragraph for older unstructured bios.
      var rows = [];
      data.bio.split(/\\n+/).forEach(function(line) {{
        var i = line.indexOf(':');
        if (i > 0 && i < 14) {{
          var tag = line.slice(0, i).trim(), txt = line.slice(i + 1).trim();
          if (tag && txt && /^[A-Za-z ]+$/.test(tag)) rows.push([tag, txt]);
        }}
      }});
      if (rows.length >= 2) {{
        bioEl.innerHTML = '<div class="ai-read">' + rows.slice(0, 4).map(function(r) {{
          return '<div class="ai-read-row"><span class="ai-read-tag">' + esc(r[0]) +
            '</span><span class="ai-read-txt">' + esc(r[1]) + '</span></div>';
        }}).join('') + '</div>';
      }} else {{
        // Older unstructured paragraph bio → break into sentence bullets (cap 4)
        // so it reads as coaching analysis, not an essay.
        // Split on sentence end (.!? + space + capital) so decimals like 8.8lb
        // and 40-50g stay intact.
        var sents = String(data.bio).replace(/\\s+/g, ' ').trim()
          .replace(/([.!?])\\s+(?=[A-Z])/g, '$1\\u0001').split('\\u0001')
          .map(function(s){{return s.trim();}})
          .filter(function(s){{return s.length > 3;}}).slice(0, 4);
        bioEl.innerHTML = sents.length
          ? '<ul class="ai-bullets">' + sents.map(function(s){{return '<li>' + esc(s) + '</li>';}}).join('') + '</ul>'
          : '<p style="margin:0">' + esc(data.bio) + '</p>';
      }}
    }} else {{
      bioEl.innerHTML = '<p style="margin:0;color:var(--mu);font-style:italic">Your read builds as Arnie learns you — keep logging and chatting.</p>';
    }}
    bioEl.style.display = 'none';  // collapsed by default (toggleBio expands it)
  }}

  // Basics grid removed — demographics now live in the "Your settings" section
  // at the top of the profile tab, rendered by renderProfileTab. The basics array
  // from /api/profile/{token} is no longer used here; only AI-learned attributes
  // belong in Arnie's brain section.

  // Standard skeleton (always-present slots) + Custom Tracking
  var attrsEl = document.getElementById('ai-attributes-section');
  if (!attrsEl) return;
  var std = (data && data.standard) || {{}};
  var STD_ORDER = ['goals','nutrition','fitness','health','lifestyle','behavior'];

  function _chip(t) {{ return '<span class="chip">' + esc(t) + '</span>'; }}
  function _slotRow(s, cat) {{
    var id = 'pc-' + _pslug(cat + '_' + s.label);
    var right;
    if (!s.filled) {{
      var editFld = s.edit_field || s.key;
      var emptyEdit = editFld
        ? '<button class="ibtn inrow-edit" onclick="editProw(\\''+id+'\\',\\''+escA(editFld)+'\\',\\'\\')">&#9998;</button>' : '';
      right = '<span class="slot-wait" title="Arnie is still learning this from your activity"></span>' + emptyEdit;
    }} else if (s.chips && s.chips.length) {{
      right = '<div class="chips">' + s.chips.map(_chip).join('') + '</div>';
    }} else {{
      right = '<span class="inval">' + esc(s.value) + '</span>';
    }}
    var confDot = (s.filled && s.confidence)
      ? '<span class="conf-dot" style="background:' + (CONF_COLORS[s.confidence]||'var(--mu)') + '" title="' + esc(s.confidence) + '"></span>' : '';
    var edit = s.edit_field
      ? '<button class="ibtn inrow-edit" onclick="editProw(\\''+id+'\\',\\''+escA(s.edit_field)+'\\',\\''+escA(s.raw)+'\\')">&#9998;</button>' : '';
    return '<div class="inrow" id="'+id+'"><span class="inlbl">' + esc(s.label) + '</span>' +
      '<div class="inrow-right">' + right + confDot + edit + '</div></div>';
  }}

  // One row for a learned/custom attribute (with remove button).
  function _customRow(c) {{
    var confDot = c.confidence
      ? '<span class="conf-dot" style="background:' + (CONF_COLORS[c.confidence]||'var(--mu)') + '" title="' + esc(c.confidence) + '"></span>' : '';
    var rm = c.key ? '<button class="inrow-x" title="Remove from profile" data-key="' + esc(c.key) +
      '" data-label="' + esc(c.label) + '" onclick="hideAttribute(this)">&#10005;</button>' : '';
    return '<div class="inrow"><span class="inlbl">' + esc(c.label) + '</span>' +
      '<div class="inrow-right"><span class="inval">' + esc(c.value) + '</span>' + confDot + rm + '</div></div>';
  }}
  var PF_LIMIT = 5;
  // _section now takes an array of pre-rendered row HTML strings so it can
  // slice at PF_LIMIT and wire up the show-more toggle without re-parsing HTML.
  function _section(label, rowsArr, learnLabels) {{
    if (!rowsArr || !rowsArr.length) return '';
    var visible = rowsArr.slice(0, PF_LIMIT).join('');
    var extra = rowsArr.slice(PF_LIMIT);
    var extraHtml = extra.length
      ? '<div class="pf-extra" style="display:none">' + extra.join('') + '</div>' +
        '<button class="pf-show-more" data-n="' + extra.length +
        '" onclick="pfToggleMore(this)">Show ' + extra.length + ' more</button>'
      : '';
    var learn = (learnLabels && learnLabels.length)
      ? '<div class="pf-learning"><span class="pf-learn-dot"></span>Still learning &middot; ' +
        learnLabels.map(esc).join(' &middot; ') + '</div>' : '';
    // Collapsible category section — starts in .collapsed state (chevron
    // rotated -90deg, body max-height:0). Click the header to expand.
    // Markup mirrors the Day-tab .log-section-hd pattern so the Profile
    // tab reads as the same visual family as the rest of the dashboard.
    return '<div class="pf-cat-section collapsed">' +
      '<div class="stitle spaced pf-cat-hd" style="margin-top:0" onclick="togglePfCat(this)">' +
        '<span>' + esc(label) + '</span>' +
        '<button class="pf-chevron" title="Toggle">&#8249;</button>' +
      '</div>' +
      '<div class="pf-cat-body">' +
        '<div class="infocrd" style="margin-top:10px">' + visible + extraHtml + learn + '</div>' +
      '</div>' +
    '</div>';
  }}

  // Nest custom/learned attributes under the section their category belongs to,
  // instead of one catch-all "Custom Tracking" block. Leftover categories that
  // don't map to a standard section collapse into a single "Other" group.
  var custom = (data && data.custom) || [];
  var customByCat = {{}};
  custom.forEach(function(c) {{
    var k = (c.category || 'custom').toLowerCase();
    (customByCat[k] = customByCat[k] || []).push(c);
  }});

  var html = '';
  STD_ORDER.forEach(function(cat) {{
    var slots = std[cat] || [];
    var slotRowsArr = slots.filter(function(s){{ return s.filled; }})
      .map(function(s){{ return _slotRow(s, cat); }});
    var custRowsArr = (customByCat[cat] || []).map(_customRow);
    delete customByCat[cat];
    var learnLabels = slots.filter(function(s){{ return !s.filled; }})
      .map(function(s){{ return s.label; }});

    html += _section(CATEGORY_LABELS[cat]||cat, slotRowsArr.concat(custRowsArr), learnLabels);
  }});

  // Any custom attrs whose category isn't a standard section → one "Other" group.
  var leftover = [];
  Object.keys(customByCat).forEach(function(k){{ leftover = leftover.concat(customByCat[k]); }});
  if (leftover.length) {{
    html += _section(CATEGORY_LABELS['custom']||'Other', leftover.map(_customRow), null);
  }}

  // Super-subtle legend: what the dots mean + how to remove a custom item.
  html += '<div class="pf-legend">' +
    '<span><i class="pf-dot" style="background:var(--ac)"></i>confirmed</span>' +
    '<span><i class="pf-dot" style="background:var(--mu)"></i>inferred from patterns</span>' +
    '<span><i class="pf-dot" style="background:#f0a500"></i>needs verification</span>' +
    (custom.length ? '<span><i class="pf-x">&#10005;</i>tap to remove</span>' : '') +
    '</div>';

  attrsEl.innerHTML = html;
}}

async function loadAIProfile() {{
  if (_aiProfileLoaded) return;
  try {{
    var r = await fetch(PROFILE_API);
    if (!r.ok) throw new Error();
    var data = await r.json();
    _aiProfileLoaded = true;
    renderAIProfile(data);
  }} catch(e) {{
    var loadEl = document.getElementById('ai-profile-loading');
    if (loadEl) loadEl.innerHTML = '<div class="lempty">Could not load profile — tap refresh to retry.</div>';
  }}
}}

// Soft-hide a learned custom attribute (dashboard "remove"). Drops it from the
// profile, bio, and Arnie's context; he may re-learn it later from conversation.
async function hideAttribute(btn) {{
  var key = btn.getAttribute('data-key');
  var label = btn.getAttribute('data-label') || 'this item';
  if (!key) return;
  if (!confirm('Remove "' + label + '" from your profile?\\n\\nArnie will stop showing and using it. He may re-learn it later if it comes up again.')) return;
  btn.disabled = true;
  try {{
    var r = await fetch('/api/profile/attribute/hide?token=' + encodeURIComponent(TOKEN), {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{attribute_key: key}})
    }});
    if (!r.ok) throw new Error();
    reloadAIProfile();
  }} catch(e) {{
    btn.disabled = false;
    alert('Could not remove — try again.');
  }}
}}

// Re-fetch the unified profile WITHOUT forcing a bio regen (used after an edit).
async function reloadAIProfile() {{
  try {{
    var r = await fetch(PROFILE_API);
    if (!r.ok) return;
    _aiProfileLoaded = true;
    renderAIProfile(await r.json());
  }} catch(e) {{}}
}}

// ── Calculate-for-me — auto-derive calorie + macro targets ─────────
// Tap the (i) glyph to reveal the calculation rules; tap the button to
// hit POST /api/profile/<token>/auto-targets which runs the BMR + goal
// + body-comp math server-side, saves the result to user_preferences,
// and returns the new targets so we can refresh the stats payload.
function toggleCalcInfo(){{
  var card = document.getElementById('calc-card');
  if(!card) return;
  card.classList.toggle('open');
  var btn = card.querySelector('.calc-info-btn');
  if(btn) btn.classList.toggle('active', card.classList.contains('open'));
}}

async function calculateTargetsForMe(){{
  // Pre-flight: catch missing demographics BEFORE the round-trip so we can
  // scroll the user to the exact field and pulse-highlight it instead of
  // showing a generic error banner.
  var p = (_baseData && _baseData.profile) || {{}};
  var missing = [];
  if(!p.current_weight_lbs) missing.push({{key:'current_weight', label:'weight'}});
  if(!p.height_cm)          missing.push({{key:'height',         label:'height'}});
  if(!p.age)                missing.push({{key:'age',            label:'age'}});
  if(!p.sex)                missing.push({{key:'sex',            label:'sex'}});
  if(missing.length){{
    var first = missing[0];
    var cell = document.getElementById('pd-'+first.key);
    if(cell){{
      cell.scrollIntoView({{behavior:'smooth', block:'center'}});
      cell.style.boxShadow = '0 0 0 2px var(--ac) inset';
      cell.style.transition = 'box-shadow .25s';
      setTimeout(function(){{ cell.style.boxShadow=''; }}, 1800);
    }}
    var names = missing.map(function(m){{return m.label;}}).join(', ');
    alert('Add your ' + names + ' first — Demographics card above. We\\'ll calculate the moment those are set.');
    return;
  }}

  // Guard against silently overwriting values the user set manually —
  // if ANY of the 4 targets is already populated, ask before clobbering.
  var hasManual = p.calorie_target || p.protein_target || p.carb_target || p.fat_target;
  if(hasManual){{
    var ok = confirm(
      'You already have targets set. Replace them with Arnie\\'s '
      + 'recommended values based on your goal and body comp?'
    );
    if(!ok) return;
  }}
  var btn = document.getElementById('calc-btn');
  if(btn){{ btn.disabled = true; btn.textContent = 'Calculating…'; }}
  try{{
    var r = await fetch('/api/profile/' + TOKEN + '/auto-targets', {{ method:'POST' }});
    var data = {{}};
    try{{ data = await r.json(); }}catch(e){{}}
    if(!r.ok){{
      alert(data.detail || 'Could not calculate — make sure your weight, height, age and sex are set above first.');
      if(btn){{ btn.disabled=false; btn.textContent='Calculate for me'; }}
      return;
    }}
    // Refresh the stats payload (drives the dashboard) AND the profile
    // tab so the new values populate everywhere.
    try{{
      delete _dayCache[_viewingDate];
      var fresh = await fetchStats(null);
      _baseData = fresh; _dayCache[_todayStr] = fresh;
      if(_activeTab === 'day') renderDayTab(fresh);
      if(_activeTab === 'profile') renderProfileTab(fresh);
    }}catch(e){{}}
    if(btn){{
      btn.textContent = '✓ Targets set — ' + data.calorie_target + ' kcal · ' + data.protein_target + 'g P';
      setTimeout(function(){{ btn.disabled=false; btn.textContent='Calculate for me'; }}, 2200);
    }}
  }}catch(e){{
    alert('Network error — try again.');
    if(btn){{ btn.disabled=false; btn.textContent='Calculate for me'; }}
  }}
}}

// Inline edit for a Basics grid cell. Renders a select for the `sex` enum and
// a text input for everything else. Height accepts free-text in a few formats
// (5'10, 5 10, 70 — server parses), Weight expects a number in lbs.
function editBasic(cellId, field, raw, label) {{
  var cell = document.getElementById(cellId); if (!cell) return;
  // Picklist option map — keep wire values in DB-form (snake_case for
  // multi-word), show friendly labels in the UI. Sex stays single-word so
  // value == label. Activity needs both since wire is snake_case.
  var _basicPicklists = {{
    sex: {{
      options: ['male','female','other'],
      label: function(v){{ return v.charAt(0).toUpperCase()+v.slice(1); }},
    }},
    non_training_activity: {{
      options: ['sedentary','lightly_active','moderately_active','very_active'],
      label: function(v){{
        return ({{
          sedentary: 'Sedentary — desk job, minimal movement',
          lightly_active: 'Lightly active — light walking through the day',
          moderately_active: 'Moderately active — on your feet often',
          very_active: 'Very active — manual labor, active job',
        }})[v] || v;
      }},
    }},
    // Common IANA timezones grouped by region. Captures the bulk of real users
    // without becoming a 400-entry browser scroll. Free-text fallback handled
    // by the unshift below when an existing value isn't in the list (e.g. user
    // already had "Europe/Berlin" via /set_user_timezone.py).
    timezone: {{
      options: [
        'America/Los_Angeles','America/Denver','America/Chicago','America/New_York',
        'America/Toronto','America/Mexico_City','America/Sao_Paulo','America/Anchorage',
        'America/Honolulu','Europe/London','Europe/Dublin','Europe/Paris','Europe/Berlin',
        'Europe/Madrid','Europe/Rome','Europe/Amsterdam','Europe/Stockholm','Europe/Athens',
        'Europe/Moscow','Africa/Cairo','Africa/Johannesburg','Asia/Dubai','Asia/Tehran',
        'Asia/Kolkata','Asia/Karachi','Asia/Bangkok','Asia/Singapore','Asia/Hong_Kong',
        'Asia/Shanghai','Asia/Tokyo','Asia/Seoul','Australia/Sydney','Australia/Perth',
        'Pacific/Auckland','UTC',
      ],
      label: function(v){{ return v.replace(/_/g,' '); }},
    }},
  }};
  var editor;
  var pl = _basicPicklists[field];
  if (pl) {{
    var cur = (raw || '').toLowerCase();
    var opts = pl.options.slice();
    if (cur && opts.indexOf(cur) === -1) opts.unshift(cur);
    editor = '<select id="bi-'+cellId+'" style="flex:1;min-width:0;background:var(--inp);border:1px solid var(--ac);color:var(--tx);padding:4px 7px;border-radius:7px;font-size:13px;font-family:inherit;outline:none">' +
      opts.map(function(o){{ return '<option value="'+escA(o)+'"'+(o===cur?' selected':'')+'>'+esc(pl.label(o))+'</option>'; }}).join('') +
      '</select>';
  }} else {{
    var ph = '';
    if (field === 'height_in')          ph = 'e.g. 5\\'10 or 70';
    else if (field === 'current_weight_lbs') ph = 'lbs';
    else if (field === 'age')           ph = 'years';
    editor = '<input type="text" id="bi-'+cellId+'" value="'+escA(raw)+'" placeholder="'+escA(ph)+'" ' +
      'style="flex:1;min-width:0;background:var(--inp);border:1px solid var(--ac);color:var(--tx);padding:4px 7px;border-radius:7px;font-size:13px;font-family:inherit;outline:none">';
  }}
  cell.innerHTML = '<div class="basic-lbl">'+esc(label)+'</div>' +
    '<div style="display:flex;gap:4px;align-items:center;margin-top:1px">' +
    editor +
    '<button class="sbtn" style="flex:none;padding:4px 9px;font-size:11px;min-height:0" onclick="saveBasic(\\''+cellId+'\\',\\''+escA(field)+'\\')">&#10003;</button>' +
    '<button class="cbtn" style="flex:none;padding:4px 7px;font-size:11px;min-height:0" onclick="cancelBasic()">&#10005;</button>' +
    '</div>';
  var inp = document.getElementById('bi-'+cellId);
  if (inp) {{ inp.focus(); if (inp.select) inp.select(); }}
}}

function cancelBasic(){{
  // Demographics cells (pd-*) live in the settings section — re-render from
  // _baseData. AI section's pb-* cells no longer exist (basics moved out),
  // but reloadAIProfile is still cheap and safe to call.
  if (_baseData) renderProfileTab(_baseData);
  reloadAIProfile();
}}

async function saveBasic(cellId, field) {{
  var inp = document.getElementById('bi-'+cellId); if (!inp) return;
  var val = inp.value.trim();
  try {{
    var r = await fetch('/api/profile/'+TOKEN, {{
      method:'PATCH', headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{field:field, value:val||null}}),
    }});
    if (!r.ok) throw new Error();
    var data = await fetchStats(null);
    if (data) {{ _baseData=data; _dayCache[_todayStr]=data; renderProfileTab(data);
      var nm=document.getElementById('user-name'); if(nm) nm.textContent=data.profile?.name||''; }}
    reloadAIProfile();
  }} catch(e) {{ alert('Save failed — try again.'); reloadAIProfile(); }}
}}

async function refreshAIProfile() {{
  _aiProfileLoaded = false;
  var loadEl = document.getElementById('ai-profile-loading');
  var section = document.getElementById('ai-profile-section');
  if (loadEl) {{ loadEl.style.display = 'block'; loadEl.innerHTML = 'Refreshing&#8230;'; }}
  if (section) section.style.display = 'none';
  try {{
    var r = await fetch(PROFILE_API + '?refresh=true');
    if (!r.ok) throw new Error();
    var data = await r.json();
    _aiProfileLoaded = true;
    renderAIProfile(data);
  }} catch(e) {{
    if (loadEl) loadEl.innerHTML = '<div class="lempty">Could not refresh — try again later.</div>';
  }}
}}
function toggleBio(){{
  var el=document.getElementById('ai-bio-card');
  var ch=document.getElementById('bio-chevron-btn');
  if(!el)return;
  var open=el.style.display==='none'||!el.style.display;
  el.style.display=open?'block':'none';
  // .expanded settles the chevron to 0deg (default state is rotated
  // -90deg via .pf-chevron base style). Pattern matches the Day-tab
  // section chevrons — defined in CSS above.
  if(ch)ch.classList.toggle('expanded',open);
}}

// Toggle a single Arnie's brain category section (Goals/Nutrition/Fitness/…)
// Called from the header onclick; finds the parent .pf-cat-section and flips
// the .collapsed class — CSS handles the chevron rotation + body max-height
// transition. Designed to mirror Day-tab toggleLogSection() behavior, except
// it's togglable on every screen size (categories opt-in to detail).
function togglePfCat(hd){{
  var sec = hd && hd.parentElement;
  if (sec && sec.classList.contains('pf-cat-section')) {{
    sec.classList.toggle('collapsed');
  }}
}}
// ── Insights ──────────────────────────────────────────────────────────────
function toggleInsights(which){{
  var el=document.getElementById('ins-'+which);
  if(!el)return;
  var open=el.classList.toggle('open');
  var b=el.querySelector('.ins-banner');
  if(b)b.setAttribute('aria-expanded',open?'true':'false');
}}
// Auto-refresh the analysis every 3h; a manual refresh resets this timer.
var _insAutoTimer=null;
function _resetInsAuto(){{
  if(_insAutoTimer) clearInterval(_insAutoTimer);
  _insAutoTimer=setInterval(function(){{
    _insightsLoaded=false;_insightsDate='';_weekInsightsLoaded=false;
    loadInsights();
    if(_activeTab==='week') loadWeekInsights();
  }},10800000);  // 3 hours
}}
function _stampInsTime(){{
  var t=document.getElementById('ins-time-day');
  if(!t)return;
  var d=new Date(),h=d.getHours(),m=d.getMinutes(),ap=h>=12?'PM':'AM';
  h=h%12||12;
  t.textContent='updated '+h+':'+(m<10?'0':'')+m+' '+ap;
}}
function renderInsights(ins){{
  var el=document.getElementById('insights-card');
  if(!el)return;
  if(!ins||!ins.length){{
    el.innerHTML='<div class="iempty">Not enough data yet — keep logging and Arnie will have more to say.</div>';
    return;
  }}
  // Day tab keeps it to 3 tight structured bullets.
  // Bold the lead-in before an em dash to create scan hierarchy.
  el.innerHTML=ins.slice(0,3).map(function(txt){{
    var parts=txt.split(' — ');
    var content=(parts.length>=2&&parts[0].length<52)
      ?'<strong>'+esc(parts[0])+'</strong> — '+esc(parts.slice(1).join(' — '))
      :esc(txt);
    return '<div class="irow fade-in"><div class="iico"></div><div class="itxt">'+content+'</div></div>';
  }}).join('');
  _stampInsTime();
  var prev=document.getElementById('ins-preview-day');
  if(prev&&ins[0]){{var raw=ins[0];prev.textContent=raw.length>54?raw.slice(0,52)+'…':raw;}}
}}

async function refreshInsights(){{
  _resetInsAuto();
  _insightsLoaded=false;_insightsDate='';
  var el=document.getElementById('insights-card');
  if(el)el.innerHTML='<div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div>';
  var _rp=document.getElementById('ins-preview-day');if(_rp)_rp.textContent='';
  try{{
    var date=_viewingDate||'';
    var ctrl=new AbortController();
    var tid=setTimeout(function(){{ctrl.abort();}},30000);
    var url=INSIGHTS_API+'?force=true'+(date?'&date='+date:'');
    var r=await fetch(url,{{signal:ctrl.signal}});
    clearTimeout(tid);
    if(!r.ok)throw new Error();
    var ins=((await r.json()).insights)||[];
    _insightsLoaded=!!ins.length;_insightsDate=date;
    renderInsights(ins);
  }}catch(e){{
    if(el)el.innerHTML='<div class="iempty">Could not load — tap &#8635; to retry.</div>';
  }}
}}

// ── Week insights ─────────────────────────────────────────────────────────
var _weekInsightsLoaded=false;

async function loadWeekInsights(){{
  if(_weekInsightsLoaded)return;
  var ins=await fetchInsights(null, 'week');  // real weekly analysis (7-day trends)
  _weekInsightsLoaded=!!ins.length;
  renderWeekInsights(ins);
}}

function renderWeekInsights(ins){{
  var el=document.getElementById('week-insights-card');
  if(!el)return;
  if(!ins||!ins.length){{
    el.innerHTML='<div class="iempty">Not enough data yet — keep logging and Arnie will have more to say.</div>';
    return;
  }}
  el.innerHTML=ins.slice(0,4).map(function(txt){{
    var parts=txt.split(' — ');
    var content=(parts.length>=2&&parts[0].length<52)
      ?'<strong>'+esc(parts[0])+'</strong> — '+esc(parts.slice(1).join(' — '))
      :esc(txt);
    return '<div class="irow fade-in"><div class="iico"></div><div class="itxt">'+content+'</div></div>';
  }}).join('');
}}

async function refreshWeekInsights(){{
  _resetInsAuto();
  _weekInsightsLoaded=false;
  var el=document.getElementById('week-insights-card');
  if(el)el.innerHTML='<div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div>';
  try{{
    var ctrl=new AbortController();
    var tid=setTimeout(function(){{ctrl.abort();}},30000);
    var r=await fetch(INSIGHTS_API+'?period=week&force=true',{{signal:ctrl.signal}});
    clearTimeout(tid);
    if(!r.ok)throw new Error();
    var ins=((await r.json()).insights)||[];
    _weekInsightsLoaded=!!ins.length;
    renderWeekInsights(ins);
  }}catch(e){{
    if(el)el.innerHTML='<div class="iempty">Could not load — tap &#8635; to retry.</div>';
  }}
}}

// ── Food emoji mapping ────────────────────────────────────────────────────
function foodEmoji(name){{
  var n=(name||'').toLowerCase();
  if(/pizza/.test(n))return'🍕';
  if(/burger|hamburger/.test(n))return'🍔';
  if(/sushi|maki|temaki|roll.*rice|rice.*roll/.test(n))return'🍣';
  if(/taco|burrito/.test(n))return'🌮';
  if(/wrap/.test(n))return'🌯';
  if(/sandwich|sub|schnitzel/.test(n))return'🥪';
  if(/chicken|popcorn chicken|popper/.test(n))return'🍗';
  if(/steak|beef|brisket/.test(n))return'🥩';
  if(/bacon|pork|ham|sausage/.test(n))return'🥓';
  if(/salmon|fish|tuna|cod|tilapia|sea/.test(n))return'🐟';
  if(/shrimp|prawn/.test(n))return'🍤';
  if(/salad/.test(n))return'🥗';
  if(/pasta|noodle|ramen|spaghetti|penne|fettuccine|linguine/.test(n))return'🍝';
  if(/rice/.test(n))return'🍚';
  if(/soup|stew/.test(n))return'🍲';
  if(/egg|omelet|scramble/.test(n))return'🥚';
  if(/toast|bagel|croissant/.test(n))return'🥐';
  if(/bread|loaf|bun/.test(n))return'🍞';
  if(/babka|pastry|danish/.test(n))return'🥐';
  if(/cookie|biscuit/.test(n))return'🍪';
  if(/cinnamon roll|cinnabon/.test(n))return'🍩';
  if(/cake|brownie|cupcake|muffin/.test(n))return'🎂';
  if(/chocolate|candy|sweet/.test(n))return'🍫';
  if(/fruit|apple|banana|orange|berry|grape|mango/.test(n))return'🍎';
  if(/yogurt|greek/.test(n))return'🫙';
  if(/oat|cereal|granola|porridge/.test(n))return'🥣';
  if(/protein shake|shake|smoothie/.test(n))return'🥤';
  if(/coffee|latte|cappuccino|espresso/.test(n))return'☕';
  if(/avocado/.test(n))return'🥑';
  if(/broccoli|veggie|vegetable/.test(n))return'🥦';
  if(/potato|fries|chips/.test(n))return'🍟';
  if(/cheese/.test(n))return'🧀';
  if(/milk/.test(n))return'🥛';
  if(/water/.test(n))return'💧';
  if(/wine|beer|cocktail/.test(n))return'🍷';
  return'🍽️';
}}

// ── Food rows ─────────────────────────────────────────────────────────────
// Preview-style flat 2-line layout:
//   Line 1: name + EST tag (if estimated), right-aligned mono "510 cal"
//   Line 2: muted secondary — "qty · 34p · 55c · 14f"
// Tap toggles .open on the row, which reveals edit/delete buttons via the
// .lrow-actions slot. No chevron — the row is informational at rest, action
// surfaces appear when needed.
function renderFoodRow(f){{
  var est=f.estimated?' <span class="est-tag" title="Estimated by Arnie — tap the row to edit if you have exact macros.">est</span>':'';
  var cam=f.from_photo?' <span class="photo-tag" title="Logged from a photo you sent Arnie." aria-label="From photo">\\ud83d\\udcf7</span>':'';
  var cal=(f.calories??0);
  var qty=f.quantity||'';
  // Secondary meta line: qty (optional) followed by macros. Mono numbers
  // for tabular alignment between rows.
  var meta='';
  if(qty) meta += esc(qty);
  if((f.protein??0)||(f.carbs??0)||(f.fats??0)){{
    if(qty) meta += '<span class="sep">·</span>';
    meta += '<b>'+(f.protein??0)+'</b>p<span class="sep">·</span>'+
            '<b>'+(f.carbs??0)+'</b>c<span class="sep">·</span>'+
            '<b>'+(f.fats??0)+'</b>f';
  }}
  return '<div class="lrow" id="food-row-'+f.id+'" onclick="this.classList.toggle(&quot;open&quot;)">'+
    '<div class="lrow-main">'+
      '<div class="lname">'+esc(f.name)+est+cam+'</div>'+
      (meta?'<div class="lmeta">'+meta+'</div>':'')+
    '</div>'+
    '<div class="lcal">'+cal+'<span class="lcal-unit">cal</span></div>'+
    '<div class="lrow-actions">'+
      '<button class="ibtn" onclick="event.stopPropagation();editFood('+f.id+')" aria-label="Edit">&#9998;</button>'+
      '<button class="ibtn del" onclick="event.stopPropagation();deleteFood('+f.id+')" aria-label="Delete">&#215;</button>'+
    '</div>'+
    '</div>';
}}

// Restored to the original pre-edit .eg-row expandable layout — each
// grouped exercise renders one row with name + summary + chevron, and
// tapping expands to reveal the individual sets + delete buttons.
// The flat-row redesign read backwards on mobile (tap hid the meta);
// this version follows the conventional "tap to reveal more" pattern.
function renderGroupedExercises(entries){{
  var groups={{}};
  var order=[];
  entries.forEach(function(e){{
    var key=(e.name||'?').toLowerCase().trim();
    if(!groups[key]){{groups[key]={{name:e.name||'?',items:[]}};order.push(key);}}
    groups[key].items.push(e);
  }});

  return order.map(function(key,gi){{
    var g=groups[key];
    var items=g.items;
    var totalSets=items.length;

    var summaryParts=[];
    var allReps=items.map(function(e){{return e.reps;}}).filter(Boolean);
    var allWts=items.map(function(e){{return e.weight;}}).filter(Boolean);
    var allDur=items.map(function(e){{return e.duration_minutes;}}).filter(Boolean);
    if(allDur.length){{
      summaryParts.push(allDur.reduce(function(a,b){{return a+b;}},0)+' min');
    }}else if(totalSets>0){{
      var repStr=allReps.length===totalSets&&new Set(allReps).size===1?allReps[0]:allReps.join('/');
      var sameWt=new Set(allWts).size<=1;
      var wtStr=allWts.length?(sameWt?allWts[0]+'lb':allWts.map(Math.round).join('/')+'lb'):'';
      summaryParts.push(totalSets+(repStr?' × '+repStr:'')+(wtStr?' @ '+wtStr:''));
    }}
    var summary=summaryParts.join(' · ');

    var setsHtml=items.map(function(e,i){{
      var detail='';
      if(e.duration_minutes){{detail=e.duration_minutes+' min'+(e.cardio_type?' ('+esc(e.cardio_type)+')':'');}}
      else if(e.sets||e.reps){{detail=(e.sets?e.sets+'×':'')+esc(e.reps||'')+(e.weight?' @ '+e.weight+'lb':'');}}
      return '<div class="eg-set">'+
        '<span class="eg-set-num">S'+(i+1)+'</span>'+
        (detail?'<span class="eg-set-detail">'+detail+'</span>':'<span style="color:var(--di);font-size:11px">logged</span>')+
        '<span style="flex:1"></span>'+
        '<button class="eg-del" onclick="event.stopPropagation();deleteExercise('+e.id+')" title="Remove">&#215;</button>'+
        '</div>';
    }}).join('');

    return '<div class="eg-row" onclick="this.classList.toggle(&quot;open&quot;)">'+
      '<div class="eg-hd">'+
      '<span class="eg-name">'+esc(g.name)+'</span>'+
      (summary?'<span class="eg-summary">'+esc(summary)+'</span>':'')+
      '<span class="eg-chevron">&#9658;</span>'+
      '</div>'+
      '<div class="eg-sets">'+setsHtml+'</div>'+
      '</div>';
  }}).join('');
}}

function renderExerciseRow(e){{
  var setsHtml='';
  if(e.sets&&e.reps){{
    var ra=String(e.reps).split(',').map(function(r){{return r.trim();}});
    var allSame=ra.length<=1||ra.every(function(r){{return r===ra[0];}});
    if(allSame){{
      var chip='<span class="eset-chip"><b>'+e.sets+'</b>×<b>'+esc(ra[0])+'</b>'+(e.weight?'&nbsp;@&nbsp;<b>'+e.weight+'lb</b>':'')+'</span>';
      setsHtml='<div class="esets">'+chip+'</div>';
    }}else{{
      var wt=e.weight?'<span class="eset-wt">'+e.weight+'lb</span>':'';
      var chips=ra.map(function(r,i){{
        return '<span class="eset-chip"><b>S'+(i+1)+':</b>&nbsp;'+esc(r)+'</span>';
      }}).join('');
      setsHtml='<div class="esets">'+wt+chips+'</div>';
    }}
  }}else if(e.duration_minutes){{
    setsHtml='<div class="esets"><span class="eset-chip"><b>'+e.duration_minutes+'</b>&nbsp;min'+(e.is_cardio&&e.cardio_type?'&nbsp;('+esc(e.cardio_type)+')':'')+'</span></div>';
  }}
  return '<div class="erow" id="ex-row-'+e.id+'">'+
    '<div class="ecnt"><div class="ename">'+esc(e.name)+'</div></div>'+
    setsHtml+
    '<div class="ract">'+
    '<button class="ibtn" onclick="editExercise('+e.id+')" aria-label="Edit">&#9998;</button>'+
    '<button class="ibtn del" onclick="deleteExercise('+e.id+')" aria-label="Delete">&#215;</button>'+
    '</div></div>';
}}

// ── Inline edit: food ─────────────────────────────────────────────────────
function findFood(id){{
  return(_dayCache[_viewingDate]?.day?.food_entries||[]).find(f=>f.id===id);
}}
function findEx(id){{
  return(_dayCache[_viewingDate]?.day?.exercise_entries||[]).find(e=>e.id===id);
}}

// Parse a quantity string into a number+unit pair, or null if no leading
// number is found. Handles decimals (1.5), fractions (1/2 -> 0.5), and
// whitespace. Unit is whatever follows the number, lower-cased + trimmed.
// Examples (input -> output):
//   "200g"       -> n=200, u="g"
//   "1.5 cups"   -> n=1.5, u="cups"
//   "1/2 cup"    -> n=0.5, u="cup"
//   "two slices" -> null  (no leading numeric)
//   "200"        -> n=200, u=""
function _parseServing(s){{
  if(s==null)return null;
  var m=String(s).trim().match(/^(\\d+(?:\\.\\d+)?)(?:\\s*\\/\\s*(\\d+(?:\\.\\d+)?))?\\s*(.*)$/);
  if(!m)return null;
  var num=parseFloat(m[1]);
  if(!isFinite(num)||num<=0)return null;
  if(m[2]){{
    var den=parseFloat(m[2]);
    if(!isFinite(den)||den<=0)return null;
    num=num/den;
  }}
  return {{n:num, u:(m[3]||'').trim().toLowerCase()}};
}}

// Normalize a unit for matching — strip trailing 's' so "cup" matches "cups",
// "slice" matches "slices". "g" stays "g". Empty stays empty. Doesn't try
// to convert between unit families (g vs kg, oz vs lb) — too risky for an
// auto-update without an explicit conversion table.
function _normUnit(u){{ return (u||'').toLowerCase().replace(/s$/,''); }}

// Called on every keystroke in the quantity field of an editFood form.
// Re-derives cal / P / C / F by proportional scaling FROM THE ORIGINAL
// values stored on the input's dataset. If the units don't match (or
// either string lacks a leading number), leaves the macro fields alone —
// the user can edit them manually for non-trivial portion changes.
function onServingInput(id){{
  var qEl=document.getElementById('ef-q-'+id);
  if(!qEl)return;
  var op=_parseServing(qEl.dataset.origQ||'');
  var np=_parseServing(qEl.value);
  if(!op||!np)return;
  if(_normUnit(op.u)!==_normUnit(np.u))return;
  var ratio=np.n/op.n;
  if(!isFinite(ratio)||ratio<=0)return;
  var origC =parseFloat(qEl.dataset.origC )||0;
  var origP =parseFloat(qEl.dataset.origP )||0;
  var origCb=parseFloat(qEl.dataset.origCb)||0;
  var origF =parseFloat(qEl.dataset.origF )||0;
  // Calories as integer, grams to 1 decimal (matches how the entries display).
  var cEl =document.getElementById('ef-c-' +id); if(cEl ) cEl .value=Math.round(origC *ratio);
  var pEl =document.getElementById('ef-p-' +id); if(pEl ) pEl .value=Math.round(origP *ratio*10)/10;
  var cbEl=document.getElementById('ef-cb-'+id); if(cbEl) cbEl.value=Math.round(origCb*ratio*10)/10;
  var fEl =document.getElementById('ef-f-' +id); if(fEl ) fEl .value=Math.round(origF *ratio*10)/10;
}}

function editFood(id){{
  var f=findFood(id);if(!f)return;
  // Stash the original quantity + macros on the quantity input's dataset so
  // onServingInput can scale from those baselines. Means typing/erasing/
  // re-typing the same quantity always returns to the original macros, and
  // proportional changes are exact (not compounding from earlier scales).
  var origQ =escA(f.quantity||'');
  var origC =(f.calories??0);
  var origP =(f.protein ??0);
  var origCb=(f.carbs   ??0);
  var origF =(f.fats    ??0);
  document.getElementById('food-row-'+id).innerHTML=
    '<div class="eform">'+
    '<input type="text" id="ef-n-'+id+'" value="'+escA(f.name)+'" placeholder="Food name">'+
    '<input type="text" id="ef-q-'+id+'" value="'+origQ+'" placeholder="Quantity"'+
      ' data-orig-q="'+origQ+'"'+
      ' data-orig-c="'+origC+'"'+
      ' data-orig-p="'+origP+'"'+
      ' data-orig-cb="'+origCb+'"'+
      ' data-orig-f="'+origF+'"'+
      ' oninput="onServingInput('+id+')">'+
    '<div class="emac">'+
    '<div class="emc"><label>Cal</label><input type="number" id="ef-c-'+id+'" value="'+(f.calories??'')+'" inputmode="numeric"></div>'+
    '<div class="emc"><label>P (g)</label><input type="number" id="ef-p-'+id+'" value="'+(f.protein??'')+'" inputmode="numeric"></div>'+
    '<div class="emc"><label>C (g)</label><input type="number" id="ef-cb-'+id+'" value="'+(f.carbs??'')+'" inputmode="numeric"></div>'+
    '<div class="emc"><label>F (g)</label><input type="number" id="ef-f-'+id+'" value="'+(f.fats??'')+'" inputmode="numeric"></div>'+
    '</div>'+
    '<div class="eact">'+
    '<button class="sbtn" onclick="saveFood('+id+')">Save</button>'+
    '<button class="cbtn" onclick="cancelEdit()">Cancel</button>'+
    '</div></div>';
}}

async function saveFood(id){{
  var body={{
    food_name:document.getElementById('ef-n-'+id).value,
    quantity:document.getElementById('ef-q-'+id).value,
    calories:parseFloat(document.getElementById('ef-c-'+id).value)||0,
    protein:parseFloat(document.getElementById('ef-p-'+id).value)||0,
    carbs:parseFloat(document.getElementById('ef-cb-'+id).value)||0,
    fats:parseFloat(document.getElementById('ef-f-'+id).value)||0,
  }};
  var btn=document.querySelector('#food-row-'+id+' .sbtn');
  if(btn){{btn.disabled=true;btn.textContent='…'}}
  var r=await fetch('/api/food/'+id+'?token='+TOKEN,{{
    method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body),
  }});
  if(!r.ok){{
    alert('Save failed — please try again.');
    if(btn){{btn.disabled=false;btn.textContent='Save'}}
    return;
  }}
  delete _dayCache[_viewingDate];await loadDayData(_viewingDate);
}}

async function deleteFood(id){{
  var f=findFood(id);
  if(!confirm('Delete "'+(f?f.name:'this item')+'"?')) return;
  var r=await fetch('/api/food/'+id+'?token='+TOKEN,{{method:'DELETE'}});
  if(!r.ok){{alert('Delete failed.');return}}
  delete _dayCache[_viewingDate];await loadDayData(_viewingDate);
}}

// ── Inline edit: exercise ─────────────────────────────────────────────────
function editExercise(id){{
  var e=findEx(id);if(!e)return;
  document.getElementById('ex-row-'+id).innerHTML=
    '<div class="eform">'+
    '<input type="text" id="ee-n-'+id+'" value="'+escA(e.name)+'" placeholder="Exercise name">'+
    '<div class="emac" style="grid-template-columns:repeat(3,1fr)">'+
    '<div class="emc"><label>Sets</label><input type="number" id="ee-s-'+id+'" value="'+(e.sets??'')+'" inputmode="numeric"></div>'+
    '<div class="emc"><label>Reps</label><input type="text" id="ee-r-'+id+'" value="'+escA(e.reps??'')+'"></div>'+
    '<div class="emc"><label>Weight (lb)</label><input type="number" id="ee-w-'+id+'" value="'+(e.weight??'')+'" inputmode="decimal"></div>'+
    '</div>'+
    '<div class="eact">'+
    '<button class="sbtn" onclick="saveExercise('+id+')">Save</button>'+
    '<button class="cbtn" onclick="cancelEdit()">Cancel</button>'+
    '</div></div>';
}}

async function saveExercise(id){{
  var body={{
    exercise_name:document.getElementById('ee-n-'+id).value||null,
    sets:parseInt(document.getElementById('ee-s-'+id).value)||null,
    reps:document.getElementById('ee-r-'+id).value||null,
    weight:parseFloat(document.getElementById('ee-w-'+id).value)||null,
  }};
  Object.keys(body).forEach(k=>body[k]==null&&delete body[k]);
  var btn=document.querySelector('#ex-row-'+id+' .sbtn');
  if(btn){{btn.disabled=true;btn.textContent='…'}}
  var r=await fetch('/api/exercise/'+id+'?token='+TOKEN,{{
    method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body),
  }});
  if(!r.ok){{
    alert('Save failed.');
    if(btn){{btn.disabled=false;btn.textContent='Save'}}
    return;
  }}
  delete _dayCache[_viewingDate];await loadDayData(_viewingDate);
}}

async function deleteExercise(id){{
  var e=findEx(id);
  if(!confirm('Delete "'+(e?e.name:'this exercise')+'"?')) return;
  var r=await fetch('/api/exercise/'+id+'?token='+TOKEN,{{method:'DELETE'}});
  if(!r.ok){{alert('Delete failed.');return}}
  delete _dayCache[_viewingDate];await loadDayData(_viewingDate);
}}

function cancelEdit(){{
  var d=_dayCache[_viewingDate];
  if(d) renderDayTab(d);
}}

// ── Profile inline editing ────────────────────────────────────────────────
function editProw(rowId,field,current){{
  var row=document.getElementById(rowId);if(!row)return;
  // Label discovery — older .inrow layouts use .inlbl, the new tile layout
  // (Goals & targets) uses .basic-lbl. Try both so the editor works in either.
  var lblEl = row.querySelector('.inlbl') || row.querySelector('.basic-lbl');
  var lbl = lblEl ? lblEl.textContent : '';
  var isTile = row.classList.contains('basic-cell');

  var _style='flex:1;min-width:0;background:var(--inp);border:1px solid var(--ac);color:var(--tx);'+
    'padding:5px 8px;border-radius:8px;font-size:12px;font-family:inherit;outline:none';
  if(!isTile) _style += ';max-width:170px';
  var opts=EDIT_OPTIONS[field], editor;
  if(opts){{
    // Picklist for enum fields. Keep any current off-list value selectable.
    // Friendly labels for primary_goal — option VALUE stays as DB key
    // (cut/bulk/…) so saves are wire-compatible, only the LABEL text changes.
    var cur=(current||'').toLowerCase(), list=opts.slice();
    if(cur && list.indexOf(cur)===-1) list.unshift(cur);
    var _opLbl = (field==='primary_goal') ? goalLabel : function(o){{ return o; }};
    editor='<select id="pi-'+rowId+'" style="'+_style+';text-transform:capitalize">'+
      list.map(function(o){{return '<option value="'+escA(o)+'"'+(o===cur?' selected':'')+'>'+esc(_opLbl(o))+'</option>';}}).join('')+
      '</select>';
  }}else{{
    editor='<input type="text" id="pi-'+rowId+'" value="'+escA(current)+'" style="'+_style+'">';
  }}

  if(isTile){{
    // Tile layout — keep the mono uppercase label on top, replace the value
    // row with the editor + save/cancel underneath. Compact buttons so the
    // tile doesn't grow during edit.
    row.innerHTML='<div class="basic-lbl">'+esc(lbl)+'</div>'+
      '<div style="display:flex;align-items:center;gap:4px;margin-top:1px">'+
      editor+
      '<button class="sbtn" style="flex:none;padding:4px 8px;font-size:11px;min-height:0" '+
      'onclick="saveProw(\\''+rowId+'\\',\\''+escA(field)+'\\')">✓</button>'+
      '<button class="cbtn" style="flex:none;padding:4px 6px;font-size:11px;min-height:0" '+
      'onclick="cancelProw()">✗</button></div>';
  }} else {{
    row.innerHTML='<span class="inlbl">'+esc(lbl)+'</span>'+
      '<div style="display:flex;align-items:center;gap:5px;flex:1;justify-content:flex-end">'+
      editor+
      '<button class="sbtn" style="flex:none;padding:5px 12px;font-size:12px;min-height:0" '+
      'onclick="saveProw(\\''+rowId+'\\',\\''+escA(field)+'\\')">✓</button>'+
      '<button class="cbtn" style="flex:none;padding:5px 10px;font-size:12px;min-height:0" '+
      'onclick="cancelProw()">✗</button></div>';
  }}
  var inp=document.getElementById('pi-'+rowId);
  if(inp){{inp.focus();if(inp.select)inp.select();}}
}}

async function saveProw(rowId,field){{
  var inp=document.getElementById('pi-'+rowId);if(!inp)return;
  var val=inp.value.trim();
  var btn=document.querySelector('#'+rowId+' .sbtn');
  if(btn){{btn.disabled=true;btn.textContent='…';}}
  try{{
    var r=await fetch('/api/profile/'+TOKEN,{{
      method:'PATCH',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{field:field,value:val||null}}),
    }});
    if(!r.ok)throw new Error('HTTP '+r.status);
    var data=await fetchStats(null);
    if(data){{
      _baseData=data;_dayCache[_todayStr]=data;
      renderProfileTab(data);
      var nm=document.getElementById('user-name'); if(nm) nm.textContent=data.profile?.name||'';
      var gt=document.getElementById('goal-tag'); if(gt) gt.textContent=goalLabel(data.profile?.primary_goal);
    }}
    reloadAIProfile();   // re-render the unified profile so the edited value shows
  }}catch(e){{
    alert('Save failed — try again.');
    if(btn){{btn.disabled=false;btn.textContent='✓';}}
  }}
}}

function cancelProw(){{
  // Re-render whichever section the row belongs to. Goals & targets edits
  // (pg-*) live in renderProfileTab; AI profile edits (pc-*/pr-*/pb-*) live
  // in renderAIProfile. Cheaper to just refresh both.
  if (_baseData) renderProfileTab(_baseData);
  reloadAIProfile();
}}

// ── Share day ─────────────────────────────────────────────────────────────
function shareDay(){{
  var day=(_dayCache[_viewingDate]?.day)||{{}};
  var tgt=(_baseData?.targets)||{{}};
  var lines=['📊 My day — '+_viewingDate,''];
  if(day.calories!=null){{
    var pctC=tgt.calories?Math.round(day.calories/tgt.calories*100):null;
    lines.push('🔥 Calories: '+day.calories+(tgt.calories?'/'+tgt.calories+(pctC?' ('+pctC+'%)':''):''));
  }}
  if(day.protein!=null){{
    var pctP=tgt.protein?Math.round(day.protein/tgt.protein*100):null;
    lines.push('💪 Protein: '+day.protein+'g'+(tgt.protein?'/'+tgt.protein+'g'+(pctP?' ('+pctP+'%)':''):''));
  }}
  if(day.workout_completed)lines.push('🏋️ Workout: done');
  if(day.cardio_completed)lines.push('🏃 Cardio: done');
  if(day.water_ml>0)lines.push('💧 Water: '+(day.water_ml>=1000?(day.water_ml/1000).toFixed(1)+'L':day.water_ml+'ml'));
  var exs=day.exercise_entries||[];
  if(exs.length){{
    lines.push('');
    exs.forEach(function(e){{
      if(e.sets&&e.reps)lines.push('  '+e.name+' — '+e.sets+'×'+e.reps+(e.weight?' @ '+e.weight+'lb':''));
      else if(e.duration_minutes)lines.push('  '+e.name+' — '+e.duration_minutes+' min');
    }});
  }}
  var text=lines.join('\\n');
  if(navigator.share){{
    navigator.share({{title:'Arnie — Day Summary',text:text}}).catch(function(){{}});
  }}else{{
    navigator.clipboard.writeText(text).then(function(){{
      var btn=document.querySelector('.share-tgl');
      if(btn){{var old=btn.innerHTML;btn.innerHTML='&#10003; Copied!';setTimeout(function(){{btn.innerHTML=old;}},1800);}}
    }}).catch(function(){{prompt('Copy your day summary:',text);}});
  }}
}}

// ── Log Modal ─────────────────────────────────────────────────────────────
var _lmTab='food', _lmExType='lift', _lmPer100=null, _lmSearchTimer=null;

function openLogModal(){{
  var m=document.getElementById('log-modal');
  if(m){{m.style.display='flex';document.getElementById('lm-search')&&document.getElementById('lm-search').focus();}}
}}
function closeLogModal(){{
  var m=document.getElementById('log-modal');
  if(m)m.style.display='none';
  // reset
  var s=document.getElementById('lm-search');if(s)s.value='';
  var r=document.getElementById('lm-results');if(r){{r.style.display='none';r.innerHTML='';}}
  var sel=document.getElementById('lm-selected');if(sel)sel.style.display='none';
  _lmPer100=null;
  ['lm-cal','lm-pro','lm-carb','lm-fat','lm-qty'].forEach(function(id){{var e=document.getElementById(id);if(e)e.value='';}});
  ['lm-ex-name','lm-sets','lm-reps','lm-weight','lm-dur'].forEach(function(id){{var e=document.getElementById(id);if(e)e.value='';}});
}}

function switchLogTab(tab){{
  _lmTab=tab;
  document.getElementById('lm-tab-food').classList.toggle('active',tab==='food');
  document.getElementById('lm-tab-exercise').classList.toggle('active',tab==='exercise');
  document.getElementById('lm-food').style.display=tab==='food'?'flex':'none';
  document.getElementById('lm-exercise').style.display=tab==='exercise'?'flex':'none';
  document.getElementById('lm-title').textContent=tab==='food'?'Log food':'Log workout';
}}

function setExType(t){{
  _lmExType=t;
  document.getElementById('lm-lift-btn').classList.toggle('active',t==='lift');
  document.getElementById('lm-cardio-btn').classList.toggle('active',t==='cardio');
  document.getElementById('lm-lift-fields').style.display=t==='lift'?'block':'none';
  document.getElementById('lm-cardio-fields').style.display=t==='cardio'?'block':'none';
}}

function lmSearchDebounce(){{
  clearTimeout(_lmSearchTimer);
  var q=(document.getElementById('lm-search').value||'').trim();
  if(q.length<2){{
    var r=document.getElementById('lm-results');r.style.display='none';r.innerHTML='';
    return;
  }}
  _lmSearchTimer=setTimeout(function(){{lmSearch(q);}},320);
}}

async function lmSearch(q){{
  var r=document.getElementById('lm-results');
  r.innerHTML='<div class="lm-result" style="color:var(--mu)">Searching…</div>';
  r.style.display='block';
  try{{
    var resp=await fetch('/api/food/search?q='+encodeURIComponent(q)+'&token='+TOKEN);
    if(!resp.ok)throw new Error();
    var data=await resp.json();
    var items=data.results||[];
    if(!items.length){{r.innerHTML='<div class="lm-result" style="color:var(--mu)">No results — enter macros manually</div>';return;}}
    r.innerHTML=items.map(function(item,i){{
      var p100=item.per100g||{{}};
      var cal=Math.round(p100.calories||0);
      var pro=Math.round(p100.protein||0);
      var carb=Math.round(p100.carbs||0);
      var fat=Math.round(p100.fat||p100.fats||0);
      var brand=item.brand?'<span style="color:var(--di)"> · '+esc(item.brand)+'</span>':'';
      return '<div class="lm-result" onclick="lmSelectFood('+i+')" data-i="'+i+'">'+
        '<div class="lm-result-name">'+esc(item.description||item.name)+brand+'</div>'+
        '<div class="lm-result-meta">'+cal+' cal · '+pro+'g P · '+carb+'g C · '+fat+'g F &nbsp;<span style="color:var(--di)">per 100g</span></div>'+
        '</div>';
    }}).join('');
    r._items=items;
  }}catch(e){{
    r.innerHTML='<div class="lm-result" style="color:var(--mu)">Search failed — enter macros manually</div>';
  }}
}}

function lmSelectFood(i){{
  var r=document.getElementById('lm-results');
  if(!r._items||!r._items[i])return;
  var item=r._items[i];
  var p100=item.per100g||{{}};
  _lmPer100=p100;
  r.style.display='none';
  // populate search with selected name
  var s=document.getElementById('lm-search');
  if(s)s.value=item.description||item.name;
  // show selected card
  var sel=document.getElementById('lm-selected');
  var selName=document.getElementById('lm-sel-name');
  var selMacros=document.getElementById('lm-sel-macros');
  selName.textContent=item.description||item.name;
  var cal=Math.round(p100.calories||0);
  var pro=+(p100.protein||0).toFixed(1);
  var carb=+(p100.carbs||0).toFixed(1);
  var fat=+(p100.fat||p100.fats||0).toFixed(1);
  selMacros.innerHTML=
    '<span><b>'+cal+'</b> cal</span>'+
    '<span style="color:var(--bl)"><b>'+pro+'g</b> P</span>'+
    '<span style="color:var(--or)"><b>'+carb+'g</b> C</span>'+
    '<span style="color:var(--pu)"><b>'+fat+'g</b> F</span>'+
    '<span style="color:var(--di)">per 100g</span>';
  sel.style.display='block';
  // Set macros for 100g default
  lmSetMacros(100, p100);
  var qty=document.getElementById('lm-qty');if(qty)qty.value='100';
  // focus qty
  setTimeout(function(){{if(qty)qty.focus();}},50);
}}

function lmSetMacros(grams,p100){{
  var ratio=grams/100;
  var set=function(id,val){{var e=document.getElementById(id);if(e)e.value=isNaN(val)?'':String(Math.round(val*10)/10);}};
  set('lm-cal',Math.round((p100.calories||0)*ratio));
  set('lm-pro',((p100.protein||0)*ratio));
  set('lm-carb',((p100.carbs||0)*ratio));
  set('lm-fat',((p100.fat||p100.fats||0)*ratio));
}}

function lmQtyChange(){{
  if(!_lmPer100)return;
  var qty=document.getElementById('lm-qty');
  if(!qty)return;
  var g=parseFloat(qty.value);
  if(!isNaN(g)&&g>0)lmSetMacros(g,_lmPer100);
}}

async function submitFood(){{
  var name=(document.getElementById('lm-search').value||'').trim();
  if(!name){{document.getElementById('lm-search').focus();return;}}
  var qty=(document.getElementById('lm-qty').value||'').trim()||null;
  var cal=parseFloat(document.getElementById('lm-cal').value)||0;
  var pro=parseFloat(document.getElementById('lm-pro').value)||0;
  var carb=parseFloat(document.getElementById('lm-carb').value)||0;
  var fat=parseFloat(document.getElementById('lm-fat').value)||0;
  var estimated=!_lmPer100;
  var btn=document.getElementById('lm-food-btn');
  btn.disabled=true;btn.textContent='Logging…';
  try{{
    var resp=await fetch('/api/food/log?token='+TOKEN,{{
      method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{name,quantity:qty,calories:cal,protein:pro,carbs:carb,fats:fat,estimated,log_date:_viewingDate}})
    }});
    if(!resp.ok)throw new Error('HTTP '+resp.status);
    closeLogModal();
    delete _dayCache[_viewingDate];
    await loadDayData(_viewingDate);
  }}catch(e){{
    btn.textContent='Error — retry';
  }}finally{{
    btn.disabled=false;
    if(btn.textContent==='Logging…')btn.textContent='Log food';
  }}
}}

async function submitExercise(){{
  var name=(document.getElementById('lm-ex-name').value||'').trim();
  if(!name){{document.getElementById('lm-ex-name').focus();return;}}
  var isCardio=_lmExType==='cardio';
  var sets=parseInt(document.getElementById('lm-sets').value)||null;
  var reps=(document.getElementById('lm-reps').value||'').trim()||null;
  var weight=parseFloat(document.getElementById('lm-weight').value)||null;
  var dur=parseFloat(document.getElementById('lm-dur').value)||null;
  var btn=document.getElementById('lm-ex-btn');
  btn.disabled=true;btn.textContent='Logging…';
  try{{
    var resp=await fetch('/api/exercise/log?token='+TOKEN,{{
      method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{name,sets,reps,weight_lbs:weight,duration_minutes:dur,is_cardio:isCardio,log_date:_viewingDate}})
    }});
    if(!resp.ok)throw new Error('HTTP '+resp.status);
    closeLogModal();
    delete _dayCache[_viewingDate];
    await loadDayData(_viewingDate);
  }}catch(e){{
    btn.textContent='Error — retry';
  }}finally{{
    btn.disabled=false;
    if(btn.textContent==='Logging…')btn.textContent='Log workout';
  }}
}}

// Wire up + Log button
function focusLogInput(){{switchTab('day');openLogModal();}}

// Close on Escape
document.addEventListener('keydown',function(e){{
  if(e.key==='Escape'){{
    var m=document.getElementById('log-modal');
    if(m&&m.style.display!=='none')closeLogModal();
  }}
}});

// ── Start ─────────────────────────────────────────────────────────────────
// Scroll to top on tab switch
(function(){{
  var _orig=switchTab;
  switchTab=function(name){{
    _orig(name);
    window.scrollTo({{top:0,behavior:'smooth'}});
  }};
}})();

// Coach Insights now collapse natively (banner-only by default on all views).

init();
_resetInsAuto();   // start the 3h auto-refresh for Coach Insights
setInterval(()=>{{
  delete _dayCache[_todayStr];
  if(_viewingDate===_todayStr) refreshCurrent();
}}, 5*60*1000);

// ── Live chat widget — consolidated Telegram + iMessage thread ─────────────
var _cwOpen=false, _cwTimer=null, _cwSig='';
function _cwChan(p){{return(String(p||'').indexOf('imessage')>-1||String(p||'').indexOf('im:')>-1)?'im':'tg';}}
// Arnie splits replies into separate bubbles with '|||'. On the web thread we
// don't re-bubble — just turn the separator into a line break so it reads clean.
function _cwClean(s){{return String(s||'').replace(/\\s*\\|{{3,}}\\s*/g,'\\n').trim();}}
async function _cwFetch(limit){{
  var r=await fetch('/api/conversation/'+TOKEN+(limit?('?limit='+limit):''));
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}}
function toggleChatWidget(){{
  _cwOpen=!_cwOpen;
  var panel=document.getElementById('cw-panel');
  panel.classList.toggle('open',_cwOpen);
  panel.setAttribute('aria-hidden',_cwOpen?'false':'true');
  var btn=document.getElementById('chat-btn');
  if(btn) btn.classList.toggle('open',_cwOpen);
  if(_cwOpen){{
    loadChatWidget(true);
    if(_cwTimer) clearInterval(_cwTimer);
    _cwTimer=setInterval(function(){{loadChatWidget(false);}},25000);
  }}else if(_cwTimer){{clearInterval(_cwTimer);_cwTimer=null;}}
}}
async function loadChatWidget(initial){{
  var thread=document.getElementById('cw-thread');
  if(initial) thread.innerHTML='<div class="cw-state">Loading your conversation&hellip;</div>';
  try{{
    var data=await _cwFetch(120);
    renderChatThread(data.turns||[],initial);
    var sub=document.getElementById('cw-sub'), plats=data.platforms||[];
    if(sub&&plats.length) sub.textContent=plats.length>1?'Telegram + iMessage':(plats[0]==='imessage'?'iMessage':'Telegram');
  }}catch(e){{
    if(initial) thread.innerHTML='<div class="cw-state">Could not load the conversation. Tap the bubble to retry.</div>';
  }}
}}
function renderChatThread(turns,initial){{
  var thread=document.getElementById('cw-thread');
  if(!turns.length){{
    thread.innerHTML='<div class="cw-state">No messages yet. Your chats with Arnie on Telegram and iMessage will show up here.</div>';
    _cwSig='';return;
  }}
  var last=turns[turns.length-1];
  var sig=turns.length+'|'+(last.ts||'');
  if(!initial && sig===_cwSig) return;   // nothing new — skip re-render (no scroll jump)
  _cwSig=sig;
  var wasNear=thread.scrollHeight-thread.scrollTop-thread.clientHeight<80;
  var html='',prevDay='';
  for(var i=0;i<turns.length;i++){{
    var t=turns[i];
    var d=t.ts?new Date(t.ts):null;
    var day=d?d.toLocaleDateString('en-US',{{weekday:'short',month:'short',day:'numeric'}}):'';
    if(day && day!==prevDay){{html+='<div class="cw-day">'+esc(day)+'</div>';prevDay=day;}}
    var time=d?d.toLocaleTimeString('en-US',{{hour:'numeric',minute:'2-digit'}}):'';
    var chan=_cwChan(t.platform), chanLbl=chan==='im'?'iMessage':'Telegram';
    var ico=t.source==='voice'?'\\ud83c\\udfa4 ':((t.source==='image'||t.source==='photo')?'\\ud83d\\udcf7 ':'');
    if((t.user||'').trim()){{
      html+='<div class="cw-row me"><div class="cw-bubble">'+ico+esc(_cwClean(t.user))+'</div>'
          +'<div class="cw-meta"><span class="cw-cdot '+chan+'"></span>'+esc(chanLbl+' \\u00b7 '+time)+'</div></div>';
    }}
    if((t.arnie||'').trim()){{
      html+='<div class="cw-row ar"><div class="cw-bubble">'+esc(_cwClean(t.arnie))+'</div></div>';
    }}
  }}
  thread.innerHTML=html;
  if(initial||wasNear) thread.scrollTop=thread.scrollHeight;
}}
</script>

<!-- LOG MODAL — direct body child so position:fixed works across all containers -->
<div class="lm-overlay" id="log-modal" style="display:none" onclick="if(event.target===this)closeLogModal()">
  <div class="lm-box">
    <div class="lm-head">
      <div class="lm-title" id="lm-title">Log</div>
      <button class="lm-close" onclick="closeLogModal()">&#215;</button>
    </div>
    <div class="lm-tabs">
      <button class="lm-tab active" id="lm-tab-food" onclick="switchLogTab('food')">&#127869; Food</button>
      <button class="lm-tab" id="lm-tab-exercise" onclick="switchLogTab('exercise')">&#127947; Workout</button>
    </div>
    <!-- FOOD PANEL -->
    <div class="lm-body" id="lm-food">
      <div class="lm-field lm-search-wrap">
        <label class="lm-label">Search food</label>
        <input class="lm-input" id="lm-search" type="text" placeholder="e.g. grilled chicken, banana…" autocomplete="off" oninput="lmSearchDebounce()" />
        <div class="lm-results" id="lm-results" style="display:none"></div>
      </div>
      <div id="lm-selected" style="display:none">
        <div class="lm-selected">
          <div class="lm-sel-name" id="lm-sel-name"></div>
          <div class="lm-sel-macros" id="lm-sel-macros"></div>
        </div>
      </div>
      <div class="lm-field">
        <label class="lm-label">Quantity <span style="color:var(--di);text-transform:none;letter-spacing:0;font-family:inherit">(grams, or describe: "1 cup")</span></label>
        <input class="lm-input" id="lm-qty" type="text" placeholder="e.g. 150  or  1 large" oninput="lmQtyChange()" />
      </div>
      <div class="lm-macro-row">
        <div class="lm-field"><label class="lm-label">Cal</label><input class="lm-input" id="lm-cal" type="number" min="0" step="1" placeholder="0" /></div>
        <div class="lm-field"><label class="lm-label">P (g)</label><input class="lm-input" id="lm-pro" type="number" min="0" step="0.1" placeholder="0" /></div>
        <div class="lm-field"><label class="lm-label">C (g)</label><input class="lm-input" id="lm-carb" type="number" min="0" step="0.1" placeholder="0" /></div>
        <div class="lm-field"><label class="lm-label">F (g)</label><input class="lm-input" id="lm-fat" type="number" min="0" step="0.1" placeholder="0" /></div>
      </div>
      <button class="lm-submit" id="lm-food-btn" onclick="submitFood()">Log food</button>
    </div>
    <!-- EXERCISE PANEL -->
    <div class="lm-body" id="lm-exercise" style="display:none">
      <div class="lm-field">
        <label class="lm-label">Exercise name</label>
        <input class="lm-input" id="lm-ex-name" type="text" placeholder="e.g. Bench press, Running…" />
      </div>
      <div class="lm-field">
        <label class="lm-label">Type</label>
        <div class="lm-type-row">
          <button class="lm-type-btn active" id="lm-lift-btn" onclick="setExType('lift')">&#127959; Strength</button>
          <button class="lm-type-btn" id="lm-cardio-btn" onclick="setExType('cardio')">&#127939; Cardio</button>
        </div>
      </div>
      <div id="lm-lift-fields">
        <div class="lm-macro-row">
          <div class="lm-field"><label class="lm-label">Sets</label><input class="lm-input" id="lm-sets" type="number" min="1" step="1" placeholder="3" /></div>
          <div class="lm-field"><label class="lm-label">Reps</label><input class="lm-input" id="lm-reps" type="text" placeholder="10" /></div>
          <div class="lm-field" style="grid-column:span 2"><label class="lm-label">Weight (lbs)</label><input class="lm-input" id="lm-weight" type="number" min="0" step="2.5" placeholder="135" /></div>
        </div>
      </div>
      <div id="lm-cardio-fields" style="display:none">
        <div class="lm-field"><label class="lm-label">Duration (minutes)</label><input class="lm-input" id="lm-dur" type="number" min="1" step="1" placeholder="30" /></div>
      </div>
      <button class="lm-submit" id="lm-ex-btn" onclick="submitExercise()">Log workout</button>
    </div>
  </div>
</div>

<!-- LIVE CHAT WIDGET — floating, consolidated Telegram + iMessage thread -->
<div class="cw-panel" id="cw-panel" aria-hidden="true" aria-label="Your conversation with Arnie">
  <div class="cw-head">
    <div class="cw-head-l">
      <span class="cw-status" role="img" aria-label="Arnie — online"></span>
      <div style="min-width:0">
        <div class="cw-title">Arnie</div>
        <div class="cw-sub" id="cw-sub">Telegram + iMessage</div>
      </div>
    </div>
    <button class="cw-close" onclick="toggleChatWidget()" aria-label="Close">&#215;</button>
  </div>
  <div class="cw-thread" id="cw-thread"><div class="cw-state">Loading&hellip;</div></div>
  <a class="cw-tg" href="tg://resolve?domain={bot_username}" target="_blank" rel="noopener">
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M22 3 11 14"/><path d="M22 3 15 22l-4-8-8-4z"/></svg>
    New message on Telegram
  </a>
</div>
</body>
</html>"""



def _apple_guide_html(endpoint: str, status_url: str = "", shortcut_url: str = "") -> str:  # noqa: C901
    # Pre-build the URL template shown in Step 3 — user pastes this into
    # the "URL" action and inserts Shortcuts variables for each placeholder.
    url_template = (
        f"{endpoint}"
        "&steps=[steps]"
        "&active_calories=[cals]"
        "&resting_calories=[rest]"
        "&sleep_seconds=[sleep]"
    )
    one_tap_html = f"""
<!-- ONE-TAP SETUP -->
<div class="onetap">
  <div class="ot-badge">Recommended</div>
  <div class="ot-title">Fast setup</div>
  <div class="ot-sub">No manual Shortcut building. Copy your URL, download the Shortcut, paste once, then run it.</div>
  <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:14px">
    <div class="ot-step"><span class="ot-n">1</span><div><b>Copy your sync URL</b> using the button below</div></div>
    <div class="ot-step"><span class="ot-n">2</span><div>Open this page in <b>Safari</b> &rarr; tap <b>Download Shortcut</b> &rarr; tap <b>Add Shortcut</b></div></div>
    <div class="ot-step"><span class="ot-n">3</span><div>When iOS asks <b>"Your Arnie sync URL"</b> &mdash; paste what you copied</div></div>
  </div>

  <div class="crow" style="margin-bottom:10px">
    <div class="cval" id="ep-url" style="font-size:11px">{endpoint}</div>
    <button class="cbtn" onclick="cp(document.getElementById('ep-url').textContent.trim(),this)">Copy URL</button>
  </div>

  <a href="{shortcut_url}" class="ot-btn">
    <span style="font-size:18px">&#11015;</span> Download Shortcut
  </a>
  <div class="ot-hint" style="margin-top:10px">
    Not in Safari? &nbsp;<button class="cbtn" style="font-size:11px;padding:4px 11px" onclick="cp(window.location.href,this)">Copy page link</button>&nbsp; then paste in Safari.
  </div>
</div>
<div class="div-or"><span>or set up manually</span></div>
""" if shortcut_url else ""
    status_script = f"""
(function poll() {{
  fetch('{status_url}')
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      var b = document.getElementById('sb');
      var t = document.getElementById('stxt');
      var m = document.getElementById('smeta');
      if (d.connected) {{
        b.className = 'sbanner yes';
        t.textContent = 'Apple Health connected ✓';
        var p = [];
        if (d.last_sync) p.push('Last sync: ' + d.last_sync);
        if (d.steps) p.push(Number(d.steps).toLocaleString() + ' steps');
        if (d.active_calories) p.push(Math.round(d.active_calories) + ' active kcal');
        if (d.resting_hr) p.push(d.resting_hr + 'bpm RHR');
        m.textContent = p.join(' · ');
      }} else {{
        b.className = 'sbanner no';
        t.textContent = 'Not connected yet';
        m.textContent = 'Finish setup and tap ▷ in Shortcuts to test — this page auto-updates';
        setTimeout(poll, 12000);
      }}
    }})
    .catch(function() {{
      document.getElementById('sb').className = 'sbanner no';
      document.getElementById('stxt').textContent = 'Could not check status';
    }});
}})();
""" if status_url else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Connect Apple Health — Arnie</title>
<style>
/* ── Reset & base ── */
*{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}
html{{font-size:16px}}
body{{
  font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;
  background:#08090e;color:#c9d4e8;min-height:100vh;
  -webkit-font-smoothing:antialiased;
  padding:0 0 80px;
}}

/* ── Header ── */
.hdr{{
  background:rgba(8,9,14,.95);border-bottom:1px solid rgba(255,255,255,.07);
  padding:14px 20px;position:sticky;top:0;z-index:20;backdrop-filter:blur(16px);
  display:flex;align-items:center;justify-content:space-between;
}}
.logo{{
  font-size:16px;font-weight:800;
  background:linear-gradient(130deg,#00e676,#4a9eff);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}}

/* ── Layout ── */
main{{max-width:520px;margin:0 auto;padding:28px 16px 0}}
h1{{font-size:26px;font-weight:800;color:#eef2ff;letter-spacing:-.4px;margin-bottom:6px}}
.sub{{font-size:15px;color:#546070;line-height:1.6;margin-bottom:24px}}

/* ── Status banner ── */
.sbanner{{
  display:flex;align-items:flex-start;gap:11px;
  border-radius:14px;padding:13px 15px;margin-bottom:26px;
  transition:background .4s,border .4s;
}}
.sbanner.loading{{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07)}}
.sbanner.yes{{background:rgba(0,230,118,.07);border:1px solid rgba(0,230,118,.22)}}
.sbanner.no{{background:rgba(74,158,255,.06);border:1px solid rgba(74,158,255,.18)}}
.sdot{{
  width:10px;height:10px;border-radius:50%;flex-shrink:0;margin-top:4px;
}}
.sbanner.loading .sdot{{background:#2a3040}}
.sbanner.yes .sdot{{background:#00e676;box-shadow:0 0 8px rgba(0,230,118,.6)}}
.sbanner.no .sdot{{background:#4a9eff}}
.stext{{font-size:14px;font-weight:600;color:#c9d4e8}}
.sbanner.yes .stext{{color:#00e676}}
.sbanner.no .stext{{color:#4a9eff}}
.smeta{{font-size:13px;color:#546070;margin-top:3px}}

/* ── Section title ── */
.stitle{{
  font-size:11px;font-weight:700;color:#2a3040;
  text-transform:uppercase;letter-spacing:1.2px;
  margin:0 0 10px;
}}

/* ── Copy row — the main UI primitive ── */
.crow{{
  display:flex;align-items:center;gap:10px;
  background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);
  border-radius:12px;padding:11px 14px;margin-bottom:8px;
}}
.cval{{
  flex:1;font-family:'SF Mono',ui-monospace,monospace;
  font-size:12.5px;color:#00e676;word-break:break-all;
  line-height:1.5;user-select:all;
}}
.cval.plain{{color:#c9d4e8;font-family:inherit;font-size:14px}}
.cbtn{{
  background:rgba(0,230,118,.10);border:1px solid rgba(0,230,118,.25);
  color:#00e676;border-radius:9px;padding:7px 14px;
  font-size:13px;font-weight:700;cursor:pointer;
  white-space:nowrap;font-family:inherit;flex-shrink:0;
  transition:all .15s;-webkit-appearance:none;
}}
.cbtn:active{{transform:scale(.91);opacity:.75}}
.cbtn.ok{{background:rgba(0,230,118,.2);color:#00e676}}

/* ── Step card ── */
.step{{
  background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.07);
  border-radius:18px;padding:20px;margin-bottom:10px;
}}
.step-hd{{display:flex;align-items:center;gap:14px;margin-bottom:14px}}
.snum{{
  width:36px;height:36px;border-radius:50%;flex-shrink:0;
  background:rgba(0,230,118,.09);border:1px solid rgba(0,230,118,.20);
  color:#00e676;font-size:15px;font-weight:800;
  display:flex;align-items:center;justify-content:center;
}}
.stname{{font-size:17px;font-weight:700;color:#eef2ff;letter-spacing:-.2px}}
p{{font-size:14px;color:#6a7a90;line-height:1.65;margin-bottom:10px}}
p:last-child{{margin-bottom:0}}
p b{{color:#b0bdd0;font-weight:600}}
.note{{
  background:rgba(74,158,255,.06);border:1px solid rgba(74,158,255,.15);
  border-radius:11px;padding:12px 14px;font-size:13.5px;color:#5a7090;
  line-height:1.6;margin-top:4px;
}}
.note b{{color:#4a9eff}}
.note.grn{{background:rgba(0,230,118,.05);border-color:rgba(0,230,118,.15)}}
.note.grn b{{color:#00e676}}

/* ── Metric rows (step 2) ── */
.mrow{{
  display:grid;grid-template-columns:1fr auto auto;
  gap:8px;align-items:center;
  background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.07);
  border-radius:12px;padding:11px 14px;margin-bottom:8px;
}}
.mname{{font-size:14px;font-weight:600;color:#eef2ff}}
.msearch{{font-size:12px;color:#546070;margin-top:2px}}
.mvar{{
  font-family:'SF Mono',ui-monospace,monospace;font-size:12px;
  background:rgba(0,230,118,.08);border:1px solid rgba(0,230,118,.18);
  color:#00e676;border-radius:7px;padding:4px 10px;white-space:nowrap;
}}
.mcopy{{
  background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.10);
  color:#546070;border-radius:8px;padding:5px 11px;
  font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;
  font-family:inherit;-webkit-appearance:none;transition:all .15s;
}}
.mcopy:active{{transform:scale(.90)}}
.mcopy.ok{{color:#00e676;background:rgba(0,230,118,.09);border-color:rgba(0,230,118,.22)}}

/* ── URL template (step 3) ── */
.url-template{{
  background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.08);
  border-radius:12px;padding:14px;font-family:'SF Mono',ui-monospace,monospace;
  font-size:12px;color:#546070;line-height:1.7;word-break:break-all;
  margin:10px 0;
}}
.url-base{{color:#00e676}}
.url-param{{color:#4a9eff}}
.url-var{{color:#f59e0b}}

hr{{border:none;border-top:1px solid rgba(255,255,255,.06);margin:26px 0}}
footer{{text-align:center;padding:24px 0 0;color:#2a3040;font-size:12px}}

/* ── One-tap section ── */
.onetap{{
  background:rgba(0,230,118,.04);border:1px solid rgba(0,230,118,.14);
  border-radius:20px;padding:22px 20px;margin-bottom:22px;
}}
.ot-badge{{
  display:inline-block;background:rgba(0,230,118,.12);border:1px solid rgba(0,230,118,.25);
  color:#00e676;font-size:10px;font-weight:800;letter-spacing:1px;
  text-transform:uppercase;border-radius:6px;padding:3px 9px;margin-bottom:10px;
}}
.ot-title{{font-size:20px;font-weight:800;color:#eef2ff;letter-spacing:-.3px;margin-bottom:6px}}
.ot-sub{{font-size:14px;color:#546070;line-height:1.6;margin-bottom:14px}}
.ot-step{{
  display:flex;align-items:flex-start;gap:10px;
  background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.07);
  border-radius:12px;padding:11px 13px;font-size:14px;color:#c9d4e8;line-height:1.5;
}}
.ot-n{{
  width:22px;height:22px;border-radius:50%;flex-shrink:0;
  background:rgba(0,230,118,.12);border:1px solid rgba(0,230,118,.25);
  color:#00e676;font-size:12px;font-weight:800;
  display:flex;align-items:center;justify-content:center;margin-top:1px;
}}
.ot-prereq{{
  background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.2);
  border-radius:11px;padding:11px 13px;font-size:13px;color:#8a7050;
  line-height:1.6;margin-bottom:14px;
}}
.ot-prereq b{{color:#f59e0b}}
.ot-btn{{
  display:flex;align-items:center;justify-content:center;gap:8px;
  background:linear-gradient(135deg,rgba(0,230,118,.15),rgba(74,158,255,.10));
  border:1.5px solid rgba(0,230,118,.4);
  color:#00e676;font-size:16px;font-weight:800;
  border-radius:15px;padding:17px;text-decoration:none;
  letter-spacing:-.2px;transition:all .15s;-webkit-appearance:none;
}}
.ot-btn:active{{transform:scale(.97);opacity:.8}}
.ot-hint{{text-align:center;font-size:11.5px;color:#2a3040;margin-top:8px;line-height:1.5}}
.div-or{{
  display:flex;align-items:center;gap:12px;
  margin:22px 0 18px;color:#2a3040;font-size:11.5px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;
}}
.div-or::before,.div-or::after{{content:'';flex:1;border-top:1px solid rgba(255,255,255,.06)}}

/* ── iOS Shortcuts Mockups ── */
.ss-wrap{{margin:18px 0 4px}}
.ss-lbl{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;color:#2a3040;margin-bottom:7px}}
.ss-screen{{background:#0f0f11;border:1px solid rgba(255,255,255,.09);border-radius:16px;overflow:hidden}}
.ss-nav{{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#161618;border-bottom:1px solid rgba(255,255,255,.06)}}
.ss-back{{font-size:13px;color:#0a84ff;font-weight:500}}
.ss-title{{font-size:14px;font-weight:700;color:#fff}}
.ss-run{{font-size:16px;color:#0a84ff}}
.ss-body{{padding:7px 7px 8px}}
.ss-act{{background:#1c1c1e;border-radius:11px;margin-bottom:4px;overflow:hidden;border:1px solid transparent}}
.ss-act.hi{{border-color:rgba(10,132,255,.3)}}
.ss-act.hi-grn{{border-color:rgba(48,209,88,.28)}}
.ss-hd{{display:flex;align-items:center;gap:7px;padding:8px 10px 6px}}
.ss-ic{{width:20px;height:20px;border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:10px;flex-shrink:0;color:#fff}}
.ss-ic.r{{background:#ff375f}}.ss-ic.b{{background:#0a84ff}}.ss-ic.t{{background:#5ac8fa}}.ss-ic.a{{background:#ff9f0a}}
.ss-nm{{font-size:12px;font-weight:600;color:#fff}}
.ss-bd{{padding:0 10px 7px 37px}}
.ss-info{{font-size:10.5px;color:#636366;line-height:1.5}}
.ss-pill{{display:inline-flex;align-items:center;background:rgba(255,159,10,.14);border:1px solid rgba(255,159,10,.3);color:#ff9f0a;border-radius:4px;padding:1px 5px;font-family:'SF Mono',monospace;font-size:9.5px;font-weight:600;vertical-align:middle;margin:0 1px}}
.ss-pill.b{{background:rgba(10,132,255,.12);border-color:rgba(10,132,255,.28);color:#4a9eff}}
.ss-add{{text-align:center;padding:8px;font-size:11px;color:#2a3040;background:rgba(255,255,255,.015);border:1px dashed rgba(255,255,255,.07);border-radius:10px;margin-top:2px}}
.ss-dim{{opacity:.35}}
</style>
</head>
<body>
<div class="hdr"><div class="logo">⚡ Arnie</div></div>
<main>

<h1>Connect Apple Health</h1>
<p class="sub">Open this page on your iPhone in Safari. Download the ready-made Shortcut, paste your sync URL once, then run it and allow Health access.</p>

{one_tap_html}

<!-- STATUS -->
<div class="sbanner loading" id="sb">
  <div class="sdot"></div>
  <div>
    <div class="stext" id="stxt">Checking connection…</div>
    <div class="smeta" id="smeta"></div>
  </div>
</div>

<!-- ── STEP 1 ── -->
<div class="step">
  <div class="step-hd">
    <div class="snum">1</div>
    <div class="stname">Create a new Shortcut</div>
  </div>
  <p>Open the <b>Shortcuts</b> app on your iPhone &rarr; tap <b>+</b> in the top-right corner.</p>
  <p>Tap the title at the top and type a name, then tap <b>Done</b>. Copy the name below to use it exactly:</p>
  <div class="crow">
    <div class="cval plain">Arnie Health</div>
    <button class="cbtn" onclick="cp('Arnie Health',this)">Copy</button>
  </div>
</div>

<!-- ── STEP 2 ── -->
<div class="step">
  <div class="step-hd">
    <div class="snum">2</div>
    <div class="stname">Add 4 health queries</div>
  </div>
  <p>For each row below, tap <b>Add Action</b> in Shortcuts &rarr; search for the term &rarr; tap it. Then:</p>
  <p style="margin-bottom:12px">① Make sure <b>Today</b> is selected &nbsp; ② Set <b>Summarise</b> to <b>Sum</b> &nbsp; ③ Tap the blue result chip at the bottom &rarr; <b>Set Variable</b> &rarr; paste the name &rarr; <b>Done</b></p>

  <div class="mrow">
    <div><div class="mname">Steps</div><div class="msearch">Search for &rarr;</div></div>
    <button class="mcopy" onclick="cp('Step Count',this)">Step Count</button>
    <button class="mcopy" onclick="cp('steps',this)">steps</button>
  </div>
  <div class="mrow">
    <div><div class="mname">Active Calories</div><div class="msearch">Search for &rarr;</div></div>
    <button class="mcopy" onclick="cp('Active Energy Burned',this)">Active Energy Burned</button>
    <button class="mcopy" onclick="cp('cals',this)">cals</button>
  </div>
  <div class="mrow">
    <div><div class="mname">Resting Calories</div><div class="msearch">Search for &rarr;</div></div>
    <button class="mcopy" onclick="cp('Basal Energy Burned',this)">Basal Energy Burned</button>
    <button class="mcopy" onclick="cp('rest',this)">rest</button>
  </div>
  <div class="mrow">
    <div><div class="mname">Sleep</div><div class="msearch">Search for &rarr;</div></div>
    <button class="mcopy" onclick="cp('Sleep Analysis',this)">Sleep Analysis</button>
    <button class="mcopy" onclick="cp('sleep',this)">sleep</button>
  </div>
  <div class="note" style="margin-top:4px">
    The two buttons on each row are: the <b>search term</b> (paste it in the search box)
    and the <b>variable name</b> (paste it when Shortcuts asks you to name the result).
  </div>
  <div class="ss-wrap">
    <div class="ss-lbl">After this step</div>
    <div class="ss-screen">
      <div class="ss-nav">
        <span class="ss-back">&#8249; Shortcuts</span>
        <span class="ss-title">Arnie Health</span>
        <span class="ss-run">&#9654;</span>
      </div>
      <div class="ss-body">
        <div class="ss-act hi">
          <div class="ss-hd"><div class="ss-ic r">&#9829;</div><div class="ss-nm">Find Health Samples</div></div>
          <div class="ss-bd"><div class="ss-info">Step Count &middot; Today &middot; Sum &rarr; <span class="ss-pill">steps</span></div></div>
        </div>
        <div class="ss-act hi">
          <div class="ss-hd"><div class="ss-ic r">&#9829;</div><div class="ss-nm">Find Health Samples</div></div>
          <div class="ss-bd"><div class="ss-info">Active Energy Burned &middot; Today &middot; Sum &rarr; <span class="ss-pill">cals</span></div></div>
        </div>
        <div class="ss-act hi">
          <div class="ss-hd"><div class="ss-ic r">&#9829;</div><div class="ss-nm">Find Health Samples</div></div>
          <div class="ss-bd"><div class="ss-info">Basal Energy Burned &middot; Today &middot; Sum &rarr; <span class="ss-pill">rest</span></div></div>
        </div>
        <div class="ss-act hi">
          <div class="ss-hd"><div class="ss-ic r">&#9829;</div><div class="ss-nm">Find Health Samples</div></div>
          <div class="ss-bd"><div class="ss-info">Sleep Analysis &middot; Today &middot; Sum &rarr; <span class="ss-pill">sleep</span></div></div>
        </div>
        <div class="ss-add">+ Add Action</div>
      </div>
    </div>
  </div>
</div>

<!-- ── STEP 3 ── -->
<div class="step">
  <div class="step-hd">
    <div class="snum">3</div>
    <div class="stname">Add a URL action</div>
  </div>
  <p>Tap <b>Add Action</b> &rarr; search <b>URL</b> &rarr; tap the first result called <b>URL</b>.</p>
  <p>Tap the URL field that appears &rarr; copy and paste your personal URL below:</p>
  <div class="crow">
    <div class="cval" id="url-text">{endpoint}</div>
    <button class="cbtn" id="copy-btn" onclick="cp(document.getElementById('url-text').textContent.trim(),this)">Copy</button>
  </div>
  <p style="margin-top:10px">After pasting, add each parameter below. For each one: <b>tap at the end of the URL</b> &rarr; copy the parameter text &rarr; paste it &rarr; then tap the <b>&#123;x&#125;</b> icon above the keyboard and pick the matching variable name.</p>
  <div class="note" style="margin-top:8px;background:rgba(245,158,11,.06);border-color:rgba(245,158,11,.22)">
    <b style="color:#f59e0b">&#9888; Common mistake:</b> After pasting <code style="font-size:12px;color:#f59e0b">&amp;steps=</code>, you <b>must tap &#123;x&#125; and select the variable</b> from the list — do <b>not</b> type the name by hand. Typing it sends the literal word "steps" instead of your step count and the sync will fail.
  </div>

  <div class="crow" style="margin-top:4px">
    <div class="cval">&amp;steps=</div>
    <button class="cbtn" onclick="cp('&steps=',this)">Copy</button>
  </div>
  <div class="crow">
    <div class="cval">&amp;active_calories=</div>
    <button class="cbtn" onclick="cp('&active_calories=',this)">Copy</button>
  </div>
  <div class="crow">
    <div class="cval">&amp;resting_calories=</div>
    <button class="cbtn" onclick="cp('&resting_calories=',this)">Copy</button>
  </div>
  <div class="crow">
    <div class="cval">&amp;sleep_seconds=</div>
    <button class="cbtn" onclick="cp('&sleep_seconds=',this)">Copy</button>
  </div>
  <div class="note grn" style="margin-top:8px">
    Your finished URL will look like this — the <span style="color:#f59e0b">orange parts</span> are your Shortcuts variables:
    <div style="margin-top:8px;background:rgba(0,0,0,.3);border-radius:9px;padding:11px 12px;
      font-family:'SF Mono',monospace;font-size:11px;line-height:1.8;word-break:break-all;
      color:#546070">
      <span style="color:#00e676">{endpoint}</span><span
      style="color:#4a9eff">&amp;steps=</span><span style="color:#f59e0b">steps</span><span
      style="color:#4a9eff">&amp;active_calories=</span><span style="color:#f59e0b">cals</span><span
      style="color:#4a9eff">&amp;resting_calories=</span><span style="color:#f59e0b">rest</span><span
      style="color:#4a9eff">&amp;sleep_seconds=</span><span style="color:#f59e0b">sleep</span>
    </div>
  </div>
  <div class="ss-wrap">
    <div class="ss-lbl">After this step</div>
    <div class="ss-screen">
      <div class="ss-nav">
        <span class="ss-back">&#8249; Shortcuts</span>
        <span class="ss-title">Arnie Health</span>
        <span class="ss-run">&#9654;</span>
      </div>
      <div class="ss-body">
        <div class="ss-act ss-dim">
          <div class="ss-hd"><div class="ss-ic r">&#9829;</div><div class="ss-nm">Find Health Samples &times;4</div></div>
        </div>
        <div class="ss-act hi">
          <div class="ss-hd"><div class="ss-ic b">&#128279;</div><div class="ss-nm">URL</div></div>
          <div class="ss-bd">
            <div class="ss-info" style="word-break:break-all">
              &hellip;&amp;steps=<span class="ss-pill">steps</span>&amp;active_calories=<span class="ss-pill">cals</span>&amp;resting_calories=<span class="ss-pill">rest</span>&amp;sleep_seconds=<span class="ss-pill">sleep</span>
            </div>
          </div>
        </div>
        <div class="ss-add">+ Add Action</div>
      </div>
    </div>
  </div>
</div>

<!-- ── STEP 4 ── -->
<div class="step">
  <div class="step-hd">
    <div class="snum">4</div>
    <div class="stname">Send it to Arnie</div>
  </div>
  <p>Tap <b>Add Action</b> &rarr; search <b>Get Contents of URL</b> &rarr; tap it. That's it — no extra settings needed. It automatically uses the URL you built in Step 3.</p>
  <p>Tap <b>▷</b> (play) at the bottom of your shortcut to test it. If it works, the green banner at the top of this page will update within a few seconds, and you'll get a confirmation in Telegram.</p>
  <div class="ss-wrap">
    <div class="ss-lbl">Completed shortcut</div>
    <div class="ss-screen">
      <div class="ss-nav">
        <span class="ss-back">&#8249; Shortcuts</span>
        <span class="ss-title">Arnie Health</span>
        <span class="ss-run">&#9654;</span>
      </div>
      <div class="ss-body">
        <div class="ss-act ss-dim">
          <div class="ss-hd"><div class="ss-ic r">&#9829;</div><div class="ss-nm">Find Health Samples &times;4</div></div>
        </div>
        <div class="ss-act ss-dim">
          <div class="ss-hd"><div class="ss-ic b">&#128279;</div><div class="ss-nm">URL</div></div>
          <div class="ss-bd"><div class="ss-info"><span class="ss-pill">steps</span> <span class="ss-pill">cals</span> <span class="ss-pill">rest</span> <span class="ss-pill">sleep</span></div></div>
        </div>
        <div class="ss-act hi">
          <div class="ss-hd"><div class="ss-ic t">&#127760;</div><div class="ss-nm">Get Contents of URL</div></div>
          <div class="ss-bd"><div class="ss-info">URL: <span class="ss-pill b">URL</span></div></div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ── STEP 5 ── -->
<div class="step">
  <div class="step-hd">
    <div class="snum">5</div>
    <div class="stname">Run it automatically every morning</div>
  </div>
  <p>In Shortcuts, tap <b>Automation</b> at the bottom &rarr; tap <b>+</b> &rarr; tap <b>Time of Day</b>.</p>
  <p>Set the time to <b>8:00 AM</b> (or whenever you wake up), set Repeat to <b>Daily</b>, then tap <b>Next</b> and choose <b>Arnie Health</b>.</p>
  <p>Tap <b>Done</b>. Then tap the new automation in the list and <b>turn off "Ask Before Running"</b> — this makes it run silently every morning without interrupting you.</p>
  <div class="note grn">
    <b>All done.</b> From tomorrow morning it runs automatically.
    Your steps, calories, and sleep will appear in your Arnie dashboard every day.
  </div>
  <div class="ss-wrap">
    <div class="ss-lbl">Your automation</div>
    <div class="ss-screen">
      <div class="ss-nav">
        <span class="ss-back">&#8249; Automation</span>
        <span class="ss-title">Personal</span>
        <span class="ss-run" style="font-size:20px">+</span>
      </div>
      <div class="ss-body">
        <div class="ss-act hi-grn">
          <div class="ss-hd">
            <div class="ss-ic a">&#9200;</div>
            <div>
              <div class="ss-nm">Time of Day &middot; 8:00 AM</div>
              <div class="ss-info">Every Day &middot; Runs automatically</div>
            </div>
          </div>
          <div class="ss-bd">
            <div class="ss-info" style="color:#30d158;font-weight:600">&#9654; Arnie Health</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<hr>
<footer>Arnie &middot; Apple Health · iOS Shortcuts</footer>

</main>

<script>
function cp(text, btn) {{
  navigator.clipboard.writeText(text).then(function() {{
    var old = btn.textContent;
    btn.textContent = '✓';
    btn.classList.add('ok');
    setTimeout(function() {{ btn.textContent = old; btn.classList.remove('ok'); }}, 1600);
  }}).catch(function() {{
    /* fallback: select the nearest monospace text */
    var row = btn.closest('.crow,.mrow');
    if (!row) return;
    var el = row.querySelector('.cval,.mvar');
    if (!el) return;
    var r = document.createRange();
    r.selectNodeContents(el);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(r);
  }});
}}

{status_script}
</script>
</body>
</html>"""
