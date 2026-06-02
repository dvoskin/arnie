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


def _dashboard_html(token: str, name: str = "") -> str:
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
.main-inner{{padding:0 48px 100px;width:100%;max-width:1100px;margin:0 auto}}
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
.insights-top{{margin-bottom:4px}}
.day-top{{margin-bottom:4px}}
.day-grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}}
.day-col-analytics{{min-width:0;order:1}}
.day-col-log{{min-width:0;order:2}}
@media(max-width:700px){{
  .day-grid{{grid-template-columns:1fr}}
  .day-col-log{{order:1}}
  .day-col-analytics{{order:2}}
}}

/* ── BOTTOM NAV (mobile) ─────────────────────────────────── */
.bottomnav{{
  display:none;position:fixed;bottom:0;left:0;right:0;z-index:60;
  justify-content:space-around;gap:4px;
  padding:10px 16px calc(10px + env(safe-area-inset-bottom));
  background:var(--hbg);backdrop-filter:blur(22px);
  -webkit-backdrop-filter:blur(22px);border-top:1px solid var(--bd);
}}
.bn-item{{
  flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;
  background:transparent;border:none;
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--mu);cursor:pointer;padding:7px 0 4px;border-radius:10px;transition:color .15s;
}}
.bn-ico{{width:23px;height:23px;display:grid;place-items:center;transition:transform .2s}}
.bn-item.active{{color:var(--ac)}}
.bn-item.active .bn-ico{{transform:translateY(-2px)}}

/* ── RESPONSIVE ──────────────────────────────────────────── */
@media(max-width:940px){{
  .shell{{grid-template-columns:1fr}}
  .sidebar{{display:none}}
  .main-inner{{max-width:100%;margin:0}}
  .main-inner{{padding:0 20px 90px;max-width:100%}}
  .bottomnav{{display:flex}}
  .pagehead{{padding:14px 0 10px}}
}}
@media(max-width:560px){{
  .main-inner{{padding:0 16px 90px}}
  .ph-sub{{flex-wrap:wrap;gap:5px 8px}}
}}

/* ── SECTION TITLES ─────────────────────────────────────── */
.stitle{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:11px;font-weight:500;color:var(--mu);text-transform:uppercase;
  letter-spacing:.14em;margin:30px 0 13px;display:flex;align-items:center;gap:10px;
}}
.stitle:first-child{{margin-top:6px}}
.stitle.spaced{{justify-content:space-between}}

/* ── ADD FOOD / WORKOUT FORMS ────────────────────────────── */
.add-card{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;
  margin-top:10px;overflow:hidden;backdrop-filter:blur(16px);box-shadow:var(--sh);
}}
.add-inp{{
  display:block;width:100%;background:transparent;border:none;
  border-bottom:1px solid var(--bd);color:var(--tx);font-family:inherit;
  font-size:14px;padding:13px 16px;outline:none;transition:background .15s;
}}
.add-inp:focus{{background:var(--sf2)}}
.add-inp::placeholder{{color:var(--di)}}
.add-macros{{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--bd)}}
.add-mac-field{{border-right:1px solid var(--bd);padding:10px 12px}}
.add-mac-field:last-child{{border-right:none}}
.add-mac-field label{{
  display:block;font-family:'Geist Mono','SF Mono',monospace;
  font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--mu);margin-bottom:5px;
}}
.add-mac-field input{{
  width:100%;background:transparent;border:none;color:var(--tx);
  font-family:inherit;font-size:14px;font-weight:500;outline:none;
}}
.add-mac-field input::placeholder{{color:var(--di)}}
.add-submit{{
  display:block;width:100%;border:none;background:transparent;
  color:var(--ac);font-family:'Geist Mono','SF Mono',monospace;
  font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;
  padding:13px 16px;cursor:pointer;text-align:left;transition:background .15s;
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

/* ── MACRO CARDS ─────────────────────────────────────────── */
.cards{{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}}
@media(min-width:440px){{.cards{{grid-template-columns:repeat(4,1fr)}}}}
.card{{
  background:var(--sf);border:1px solid var(--bd);border-radius:18px;padding:20px;
  backdrop-filter:blur(16px) saturate(140%);-webkit-backdrop-filter:blur(16px) saturate(140%);
  box-shadow:var(--sh);transition:background .3s,border-color .3s;
  position:relative;overflow:hidden;
}}
[data-theme="dark"] .card::before{{
  content:'';position:absolute;inset:0;border-radius:16px;
  background:linear-gradient(135deg,rgba(255,255,255,.03),transparent);
  pointer-events:none;
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
[data-theme="dark"] .pfill{{filter:brightness(1.1) saturate(1.2)}}

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
.heat-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}}
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
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
[data-theme="dark"] .icrd{{
  background:linear-gradient(160deg,rgba(0,230,118,.04),transparent 55%),var(--sf);
  border-color:rgba(0,230,118,.14);
}}
.irow{{
  display:grid;grid-template-columns:26px 1fr;gap:10px;
  padding:12px 14px;border-bottom:1px solid var(--bd);align-items:flex-start;
}}
.irow:last-child{{border-bottom:none}}
.iico{{
  font-size:11px;width:24px;height:24px;flex-shrink:0;margin-top:1px;
  background:var(--ac-dim);color:var(--ac);border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  border:1px solid rgba(var(--ac-rgb),.2);
}}
.itxt{{font-size:14px;line-height:1.55;color:var(--tx2)}}
.iload,.iempty{{padding:16px 12px;color:var(--mu);font-size:13px;text-align:center}}

/* ── WEARABLE ────────────────────────────────────────────── */
.hgrid{{display:grid;gap:7px;grid-template-columns:repeat(3,1fr)}}
@media(min-width:420px){{.hgrid{{grid-template-columns:repeat(6,1fr)}}}}
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
  display:flex;align-items:flex-start;gap:13px;
  padding:14px 16px;border-bottom:1px solid var(--bd);position:relative;
}}
.lrow:last-child{{border-bottom:none}}
.lrow:hover{{background:var(--sf2)}}
.ficon{{
  width:38px;height:38px;border-radius:11px;flex-shrink:0;
  background:var(--sf2);border:1px solid var(--bd);
  display:grid;place-items:center;font-size:20px;margin-top:2px;
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
  display:flex;gap:0;font-size:12px;margin-top:7px;flex-wrap:wrap;
  font-family:'Geist Mono','SF Mono',monospace;
  align-items:center;
}}
.lmac .lm-sep{{color:var(--di);margin:0 8px;font-size:10px;}}
.lmac .lm-cal{{color:var(--tx2);font-weight:600;font-size:13px;}}
.lmac .lm-macro{{color:var(--mu);font-weight:400;font-size:11px;}}
.lmac b{{font-weight:600}}
.lempty{{padding:18px 12px;color:var(--mu);font-size:13px;text-align:center}}

