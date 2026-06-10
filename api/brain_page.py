"""
HTML template for Arnie's Brain — the live mindmap of everything Arnie has
learned about the user. Served at /brain/{token} and embedded as an iframe
inside the dashboard's Brain tab (see panel-brain in api/templates.py).

The page is a small React app (loaded via CDN babel-standalone) that:
  • polls /api/profile/{token} every 20s while the tab is visible
  • adapts the response into the {lobes: [{id, name, nodes: [...]}]} shape
  • diffs against the previous snapshot to emit fresh-node events
  • falls back to the BRAIN_INITIAL sample stream for empty profiles so
    new users see the visual working immediately

Pure string function — no DB, no FastAPI deps. Mounted by api/app.py.

The JSX is kept in plain (non-f) strings and assembled by concatenation —
not Template/format — because the React code uses ``${...}`` template
literals and ``{...}`` JSX expressions that would collide with either
substitution syntax. Only the token URL is interpolated.
"""


# ── Sample data used as fallback for empty profiles ─────────────────────────
# Lifted from the standalone prototype (Arnie's Brain (standalone).html). The
# event stream loops until live data arrives.
_SAMPLE_JS = r"""
window.BRAIN_SAMPLE_LOBES = [
  { id: "nutrition", name: "Nutrition", short: "NUTRITION", nodes: [
    { id: "staple",   label: "Staple foods",   chips: ["Banana", "Barebells bars", "Oikos shake", "Honey", "White rice"], state: "confirmed" },
    { id: "diet",     label: "Diet style",     value: "High-protein, flexible dieting", state: "confirmed" },
    { id: "protein",  label: "Protein habits", value: "~180 g/day", state: "confirmed" },
    { id: "hydration", label: "Hydration",     value: "~3 L/day", state: "inferred" },
  ]},
  { id: "fitness", name: "Fitness", short: "FITNESS", nodes: [
    { id: "split",    label: "Training split", value: "Upper-Focus PPL", state: "confirmed" },
    { id: "exp",      label: "Experience",     value: "Advanced", state: "confirmed" },
    { id: "cardio",   label: "Favorite cardio", chips: ["Zone 1-2 Spin", "Incline walk"], state: "confirmed" },
  ]},
  { id: "health", name: "Health", short: "HEALTH", nodes: [
    { id: "supps",    label: "Supplements", chips: ["C4 pre-workout", "Fish oil", "Vitamin D"], state: "confirmed" },
  ]},
  { id: "behavior", name: "Behavior", short: "BEHAVIOR", nodes: [
    { id: "coachstyle", label: "Coaching style", value: "Strict", state: "confirmed" },
    { id: "motivation", label: "Motivation", value: "Strength PRs, leaner look", state: "inferred" },
  ]},
];

window.BRAIN_SAMPLE_EVENTS = [
  { t: "add",     lobe: "nutrition", id: "mealtiming", label: "Meal timing", value: "noticing a pattern...", state: "learning" },
  { t: "add",     lobe: "fitness",   id: "tfreq",      label: "Training frequency", value: "asking about this...", state: "learning" },
  { t: "add",     lobe: "health",    id: "sleepq",     label: "Sleep quality", value: "8.1h avg", state: "confirmed" },
  { t: "promote", id: "mealtiming", value: "Brunch -> protein dinner" },
  { t: "promote", id: "tfreq",   value: "5 days / week" },
  { t: "refine",  id: "protein", value: "~190 g/day" },
  { t: "promote", id: "hydration", value: "~3.2 L/day" },
];

window.applySampleEvent = function (lobes, ev) {
  const clone = lobes.map((l) => ({ ...l, nodes: l.nodes.map((n) => ({ ...n })) }));
  const find = (id) => { for (const l of clone) { const n = l.nodes.find((x) => x.id === id); if (n) return n; } return null; };
  let toast = null;
  if (ev.t === "add") {
    const lobe = clone.find((l) => l.id === ev.lobe);
    const existing = lobe && lobe.nodes.find((n) => n.id === ev.id);
    if (!existing && lobe) {
      lobe.nodes.push({ id: ev.id, label: ev.label, value: ev.value, state: ev.state });
      toast = { label: "Arnie noticed something new", text: ev.label };
    } else { toast = { label: "Arnie reconfirmed", text: (existing && existing.label) || ev.label }; }
  } else if (ev.t === "promote") {
    const n = find(ev.id);
    if (n) { n.state = "confirmed"; if (ev.value) n.value = ev.value;
      toast = { label: "Arnie confirmed your", text: n.label }; }
  } else if (ev.t === "refine") {
    const n = find(ev.id);
    if (n) { n.value = ev.value; toast = { label: "Arnie updated your", text: n.label }; }
  }
  return { lobes: clone, freshId: ev.id, toast };
};
"""


# ── Themes — aligned to the dashboard's design tokens ──────────────────────
# Mirrors --bg/--ac/--tx/--mu/--bd from api/templates.py so the constellation
# reads as part of the same surface as the rest of the dashboard. stageBg is
# transparent on purpose — the iframe sits on top of the dashboard's mesh
# gradient (#0c1018 dark / #f5f7fa light + the radial body::before overlays),
# and we want that to show through instead of painting another box.
_THEMES_JS = r"""
window.BRAIN_THEMES = {
  dark: {
    name: "dark",
    stageBg: "transparent",
    grain: "transparent",       // dashboard already has a mesh gradient
    known: "#00e676",            // --ac
    inferred: "#6b7a99",         // --mu
    learning: "#f97316",         // --or  (was amber — orange matches the dashboard's "needs verification" palette)
    glowA: "55",                 // softer glow so dots don't overpower
    line: "rgba(255,255,255,0.10)",   // --bd
    hub: "rgba(0,230,118,0.55)",      // --ac at low alpha
    label: "rgba(200,208,232,0.55)",  // --tx2 dimmed
    labelSel: "#eef2ff",              // --tx
    headText: "#eef2ff",
    subText: "#6b7a99",
    cardBg: "rgba(12,16,24,0.92)",    // --hbg
    cardBorder: "rgba(255,255,255,0.10)",
    cardLabel: "#6b7a99", cardTitle: "#c8d0e8", cardVal: "#eef2ff",
    listBg: "transparent", listDivider: "rgba(255,255,255,0.08)",
    secLabel: "#6b7a99", rowLabel: "#c8d0e8", rowVal: "#eef2ff",
    freshWash: "rgba(0,230,118,0.10)",
    ctrlBg: "rgba(255,255,255,0.05)", ctrlActiveBg: "rgba(255,255,255,0.10)",
    ctrlText: "#6b7a99", ctrlActiveText: "#eef2ff",
    iconBg: "rgba(255,255,255,0.05)", iconBorder: "rgba(255,255,255,0.10)", iconText: "#c8d0e8",
  },
  light: {
    name: "light",
    stageBg: "transparent",
    grain: "transparent",
    known: "#059669",            // --ac
    inferred: "#94a3b8",         // --di
    learning: "#ea580c",         // --or
    glowA: "55",
    line: "#dde4ef",             // --bd
    hub: "rgba(5,150,105,0.55)",
    label: "#64748b",
    labelSel: "#0f172a",
    headText: "#0f172a",
    subText: "#64748b",
    cardBg: "rgba(255,255,255,0.95)",
    cardBorder: "#dde4ef",
    cardLabel: "#64748b", cardTitle: "#334155", cardVal: "#0f172a",
    listBg: "transparent", listDivider: "#dde4ef",
    secLabel: "#64748b", rowLabel: "#334155", rowVal: "#0f172a",
    freshWash: "rgba(5,150,105,0.10)",
    ctrlBg: "#eef2f7", ctrlActiveBg: "#ffffff",
    ctrlText: "#64748b", ctrlActiveText: "#0f172a",
    iconBg: "#ffffff", iconBorder: "#dde4ef", iconText: "#334155",
  },
};
"""


