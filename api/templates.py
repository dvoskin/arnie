"""
HTML template builders for Arnie web pages (extracted from api/app.py).

Pure string functions — no DB, no app.state, no FastAPI deps. Each is called
from exactly one route in api/app.py. Split out so app.py holds API/route logic
and these ~1.6k lines of HTML live on their own (AUDIT #9).
"""
from typing import Optional  # noqa: F401 — kept for parity if signatures evolve


def _dashboard_html(token: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Arnie</title>
<script>
(function(){{
  var t=localStorage.getItem('arnie-theme')||
    (window.matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');
  document.documentElement.setAttribute('data-theme',t);
}})();
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}

/* ── THEMES ─────────────────────────────────────────────── */
[data-theme="dark"]{{
  --bg:#070c18;
  --sf:rgba(255,255,255,.045); --sf2:rgba(255,255,255,.08); --sf3:rgba(255,255,255,.13);
  --bd:rgba(255,255,255,.09);  --bd2:rgba(255,255,255,.18);
  --ac:#00e676; --ac-rgb:0,230,118; --ac-dim:rgba(0,230,118,.12);
  --bl:#3b82f6; --or:#f97316; --pu:#a855f7; --re:#ef4444; --ye:#eab308;
  --tx:#eef2ff; --tx2:#c8d0e8; --mu:#6b7a99; --di:#3d4a66;
  --sh:none; --hbg:rgba(7,12,24,.92);
  --cgrid:rgba(255,255,255,.05); --ctick:#4a5568; --inp:rgba(255,255,255,.05);
}}
[data-theme="light"]{{
  --bg:#f0f4f8;
  --sf:#ffffff; --sf2:#f5f8fc; --sf3:#edf2f7;
  --bd:#e2e8f0; --bd2:#cbd5e1;
  --ac:#059669; --ac-rgb:5,150,105; --ac-dim:rgba(5,150,105,.1);
  --bl:#2563eb; --or:#ea580c; --pu:#9333ea; --re:#dc2626; --ye:#d97706;
  --tx:#0f172a; --tx2:#334155; --mu:#64748b; --di:#94a3b8;
  --sh:0 1px 3px rgba(0,0,0,.07),0 4px 16px rgba(0,0,0,.05);
  --hbg:rgba(240,244,248,.92);
  --cgrid:#e2e8f0; --ctick:#94a3b8; --inp:#f8fafc;
}}

/* ── BASE ────────────────────────────────────────────────── */
html{{background:var(--bg);transition:background .3s,color .3s}}
body{{
  font-family:'Inter',-apple-system,system-ui,sans-serif;
  background:var(--bg);color:var(--tx);min-height:100vh;
  -webkit-font-smoothing:antialiased;overflow-x:hidden;position:relative;
  padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom);
  transition:background .3s,color .3s;
}}
[data-theme="dark"] body::before{{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 80% 50% at 15% 20%,rgba(0,230,118,.07),transparent),
    radial-gradient(ellipse 60% 40% at 85% 70%,rgba(59,130,246,.05),transparent);
  animation:mesh 20s ease-in-out infinite alternate;
}}
@keyframes mesh{{0%{{opacity:.7;transform:scale(1)}}100%{{opacity:1;transform:scale(1.06)}}}}

/* ── HEADER ─────────────────────────────────────────────── */
header{{
  background:var(--hbg);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-bottom:1px solid var(--bd);padding:8px 14px;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;transition:background .3s;
}}
.logo{{
  font-size:15px;font-weight:800;letter-spacing:-.5px;
  background:linear-gradient(130deg,var(--ac),var(--bl));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}}
.hdr-r{{display:flex;align-items:center;gap:6px}}
.u-name{{font-size:12px;font-weight:600;color:var(--tx2)}}
.g-tag{{
  background:var(--ac-dim);color:var(--ac);font-size:9px;font-weight:700;
  padding:2px 7px;border-radius:20px;border:1px solid rgba(var(--ac-rgb),.25);
  text-transform:capitalize;
}}
.hbtn{{
  background:var(--sf2);border:1px solid var(--bd2);color:var(--mu);
  width:30px;height:30px;border-radius:9px;cursor:pointer;font-size:14px;
  display:flex;align-items:center;justify-content:center;font-family:inherit;
  transition:all .2s;flex-shrink:0;
}}
.hbtn:hover{{border-color:var(--ac);color:var(--ac)}}
.hbtn:active{{transform:scale(.91)}}