/* ── TRAINING PROGRAM ───────────────────────────────────── */
.wp-summary{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;
  padding:18px 20px;backdrop-filter:blur(16px);box-shadow:var(--sh);
}}
.wp-name{{font-family:'Instrument Serif','Times New Roman',serif;font-size:22px;letter-spacing:-.01em;margin-bottom:4px}}
.wp-focus{{font-size:13px;color:var(--mu);margin-bottom:14px}}
.wp-rotation{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:18px}}
.wp-chip{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  padding:4px 10px;border-radius:6px;border:1px solid var(--bd);
  background:var(--sf2);color:var(--tx2);
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
  font-size:12px;color:var(--tx2);background:var(--sf2);
  border:1px solid var(--bd);border-radius:6px;padding:3px 9px;
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
.profile-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:700px){{.profile-grid{{grid-template-columns:1fr}}}}
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
.c2col{{display:grid;grid-template-columns:1fr;gap:9px}}
@media(min-width:700px){{.c2col{{grid-template-columns:1fr 1fr}}}}

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
.inval{{
  font-size:13px;font-weight:500;color:var(--tx2);
  text-align:right;word-break:break-word;overflow-wrap:anywhere;flex:1;min-width:0;
}}
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
  font-size:38px;line-height:1;letter-spacing:-.025em;color:var(--tx);
}}
@media(max-width:940px){{.ph-title{{font-size:30px}}}}
@media(max-width:560px){{.ph-title{{font-size:25px}}}}
.ph-sub{{
  font-family:'Geist Mono','SF Mono',monospace;
  font-size:11px;color:var(--mu);margin-top:8px;
  letter-spacing:.07em;text-transform:uppercase;
  display:flex;align-items:center;gap:12px;
}}
.ph-streak{{color:var(--ac);display:inline-flex;align-items:center;gap:5px;font-weight:500}}
.ph-actions{{display:flex;gap:8px;align-items:center;flex-shrink:0}}
.ph-log-btn{{
  border:none;border-radius:11px;padding:0 16px;height:36px;font-size:13px;
  font-weight:600;color:#000;background:var(--ac);
  cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:6px;
  white-space:nowrap;transition:opacity .15s,transform .12s;
  box-shadow:0 4px 14px rgba(var(--ac-rgb),.4);flex-shrink:0;
}}
[data-theme="light"] .ph-log-btn{{color:#fff}}
.ph-log-btn:hover{{opacity:.85;transform:translateY(-1px)}}
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
  width:14px;height:14px;border-radius:4px;border:1.5px solid var(--di);
  display:grid;place-items:center;flex-shrink:0;font-size:10px;line-height:1;color:transparent;
}}
.toggle.on .tcb{{background:var(--ac);border-color:var(--ac);color:#000}}
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

/* ═══════════════════════════════════════════════════════════
   IMMERSIVE 3D + MOBILE
   ═══════════════════════════════════════════════════════════ */

/* ── Subtle dot-grid texture ─────────────────────────────── */
[data-theme="dark"] body::after{{
  content:'';position:fixed;inset:0;z-index:3;pointer-events:none;
  opacity:.055;
  background-image:radial-gradient(circle,rgba(255,255,255,.35) 1px,transparent 1px);
  background-size:28px 28px;
}}

/* ── Ambient scene (body::before removed, handled by .scene divs) ── */
[data-theme="dark"] body::before{{display:none}}
[data-theme="light"] body::before{{display:none}}

/* ── 3D Ambient scene ────────────────────────────────────── */
.scene{{
  position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;
}}
.scene-orb{{
  position:absolute;border-radius:50%;
  will-change:transform;
}}
.so-1{{
  width:900px;height:900px;
  background:radial-gradient(closest-side,rgba(0,230,118,.18),transparent);
  top:-25%;left:-20%;filter:blur(55px);
  animation:soFloat1 22s ease-in-out infinite;
}}
.so-2{{
  width:750px;height:750px;
  background:radial-gradient(closest-side,rgba(59,130,246,.16),transparent);
  top:35%;right:-18%;filter:blur(50px);
  animation:soFloat2 28s ease-in-out infinite;
}}
.so-3{{
  width:650px;height:650px;
  background:radial-gradient(closest-side,rgba(112,60,220,.14),transparent);
  bottom:-12%;left:22%;filter:blur(60px);
  animation:soFloat3 20s ease-in-out infinite;
}}
.so-4{{
  width:450px;height:450px;
  background:radial-gradient(closest-side,rgba(0,195,255,.11),transparent);
  top:18%;left:52%;filter:blur(45px);
  animation:soFloat4 17s ease-in-out infinite reverse;
}}
.scene-grid{{
  position:absolute;
  bottom:-8%;left:-30%;right:-30%;height:48%;
  transform:perspective(550px) rotateX(72deg);
  transform-origin:bottom center;
  background-image:
    linear-gradient(rgba(0,230,118,.07) 0,transparent 1px),
    linear-gradient(90deg,rgba(0,230,118,.07) 0,transparent 1px);
  background-size:72px 72px;
  mask-image:linear-gradient(to top,rgba(0,0,0,.7) 0%,transparent 72%);
  -webkit-mask-image:linear-gradient(to top,rgba(0,0,0,.7) 0%,transparent 72%);
  animation:gridBreath 10s ease-in-out infinite;
}}
[data-theme="light"] .scene-grid{{opacity:0}}
[data-theme="light"] .so-1{{background:radial-gradient(closest-side,rgba(5,150,105,.09),transparent)}}
[data-theme="light"] .so-2{{background:radial-gradient(closest-side,rgba(37,99,235,.07),transparent)}}
[data-theme="light"] .so-3{{background:radial-gradient(closest-side,rgba(80,40,180,.06),transparent)}}
[data-theme="light"] .so-4{{background:radial-gradient(closest-side,rgba(0,150,200,.06),transparent)}}
@keyframes soFloat1{{
  0%,100%{{transform:translate(0,0) scale(1);}}
  25%{{transform:translate(90px,-70px) scale(1.08);}}
  50%{{transform:translate(-50px,55px) scale(.94);}}
  75%{{transform:translate(70px,25px) scale(1.04);}}
}}
@keyframes soFloat2{{
  0%,100%{{transform:translate(0,0) scale(1);}}
  33%{{transform:translate(-85px,-65px) scale(1.1);}}
  66%{{transform:translate(65px,85px) scale(.91);}}
}}
@keyframes soFloat3{{
  0%,100%{{transform:translate(0,0) scale(1);}}
  40%{{transform:translate(-65px,-80px) scale(1.12);}}
  80%{{transform:translate(85px,-35px) scale(.88);}}
}}
@keyframes soFloat4{{
  0%,100%{{transform:translate(0,0) scale(1);}}
  50%{{transform:translate(-75px,65px) scale(1.16);}}
}}
@keyframes gridBreath{{
  0%,100%{{opacity:.85;}}
  50%{{opacity:1.1;}}
}}

/* ── Deep card depth (dark mode) ─────────────────────────── */
[data-theme="dark"] .card,[data-theme="dark"] .icrd,
[data-theme="dark"] .heat-wrap,[data-theme="dark"] .ccrd,
[data-theme="dark"] .goal-card,[data-theme="dark"] .macro-ring-wrap,
[data-theme="dark"] .stat-tile,[data-theme="dark"] .lcrd,
[data-theme="dark"] .ancrd,[data-theme="dark"] .infocrd,
[data-theme="dark"] .dev-card{{
  box-shadow:
    0 1px 0 rgba(255,255,255,.07) inset,
    0 -1px 0 rgba(0,0,0,.18) inset,
    0 3px 6px rgba(0,0,0,.28),
    0 12px 32px rgba(0,0,0,.38),
    0 0 0 1px rgba(255,255,255,.07);
}}

/* ── 3D will-change + base transition ────────────────────── */
.card,.icrd,.heat-wrap,.ccrd,.goal-card,.macro-ring-wrap,.stat-tile{{
  will-change:transform;
  transition:transform .16s ease,box-shadow .16s ease;
}}

/* ── Glass light sweep on hover (desktop) ────────────────── */
.card,.icrd,.ccrd,.goal-card,.stat-tile,.macro-ring-wrap{{position:relative;overflow:hidden}}
.card::after,.icrd::after,.ccrd::after,.goal-card::after,.stat-tile::after,.macro-ring-wrap::after{{
  content:'';position:absolute;top:0;left:-90%;
  width:45%;height:100%;
  background:linear-gradient(105deg,transparent,rgba(255,255,255,.055),transparent);
  transform:skewX(-8deg);transition:left .55s cubic-bezier(.4,0,.2,1);
  pointer-events:none;z-index:2;
}}
.card:hover::after,.icrd:hover::after,.ccrd:hover::after,
.goal-card:hover::after,.stat-tile:hover::after,.macro-ring-wrap:hover::after{{left:150%}}

/* ── Neon glow system ────────────────────────────────────── */
[data-theme="dark"] .ph-log-btn{{
  box-shadow:
    0 0 22px rgba(0,230,118,.5),
    0 0 50px rgba(0,230,118,.16),
    0 4px 14px rgba(0,230,118,.4),
    0 1px 0 rgba(255,255,255,.4) inset;
}}
[data-theme="dark"] .ph-log-btn:hover{{
  box-shadow:
    0 0 30px rgba(0,230,118,.65),
    0 0 60px rgba(0,230,118,.22),
    0 6px 18px rgba(0,230,118,.5),
    0 1px 0 rgba(255,255,255,.4) inset;
}}
[data-theme="dark"] .navitem.active::before{{
  box-shadow:0 0 14px var(--ac),0 0 28px rgba(0,230,118,.35);
}}
[data-theme="dark"] .ph-streak{{
  text-shadow:0 0 14px rgba(0,230,118,.7);
}}
[data-theme="dark"] .dchip.active{{
  box-shadow:0 0 12px rgba(0,230,118,.25);
}}
[data-theme="dark"] .sb-avatar::after{{
  box-shadow:0 0 10px var(--ac);
}}

/* ── Sidebar glass depth ─────────────────────────────────── */
[data-theme="dark"] .sidebar{{
  background:linear-gradient(180deg,rgba(10,14,22,.96),rgba(8,12,20,.90));
  border-right:1px solid rgba(255,255,255,.07);
  box-shadow:2px 0 24px rgba(0,0,0,.4);
}}

/* ── Stagger card entrance ───────────────────────────────── */
@keyframes cardIn{{
  from{{opacity:0;transform:translateY(16px) scale(.98)}}
  to{{opacity:1;transform:none}}
}}
.card-in{{animation:cardIn .42s cubic-bezier(.2,.7,.2,1) both}}

/* ── Glowing border on insights card ────────────────────── */
[data-theme="dark"] .icrd{{
  border:1px solid rgba(0,230,118,.18);
  box-shadow:
    0 1px 0 rgba(255,255,255,.07) inset,
    0 3px 6px rgba(0,0,0,.28),
    0 12px 32px rgba(0,0,0,.38),
    0 0 20px rgba(0,230,118,.06);
}}

/* ── Floating glow on stat nums ──────────────────────────── */
[data-theme="dark"] .stat-num{{
  text-shadow:0 0 40px rgba(0,230,118,.2);
}}

/* ═══ MOBILE TYPOGRAPHY + LAYOUT FIXES ═════════════════════ */
@media(max-width:560px){{
  /* Pagehead: hide icon-only buttons, keep just + Log */
  .pagehead .hbtn{{display:none}}
  .pagehead{{padding:12px 0 8px;gap:10px;align-items:center;margin-bottom:4px}}
  .ph-title{{font-size:26px!important;letter-spacing:-.015em}}
  .ph-sub{{font-size:11px;margin-top:6px;gap:8px}}
  .ph-actions{{gap:5px}}
  .ph-log-btn{{padding:0 14px;height:35px;font-size:13px;border-radius:9px}}
  /* Section labels */
  .stitle{{margin:16px 0 8px;font-size:10px;letter-spacing:.11em}}
  /* Cards */
  .cval{{font-size:28px}}
  .clbl{{font-size:9.5px;margin-bottom:5px;letter-spacing:.09em}}
  .card{{padding:14px;border-radius:14px}}
  .lcrd{{border-radius:14px}}
  .heat-wrap{{padding:14px}}
  .macro-ring-wrap{{padding:14px;gap:14px}}
  .csub{{font-size:12px}}
  /* Date nav */
  .dchip{{padding:8px 13px;font-size:11.5px}}
  .darr{{width:34px;height:34px;border-radius:9px}}
  .dnav{{gap:5px;margin-bottom:14px}}
  /* Toggles */
  .toggle{{padding:7px 11px;font-size:12px;gap:6px}}
  .toggles{{gap:6px;margin-bottom:14px}}
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
  .ph-title{{font-size:28px!important}}
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
</style>
</head>
<body>
<div class="scene" aria-hidden="true">
  <div class="scene-orb so-1"></div>
  <div class="scene-orb so-2"></div>
  <div class="scene-orb so-3"></div>
  <div class="scene-orb so-4"></div>
  <div class="scene-grid"></div>
</div>
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
    <button class="ph-log-btn" onclick="openLogModal()">+ Log</button>
    <button class="hbtn" id="theme-btn" onclick="toggleTheme()" title="Toggle theme">&#9790;</button>
    <button class="hbtn" onclick="refreshCurrent()" title="Refresh">&#8635;</button>
  </div>
</div>

<div id="app-load">Loading your data&hellip;</div>

  <!-- DAY TAB -->
  <div class="tab-panel active" id="panel-day">
    <div class="dnav">
      <button class="darr" id="date-prev" onclick="navDate(-1)" aria-label="Previous day">&#8249;</button>
      <div class="dscroll" id="date-chips"></div>
      <button class="darr" id="date-next" onclick="navDate(1)"  aria-label="Next day">&#8250;</button>
    </div>

    <!-- FULL-WIDTH: macros + toggles always on top -->
    <!-- Coach insights — full width, always at the top -->
    <div class="insights-top">
      <div class="stitle spaced">
        <span>&#10024; Coach insights <span class="ai-pill">AI</span></span>
        <button class="add-toggle" onclick="refreshInsights()" title="Refresh" style="font-size:14px;font-family:inherit">&#8635;</button>
      </div>
      <div class="icrd fade-in" id="insights-card">
        <div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div>
      </div>
    </div>

    <div class="day-top">
      <div class="stitle" id="day-label">Today</div>
      <div class="cards">
        <div class="card">
          <div class="clbl">Calories</div>
          <div class="cval" id="cal-val">&mdash;</div>
          <div class="csub" id="cal-sub"></div>
          <div class="ptrack"><div class="pfill" id="cal-bar" style="background:var(--ac);width:0%"></div></div>
        </div>
        <div class="card">
          <div class="clbl">Protein</div>
          <div class="cval" id="pro-val">&mdash;</div>
          <div class="csub" id="pro-sub"></div>
          <div class="ptrack"><div class="pfill" id="pro-bar" style="background:var(--bl);width:0%"></div></div>
        </div>
        <div class="card">
          <div class="clbl">Carbs</div>
          <div class="cval" id="carb-val">&mdash;</div>
          <div class="csub" id="carb-sub"></div>
        </div>
        <div class="card">
          <div class="clbl">Fats</div>
          <div class="cval" id="fat-val">&mdash;</div>
          <div class="csub" id="fat-sub"></div>
        </div>
      </div>
      <div class="toggles">
        <span id="wo-badge" class="toggle"><span class="tcb"></span>No workout</span>
        <span id="ca-badge" class="toggle"><span class="tcb"></span>No cardio</span>
        <span id="wt-badge" class="toggle on" style="display:none"></span>
        <button class="toggle share-tgl t-click" onclick="shareDay()">&#8679; Share day</button>
      </div>
    </div>

    <!-- 2-COL GRID: food/workouts left on mobile, analytics right -->
    <div class="day-grid">

      <!-- Analytics column (right on desktop, bottom on mobile) -->
      <div class="day-col-analytics">
        <div class="stitle">Energy breakdown</div>
        <div class="macro-ring-wrap">
          <canvas class="macro-ring-canvas" id="macroRing" width="80" height="80"></canvas>
          <div class="macro-legend" id="macro-legend"></div>
        </div>

        <div class="stitle">28-day consistency</div>
        <div class="heat-wrap">
          <div class="heat-dow">
            <span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span><span>S</span>
          </div>
          <div class="heat-grid" id="heat-grid"></div>
          <div class="heat-legend">
            <span class="hleg-dot" style="background:#22c55e"></span>On target &nbsp;
            <span class="hleg-dot" style="background:#f59e0b"></span>Logged &nbsp;
            <span class="hleg-dot" style="background:var(--sf2)"></span>Missed &nbsp;
            <span class="hleg-dot" style="background:rgba(255,255,255,.15)"></span><span style="color:var(--di)">● workout</span>
          </div>
        </div>

        <div id="health-section" style="display:none">
          <div class="stitle">Wearable</div>
          <div class="hgrid" id="health-grid"></div>
        </div>
      </div>

      <!-- Logging column (right on desktop, top on mobile) -->
      <div class="day-col-log">
        <div class="stitle spaced">
          <span>Food log <span id="food-log-count" style="font-weight:400;opacity:.7"></span></span>
          <button class="add-toggle" id="food-toggle" onclick="toggleAddForm('food')" title="Add food">+</button>
        </div>
        <div class="add-card" id="food-form" style="display:none">
          <input class="add-inp" id="food-name" placeholder="Food name (e.g. chicken breast)" autocomplete="off">
          <input class="add-inp" id="food-qty" placeholder="Portion (e.g. 200g, 1 cup)">
          <div class="add-macros">
            <div class="add-mac-field"><label>Cal</label><input type="number" id="food-cal" min="0" inputmode="numeric" placeholder="0"></div>
            <div class="add-mac-field"><label>P (g)</label><input type="number" id="food-pro" min="0" inputmode="decimal" placeholder="0"></div>
            <div class="add-mac-field"><label>C (g)</label><input type="number" id="food-carb" min="0" inputmode="decimal" placeholder="0"></div>
            <div class="add-mac-field"><label>F (g)</label><input type="number" id="food-fat" min="0" inputmode="decimal" placeholder="0"></div>
          </div>
          <button class="add-submit" id="food-submit" onclick="submitFood()">Save food</button>
        </div>
        <div class="lcrd" id="food-log"><div class="lempty">Loading&hellip;</div></div>

        <div class="stitle spaced" style="margin-top:28px">
          <span>Workouts</span>
          <button class="add-toggle" id="ex-toggle" onclick="toggleAddForm('ex')" title="Add workout">+</button>
        </div>
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
            <label for="ex-cardio">Cardio / conditioning</label>
          </div>
          <button class="add-submit" id="ex-submit" onclick="submitExercise()">Save workout</button>
        </div>
      </div>

    </div><!-- /day-grid -->
  </div>
  </div>

  <!-- WEEK TAB — single column -->
  <div class="tab-panel" id="panel-week">
    <div class="ccrd">
      <div class="ctitle"><span>Calories &middot; 30 days</span><span id="cal-avg-lbl" class="ctitle-val" style="color:var(--ac)"></span></div>
      <div class="cwrap"><canvas id="calChart"></canvas></div>
    </div>
    <div class="ccrd" style="margin-top:14px">
      <div class="ctitle"><span>Protein &middot; 30 days</span><span id="pro-tgt-lbl" class="ctitle-val" style="color:var(--bl)"></span></div>
      <div class="cwrap"><canvas id="proChart"></canvas></div>
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
    <div class="stitle">Last 14 days</div>
    <div class="infocrd" id="hist-table-wrap"><div class="lempty">Loading&hellip;</div></div>
  </div>

  <!-- PROFILE TAB — single column -->
  <div class="tab-panel" id="panel-profile">
    <div class="stitle" style="margin-top:4px">Your info</div>
    <div class="infocrd" id="profile-info"></div>
    <div class="stitle">Targets</div>
    <div class="infocrd" id="profile-targets"></div>

    <div class="stitle spaced">
      <span>Training program</span>
      <button class="add-toggle" id="wp-edit-btn" onclick="openWorkoutEditor()" title="Set up program">+</button>
    </div>
    <div id="workout-program-card"></div>

    <!-- paste / edit panel (hidden by default) -->
    <div class="add-card" id="workout-editor" style="display:none;margin-top:10px">
      <div style="display:flex;gap:8px;padding:12px 14px;border-bottom:1px solid var(--bd)">
        <button class="add-submit" style="flex:1;text-align:center;padding:10px" onclick="autoFillWorkout()">&#10024; Auto-fill from Arnie chat</button>
      </div>
      <div style="padding:6px 14px;font-family:'Geist Mono','SF Mono',monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--di)">or paste manually</div>
      <textarea class="add-inp" id="workout-raw" rows="10" placeholder="Paste your workout split here — exercises, goals, recent lifts, rotation." style="height:180px;resize:vertical;font-size:13px;line-height:1.5"></textarea>
      <div style="display:flex;gap:8px;padding:10px 14px;border-top:1px solid var(--bd)">
        <button class="add-submit" style="flex:1" onclick="saveWorkoutProgram()">&#9889; Parse &amp; save</button>
        <button class="cbtn" onclick="closeWorkoutEditor()">Cancel</button>
      </div>
      <div id="workout-parse-status" style="padding:0 14px 10px;font-size:12px;color:var(--mu)"></div>
    </div>

    <div class="stitle">Connected devices</div>
    <div class="infocrd" style="overflow:hidden" id="devices-card"></div>
    <div class="stitle">Science</div>
    <div class="ancrd">
      <div class="antitle">Performance analytics</div>
      <div class="angrid" id="analytics-grid"></div>
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
</nav>

</div><!-- /shell -->

<script>
// ── Constants ─────────────────────────────────────────────────────────────
const TOKEN        = '{token}';
const STATS_BASE   = '/api/stats/'    + TOKEN;
const INSIGHTS_API = '/api/insights/' + TOKEN;

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
  var[,m,day]=d.split('-');
  return['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m-1]+' '+ +day;
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
async function fetchInsights(){{
  try{{
    var r=await fetch(INSIGHTS_API);
    if(!r.ok) return[];
    return(await r.json()).insights||[];
  }}catch(e){{return[]}}
}}

// ── Tab switching ─────────────────────────────────────────────────────────
var PAGE_HEADS={{
  week:{{title:'Your trends',sub:'LAST 30 DAYS'}},
  profile:{{title:'Your profile',sub:'ACCOUNT &amp; COACHING'}},
}};
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
  if(name==='week' && _baseData) renderWeekTab(_baseData);
  if(name==='profile' && _baseData){{renderProfileTab(_baseData);loadWorkoutProgram();}}
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
    fetchInsights().then(renderInsights);
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
      responsive:false,
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
  var closed=history.filter(function(h){{return h.status==='closed';}});
  var avgCal=closed.length?Math.round(closed.reduce(function(s,h){{return s+h.calories;}},0)/closed.length):null;

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
  var ds=now.toLocaleDateString('en-US',{{weekday:'long',month:'long',day:'numeric'}}).toUpperCase();
  var hist=d.history||[];
  var t0=new Date();t0.setHours(0,0,0,0);
  var logSet=new Set(hist.map(function(h){{return h.date;}}));
  var st=0,ck=new Date(t0);
  while(true){{var ds2=_localDate(ck);if(logSet.has(ds2)){{st++;ck.setDate(ck.getDate()-1);}}else break;}}
  ps.innerHTML=esc(ds)+(st>0?' <span class="ph-streak">&#9889; '+st+'-DAY STREAK</span>':'');
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

function focusLogInput(){{
  switchTab('day');
  setTimeout(function(){{
    var form=document.getElementById('food-form');
    var btn=document.getElementById('food-toggle');
    if(form&&form.style.display==='none'){{
      form.style.display='block';
      if(btn)btn.classList.add('open');
    }}
    var el=document.getElementById('food-name');
    if(el){{el.scrollIntoView({{behavior:'smooth',block:'center'}});el.focus();}}
  }},220);
}}

// ── Log food ──────────────────────────────────────────────
async function submitFood(){{
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
async function submitExercise(){{
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
  document.getElementById('day-label').textContent=isToday?'Today':fmtDate(_viewingDate);
  var day=d.day||{{}},tgt=d.targets||{{}};
  var cp=pct(day.calories,tgt.calories),pp=pct(day.protein,tgt.protein);

  var calEl=document.getElementById('cal-val');
  if(day.calories!=null) countUp(calEl,day.calories);
  else calEl.textContent='—';
  document.getElementById('cal-sub').textContent=tgt.calories?'/ '+tgt.calories+' ('+cp+'%)':'kcal';
  document.getElementById('cal-bar').style.width=cp+'%';

  var proEl=document.getElementById('pro-val');
  proEl.textContent=day.protein!=null?day.protein+'g':'—';
  document.getElementById('pro-sub').textContent=tgt.protein?'/ '+tgt.protein+'g ('+pp+'%)':'grams';
  document.getElementById('pro-bar').style.width=pp+'%';
  var carbEl=document.getElementById('carb-val');carbEl.textContent=day.carbs!=null?day.carbs+'g':'—';
  var carbSub=document.getElementById('carb-sub');if(carbSub)carbSub.textContent=tgt.carbs?'/ '+tgt.carbs+'g ('+pct(day.carbs,tgt.carbs)+'%)':'grams';
  var fatEl=document.getElementById('fat-val');fatEl.textContent=day.fats!=null?day.fats+'g':'—';
  var fatSub=document.getElementById('fat-sub');if(fatSub)fatSub.textContent=tgt.fats?'/ '+tgt.fats+'g ('+pct(day.fats,tgt.fats)+'%)':'grams';

  var wb=document.getElementById('wo-badge');
  if(wb){{var woOn=!!day.workout_completed;wb.className='toggle'+(woOn?' on':'');wb.innerHTML='<span class="tcb">'+(woOn?'&#10003;':'')+'</span>'+(woOn?'Workout done':'No workout');}}
  var cb=document.getElementById('ca-badge');
  if(cb){{var caOn=!!day.cardio_completed;cb.className='toggle'+(caOn?' on':'');cb.innerHTML='<span class="tcb">'+(caOn?'&#10003;':'')+'</span>'+(caOn?'Cardio done':'No cardio');}}
  var wb2=document.getElementById('wt-badge');
  if(wb2){{
    if(day.water_ml>0){{
      wb2.style.display='inline-flex';wb2.className='toggle on';
      wb2.textContent='💧 '+(day.water_ml>=1000?(day.water_ml/1000).toFixed(1)+'L':day.water_ml+'ml');
    }}else wb2.style.display='none';
  }}

  var fe=day.food_entries||[];
  var flc=document.getElementById('food-log-count');
  if(flc)flc.textContent=fe.length?fe.length+' item'+(fe.length!==1?'s':''):'';
  document.getElementById('food-log').innerHTML=fe.length?fe.map(renderFoodRow).join('')
    :'<div class="lempty">Nothing logged'+(isToday?' yet':'')+'</div>';
  var ee=day.exercise_entries||[];
  document.getElementById('ex-log').innerHTML=ee.length?ee.map(renderExerciseRow).join('')
    :'<div class="lempty">No exercises logged'+(isToday?' yet':'')+'</div>';

  renderMacroRing(day);
  renderHeatmap(d.history||[], d.targets||{{}});

  var hl=d.health||[],hd=hl.find(h=>h.date===_viewingDate)||null;
  var hs=document.getElementById('health-section');
  if(hd){{hs.style.display='block';renderHealthGrid(hd)}}
  else hs.style.display='none';
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

  var rows=(hist.slice(-14)||[]).reverse();
  document.getElementById('hist-table-wrap').innerHTML=rows.length===0
    ?'<div class="lempty">No history yet</div>'
    :'<table class="htbl"><thead><tr><th>Date</th><th class="r">Calories</th><th class="r">Protein</th><th class="r">Workout</th></tr></thead><tbody>'+
      rows.map(function(h){{
        var calOk=tgt.calories&&h.calories>=tgt.calories*.9&&h.calories<=tgt.calories*1.1;
        var calOv=tgt.calories&&h.calories>tgt.calories*1.1;
        var proOk=tgt.protein&&h.protein>=tgt.protein*.9;
        var woDot=h.workout
          ?'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ac);box-shadow:0 0 6px var(--ac)"></span>'
          :'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--di)"></span>';
        return '<tr>'+
          '<td class="td-date">'+esc(h.date.slice(5))+'</td>'+
          '<td class="r '+(calOk?'td-ok':calOv?'td-ov':'')+'">'+(h.calories!=null?h.calories.toLocaleString():'—')+'</td>'+
          '<td class="r '+(proOk?'td-ok':'')+'">'+(h.protein!=null?h.protein+'g':'—')+'</td>'+
          '<td class="r">'+woDot+'</td></tr>';
      }}).join('')+'</tbody></table>';

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
    var goalsHtml=(day.goals||[]).map(function(g){{return '<span class="wp-goal">'+esc(g)+'</span>';'}}).join('');
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

function renderProfileTab(d){{
  var p=d.profile||{{}},tgt=d.targets||{{}},an=p.analytics||{{}};
  var rows=[
    ['Name',p.name],['Age',p.age?p.age+' yrs':null],['Sex',p.sex],
    ['Height',p.height_ft||(p.height_cm?p.height_cm+' cm':null)],
    ['Current weight',p.current_weight_lbs?p.current_weight_lbs+' lbs':null],
    ['Goal weight',p.goal_weight_lbs?p.goal_weight_lbs+' lbs':null],
    ['Goal',p.primary_goal],['Experience',p.training_experience],
    ['Diet',p.dietary_preferences&&p.dietary_preferences!=='none'?p.dietary_preferences:null],
    ['Injuries',p.injuries&&p.injuries!=='none'?p.injuries:null],
    ['Timezone',p.timezone],['Coaching style',p.coaching_style],
  ].filter(([,v])=>v!=null&&v!=='');
  // Badge renderer for Goal / Coaching style
  function _badge(v,cls){{return v?'<span class="'+cls+'">'+esc(v.toUpperCase())+'</span>':'';}}
  document.getElementById('profile-info').innerHTML=rows.map(([l,v])=>{{
    if(l==='Goal') return _inrow(l,null,_PEDIT,null).replace('</div></div>',
      '<div style="display:flex;align-items:center;gap:6px">'+_badge(v,'goal-badge')+'</div></div></div>');
    if(l==='Coaching style') return _inrow(l,null,_PEDIT,null).replace('</div></div>',
      '<div style="display:flex;align-items:center;gap:6px">'+_badge(v,'coach-badge')+'</div></div></div>');
    return _inrow(l,v,_PEDIT,null);
  }}).join('')||'<div class="lempty">No profile data</div>';

  document.getElementById('profile-targets').innerHTML=
    _inrow('Calorie target',tgt.calories?tgt.calories.toLocaleString()+' kcal/day':'—',_TEDIT,'var(--ac)')+
    _inrow('Protein target',tgt.protein?tgt.protein+'g/day':'—',_TEDIT,'var(--bl)');

  var items=[
    ['TDEE',an.tdee_estimate!=null?an.tdee_estimate.toLocaleString()+' kcal':null,'var(--ac)'],
    ['BMR',an.bmr!=null?an.bmr.toLocaleString()+' kcal':null,'var(--bl)'],
    ['Daily diff',an.daily_vs_tdee!=null?(an.daily_vs_tdee>0?'+':'')+an.daily_vs_tdee+' kcal':null,
      an.pace_label==='surplus'?'var(--or)':'var(--ac)'],
    ['Target pace',an.pace_lbs_per_week!=null?an.pace_lbs_per_week+' lbs/wk':null,'var(--ac)'],
    ['Actual pace',an.actual_lbs_per_week!=null?an.actual_lbs_per_week+' lbs/wk':null,'var(--mu)'],
    ['Weeks to goal',an.weeks_to_goal!=null?an.weeks_to_goal+' wks':null,'var(--ye)'],
    ['Rec. protein',(an.rec_protein_min&&an.rec_protein_max)?an.rec_protein_min+'–'+an.rec_protein_max+'g':null,'var(--pu)'],
  ].filter(([,v])=>v!=null);
  document.getElementById('analytics-grid').innerHTML=items.map(([l,v,c])=>
    '<div class="anitem"><div class="anval" style="color:'+c+'">'+esc(String(v))+'</div>'+
    '<div class="anlbl">'+esc(l)+'</div></div>'
  ).join('')||'<div style="color:var(--mu);font-size:13px;grid-column:1/-1">No analytics data yet</div>';

  var devs=[
    {{name:'Apple Health',icon:'♥',live:p.apple_health_connected,label:p.apple_health_connected?'Syncing':'Not connected'}},
    {{name:'Whoop',icon:'〰',live:p.whoop_connected,label:p.whoop_connected?'Connected':'Not connected'}},
    {{name:'Fitbit',icon:'⊕',live:false,label:'Coming soon',soon:true}},
    {{name:'Hume',icon:'◉',live:false,label:'Coming soon',soon:true}},
  ];
  document.getElementById('devices-card').innerHTML=
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

// ── Insights ──────────────────────────────────────────────────────────────
function renderInsights(ins){{
  var el=document.getElementById('insights-card');
  if(!el)return;
  if(!ins||!ins.length){{
    el.innerHTML='<div class="iempty">Not enough data yet — keep logging and Arnie will have more to say.</div>';
    return;
  }}
  el.innerHTML=ins.map(function(txt){{
    return '<div class="irow fade-in"><div class="iico">&#9656;</div><div class="itxt">'+esc(txt)+'</div></div>';
  }}).join('');
}}

async function refreshInsights(){{
  var el=document.getElementById('insights-card');
  if(el)el.innerHTML='<div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div>';
  try{{
    var r=await fetch(INSIGHTS_API+'?force=true');
    if(!r.ok)throw new Error();
    renderInsights(((await r.json()).insights)||[]);
  }}catch(e){{
    if(el)el.innerHTML='<div class="iempty">Could not load insights — try again shortly.</div>';
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
  var est=f.estimated?'<span class="est-tag">EST</span>':'';
  var ico=foodEmoji(f.name);
  return '<div class="lrow" id="food-row-'+f.id+'">'+
    '<div class="ficon">'+ico+'</div>'+
    '<div class="fbody">'+
    '<div class="lname">'+esc(f.name)+est+'</div>'+
    (f.quantity?'<div class="lqty">'+esc(f.quantity)+'</div>':'')+
    '<div class="lmac">'+
    '<span class="lm-cal">'+(f.calories??0)+' cal</span>'+
    '<span class="lm-sep">·</span>'+
    '<span class="lm-macro"><b style="color:var(--bl)">'+(f.protein??0)+'g</b> P</span>'+
    '<span class="lm-sep">·</span>'+
    '<span class="lm-macro"><b style="color:var(--or)">'+(f.carbs??0)+'g</b> C</span>'+
    '<span class="lm-sep">·</span>'+
    '<span class="lm-macro"><b style="color:var(--pu)">'+(f.fats??0)+'g</b> F</span>'+
    '</div></div>'+
    '<div class="ract">'+
    '<button class="ibtn" onclick="editFood('+f.id+')" aria-label="Edit">&#9998;</button>'+
    '<button class="ibtn del" onclick="deleteFood('+f.id+')" aria-label="Delete">&#215;</button>'+
    '</div></div>';
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
  row.innerHTML='<span class="inlbl">'+esc(lbl)+'</span>'+
    '<div style="display:flex;align-items:center;gap:5px;flex:1;justify-content:flex-end">'+
    '<input type="text" id="pi-'+rowId+'" value="'+escA(current)+'" '+
    'style="flex:1;max-width:160px;background:var(--inp);border:1px solid var(--ac);color:var(--tx);'+
    'padding:5px 8px;border-radius:8px;font-size:12px;font-family:inherit;outline:none">'+
    '<button class="sbtn" style="flex:none;padding:5px 12px;font-size:12px;min-height:0" '+
    'onclick="saveProw(\\''+rowId+'\\',\\''+escA(field)+'\\')">✓</button>'+
    '<button class="cbtn" style="flex:none;padding:5px 10px;font-size:12px;min-height:0" '+
    'onclick="cancelProw()">✗</button></div>';
  var inp=document.getElementById('pi-'+rowId);
  if(inp){{inp.focus();inp.select();}}
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
    _baseData=data;_dayCache[_todayStr]=data;
    renderProfileTab(data);
    document.getElementById('user-name').textContent=data.profile?.name||'';
    document.getElementById('goal-tag').textContent=data.profile?.primary_goal||'';
  }}catch(e){{
    alert('Save failed — try again.');
    if(btn){{btn.disabled=false;btn.textContent='✓';}}
  }}
}}

function cancelProw(){{if(_baseData)renderProfileTab(_baseData);}}

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
init();
setInterval(()=>{{
  delete _dayCache[_todayStr];
  if(_viewingDate===_todayStr) refreshCurrent();
}}, 5*60*1000);

// ── Post-render enhancements ──────────────────────────────
(function(){{
  var isMobile=window.matchMedia('(max-width:860px)').matches;
  var TILT=7,SC=1.018;
  var CARD_SEL='.card,.icrd,.stat-tile,.ccrd,.goal-card,.macro-ring-wrap';
  var STAGGER_SEL='.card,.icrd,.heat-wrap,.ccrd,.goal-card,.stat-tile,.macro-ring-wrap,.lcrd,.ancrd,.infocrd';

  // 3D tilt (desktop only)
  function attachTilt(){{
    if(isMobile)return;
    document.querySelectorAll(CARD_SEL).forEach(function(card){{
      if(card._tilt)return;card._tilt=true;
      card.addEventListener('mousemove',function(e){{
        var r=card.getBoundingClientRect();
        var x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;
        card.style.transform='perspective(900px) rotateX('+(y*-TILT)+'deg) rotateY('+(x*TILT)+'deg) scale('+SC+')';
      }});
      card.addEventListener('mouseleave',function(){{card.style.transform='';}});
    }});
  }}

  // Stagger entrance
  function staggerCards(scope){{
    (scope||document).querySelectorAll(STAGGER_SEL).forEach(function(el,i){{
      el.style.animation='none';void el.offsetWidth;
      el.style.animationDelay=(i*50)+'ms';
      el.style.animation='cardIn .4s cubic-bezier(.2,.7,.2,1) both';
    }});
  }}

  // Mouse parallax on body::before (desktop)
  if(!isMobile){{
    var raf=null;
    window.addEventListener('mousemove',function(e){{
      if(raf)return;
      raf=requestAnimationFrame(function(){{
        var x=(e.clientX/window.innerWidth-.5)*30;
        var y=(e.clientY/window.innerHeight-.5)*20;
        document.documentElement.style.setProperty('--px',x+'px');
        document.documentElement.style.setProperty('--py',y+'px');
        raf=null;
      }});
    }});
  }}

  // Hook into switchTab once
  var _orig=switchTab;
  switchTab=function(name){{
    _orig(name);
    window.scrollTo({{top:0,behavior:'smooth'}});
    setTimeout(function(){{
      staggerCards(document.getElementById('panel-'+name));
      attachTilt();
    }},60);
  }};

  // Initial run
  setTimeout(function(){{staggerCards();attachTilt();}},500);
}})();
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
</body>
</html>"""


def _apple_guide_html(endpoint: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Apple Health Setup — Arnie</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',-apple-system,sans-serif;background:#070c18;color:#eef2ff;
  min-height:100vh;padding:0 0 48px;-webkit-font-smoothing:antialiased}}
header{{background:rgba(7,12,24,.95);border-bottom:1px solid rgba(255,255,255,.08);
  padding:14px 20px;position:sticky;top:0;z-index:10;backdrop-filter:blur(16px)}}
.logo{{font-size:17px;font-weight:800;background:linear-gradient(130deg,#00e676,#3b82f6);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
main{{max-width:640px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;font-weight:800;margin-bottom:6px;letter-spacing:-.4px}}
.sub{{font-size:14px;color:#6b7a99;margin-bottom:28px;line-height:1.5}}
.section{{margin-bottom:32px}}
.section-lbl{{font-size:10px;font-weight:700;color:#3d4a66;text-transform:uppercase;
  letter-spacing:1.4px;margin-bottom:12px}}
.url-box{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);
  border-radius:12px;padding:14px;display:flex;align-items:center;gap:10px;cursor:pointer}}
.url-text{{font-family:monospace;font-size:12px;color:#00e676;word-break:break-all;flex:1;line-height:1.5}}
.copy-btn{{background:rgba(0,230,118,.15);border:1px solid rgba(0,230,118,.3);color:#00e676;
  padding:8px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;
  white-space:nowrap;font-family:inherit;transition:all .2s;flex-shrink:0}}
.copy-btn:active{{transform:scale(.94)}}
.steps{{display:grid;gap:12px}}
.step{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
  border-radius:14px;padding:16px;display:grid;grid-template-columns:32px 1fr;gap:12px;align-items:start}}
.step-num{{width:32px;height:32px;background:rgba(0,230,118,.12);border:1px solid rgba(0,230,118,.25);
  color:#00e676;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:800;flex-shrink:0}}
.step-title{{font-size:14px;font-weight:700;color:#eef2ff;margin-bottom:4px}}
.step-body{{font-size:13px;color:#8899aa;line-height:1.55}}
.step-body b{{color:#c8d0e8;font-weight:600}}
.step-body code{{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:5px;
  font-size:11px;color:#00e676;font-family:monospace}}
.json-block{{background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.08);
  border-radius:10px;padding:14px;font-family:monospace;font-size:12px;
  color:#8899aa;line-height:1.7;overflow-x:auto;margin-top:10px}}
.json-block .k{{color:#c8d0e8}}.json-block .v{{color:#00e676}}.json-block .c{{color:#3d4a66}}
.metrics-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
@media(min-width:480px){{.metrics-grid{{grid-template-columns:repeat(3,1fr)}}}}
.metric{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
  border-radius:10px;padding:10px}}
.metric-key{{font-family:monospace;font-size:11px;color:#00e676;margin-bottom:3px}}
.metric-src{{font-size:11px;color:#6b7a99}}
.tip{{background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.2);
  border-radius:12px;padding:14px;font-size:13px;color:#8899aa;line-height:1.55}}
.tip b{{color:#3b82f6}}
footer{{text-align:center;padding:32px 16px 0;color:#3d4a66;font-size:11px}}
</style>
</head>
<body>
<header><div class="logo">&#9889; Arnie</div></header>
<main>

<h1>Apple Health Setup</h1>
<p class="sub">Sync your iPhone's health data to Arnie automatically each morning using an iOS Shortcut.</p>

<div class="section">
  <div class="section-lbl">Your personal endpoint</div>
  <div class="url-box" onclick="copyUrl()">
    <div class="url-text" id="url-text">{endpoint}</div>
    <button class="copy-btn" id="copy-btn">Copy</button>
  </div>
</div>

<div class="section">
  <div class="section-lbl">Create the iOS Shortcut</div>
  <div class="steps">

    <div class="step">
      <div class="step-num">1</div>
      <div>
        <div class="step-title">Open Shortcuts → New Shortcut</div>
        <div class="step-body">
          On your iPhone open the <b>Shortcuts</b> app and tap <b>+</b> in the top right.
          Tap the title to rename it <b>"Arnie Health Sync"</b>.
        </div>
      </div>
    </div>

    <div class="step">
      <div class="step-num">2</div>
      <div>
        <div class="step-title">Add health data actions</div>
        <div class="step-body">
          Tap <b>Add Action</b>, search <b>"Find Health Samples"</b> and add one for each metric you want to sync.
          For each action set the date range to <b>Today</b> and choose the right statistic:<br><br>
          • <b>Step Count</b> — Summarise: Sum<br>
          • <b>Resting Heart Rate</b> — Limit: 1, Sort: Newest first<br>
          • <b>Heart Rate Variability</b> — Limit: 1, Sort: Newest first<br>
          • <b>Active Energy Burned</b> — Summarise: Sum<br>
          • <b>Sleep Analysis</b> — Summarise: Sum (gives hours × 3600 — divide by 3600 in the next step)<br><br>
          Set a <b>variable name</b> for the result of each action (e.g. "steps", "rhr", "hrv", "cals", "sleep").
        </div>
      </div>
    </div>

    <div class="step">
      <div class="step-num">3</div>
      <div>
        <div class="step-title">Build the request body</div>
        <div class="step-body">
          Add a <b>Dictionary</b> action and add keys for each metric using your variables:
          <div class="json-block">
<span class="c">// key → Health variable</span>
<span class="k">date</span>         → <span class="v">Format Date (Today, "yyyy-MM-dd")</span>
<span class="k">steps</span>        → <span class="v">steps variable</span>
<span class="k">resting_hr</span>   → <span class="v">rhr variable</span>
<span class="k">hrv</span>          → <span class="v">hrv variable</span>
<span class="k">active_calories</span> → <span class="v">cals variable</span>
<span class="k">sleep_hours</span>  → <span class="v">sleep ÷ 3600</span></div>
        </div>
      </div>
    </div>

    <div class="step">
      <div class="step-num">4</div>
      <div>
        <div class="step-title">Send to Arnie</div>
        <div class="step-body">
          Add a <b>"Get Contents of URL"</b> action:<br><br>
          • URL: <code>{endpoint}</code><br>
          • Method: <b>POST</b><br>
          • Request Body: <b>JSON</b> → set to the Dictionary from step 3
        </div>
      </div>
    </div>

    <div class="step">
      <div class="step-num">5</div>
      <div>
        <div class="step-title">Automate it</div>
        <div class="step-body">
          In Shortcuts tap <b>Automation</b> (bottom tab) → <b>+</b> → <b>Time of Day</b><br><br>
          • Time: <b>8:00 AM</b> (or whenever you wake up)<br>
          • Repeat: <b>Daily</b><br>
          • Run Shortcut: <b>Arnie Health Sync</b><br><br>
          Turn off "Ask Before Running" so it runs silently in the background.
        </div>
      </div>
    </div>

  </div>
</div>

<div class="section">
  <div class="section-lbl">Supported fields</div>
  <div class="metrics-grid">
    <div class="metric"><div class="metric-key">date</div><div class="metric-src">yyyy-MM-dd</div></div>
    <div class="metric"><div class="metric-key">steps</div><div class="metric-src">Step Count</div></div>
    <div class="metric"><div class="metric-key">resting_hr</div><div class="metric-src">Resting HR (bpm)</div></div>
    <div class="metric"><div class="metric-key">avg_hr</div><div class="metric-src">Heart Rate avg</div></div>
    <div class="metric"><div class="metric-key">hrv</div><div class="metric-src">HRV SDNN (ms)</div></div>
    <div class="metric"><div class="metric-key">active_calories</div><div class="metric-src">Active Energy (kcal)</div></div>
    <div class="metric"><div class="metric-key">resting_calories</div><div class="metric-src">Basal Energy (kcal)</div></div>
    <div class="metric"><div class="metric-key">sleep_hours</div><div class="metric-src">Sleep total (hrs)</div></div>
    <div class="metric"><div class="metric-key">sleep_deep_hours</div><div class="metric-src">Sleep deep (hrs)</div></div>
    <div class="metric"><div class="metric-key">sleep_rem_hours</div><div class="metric-src">Sleep REM (hrs)</div></div>
    <div class="metric"><div class="metric-key">stand_hours</div><div class="metric-src">Stand Hours</div></div>
    <div class="metric"><div class="metric-key">exercise_minutes</div><div class="metric-src">Exercise Minutes</div></div>
  </div>
</div>

<div class="tip">
  <b>Tip:</b> You only need to include the metrics you care about — all fields are optional.
  Once your first sync arrives, the dashboard will show Apple Health as connected and your metrics
  will appear in the Wearable section of the Day tab.
</div>

</main>
<footer>Arnie &middot; Apple Health via iOS Shortcut</footer>

<script>
function copyUrl(){{
  var url=document.getElementById('url-text').textContent;
  navigator.clipboard.writeText(url).then(function(){{
    var btn=document.getElementById('copy-btn');
    btn.textContent='Copied!';
    setTimeout(function(){{btn.textContent='Copy'}},2000);
  }});
}}
</script>
</body>
</html>"""