# ── Constellation + List view — adapted from the prototype, with lobe
#    positions now computed on a ring (so the visual scales to N lobes).
_VIEWS_JS = r"""
// ── Constellation view ──────────────────────────────────────────────────────
const { useRef: useRefL, useEffect: useEffectL, useState: useStateL } = React;
const HALF = 134;
const FLOATS = ["lvFloatA", "lvFloatB", "lvFloatC", "lvFloatD", "lvFloatE"];

// Place lobes on an ellipse around a shifted-down centre. Radii scale with
// BOTH the canvas aspect ratio AND the number of lobes — fewer params huddle
// close to the core, more spread outward. Keeps the brain feeling alive and
// ever-growing instead of stretched-to-fit.
//
// Two structural choices keep the constellation from colliding with the
// header strip:
//   1. The vertical centre is biased DOWN by ~38px so the top half of the
//      ring clears the "23 PARAMETERS · LEARNING LIVE" + BRAIN/LIST chrome.
//   2. The starting angle rotates with lobe count so no lobe lands at exactly
//      12-o'clock under the header — for an even count we offset by half a
//      slice, for odd we keep top-centred but the centre shift handles it.
function lobePositions(lobes, w, h) {
  const n = lobes.length;
  if (!n) return {};
  const aspect = (w && h) ? w / h : 1.4;
  // 1 lobe -> tiny ring near centre; 5 -> filling the canvas. Caps at 1.
  const countScale = Math.min(1, 0.40 + n * 0.11);
  const rx = Math.min(0.40, (0.26 + aspect * 0.06)) * countScale;
  const ry = Math.min(0.32, (0.20 + (1 / aspect) * 0.06)) * countScale;
  const cy = 0.5 + (h ? 38 / h : 0);  // shift down to clear header chrome
  const res = {};
  // Offset starting angle by half a slice when count is even, so the ring
  // never has a lobe + label sitting under the top header bar.
  const start = -Math.PI / 2 + (n % 2 === 0 ? Math.PI / n : 0);
  lobes.forEach((l, i) => {
    const ang = start + (i * 2 * Math.PI) / n;
    res[l.id] = {
      x: 0.5 + Math.cos(ang) * rx,
      y: cy + Math.sin(ang) * ry,
    };
  });
  // Expose cy so the core pulse follows the same vertical centre.
  res.__cy = cy;
  return res;
}

// Per-lobe node ring. Tight single-ring for sparse lobes; once n > 8 we
// split into two concentric rings (inner + outer) so the cluster reads
// as a small galaxy instead of a cramped wheel. Group consecutive nodes
// with the same parentLabel onto the same ring when possible so each
// chip group reads as a cohesive arc rather than alternating in-out-in.
function layoutLocal(nodes) {
  const n = nodes.length;
  if (n <= 1) return nodes.map((node) => ({ id: node.id, lx: HALF, ly: HALF }));

  if (n <= 8) {
    const R = Math.min(86, 28 + n * 6);
    return nodes.map((node, i) => {
      const ang = (-90 + i * (360 / n)) * Math.PI / 180;
      return { id: node.id, lx: HALF + Math.cos(ang) * R, ly: HALF + Math.sin(ang) * R };
    });
  }

  // Dense lobe — two concentric rings. Split nodes ~60/40 outer/inner so
  // the outer ring (the eye-catching one) carries the majority and the
  // inner ring fills the breathing room without overlapping the outer
  // dots. Keep parentLabel runs intact: if a chip group spans the split,
  // shift the boundary forward so the whole group stays together.
  const outerCount = Math.ceil(n * 0.62);
  let split = outerCount;
  for (let k = split; k > Math.floor(n * 0.4); k--) {
    if (!nodes[k] || !nodes[k - 1]) break;
    if (nodes[k].parentLabel && nodes[k].parentLabel === nodes[k - 1].parentLabel) {
      split = k - 1;
    } else {
      break;
    }
  }
  const outerN = Math.max(2, split);
  const innerN = n - outerN;
  const Router = Math.min(110, 60 + outerN * 4);
  const Rinner = Math.max(28, Router - 40);

  const out = [];
  // Outer ring — start at top, full circle
  for (let i = 0; i < outerN; i++) {
    const ang = (-90 + (i * 360) / outerN) * Math.PI / 180;
    out.push({ id: nodes[i].id, lx: HALF + Math.cos(ang) * Router, ly: HALF + Math.sin(ang) * Router });
  }
  // Inner ring — offset half a slice so dots stagger from the outer ones
  for (let j = 0; j < innerN; j++) {
    const ang = (-90 + 180 / outerN + (j * 360) / innerN) * Math.PI / 180;
    out.push({ id: nodes[outerN + j].id, lx: HALF + Math.cos(ang) * Rinner, ly: HALF + Math.sin(ang) * Rinner });
  }
  return out;
}

function dotStyle(node, theme, sel, fresh) {
  const learning = node.state === "learning";
  const inferred = node.state === "inferred";
  const col = learning ? theme.learning : inferred ? theme.inferred : theme.known;
  const base = { width: sel ? 13 : 9, height: sel ? 13 : 9, borderRadius: "50%",
    transition: "width .22s, height .22s, box-shadow .3s, background .3s, border-color .3s" };
  if (learning) return { ...base, background: "transparent", border: `1.4px solid ${col}`, animation: "lvPulse 2.8s ease-in-out infinite", boxShadow: "none", col };
  if (inferred) return { ...base, background: "transparent", border: `1.4px solid ${col}`, boxShadow: "none", col };
  return { ...base, background: col, border: "none", boxShadow: `0 0 ${sel ? 14 : fresh ? 13 : 7}px ${col}${theme.glowA}`, col };
}

function NodeDot({ node, e, theme, sel, fresh, freshTick, onSelect }) {
  const [hover, setHover] = useStateL(false);
  const ds = dotStyle(node, theme, sel, fresh);
  const lit = sel || fresh || hover;
  // Labels hidden by default — they appear only when this dot is in focus
  // (hover, selection, or just-learned ripple). Keeps the constellation
  // breathing instead of drowning in text.
  return (
    <div onClick={(ev) => { ev.stopPropagation(); onSelect(sel ? null : node.id); }}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ position: "absolute", left: e.x, top: e.y,
        transform: `translate(-50%,-50%) scale(${e.s.toFixed(3)})`, opacity: e.o.toFixed(3),
        cursor: "pointer", zIndex: sel ? 8 : hover ? 7 : 2 }}>
      <span style={{ position: "relative", display: "grid", placeItems: "center" }}>
        {fresh && <span key={freshTick} className="lvRipple" style={{ position: "absolute", width: 13, height: 13, borderRadius: "50%", border: `1.4px solid ${ds.col}` }}></span>}
        <span style={{ width: ds.width, height: ds.height, borderRadius: ds.borderRadius, background: ds.background, border: ds.border, boxShadow: ds.boxShadow, transition: ds.transition }}></span>
      </span>
      <span title={node.label} style={{
        position: "absolute", top: "calc(50% + 12px)", left: "50%", transform: `translateX(-50%) translateY(${lit ? 0 : -3}px)`,
        maxWidth: 120, textAlign: "center", lineHeight: 1.18, whiteSpace: "nowrap",
        fontFamily: "'Geist Mono','DM Mono', monospace", fontSize: 10, letterSpacing: "0.02em",
        color: theme.labelSel, fontWeight: 500,
        opacity: lit ? 1 : 0, transition: "opacity .25s ease, transform .25s ease", pointerEvents: "none",
        textShadow: theme.name === "dark" ? "0 1px 8px rgba(0,0,0,0.9)" : "0 1px 6px rgba(255,255,255,0.95)" }}>
        {node.label}
      </span>
    </div>
  );
}

function BrainConstellationLive({ lobes, theme, freshId, freshTick, selectedId, onSelect, onSelectLobe, size }) {
  const pos = useRefL(new Map());
  const raf = useRefL(0);
  const running = useRefL(false);
  const [, setTick] = useStateL(0);
  const sig = lobes.map((l) => l.id + ":" + l.nodes.map((n) => n.id).join(",")).join("|");

  // ── Pan + zoom: drag with the mouse to reposition the constellation,
  // scroll/pinch to zoom. State lives on this component so the dot-tween
  // pipeline keeps working unchanged — we just transform the whole stage.
  const [pan, setPan] = useStateL({ x: 0, y: 0 });
  const [zoom, setZoom] = useStateL(1);
  const drag = useRefL(null);
  function onPointerDown(e) {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    drag.current = { px: e.clientX, py: e.clientY, sx: pan.x, sy: pan.y, moved: false, pid: e.pointerId };
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {}
  }
  function onPointerMove(e) {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.px;
    const dy = e.clientY - drag.current.py;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.current.moved = true;
    setPan({ x: drag.current.sx + dx, y: drag.current.sy + dy });
  }
  function onPointerUp(e) {
    const wasDrag = drag.current && drag.current.moved;
    drag.current = null;
    if (!wasDrag) onSelect(null);  // tap on empty = deselect
  }
  function onWheel(e) {
    e.preventDefault();
    const factor = Math.exp(-e.deltaY * 0.0015);
    setZoom((z) => Math.max(0.45, Math.min(2.4, z * factor)));
  }
  function resetView() { setPan({ x: 0, y: 0 }); setZoom(1); }

  // Stagger schedule — new dots get a startAt timestamp so they hold at
  // the centre invisible until their wave fires. Outer-lobe dots (li=0
  // is the topmost lobe in the ring) lead, and within each lobe the
  // dots fan out by index. Result: dots cascade out from Arnie like a
  // Big Bang lobe-by-lobe, then settle, instead of all blooming at once.
  // Refresh / re-render existing dots keep their position (no delay).
  useEffectL(() => {
    const present = new Set();
    const t0 = (typeof performance !== "undefined" ? performance.now() : 0);
    lobes.forEach((l, li) => {
      layoutLocal(l.nodes).forEach((loc, ni) => {
        present.add(loc.id);
        const e = pos.current.get(loc.id);
        if (!e) {
          // First time we've seen this dot — schedule it into the cascade.
          const delay = 50 + li * 75 + ni * 18;     // ms before this dot starts tweening
          pos.current.set(loc.id, {
            x: HALF, y: HALF, s: 0, o: 0,
            tx: loc.lx, ty: loc.ly, ts: 1, to: 1,
            lobe: l.id, removing: false,
            startAt: t0 + delay,
            // Brief overshoot so the dot pops on arrival instead of
            // creeping in.  Cleared a few frames after startAt fires.
            popUntil: t0 + delay + 340,
          });
        } else {
          e.tx = loc.lx; e.ty = loc.ly; e.ts = 1; e.to = 1; e.lobe = l.id; e.removing = false;
        }
      });
    });
    pos.current.forEach((e, id) => { if (!present.has(id)) { e.removing = true; e.ts = 0; e.to = 0; } });
    if (!running.current) { running.current = true; raf.current = requestAnimationFrame(loop); }
    // eslint-disable-next-line
  }, [sig]);

  function loop() {
    let active = false;
    const now = (typeof performance !== "undefined" ? performance.now() : 0);
    pos.current.forEach((e, id) => {
      // Cascade gate — hold the dot at the centre, invisible, until its
      // scheduled startAt. Keep the loop active so we re-check next frame.
      if (e.startAt && now < e.startAt) { active = true; return; }

      // Pop window — temporarily aim past the final scale so the dot
      // overshoots to ~1.18 then settles to 1.0 once the window closes.
      const ts = (e.popUntil && now < e.popUntil) ? 1.18 : 1;

      e.x += (e.tx - e.x) * 0.18;
      e.y += (e.ty - e.y) * 0.18;
      e.s += (ts - e.s) * 0.22;
      e.o += (e.to - e.o) * 0.20;
      if (
        Math.abs(e.tx - e.x) > 0.4 ||
        Math.abs(e.ty - e.y) > 0.4 ||
        Math.abs(ts - e.s) > 0.01 ||
        Math.abs(e.to - e.o) > 0.01
      ) active = true;
      if (e.removing && e.o < 0.03) pos.current.delete(id);
    });
    setTick((t) => t + 1);
    if (active) raf.current = requestAnimationFrame(loop); else running.current = false;
  }

  const W = size.w, H = size.h;
  if (!W || !H) return null;
  const fracs = lobePositions(lobes, W, H);
  const centers = {};
  lobes.forEach((l) => {
    const f = fracs[l.id] || { x: 0.5, y: 0.5 };
    centers[l.id] = { x: f.x * W, y: f.y * H };
  });
  // Core sits on the same vertical centre as the lobe ring (which is
  // biased downward by lobePositions to clear the header chrome).
  const cy = fracs.__cy != null ? fracs.__cy : 0.5;
  const core = { x: 0.5 * W, y: cy * H };

  // The transform layer is what gets pan/zoom applied. Pointer/wheel
  // handlers live on the OUTER div so a drag started over empty space still
  // counts, and stopPropagation on the NodeDot click prevents drag from
  // hijacking a tap on a dot.
  return (
    <div onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
      onWheel={onWheel} onDoubleClick={resetView}
      style={{ position: "absolute", inset: 0, overflow: "hidden", touchAction: "none",
        cursor: drag.current ? "grabbing" : "grab" }}>
      <div style={{ position: "absolute", inset: 0,
        transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: "50% 50%",
        transition: drag.current ? "none" : "transform .22s ease-out", willChange: "transform" }}>
        {/* Just the pulse at the core — no spokes, no ARNIE text.
            The minimal silhouette reads as "thinking centre", and the
            dots gravitating around it tell the rest of the story. */}
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
          <circle cx={core.x} cy={core.y} r="3" fill={theme.hub} />
          <circle cx={core.x} cy={core.y} r="3" fill="none" stroke={theme.known} strokeOpacity="0.35">
            <animate attributeName="r" values="3;20;3" dur="5s" repeatCount="indefinite" />
            <animate attributeName="stroke-opacity" values="0.35;0;0.35" dur="5s" repeatCount="indefinite" />
          </circle>
        </svg>

        {lobes.map((l, li) => {
          const c = centers[l.id];
          const entries = l.nodes.map((n) => ({ node: n, e: pos.current.get(n.id) })).filter((x) => x.e);
          const confirmedCount = l.nodes.filter((n) => n.state === "confirmed").length;
          // Lobe label = the cluster's "section title". Matches the
          // dashboard's .stitle (Day tab) typography exactly:
          // Geist Mono, 10.5px, weight 500, color var(--mu), uppercase,
          // letter-spacing .10em. A monospace count sits to the right of
          // the label like "NUTRITION  4/6" — confirmed over total —
          // mirroring the way the Day tab's macro/food/workout sections
          // surface a tiny status next to each title.
          return (
            <div key={l.id} className={FLOATS[li % FLOATS.length]}
              style={{ position: "absolute", left: c.x - HALF, top: c.y - HALF, width: HALF * 2, height: HALF * 2 }}>
              {/* Clickable lobe label — opens the insights panel for this
                  cluster. stopPropagation on pointerdown keeps the drag/pan
                  handler from swallowing the tap. */}
              <button onClick={(ev) => { ev.stopPropagation(); onSelectLobe && onSelectLobe(l.id); }}
                onPointerDown={(ev) => ev.stopPropagation()}
                style={{ position: "absolute", left: HALF, top: -6, transform: "translate(-50%,-100%)",
                  display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap",
                  border: "none", background: "transparent", padding: "4px 8px", margin: "-4px -8px",
                  borderRadius: 8, cursor: "pointer", pointerEvents: "auto",
                  transition: "background .18s" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = theme.ctrlBg; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
                <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10.5, fontWeight: 500,
                  letterSpacing: "0.10em", textTransform: "uppercase", color: theme.subText }}>{l.short}</span>
                <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10, fontWeight: 500,
                  letterSpacing: "0.04em", color: theme.subText, opacity: 0.55 }}>{confirmedCount}/{l.nodes.length}</span>
              </button>
              {entries.map(({ node, e }) => (
                <NodeDot key={node.id} node={node} e={e} theme={theme}
                  sel={selectedId === node.id} fresh={freshId === node.id} freshTick={freshTick} onSelect={onSelect} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
window.BrainConstellationLive = BrainConstellationLive;

// ── List view ───────────────────────────────────────────────────────────────
function stateColor(state, theme) {
  return state === "learning" ? theme.learning : state === "inferred" ? theme.inferred : theme.known;
}
function Dot({ state, theme }) {
  const col = stateColor(state, theme);
  const filled = state === "confirmed";
  return <span style={{ width: 8, height: 8, borderRadius: "50%", flex: "none", marginTop: 8,
    background: filled ? col : "transparent", border: filled ? "none" : `1.4px solid ${col}`,
    animation: state === "learning" ? "lvPulse 2.8s ease-in-out infinite" : "none" }}></span>;
}
// Snake-case a label for the tabulated list view so it reads as a backend
// data key ("Coaching style" -> "coaching_style"). Preserves alphanumerics
// and dashes; collapses everything else to underscores.
function tableKey(s) {
  return String(s || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function ListRow({ node, theme, fresh, first }) {
  // Tabulated, backend-style row: fixed-width mono key on the left,
  // value/chips column flexing in the middle, tight state dot on the
  // right. No padding inflation, single 1px divider, no card chrome.
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "7px 0",
      borderTop: first ? "none" : `1px solid ${theme.listDivider}`,
      background: fresh ? theme.freshWash : "transparent",
      transition: "background 1.4s ease", minHeight: 26 }}>
      <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 11, fontWeight: 500,
        letterSpacing: "0.02em", color: theme.subText, flex: "0 0 38%", minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {tableKey(node.label)}
      </div>
      {node.chips ? (
        <div style={{ flex: "1 1 auto", minWidth: 0, textAlign: "right",
          fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 11.5, fontWeight: 500,
          letterSpacing: "0.01em", color: theme.rowVal,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {node.chips.join(" · ")}
        </div>
      ) : node.value ? (
        <div style={{ flex: "1 1 auto", minWidth: 0, textAlign: "right",
          fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 11.5, fontWeight: 500,
          letterSpacing: "0.01em", color: theme.rowVal,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          title={node.value}>
          {node.value}
        </div>
      ) : (
        <div style={{ flex: "1 1 auto", textAlign: "right",
          fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 11.5,
          color: theme.subText, opacity: 0.35 }}>—</div>
      )}
      <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
        background: node.state === "confirmed" ? theme.known : "transparent",
        border: node.state === "confirmed" ? "none" : `1.2px solid ${stateColor(node.state, theme)}` }} />
    </div>
  );
}
// Re-bundle exploded chip nodes back under their parent slot for the
// LIST view, so users see one tidy row per parameter ("Training split:
// Chest · Back · Shoulders+traps · …") instead of six rows that read as
// orphans. Constellation and panel still show every chip as its own dot
// — the brain map wants density, but the list wants consolidation.
function consolidateChipNodes(nodes) {
  const out = [];
  const groups = {};
  for (const n of nodes) {
    if (n.parentLabel) {
      const key = n.parentLabel;
      if (groups[key]) {
        groups[key].chips.push(n.label);
        // Promote confirmed state if any sibling is confirmed; learning
        // wins only if every sibling is learning. (Mostly N/A — chips
        // share their parent's state by construction — but defensive.)
        if (n.state === "confirmed") groups[key].state = "confirmed";
      } else {
        const row = { id: "group." + key, label: key, chips: [n.label], state: n.state };
        groups[key] = row;
        out.push(row);
      }
    } else {
      out.push(n);
    }
  }
  return out;
}

function BrainListView({ lobes, theme, freshId }) {
  // Tabulated data view — feels like a tidy stdout / db dump rather than a
  // designed component. Flat section headers with key/count + a thin hairline,
  // no card backgrounds, monospace alignment throughout.
  return (
    <div style={{ maxWidth: 560, margin: "0 auto", padding: "6px 18px 120px",
      fontFamily: "'Geist Mono','SF Mono', monospace" }}>
      {lobes.map((l) => {
        const consolidated = consolidateChipNodes(l.nodes);
        const confirmed = consolidated.filter((n) => n.state === "confirmed").length;
        return (
          <div key={l.id} style={{ marginBottom: 18 }}>
            {/* Flat section header row: KEY  count/total ───────── */}
            <div style={{ display: "flex", alignItems: "baseline", gap: 10,
              padding: "16px 0 6px", borderBottom: `1px solid ${theme.listDivider}` }}>
              <span style={{ fontSize: 10.5, fontWeight: 500, letterSpacing: "0.18em",
                textTransform: "uppercase", color: theme.secLabel }}>
                {tableKey(l.name)}
              </span>
              <span style={{ flex: 1, height: 1 }} />
              <span style={{ fontSize: 9.5, fontWeight: 500, letterSpacing: "0.06em",
                color: theme.subText, opacity: 0.6 }}>
                {confirmed}/{consolidated.length}
              </span>
            </div>
            {/* Rows */}
            <div>
              {consolidated.map((n, i) => (
                <ListRow key={n.id} node={n} theme={theme} fresh={freshId === n.id} first={i === 0} />
              ))}
            </div>
          </div>
        );
      })}
      {/* Legend — flat mono row matching the table aesthetic */}
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", justifyContent: "flex-start",
        marginTop: 28, paddingTop: 14, borderTop: `1px solid ${theme.listDivider}`,
        fontSize: 9.5, fontWeight: 500, letterSpacing: "0.06em", color: theme.subText, opacity: 0.65 }}>
        {[["confirmed", "confirmed"], ["inferred", "inferred"], ["learning", "needs_verification"]].map(([st, txt]) => (
          <span key={st} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0,
              background: st === "confirmed" ? theme.known : "transparent",
              border: st === "confirmed" ? "none" : `1.2px solid ${stateColor(st, theme)}` }}></span>
            {txt}
          </span>
        ))}
      </div>
    </div>
  );
}
window.BrainListView = BrainListView;
"""