/* ── TABS ────────────────────────────────────────────────── */
.tabs{{
  background:var(--hbg);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-bottom:1px solid var(--bd);padding:6px 12px;
  display:flex;gap:4px;position:sticky;top:47px;z-index:99;
  transition:background .3s;
}}
.tab-pill{{
  position:absolute;bottom:8px;height:calc(100% - 16px);
  background:var(--sf2);border:1px solid var(--bd2);border-radius:10px;
  transition:left .25s cubic-bezier(.4,0,.2,1),width .25s cubic-bezier(.4,0,.2,1);
  pointer-events:none;z-index:0;
}}
.tab-btn{{
  flex:1;padding:6px 10px;border-radius:9px;border:none;
  background:transparent;color:var(--mu);font-size:12px;font-weight:600;
  cursor:pointer;font-family:inherit;min-height:32px;
  transition:color .2s;position:relative;z-index:1;
}}
.tab-btn.active{{color:var(--tx)}}

/* ── APP WRAP ────────────────────────────────────────────── */
.app-wrap{{
  max-width:960px;margin:0 auto;position:relative;min-height:100vh;
}}

/* ── MAIN ────────────────────────────────────────────────── */
main{{padding:12px 16px 80px;position:relative;z-index:1}}

/* Desktop 2-col day layout */
@media(min-width:700px){{
  #panel-day.active{{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}}
  .day-col-left{{min-width:0}}
  .day-col-right{{min-width:0}}
  #panel-day .dnav{{grid-column:1/-1}}
}}
#app-load{{text-align:center;padding:80px 20px;color:var(--mu);font-size:14px}}
.tab-panel{{display:none;animation:fadeUp .28s ease}}
.tab-panel.active{{display:block}}

/* ── SECTION TITLES ─────────────────────────────────────── */
.stitle{{
  font-size:10px;font-weight:700;color:var(--di);text-transform:uppercase;
  letter-spacing:1.4px;margin:18px 2px 8px;display:flex;align-items:center;gap:8px;
}}
.stitle:first-child{{margin-top:2px}}
.ai-pill{{
  background:var(--ac-dim);color:var(--ac);border:1px solid rgba(var(--ac-rgb),.2);
  padding:2px 7px;border-radius:10px;font-size:9px;letter-spacing:.5px;font-weight:700;
}}

