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


def _dashboard_html(token: str, name: str = "", bot_username: str = "Arnie_1026_Bot") -> str:
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
.hbtn{{
  background:var(--sf2);border:1px solid var(--bd);color:var(--mu);
  width:34px;height:34px;border-radius:10px;cursor:pointer;font-size:14px;
  display:flex;align-items:center;justify-content:center;font-family:inherit;
  transition:all .2s;flex-shrink:0;
}}
.hbtn:hover{{border-color:var(--ac);color:var(--ac)}}
.hbtn:active{{transform:scale(.91)}}
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
  color:var(--mu);cursor:pointer;padding:6px 0 2px;transition:color .15s;
}}
.bn-ico{{width:24px;height:24px;display:grid;place-items:center}}
.bn-item.active{{color:var(--ac)}}

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
.ins-body{{max-height:0;overflow:hidden;transition:max-height .3s cubic-bezier(.4,0,.2,1)}}
.insights.open .ins-body{{max-height:1600px;margin-top:8px}}

/* ── WEARABLE ────────────────────────────────────────────── */
.htile{{
  background:var(--sf);border:1px solid var(--bd);border-radius:12px;
  padding:10px 8px;text-align:center;backdrop-filter:blur(12px);
  box-shadow:var(--sh);transition:background .3s;
}}
.hv{{font-family:'Instrument Serif','Times New Roman',serif;font-size:18px;font-weight:normal;line-height:1;letter-spacing:-.01em}}
.hl{{font-family:'Geist Mono','SF Mono',monospace;font-size:9px;color:var(--mu);text-transform:uppercase;letter-spacing:.08em;margin-top:3px;font-weight:500}}

/* ── LOG CARDS ───────────────────────────────────────────── */
.lcrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
.lrow{{
  display:flex;align-items:flex-start;gap:12px;
  padding:12px 16px;border-bottom:1px solid var(--bd);position:relative;
}}
.lrow:last-child{{border-bottom:none}}
.lrow:hover{{background:var(--sf2)}}
.ficon{{
  width:36px;height:36px;border-radius:10px;flex-shrink:0;
  background:var(--sf2);border:1px solid var(--bd);
  display:grid;place-items:center;font-size:19px;margin-top:1px;
}}
.fbody{{flex:1;min-width:0;padding-right:58px}}
.lname{{
  font-size:15px;font-weight:500;line-height:1.3;word-break:break-word;
  color:var(--tx);display:flex;align-items:center;gap:7px;flex-wrap:wrap;
}}
.est-tag{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:8.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--mu);background:var(--sf2);border:1px solid var(--bd);
  border-radius:5px;padding:2px 6px;flex-shrink:0;font-weight:500;
}}
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