# ── Live data adapter + diffing + App shell ─────────────────────────────────
_APP_JS = r"""
// Order of standard categories in the constellation. Lobes whose nodes array
// is empty after adapting are dropped (e.g. a brand-new user with no mental
// attributes yet won't show an empty "Mental" lobe).
//
// `coaching` describes how parameters in this lobe influence Arnie's
// behaviour — shown in the lobe-insights panel that opens when the user taps
// the lobe label.
const LOBE_ORDER = [
  { id: "demographics", name: "Demographics", short: "DEMOGRAPHICS",
    coaching: "Baseline for every calculation Arnie runs. BMR, daily calorie target, macro splits, and progress comparisons all use these numbers. When a value changes (you log a new weight, update height) Arnie re-derives targets in the background." },
  { id: "goals", name: "Goals & targets", short: "GOALS",
    coaching: "The anchor for every recommendation. Surplus/deficit, macro split, training emphasis, and progress feedback all derive from your stated goal. Targets here override anything Arnie infers from patterns." },
  { id: "nutrition", name: "Nutrition", short: "NUTRITION",
    coaching: "Drives meal suggestions, macro reminders, and food substitutions. Arnie uses your staples + avoidances to recommend foods you'll actually eat, flag patterns (e.g. low fibre days), and pace nudges when you're under or over target." },
  { id: "fitness", name: "Fitness", short: "FITNESS",
    coaching: "Shapes workout pacing, exercise selection, and progressive-overload guidance. Arnie picks reps/loads that match your training experience and respects the recovery rhythm of your split." },
  { id: "health", name: "Health", short: "HEALTH",
    coaching: "Informs supplement timing, training modifications around injuries, and recovery-aware intensity. When HRV or sleep dips, Arnie pulls back volume; he steers around your limitations rather than asking you to push through." },
  { id: "behavior", name: "Behavior", short: "BEHAVIOR",
    coaching: "Tunes Arnie's tone, accountability cadence, and how directly he pushes vs supports. Confirmed preferences here set the default voice of every check-in." },
  { id: "lifestyle", name: "Lifestyle", short: "LIFESTYLE",
    coaching: "Calibrates timing — when nudges land, how recovery advice adapts to your sleep schedule, and how Arnie suggests workout windows that fit your routine instead of fighting it." },
  { id: "mental", name: "Mental", short: "MENTAL",
    coaching: "Shapes how Arnie supports motivation dips, plateau anxieties, and setbacks. He reframes rather than lectures when these signals show up." },
  { id: "custom", name: "Custom tracking", short: "CUSTOM",
    coaching: "Bespoke parameters you've added or Arnie has noticed from your logs. He weaves these into specific check-ins and tailored recommendations." },
];

// confidence value -> mindmap state
function confState(c) {
  if (c === "confirmed") return "confirmed";
  if (c === "needs_verification") return "learning";
  return "inferred";
}

// Simulation hook — when ?sim=health is set on the page URL, the Health
// lobe gets a realistic mock supplement stack + peptide stack injected
// after the real data lands. Lets us preview a packed lobe without
// touching the user's actual profile. Off by default.
const SIM_HEALTH = (() => {
  try { return new URLSearchParams(window.location.search).get("sim") === "health"; }
  catch (e) { return false; }
})();
const SIM_SUPPLEMENTS = [
  "Creatine 5g", "Fish oil 2g", "Vitamin D 5000IU",
  "Magnesium glycinate 400mg", "Multivitamin", "NMN 500mg",
  "Taurine 1g", "L-citrulline 6g", "Ashwagandha 600mg",
];
const SIM_PEPTIDES = [
  "BPC-157 250mcg", "TB-500 500mcg", "Ipamorelin 200mcg",
  "CJC-1295 100mcg", "MK-677 10mg",
];

// Adapt /api/profile/{token} response into [{id,name,short,nodes:[...]}, ...].
// Unfilled standard slots show as "still learning" pulsing nodes; custom
// attributes append to the same lobe as their category. The DEMOGRAPHICS
// lobe is sourced from data.basics (user-entered scalars like name, age,
// sex, height, current weight) rather than from learned attributes — these
// are always treated as `confirmed` because the user typed them in.
function profileToLobes(data) {
  const std = (data && data.standard) || {};
  const custom = (data && data.custom) || [];
  const basics = (data && data.basics) || [];

  const customByCat = {};
  custom.forEach((c) => {
    const k = ((c.category) || "custom").toLowerCase();
    (customByCat[k] = customByCat[k] || []).push(c);
  });

  // Pre-build the demographics nodes from data.basics. Each entry is
  // {label, value, edit_field, raw} — we treat them as always-confirmed.
  const demoNodes = basics.map((b, i) => ({
    id: "demographics.b." + (b.edit_field || b.label || ("basic" + i)),
    label: b.label,
    value: b.value,
    state: "confirmed",
  }));

  const lobes = [];
  LOBE_ORDER.forEach((lobe) => {
    if (lobe.id === "demographics") {
      if (demoNodes.length) lobes.push({ ...lobe, nodes: demoNodes });
      return;
    }
    const slots = std[lobe.id] || [];
    const customs = customByCat[lobe.id] || [];
    const nodes = [];

    // Sentence-case a chip label so "chest" reads as "Chest" and
    // "lat-biased pulldown" as "Lat-biased pulldown". Doesn't touch
    // mid-word casing — values like "DEXA" or "B12" stay intact.
    const sentenceCase = (s) => {
      const v = String(s || "").trim();
      if (!v) return v;
      return v.charAt(0).toUpperCase() + v.slice(1);
    };

    // Helper: turn a single slot/attribute with chips into individual
    // per-chip nodes. A "Supplements" slot with 5 items becomes 5 dots,
    // each labeled by its item ("Fish oil", "Vitamin D", …) so the
    // constellation actually shows the count of things Arnie knows
    // rather than collapsing them under one parent.
    const explodeChips = (idPrefix, parentLabel, chips, st) =>
      chips.map((chip, j) => ({
        id: idPrefix + ".chip." + j,
        label: sentenceCase(chip),
        parentLabel: parentLabel,
        state: st,
      }));

    // Bullet-delimited string values (e.g. "6-day rotation: chest · back ·
    // shoulders+traps · arms · legs · repeat") are LISTS dressed up as a
    // single string. Detect that pattern and explode each part into its
    // own node. Heuristic: split on " · ", require >= 2 parts, all of
    // reasonable length (<= 50 chars each). Optional short "Header: "
    // prefix is stripped so we don't glue the heading onto the first part.
    function asBulletList(value) {
      if (!value) return null;
      let body = String(value);
      const m = body.match(/^([^:\n]{1,30}):\s*(.+)$/);
      if (m) body = m[2];
      const parts = body.split(/\s+·\s+/).map((p) => p.trim()).filter(Boolean);
      if (parts.length < 2) return null;
      if (parts.some((p) => p.length > 50)) return null;
      return parts;
    }

    slots.forEach((s, i) => {
      const nid = lobe.id + ".s." + (s.key || s.label || ("slot" + i));
      if (s.filled) {
        if (s.chips && s.chips.length) {
          nodes.push(...explodeChips(nid, s.label, s.chips, confState(s.confidence)));
        } else {
          const parts = asBulletList(s.value);
          if (parts) {
            nodes.push(...explodeChips(nid, s.label, parts, confState(s.confidence)));
          } else {
            nodes.push({ id: nid, label: s.label, value: s.value || "", state: confState(s.confidence) });
          }
        }
      } else {
        // Unfilled slot — no placeholder text. The orange ring on the dot
        // and the state badge already communicate "still learning". Adding
        // a literal "still learning..." string just added noise to every
        // half-empty lobe panel.
        nodes.push({ id: nid, label: s.label, state: "learning" });
      }
    });
    customs.forEach((c, i) => {
      const nid = lobe.id + ".c." + (c.key || c.label || ("cust" + i));
      if (c.chips && c.chips.length) {
        nodes.push(...explodeChips(nid, c.label, c.chips, confState(c.confidence)));
      } else {
        const parts = asBulletList(c.value);
        if (parts) {
          nodes.push(...explodeChips(nid, c.label, parts, confState(c.confidence)));
        } else {
          nodes.push({ id: nid, label: c.label, value: c.value || "", state: confState(c.confidence) });
        }
      }
    });

    if (nodes.length) lobes.push({ ...lobe, nodes });
  });

  // Drop any custom-categories that didn't match a standard lobe -> stuff them
  // into the Custom lobe at the end.
  const knownIds = new Set(LOBE_ORDER.map((l) => l.id));
  const leftover = [];
  Object.keys(customByCat).forEach((k) => {
    if (knownIds.has(k)) return;
    customByCat[k].forEach((c, i) => {
      const nid = "other.c." + (c.key || c.label || ("cust" + i));
      if (c.chips && c.chips.length) {
        c.chips.forEach((chip, j) => leftover.push({
          id: nid + ".chip." + j, label: chip, parentLabel: c.label,
          state: confState(c.confidence),
        }));
      } else {
        leftover.push({ id: nid, label: c.label, value: c.value || "", state: confState(c.confidence) });
      }
    });
  });
  if (leftover.length) {
    const existing = lobes.find((l) => l.id === "custom");
    if (existing) existing.nodes = existing.nodes.concat(leftover);
    else lobes.push({ id: "custom", name: "Custom", short: "CUSTOM", nodes: leftover });
  }

  // Simulation injection — only on ?sim=health
  if (SIM_HEALTH) {
    let health = lobes.find((l) => l.id === "health");
    if (!health) {
      const meta = LOBE_ORDER.find((l) => l.id === "health");
      health = { ...meta, nodes: [] };
      lobes.push(health);
    }
    SIM_SUPPLEMENTS.forEach((s, i) => {
      health.nodes.push({
        id: "sim.supp." + i, label: s, parentLabel: "Supplements", state: "confirmed",
      });
    });
    SIM_PEPTIDES.forEach((p, i) => {
      health.nodes.push({
        id: "sim.pep." + i, label: p, parentLabel: "Peptides", state: "confirmed",
      });
    });
  }

  return lobes;
}

// Diff two adapted snapshots; returns events to feed the toast/fresh pipeline.
// Used only to surface what changed since the last poll.
function diffLobes(prev, next) {
  const events = [];
  const idx = (snap) => {
    const m = {};
    snap.forEach((l) => l.nodes.forEach((n) => { m[n.id] = { lobe: l.id, node: n }; }));
    return m;
  };
  const a = idx(prev || []), b = idx(next || []);
  for (const id in b) {
    const nx = b[id], pv = a[id];
    if (!pv) {
      events.push({ t: "add", lobe: nx.lobe, id, label: nx.node.label, value: nx.node.value });
    } else if (pv.node.state !== nx.node.state) {
      if (nx.node.state === "confirmed") events.push({ t: "promote", id, label: nx.node.label, value: nx.node.value });
      else if (nx.node.state === "learning") events.push({ t: "refine", id, label: nx.node.label, value: nx.node.value });
      else events.push({ t: "refine", id, label: nx.node.label, value: nx.node.value });
    } else {
      const va = JSON.stringify(pv.node.value || pv.node.chips || "");
      const vb = JSON.stringify(nx.node.value || nx.node.chips || "");
      if (va !== vb) events.push({ t: "refine", id, label: nx.node.label, value: nx.node.value });
    }
  }
  return events;
}

// ── App shell ──────────────────────────────────────────────────────────────
const { useState, useEffect, useRef } = React;

// Insights panel — what every parameter in this lobe is + how Arnie uses
// them. Slides in from the right on desktop, becomes a bottom sheet on
// mobile (max-width handles the breakpoint via min(420px, calc(100vw-32px))).
function LobeInsightsPanel({ lobe, theme, onClose, stateMeta, stateCol }) {
  const open = !!lobe;
  // Mount the panel even when closed so the slide-out transition reads.
  const lockRef = useRef(null);
  if (open && lobe) lockRef.current = lobe;          // remember the last lobe
  const shown = lockRef.current;
  const confirmedCount = shown ? shown.nodes.filter((n) => n.state === "confirmed").length : 0;
  const learningCount = shown ? shown.nodes.filter((n) => n.state === "learning").length : 0;

  // ── AI-generated coaching insight ──────────────────────────────────────
  // Hits /api/brain/insights/{token} when the panel opens for a new lobe.
  // While the request is in flight we show a subtle "Arnie's thinking..."
  // state; on success we fade in his actual prose over the static fallback.
  // Cached by lobe id for this session so re-opening is instant.
  const insightCache = useRef({});
  const [insight, setInsight] = useState(null);   // { text, generated_at }
  const [thinking, setThinking] = useState(false);
  useEffect(() => {
    if (!open || !lobe) return;
    if (insightCache.current[lobe.id]) {
      setInsight(insightCache.current[lobe.id]);
      setThinking(false);
      return;
    }
    setInsight(null);
    setThinking(true);
    const url = window.BRAIN_PROFILE_URL.replace("/api/profile/", "/api/brain/insights/");
    fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lobe_id: lobe.id, lobe_name: lobe.name, lobe_short: lobe.short,
        nodes: lobe.nodes.map((n) => ({
          label: n.label, state: n.state,
          value: n.value, chips: n.chips,
        })),
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data && data.ok && data.insight) {
          const rec = { text: data.insight, generated_at: data.generated_at, cached: data.cached };
          insightCache.current[lobe.id] = rec;
          setInsight(rec);
        }
      })
      .catch(() => {})
      .finally(() => setThinking(false));
  }, [open, lobe && lobe.id]);

  return (
    <>
      {/* Backdrop */}
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 28,
        background: open ? (theme.name === "dark" ? "rgba(8,12,18,0.55)" : "rgba(40,55,70,0.18)") : "transparent",
        backdropFilter: open ? "blur(2px)" : "none",
        opacity: open ? 1 : 0, transition: "opacity .26s ease, backdrop-filter .26s ease",
        pointerEvents: open ? "auto" : "none" }} />

      {/* Panel — compact list view, modeled on the original Arnie's brain
          section from the Profile tab. `position: fixed` anchored via an
          explicit left calc so the math is unambiguous — `right: 0` was
          landing the panel off-viewport in this iframe context. */}
      <div style={{ position: "fixed", top: 0, left: "max(0px, calc(100vw - 400px))", bottom: 0, right: 0, zIndex: 30,
        background: theme.cardBg, borderLeft: `1px solid ${theme.cardBorder}`,
        boxShadow: open ? "-24px 0 48px -24px rgba(0,0,0,0.5)" : "none",
        backdropFilter: "blur(14px)",
        transform: `translateX(${open ? 0 : 100}%)`, transition: "transform .32s cubic-bezier(.4,0,.2,1)",
        display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {shown && (
          <>
            {/* Compact header: lobe name + count + close, all in one row */}
            <div style={{ padding: "14px 16px 12px", borderBottom: `1px solid ${theme.cardBorder}`,
              display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: theme.known,
                flexShrink: 0, boxShadow: `0 0 6px ${theme.known}55` }} />
              <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10.5, fontWeight: 500,
                letterSpacing: "0.10em", textTransform: "uppercase", color: theme.subText, flex: 1, minWidth: 0,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {shown.short}
              </span>
              <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10, fontWeight: 500,
                letterSpacing: "0.04em", color: theme.subText, opacity: 0.65, flexShrink: 0 }}>
                {confirmedCount}/{shown.nodes.length}
              </span>
              <button onClick={onClose} aria-label="Close" style={{
                width: 22, height: 22, borderRadius: 6, border: "none", background: "transparent",
                color: theme.iconText, cursor: "pointer", flexShrink: 0,
                display: "grid", placeItems: "center", fontSize: 15, lineHeight: 1, opacity: 0.55, padding: 0 }}>×</button>
            </div>

            {/* Body — scrollable */}
            <div style={{ overflowY: "auto", flex: 1, padding: "4px 0 18px" }}>
              {/* Parameter list — tight rows, no card wrapper. Each row is
                  a thin div with label on the left, value on the right, and
                  a tiny confidence dot at the far right (matches the
                  original .inrow + .conf-dot pattern). */}
              {shown.nodes.map((n, i) => {
                const hasValue = (n.chips && n.chips.length) || (n.value && n.value.length);
                const prev = i > 0 ? shown.nodes[i - 1] : null;
                const next = i < shown.nodes.length - 1 ? shown.nodes[i + 1] : null;
                // Group bookkeeping — when does this row start/end a parent
                // group, and how many items are in the group? The visual
                // treatment depends on these (left rail, group header, count).
                const isNewGroup = n.parentLabel && (!prev || prev.parentLabel !== n.parentLabel);
                const isGroupEnd = n.parentLabel && (!next || next.parentLabel !== n.parentLabel);
                let groupSize = 0;
                if (n.parentLabel) {
                  for (const m of shown.nodes) if (m.parentLabel === n.parentLabel) groupSize++;
                }
                const railColor = `rgba(${theme.name === "dark" ? "0,230,118" : "5,150,105"},0.32)`;
                const railBg = `rgba(${theme.name === "dark" ? "255,255,255,0.018" : "0,0,0,0.018"})`;
                return (
                  <React.Fragment key={n.id}>
                    {isNewGroup && (
                      <div style={{ padding: "14px 14px 6px",
                        display: "flex", alignItems: "center", gap: 10 }}>
                        {/* Group header label + count badge */}
                        <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 9.5, fontWeight: 500,
                          letterSpacing: "0.10em", textTransform: "uppercase", color: theme.subText, opacity: 0.85 }}>
                          {n.parentLabel}
                        </span>
                        <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 9, fontWeight: 500,
                          letterSpacing: "0.04em", color: theme.subText, opacity: 0.5 }}>
                          {groupSize}
                        </span>
                        <span style={{ flex: 1, height: 1, background: theme.cardBorder, opacity: 0.6 }} />
                      </div>
                    )}
                    <div style={{ position: "relative", display: "flex", alignItems: "baseline", gap: 12,
                      padding: n.parentLabel ? "5px 14px 5px 24px" : "10px 14px",
                      background: n.parentLabel ? railBg : "transparent",
                      borderBottom: (i === shown.nodes.length - 1 || (isGroupEnd && next && !next.parentLabel)) ? "none"
                        : (n.parentLabel && next && next.parentLabel === n.parentLabel) ? "none"
                        : `1px solid ${theme.cardBorder}` }}>
                      {/* Left accent rail — visible only on rows inside a
                          parent group. Stops just before the next group/row. */}
                      {n.parentLabel && (
                        <span style={{ position: "absolute", left: 14, top: isNewGroup ? 0 : -1,
                          bottom: isGroupEnd ? 4 : -1, width: 1.5, borderRadius: 1,
                          background: railColor }} />
                      )}
                      <span style={{ fontFamily: "'Geist', system-ui, sans-serif", fontSize: 12.5, fontWeight: 400,
                        color: theme.subText, flex: "0 0 auto", maxWidth: "45%",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        opacity: hasValue ? 1 : 0.55 }}>
                        {n.label}
                      </span>
                      {n.chips ? (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, justifyContent: "flex-end",
                          flex: "1 1 auto", minWidth: 0 }}>
                          {n.chips.map((c, j) => (
                            <span key={j} style={{ fontFamily: "'Geist', system-ui, sans-serif",
                              fontSize: 11.5, fontWeight: 500, color: theme.rowVal,
                              background: theme.ctrlBg, borderRadius: 5,
                              padding: "1px 7px", whiteSpace: "nowrap" }}>{c}</span>
                          ))}
                        </div>
                      ) : n.value ? (
                        <span style={{ flex: "1 1 auto", minWidth: 0, textAlign: "right",
                          fontFamily: "'Geist', system-ui, sans-serif", fontSize: 12.5, fontWeight: 500,
                          color: theme.rowVal, lineHeight: 1.42, textWrap: "pretty" }}>{n.value}</span>
                      ) : (
                        <span style={{ flex: "1 1 auto" }} />
                      )}
                      <span style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0,
                        background: n.state === "confirmed" ? theme.known : "transparent",
                        border: n.state === "confirmed" ? "none" : `1.2px solid ${stateCol(n.state)}` }} />
                    </div>
                  </React.Fragment>
                );
              })}

              {/* How Arnie uses this — inlined, no nested card. Just a
                  small section caption with the "thinking/live" badge,
                  followed by the prose at quiet body text size. */}
              {(shown.coaching || insight || thinking) && (
                <div style={{ padding: "16px 16px 4px", borderTop: `1px solid ${theme.cardBorder}`,
                  marginTop: 4 }}>
                  <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 9.5, fontWeight: 500,
                    letterSpacing: "0.10em", textTransform: "uppercase", color: theme.subText,
                    margin: "0 0 8px", display: "flex", alignItems: "center", gap: 8 }}>
                    <span>How Arnie uses this</span>
                    {(thinking || insight) && (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
                        <span style={{ width: 5, height: 5, borderRadius: "50%", background: theme.known,
                          boxShadow: `0 0 4px ${theme.known}`,
                          animation: thinking ? "lvThink 1.4s ease-in-out infinite" : "none" }} />
                        <span style={{ fontSize: 9, letterSpacing: "0.06em", textTransform: "none",
                          color: thinking ? theme.subText : theme.known,
                          fontWeight: 500,
                          transition: "color .3s ease" }}>
                          {thinking ? "thinking" : "live"}
                        </span>
                      </span>
                    )}
                  </div>
                  <div style={{ position: "relative", minHeight: 64,
                    fontFamily: "'Geist', system-ui, sans-serif", fontSize: 13, fontWeight: 400,
                    color: theme.cardVal, lineHeight: 1.5, letterSpacing: "-.003em", textWrap: "pretty" }}>
                    {/* Fallback coaching string under-layer. While thinking
                        it stays visible at quiet opacity AND gets a soft
                        horizontal shimmer to read as "loading". When the
                        AI insight arrives the fallback fades to 0 over
                        the same .3s window the insight fades in over. */}
                    <span className={thinking ? "lvShimmer" : ""}
                      style={{
                        opacity: insight ? 0 : (thinking ? 0.62 : 0.92),
                        transition: "opacity .35s ease",
                        position: insight ? "absolute" : "static",
                        inset: insight ? 0 : "auto",
                        display: "block",
                        color: thinking ? "transparent" : theme.cardVal,
                        WebkitTextFillColor: thinking ? "transparent" : "currentColor",
                      }}>
                      {shown.coaching}
                    </span>
                    {insight && (
                      <span style={{
                        opacity: 1,
                        transition: "opacity .55s ease",
                        display: "block",
                        color: theme.cardVal, opacity: 0.95,
                      }}>
                        {insight.text}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}

function App() {
  const THEMES = window.BRAIN_THEMES;

  // Theme resolution order:
  //   1. ?theme=dark|light URL param (set by the dashboard on iframe mount)
  //   2. parent dashboard's localStorage (when embedded same-origin)
  //   3. our own last pref
  //   4. dark
  const initialMode = (function () {
    try {
      const u = new URL(window.location.href);
      const q = u.searchParams.get("theme");
      if (q === "dark" || q === "light") return q;
    } catch (e) {}
    const dash = localStorage.getItem("arnie-theme");
    if (dash === "dark" || dash === "light") return dash;
    return localStorage.getItem("arnie.mode") || "dark";
  })();
  const [mode, setMode] = useState(initialMode);
  const [view, setView] = useState(() => localStorage.getItem("arnie.view") || "brain");

  // Live theme sync — dashboard pushes {type:'arnie-brain-theme', mode}.
  useEffect(() => {
    function onMsg(e) {
      const d = e && e.data;
      if (!d || d.type !== "arnie-brain-theme") return;
      if (d.mode === "dark" || d.mode === "light") setMode(d.mode);
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const [lobes, setLobes] = useState([]);
  const [usingSample, setUsingSample] = useState(false);
  const [freshId, setFreshId] = useState(null);
  const [freshTick, setFreshTick] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedLobeId, setSelectedLobeId] = useState(null);
  const [toast, setToast] = useState(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  const rootRef = useRef(null);
  const prevSnapshot = useRef(null);
  const sampleIdx = useRef(0);
  const toastTimer = useRef(null);
  const theme = THEMES[mode];

  useEffect(() => { localStorage.setItem("arnie.mode", mode); }, [mode]);
  // Expose the theme accent + shimmer tints as CSS variables so the
  // keyframe animations defined in <style> can reference them.
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--lv-known", THEMES[mode].known);
    root.style.setProperty("--lv-shimmer", mode === "dark" ? "rgba(255,255,255,0.16)" : "rgba(40,55,70,0.22)");
  }, [mode]);
  useEffect(() => { localStorage.setItem("arnie.view", view); }, [view]);

  // measure the stage so the constellation knows its canvas
  useEffect(() => {
    const measure = () => {
      const el = rootRef.current; if (!el) return;
      const r = el.getBoundingClientRect();
      setSize({ w: r.width, h: r.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (rootRef.current) ro.observe(rootRef.current);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, []);

  function showToast(t) {
    if (!t) return;
    setToast(t);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3800);
  }

  function flashFresh(id) {
    setFreshId(id);
    setFreshTick((t) => t + 1);
    setTimeout(() => setFreshId((f) => (f === id ? null : f)), 3400);
  }

  // ── Live data poll ────────────────────────────────────────────────────────
  // Poll /api/profile/{token} every 20s. First fetch decides sample vs live.
  // Subsequent fetches diff against the previous snapshot to emit events.
  useEffect(() => {
    let cancelled = false;
    async function pull() {
      try {
        const r = await fetch(window.BRAIN_PROFILE_URL, { cache: "no-store" });
        if (!r.ok) throw new Error("status " + r.status);
        const data = await r.json();
        const next = profileToLobes(data);
        if (cancelled) return;
        if (!next.length) {
          // Empty profile -> fall back to the sample stream so the page
          // always feels alive, even for a brand-new user.
          if (!usingSample) {
            setUsingSample(true);
            setLobes(window.BRAIN_SAMPLE_LOBES.map((l) => ({ ...l, nodes: l.nodes.map((n) => ({ ...n })) })));
            prevSnapshot.current = null;
          }
          return;
        }
        // Live data arrived. If we were in sample mode, swap to live.
        if (usingSample) {
          setUsingSample(false);
          setLobes(next);
          prevSnapshot.current = next;
          return;
        }
        const events = diffLobes(prevSnapshot.current, next);
        prevSnapshot.current = next;
        setLobes(next);
        if (events.length) {
          const ev = events[0];
          flashFresh(ev.id);
          showToast({
            label: ev.t === "add" ? "Arnie noticed something new"
                 : ev.t === "promote" ? "Arnie confirmed your"
                 : "Arnie updated your",
            text: ev.label || ev.id,
          });
        }
      } catch (e) {
        // Quietly tolerate network blips; the next poll will retry.
        console.warn("brain poll failed:", e);
      }
    }
    pull();
    const iv = setInterval(pull, 20000);
    return () => { cancelled = true; clearInterval(iv); };
  }, [usingSample]);

  // ── Sample event ticker (only while we have no live data) ────────────────
  useEffect(() => {
    if (!usingSample) return;
    const iv = setInterval(() => {
      const ev = window.BRAIN_SAMPLE_EVENTS[sampleIdx.current % window.BRAIN_SAMPLE_EVENTS.length];
      sampleIdx.current += 1;
      setLobes((prev) => {
        const res = window.applySampleEvent(prev, ev);
        flashFresh(res.freshId);
        showToast(res.toast);
        return res.lobes;
      });
    }, 3600);
    return () => clearInterval(iv);
  }, [usingSample]);

  const allNodes = lobes.flatMap((l) => l.nodes.map((n) => ({ ...n, lobe: l.name, lobeId: l.id })));
  const node = selectedId ? allNodes.find((n) => n.id === selectedId) : null;
  const total = allNodes.length;
  const stateMeta = (st) => st === "learning" ? "needs verification" : st === "inferred" ? "inferred from patterns" : "confirmed";
  const stateCol = (st) => st === "learning" ? theme.learning : st === "inferred" ? theme.inferred : theme.known;

  return (
    <div ref={rootRef} style={{ position: "relative", height: "100%", background: theme.stageBg,
      transition: "background .5s ease", overflow: "hidden" }}>

      {view === "brain" ? (
        <window.BrainConstellationLive lobes={lobes} theme={theme} freshId={freshId} freshTick={freshTick}
          selectedId={selectedId} onSelect={setSelectedId}
          onSelectLobe={(id) => setSelectedLobeId((prev) => prev === id ? null : id)}
          size={size} />
      ) : (
        <div className="brain-list" style={{ position: "absolute", inset: 0, overflow: "auto", paddingTop: 92 }}>
          <window.BrainListView lobes={lobes} theme={theme} freshId={freshId} />
        </div>
      )}

      {/* In-iframe header — minimal and matched to the Day tab's section
          title typography (.stitle): Geist Mono, 10.5px, weight 500,
          letter-spacing .10em, uppercase, color var(--mu).  The dashboard's
          pagehead carries the page title; here we just surface the
          parameter count + view toggle. */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, zIndex: 20, padding: "18px 22px 12px",
        display: "flex", alignItems: "center", gap: 12, pointerEvents: "none",
        background: view === "list" ? `linear-gradient(${mode === "dark" ? "#0a110fcc" : "#ffffffcc"}, transparent)` : "none",
        backdropFilter: view === "list" ? "blur(2px)" : "none" }}>
        <div style={{ pointerEvents: "auto", flexShrink: 0, display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ position: "relative", width: 6, height: 6, borderRadius: "50%", background: theme.known }}>
            <span className="lvRipple" key={freshTick} style={{ position: "absolute", inset: -3, borderRadius: "50%", border: `1px solid ${theme.known}` }}></span>
          </span>
          <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10.5, fontWeight: 500,
            letterSpacing: "0.10em", textTransform: "uppercase", color: theme.subText, whiteSpace: "nowrap" }}>
            {total} parameters {usingSample ? "· demo stream" : "· learning live"}
          </span>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, pointerEvents: "auto" }}>
          <div style={{ display: "flex", background: theme.ctrlBg, borderRadius: 8, padding: 2,
            border: `1px solid ${theme.cardBorder}` }}>
            {["brain", "list"].map((v) => (
              <button key={v} onClick={() => setView(v)} style={{
                border: "none", cursor: "pointer", borderRadius: 6, padding: "5px 11px",
                fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10, fontWeight: 500,
                letterSpacing: "0.08em", textTransform: "uppercase",
                background: view === v ? theme.ctrlActiveBg : "transparent",
                color: view === v ? theme.ctrlActiveText : theme.ctrlText, transition: "all .2s" }}>{v}</button>
            ))}
          </div>
        </div>
      </div>

      <div style={{ position: "absolute", top: 88, left: "50%", transform: `translateX(-50%) translateY(${toast ? 0 : -14}px)`,
        zIndex: 25, opacity: toast ? 1 : 0, transition: "all .4s cubic-bezier(.2,.9,.2,1)", pointerEvents: "none",
        display: "flex", alignItems: "center", gap: 9, padding: "8px 14px", borderRadius: 999,
        background: theme.cardBg, border: `1px solid ${theme.cardBorder}`, backdropFilter: "blur(10px)",
        boxShadow: "0 10px 30px -12px rgba(0,0,0,0.4)" }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: theme.known, boxShadow: `0 0 8px ${theme.known}` }}></span>
        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10.5, letterSpacing: "0.02em", color: theme.subText }}>
          {toast && toast.label}
        </span>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: theme.cardVal }}>{toast && toast.text}</span>
      </div>

      {view === "brain" && !node && (
        <div style={{ position: "absolute", left: 22, bottom: 18, zIndex: 15, display: "flex", flexDirection: "column", gap: 6,
          fontFamily: "'Geist', system-ui, sans-serif", fontSize: 10.5, color: theme.subText, opacity: 0.7,
          lineHeight: 1.4, pointerEvents: "none" }}>
          {[["confirmed", "confirmed"], ["inferred", "inferred from patterns"], ["learning", "needs verification"]].map(([st, txt]) => (
            <span key={st} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0,
                background: st === "confirmed" ? theme.known : "transparent",
                border: st === "confirmed" ? "none" : `1.3px solid ${stateCol(st)}` }}></span>{txt}
            </span>
          ))}
        </div>
      )}

      {/* Lobe insights panel — slides in from the right when a lobe label is
          tapped. Shows every parameter in the cluster + how Arnie uses them
          to shape coaching. Backdrop dims the constellation. */}
      <LobeInsightsPanel lobe={lobes.find((l) => l.id === selectedLobeId)} theme={theme}
        onClose={() => setSelectedLobeId(null)} stateMeta={stateMeta} stateCol={stateCol} />

      {/* Node detail card — slides up from the bottom when a dot is tapped.
          Mirrors the lobe-insights panel's visual rhythm (same radius, same
          backdrop, same .stitle-style mono caption) but compact to one
          parameter. Click outside or the × button to dismiss; the
          "View N parameters →" footer escalates to the full lobe panel. */}
      {view === "brain" && (
        <div onClick={() => setSelectedId(null)} style={{ position: "absolute", left: 16, right: 16, bottom: 24, zIndex: 22,
          display: "flex", justifyContent: "center", pointerEvents: node ? "auto" : "none" }}>
          <div onClick={(e) => e.stopPropagation()} style={{ width: "min(400px, 100%)",
            background: theme.cardBg, border: `1px solid ${theme.cardBorder}`,
            borderRadius: 14, backdropFilter: "blur(14px)", boxShadow: "0 18px 44px -18px rgba(0,0,0,0.5)",
            padding: node ? "14px 16px 12px" : "0 16px",
            maxHeight: node ? 320 : 0, opacity: node ? 1 : 0,
            overflow: "hidden", transition: "all .32s cubic-bezier(.4,0,.2,1)", cursor: "default" }}>
            {node && (
              <>
                {/* Header row: state dot · LOBE (muted mono) · state badge · close ×
                    Lobe stays in the calm subText color so it doesn't fight the
                    value below; state is shown as a coloured badge instead. */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                    background: node.state === "confirmed" ? theme.known : "transparent",
                    border: node.state === "confirmed" ? "none" : `1.4px solid ${stateCol(node.state)}` }}></span>
                  <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10.5, fontWeight: 500,
                    letterSpacing: "0.10em", textTransform: "uppercase", color: theme.subText, flex: 1, minWidth: 0,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{node.lobe}</span>
                  <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 9.5, fontWeight: 500,
                    letterSpacing: "0.06em", color: stateCol(node.state), textTransform: "lowercase",
                    border: `1px solid ${stateCol(node.state)}`, opacity: 0.85,
                    borderRadius: 6, padding: "2px 7px", whiteSpace: "nowrap" }}>{stateMeta(node.state)}</span>
                  <button onClick={() => setSelectedId(null)} aria-label="Close" style={{
                    width: 22, height: 22, borderRadius: 6, border: "none", background: "transparent",
                    color: theme.iconText, cursor: "pointer", display: "grid", placeItems: "center",
                    fontSize: 15, lineHeight: 1, opacity: 0.55, padding: 0, flexShrink: 0 }}>×</button>
                </div>

                {/* Two visual treatments depending on whether this is an
                    exploded chip (parentLabel present) or a regular slot.

                    Exploded chip: the label IS the headline. Show it big
                    (Geist sans, 22/600), then a "Part of TRAINING SPLIT"
                    framing line, then the siblings as inline pills with
                    the current one highlighted — so users see the chip in
                    its full context, not as an orphan word.

                    Regular slot: keep the original label + value rhythm
                    that already reads well for "Experience → Advanced". */}
                {node.parentLabel ? (
                  <>
                    <div style={{ fontFamily: "'Geist', system-ui, sans-serif", fontSize: 22, fontWeight: 600,
                      color: theme.cardVal, lineHeight: 1.2, letterSpacing: "-.012em",
                      marginBottom: 12 }}>{node.label}</div>
                    <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 9.5, fontWeight: 500,
                      letterSpacing: "0.10em", textTransform: "uppercase", color: theme.subText,
                      opacity: 0.7, marginBottom: 8 }}>
                      Part of · {node.parentLabel}
                    </div>
                    {(() => {
                      const parent = lobes.find((l) => l.id === node.lobeId);
                      if (!parent) return null;
                      const siblings = parent.nodes.filter((s) => s.parentLabel === node.parentLabel);
                      if (siblings.length < 2) return null;
                      return (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                          {siblings.map((s, i) => {
                            const isCurrent = s.id === node.id;
                            return (
                              <span key={s.id} style={{
                                fontFamily: "'Geist', system-ui, sans-serif",
                                fontSize: 12.5, fontWeight: isCurrent ? 600 : 500,
                                color: isCurrent ? theme.cardVal : theme.subText,
                                background: isCurrent ? `rgba(${theme.name === "dark" ? "0,230,118" : "5,150,105"},0.14)` : theme.ctrlBg,
                                border: `1px solid ${isCurrent ? theme.known : theme.cardBorder}`,
                                borderRadius: 7, padding: "3px 9px", whiteSpace: "nowrap",
                                transition: "all .18s" }}>{s.label}</span>
                            );
                          })}
                        </div>
                      );
                    })()}
                  </>
                ) : (
                  <>
                    <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 11, fontWeight: 500,
                      letterSpacing: "0.02em", color: theme.cardTitle, marginBottom: 8 }}>{node.label}</div>
                    {node.value ? (
                      <div style={{ fontFamily: "'Geist', system-ui, sans-serif", fontSize: 16, fontWeight: 600,
                        color: theme.cardVal, lineHeight: 1.36, letterSpacing: "-.005em", textWrap: "pretty" }}>{node.value}</div>
                    ) : null}
                  </>
                )}

                {/* Escalation row — opens the full lobe insights panel for this
                    node's lobe. Helps users discover the panel exists. */}
                {node.lobeId && (() => {
                  const parent = lobes.find((l) => l.id === node.lobeId);
                  if (!parent) return null;
                  return (
                    <div style={{ borderTop: `1px solid ${theme.cardBorder}`, marginTop: 12, paddingTop: 10 }}>
                      <button onClick={() => { setSelectedLobeId(node.lobeId); setSelectedId(null); }}
                        style={{ background: "transparent", border: "none", padding: 0, cursor: "pointer",
                          fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10.5, fontWeight: 500,
                          letterSpacing: "0.06em", color: theme.subText, textTransform: "uppercase",
                          display: "inline-flex", alignItems: "center", gap: 6, transition: "color .15s" }}
                        onMouseEnter={(e) => e.currentTarget.style.color = theme.cardVal}
                        onMouseLeave={(e) => e.currentTarget.style.color = theme.subText}>
                        View all {parent.nodes.length} {parent.short.toLowerCase()} parameters
                        <span aria-hidden="true">→</span>
                      </button>
                    </div>
                  );
                })()}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
"""