/* ── DATE NAV ────────────────────────────────────────────── */
.dnav{{display:flex;align-items:center;gap:5px;margin-bottom:12px}}
.dscroll{{flex:1;display:flex;gap:5px;overflow-x:auto;scrollbar-width:none}}
.dscroll::-webkit-scrollbar{{display:none}}
.darr{{
  background:var(--sf);border:1px solid var(--bd);color:var(--mu);
  width:32px;height:32px;min-width:32px;border-radius:9px;cursor:pointer;
  font-size:15px;display:flex;align-items:center;justify-content:center;
  font-family:inherit;flex-shrink:0;transition:all .2s;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.darr:hover{{border-color:var(--bd2);color:var(--tx)}}
.darr:disabled{{opacity:.3;cursor:default}}
.dchip{{
  background:var(--sf);border:1px solid var(--bd);color:var(--mu);
  padding:6px 11px;border-radius:9px;font-size:11px;font-weight:600;
  white-space:nowrap;cursor:pointer;transition:all .2s;flex-shrink:0;
  display:inline-flex;align-items:center;gap:4px;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.dchip:hover{{border-color:var(--bd2);color:var(--tx2)}}
.dchip.active{{background:var(--ac-dim);border-color:var(--ac);color:var(--ac)}}
.today-tag{{
  background:var(--ac);color:#fff;font-size:9px;font-weight:700;
  padding:1px 5px;border-radius:5px;
}}
[data-theme="dark"] .today-tag{{color:#000}}

/* ── MACRO CARDS ─────────────────────────────────────────── */
.cards{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}}
@media(min-width:440px){{.cards{{grid-template-columns:repeat(4,1fr)}}}}
.card{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:12px;
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  box-shadow:var(--sh);transition:background .3s,border-color .3s;
  position:relative;overflow:hidden;
}}
[data-theme="dark"] .card::before{{
  content:'';position:absolute;inset:0;border-radius:16px;
  background:linear-gradient(135deg,rgba(255,255,255,.025),transparent);
  pointer-events:none;
}}
.clbl{{font-size:10px;color:var(--mu);text-transform:uppercase;letter-spacing:.8px;margin-bottom:5px;font-weight:700}}
.cval{{font-size:20px;font-weight:800;line-height:1;letter-spacing:-.5px}}
.csub{{font-size:11px;color:var(--mu);margin-top:3px;font-weight:500}}
.ptrack{{background:var(--sf2);border-radius:999px;height:3px;margin-top:10px;overflow:hidden}}
.pfill{{height:100%;border-radius:999px;transition:width .8s cubic-bezier(.4,0,.2,1)}}
[data-theme="dark"] .pfill{{filter:brightness(1.15) saturate(1.2)}}

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
  display:flex;align-items:center;gap:14px;
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:14px 16px;
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);box-shadow:var(--sh);
}}
.macro-ring-canvas{{width:80px;height:80px;flex-shrink:0}}
.macro-legend{{flex:1;display:flex;flex-direction:column;gap:7px}}
.mleg{{display:flex;align-items:center;gap:8px;font-size:12px}}
.mleg-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
.mleg-lbl{{color:var(--mu);flex:1;font-weight:500}}
.mleg-val{{font-weight:700;color:var(--tx);font-size:12px}}
.mleg-sub{{font-size:10px;color:var(--di)}}
.macro-divider{{border:none;border-top:1px solid var(--bd);margin:2px 0}}

/* ── CONSISTENCY HEATMAP ─────────────────────────────────── */
.heat-wrap{{background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:14px 16px;backdrop-filter:blur(16px);box-shadow:var(--sh)}}
.heat-dow{{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-bottom:3px}}
.heat-dow span{{font-size:9px;color:var(--di);text-align:center;font-weight:600;text-transform:uppercase;letter-spacing:.4px}}
.heat-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}}
.hcell{{height:20px;border-radius:4px;background:var(--sf2);position:relative;transition:transform .15s;cursor:default}}
.hcell:hover{{transform:scale(1.2);z-index:2}}
.hcell.h-on{{background:#22c55e}}
.hcell.h-off{{background:#f59e0b}}
.hcell.h-today{{box-shadow:0 0 0 2px var(--ac)}}
.hcell-wo{{position:absolute;bottom:2px;right:2px;width:3px;height:3px;border-radius:50%;background:rgba(255,255,255,.8)}}
.heat-legend{{display:flex;gap:12px;margin-top:8px;font-size:10px;color:var(--di);align-items:center}}
.hleg-dot{{width:8px;height:8px;border-radius:2px;display:inline-block;flex-shrink:0}}

/* ── GOAL PROGRESS ───────────────────────────────────────── */
.goal-card{{background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:14px 16px;backdrop-filter:blur(16px);box-shadow:var(--sh)}}
.goal-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}}
.goal-title{{font-size:13px;font-weight:700}}
.goal-sub{{font-size:11px;color:var(--mu);margin-top:2px}}
.goal-current{{text-align:right}}
.goal-lbs{{font-size:18px;font-weight:900;line-height:1;letter-spacing:-.5px}}
.goal-lbs-lbl{{font-size:10px;color:var(--mu)}}
.goal-track{{position:relative;height:7px;background:var(--sf2);border-radius:999px;margin:4px 0 8px}}
.goal-fill{{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--bl),var(--ac));transition:width .9s cubic-bezier(.4,0,.2,1)}}
.goal-pin{{position:absolute;top:50%;transform:translate(-50%,-50%);width:14px;height:14px;border-radius:50%;border:2px solid var(--bg)}}
.goal-labels{{display:flex;justify-content:space-between;font-size:10px;color:var(--mu);font-weight:600}}

