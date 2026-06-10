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
function lobePositions(lobes, w, h, half) {
  const n = lobes.length;
  if (!n) return {};
  const aspect = (w && h) ? w / h : 1.4;
  // 1 lobe -> tiny ring near centre; 5 -> filling the canvas. Caps at 1.
  const countScale = Math.min(1, 0.40 + n * 0.11);
  let rx = Math.min(0.40, (0.26 + aspect * 0.06)) * countScale;
  let ry = Math.min(0.32, (0.20 + (1 / aspect) * 0.06)) * countScale;
  // Geometric clamp — keep the lobe wrapper (sized HALF*2) fully on-screen
  // by limiting the centre's distance from canvas centre to (W/2 - half - margin).
  // Without this, mobile viewports (W < ~600) would push the wrapper off
  // the left/right edges and clip the lobe labels. On narrow viewports
  // the label is now a pill (~24px wider than naked text), so we widen the
  // horizontal margin so paired lobes don't touch each other at the equator.
  if (w && half) {
    const isPhone = w < 480;
    const marginX = isPhone ? 14 : 10;
    rx = Math.min(rx, Math.max(0.05, (w / 2 - half - marginX) / w));
  }
  if (h && half) {
    // Reserve room for the header strip + lobe label tail. Mobile uses a
    // tighter bottom margin so the southern lobes can edge into the
    // legend hairline — that gentle overlap reads as natural visual
    // continuity instead of a wide empty band at the bottom of the
    // screen.
    const marginY = (w && w < 480) ? 28 : 60;
    ry = Math.min(ry, Math.max(0.05, (h / 2 - half - marginY) / h));
  }
  // Vertical centre shift — pushes the ring down so the top lobe clears
  // the header strip + toast band. Mobile sits a bit lower (62px) so the
  // top lobes feel anchored under the toast and the bottom dot cluster
  // brushes the legend hairline naturally.
  const isPhoneY = w && w < 480;
  const yShift = isPhoneY ? 62 : 38;
  const cy = 0.5 + (h ? yShift / h : 0);
  const res = {};
  // Offset starting angle by half a slice when count is even, so the ring
  // never has a lobe + label sitting under the top header bar. On mobile
  // we additionally nudge the whole ring by a quarter-slice so no two
  // lobes share the same Y — that's what causes pairs like BEHAVIOR /
  // HEALTH to crash into each other horizontally on narrow viewports.
  const phoneTwist = (w && w < 480) ? (Math.PI / (2 * n)) : 0;
  const start = -Math.PI / 2 + (n % 2 === 0 ? Math.PI / n : 0) + phoneTwist;
  lobes.forEach((l, i) => {
    const ang = start + (i * 2 * Math.PI) / n;
    res[l.id] = {
      x: 0.5 + Math.cos(ang) * rx,
      y: cy + Math.sin(ang) * ry,
    };
  });
  // Pair up sibling lobes into tight vertical stacks on the left and
  // right flanks of the constellation. This frees the top + bottom of
  // the ring for the more actionable categories (NUTRITION, FITNESS)
  // and lets the engagement-shaping (THOUGHTS + BEHAVIOR) and
  // contextual (DEMOGRAPHICS + LIFESTYLE) groups read as single zones.
  //
  // Skip the pair overrides on mobile — phone-width viewports don't have
  // the horizontal room for two stacked-pair columns plus a dense central
  // ring without labels piling on each other. On mobile we keep the
  // plain ring layout so each lobe gets its own breathing room.
  const skipPairs = (w && w < 480);
  const stackPair = (topId, bottomId, sideX) => {
    if (skipPairs) return;
    if (!res[topId] || !res[bottomId] || !h || !half) return;
    const offset = (half * 0.55) / h;
    res[topId] = { x: sideX, y: cy - offset };
    res[bottomId] = { x: sideX, y: cy + offset };
  };
  // Calculate flanking x positions — push out toward the edges as far
  // as the geometric clamp allows so the central column (Nutrition,
  // Fitness, Goals) keeps its breathing room. Falls back to .25 / .75
  // (legible third positions) if half/W aren't available yet.
  const flankInset = (w && half) ? (half + 14) / w : 0.18;
  const leftX  = Math.max(0.12, flankInset);
  const rightX = Math.min(0.88, 1 - flankInset);
  // Thoughts lobe id is "custom" (renamed-display only).
  stackPair("custom", "behavior", leftX);
  stackPair("demographics", "lifestyle", rightX);
  // Expose cy so the core pulse follows the same vertical centre.
  res.__cy = cy;
  return res;
}

// Per-lobe node ring. Tight single-ring for sparse lobes; once n > 8 we
// split into two concentric rings (inner + outer) so the cluster reads
// as a small galaxy instead of a cramped wheel. Group consecutive nodes
// with the same parentLabel onto the same ring when possible so each
// chip group reads as a cohesive arc rather than alternating in-out-in.
function layoutLocal(nodes, half, isMobile) {
  if (half == null) half = HALF;
  // Scale internal ring radii proportional to half so dots stay inside
  // the wrapper on smaller (mobile) lobes. Mobile additionally packs
  // dense clusters ~30% tighter so a 30-37 dot lobe (NUTRITION,
  // FITNESS, HEALTH) doesn't sprawl into adjacent lobes' wrappers on a
  // 375px-wide ring.
  const k = half / HALF;
  const n = nodes.length;
  if (n <= 1) return nodes.map((node) => ({ id: node.id, lx: half, ly: half }));

  if (n <= 7) {
    // Small lobe — single tidy ring. Pull slightly closer on mobile.
    const Rcap = isMobile ? 70 : 86;
    const Rgrow = isMobile ? 4.5 : 6;
    const R = Math.min(Rcap * k, (24 + n * Rgrow) * k);
    return nodes.map((node, i) => {
      const ang = (-90 + i * (360 / n)) * Math.PI / 180;
      return { id: node.id, lx: half + Math.cos(ang) * R, ly: half + Math.sin(ang) * R };
    });
  }

  // Dense lobe — sunflower / phyllotaxis spiral. The golden angle
  // (~137.5°) packs dots so the next one always lands in the largest gap,
  // producing an organic disk that reads as a cluster/galaxy rather than
  // the geometric two-ring rosette we had before (HEALTH was looking like
  // a star). sqrt(i/n) radius distribution keeps the density uniform from
  // centre to rim instead of bunching at the edge.
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));     // ~137.508°
  const cap   = isMobile ? 76  : 108;
  const grow  = isMobile ? 2.4 : 3.5;
  const baseR = isMobile ? 34  : 50;
  const maxR = Math.min(cap * k, (baseR + n * grow) * k);
  const minR = 6 * k;                                    // hollow centre
  return nodes.map((node, i) => {
    const t = (i + 0.5) / n;                             // 0..1
    const r = minR + (maxR - minR) * Math.sqrt(t);
    const ang = i * goldenAngle - Math.PI / 2;           // start near top
    return { id: node.id, lx: half + Math.cos(ang) * r, ly: half + Math.sin(ang) * r };
  });
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

function NodeDot({ node, e, theme, sel, fresh, freshTick, onSelect, pulse, offsetX, offsetY }) {
  const [hover, setHover] = useStateL(false);
  const ds = dotStyle(node, theme, sel, fresh);
  const lit = sel || fresh || hover;
  // Label visibility: hover + fresh-flash still show the inline name so
  // the user can see what they're about to tap. Selection HIDES the
  // label — the detail card already surfaces the name, and the dual
  // label feels redundant when the card is open.
  const showLabel = !sel && (hover || fresh);
  // pulse (0..1) is the wave amplification from the ripple emitted on
  // the most recent click. Boosts scale + glow as the ring sweeps past.
  const p = pulse || 0;
  const waveScale = 1 + p * 0.55;
  const waveGlow = p > 0
    ? `, 0 0 ${(p * 18).toFixed(1)}px ${ds.col}, 0 0 ${(p * 36).toFixed(1)}px ${ds.col}66`
    : "";
  // Labels hidden by default — they appear only when this dot is in focus
  // (hover, selection, or just-learned ripple). Keeps the constellation
  // breathing instead of drowning in text.
  return (
    <div onClick={(ev) => { ev.stopPropagation(); onSelect(sel ? null : node.id); }}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ position: "absolute", left: e.x + (offsetX || 0), top: e.y + (offsetY || 0),
        transform: `translate(-50%,-50%) scale(${(e.s * waveScale).toFixed(3)})`, opacity: e.o.toFixed(3),
        cursor: "pointer", zIndex: sel ? 8 : hover ? 7 : (p > 0.1 ? 6 : 2),
        transition: "z-index 0s" }}>
      <span style={{ position: "relative", display: "grid", placeItems: "center" }}>
        {fresh && <span key={freshTick} className="lvRipple" style={{ position: "absolute", width: 13, height: 13, borderRadius: "50%", border: `1.4px solid ${ds.col}` }}></span>}
        <span style={{ width: ds.width, height: ds.height, borderRadius: ds.borderRadius, background: ds.background, border: ds.border,
          boxShadow: (ds.boxShadow || "0 0 0 transparent") + waveGlow,
          transition: ds.transition }}></span>
      </span>
      <span title={node.label} style={{
        position: "absolute", top: "calc(50% + 12px)", left: "50%", transform: `translateX(-50%) translateY(${showLabel ? 0 : -3}px)`,
        maxWidth: 120, textAlign: "center", lineHeight: 1.18, whiteSpace: "nowrap",
        fontFamily: "'Geist Mono','DM Mono', monospace", fontSize: 10, letterSpacing: "0.02em",
        color: theme.labelSel, fontWeight: 500,
        opacity: showLabel ? 1 : 0, transition: "opacity .25s ease, transform .25s ease", pointerEvents: "none",
        textShadow: theme.name === "dark" ? "0 1px 8px rgba(0,0,0,0.9)" : "0 1px 6px rgba(255,255,255,0.95)" }}>
        {node.label}
      </span>
    </div>
  );
}