/* ── DEVICE CARDS ────────────────────────────────────────── */
.dev-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px}}
.dev-card{{
  display:flex;align-items:center;gap:11px;padding:13px;
  border-radius:12px;border:1px solid var(--bd);background:var(--sf);
  transition:all .2s;
}}
.dev-card:hover{{border-color:var(--bd2);background:var(--sf2)}}
.dev-card.dev-soon{{opacity:.6}}
.dev-logo{{
  width:40px;height:40px;border-radius:10px;flex-shrink:0;
  background:var(--sf2);border:1px solid var(--bd);
  display:grid;place-items:center;font-size:18px;
}}
.dev-body{{min-width:0}}
.dev-name{{font-size:13px;font-weight:500;color:var(--tx)}}
.dev-status{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--mu);margin-top:3px;display:inline-flex;align-items:center;gap:5px;
}}
.dev-status.dev-live{{color:var(--ac)}}
.dev-dot{{
  width:6px;height:6px;border-radius:50%;
  background:currentColor;box-shadow:0 0 6px currentColor;flex-shrink:0;
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
}}
@media(max-width:940px){{.ph-title{{font-size:26px}}}}
@media(max-width:560px){{.ph-title{{font-size:24px}}}}
.ph-sub{{
  font-size:12px;color:var(--tx2);margin-top:7px;
  letter-spacing:.01em;
  display:flex;align-items:center;gap:10px;
}}
.ph-streak{{color:var(--ac);display:inline-flex;align-items:center;gap:5px;font-weight:500}}
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
  /* Pagehead: hide icon-only buttons, keep just the Chat button */
  .pagehead .hbtn{{display:none}}
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
  /* Today counters — quiet label, clear weighted number, even bars */
  .macro-cell{{padding:10px 12px}}
  .mc-label{{font-size:9px;letter-spacing:.08em;margin-bottom:4px;color:var(--mu);font-weight:500}}
  .mc-num{{font-size:26px;line-height:1.1}}
  .mc-sub{{font-size:10px;margin-top:3px;color:var(--mu)}}
  .mc-bar{{margin-top:6px;height:3px}}
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
  /* Food */
  .ficon{{width:38px;height:38px;font-size:20px;border-radius:10px}}
  .lname{{font-size:15px}}
  .lqty{{font-size:13px}}
  .lmac{{font-size:12px}}
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
  .dev-grid{{grid-template-columns:1fr;gap:8px}}
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
.trend-strip{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:4px}}
.tcell{{background:var(--sf2);border:1px solid var(--bd);border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;gap:2px}}
.tc-lbl{{font-size:9px;letter-spacing:.06em;text-transform:uppercase;color:var(--mu);font-weight:500}}
.tc-val{{font-size:16px;font-weight:600;color:var(--tx2);line-height:1.1}}
.tc-sub{{font-size:10px;color:var(--mu);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
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
        <span class="ni-lbl">Day</span><span class="ni-meta">Today</span>
      </button>
      <button class="navitem" id="nav-week" onclick="switchTab('week')">
        <span class="ni-ico"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 16l5-5 4 4 8-9"/><path d="M16 6h5v5"/><path d="M3 21h18" opacity=".4"/></svg></span>
        <span class="ni-lbl">Week</span><span class="ni-meta">Trends</span>
      </button>
      <button class="navitem" id="nav-profile" onclick="switchTab('profile')">
        <span class="ni-ico"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.2 4-6.5 8-6.5s8 2.3 8 6.5"/></svg></span>
        <span class="ni-lbl">Profile</span><span class="ni-meta">You</span>
      </button>
      <button class="navitem" id="nav-coaching" onclick="switchTab('coaching')">
        <span class="ni-ico"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3C7 3 3 6.6 3 11c0 2.4 1.1 4.5 2.9 6L5 21l4.3-1.4A9.6 9.6 0 0 0 12 20c5 0 9-3.6 9-8s-4-9-9-9Z"/><path d="M9 11h.01M12 11h.01M15 11h.01" stroke-width="2.2" stroke-linecap="round"/></svg></span>
        <span class="ni-lbl">Coaching</span><span class="ni-meta">Settings</span>
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
    <button class="ph-log-btn" id="chat-btn" onclick="toggleChatWidget()"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15.5a2.5 2.5 0 0 1-2.5 2.5H7.8L3 22V5.5A2.5 2.5 0 0 1 5.5 3h13A2.5 2.5 0 0 1 21 5.5z"/></svg>Chat</button>
    <button class="hbtn" id="theme-btn" onclick="toggleTheme()" title="Toggle theme">&#9790;</button>
    <button class="hbtn" onclick="refreshCurrent()" title="Refresh">&#8635;</button>
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

    <!-- ARNIE'S LEARNING — shown only for new users, hides at 100% -->
    <div id="learn-wrap" style="display:none;margin-top:12px">
      <div class="lrn-card">
        <div class="lrn-top">
          <span class="lrn-label">Still learning</span>
          <div class="learn-bar"><div class="learn-fill" id="learn-fill" style="width:0%"></div></div>
          <span id="learn-pct" class="lrn-pct"></span>
        </div>
        <div class="learn-chips" id="learn-list"></div>
      </div>
    </div>

    <!-- MACRO STRIP -->
    <div class="macro-strip" style="margin-top:16px">
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

    <!-- STATUS (workout / cardio / water) — pills only shown when logged -->
    <div class="day-status">
      <span id="wo-badge" class="ds-pill on" style="display:none"></span>
      <span id="ca-badge" class="ds-pill on" style="display:none"></span>
      <span id="wt-badge" class="ds-pill on" style="display:none"></span>
      <button class="ds-share" onclick="shareDay()" aria-label="Share day" style="display:none">&#8679;</button>
    </div>

    <!-- AI INSIGHTS — collapsed banner, expands on tap -->
    <div class="insights" id="ins-day" style="margin-top:12px">
      <div class="ins-banner" onclick="toggleInsights('day')" role="button" tabindex="0" aria-expanded="false">
        <span class="ins-spark"><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2.2l1.7 4.8 4.8 1.7-4.8 1.7L12 15.2l-1.7-4.8L5.5 8.7l4.8-1.7z"/><path d="M18.6 13.4l.82 2.18 2.18.82-2.18.82-.82 2.18-.82-2.18L15.6 16.4l2.18-.82z"/></svg></span>
        <div class="ins-head"><span class="ins-title">Coach Insights</span><div class="ins-preview" id="ins-preview-day"></div></div>
        <span class="ins-time" id="ins-time-day"></span>
        <span class="ins-actions">
          <span class="ins-refresh" onclick="event.stopPropagation();refreshInsights()" title="Refresh">&#8635;</span>
          <span class="ins-chev">&#9662;</span>
        </span>
      </div>
      <div class="ins-body"><div class="icrd fade-in" id="insights-card"><div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div></div></div>
    </div>

    <!-- 5-DAY TREND -->
    <div id="trend-wrap" style="display:none;margin-top:16px">
      <div class="stitle" style="margin-bottom:8px">5-day trend <span id="trend-days-lbl" style="font-weight:400;opacity:.55;font-size:9px;letter-spacing:.04em"></span></div>
      <div class="trend-strip" id="trend-strip"></div>
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

    <!-- WHOOP RECOVERY — bottom of day, only when connected -->
    <div id="whoop-module" style="display:none">
      <div class="stitle spaced">
        <span style="display:inline-flex;align-items:center"><span id="health-brand" style="display:inline-flex;margin-right:7px"></span><span id="health-mod-title">Whoop</span> <span id="whoop-date" style="font-family:'Geist Mono','SF Mono',monospace;font-weight:400;opacity:.6;font-size:9px;letter-spacing:.04em;margin-left:6px"></span></span>
        <button class="add-toggle" id="whoop-sync-btn" onclick="syncWhoop()" title="Sync" style="font-size:15px;font-family:inherit">&#8635;</button>
      </div>
      <div id="whoop-grid"></div>
    </div>

  </div><!-- /panel-day -->

  <!-- WEEK TAB -->
  <div class="tab-panel" id="panel-week">

    <!-- Weekly AI analysis — collapsed banner, expands on tap -->
    <div class="insights" id="ins-week" style="margin-top:4px">
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

    <div class="stitle" style="margin-top:20px">Trends</div>
    <div class="c2col">
      <div class="ccrd">
        <div class="ctitle"><span>Calories &middot; 30 days</span><span id="cal-avg-lbl" class="ctitle-val" style="color:var(--ac)"></span></div>
        <div class="cwrap"><canvas id="calChart"></canvas></div>
      </div>
      <div class="ccrd">
        <div class="ctitle"><span>Protein &middot; 30 days</span><span id="pro-tgt-lbl" class="ctitle-val" style="color:var(--bl)"></span></div>
        <div class="cwrap"><canvas id="proChart"></canvas></div>
      </div>
    </div>
    <div class="ccrd" style="margin-top:14px">
      <div class="ctitle"><span>Weight trend &middot; 30 days</span><span id="wt-now-lbl" class="ctitle-val" style="color:var(--pu)"></span></div>
      <div class="cwrap"><canvas id="weightChart"></canvas></div>
    </div>
    <div class="stitle">Goal progress</div>
    <div class="goal-card" id="goal-card"></div>
    <div class="stitle">Stats</div>
    <div class="stat-row">
      <div class="stat-tile"><div class="stat-num" id="stat-streak">—</div><div class="stat-lbl">Day streak</div></div>
      <div class="stat-tile"><div class="stat-num" id="stat-workouts">—</div><div class="stat-lbl">Workouts / 30d</div></div>
      <div class="stat-tile"><div class="stat-num" id="stat-avg-cal">—</div><div class="stat-lbl">Avg cal / day</div></div>
    </div>
  </div>

  <!-- PROFILE TAB -->
  <div class="tab-panel" id="panel-profile">

    <!-- AI Profile — bio + learned attributes -->
    <div id="ai-profile-section" style="display:none">
      <div class="stitle spaced" style="margin-top:4px;cursor:pointer" onclick="toggleBio()">
        <span>Arnie's profile <span class="ai-pill">AI</span> <span id="bio-chevron" style="font-size:11px;opacity:.5">▼</span></span>
        <button class="add-toggle" onclick="event.stopPropagation();refreshAIProfile()" title="Refresh">&#8635;</button>
      </div>
      <!-- Bio card — collapsed by default -->
      <div class="infocrd" id="ai-bio-card" style="padding:14px 16px;line-height:1.6;font-size:14px;color:var(--tx);display:none"></div>
      <!-- Basics: compact demographic grid -->
      <div id="ai-basics" class="basics-grid"></div>
      <!-- Declared + learned facts, merged by category -->
      <div id="ai-attributes-section"></div>
    </div>
    <div id="ai-profile-loading" style="padding:24px 16px;text-align:center;color:var(--mu);font-size:13px">Building your profile&#8230;</div>
    <div id="ai-profile-empty" style="display:none;padding:16px 0">
      <div class="lempty">Keep logging and chatting — Arnie builds your profile from your interactions. Check back after a few days.</div>
    </div>

    <!-- Training program — sits with the fitness content; full structured split
         lives in WorkoutProgram, a summary mirrors into the Fitness attributes -->
    <div class="stitle spaced" style="margin-top:24px">
      <span>Training program</span>
      <button class="add-toggle" id="wp-edit-btn" onclick="openWorkoutEditor()" title="Set up / edit">+</button>
    </div>
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

    <div class="stitle" style="margin-top:16px">Connected devices</div>
    <div class="infocrd" style="overflow:hidden" id="devices-card"></div>
  </div>

  <!-- COACHING TAB -->
  <div class="tab-panel" id="panel-coaching">
    <div class="stitle" style="margin-top:4px">Reminders</div>
    <div class="pref-card" id="remind-card">
      <div class="pref-row">
        <span class="pref-lbl">Daily check-ins</span>
        <label class="pref-toggle">
          <input type="checkbox" id="remind-toggle" onchange="saveRemindOn(this.checked)">
          <span class="pref-slider"></span>
        </label>
      </div>
      <div id="remind-freq-wrap" style="margin-top:12px">
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
    </div>

    <div class="stitle" style="margin-top:16px">Food logging</div>
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

    <div class="stitle" style="margin-top:16px">Coaching style</div>
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
  </div>

<footer>Arnie &middot; auto-refresh 5 min</footer>
</div><!-- /main-inner -->
</div><!-- /main -->

<nav class="bottomnav">
  <button class="bn-item active" id="bn-day" onclick="switchTab('day')">
    <span class="bn-ico"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4.5" width="18" height="16.5" rx="3"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><circle cx="12" cy="15" r="1.8" fill="currentColor" stroke="none"/></svg></span>Day
  </button>
  <button class="bn-item" id="bn-week" onclick="switchTab('week')">
    <span class="bn-ico"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 16l5-5 4 4 8-9"/><path d="M16 6h5v5"/></svg></span>Week
  </button>
  <button class="bn-item" id="bn-profile" onclick="switchTab('profile')">
    <span class="bn-ico"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.2 4-6.5 8-6.5s8 2.3 8 6.5"/></svg></span>Profile
  </button>
  <button class="bn-item" id="bn-coaching" onclick="switchTab('coaching')">
    <span class="bn-ico"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3C7 3 3 6.6 3 11c0 2.4 1.1 4.5 2.9 6L5 21l4.3-1.4A9.6 9.6 0 0 0 12 20c5 0 9-3.6 9-8s-4-9-9-9Z"/><path d="M9 11h.01M12 11h.01M15 11h.01" stroke-width="2.2" stroke-linecap="round"/></svg></span>Coaching
  </button>
</nav>

</div><!-- /shell -->

<script>
// ── Constants ─────────────────────────────────────────────────────────────
const TOKEN        = '{token}';
const STATS_BASE   = '/api/stats/'    + TOKEN;
const INSIGHTS_API = '/api/insights/' + TOKEN;
const PROFILE_API  = '/api/profile/'  + TOKEN;

// ── State ─────────────────────────────────────────────────────────────────
let _baseData=null, _dayCache={{}}, _viewingDate=null, _todayStr=null;
let _availDates=[], _activeTab='day', calChart, proChart, weightChart;

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
  week:{{title:'Your trends',sub:'LAST 30 DAYS'}},
  profile:{{title:'Your profile',sub:'ACCOUNT &amp; SETTINGS'}},
  coaching:{{title:'Coaching',sub:'PREFERENCES &amp; REMINDERS'}},
}};
function renderCoachingTab(d) {{
  var p = (d && d.profile) || {{}};
  renderRemindSettings(p);
  renderFoodModeSettings(p);
  renderCoachingStyleSettings(p);
}}
function switchTab(name){{
  _activeTab=name;
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
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
  if(name==='coaching' && _baseData){{renderCoachingTab(_baseData);}}
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
    if(sg)sg.textContent=(gl?gl.toUpperCase():'')+(wt?' · '+wt+' LB':'');
    if(su&&nm)su.style.display='flex';
    document.getElementById('app-load').style.display='none';
    renderDateNav();
    renderDayTab(data);
    loadInsights();
    initLogSections();
  }}catch(e){{
    document.getElementById('app-load').textContent='Failed to load — tap ↻ to retry.';
  }}
}}