/* ── STREAK STATS ────────────────────────────────────────── */
.stat-row{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.stat-tile{{background:var(--sf);border:1px solid var(--bd);border-radius:12px;padding:13px 10px;text-align:center;backdrop-filter:blur(16px);box-shadow:var(--sh)}}
.stat-num{{font-size:22px;font-weight:900;line-height:1;letter-spacing:-.5px}}
.stat-lbl{{font-size:9px;color:var(--mu);text-transform:uppercase;letter-spacing:.5px;margin-top:4px;font-weight:700}}

/* ── INSIGHTS ────────────────────────────────────────────── */
.icrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
[data-theme="dark"] .icrd{{
  background:linear-gradient(160deg,rgba(0,230,118,.04),transparent 60%),var(--sf);
  border-color:rgba(0,230,118,.15);
}}
.irow{{
  display:grid;grid-template-columns:26px 1fr;gap:8px;
  padding:10px 12px;border-bottom:1px solid var(--bd);align-items:flex-start;
}}
.irow:last-child{{border-bottom:none}}
.iico{{
  font-size:11px;width:24px;height:24px;flex-shrink:0;margin-top:1px;
  background:var(--ac-dim);color:var(--ac);border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  border:1px solid rgba(var(--ac-rgb),.2);
}}
.itxt{{font-size:12px;line-height:1.5;color:var(--tx2)}}
.iload,.iempty{{padding:16px 12px;color:var(--mu);font-size:12px;text-align:center}}

/* ── WEARABLE ────────────────────────────────────────────── */
.hgrid{{display:grid;gap:7px;grid-template-columns:repeat(3,1fr)}}
@media(min-width:420px){{.hgrid{{grid-template-columns:repeat(6,1fr)}}}}
.htile{{
  background:var(--sf);border:1px solid var(--bd);border-radius:12px;
  padding:10px 8px;text-align:center;backdrop-filter:blur(12px);
  box-shadow:var(--sh);transition:background .3s;
}}
.hv{{font-size:15px;font-weight:800;line-height:1;letter-spacing:-.3px}}
.hl{{font-size:9px;color:var(--mu);text-transform:uppercase;letter-spacing:.5px;margin-top:3px;font-weight:700}}

/* ── LOG CARDS ───────────────────────────────────────────── */
.lcrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
.lrow{{padding:11px 12px;border-bottom:1px solid var(--bd);position:relative}}
.lrow:last-child{{border-bottom:none}}
.lname{{font-size:13px;font-weight:600;line-height:1.3;word-break:break-word;padding-right:66px;color:var(--tx)}}
.lqty{{font-size:11px;color:var(--mu);margin-top:2px;font-weight:500}}
.lmac{{display:flex;gap:8px;font-size:11px;margin-top:5px;flex-wrap:wrap}}
.lmac span{{color:var(--mu)}}
.lmac b{{color:var(--tx2);font-weight:700}}
.lempty{{padding:18px 12px;color:var(--mu);font-size:13px;text-align:center}}
.erow{{padding:11px 12px;border-bottom:1px solid var(--bd);position:relative}}
.erow:last-child{{border-bottom:none}}
.ecnt{{display:flex;justify-content:space-between;align-items:center;padding-right:66px;gap:8px}}
.ename{{font-size:13px;font-weight:600;word-break:break-word;flex:1;color:var(--tx)}}
.edet{{font-size:12px;color:var(--ac);font-weight:700;white-space:nowrap}}

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
.emc label{{font-size:10px;color:var(--mu);display:block;margin-bottom:3px;font-weight:600}}
.eact{{display:flex;gap:6px;margin-top:4px}}
.sbtn{{
  background:var(--ac);color:#000;border:none;padding:9px 16px;
  border-radius:9px;font-weight:700;font-size:13px;cursor:pointer;font-family:inherit;
  flex:1;min-height:38px;transition:opacity .15s;
}}
[data-theme="light"] .sbtn{{color:#fff}}
.sbtn:hover{{opacity:.88}}
.cbtn{{
  background:var(--sf2);color:var(--mu);border:1px solid var(--bd);
  padding:9px 16px;border-radius:9px;font-size:13px;cursor:pointer;font-family:inherit;
  min-height:38px;transition:all .15s;
}}
.cbtn:hover{{border-color:var(--bd2);color:var(--tx)}}

/* ── CHARTS ──────────────────────────────────────────────── */
.ccrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:14px;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
.ctitle{{font-size:10px;font-weight:700;margin-bottom:12px;color:var(--mu);text-transform:uppercase;letter-spacing:.8px}}
.cwrap{{position:relative;height:150px}}
.c2col{{display:grid;grid-template-columns:1fr;gap:8px}}
@media(min-width:700px){{.c2col{{grid-template-columns:1fr 1fr}}}}

/* ── HISTORY TABLE ───────────────────────────────────────── */
.htbl{{width:100%;border-collapse:collapse;font-size:11px}}
.htbl th{{
  color:var(--di);text-transform:uppercase;letter-spacing:.5px;
  font-size:9px;font-weight:700;padding:8px 10px;text-align:left;
  border-bottom:1px solid var(--bd);
}}
.htbl td{{padding:8px 10px;border-bottom:1px solid var(--bd);color:var(--mu)}}
.htbl tr:last-child td{{border-bottom:none}}
.htbl td:first-child{{color:var(--tx2);font-weight:600}}
.td-ok{{color:var(--ac)!important;font-weight:700}}
.td-ov{{color:var(--re)!important;font-weight:700}}

/* ── PROFILE ─────────────────────────────────────────────── */
.infocrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);margin-bottom:8px;transition:background .3s;
}}
.inrow{{
  display:flex;justify-content:space-between;align-items:center;
  padding:11px 12px;border-bottom:1px solid var(--bd);
}}
.inrow:last-child{{border-bottom:none}}
.inlbl{{font-size:12px;color:var(--mu);font-weight:500}}
.inval{{font-size:12px;font-weight:700;color:var(--tx2);text-align:right;max-width:60%}}
.ancrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:14px;
  backdrop-filter:blur(16px);box-shadow:var(--sh);margin-bottom:8px;transition:background .3s;
}}
[data-theme="dark"] .ancrd{{
  background:linear-gradient(135deg,rgba(59,130,246,.06),transparent 60%),var(--sf);
  border-color:rgba(59,130,246,.15);
}}
.antitle{{font-size:10px;color:var(--mu);font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}}
.angrid{{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}}
@media(min-width:420px){{.angrid{{grid-template-columns:repeat(3,1fr)}}}}
.anitem{{background:var(--sf2);border-radius:10px;padding:10px;border:1px solid var(--bd);transition:background .3s}}
.anval{{font-size:16px;font-weight:800;line-height:1;letter-spacing:-.3px}}
.anlbl{{font-size:10px;color:var(--mu);margin-top:3px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}}
.devrow{{display:flex;align-items:center;gap:10px;padding:11px 12px;border-bottom:1px solid var(--bd)}}
.devrow:last-child{{border-bottom:none}}
.devname{{font-size:13px;font-weight:700;flex:1;color:var(--tx)}}
.devst{{font-size:12px;font-weight:700}}
.devst.on{{color:var(--ac)}}
.devst.off{{color:var(--mu)}}