function BrainConstellationLive({ lobes, theme, freshId, freshTick, selectedId, onSelect, onSelectLobe, size, cardCenter, cardRadius }) {
  const pos = useRefL(new Map());
  const raf = useRefL(0);
  const running = useRefL(false);
  const [, setTick] = useStateL(0);
  const sig = lobes.map((l) => l.id + ":" + l.nodes.map((n) => n.id).join(",")).join("|") + "@" + (size && size.w ? Math.round(size.w / 40) : 0);

  // ── Mobile-aware lobe sizing. On narrow viewports the default 268px
  //    lobe wrapper (HALF*2) overflows the edges, clipping labels and
  //    pushing dots offscreen. Shrink the wrapper + internal ring radii
  //    proportionally so a 7-lobe ring still reads cleanly at 375px.
  const W0 = size && size.w ? size.w : 800;
  const isMobile = W0 < 480;
  // Mobile lobe sizing scales with both viewport width and active lobe
  // count — more lobes → smaller wrappers so they spread further on the
  // ring without overlap. Empirically half ≈ W*0.18 fits 7-8 lobes on a
  // 375px viewport. Sizes bumped ~7% from the prior pass so the brain
  // fills more of the available vertical room.
  const activeCount = Math.max(4, Math.min(8, lobes.length || 7));
  const sizeFactor = activeCount <= 5 ? 0.225 : activeCount <= 6 ? 0.205 : 0.178;
  const half = isMobile ? Math.max(66, Math.min(100, Math.round(W0 * sizeFactor))) : HALF;
  const waveLobeRange = isMobile ? 360 : 700;
  const waveDotRange = isMobile ? 260 : 560;
  const waveLobeDur = isMobile ? 1000 : 1300;
  // Mobile label tuning — smaller font, drop the parenthetical count so
  // adjacent lobes' labels don't crash into each other on the ring.
  const labelFontPx = isMobile ? 9.5 : 10.5;
  const chevronFontPx = isMobile ? 10 : 11;
  const showLobeCount = !isMobile;

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

  // ── Ripple wave — sci-fi "data propagation" feedback. When a dot is
  // tapped (or a lobe label is opened) we emit an expanding ring from
  // that screen position. Implementation uses an SVG <animate> element
  // keyed by emission timestamp so each wave restarts cleanly without
  // depending on React's render loop. The wave key is bumped to force
  // the SVG to remount and replay the animation.
  const [wave, setWave] = useStateL(null);          // {x, y, t0, range, dur}
  function emitWave(x, y, range, dur) {
    setWave({
      x, y,
      t0: (typeof performance !== "undefined" ? performance.now() : 0),
      range: range || waveDotRange,
      dur: dur || 1100,
    });
  }
  // Wrap onSelect / onSelectLobe so the click also emits the ripple AND
  // forwards the dot's world-space origin upstream — the App uses that to
  // anchor the mini detail card right next to the tapped dot instead of
  // pinning it to the bottom of the screen.
  //
  // Mobile skips the ripple wave on a single-dot click — the expanding
  // ring + spark plays badly on phone GPUs and the visual win isn't
  // worth the dropped frames. Lobe clicks still ripple because there
  // are fewer of them and the larger animation reads as deliberate.
  function selectWithRipple(id, originX, originY) {
    if (!isMobile && id != null && originX != null) emitWave(originX, originY);
    onSelect(id, originX, originY);
  }
  function selectLobeWithRipple(lobeId, originX, originY) {
    if (!isMobile && originX != null) emitWave(originX, originY, waveLobeRange, waveLobeDur);
    if (onSelectLobe) onSelectLobe(lobeId);
  }

  // Wave-pulse multiplier for a given (x,y). Returns 0 outside the
  // sweeping band, 0..1 inside it. Computed on every render — fine on
  // desktop because the constellation's existing animation loop is
  // constantly re-rendering anyway via setTick. Skipped on mobile
  // because the per-dot Math.sqrt() per frame was the biggest perf hit
  // and mobile already skips the originating ripple, so there's no
  // wave to sweep across.
  function wavePulseFor(x, y) {
    if (isMobile || !wave) return 0;
    const elapsed = (typeof performance !== "undefined" ? performance.now() : 0) - wave.t0;
    if (elapsed < 0 || elapsed > wave.dur) return 0;
    const progress = elapsed / wave.dur;
    const radius = progress * wave.range;
    const band = 46;
    const dist = Math.sqrt((x - wave.x) ** 2 + (y - wave.y) ** 2);
    const delta = Math.abs(dist - radius);
    if (delta > band) return 0;
    const intensity = (1 - delta / band) * (1 - progress * 0.35);
    return Math.max(0, intensity);
  }

  // Stagger schedule — new dots get a startAt timestamp so they hold at
  // the centre invisible until their wave fires. Outer-lobe dots (li=0
  // is the topmost lobe in the ring) lead, and within each lobe the
  // dots fan out by index. Result: dots cascade out from Arnie like a
  // Big Bang lobe-by-lobe, then settle, instead of all blooming at once.
  // Refresh / re-render existing dots keep their position (no delay).
  useEffectL(() => {
    // Wait for the stage to be measured before laying out dots — the
    // big-bang origin and lobe centres both depend on the real viewport
    // dimensions. If we run before measurement we'd seed every dot at
    // a stale (fallback) world centre that later doesn't match the lobes.
    if (!size || !size.w || !size.h) return;
    const present = new Set();
    const t0 = (typeof performance !== "undefined" ? performance.now() : 0);
    // Big-bang origin — every newly-seen dot is born at the screen
    // centre, then flies out to its final lobe-local target. This is
    // expressed in lobe-local coords (e.x/e.y), so for each lobe l we
    // compute the offset that maps world-centre → lobe-local space:
    //    e.x = (W/2) - c.x + half
    //    e.y = (H/2) - c.y + half
    // c.x/c.y is the lobe wrapper's centre in world coords. The whole
    // constellation reads as a single system that explodes outward
    // instead of each lobe blooming independently from its own core.
    const W = size.w;
    const H = size.h;
    const fracs = lobePositions(lobes, W, H, half);
    const centers = {};
    lobes.forEach((l) => {
      const f = fracs[l.id] || { x: 0.5, y: 0.5 };
      centers[l.id] = { x: f.x * W, y: f.y * H };
    });
    lobes.forEach((l, li) => {
      const c = centers[l.id] || { x: W / 2, y: H / 2 };
      // Mobile skips the big-bang origin and just drops every dot at its
      // final position with full opacity — the animated cascade was the
      // single biggest source of dropped frames on phone GPUs. Desktop
      // keeps the originate-from-centre flourish.
      const bornX = isMobile ? null : (W / 2 - c.x + half);
      const bornY = isMobile ? null : (H / 2 - c.y + half);
      layoutLocal(l.nodes, half, isMobile).forEach((loc, ni) => {
        present.add(loc.id);
        const e = pos.current.get(loc.id);
        if (!e) {
          // First time we've seen this dot — schedule it into the cascade
          // on desktop; on mobile, snap straight to the target.
          const delay = isMobile ? 0 : (50 + li * 35 + ni * 12);
          pos.current.set(loc.id, {
            x: isMobile ? loc.lx : bornX,
            y: isMobile ? loc.ly : bornY,
            s: isMobile ? 1 : 0,
            o: isMobile ? 1 : 0,
            tx: loc.lx, ty: loc.ly, ts: 1, to: 1,
            // Scatter displacement (world-space offset applied when the
            // detail card opens nearby). Tweens smoothly to 0 when the
            // card closes — never stored on the base (tx, ty) so dots
            // always have a clean home position to return to.
            dx: 0, dy: 0, dxT: 0, dyT: 0,
            lobe: l.id, removing: false,
            wcx: 0, wcy: 0,  // last computed world centre — set on render
            startAt: t0 + delay,
            popUntil: isMobile ? 0 : (t0 + delay + 340),
          });
        } else {
          e.tx = loc.lx; e.ty = loc.ly; e.ts = 1; e.to = 1; e.lobe = l.id; e.removing = false;
          if (e.dx == null) { e.dx = 0; e.dy = 0; e.dxT = 0; e.dyT = 0; }
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
      // Scatter — tween toward the target displacement that the render
      // pass set based on proximity to the open detail card. A gentler
      // ease so the dots drift open with weight, not snap.
      const dxT = e.dxT || 0, dyT = e.dyT || 0;
      e.dx = (e.dx || 0) + (dxT - (e.dx || 0)) * 0.14;
      e.dy = (e.dy || 0) + (dyT - (e.dy || 0)) * 0.14;
      if (
        Math.abs(e.tx - e.x) > 0.4 ||
        Math.abs(e.ty - e.y) > 0.4 ||
        Math.abs(ts - e.s) > 0.01 ||
        Math.abs(e.to - e.o) > 0.01 ||
        Math.abs(dxT - e.dx) > 0.4 ||
        Math.abs(dyT - e.dy) > 0.4
      ) active = true;
      if (e.removing && e.o < 0.03) pos.current.delete(id);
    });
    setTick((t) => t + 1);
    if (active) raf.current = requestAnimationFrame(loop); else running.current = false;
  }

  const W = size.w, H = size.h;
  if (!W || !H) return null;
  const fracs = lobePositions(lobes, W, H, half);
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

        {/* Ripple wave — CSS-keyframe driven for reliability. Two
            concentric rings expand outward + a quick spark at the origin.
            Each ring's intrinsic size is set inline (the FINAL size); the
            keyframe scales it from 0 → 1. Wave.t0 in the key forces
            React to remount on each new click so the animation replays. */}
        {wave && (() => {
          const sz1 = wave.range * 2;          // ring A diameter
          const sz2 = wave.range * 1.45;        // ring B diameter (inner)
          return (
            <div key={"wave-" + wave.t0} style={{
              position: "absolute", left: wave.x, top: wave.y,
              pointerEvents: "none", zIndex: 3, width: 0, height: 0 }}>
              <div className="lvRipplePulse" style={{
                position: "absolute", left: 0, top: 0,
                width: 14, height: 14, marginLeft: -7, marginTop: -7,
                borderRadius: "50%", background: theme.known,
                boxShadow: `0 0 28px ${theme.known}, 0 0 60px ${theme.known}66`,
                "--wave-dur": (wave.dur / 1000) + "s" }} />
              <div className="lvRippleRing lvRippleRingA" style={{
                position: "absolute", left: 0, top: 0,
                width: sz1, height: sz1, marginLeft: -sz1/2, marginTop: -sz1/2,
                borderRadius: "50%", border: `1.6px solid ${theme.known}`,
                boxSizing: "border-box",
                "--wave-dur": (wave.dur / 1000) + "s" }} />
              <div className="lvRippleRing lvRippleRingB" style={{
                position: "absolute", left: 0, top: 0,
                width: sz2, height: sz2, marginLeft: -sz2/2, marginTop: -sz2/2,
                borderRadius: "50%", border: `0.9px solid ${theme.known}`,
                boxSizing: "border-box",
                "--wave-dur": (wave.dur / 1000) + "s" }} />
            </div>
          );
        })()}

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
              style={{ position: "absolute", left: c.x - half, top: c.y - half, width: half * 2, height: half * 2 }}>
              {/* Clickable lobe label — wrapped in a subtle blurred pill so
                  it doesn't visually merge with the dot labels that float
                  underneath. The pill has a thin border + backdrop blur to
                  read as a tappable category badge, but no heavy fill so it
                  still feels native to the constellation. Hover/focus
                  brightens the border for affordance. */}
              <button onClick={(ev) => { ev.stopPropagation(); selectLobeWithRipple(l.id, c.x, c.y); }}
                onPointerDown={(ev) => ev.stopPropagation()}
                style={{ position: "absolute", left: half, top: -6, transform: "translate(-50%,-100%)",
                  display: "inline-flex", alignItems: "center", gap: 7, whiteSpace: "nowrap",
                  border: `1px solid ${theme.cardBorder}`,
                  background: theme.cardBg,
                  backdropFilter: "blur(10px)",
                  WebkitBackdropFilter: "blur(10px)",
                  borderRadius: 999,
                  padding: isMobile ? "5px 11px 5px 10px" : "5px 12px 5px 11px",
                  boxShadow: "0 6px 18px -10px rgba(0,0,0,0.45)",
                  cursor: "pointer", pointerEvents: "auto",
                  transition: "border-color .18s, transform .18s, box-shadow .18s" }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = theme.known + "88";
                  e.currentTarget.style.boxShadow = `0 8px 22px -10px ${theme.known}55`;
                  const nm = e.currentTarget.querySelector(".lvLobeName");
                  if (nm) nm.style.color = theme.cardVal;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = theme.cardBorder;
                  e.currentTarget.style.boxShadow = "0 6px 18px -10px rgba(0,0,0,0.45)";
                  const nm = e.currentTarget.querySelector(".lvLobeName");
                  if (nm) nm.style.color = theme.headText;
                }}>
                {/* Tiny green status dot anchors the pill — matches the dot
                    state colour vocabulary so the lobe reads as the parent
                    of the dots clustered below it. */}
                <span style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0,
                  background: theme.known, boxShadow: `0 0 6px ${theme.known}` }}></span>
                <span className="lvLobeName" style={{
                  fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: labelFontPx, fontWeight: 500,
                  letterSpacing: "0.10em", textTransform: "uppercase",
                  color: theme.headText, transition: "color .18s" }}>{l.short}</span>
                {showLobeCount && (
                  <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10, fontWeight: 500,
                    letterSpacing: "0.04em", color: theme.subText, opacity: 0.6 }}>{confirmedCount}/{l.nodes.length}</span>
                )}
                {/* Chevron — small green accent so the eye still finds the
                    affordance without any heavier chrome. */}
                <span aria-hidden="true" style={{
                  color: theme.known, fontSize: chevronFontPx, fontWeight: 700, lineHeight: 1,
                  opacity: 0.9, marginLeft: 1 }}>›</span>
              </button>
              {entries.map(({ node, e }) => {
                // World-space position of this dot — used as the ripple
                // origin when the user clicks it. e.x/e.y are relative to
                // the lobe (half, half anchored), so add the lobe centre
                // and subtract half to get the canvas-space coordinate.
                const worldX = c.x - half + e.x;
                const worldY = c.y - half + e.y;
                const pulse = wavePulseFor(worldX, worldY);
                // Scatter — when the detail card is open near this dot,
                // push the dot radially outward from the card centre. The
                // strength falls off with distance (^2) so neighbours just
                // outside the influence zone barely budge, while dots right
                // under the card open a clear pocket. The loop tweens
                // e.dx/e.dy toward these targets each frame.
                //
                // Skipped on mobile: the per-dot Math.sqrt + tween every
                // frame was a major source of dropped frames on phone
                // GPUs. The card simply overlays the dots on mobile.
                if (!isMobile && cardCenter && cardRadius && selectedId !== node.id) {
                  const fcx = worldX - cardCenter.x;
                  const fcy = worldY - cardCenter.y;
                  const d = Math.sqrt(fcx * fcx + fcy * fcy);
                  if (d > 0.5 && d < cardRadius) {
                    const force = Math.pow(1 - d / cardRadius, 1.6);
                    const push = force * 46;
                    e.dxT = (fcx / d) * push;
                    e.dyT = (fcy / d) * push;
                  } else {
                    e.dxT = 0; e.dyT = 0;
                  }
                } else {
                  e.dxT = 0; e.dyT = 0;
                }
                // Patch the NodeDot to read the displaced position by
                // mutating e.x/e.y views — no, instead pass an offset.
                const dx = e.dx || 0;
                const dy = e.dy || 0;
                return (
                  <NodeDot key={node.id} node={node} e={e} theme={theme}
                    offsetX={dx} offsetY={dy}
                    sel={selectedId === node.id} fresh={freshId === node.id} freshTick={freshTick}
                    onSelect={(id) => selectWithRipple(id, worldX + dx, worldY + dy)}
                    pulse={pulse} />
                );
              })}
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
  // Tabulated, backend-style row with two affordances stacked on the
  // right-hand column:
  //  • Tap the row → expand (full value wraps below)
  //  • Tap the value text → inline edit (PATCHes /api/profile/{token})
  // Edit is only enabled for nodes that carry editField (set during the
  // profile adapter pass). Chips and unfilled slots fall back to expand.
  // Mobile tuning — bigger type, looser row height, wider value column,
  // larger tap targets for inline edit. Reads at-a-glance on a phone
  // instead of squinting at 11px mono.
  const isPhone = (typeof window !== "undefined" && window.innerWidth < 480);
  const keyFont = isPhone ? 12 : 11;
  const valFont = isPhone ? 12.5 : 11.5;
  const rowMin = isPhone ? 30 : 22;
  const rowPad = isPhone ? "7px 0" : "4px 0";
  const labelFlex = isPhone ? "0 0 36%" : "0 0 38%";
  const [expanded, setExpanded] = useStateL(false);
  const [editing, setEditing] = useStateL(false);
  const [draft, setDraft] = useStateL("");
  const [saving, setSaving] = useStateL(false);
  const [saveErr, setSaveErr] = useStateL(null);
  // Local override of the displayed value after a successful save. The
  // backend poll catches up within 20s and refreshes via props; until
  // then this keeps the optimistic UI value on screen.
  const [override, setOverride] = useStateL(null);
  const baseValue = node.chips ? node.chips.join(" · ") : (node.value || "");
  const displayValue = override != null ? override : baseValue;
  const canExpand = !!displayValue && (displayValue.length > 28 || /[.;,]/.test(displayValue));
  const canEdit = !!node.editField && !node.chips;
  const startEdit = (ev) => {
    if (!canEdit) return;
    ev.stopPropagation();
    setDraft(node.editRaw != null ? node.editRaw : displayValue);
    setSaveErr(null);
    setEditing(true);
  };
  const cancelEdit = () => { setEditing(false); setSaveErr(null); };
  const commitEdit = async () => {
    if (!canEdit) { cancelEdit(); return; }
    const trimmed = String(draft).trim();
    if (trimmed === (node.editRaw != null ? String(node.editRaw).trim() : displayValue.trim())) {
      cancelEdit(); return;
    }
    setSaving(true); setSaveErr(null);
    try {
      const url = window.BRAIN_PROFILE_URL;  // /api/profile/{token}
      const r = await fetch(url, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field: node.editField, value: trimmed || null }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail || ("status " + r.status));
      }
      // Optimistic — the next 20s poll will refresh real state with the
      // canonical formatting (units, normalization, etc.).
      setOverride(trimmed);
      setEditing(false);
    } catch (err) {
      setSaveErr(String(err && err.message ? err.message : err) || "save failed");
    } finally {
      setSaving(false);
    }
  };
  return (
    <div onClick={() => { if (!editing && canExpand) setExpanded(v => !v); }}
      style={{ display: "flex", flexDirection: "column",
        padding: rowPad,
        borderTop: first ? "none" : `1px solid ${theme.listDivider}`,
        background: fresh ? theme.freshWash : (editing ? theme.freshWash : "transparent"),
        transition: "background .25s ease",
        cursor: (!editing && canExpand) ? "pointer" : "default" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, minHeight: rowMin }}>
        <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: keyFont, fontWeight: 500,
          letterSpacing: "0.02em", color: theme.subText, flex: labelFlex, minWidth: 0,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {tableKey(node.label)}
        </div>
        {editing ? (
          <input
            autoFocus
            value={draft}
            disabled={saving}
            onClick={(ev) => ev.stopPropagation()}
            onChange={(ev) => setDraft(ev.target.value)}
            onKeyDown={(ev) => {
              if (ev.key === "Enter") { ev.preventDefault(); commitEdit(); }
              else if (ev.key === "Escape") { ev.preventDefault(); cancelEdit(); }
            }}
            onBlur={() => { if (!saving) commitEdit(); }}
            style={{ flex: "1 1 auto", minWidth: 0, textAlign: "right",
              fontFamily: "'Geist Mono','SF Mono', monospace",
              fontSize: valFont, fontWeight: 500, letterSpacing: "0.01em",
              color: theme.rowVal,
              background: "transparent",
              border: "none",
              borderBottom: `1px solid ${saveErr ? "rgba(255,90,80,0.7)" : theme.known}`,
              outline: "none",
              padding: isPhone ? "4px 0" : "1px 0",
              opacity: saving ? 0.6 : 1 }} />
        ) : displayValue ? (
          <div onClick={canEdit ? startEdit : undefined}
            style={{ flex: "1 1 auto", minWidth: 0, textAlign: "right",
              fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: valFont, fontWeight: 500,
              letterSpacing: "0.01em", color: theme.rowVal,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              cursor: canEdit ? "text" : "inherit",
              borderBottom: canEdit ? `1px dashed ${theme.cardBorder}` : "none",
              // Larger tap target on mobile — the value's hit area grows
              // to the full cell so a finger doesn't have to land on the
              // text itself.
              padding: canEdit ? (isPhone ? "5px 0 6px" : "0 0 1px") : 0 }}
            title={canEdit ? "Tap to edit" : displayValue}>
            {displayValue}
          </div>
        ) : canEdit ? (
          <div onClick={startEdit}
            style={{ flex: "1 1 auto", textAlign: "right",
              fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: valFont,
              color: theme.subText, opacity: 0.45,
              cursor: "text",
              borderBottom: `1px dashed ${theme.cardBorder}`,
              padding: isPhone ? "5px 0 6px" : "0 0 1px" }}
            title="Tap to add">
            add
          </div>
        ) : (
          <div style={{ flex: "1 1 auto", textAlign: "right",
            fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: valFont,
            color: theme.subText, opacity: 0.35 }}>—</div>
        )}
        {/* Right-edge affordance — expand caret OR saving spinner OR state dot */}
        {!editing && canExpand ? (
          <span aria-hidden="true" style={{ width: 10, height: 10, color: theme.subText,
            opacity: 0.45, fontSize: 9, lineHeight: 1, flexShrink: 0,
            transform: expanded ? "rotate(90deg)" : "none", transition: "transform .18s ease" }}>›</span>
        ) : null}
        {editing && saving ? (
          <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
            background: theme.known, opacity: 0.65,
            animation: "lvThink 1.2s ease-in-out infinite" }} />
        ) : (
          <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
            background: node.state === "confirmed" ? theme.known : "transparent",
            border: node.state === "confirmed" ? "none" : `1.2px solid ${stateColor(node.state, theme)}` }} />
        )}
      </div>
      {editing && saveErr && (
        <div style={{ marginTop: 3, padding: "0",
          fontFamily: "'Geist Mono','SF Mono', monospace",
          fontSize: 9.5, color: "rgba(255,120,110,0.85)",
          letterSpacing: "0.06em", textAlign: "right" }}>
          {saveErr}
        </div>
      )}
      {/* Expanded body — shows the full value with proper wrapping so
          long sentences and chip lists become legible. Stays inside the
          row's existing left/right gutters. */}
      {canExpand && expanded && (
        <div style={{ marginTop: 4, padding: isPhone ? "6px 0 9px" : "4px 0 6px",
          fontFamily: "'Geist Mono','SF Mono', monospace",
          fontSize: isPhone ? 12.5 : 11.5, fontWeight: 400,
          color: theme.cardVal, lineHeight: 1.55, letterSpacing: "0.01em",
          textWrap: "pretty", whiteSpace: "normal", wordBreak: "break-word" }}>
          {displayValue}
        </div>
      )}
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
        const row = { id: "group." + key, label: key, chips: [n.label],
          // Chip groups aren't directly editable from a list row — their
          // value is a multi-item set. Mark as not-editable; tap-to-edit
          // is a single-value affordance.
          state: n.state, editField: null };
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
  // Softer list view — readable section headers, sentence-case keys
  // instead of snake_case, sans-serif body type. Reads like a notebook
  // of what Arnie knows, not a database dump. Still tabulated and tight
  // but warmer.
  //
  // Section ordering is opinionated for the LIST view: surface the user
  // anchors first (Demographics → Goals → Nutrition → Fitness →
  // Lifestyle → Thoughts), then the rest. Mirrors the way a coach
  // briefing reads top-down, not the spatial logic the constellation
  // uses around the ring.
  const LIST_ORDER = ["demographics", "goals", "nutrition", "fitness", "lifestyle", "custom"];
  const ordered = (() => {
    const byId = {};
    lobes.forEach((l) => { byId[l.id] = l; });
    const used = new Set();
    const out = [];
    LIST_ORDER.forEach((id) => {
      if (byId[id]) { out.push(byId[id]); used.add(id); }
    });
    lobes.forEach((l) => { if (!used.has(l.id)) out.push(l); });
    return out;
  })();
  return (
    <div style={{ maxWidth: 600, margin: "0 auto",
      // Tighter side gutters on mobile (8px) so the list uses the full
      // viewport width without crowding the dividers. Tablet+ scales up
      // with viewport via clamp so wider screens still get a centred,
      // breathable column.
      padding: "6px clamp(8px, 3vw, 32px) 120px",
      fontFamily: "'Geist Mono','SF Mono', monospace" }}>
      {ordered.map((l) => {
        const consolidated = consolidateChipNodes(l.nodes);
        const confirmed = consolidated.filter((n) => n.state === "confirmed").length;
        const isPhoneSection = (typeof window !== "undefined" && window.innerWidth < 480);
        return (
          <div key={l.id} style={{ marginBottom: isPhoneSection ? 14 : 12 }}>
            {/* Section header — tight mono caps in the terminal/stdout
                style. Mobile gives the header a touch more breathing
                room and a slightly larger key so the sections feel
                scannable on a phone. */}
            <div style={{ display: "flex", alignItems: "baseline", gap: 10,
              padding: isPhoneSection ? "16px 0 7px" : "12px 0 5px",
              borderBottom: `1px solid ${theme.listDivider}` }}>
              <span style={{ fontSize: isPhoneSection ? 10.5 : 10, fontWeight: 500,
                letterSpacing: "0.18em",
                textTransform: "uppercase", color: theme.secLabel }}>
                {tableKey(l.name)}
              </span>
              <span style={{ flex: 1, height: 1 }} />
              <span style={{ fontSize: 9.5, fontWeight: 500, letterSpacing: "0.06em",
                color: theme.subText, opacity: 0.55 }}>
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
// Ring positions interleave DENSE (Nutrition, Fitness, Health, Behavior)
// and SPARSE (Demographics, Lifestyle, Thoughts) lobes so the
// constellation looks balanced at every screen size. With 7 active lobes
// the result is a perfect dense-sparse-dense-sparse alternation: no two
// big clusters end up adjacent on the ring, which used to make the
// top-right corner overflow on narrow viewports.
//
// Constraints honoured:
//   • NUTRITION at index 0 → top (most actionable for a coach).
//   • LIFESTYLE at index 3 → south / bottom (per user request).
//   • BEHAVIOR at index 6 → upper-left, ABOVE Demographics.
//
// Goals + Mental stay in the list so they slot in if the user fills
// them, but don't reserve a ring slot when empty.
const LOBE_ORDER = [
  { id: "nutrition", name: "Nutrition", short: "NUTRITION",
    coaching: "Drives meal suggestions, macro reminders, and food substitutions. Arnie uses your staples + avoidances to recommend foods you'll actually eat, flag patterns (e.g. low fibre days), and pace nudges when you're under or over target." },
  { id: "demographics", name: "Demographics", short: "DEMOGRAPHICS",
    coaching: "Baseline for every calculation Arnie runs. BMR, daily calorie target, macro splits, and progress comparisons all use these numbers. When a value changes (you log a new weight, update height) Arnie re-derives targets in the background." },
  { id: "fitness", name: "Fitness", short: "FITNESS",
    coaching: "Shapes workout pacing, exercise selection, and progressive-overload guidance. Arnie picks reps/loads that match your training experience and respects the recovery rhythm of your split." },
  { id: "lifestyle", name: "Lifestyle", short: "LIFESTYLE",
    coaching: "Calibrates timing — when nudges land, how recovery advice adapts to your sleep schedule, and how Arnie suggests workout windows that fit your routine instead of fighting it." },
  { id: "health", name: "Health", short: "HEALTH",
    coaching: "Informs supplement timing, training modifications around injuries, and recovery-aware intensity. When HRV or sleep dips, Arnie pulls back volume; he steers around your limitations rather than asking you to push through." },
  { id: "custom", name: "Thoughts", short: "THOUGHTS",
    coaching: "Things I've noticed about you that don't fit the standard categories — patterns, preferences, quirks I'm tracking on my own. These often end up shaping coaching more than the textbook stuff." },
  { id: "behavior", name: "Behavior", short: "BEHAVIOR",
    coaching: "Tunes Arnie's tone, accountability cadence, and how directly he pushes vs supports. Confirmed preferences here set the default voice of every check-in." },
  // Populated-only — these stay in the list so they slot in if the user
  // ever fills them, but they don't reserve ring positions when empty.
  { id: "goals", name: "Goals & targets", short: "GOALS",
    coaching: "The anchor for every recommendation. Surplus/deficit, macro split, training emphasis, and progress feedback all derive from your stated goal. Targets here override anything Arnie infers from patterns." },
  { id: "mental", name: "Mental", short: "MENTAL",
    coaching: "Shapes how Arnie supports motivation dips, plateau anxieties, and setbacks. He reframes rather than lectures when these signals show up." },
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
// Module-level helper — used by both the profile adapter (turning a date
// into node metadata) and by the detail card render (turning that
// metadata back into a human caption). Exposed on `window` so it can be
// called from any closure in this bundle without re-declaring.
window.brainFormatRelTime = function (dateStr) {
  if (!dateStr) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!m) return dateStr;
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  const now = new Date();
  const days = Math.round((now - d) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return days + " days ago";
  if (days < 30) return Math.round(days / 7) + (days < 14 ? " week ago" : " weeks ago");
  if (days < 365) return Math.round(days / 30) + (days < 60 ? " month ago" : " months ago");
  return Math.round(days / 365) + " yr ago";
};

const SIM_MODE = (() => {
  try { return new URLSearchParams(window.location.search).get("sim") || ""; }
  catch (e) { return ""; }
})();
// SIM_HEALTH (legacy) only fires for ?sim=health. When ?sim=full is set
// we instead use the structured SIM_CUSTOMS list below, which mirrors the
// real profile shape (commas → spec lines, dates → metadata footer).
const SIM_HEALTH = SIM_MODE === "health";
const SIM_FULL = SIM_MODE === "full";

const SIM_SUPPLEMENTS = [
  "Creatine 5g", "Fish oil 2g", "Vitamin D 5000IU",
  "Magnesium glycinate 400mg", "Multivitamin", "NMN 500mg",
  "Taurine 1g", "L-citrulline 6g", "Ashwagandha 600mg",
];
const SIM_PEPTIDES = [
  "BPC-157 250mcg", "TB-500 500mcg", "Ipamorelin 200mcg",
  "CJC-1295 100mcg", "MK-677 10mg",
];

// Realistic mock fills for the standard slots the profile usually leaves
// unfilled. Keyed by lobe id → { node label → value }. Used by ?sim=full.
// Modelled on the user's real profile shape — bullet lists for chip
// groups, sentence values for descriptions, "(date, source)" suffixes on
// learned metrics so the extractMeta path runs against realistic input.
const SIM_FILLS = {
  nutrition: {
    "Staple foods": "Banana · Barebells salty peanut protein bar · Oikos vanilla protein shake · White rice · Honey · Barebells caramel cashew protein bar",
    "Foods avoided": "Oysters · Mussels · Lamb",
    "Diet style": "High-protein, flexible dieting, tracks calories and protein. Fats generally low/controlled.",
    "Protein habits": "High-protein · targets 190g per day",
    "Meal timing": "Brunch around 11 · Protein-forward dinner · Zero late snacks",
  },
  fitness: {
    "Training split": "Upper-Focus PPL with Arms/Core/Legs Maintenance",
    "Training time": "5:30–6pm post-work",
    "Favorite cardio": "Zone 1–2 spin · Incline walk · Stair climber on lift days",
  },
  lifestyle: {
    "Sleep schedule": "07:30–23:00",
    "Work schedule": "10am–4pm",
    "Stress level": "Moderate · peaks on quarter-end weeks",
  },
  behavior: {
    "Coaching style": "Balanced",
    "Accountability": "High",
    "Motivation": "Strength progression, rep PRs, looking leaner, visible physique changes",
  },
  // Goals fill the standard goal_why + goal_timeline slots that the
  // profile API surfaces under data.standard.goals. Filling them here
  // makes the Goals lobe show up in the constellation; live edits from
  // chat or the profile tab flow through the same 20s poll → diffLobes
  // pipeline that drives the toast, so a real goal change will appear
  // as "Arnie · confirmed" in the brain within one poll cycle.
  goals: {
    "Why this goal": "Look and feel strong; build a visible physique while staying lean enough to see the work.",
    "Timeline": "12-week pushes · evaluate at each checkpoint",
  },
};

// Custom attributes that aren't part of the standard slot schema but are
// real things Arnie has learned and surfaces in the live dashboard
// (Calorie target, Resting heart rate from Whoop, Exercises list, etc.).
// Mirrors the shape returned by /api/profile under data.custom: each
// entry is { category, label, value | chips, confidence }.
const SIM_CUSTOMS = [
  // Nutrition customs
  { category: "nutrition", label: "Calorie target", value: "2000 kcal/day" },
  { category: "nutrition", label: "Protein target", value: "150g/day" },
  { category: "nutrition", label: "Fat target", value: "Low/controlled, fills remainder after protein · carbs" },
  { category: "nutrition", label: "Protein sources", chips: ["Oikos vanilla shake", "Barebells protein bars", "Ground turkey", "Happy wolf chocolate chip bar", "Muscle milk pro shake"] },
  { category: "nutrition", label: "Typical protein intake", value: "190g/day" },
  { category: "nutrition", label: "Carb sources", chips: ["White rice", "Banana", "Royo challah roll", "Watermelon"] },
  { category: "nutrition", label: "Key moves", value: "Eat earlier · Pre-workout carbs · Post-workout meal · Skip daily weigh-ins" },
  { category: "nutrition", label: "Weakness", value: "Under-fueled until afternoon; compensates late-day eating" },
  // Fitness customs
  { category: "fitness", label: "Experience", value: "Advanced" },
  { category: "fitness", label: "Daily steps", value: "8500" },
  { category: "fitness", label: "Dislikes", chips: ["Excessive volume", "Junk sets", "Long workouts", "Excess leg work"] },
  { category: "fitness", label: "Morning weigh-in", value: "true" },
  { category: "fitness", label: "Exercises", chips: [
    "Lat pulldown", "Incline bench machine press", "Cable fly",
    "Straight arm pulldown", "Cable front raise",
    "Shoulder press machine", "Cable lateral raise", "Crunches"
  ] },
  { category: "fitness", label: "Progression model", value: "Rep PRs first, then increase load. Earn weight increases." },
  { category: "fitness", label: "RIR — compounds", value: "1–2 RIR" },
  { category: "fitness", label: "RIR — isolations", value: "Often to failure" },
  // Health customs — "(date, source)" pattern feeds extractMeta
  { category: "health", label: "Injuries / limitations", value: "ACL and meniscus reconstruction 2023, knee health" },
  { category: "health", label: "Supplements", chips: [
    "C4 pre-workout, training days",
    "Ferritin, monitoring",
    "Fish oil 2g",
    "Happy Wolf bars, occasional",
    "Magnesium 120mg, 4x per week",
    "Muscle Milk Pro 42g, occasional",
    "Vitamin D 5000IU"
  ] },
  { category: "health", label: "HRV trend", value: "70ms (2026-06-09, Whoop)" },
  { category: "health", label: "Resting heart rate", value: "53bpm (2026-06-09, Whoop)" },
  { category: "health", label: "Recovery status", value: "56% (2026-06-10, Whoop)" },
  { category: "health", label: "Sleep quality", value: "8.1h total · 2.5h deep · 1.8h REM (2026-06-09)" },
  // Goals & targets — custom entries that aren't part of the standard
  // goal slot schema but are real things Arnie tracks. Includes the
  // headline goal, body composition targets, training PRs, and the
  // current training block, each modelled to flow through the same
  // adapter parsers (chips, dates, units) the rest of the brain uses.
  { category: "goals", label: "Primary goal", value: "Lean bulk · gain muscle without adding fat" },
  { category: "goals", label: "Current phase", value: "Lean bulk (week 4 of 12)" },
  { category: "goals", label: "Target weight", value: "195 lbs (2026-09-01)" },
  { category: "goals", label: "Target body fat", value: "12%" },
  { category: "goals", label: "Strength PRs", chips: [
    "Bench 225×5", "Squat 315×3", "Deadlift 405×2", "OHP 155×5"
  ] },
  { category: "goals", label: "Why", value: "Look and feel strong; visible physique change without giving up the parts of training I enjoy." },
  { category: "goals", label: "Source", value: "stated in chat" },
  // Lifestyle
  { category: "lifestyle", label: "Family", value: "Married, has a baby" },
  // Behavior
  { category: "behavior", label: "Accountability preference", value: "high" },
  { category: "behavior", label: "Coaching tone preference", value: "strict" },
];

// Thoughts — the new free-form lobe for things Arnie noticed about you
// that don't slot into a standard category. Each is a discrete observation
// rather than a clean data point.
const SIM_THOUGHTS = [
  "Reads more physique content than performance content",
  "Underestimates calorie intake on weekends",
  "Mentions back tightness on heavy pulling days",
  "Sleeps better after lift days vs rest days",
  "Gets reactive when scale fluctuates 2+ lbs in a day",
  "Prefers shorter intense sessions over long ones",
  "Asks about cardio mostly on rest days",
  "Feels 'skinny' when energy is low — diet usually the cause",
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
    editField: b.edit_field || null,
    editRaw: b.raw || null,
    state: "confirmed",
  }));

  // Helpers — hoisted to the top of profileToLobes scope so the SIM_FULL
  // block can call them too (they used to live inside the LOBE_ORDER
  // forEach which made them invisible to anything after the loop).
  //
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
    chips.map((chip, j) => {
      const { name, spec } = splitChipSpec(chip);
      return {
        id: idPrefix + ".chip." + j,
        label: sentenceCase(name),
        spec: spec || null,
        parentLabel: parentLabel,
        state: st,
      };
    });

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
  // ── Value-shape helpers ──────────────────────────────────────────────────
  //
  // Real profile values aren't clean scalars. They carry inline metadata
  // (dates + sources in parens), unit-of-unit duplication, brand+dose+freq
  // compounds, and booleans-as-strings. Parsing these into a head + meta
  // pair lets the detail card render them as a clean hierarchy instead of
  // dumping a string blob onto the user.
  //
  // extractMeta("70ms (2026-06-09, Whoop)") →
  //   { value: "70ms", date: "2026-06-09", source: "Whoop" }
  // extractMeta("Plain value") →
  //   { value: "Plain value" }
  function extractMeta(value) {
    if (!value) return { value: "" };
    const raw = String(value).trim();
    // Trailing "(...)" — pull out date / source pairs.
    const m = raw.match(/^(.+?)\s*\(([^()]+)\)\s*$/);
    if (!m) return { value: raw };
    const head = m[1].trim();
    const inner = m[2].trim();
    // Split on " , " — typical "(2026-06-09, Whoop)" form.
    const parts = inner.split(/\s*,\s*/);
    let date = null, source = null;
    parts.forEach((p) => {
      if (/^\d{4}-\d{2}-\d{2}$/.test(p)) date = p;
      else source = p;     // last non-date wins as the source label
    });
    return { value: head, date, source };
  }
  // formatRelTime — local alias of the module-scoped helper, kept here so
  // the rest of the adapter logic reads in one place. The detail card
  // calls window.brainFormatRelTime directly (defined just below).
  const formatRelTime = (s) => window.brainFormatRelTime(s);
  // normalizeBool — render "true"/"false"/"yes"/"no" as glyphs so a
  // Morning Weigh-In Reminder dot doesn't say the literal word "true".
  function normalizeBool(value) {
    if (value == null) return null;
    const v = String(value).toLowerCase().trim();
    if (v === "true" || v === "yes" || v === "on") return "Yes";
    if (v === "false" || v === "no" || v === "off") return "No";
    return null;
  }
  // splitChipSpec — for chips that carry a brand + dose + freq compound
  // ("Magnesium 120mg, 4x per week"), return { name, spec }. The chip
  // detail card uses name as the headline and spec as a small caption.
  // Heuristic: split on the first comma OR on the first numeric run.
  function splitChipSpec(chip) {
    const raw = String(chip || "").trim();
    if (!raw) return { name: raw };
    // Pattern 1: "Name, qualifier · cadence" — comma split is enough.
    const ci = raw.indexOf(",");
    if (ci > 0 && ci < raw.length - 1) {
      return { name: raw.slice(0, ci).trim(), spec: raw.slice(ci + 1).trim() };
    }
    // Pattern 2: "Name 120mg foo" — split before the first dose-like token.
    const dose = raw.match(/^(.+?)\s+(\d+(?:\.\d+)?\s*(?:mg|mcg|g|iu|kcal|ml|min|hr|h|x)\b.*)$/i);
    if (dose) return { name: dose[1].trim(), spec: dose[2].trim() };
    return { name: raw };
  }

  const lobes = [];
  LOBE_ORDER.forEach((lobe) => {
    if (lobe.id === "demographics") {
      if (demoNodes.length) lobes.push({ ...lobe, nodes: demoNodes });
      return;
    }
    const slots = std[lobe.id] || [];
    const customs = customByCat[lobe.id] || [];
    const nodes = [];

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
            const m = extractMeta(s.value);
            const boolish = normalizeBool(m.value);
            nodes.push({ id: nid, label: s.label,
              value: boolish || m.value || "",
              editField: s.edit_field || s.key || null,
              editRaw: s.raw != null ? String(s.raw) : (m.value || ""),
              date: m.date || null, source: m.source || null,
              state: confState(s.confidence) });
          }
        }
      } else {
        // Unfilled slot — no placeholder text. The orange ring on the dot
        // and the state badge already communicate "still learning". Adding
        // a literal "still learning..." string just added noise to every
        // half-empty lobe panel.
        nodes.push({ id: nid, label: s.label,
          editField: s.edit_field || s.key || null,
          state: "learning" });
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
          const m = extractMeta(c.value);
          const boolish = normalizeBool(m.value);
          nodes.push({ id: nid, label: c.label,
            value: boolish || m.value || "",
            date: m.date || null, source: m.source || null,
            state: confState(c.confidence) });
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
    else lobes.push({ id: "custom", name: "Thoughts", short: "THOUGHTS", nodes: leftover });
  }

  // Simulation injection.
  //
  //   ?sim=health → only supplements + peptides under HEALTH
  //   ?sim=full   → everything above, plus fills in every still-unfilled
  //                 standard slot AND injects a fresh THOUGHTS lobe with
  //                 8 Arnie-noticed observations. Used for previewing a
  //                 fully populated brain without writing to the real DB.
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

  if (SIM_FULL) {
    // Promote every still-learning slot to a confirmed value using the
    // SIM_FILLS lookup. Bullet-separated strings get exploded into
    // per-chip nodes the same way real values do, so each sim fill
    // grows the constellation realistically instead of collapsing into
    // one dot per slot.
    Object.keys(SIM_FILLS).forEach((lobeId) => {
      const lobe = lobes.find((l) => l.id === lobeId);
      if (!lobe) return;
      const fills = SIM_FILLS[lobeId];
      const newNodes = [];
      lobe.nodes.forEach((n) => {
        if (n.state === "learning" && fills[n.label]) {
          const value = fills[n.label];
          const parts = asBulletList(value);
          if (parts) {
            newNodes.push(...explodeChips(n.id, n.label, parts, "confirmed"));
          } else {
            const m = extractMeta(value);
            const boolish = normalizeBool(m.value);
            newNodes.push({ ...n, state: "confirmed",
              value: boolish || m.value || "",
              date: m.date || null, source: m.source || null });
          }
        } else {
          newNodes.push(n);
        }
      });
      lobe.nodes = newNodes;
    });

    // SIM_CUSTOMS — append realistic custom attributes per lobe, mirroring
    // the shape of data.custom in the live profile. Each entry becomes a
    // node (chip-exploded if .chips is present) so the constellation
    // density matches what a real fully-onboarded user would see.
    //
    // Auto-bootstrap any lobe a custom entry references — when SIM_FULL
    // injects Goals customs but the live profile didn't return any goals
    // standard slots, the goals lobe wouldn't otherwise exist yet. Spin
    // it up from LOBE_ORDER metadata so the customs have a home and the
    // constellation actually gains the lobe.
    SIM_CUSTOMS.forEach((c, i) => {
      let lobe = lobes.find((l) => l.id === c.category);
      if (!lobe) {
        const meta = LOBE_ORDER.find((l) => l.id === c.category);
        if (!meta) return;
        lobe = { ...meta, nodes: [] };
        lobes.push(lobe);
      }
      const nid = c.category + ".sim.c." + i;
      if (c.chips && c.chips.length) {
        lobe.nodes.push(...explodeChips(nid, c.label, c.chips, "confirmed"));
      } else if (c.value) {
        const parts = asBulletList(c.value);
        if (parts) {
          lobe.nodes.push(...explodeChips(nid, c.label, parts, "confirmed"));
        } else {
          const m = extractMeta(c.value);
          const boolish = normalizeBool(m.value);
          lobe.nodes.push({ id: nid, label: c.label,
            value: boolish || m.value || "",
            date: m.date || null, source: m.source || null,
            state: "confirmed" });
        }
      }
    });

    // Spin up the THOUGHTS lobe (the renamed-from-custom one). If it
    // already exists from real custom attributes we just append; if not
    // we create it from LOBE_ORDER metadata so coaching/icon/order stay
    // consistent with the rest.
    let thoughts = lobes.find((l) => l.id === "custom");
    if (!thoughts) {
      const meta = LOBE_ORDER.find((l) => l.id === "custom");
      thoughts = { ...meta, nodes: [] };
      lobes.push(thoughts);
    }
    SIM_THOUGHTS.forEach((t, i) => {
      thoughts.nodes.push({
        id: "sim.thought." + i,
        label: t,
        state: "confirmed",
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
                // Rail wash behind grouped chip rows. Mobile bumps the
                // alpha noticeably — at 0.018 these rows are invisible
                // on a phone, which made supplement/exercise lists hard
                // to parse from the surrounding single-value rows.
                const isPhonePanel = (typeof window !== "undefined" && window.innerWidth < 480);
                const railBgAlpha = isPhonePanel ? "0.055" : "0.018";
                const railBg = `rgba(${theme.name === "dark" ? "255,255,255," + railBgAlpha : "0,0,0," + (isPhonePanel ? "0.04" : "0.018")})`;
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
                      // Uniform vertical padding for both grouped chip rows
                      // and single-value rows so the panel reads as one
                      // consistent list rhythm. Left padding is 24px for
                      // grouped rows (to clear the accent rail) and 14px
                      // for single rows.
                      padding: n.parentLabel ? "8px 14px 8px 24px" : "8px 14px",
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
                      <span style={{ fontFamily: "'Geist', system-ui, sans-serif",
                        fontSize: 12.5,
                        // Grouped chip rows: label IS the primary content
                        // (the chip name), so render it brighter for higher
                        // contrast. Single-value rows: label is a caption
                        // paired with the value on the right, so it stays
                        // muted to let the value lead.
                        fontWeight: n.parentLabel ? 500 : 400,
                        color: n.parentLabel ? theme.cardVal : theme.subText,
                        flex: "0 0 auto", maxWidth: "45%",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        opacity: hasValue ? 1 : 0.55 }}>
                        {n.label}
                      </span>
                      {/* Spec line for chip rows (e.g. "120mg · 4x per week") */}
                      {n.parentLabel && n.spec && (
                        <span style={{ fontFamily: "'Geist', system-ui, sans-serif",
                          fontSize: 11, fontWeight: 400, color: theme.subText,
                          opacity: 0.75, marginLeft: 4, flex: "0 1 auto",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {n.spec}
                        </span>
                      )}
                      {n.chips ? (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, justifyContent: "flex-end",
                          flex: "1 1 auto", minWidth: 0 }}>
                          {n.chips.map((c, j) => (
                            <span key={j} style={{ fontFamily: "'Geist', system-ui, sans-serif",
                              fontSize: 11.5, fontWeight: 500, color: theme.cardVal,
                              // Mobile chips ride a brighter background so
                              // chip lists pop out of the row instead of
                              // blending into it.
                              background: isPhonePanel
                                ? (theme.name === "dark" ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.06)")
                                : theme.ctrlBg,
                              borderRadius: 5,
                              padding: "2px 8px", whiteSpace: "nowrap" }}>{c}</span>
                          ))}
                        </div>
                      ) : n.value ? (
                        <span style={{ flex: "1 1 auto", minWidth: 0, textAlign: "right",
                          fontFamily: "'Geist', system-ui, sans-serif", fontSize: 12.5, fontWeight: 500,
                          color: theme.rowVal, lineHeight: 1.42, textWrap: "pretty",
                          display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>{n.value}</span>
                          {(n.date || n.source) && (
                            <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace",
                              fontSize: 8.5, fontWeight: 500, letterSpacing: "0.08em",
                              textTransform: "uppercase", color: theme.subText, opacity: 0.55,
                              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>
                              {[
                                n.date ? (window.brainFormatRelTime(n.date) || n.date) : null,
                                n.source
                              ].filter(Boolean).join(" · ")}
                            </span>
                          )}
                        </span>
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
  // First-visit welcome tooltip — gone once dismissed, never returns. The
  // localStorage flag is set on dismiss, not just on first-render, so a
  // refresh mid-session keeps the card visible until the user actually
  // closes it.
  const [welcomed, setWelcomed] = useState(() => localStorage.getItem("arnie.brain.welcomed") === "1");
  function dismissWelcome() {
    try { localStorage.setItem("arnie.brain.welcomed", "1"); } catch (e) {}
    setWelcomed(true);
  }

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
  // World-space origin of the currently-selected dot — set when the user
  // taps a dot, cleared when the card closes. Drives both the floating
  // card's position and the scatter halo BrainConstellationLive applies to
  // surrounding dots so they make room for the card.
  const [selectedPos, setSelectedPos] = useState(null);
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
  // Overall "Arnie knows you" percentage, used to gate the still-loading
  // nudge. Confirmed = the user has either told Arnie directly or he's
  // extracted it from enough patterns to be sure. Learning/inferred dots
  // don't count — those are works in progress.
  const confirmedTotal = allNodes.filter((n) => n.state === "confirmed").length;
  const confirmedPct = total > 0 ? Math.round((confirmedTotal / total) * 100) : 0;
  const stillLoading = total > 0 && confirmedPct < 60;
  const stateMeta = (st) => st === "learning" ? "needs verification" : st === "inferred" ? "inferred from patterns" : "confirmed";
  const stateCol = (st) => st === "learning" ? theme.learning : st === "inferred" ? theme.inferred : theme.known;

  return (
    <div ref={rootRef} style={{ position: "relative", height: "100%", background: theme.stageBg,
      transition: "background .5s ease", overflow: "hidden" }}>

      {view === "brain" ? (
        <window.BrainConstellationLive lobes={lobes} theme={theme} freshId={freshId} freshTick={freshTick}
          selectedId={selectedId}
          onSelect={(id, worldX, worldY) => {
            setSelectedId(id);
            if (id != null && worldX != null) setSelectedPos({ x: worldX, y: worldY });
            else if (id == null) setSelectedPos(null);
          }}
          onSelectLobe={(id) => setSelectedLobeId((prev) => prev === id ? null : id)}
          size={size}
          cardCenter={selectedId && selectedPos && size && size.h ? (() => {
            // Card's visual centre = dot pos + offset to whichever side the
            // card opens on. Matches the placement math in the detail-card
            // JSX so the scatter zone tracks the actual card body, not the
            // tapped dot.
            const compact = size.w < 480;
            const cardH = compact ? 175 : 220;
            const gap = compact ? 28 : 32;
            const above = selectedPos.y > size.h * 0.55;
            const cy = above
              ? selectedPos.y - gap - cardH / 2
              : selectedPos.y + gap + cardH / 2;
            return { x: selectedPos.x, y: cy };
          })() : null}
          cardRadius={selectedId && selectedPos ? ((size && size.w < 480) ? 165 : 195) : 0} />
      ) : (
        <div className="brain-list" style={{ position: "absolute", inset: 0, overflow: "auto", paddingTop: 92 }}>
          <window.BrainListView lobes={lobes} theme={theme} freshId={freshId} />
        </div>
      )}

      {/* In-iframe header — minimal and matched to the Day tab's section
          title typography (.stitle): Geist Mono, 10.5px, weight 500,
          letter-spacing .10em, uppercase, color var(--mu).  The dashboard's
          pagehead carries the page title; here we just surface the
          parameter count + view toggle. Mobile collapses the trailing
          status suffix so the line doesn't crowd the BRAIN/LIST toggle. */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, zIndex: 20,
        // Mobile reserves safe-area-inset-top so the iframe header
        // doesn't tuck under the iPhone status bar / notch. The
        // dashboard hides its own pagehead in brain-active mode, so the
        // brain page is responsible for its own top safe area.
        padding: (size && size.w < 480)
          ? "calc(14px + env(safe-area-inset-top, 0px)) 14px 10px"
          : "18px 22px 12px",
        display: "flex", alignItems: "center", gap: 10, pointerEvents: "none",
        background: view === "list" ? `linear-gradient(${mode === "dark" ? "#0a110fcc" : "#ffffffcc"}, transparent)` : "none",
        backdropFilter: view === "list" ? "blur(2px)" : "none" }}>
        <div style={{ pointerEvents: "auto", flexShrink: 0, display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ position: "relative", width: 6, height: 6, borderRadius: "50%", background: theme.known }}>
            <span className="lvRipple" key={freshTick} style={{ position: "absolute", inset: -3, borderRadius: "50%", border: `1px solid ${theme.known}` }}></span>
          </span>
          <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10.5, fontWeight: 500,
            letterSpacing: "0.10em", textTransform: "uppercase", color: theme.subText, whiteSpace: "nowrap" }}>
            {(size && size.w < 480)
              ? `${total} ${usingSample ? "demo" : "live"}`
              : `${total} parameters ${usingSample ? "· demo stream" : "· learning live"}`}
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

      {/* Toast — rounded rectangle (not a pill) so it reads as a quiet
          system note rather than a UI control. Inline format:
            ● confirmed · Protein habits
          Tiny status dot, mono verb caption, dot-separator, value in
          slightly brighter sans. One line on mobile so it barely takes
          any vertical space and never crashes into the top lobe. */}
      {(() => {
        const compact = size && size.w < 480;
        // Normalize the verb to a single word so the toast stays
        // one tight line. Maps the original sentence-style labels
        // (e.g. "Arnie noticed something new") to terse system-note
        // verbs (new / confirmed / updated).
        const verb = (() => {
          if (!toast || !toast.label) return "";
          const raw = toast.label.toLowerCase();
          if (raw.includes("noticed") || raw.includes("new")) return "new";
          if (raw.includes("confirmed")) return "confirmed";
          if (raw.includes("updated") || raw.includes("refined")) return "updated";
          return raw.replace(/^arnie\s+/, "").replace(/\s+your$/, "").split(/\s+/).pop();
        })();
        return (
          <div style={{ position: "absolute",
            top: compact ? 68 : 92,
            left: "50%",
            transform: `translateX(-50%) translateY(${toast ? 0 : -10}px)`,
            zIndex: 25, opacity: toast ? 0.94 : 0,
            transition: "all .38s cubic-bezier(.2,.9,.2,1)", pointerEvents: "none",
            display: "inline-flex", alignItems: "center",
            gap: compact ? 7 : 9,
            padding: compact ? "5px 11px 5px 9px" : "7px 14px 7px 11px",
            borderRadius: compact ? 8 : 10,
            maxWidth: "calc(100vw - 36px)",
            background: theme.cardBg,
            border: `1px solid ${theme.cardBorder}`,
            backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
            boxShadow: "0 6px 18px -10px rgba(0,0,0,0.45)" }}>
            {/* Quiet status dot — no pulse, no glow, just the colour. */}
            <span style={{
              width: 5, height: 5, borderRadius: "50%",
              background: theme.known, flexShrink: 0 }} />
            {/* Verb caption — tiny mono caps, muted. */}
            <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace",
              fontSize: compact ? 8.5 : 9, fontWeight: 500,
              letterSpacing: "0.12em", textTransform: "uppercase",
              color: theme.subText, opacity: 0.72,
              whiteSpace: "nowrap", flexShrink: 0 }}>
              {verb}
            </span>
            <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace",
              fontSize: compact ? 9 : 10, color: theme.subText,
              opacity: 0.35, flexShrink: 0 }}>·</span>
            {/* Value — same row, slightly brighter. Truncates with
                ellipsis so a long parameter label can't push the toast
                offscreen. */}
            <span style={{ fontFamily: "'Geist', system-ui, sans-serif",
              fontSize: compact ? 11 : 12, fontWeight: 500,
              color: theme.cardVal, letterSpacing: "-.003em",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              minWidth: 0 }}>
              {toast && toast.text}
            </span>
          </div>
        );
      })()}

      {/* Legend — three state dots + labels. Desktop keeps a vertical
          stack at the bottom-left; mobile uses a single subtle hairline
          row pinned to the safe-area bottom with mono caps that feel like
          a metadata footer rather than a UI control. */}
      {view === "brain" && !node && (() => {
        const compact = size && size.w < 480;
        const items = compact
          ? [["confirmed", "known"], ["inferred", "inferred"], ["learning", "learning"]]
          : [["confirmed", "confirmed"], ["inferred", "inferred from patterns"], ["learning", "needs verification"]];
        if (compact) {
          return (
            <div style={{ position: "absolute",
              left: 0, right: 0, bottom: "calc(10px + env(safe-area-inset-bottom, 0px))",
              zIndex: 15,
              display: "flex", justifyContent: "center", alignItems: "center",
              gap: 14,
              padding: 0,
              fontFamily: "'Geist Mono','SF Mono', monospace",
              fontSize: 9, fontWeight: 500, letterSpacing: "0.14em", textTransform: "uppercase",
              color: theme.subText, opacity: 0.55,
              pointerEvents: "none", whiteSpace: "nowrap" }}>
              {items.map(([st, txt]) => (
                <span key={st} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <span style={{ width: 4.5, height: 4.5, borderRadius: "50%", flexShrink: 0,
                    background: st === "confirmed" ? theme.known : "transparent",
                    border: st === "confirmed" ? "none" : `1.2px solid ${stateCol(st)}` }}></span>
                  {txt}
                </span>
              ))}
            </div>
          );
        }
        return (
          <div style={{ position: "absolute", left: 22, bottom: 18, zIndex: 15,
            display: "flex", flexDirection: "column", gap: 6,
            fontFamily: "'Geist', system-ui, sans-serif", fontSize: 10.5, color: theme.subText,
            opacity: 0.7, lineHeight: 1.4, pointerEvents: "none", whiteSpace: "nowrap" }}>
            {items.map(([st, txt]) => (
              <span key={st} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0,
                  background: st === "confirmed" ? theme.known : "transparent",
                  border: st === "confirmed" ? "none" : `1.3px solid ${stateCol(st)}` }}></span>{txt}
              </span>
            ))}
          </div>
        );
      })()}

      {/* First-visit welcome — small floating card anchored bottom-right.
          Explains the two interaction tiers (dot for one parameter, section
          label for the full lobe + AI coaching insight) and softly nudges
          the user back to Telegram. Dismissed once = gone forever. */}
      {view === "brain" && !welcomed && !stillLoading && !node && !selectedLobeId && (
        <div style={{ position: "absolute", right: 18, bottom: 18, zIndex: 18,
          width: "min(320px, calc(100vw - 36px))",
          background: theme.cardBg, border: `1px solid ${theme.cardBorder}`,
          borderRadius: 14, padding: "14px 16px 12px",
          backdropFilter: "blur(14px)",
          boxShadow: "0 18px 44px -18px rgba(0,0,0,0.5)",
          fontFamily: "'Geist', system-ui, sans-serif",
          animation: "lvWelcomeIn .5s ease-out both" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
            <span style={{ position: "relative", width: 8, height: 8, borderRadius: "50%",
              background: theme.known, boxShadow: `0 0 8px ${theme.known}`, flexShrink: 0, marginTop: 6 }}>
              <span className="lvRipple" style={{ position: "absolute", inset: -3, borderRadius: "50%",
                border: `1px solid ${theme.known}` }} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10,
                fontWeight: 500, letterSpacing: "0.10em", textTransform: "uppercase",
                color: theme.subText, marginBottom: 6 }}>
                Welcome to my brain
              </div>
              <div style={{ fontSize: 13, fontWeight: 400, color: theme.cardVal,
                lineHeight: 1.45, letterSpacing: "-.003em", textWrap: "pretty" }}>
                Each dot is something I've learned about you. <strong style={{ fontWeight: 600 }}>Tap any dot</strong> for the detail,
                or <strong style={{ fontWeight: 600 }}>tap a section like <span style={{ color: theme.known }}>Nutrition</span></strong> to see how it shapes my coaching.
                <br /><br />
                The more you message me on Telegram, the more this fills in.
              </div>
            </div>
            <button onClick={dismissWelcome} aria-label="Close welcome"
              style={{ width: 22, height: 22, borderRadius: 6, border: "none",
                background: "transparent", color: theme.iconText, cursor: "pointer",
                display: "grid", placeItems: "center", fontSize: 15, lineHeight: 1,
                opacity: 0.55, padding: 0, flexShrink: 0, marginTop: 2 }}>×</button>
          </div>
        </div>
      )}

      {/* Unlock gate — when Arnie knows less than 60% of the user, the
          constellation is shown faded behind a backdrop that blocks all
          interaction. Centred card explains what's missing, shows their
          progress to the unlock threshold, and gives them four concrete
          things to share with Arnie on Telegram. CTA opens the chat in a
          new tab. The gate disappears automatically once they cross 60%.

          We only gate the brain view — the LIST view is still accessible
          so users can audit what Arnie already knows. */}
      {view === "brain" && stillLoading && (() => {
        const botUsername = (() => {
          try { return new URLSearchParams(window.location.search).get("bot") || "arnie"; }
          catch (e) { return "arnie"; }
        })();
        const telegramHref = "tg://resolve?domain=" + botUsername.replace(/^@/, "");
        return (
          <>
            {/* Backdrop — lets the constellation peek through (faded teaser
                of what they're unlocking) while blocking all pointer events
                so dots/lobes aren't tappable until they cross 60%. */}
            <div onClick={(ev) => ev.stopPropagation()}
              onPointerDown={(ev) => ev.stopPropagation()}
              onWheel={(ev) => ev.stopPropagation()}
              style={{ position: "absolute", inset: 0, zIndex: 26,
                background: theme.name === "dark"
                  ? "radial-gradient(ellipse at center, rgba(8,12,18,0.30) 0%, rgba(8,12,18,0.62) 80%)"
                  : "radial-gradient(ellipse at center, rgba(245,247,250,0.30) 0%, rgba(245,247,250,0.62) 80%)",
                backdropFilter: "blur(10px) saturate(110%)",
                WebkitBackdropFilter: "blur(10px) saturate(110%)" }} />

            {/* Centred unlock card — compact, single-column rhythm. Small
                pulsing dot anchors the top instead of a heavy emblem; the
                progress bar is the visual centrepiece; chips collapse to a
                single comma-separated mono line; one solid CTA at the
                bottom. Everything reads as a focused unlock prompt rather
                than a marketing card. */}
            <div style={{ position: "absolute", inset: 0, zIndex: 27,
              display: "flex", alignItems: "center", justifyContent: "center",
              padding: "20px", pointerEvents: "none",
              animation: "lvWelcomeIn .55s ease-out both" }}>
              <div style={{ width: "min(360px, calc(100vw - 40px))",
                background: theme.name === "dark" ? "rgba(12,16,24,0.96)" : "rgba(255,255,255,0.98)",
                border: `1px solid ${theme.cardBorder}`,
                borderRadius: 14, padding: "20px 22px 18px",
                boxShadow: `0 30px 80px -28px rgba(0,0,0,0.7), 0 0 80px -32px ${theme.known}40`,
                fontFamily: "'Geist', system-ui, sans-serif",
                pointerEvents: "auto" }}>

                {/* Small pulsing dot + mono caption — single row */}
                <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 14 }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%",
                    background: theme.known, boxShadow: `0 0 6px ${theme.known}`,
                    animation: "lvThink 1.8s ease-in-out infinite", flexShrink: 0 }} />
                  <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 10,
                    fontWeight: 500, letterSpacing: "0.14em", textTransform: "uppercase",
                    color: theme.subText }}>
                    Brain · {confirmedPct}% loaded
                  </span>
                </div>

                {/* Headline + brief explainer */}
                <div style={{ fontSize: 18, fontWeight: 600, color: theme.cardVal,
                  letterSpacing: "-.012em", lineHeight: 1.22, marginBottom: 6 }}>
                  Teach me a little more
                </div>
                <div style={{ fontSize: 13, color: theme.subText, lineHeight: 1.5,
                  textWrap: "pretty", marginBottom: 16 }}>
                  I unlock at <strong style={{ color: theme.cardVal, fontWeight: 600 }}>60%</strong>.
                  Chat with me on Telegram — every thing you share fills a dot.
                </div>

                {/* Progress bar — slim, with the 60% tick + inline labels */}
                <div style={{ position: "relative", height: 4, borderRadius: 2,
                  background: `rgba(${theme.name === "dark" ? "255,255,255,0.07" : "0,0,0,0.07"})`,
                  overflow: "visible", marginBottom: 6 }}>
                  <div style={{ position: "absolute", left: 0, top: 0, bottom: 0,
                    width: `${confirmedPct}%`, background: theme.known,
                    boxShadow: `0 0 6px ${theme.known}`,
                    borderRadius: 2, transition: "width .6s ease" }} />
                  {/* 60% tick mark — minimal vertical line */}
                  <div style={{ position: "absolute", left: "60%", top: -3, bottom: -3,
                    width: 1, background: theme.subText, opacity: 0.5 }} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between",
                  fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 9,
                  fontWeight: 500, letterSpacing: "0.04em", color: theme.subText,
                  opacity: 0.6, marginBottom: 16 }}>
                  <span>{confirmedPct}%</span>
                  <span>60%</span>
                </div>

                {/* Suggested categories — single mono line, comma-separated,
                    so they read as quick prompts rather than a clickable
                    grid. Way more compact than chip pills. */}
                <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 9.5,
                  fontWeight: 500, letterSpacing: "0.10em", textTransform: "uppercase",
                  color: theme.subText, opacity: 0.7, marginBottom: 4 }}>
                  Try telling me about
                </div>
                <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace", fontSize: 11.5,
                  fontWeight: 500, color: theme.cardVal, lineHeight: 1.5,
                  marginBottom: 18 }}>
                  your sleep · foods you avoid ·<br />
                  training rhythm · what you're chasing
                </div>

                {/* Telegram CTA — single solid pill, full width inside card */}
                <a href={telegramHref} target="_blank" rel="noopener noreferrer"
                  style={{ display: "flex", alignItems: "center", justifyContent: "center",
                    gap: 8, width: "100%", boxSizing: "border-box",
                    padding: "10px 18px", borderRadius: 10,
                    background: theme.known, color: theme.name === "dark" ? "#062818" : "#ffffff",
                    fontFamily: "'Geist', system-ui, sans-serif",
                    fontSize: 13, fontWeight: 600, letterSpacing: "-.005em",
                    textDecoration: "none",
                    boxShadow: `0 4px 18px -6px ${theme.known}`,
                    transition: "transform .18s, box-shadow .18s" }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-1px)";
                    e.currentTarget.style.boxShadow = `0 8px 24px -6px ${theme.known}, 0 0 28px -10px ${theme.known}`;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "translateY(0)";
                    e.currentTarget.style.boxShadow = `0 4px 18px -6px ${theme.known}`;
                  }}>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
                    <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.24 3.64 11.94c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/>
                  </svg>
                  Open Telegram
                </a>
              </div>
            </div>
          </>
        );
      })()}

      {/* Lobe insights panel — slides in from the right when a lobe label is
          tapped. Shows every parameter in the cluster + how Arnie uses them
          to shape coaching. Backdrop dims the constellation. */}
      <LobeInsightsPanel lobe={lobes.find((l) => l.id === selectedLobeId)} theme={theme}
        onClose={() => setSelectedLobeId(null)} stateMeta={stateMeta} stateCol={stateCol} />

      {/* Node detail card — floats above (or below) the tapped dot, not
          pinned to the bottom of the screen. As the card opens, the dots
          immediately around it scatter outward to clear a pocket of space
          (handled inside BrainConstellationLive via cardCenter/cardRadius).
          Click outside or the × button to dismiss; the "View all →" footer
          escalates to the full lobe panel. */}
      {view === "brain" && (() => {
        const compact = size && size.w < 480;
        // Mobile cards now span nearly the full viewport (12px gutter
        // each side) so info has room to lay out horizontally — chip
        // groups, spec lines, escalation can all sit closer to their
        // labels. Desktop stays as a focused 320px floating card.
        const stageW = (size && size.w) || 0;
        const cardW = compact ? Math.min(stageW - 24, 360) : 320;
        const stageH = (size && size.h) || 0;
        const px = selectedPos ? selectedPos.x : (stageW / 2);
        const py = selectedPos ? selectedPos.y : (stageH / 2);
        // Place card above when the dot is in the lower half of the stage,
        // else below — keeps it from running off the edge.
        const placeAbove = py > stageH * 0.55;
        const cardMaxH = compact ? 220 : 300;
        const gap = compact ? 24 : 32;
        // Clamp horizontal centre so card never bleeds past the viewport.
        const halfW = cardW / 2;
        const cx = compact
          ? (stageW / 2)
          : Math.max(halfW + 10, Math.min(stageW - halfW - 10, px));
        return (
          <div onClick={() => { setSelectedId(null); setSelectedPos(null); }}
            style={{ position: "absolute", inset: 0, zIndex: 22,
              pointerEvents: node ? "auto" : "none" }}>
            <div onClick={(e) => e.stopPropagation()} style={{
              position: "absolute",
              left: cx, top: py,
              transform: `translate(-50%, ${placeAbove ? `calc(-100% - ${gap}px)` : `${gap}px`}) translateY(${node ? 0 : (placeAbove ? -8 : 8)}px)`,
              width: cardW,
              background: theme.cardBg, border: `1px solid ${theme.cardBorder}`,
              borderRadius: compact ? 10 : 14,
              backdropFilter: "blur(14px)",
              boxShadow: "0 18px 44px -18px rgba(0,0,0,0.5)",
              padding: node ? (compact ? "9px 12px 8px" : "13px 15px 11px") : 0,
              maxHeight: node ? cardMaxH : 0, opacity: node ? 1 : 0,
              overflow: "hidden",
              transition: "all .22s cubic-bezier(.4,0,.2,1)",
              cursor: "default" }}>
              {node && (
                <>
                  {/* Header — quiet metadata strip. Tiny state dot, lobe
                      name in muted mono caps, close × on the far right.
                      No state badge — the dot colour already says it and
                      the visual weight belongs to the value below. */}
                  <div style={{ display: "flex", alignItems: "center",
                    gap: compact ? 7 : 8,
                    marginBottom: compact ? 8 : 10 }}>
                    <span style={{ width: 5.5, height: 5.5, borderRadius: "50%", flexShrink: 0,
                      background: node.state === "confirmed" ? theme.known : "transparent",
                      border: node.state === "confirmed" ? "none" : `1.3px solid ${stateCol(node.state)}` }}></span>
                    <span style={{ fontFamily: "'Geist Mono','SF Mono', monospace",
                      fontSize: compact ? 9 : 9.5, fontWeight: 500,
                      letterSpacing: "0.16em", textTransform: "uppercase",
                      color: theme.subText, opacity: 0.7,
                      flex: 1, minWidth: 0,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {node.lobe}
                    </span>
                    <button onClick={() => { setSelectedId(null); setSelectedPos(null); }} aria-label="Close" style={{
                      width: compact ? 18 : 20, height: compact ? 18 : 20,
                      borderRadius: 4, border: "none", background: "transparent",
                      color: theme.iconText, cursor: "pointer", display: "grid", placeItems: "center",
                      fontSize: compact ? 13 : 14, lineHeight: 1, opacity: 0.4, padding: 0, flexShrink: 0 }}>×</button>
                  </div>

                  {/* Title + value rhythm — exploded chip vs regular slot.
                      Title takes the visual weight; spec sits right under
                      it as a soft sub-line; parent caption tucked above
                      the sibling chips as the smallest hint. */}
                  {node.parentLabel ? (
                    <>
                      <div style={{ fontFamily: "'Geist', system-ui, sans-serif",
                        fontSize: compact ? 15 : 22, fontWeight: 600,
                        color: theme.cardVal, lineHeight: 1.15, letterSpacing: "-.013em",
                        marginBottom: node.spec ? (compact ? 2 : 5) : (compact ? 6 : 12),
                        overflow: "hidden", textOverflow: "ellipsis",
                        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>{node.label}</div>
                      {node.spec && (
                        <div style={{ fontFamily: "'Geist', system-ui, sans-serif",
                          fontSize: compact ? 11 : 13, fontWeight: 400,
                          color: theme.subText, opacity: 0.9, lineHeight: 1.3,
                          letterSpacing: "-.003em",
                          marginBottom: compact ? 7 : 11,
                          overflow: "hidden", textOverflow: "ellipsis",
                          display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>{node.spec}</div>
                      )}
                      <div style={{ fontFamily: "'Geist Mono','SF Mono', monospace",
                        fontSize: 8.5, fontWeight: 500,
                        letterSpacing: "0.14em", textTransform: "uppercase", color: theme.subText,
                        opacity: 0.5,
                        marginBottom: compact ? 4 : 7 }}>
                        {node.parentLabel}
                      </div>
                      {(() => {
                        const parent = lobes.find((l) => l.id === node.lobeId);
                        if (!parent) return null;
                        const siblings = parent.nodes.filter((s) => s.parentLabel === node.parentLabel);
                        if (siblings.length < 2) return null;
                        // On mobile with many siblings, show first 3 + "+N"
                        const visible = compact && siblings.length > 4 ? siblings.slice(0, 3) : siblings;
                        const hiddenCount = siblings.length - visible.length;
                        return (
                          <div style={{ display: "flex", flexWrap: "wrap", gap: compact ? 5 : 6 }}>
                            {visible.map((s) => {
                              const isCurrent = s.id === node.id;
                              return (
                                <span key={s.id} style={{
                                  fontFamily: "'Geist', system-ui, sans-serif",
                                  fontSize: compact ? 11 : 12, fontWeight: 500, letterSpacing: "-.005em",
                                  color: isCurrent ? theme.known : theme.cardVal,
                                  background: isCurrent ? `${theme.known}14` : (theme.name === "dark" ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)"),
                                  border: `1px solid ${isCurrent ? theme.known + "88" : "transparent"}`,
                                  borderRadius: 999,
                                  padding: compact ? "3px 9px" : "4px 11px",
                                  whiteSpace: "nowrap",
                                  transition: "all .18s ease",
                                  display: "inline-flex", alignItems: "center", gap: compact ? 5 : 6 }}>
                                  {isCurrent && (
                                    <span style={{ width: 4, height: 4, borderRadius: "50%",
                                      flexShrink: 0, background: theme.known,
                                      boxShadow: `0 0 5px ${theme.known}` }} />
                                  )}
                                  {s.label}
                                </span>
                              );
                            })}
                            {hiddenCount > 0 && (
                              <span style={{
                                fontFamily: "'Geist Mono','SF Mono', monospace",
                                fontSize: compact ? 10 : 11, fontWeight: 500, letterSpacing: "0.02em",
                                color: theme.subText, opacity: 0.55,
                                alignSelf: "center", padding: "3px 6px" }}>
                                +{hiddenCount}
                              </span>
                            )}
                          </div>
                        );
                      })()}
                    </>
                  ) : (
                    <>
                      <div style={{ fontFamily: "'Geist', system-ui, sans-serif",
                        fontSize: compact ? 11 : 13, fontWeight: 400,
                        letterSpacing: "-.003em", color: theme.subText,
                        opacity: 0.85,
                        marginBottom: compact ? 2 : 6 }}>{node.label}</div>
                      {node.value ? (
                        <div style={{ fontFamily: "'Geist', system-ui, sans-serif",
                          fontSize: compact ? 16 : 20, fontWeight: 600,
                          color: theme.cardVal, lineHeight: 1.22, letterSpacing: "-.012em",
                          textWrap: "pretty",
                          overflow: "hidden", textOverflow: "ellipsis",
                          display: "-webkit-box", WebkitLineClamp: compact ? 3 : 4, WebkitBoxOrient: "vertical" }}>{node.value}</div>
                      ) : null}
                    </>
                  )}

                  {/* Provenance footer — tiny mono caption with the
                      relative-time + source. Reads as system metadata. */}
                  {(node.date || node.source) && (
                    <div style={{
                      fontFamily: "'Geist Mono','SF Mono', monospace",
                      fontSize: 8.5, fontWeight: 500,
                      letterSpacing: "0.12em", textTransform: "uppercase",
                      color: theme.subText, opacity: 0.45,
                      marginTop: compact ? 6 : 12,
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {[
                        node.date ? (window.brainFormatRelTime(node.date) || node.date) : null,
                        node.source
                      ].filter(Boolean).join(" · ")}
                    </div>
                  )}

                  {/* Escalation row — small caption that opens the full
                      lobe panel. Lighter than before (subtle divider,
                      lowercase, no all-caps) so it doesn't compete with
                      the value above. */}
                  {node.lobeId && (() => {
                    const parent = lobes.find((l) => l.id === node.lobeId);
                    if (!parent) return null;
                    return (
                      <div style={{
                        borderTop: `1px solid ${theme.cardBorder}`,
                        marginTop: compact ? 7 : 13, paddingTop: compact ? 6 : 10,
                        opacity: 0.85 }}>
                        <button onClick={() => { setSelectedLobeId(node.lobeId); setSelectedId(null); setSelectedPos(null); }}
                          style={{ background: "transparent", border: "none", padding: 0, cursor: "pointer",
                            fontFamily: "'Geist', system-ui, sans-serif",
                            fontSize: compact ? 10.5 : 12, fontWeight: 500,
                            letterSpacing: "-.003em", color: theme.subText,
                            display: "inline-flex", alignItems: "center", gap: 4, transition: "color .15s" }}
                          onMouseEnter={(e) => { e.currentTarget.style.color = theme.cardVal; }}
                          onMouseLeave={(e) => { e.currentTarget.style.color = theme.subText; }}>
                          View all {parent.nodes.length}
                          <span aria-hidden="true" style={{ opacity: 0.6, marginLeft: 1 }}>→</span>
                        </button>
                      </div>
                    );
                  })()}
                </>
              )}
            </div>
          </div>
        );
      })()}
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

  /* Ripple wave on click — expanding rings + spark at origin. Uses
     transform:scale() so the size animates cleanly without depending on
     CSS variables inside @keyframes (which not every browser resolves).
     The element's intrinsic size is set inline via React, and the
     keyframe just scales it from 0 → 1. */
  @keyframes lvRippleRing {
    0%   { transform: translate(-50%,-50%) scale(0);   opacity: 0.85; }
    100% { transform: translate(-50%,-50%) scale(1);   opacity: 0; }
  }
  @keyframes lvRippleSpark {
    0%   { transform: translate(-50%,-50%) scale(0.5); opacity: 0.9; }
    100% { transform: translate(-50%,-50%) scale(4);   opacity: 0; }
  }
  .lvRippleRingA {
    animation: lvRippleRing var(--wave-dur, 1.1s) cubic-bezier(.25,.8,.3,1) forwards;
  }
  .lvRippleRingB {
    animation: lvRippleRing var(--wave-dur, 1.1s) cubic-bezier(.25,.8,.3,1) forwards;
    animation-delay: .08s;
  }
  .lvRipplePulse {
    animation: lvRippleSpark .55s ease-out forwards;
  }
  /* Welcome card entrance — gentle slide up + fade so it feels invited,
     not popped in. */
  @keyframes lvWelcomeIn {
    from { transform: translateY(14px); opacity: 0; }
    to   { transform: translateY(0); opacity: 1; }
  }

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