async function refreshCurrent(){{
  delete _dayCache[_viewingDate];
  if(_viewingDate===_todayStr){{
    try{{
      var data=await fetchStats(null);
      _baseData=data;_dayCache[_todayStr]=data;
      renderDayTab(data);
      if(_activeTab==='week') renderWeekTab(data);
      if(_activeTab==='profile') renderProfileTab(data);
    }}catch(e){{}}
  }}else{{
    await loadDayData(_viewingDate);
  }}
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
// A small checklist + bar that shows users Arnie sharpens as they feed it more.
// Each item is a dimension Arnie learns about them; uses only the stats payload
// (zero backend). Hides entirely once all dimensions are learned (100%).
function renderLearningProgress(d){{
  var wrap=document.getElementById('learn-wrap');
  if(!wrap)return;
  var p=d.profile||{{}}, tgt=d.targets||{{}};
  var hist=d.history||[], weights=d.weights||[];
  var loggedDays=hist.filter(function(h){{return (h.calories||0)>0;}}).length;
  var workoutDays=hist.filter(function(h){{return h.workout;}}).length;
  var items=[
    {{label:'Goals',    done:!!(p.primary_goal && tgt.calories && tgt.protein)}},
    {{label:'Eating',   done:loggedDays>=3}},
    {{label:'Weight',   done:weights.length>=3}},
    {{label:'Training', done:workoutDays>=1}},
    {{label:'Recovery', done:!!(p.whoop_connected||p.apple_health_connected)}},
  ];
  var done=items.filter(function(i){{return i.done;}}).length;
  // Once Arnie has learned every dimension, the indicator has served its purpose —
  // hide it so the day view stays clean for dialed-in users.
  if(done>=items.length){{wrap.style.display='none';return;}}
  var pctv=Math.round(done/items.length*100);
  var fill=document.getElementById('learn-fill');if(fill)fill.style.width=pctv+'%';
  var lbl=document.getElementById('learn-pct');if(lbl)lbl.textContent=pctv+'%';
  var list=document.getElementById('learn-list');
  if(list)list.innerHTML=items.map(function(it){{
    return '<span class="learn-chip'+(it.done?' done':'')+'">'+esc(it.label)+'</span>';
  }}).join('');
  wrap.style.display='block';
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
  var wrap=document.getElementById('remind-freq-wrap');
  if(wrap)wrap.style.opacity=(on&&!blocked)?'1':'.4';
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
  var wrap=document.getElementById('remind-freq-wrap');
  if(wrap)wrap.style.opacity=checked?'1':'.4';
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
  var monthAgo=new Date(today);monthAgo.setDate(monthAgo.getDate()-30);
  var monthStr=_localDate(monthAgo);
  var workouts=history.filter(function(h){{return h.date>=monthStr&&h.workout;}}).length;
  // Past days only — today's totals are still moving. No open/closed state any more.
  var todayStr=_localDate(today);
  var past=history.filter(function(h){{return h.date<todayStr;}});
  var avgCal=past.length?Math.round(past.reduce(function(s,h){{return s+h.calories;}},0)/past.length):null;

  var el=document.getElementById('stat-streak');if(el)el.textContent=streak;
  el=document.getElementById('stat-workouts');if(el)el.textContent=workouts;
  el=document.getElementById('stat-avg-cal');if(el)el.textContent=avgCal?avgCal.toLocaleString():'—';
}}

function renderPageHead(d){{
  var pt=document.getElementById('ph-title');
  var ps=document.getElementById('ph-sub');
  if(!pt||!ps)return;
  var hr=new Date().getHours();
  var g=hr<12?'Good morning':hr<18?'Good afternoon':'Good evening';
  var name=((d.profile&&d.profile.name)||'').trim();
  pt.textContent=name?(g+', '+name):g;
  var now=new Date();
  var ds=now.toLocaleDateString('en-US',{{weekday:'long',month:'long',day:'numeric'}});
  var hist=d.history||[];
  var t0=new Date();t0.setHours(0,0,0,0);
  var logSet=new Set(hist.map(function(h){{return h.date;}}));
  var st=0,ck=new Date(t0);
  while(true){{var ds2=_localDate(ck);if(logSet.has(ds2)){{st++;ck.setDate(ck.getDate()-1);}}else break;}}
  ps.innerHTML='<span style="color:var(--tx);font-weight:500;letter-spacing:.01em">'+esc(ds)+'</span>'+(st>0?' <span class="ph-streak">&#9889; '+st+'-day streak</span>':'');
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

function renderDayTab(d){{
  if(_activeTab==='day') renderPageHead(d);
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

  var wb=document.getElementById('wo-badge');
  if(wb){{var woOn=!!day.workout_completed;wb.style.display=woOn?'':'none';if(woOn){{wb.className='ds-pill on';wb.innerHTML='<span class="tcb">&#10003;</span>Workout';}}}}
  var cb=document.getElementById('ca-badge');
  if(cb){{var caOn=!!day.cardio_completed;cb.style.display=caOn?'':'none';if(caOn){{cb.className='ds-pill on';cb.innerHTML='<span class="tcb">&#10003;</span>Cardio';}}}}
  var wb2=document.getElementById('wt-badge');
  if(wb2){{
    // Water is opt-in — only show the pill when the user actually logs it, so it's
    // never a permanent "No water" guilt-chip for people who don't track it.
    if(day.water_ml>0){{
      var wAmt=day.water_ml>=1000?(day.water_ml/1000).toFixed(1)+'L':Math.round(day.water_ml)+'ml';
      wb2.style.display='inline-flex';
      wb2.className='ds-pill on';
      wb2.innerHTML='<span class="tcb">&#10003;</span>Water '+wAmt;
    }}else{{
      wb2.style.display='none';
    }}
  }}

  var fe=day.food_entries||[];
  var flc=document.getElementById('food-log-count');
  if(flc)flc.textContent=fe.length?fe.length+' item'+(fe.length!==1?'s':''):'';
  document.getElementById('food-log').innerHTML=fe.length?fe.map(renderFoodRow).join('')
    :'<div class="lempty">'+(isToday?'Nothing logged yet — tap + to add a meal.':'Nothing logged this day.')+'</div>';
  var ee=day.exercise_entries||[];
  document.getElementById('ex-log').innerHTML=ee.length?renderGroupedExercises(ee)
    :'<div class="lempty">'+(isToday?'No workouts logged yet — tap + to add one.':'No workouts logged this day.')+'</div>';

  // Whoop module
  var health=d.health||[];
  var snap=health.find(function(h){{return h.date===_viewingDate;}}) || (health.length?health[0]:null);
  renderWhoopModule(snap, d.profile);

  // Arnie's learning progress + 5-day trend — both use only the stats payload
  renderLearningProgress(d);
  renderTrendStrip(d.history||[], d.weights||[], d.targets||{{}});
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

// ── Whoop stats module ────────────────────────────────────────────────────
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

  // Short-value metrics → 3-up compact cells
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
  var activity=grid3(
    hcell('Steps',snap.steps!=null?snap.steps.toLocaleString():null)+
    hcell('Active cal',snap.active_calories!=null?Math.round(snap.active_calories)+'':null,'var(--or)')+
    hcell('Resting cal',snap.resting_calories!=null?Math.round(snap.resting_calories)+'':null));
  var sleep=grid3(hcell('Sleep',fmtSleep(snap.sleep_hours),'var(--bl)'));

  grid.innerHTML=
    (hsec('ah-activity','Activity',snap.steps!=null?snap.steps.toLocaleString():'',activity,!wIsMobile())+
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
function renderWeekTab(d){{
  var dk=document.documentElement.getAttribute('data-theme')!=='light';
  var hist=(d.history||[]).slice(-30),tgt=d.targets||{{}};
  var labels=hist.map(h=>h.date.slice(5));
  var calD=hist.map(h=>h.calories??0),proD=hist.map(h=>h.protein??0);
  // Dynamic chart header values
  var loggedCal=hist.filter(h=>h.calories>0);
  var avgCal=loggedCal.length?Math.round(loggedCal.reduce((s,h)=>s+h.calories,0)/loggedCal.length):null;
  var wEl=document.getElementById('cal-avg-lbl');if(wEl)wEl.textContent=avgCal?'AVG '+avgCal.toLocaleString():'';
  var pEl=document.getElementById('pro-tgt-lbl');if(pEl)pEl.textContent=tgt.protein?'TARGET '+tgt.protein+'G':'';
  var weights=d.weights||[];
  var curW=weights.length?weights[weights.length-1].lbs:null;
  var wEl2=document.getElementById('wt-now-lbl');if(wEl2)wEl2.textContent=curW?curW+' LB NOW':'';
  var tick=dk?'#4a5568':'#94a3b8',grid=dk?'rgba(255,255,255,.05)':'#e2e8f0';
  var opts={{
    responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{grid:{{display:false}},ticks:{{color:tick,font:{{size:9}},maxRotation:0,autoSkip:true,maxTicksLimit:8}}}},
      y:{{grid:{{color:grid}},ticks:{{color:tick,font:{{size:10}}}},beginAtZero:true}}
    }}
  }};

  if(calChart) calChart.destroy();
  calChart=new Chart(document.getElementById('calChart'),{{
    type:'bar',
    data:{{
      labels,
      datasets:[
        {{
          data:calD,
          backgroundColor:calD.map(v=>tgt.calories&&v>tgt.calories
            ?(dk?'rgba(239,68,68,.7)':'rgba(220,38,38,.7)')
            :(dk?'rgba(0,230,118,.65)':'rgba(5,150,105,.65)')),
          borderRadius:4,
        }},
        ...(tgt.calories?[{{
          type:'line',data:Array(labels.length).fill(tgt.calories),
          borderColor:dk?'rgba(255,255,255,.25)':'rgba(0,0,0,.2)',
          borderDash:[4,4],borderWidth:1.5,pointRadius:0,fill:false,
        }}]:[])
      ]
    }},
    options:opts,
  }});

  if(proChart) proChart.destroy();
  proChart=new Chart(document.getElementById('proChart'),{{
    type:'bar',
    data:{{
      labels,
      datasets:[
        {{
          data:proD,
          backgroundColor:proD.map(v=>tgt.protein&&v>=tgt.protein
            ?(dk?'rgba(59,130,246,.85)':'rgba(37,99,235,.85)')
            :(dk?'rgba(59,130,246,.3)':'rgba(37,99,235,.3)')),
          borderRadius:4,
        }},
        ...(tgt.protein?[{{
          type:'line',data:Array(labels.length).fill(tgt.protein),
          borderColor:dk?'rgba(255,255,255,.25)':'rgba(0,0,0,.2)',
          borderDash:[4,4],borderWidth:1.5,pointRadius:0,fill:false,
        }}]:[])
      ]
    }},
    options:opts,
  }});

  if(weightChart) weightChart.destroy();
  var wD=(d.weights||[]).slice(-30);
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
  renderStreakStats(d.history||[], d.targets||{{}});
}}

// ── Profile tab ───────────────────────────────────────────────────────────
var _PEDIT={{
  'Name':'name','Age':'age',
  'Current weight':'current_weight_lbs','Goal weight':'goal_weight_lbs',
  'Goal':'primary_goal','Experience':'training_experience',
  'Diet':'dietary_preferences','Injuries':'injuries',
  'Timezone':'timezone','Coaching style':'coaching_style',
}};
var _TEDIT={{'Calorie target':'calorie_target','Protein target':'protein_target'}};

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

  var dc=document.getElementById('devices-card');
  if(!dc) return;
  var devs=[
    {{name:'Apple Health',icon:'♥',live:p.apple_health_connected,label:p.apple_health_connected?'Syncing':'Not connected'}},
    {{name:'Whoop',icon:'〰',live:p.whoop_connected,label:p.whoop_connected?'Connected':'Run /connect whoop in Telegram to link'}},
    {{name:'Fitbit',icon:'⊕',live:false,label:'Coming soon',soon:true}},
    {{name:'Hume',icon:'◉',live:false,label:'Coming soon',soon:true}},
  ];
  dc.innerHTML=
    '<div class="dev-grid">'+devs.map(function(d){{
      return '<div class="dev-card'+(d.soon?' dev-soon':'')+'">'+
        '<div class="dev-logo">'+d.icon+'</div>'+
        '<div class="dev-body">'+
        '<div class="dev-name">'+esc(d.name)+'</div>'+
        '<div class="dev-status'+(d.live?' dev-live':'')+'">'+
        (d.live?'<span class="dev-dot"></span>':'')+esc(d.label)+
        '</div></div></div>';
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

  var basics = (data && data.basics) || [];
  var hasStd = !!(data && data.standard && Object.keys(data.standard).length);
  if (!data || (!data.bio && !basics.length && !hasStd)) {{
    if (emptyEl) emptyEl.style.display = 'block';
    return;
  }}

  if (section) section.style.display = 'block';
  if (emptyEl) emptyEl.style.display = 'none';

  // Bio
  var bioEl = document.getElementById('ai-bio-card');
  if (bioEl) {{
    if (data.bio) {{
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

  // Basics — compact demographic grid
  var basicsEl = document.getElementById('ai-basics');
  if (basicsEl) {{
    basicsEl.innerHTML = basics.map(function(b) {{
      var id = 'pb-' + _pslug(b.label);
      var edit = b.edit_field
        ? '<button class="basic-edit" onclick="editBasic(\\''+id+'\\',\\''+escA(b.edit_field)+'\\',\\''+escA(b.raw)+'\\',\\''+escA(b.label)+'\\')">&#9998;</button>'
        : '';
      return '<div class="basic-cell" id="'+id+'">' +
        '<div class="basic-lbl">'+esc(b.label)+'</div>' +
        '<div class="basic-val">'+esc(b.value)+'</div>' + edit +
        '</div>';
    }}).join('');
  }}

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
    return '<div style="margin-top:20px"><div class="stitle" style="margin-top:0">' + esc(label) + '</div>' +
      '<div class="infocrd">' + visible + extraHtml + learn + '</div></div>';
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
    // Empty standard slots collapse into one compact "still learning" footer.
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

// Inline edit for a Basics grid cell.
function editBasic(cellId, field, raw, label) {{
  var cell = document.getElementById(cellId); if (!cell) return;
  cell.innerHTML = '<div class="basic-lbl">'+esc(label)+'</div>' +
    '<div style="display:flex;gap:4px;align-items:center;margin-top:1px">' +
    '<input type="text" id="bi-'+cellId+'" value="'+escA(raw)+'" ' +
    'style="flex:1;min-width:0;background:var(--inp);border:1px solid var(--ac);color:var(--tx);padding:4px 7px;border-radius:7px;font-size:13px;font-family:inherit;outline:none">' +
    '<button class="sbtn" style="flex:none;padding:4px 9px;font-size:11px;min-height:0" onclick="saveBasic(\\''+cellId+'\\',\\''+escA(field)+'\\')">&#10003;</button>' +
    '<button class="cbtn" style="flex:none;padding:4px 7px;font-size:11px;min-height:0" onclick="reloadAIProfile()">&#10005;</button>' +
    '</div>';
  var inp = document.getElementById('bi-'+cellId);
  if (inp) {{ inp.focus(); inp.select(); }}
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
  var ch=document.getElementById('bio-chevron');
  if(!el)return;
  var open=el.style.display==='none'||!el.style.display;
  el.style.display=open?'block':'none';
  if(ch)ch.textContent=open?'▲':'▼';
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
function renderFoodRow(f){{
  var est=f.estimated?' <span class="est-tag">est</span>':'';
  var cal=(f.calories??0);
  var macroLine=
    '<span class="fm-val fm-cal">'+cal+'</span><span class="fm-label">&nbsp;cal</span>'+
    '<span class="fm-sep">·</span>'+
    '<span class="fm-label">P&nbsp;</span><span class="fm-val fm-pro">'+(f.protein??0)+'g</span>'+
    '<span class="fm-sep">·</span>'+
    '<span class="fm-label">C&nbsp;</span><span class="fm-val fm-carb">'+(f.carbs??0)+'g</span>'+
    '<span class="fm-sep">·</span>'+
    '<span class="fm-label">F&nbsp;</span><span class="fm-val fm-fat">'+(f.fats??0)+'g</span>';

  return '<div class="eg-row" id="food-row-'+f.id+'" onclick="this.classList.toggle(&quot;open&quot;)">'+
    '<div class="eg-hd">'+
    '<span class="eg-name">'+esc(f.name)+est+'</span>'+
    '<span class="eg-summary">'+cal+' cal</span>'+
    '<span class="eg-chevron">&#9658;</span>'+
    '</div>'+
    '<div class="eg-sets">'+
    (f.quantity?'<div class="eg-set"><span class="eg-set-num"></span><span style="font-size:12px;color:var(--mu)">'+esc(f.quantity)+'</span></div>':'')+
    '<div class="eg-set">'+
    '<span class="eg-set-num"></span>'+
    '<span class="food-macros">'+macroLine+'</span>'+
    '<button class="ibtn" onclick="event.stopPropagation();editFood('+f.id+')" aria-label="Edit" style="width:24px;height:24px;font-size:11px">&#9998;</button>'+
    '<button class="ibtn del" onclick="event.stopPropagation();deleteFood('+f.id+')" aria-label="Delete" style="width:24px;height:24px;font-size:12px">&#215;</button>'+
    '</div>'+
    '</div>'+
    '</div>';
}}

function renderGroupedExercises(entries){{
  // Group entries by exercise name
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

    // Summary line: sets × reps @ weight or duration
    var summaryParts=[];
    var allReps=items.map(function(e){{return e.reps;}}).filter(Boolean);
    var allWts=items.map(function(e){{return e.weight;}}).filter(Boolean);
    var allDur=items.map(function(e){{return e.duration_minutes;}}).filter(Boolean);
    if(allDur.length){{
      summaryParts.push(allDur.reduce(function(a,b){{return a+b;}},0)+' min');
    }}else if(totalSets>0){{
      var repStr=allReps.length===totalSets&&new Set(allReps).size===1?allReps[0]:allReps.join('/');
      // Show every load when sets differ (135/145/155lb), one when they're equal.
      var sameWt=new Set(allWts).size<=1;
      var wtStr=allWts.length?(sameWt?allWts[0]+'lb':allWts.map(Math.round).join('/')+'lb'):'';
      summaryParts.push(totalSets+(repStr?' × '+repStr:'')+(wtStr?' @ '+wtStr:''));
    }}
    var summary=summaryParts.join(' · ');

    // Individual set lines
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

    var isOpen=false;  // all exercises collapsed by default — tap to expand sets
    return '<div class="eg-row'+(isOpen?' open':'')+'" onclick="this.classList.toggle(&quot;open&quot;)">'+
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

function editFood(id){{
  var f=findFood(id);if(!f)return;
  document.getElementById('food-row-'+id).innerHTML=
    '<div class="eform">'+
    '<input type="text" id="ef-n-'+id+'" value="'+escA(f.name)+'" placeholder="Food name">'+
    '<input type="text" id="ef-q-'+id+'" value="'+escA(f.quantity||'')+'" placeholder="Quantity">'+
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
  var lbl=row.querySelector('.inlbl').textContent;
  var _style='flex:1;max-width:170px;background:var(--inp);border:1px solid var(--ac);color:var(--tx);'+
    'padding:5px 8px;border-radius:8px;font-size:12px;font-family:inherit;outline:none';
  var opts=EDIT_OPTIONS[field], editor;
  if(opts){{
    // Picklist for enum fields. Keep any current off-list value selectable.
    var cur=(current||'').toLowerCase(), list=opts.slice();
    if(cur && list.indexOf(cur)===-1) list.unshift(cur);
    editor='<select id="pi-'+rowId+'" style="'+_style+';text-transform:capitalize">'+
      list.map(function(o){{return '<option value="'+escA(o)+'"'+(o===cur?' selected':'')+'>'+esc(o)+'</option>';}}).join('')+
      '</select>';
  }}else{{
    editor='<input type="text" id="pi-'+rowId+'" value="'+escA(current)+'" style="'+_style+'">';
  }}
  row.innerHTML='<span class="inlbl">'+esc(lbl)+'</span>'+
    '<div style="display:flex;align-items:center;gap:5px;flex:1;justify-content:flex-end">'+
    editor+
    '<button class="sbtn" style="flex:none;padding:5px 12px;font-size:12px;min-height:0" '+
    'onclick="saveProw(\\''+rowId+'\\',\\''+escA(field)+'\\')">✓</button>'+
    '<button class="cbtn" style="flex:none;padding:5px 10px;font-size:12px;min-height:0" '+
    'onclick="cancelProw()">✗</button></div>';
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
      var gt=document.getElementById('goal-tag'); if(gt) gt.textContent=data.profile?.primary_goal||'';
    }}
    reloadAIProfile();   // re-render the unified profile so the edited value shows
  }}catch(e){{
    alert('Save failed — try again.');
    if(btn){{btn.disabled=false;btn.textContent='✓';}}
  }}
}}

function cancelProw(){{reloadAIProfile();}}

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
  <a class="cw-tg" href="https://t.me/{bot_username}" target="_blank" rel="noopener">
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
<p class="sub">Use the shortcut below for the quickest setup, or follow the manual steps if preferred.</p>

{f"""
<!-- ONE-TAP SETUP -->
<div class="onetap">
  <div class="ot-badge">Recommended</div>
  <div class="ot-title">3-step setup</div>
  <div class="ot-sub">No variable insertion needed. Copy, download, paste &mdash; done.</div>

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
""" if shortcut_url else ""}

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

{f"""
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
""" if status_url else ""}
</script>
</body>
</html>"""