/* ── EXERCISE SETS ───────────────────────────────────────── */
.esets{{display:flex;flex-wrap:wrap;gap:4px;padding:4px 12px 10px;align-items:center}}
.eset-chip{{
  background:var(--sf2);border:1px solid var(--bd);border-radius:7px;
  padding:4px 9px;font-size:11px;font-weight:600;color:var(--tx2);
}}
.eset-chip b{{color:var(--ac)}}
.eset-wt{{font-size:11px;font-weight:700;color:var(--or);margin-right:3px}}

/* ── SHARE BUTTON ────────────────────────────────────────── */
.share-btn{{
  background:var(--sf2);border:1px solid var(--bd);color:var(--mu);
  padding:5px 10px;border-radius:9px;font-size:11px;font-weight:600;
  cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;
  gap:4px;transition:all .2s;flex-shrink:0;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.share-btn:hover{{border-color:var(--ac);color:var(--ac)}}
.share-btn:active{{transform:scale(.93)}}

/* ── MISC ────────────────────────────────────────────────── */
footer{{text-align:center;padding:16px 12px;color:var(--di);font-size:10px;position:relative;z-index:1}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
.fade-in{{animation:fadeUp .3s ease}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.spin{{display:inline-block;animation:spin 1s linear infinite}}
</style>
</head>
<body>
<div class="app-wrap">

<header>
  <div class="logo">&#9889; Arnie</div>
  <div class="hdr-r">
    <span class="u-name" id="user-name"></span>
    <span id="goal-tag" class="g-tag"></span>
    <button class="hbtn" id="theme-btn" onclick="toggleTheme()" title="Toggle theme">&#9790;</button>
    <button class="hbtn" onclick="refreshCurrent()" title="Refresh">&#8635;</button>
  </div>
</header>

<div class="tabs" id="tabs-bar" role="tablist">
  <div class="tab-pill" id="tab-pill"></div>
  <button class="tab-btn active" id="tab-day"     role="tab" onclick="switchTab('day')">Day</button>
  <button class="tab-btn"        id="tab-week"    role="tab" onclick="switchTab('week')">Week</button>
  <button class="tab-btn"        id="tab-profile" role="tab" onclick="switchTab('profile')">Profile</button>
</div>

<main>
  <div id="app-load">Loading your data&hellip;</div>

  <!-- DAY TAB -->
  <div class="tab-panel active" id="panel-day">
    <div class="dnav">
      <button class="darr" id="date-prev" onclick="navDate(-1)" aria-label="Previous day">&#8249;</button>
      <div class="dscroll" id="date-chips"></div>
      <button class="darr" id="date-next" onclick="navDate(1)"  aria-label="Next day">&#8250;</button>
    </div>

    <!-- LEFT COLUMN: insights + macros + visuals -->
    <div class="day-col-left">
      <div class="stitle">&#10024; Coach insights <span class="ai-pill">AI</span></div>
      <div class="icrd fade-in" id="insights-card">
        <div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div>
      </div>

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
          <div class="csub" style="color:var(--or)">grams</div>
        </div>
        <div class="card">
          <div class="clbl">Fats</div>
          <div class="cval" id="fat-val">&mdash;</div>
          <div class="csub" style="color:var(--pu)">grams</div>
        </div>
      </div>

      <div class="sbrow">
        <span id="wo-badge" class="badge bg-n"></span>
        <span id="ca-badge" class="badge bg-n"></span>
        <span id="wt-badge" class="badge bg-b" style="display:none"></span>
        <button class="share-btn" onclick="shareDay()" title="Share today&apos;s summary">&#128228; Share day</button>
      </div>

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

    <!-- RIGHT COLUMN: food + workout logs -->
    <div class="day-col-right">
      <div class="stitle">Food log</div>
      <div class="lcrd" id="food-log"><div class="lempty">Loading&hellip;</div></div>

      <div class="stitle">Workouts</div>
      <div class="lcrd" id="ex-log"><div class="lempty">Loading&hellip;</div></div>
    </div>
  </div>

  <!-- WEEK TAB -->
  <div class="tab-panel" id="panel-week">
    <div class="c2col">
      <div class="ccrd">
        <div class="ctitle">Calories &mdash; 30 days</div>
        <div class="cwrap"><canvas id="calChart"></canvas></div>
      </div>
      <div class="ccrd">
        <div class="ctitle">Protein &mdash; 30 days</div>
        <div class="cwrap"><canvas id="proChart"></canvas></div>
      </div>
      <div class="ccrd">
        <div class="ctitle">Weight trend (lbs)</div>
        <div class="cwrap"><canvas id="weightChart"></canvas></div>
      </div>
    </div>
    <div class="stitle">Last 14 days</div>
    <div class="infocrd" id="hist-table-wrap"><div class="lempty">Loading&hellip;</div></div>

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
    <div class="stitle">Your info</div>
    <div class="infocrd" id="profile-info"></div>
    <div class="stitle">Targets</div>
    <div class="infocrd" id="profile-targets"></div>
    <div class="stitle">Science</div>
    <div class="ancrd">
      <div class="antitle">Performance analytics</div>
      <div class="angrid" id="analytics-grid"></div>
    </div>
    <div class="stitle">Connected devices</div>
    <div class="infocrd" id="devices-card"></div>
  </div>

</main>
<footer>Arnie &middot; auto-refresh 5 min</footer>
</div>

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

function toggleTheme(){{
  var html=document.documentElement;
  var next=html.getAttribute('data-theme')==='dark'?'light':'dark';
  html.setAttribute('data-theme',next);
  document.getElementById('theme-btn').textContent=next==='dark'?'☾':'☀';
  localStorage.setItem('arnie-theme',next);
  if(_baseData && _activeTab==='week') setTimeout(()=>renderWeekTab(_baseData),50);
}}

// ── Tab indicator pill ────────────────────────────────────────────────────
function updatePill(name){{
  var btn=document.getElementById('tab-'+name);
  var bar=document.getElementById('tabs-bar');
  var pill=document.getElementById('tab-pill');
  if(!btn||!bar||!pill) return;
  var br=bar.getBoundingClientRect(), br2=btn.getBoundingClientRect();
  pill.style.left=(br2.left-br.left)+'px';
  pill.style.width=br2.width+'px';
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
function switchTab(name){{
  _activeTab=name;
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  document.getElementById('panel-'+name).classList.add('active');
  updatePill(name);
  if(name==='week' && _baseData) renderWeekTab(_baseData);
  if(name==='profile' && _baseData) renderProfileTab(_baseData);
}}

// ── Boot ──────────────────────────────────────────────────────────────────
async function init(){{
  updatePill('day');
  try{{
    var data=await fetchStats(null);
    _baseData=data;
    _todayStr=data.viewing_date||data.day?.date||_localDate(new Date());
    _viewingDate=_todayStr;
    var hd=(data.history||[]).map(h=>h.date);
    _availDates=[...new Set([...hd,_todayStr])].sort();
    _dayCache[_todayStr]=data;
    document.getElementById('user-name').textContent=data.profile?.name||'';
    document.getElementById('goal-tag').textContent=data.profile?.primary_goal||'';
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

function renderDayTab(d){{
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
  document.getElementById('carb-val').textContent=day.carbs!=null?day.carbs+'g':'—';
  document.getElementById('fat-val').textContent=day.fats!=null?day.fats+'g':'—';

  var wb=document.getElementById('wo-badge');
  wb.className='badge '+(day.workout_completed?'bg-g':'bg-n');
  wb.textContent=day.workout_completed?'💪 Workout done':'⬜ No workout';
  var cb=document.getElementById('ca-badge');
  cb.className='badge '+(day.cardio_completed?'bg-g':'bg-n');
  cb.textContent=day.cardio_completed?'🏃 Cardio done':'⬜ No cardio';
  var wb2=document.getElementById('wt-badge');
  if(day.water_ml>0){{
    wb2.style.display='inline-flex';
    wb2.textContent='💧 '+(day.water_ml>=1000?(day.water_ml/1000).toFixed(1)+'L':day.water_ml+'ml');
  }}else wb2.style.display='none';

  var fe=day.food_entries||[];
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
    :'<table class="htbl"><thead><tr><th>Date</th><th>Calories</th><th>Protein</th><th>Workout</th></tr></thead><tbody>'+
      rows.map(h=>{{
        var cc=tgt.calories
          ?(h.calories>=tgt.calories*.9&&h.calories<=tgt.calories*1.1?'td-ok':h.calories>tgt.calories*1.1?'td-ov':'')
          :'';
        var pc=tgt.protein?(h.protein>=tgt.protein*.9?'td-ok':''):'';
        return '<tr><td>'+esc(h.date.slice(5))+'</td>'+
          '<td class="'+cc+'">'+(h.calories??'—')+'</td>'+
          '<td class="'+pc+'">'+(h.protein!=null?h.protein+'g':'—')+'</td>'+
          '<td>'+(h.workout?'✓':'✗')+'</td></tr>';
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
  var dispVal=color?'<span class="inval" style="color:'+color+'">'+esc(rawVal)+'</span>'
                   :'<span class="inval">'+esc(rawVal)+'</span>';
  var editBtn=fld?'<button class="ibtn" style="flex-shrink:0;margin-left:4px" onclick="editProw(\\'pr-'+_pslug(l)+'\\',\\''+escA(fld)+'\\',\\''+escA(rawVal)+'\\')">&#9998;</button>':'';
  return '<div class="inrow" id="pr-'+_pslug(l)+'"><span class="inlbl">'+esc(l)+'</span>'+
    '<div style="display:flex;align-items:center">'+dispVal+editBtn+'</div></div>';
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
  document.getElementById('profile-info').innerHTML=rows.map(([l,v])=>_inrow(l,v,_PEDIT,null))
    .join('')||'<div class="lempty">No profile data</div>';

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

  document.getElementById('devices-card').innerHTML=
    '<div class="devrow"><span style="font-size:20px">&#8987;</span>'+
    '<span class="devname">Whoop</span>'+
    '<span class="devst '+(p.whoop_connected?'on':'off')+'">'+
    (p.whoop_connected?'✓ Connected':'⚠ Not connected')+'</span></div>'+
    '<div class="devrow"><span style="font-size:20px">&#63743;</span>'+
    '<span class="devname">Apple Health</span>'+
    '<span class="devst '+(p.apple_health_connected?'on':'off')+'">'+
    (p.apple_health_connected?'✓ Syncing':'⚠ Not connected')+'</span></div>';
}}

// ── Insights ──────────────────────────────────────────────────────────────
function renderInsights(ins){{
  var el=document.getElementById('insights-card');
  if(!ins||!ins.length){{
    el.innerHTML='<div class="iempty">Not enough data yet — keep logging and check back tomorrow.</div>';
    return;
  }}
  el.innerHTML=ins.map(txt=>
    '<div class="irow fade-in"><div class="iico">&#9656;</div><div class="itxt">'+esc(txt)+'</div></div>'
  ).join('');
}}

// ── Food rows ─────────────────────────────────────────────────────────────
function renderFoodRow(f){{
  var est=f.estimated?' <span style="color:var(--di);font-size:10px;font-weight:500">~est</span>':'';
  return '<div class="lrow" id="food-row-'+f.id+'">'+
    '<div class="lname">'+esc(f.name)+est+'</div>'+
    '<div class="lqty">'+esc(f.quantity||'')+'</div>'+
    '<div class="lmac">'+
    '<span><b>'+(f.calories??0)+'</b> cal</span>'+
    '<span><b>'+(f.protein??0)+'g</b> P</span>'+
    '<span><b>'+(f.carbs??0)+'g</b> C</span>'+
    '<span><b>'+(f.fats??0)+'g</b> F</span></div>'+
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
      var btn=document.querySelector('.share-btn');
      if(btn){{var old=btn.innerHTML;btn.innerHTML='&#10003; Copied!';setTimeout(function(){{btn.innerHTML=old;}},1800);}}
    }}).catch(function(){{prompt('Copy your day summary:',text);}});
  }}
}}

// ── Start ─────────────────────────────────────────────────────────────────
init();
setInterval(()=>{{
  delete _dayCache[_todayStr];
  if(_viewingDate===_todayStr) refreshCurrent();
}}, 5*60*1000);
</script>
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