_PAGE_HEAD = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Arnie's Brain</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500&family=Hanken+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; background: transparent; }
  body { font-family: 'Geist', 'Hanken Grotesk', system-ui, sans-serif; -webkit-font-smoothing: antialiased; letter-spacing: -.005em; }
  #root { height: 100%; background: transparent; }

  @keyframes lvFloatA { 0%,100%{transform:translate(0,0)} 50%{transform:translate(5px,-7px)} }
  @keyframes lvFloatB { 0%,100%{transform:translate(0,0)} 50%{transform:translate(-6px,6px)} }
  @keyframes lvFloatC { 0%,100%{transform:translate(0,0)} 50%{transform:translate(6px,5px)} }
  @keyframes lvFloatD { 0%,100%{transform:translate(0,0)} 50%{transform:translate(-5px,-6px)} }
  @keyframes lvFloatE { 0%,100%{transform:translate(0,0)} 50%{transform:translate(4px,7px)} }
  .lvFloatA{animation:lvFloatA 13s ease-in-out infinite}
  .lvFloatB{animation:lvFloatB 15s ease-in-out infinite}
  .lvFloatC{animation:lvFloatC 12s ease-in-out infinite}
  .lvFloatD{animation:lvFloatD 16s ease-in-out infinite}
  .lvFloatE{animation:lvFloatE 14s ease-in-out infinite}
  @keyframes lvPulse { 0%,100%{opacity:.4} 50%{opacity:1} }
  @keyframes lvRipple { from{transform:scale(.5);opacity:.6} to{transform:scale(2.6);opacity:0} }
  .lvRipple{animation:lvRipple 2.6s ease-out forwards}

  /* Thinking dot: gentle expand/contract with a soft halo. Read as the
     "I'm working on it" pulse beside the live badge in the insights card. */
  @keyframes lvThink {
    0%,100% { transform: scale(1); box-shadow: 0 0 4px var(--lv-known); opacity: .6; }
    50%     { transform: scale(1.55); box-shadow: 0 0 10px var(--lv-known); opacity: 1; }
  }
  /* Shimmer: a soft horizontal light-sweep across the fallback coaching
     text while the AI insight is generating, so the text feels "loading"
     rather than just sitting at half opacity. */
  @keyframes lvShimmer {
    0%   { background-position: -180% 0; }
    100% { background-position: 280% 0; }
  }
  .lvShimmer {
    background-image: linear-gradient(110deg,
      transparent 35%,
      var(--lv-shimmer) 50%,
      transparent 65%);
    background-size: 220% 100%;
    background-repeat: no-repeat;
    -webkit-background-clip: text; background-clip: text;
    animation: lvShimmer 1.8s linear infinite;
  }

  .brain-list::-webkit-scrollbar{width:0}
  .brain-list{scrollbar-width:none}
</style>
</head>
<body>
<div id="root"></div>
"""

_PAGE_LIBS = r"""
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
"""

_PAGE_TAIL = r"""
</body>
</html>
"""


def _brain_html(token: str) -> str:
    """Render the Arnie's Brain page for a given dashboard token."""
    # Only the data-source URL needs token substitution. Everything else is
    # static JS/HTML; assemble by concatenation to keep JSX/template-literal
    # braces and ``$`` characters untouched.
    boot_script = (
        '<script>\n'
        '  // Tell the React app where to fetch live data from.\n'
        f'  window.BRAIN_PROFILE_URL = "/api/profile/{token}";\n'
        '</script>\n'
    )
    return (
        _PAGE_HEAD
        + boot_script
        + _PAGE_LIBS
        + "<script>" + _THEMES_JS + "</script>\n"
        + "<script>" + _SAMPLE_JS + "</script>\n"
        + '<script type="text/babel" data-presets="react">' + _VIEWS_JS + "</script>\n"
        + '<script type="text/babel" data-presets="react">' + _APP_JS + "</script>\n"
        + _PAGE_TAIL
    )
