// SnapGrade — Triage Screen
// Full filter panel: verdict, stars, quality scores, rejection flags,
// content type, scene, OCR, animals, colour (temp/sat/cast/dominant hue),
// camera, ISO, aperture, orientation, date range, filename, burst.

const { useState, useEffect, useCallback, useRef, useMemo } = React;

// ── Filter state ──────────────────────────────────────────────────────────────
const DEFAULT_FILTERS = {
  verdict:       'all',   // all | keeper | review | reject
  stars_min:     0,       // 0 = any
  sharpness_min: 0,       // 0..1
  aesthetic_min: 0,       // 0..1
  reason_blur:   false,
  reason_eyes:   false,
  reason_exposure: false,
  reason_tilt:   false,
  reason_cast:   false,
  content_type:  'all',   // all | photo | screenshot | document
  scene:         'all',
  has_ocr:       false,
  ocr_text:      '',
  has_animals:   false,
  temperature:   'all',   // all | warm | cool | neutral
  saturation:    'all',   // all | mono | muted | vivid
  cast_hue:      'all',   // all | red | green | blue
  hue_anchors:    [],     // [hueDeg, ...] — anchor hues to match against dominant colours
  hue_tolerance:  30,     // ±deg around each anchor (0..90)
  hue_min_sat:    0.15,   // ignore near-greyscale pixels below this saturation
  camera:        'all',
  iso:           'all',   // all | low | mid | high | extreme
  aperture:      'all',   // all | wide | mid | narrow
  orientation:   'all',   // all | landscape | portrait | square
  date_from:     '',
  date_to:       '',
  text_search:   '',
  burst_only:    false,
  burst_best:    false,
};

// ── Filter helpers ─────────────────────────────────────────────────────────────
function isoToBucket(iso) {
  if (!iso) return 'low';
  if (iso <= 200)  return 'low';
  if (iso <= 1600) return 'mid';
  if (iso <= 6400) return 'high';
  return 'extreme';
}
function apertureToBucket(f) {
  if (!f) return 'mid';
  if (f < 2.8)  return 'wide';
  if (f <= 5.6) return 'mid';
  return 'narrow';
}
function orientationOf(img) {
  const w = img.width || 0, h = img.height || 0;
  if (!w || !h) return 'landscape';
  if (Math.abs(w - h) <= Math.max(w, h) * 0.02) return 'square';
  return w > h ? 'landscape' : 'portrait';
}
// RGB → HSL (h in degrees, s/l in 0..1)
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h;
  if (max === r)      h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
  else if (max === g) h = ((b - r) / d + 2) / 6;
  else                h = ((r - g) / d + 4) / 6;
  return { h: h * 360, s, l };
}

// Circular hue distance in degrees
function hueDistance(a, b) {
  const d = Math.abs(a - b) % 360;
  return d > 180 ? 360 - d : d;
}

// True if any dominant colour of `img` falls within `tolerance` of any anchor
// (anchors must also clear the saturation floor to avoid matching greys).
function matchesHueAnchors(img, anchors, tolerance, minSat) {
  if (!anchors?.length) return true;
  const dom = img.color?.dominant || [];
  for (const [r, g, b] of dom) {
    const { h, s } = rgbToHsl(r, g, b);
    if (s < minSat) continue;
    for (const a of anchors) {
      if (hueDistance(h, a) <= tolerance) return true;
    }
  }
  return false;
}

function applyFilters(images, f) {
  return images.filter(img => {
    if (f.verdict !== 'all' && img.verdict !== f.verdict) return false;
    if (f.stars_min > 0 && (img.stars || 0) < f.stars_min) return false;
    if (f.sharpness_min > 0 && img.sharpness < f.sharpness_min) return false;
    if (f.aesthetic_min > 0 && (img.aesthetic_score || 0) < f.aesthetic_min) return false;
    if (f.reason_blur     && !img.reasons?.some(r => /focus|soft|blur/i.test(r))) return false;
    if (f.reason_eyes     && !img.reasons?.some(r => /eyes/i.test(r))) return false;
    if (f.reason_exposure && !img.reasons?.some(r => /exposed/i.test(r))) return false;
    if (f.reason_tilt     && !img.reasons?.some(r => /tilt/i.test(r))) return false;
    if (f.reason_cast     && !img.reasons?.some(r => /cast/i.test(r))) return false;
    if (f.content_type !== 'all' && (img.content_type || 'photo') !== f.content_type) return false;
    if (f.scene !== 'all' && img.scene !== f.scene) return false;
    if (f.has_ocr   && !(img.ocr?.length > 0)) return false;
    if (f.ocr_text  && !img.ocr?.some(r => r.text.toLowerCase().includes(f.ocr_text.toLowerCase()))) return false;
    if (f.has_animals && !(img.animals?.length > 0)) return false;
    if (f.temperature !== 'all' && img.color?.temperature !== f.temperature) return false;
    if (f.saturation  !== 'all' && img.color?.saturation  !== f.saturation)  return false;
    if (f.cast_hue    !== 'all' && img.color?.cast_hue    !== f.cast_hue)    return false;
    if (!matchesHueAnchors(img, f.hue_anchors, f.hue_tolerance, f.hue_min_sat)) return false;
    if (f.camera !== 'all' && img.camera_model !== f.camera) return false;
    if (f.iso    !== 'all' && isoToBucket(img.iso)       !== f.iso)    return false;
    if (f.aperture !== 'all' && apertureToBucket(img.f_number) !== f.aperture) return false;
    if (f.orientation !== 'all' && orientationOf(img) !== f.orientation) return false;
    if (f.date_from && img.capture_time < f.date_from) return false;
    if (f.date_to   && img.capture_time > f.date_to + 'T23:59:59') return false;
    if (f.text_search && !img.path.toLowerCase().includes(f.text_search.toLowerCase())) return false;
    if (f.burst_only && !img.burst_id) return false;
    if (f.burst_best && !img.is_best) return false;
    return true;
  });
}

// Active chips for the filterbar (excludes verdict which has its own UI)
function buildActiveChips(f, upd) {
  const d = DEFAULT_FILTERS;
  const c = [];
  if (f.stars_min > 0)
    c.push({ id:'stars',   label: `${f.stars_min}★+`,             clear: () => upd('stars_min', 0) });
  if (f.content_type !== d.content_type)
    c.push({ id:'ct',      label: f.content_type === 'screenshot' ? '🖥 screenshot' : '📄 document', clear: () => upd('content_type', 'all') });
  if (f.sharpness_min > 0)
    c.push({ id:'sharp',   label: `sharp≥${Math.round(f.sharpness_min*100)}%`,   clear: () => upd('sharpness_min', 0) });
  if (f.aesthetic_min > 0)
    c.push({ id:'aesth',   label: `aesth≥${Math.round(f.aesthetic_min*100)}%`,   clear: () => upd('aesthetic_min', 0) });
  if (f.scene !== d.scene)
    c.push({ id:'scene',   label: `⛰ ${f.scene}`,                 clear: () => upd('scene', 'all') });
  if (f.has_ocr)
    c.push({ id:'ocr',     label: 'has OCR',                       clear: () => upd('has_ocr', false) });
  if (f.ocr_text)
    c.push({ id:'ocrtxt',  label: `"${f.ocr_text}"`,              clear: () => upd('ocr_text', '') });
  if (f.has_animals)
    c.push({ id:'animals', label: '🐾 animals',                    clear: () => upd('has_animals', false) });
  if (f.temperature !== d.temperature)
    c.push({ id:'temp',    label: f.temperature,                   clear: () => upd('temperature', 'all') });
  if (f.saturation !== d.saturation)
    c.push({ id:'sat',     label: f.saturation,                    clear: () => upd('saturation', 'all') });
  if (f.cast_hue !== d.cast_hue)
    c.push({ id:'cast',    label: `${f.cast_hue} cast`,            clear: () => upd('cast_hue', 'all') });
  if (f.hue_anchors.length > 0) {
    c.push({
      id:'hues',
      label: `${f.hue_anchors.length} hue${f.hue_anchors.length>1?'s':''} ±${f.hue_tolerance}°`,
      clear: () => upd('hue_anchors', []),
    });
  }
  if (f.camera !== d.camera)
    c.push({ id:'cam',     label: f.camera.split(' ').slice(-1)[0], clear: () => upd('camera', 'all') });
  if (f.iso !== d.iso)
    c.push({ id:'iso',     label: `ISO:${f.iso}`,                  clear: () => upd('iso', 'all') });
  if (f.aperture !== d.aperture)
    c.push({ id:'apt',     label: `f/${f.aperture}`,               clear: () => upd('aperture', 'all') });
  if (f.orientation !== d.orientation)
    c.push({ id:'orient',  label: f.orientation,                   clear: () => upd('orientation', 'all') });
  if (f.reason_blur)     c.push({ id:'rblur', label:'blur',         clear: () => upd('reason_blur', false) });
  if (f.reason_eyes)     c.push({ id:'reyes', label:'eyes closed',  clear: () => upd('reason_eyes', false) });
  if (f.reason_exposure) c.push({ id:'rexp',  label:'exposure',     clear: () => upd('reason_exposure', false) });
  if (f.reason_tilt)     c.push({ id:'rtilt', label:'tilt',         clear: () => upd('reason_tilt', false) });
  if (f.reason_cast)     c.push({ id:'rcast', label:'colour cast',  clear: () => upd('reason_cast', false) });
  if (f.burst_only)      c.push({ id:'burst', label:'in burst',     clear: () => upd('burst_only', false) });
  if (f.burst_best)      c.push({ id:'best',  label:'best pick',    clear: () => upd('burst_best', false) });
  if (f.date_from)       c.push({ id:'dfrom', label:`from ${f.date_from.slice(5)}`, clear: () => upd('date_from', '') });
  if (f.date_to)         c.push({ id:'dto',   label:`to ${f.date_to.slice(5)}`,     clear: () => upd('date_to', '') });
  if (f.text_search)     c.push({ id:'txt',   label:`"${f.text_search}"`,           clear: () => upd('text_search', '') });
  return c;
}

// ── FilterPanel sub-components ────────────────────────────────────────────────
function FSection({ title, active, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ borderBottom: '1px solid var(--c-border)' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ width:'100%', display:'flex', justifyContent:'space-between', alignItems:'center',
                 padding:'9px 16px', background:'none', border:'none', cursor:'pointer',
                 fontSize:8, letterSpacing:'0.26em', textTransform:'uppercase',
                 color: active ? 'var(--c-accent)' : 'var(--c-mute)', fontFamily:'var(--font-ui)',
                 transition:'color .12s' }}
      >
        <span>{title}</span>
        <span style={{ fontSize:9, color:'var(--c-mute)', transition:'transform .15s',
                       transform: open ? 'none' : 'rotate(-90deg)', display:'inline-block' }}>▾</span>
      </button>
      {open && <div style={{ padding:'2px 16px 14px' }}>{children}</div>}
    </div>
  );
}

function FChip({ on, onClick, children, style = {} }) {
  return (
    <button onClick={onClick} style={{
      padding: '4px 10px', fontSize: 10,
      border: `1px solid ${on ? 'var(--c-accent)' : 'var(--c-border)'}`,
      color: on ? 'var(--c-accent)' : 'var(--c-text2)',
      background: on ? 'rgba(193,68,14,0.1)' : 'transparent',
      borderRadius: 'var(--radius)', cursor:'pointer', fontFamily:'var(--font-ui)',
      transition:'all .1s', ...style,
    }}>{children}</button>
  );
}

function FSlider({ label, value, min, max, step, onChange, fmt }) {
  const isDefault = value === min;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:4 }}>
        <span style={{ fontSize:10, color:'var(--c-text2)' }}>{label}</span>
        <span style={{ fontSize:11, fontFamily:'var(--font-display)', fontStyle:'italic',
                       color: isDefault ? 'var(--c-mute)' : 'var(--c-accent)' }}>
          {fmt ? fmt(value) : value}
        </span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        style={{ width:'100%', accentColor:'var(--c-accent)' }}
      />
    </div>
  );
}

function FLabel({ children }) {
  return (
    <div style={{ fontSize:8, letterSpacing:'0.22em', textTransform:'uppercase',
                  color:'var(--c-mute)', marginBottom:6, marginTop:10 }}>{children}</div>
  );
}

// ── Histogram with draggable threshold ────────────────────────────────────────
// Renders a 30-bar distribution of `values` (each 0..1) and lets the user drag
// the threshold marker to set the cutoff. Bins above the cutoff use `accent`;
// bins below are dimmed so the at-a-glance shape shows "what passes".
function Histogram({ values, threshold, onChange, label, accent = 'var(--c-keeper)' }) {
  const BINS = 30;
  const ref = useRef(null);
  const dragRef = useRef(false);
  // Stash the latest onChange in a ref so the window listeners stay stable
  // even when the parent passes a fresh closure on every render.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const counts = useMemo(() => {
    const c = new Array(BINS).fill(0);
    for (const v of values) {
      const idx = Math.min(BINS - 1, Math.max(0, Math.floor((v ?? 0) * BINS)));
      c[idx]++;
    }
    return c;
  }, [values]);
  const maxCount  = Math.max(1, ...counts);
  const passCount = useMemo(() => values.filter(v => (v ?? 0) >= threshold).length, [values, threshold]);

  function applyAt(clientX) {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    onChangeRef.current(Math.round(pct * 20) / 20);   // snap to 0.05
  }

  useEffect(() => {
    function up() { dragRef.current = false; }
    function move(e) {
      if (!dragRef.current || !ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      onChangeRef.current(Math.round(pct * 20) / 20);
    }
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    return () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
  }, []);

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:4 }}>
        <span style={{ fontSize:10, color:'var(--c-text2)' }}>{label}</span>
        <span style={{ fontSize:11, fontFamily:'var(--font-display)', fontStyle:'italic',
                       color: threshold === 0 ? 'var(--c-mute)' : 'var(--c-accent)' }}>
          {threshold === 0 ? 'any' : `≥${Math.round(threshold * 100)}%`}
        </span>
      </div>
      <div ref={ref}
        onMouseDown={e => { dragRef.current = true; applyAt(e.clientX); }}
        style={{ position:'relative', height:54, cursor:'col-resize', userSelect:'none',
                 background:'var(--c-bg)', border:'1px solid var(--c-border)',
                 borderRadius:'var(--radius)' }}
      >
        {counts.map((c, i) => {
          const passes = (i + 0.5) / BINS >= threshold;
          const h = c === 0 ? 0 : Math.max(2, (c / maxCount) * 50);
          return (
            <div key={i} style={{
              position:'absolute', left:`${i / BINS * 100}%`, width:`${100 / BINS}%`,
              bottom:0, height:h, paddingLeft:0.5, paddingRight:0.5,
              boxSizing:'border-box', pointerEvents:'none',
            }}>
              <div style={{
                width:'100%', height:'100%',
                background: passes ? accent : 'var(--c-border2)',
                opacity: passes ? 0.95 : 0.4,
                transition: 'opacity .12s, background .12s',
              }}/>
            </div>
          );
        })}
        {/* Threshold line */}
        <div style={{ position:'absolute', top:0, bottom:0, left:`${threshold * 100}%`,
                      width:2, marginLeft:-1, background:'var(--c-accent)', pointerEvents:'none' }}/>
        {/* Handle dot */}
        <div style={{ position:'absolute', top:-4, left:`${threshold * 100}%`,
                      width:11, height:11, marginLeft:-5.5,
                      background:'var(--c-accent)', borderRadius:'50%',
                      border:'2px solid var(--c-bg)', pointerEvents:'none' }}/>
      </div>
      <div style={{ display:'flex', justifyContent:'space-between',
                    fontSize:8, letterSpacing:'0.2em', textTransform:'uppercase',
                    color:'var(--c-mute)', marginTop:4, fontFamily:'var(--font-ui)' }}>
        <span>0%</span>
        <span style={{ color:'var(--c-text2)' }}>{passCount} of {values.length} pass</span>
        <span>100%</span>
      </div>
    </div>
  );
}

// ── TimelineScrubber: capture-time density + two draggable handles ────────────
// Bins frames into a 60-cell histogram of capture_time; the two handles drive
// date_from / date_to. Drag to the very edge to clear that bound.
function TimelineScrubber({ images, dateFrom, dateTo, onChange }) {
  const ref = useRef(null);
  const dragRef = useRef(null);  // 'from' | 'to' | null
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const dated = useMemo(() => {
    return images
      .map(i => i.capture_time ? new Date(i.capture_time).getTime() : NaN)
      .filter(t => !isNaN(t))
      .sort((a, b) => a - b);
  }, [images]);

  const minT = dated[0];
  const maxT = dated[dated.length - 1];
  const span = (maxT || 0) - (minT || 0);

  const BINS = 60;
  const counts = useMemo(() => {
    const c = new Array(BINS).fill(0);
    if (!span) return c;
    for (const t of dated) {
      const idx = Math.min(BINS - 1, Math.floor((t - minT) / span * BINS));
      c[idx]++;
    }
    return c;
  }, [dated, minT, span]);
  const maxCount = Math.max(1, ...counts);

  const fromT = dateFrom ? new Date(dateFrom).getTime() : (minT || 0);
  const toT   = dateTo   ? new Date(dateTo + 'T23:59:59').getTime() : (maxT || 0);
  const fromPct = span ? Math.max(0, Math.min(1, (fromT - minT) / span)) : 0;
  const toPct   = span ? Math.max(0, Math.min(1, (toT   - minT) / span)) : 1;

  useEffect(() => {
    function up() { dragRef.current = null; }
    function move(e) {
      if (!dragRef.current || !ref.current || !span) return;
      const rect = ref.current.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const ts = minT + pct * span;
      const iso = new Date(ts).toISOString().slice(0, 10);
      if (dragRef.current === 'from') {
        onChangeRef.current({ from: pct < 0.01 ? '' : iso });
      } else {
        onChangeRef.current({ to:   pct > 0.99 ? '' : iso });
      }
    }
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    return () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
  }, [minT, span]);

  if (dated.length < 2 || !span) return null;

  function onBgMouseDown(e) {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const handle = Math.abs(pct - fromPct) <= Math.abs(pct - toPct) ? 'from' : 'to';
    dragRef.current = handle;
    const ts = minT + pct * span;
    const iso = new Date(ts).toISOString().slice(0, 10);
    if (handle === 'from') onChange({ from: pct < 0.01 ? '' : iso });
    else                    onChange({ to:   pct > 0.99 ? '' : iso });
  }

  const fmt = ts => new Date(ts).toLocaleDateString('en-GB',
    { day: '2-digit', month: 'short', year: '2-digit' });
  const filterActive = !!(dateFrom || dateTo);

  return (
    <div style={{ padding:'8px 18px 6px', borderBottom:'1px solid var(--c-border)',
                  background:'var(--c-panel2)', flexShrink:0,
                  display:'flex', alignItems:'center', gap:16 }}>
      <div style={{ fontSize:8, letterSpacing:'0.28em', textTransform:'uppercase',
                    color: filterActive ? 'var(--c-accent)' : 'var(--c-mute)',
                    fontFamily:'var(--font-ui)', flexShrink:0, width:70 }}>Timeline</div>

      <div style={{ flex:1, position:'relative' }}>
        <div ref={ref} onMouseDown={onBgMouseDown}
          style={{ position:'relative', height:36, cursor:'col-resize', userSelect:'none',
                   background:'var(--c-bg)', border:'1px solid var(--c-border)',
                   borderRadius:'var(--radius)' }}
        >
          {counts.map((c, i) => {
            const binCenter = (i + 0.5) / BINS;
            const inRange = binCenter >= fromPct && binCenter <= toPct;
            const h = c === 0 ? 0 : Math.max(2, (c / maxCount) * 32);
            return (
              <div key={i} style={{
                position:'absolute', left:`${i / BINS * 100}%`, width:`${100 / BINS}%`,
                bottom:0, height:h, paddingLeft:0.5, paddingRight:0.5,
                boxSizing:'border-box', pointerEvents:'none',
              }}>
                <div style={{
                  width:'100%', height:'100%',
                  background: inRange ? 'var(--c-text2)' : 'var(--c-border2)',
                  opacity: inRange ? 0.85 : 0.35,
                }}/>
              </div>
            );
          })}
          {/* Selection band */}
          <div style={{ position:'absolute', top:0, bottom:0,
                        left:`${fromPct * 100}%`, width:`${(toPct - fromPct) * 100}%`,
                        background:'rgba(193,68,14,0.08)', pointerEvents:'none' }}/>
          {/* From handle */}
          <div onMouseDown={e => { e.stopPropagation(); dragRef.current = 'from'; }}
            style={{ position:'absolute', top:-3, bottom:-3, left:`${fromPct * 100}%`,
                     width:10, marginLeft:-5, background:'var(--c-accent)',
                     borderRadius:2, border:'1.5px solid var(--c-bg)',
                     cursor:'ew-resize', zIndex:2,
                     boxShadow:'0 1px 3px rgba(0,0,0,0.4)' }}/>
          {/* To handle */}
          <div onMouseDown={e => { e.stopPropagation(); dragRef.current = 'to'; }}
            style={{ position:'absolute', top:-3, bottom:-3, left:`${toPct * 100}%`,
                     width:10, marginLeft:-5, background:'var(--c-accent)',
                     borderRadius:2, border:'1.5px solid var(--c-bg)',
                     cursor:'ew-resize', zIndex:2,
                     boxShadow:'0 1px 3px rgba(0,0,0,0.4)' }}/>
        </div>
        <div style={{ display:'flex', justifyContent:'space-between',
                      fontSize:8, letterSpacing:'0.18em', textTransform:'uppercase',
                      color:'var(--c-mute)', marginTop:4, fontFamily:'var(--font-ui)' }}>
          <span style={{ color: dateFrom ? 'var(--c-accent)' : 'var(--c-mute)' }}>◀ {fmt(fromT)}</span>
          <span style={{ color:'var(--c-text2)' }}>{dated.length} dated frames</span>
          <span style={{ color: dateTo ? 'var(--c-accent)' : 'var(--c-mute)' }}>{fmt(toT)} ▶</span>
        </div>
      </div>

      {filterActive && (
        <button onClick={() => onChange({ from: '', to: '' })}
          style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase',
                   color:'var(--c-danger)', background:'none', border:'none',
                   cursor:'pointer', fontFamily:'var(--font-ui)', flexShrink:0 }}>
          reset ×
        </button>
      )}
    </div>
  );
}

// ── HuePicker — click-to-pin anchors on a hue strip ──────────────────────────
const NAMED_HUES = [
  { h:   0, label: 'Red',     css: 'hsl(0,80%,50%)' },
  { h:  30, label: 'Orange',  css: 'hsl(30,90%,55%)' },
  { h:  55, label: 'Yellow',  css: 'hsl(55,85%,55%)' },
  { h:  95, label: 'Lime',    css: 'hsl(95,60%,45%)' },
  { h: 140, label: 'Green',   css: 'hsl(140,55%,40%)' },
  { h: 175, label: 'Teal',    css: 'hsl(175,55%,40%)' },
  { h: 205, label: 'Sky',     css: 'hsl(205,75%,55%)' },
  { h: 235, label: 'Blue',    css: 'hsl(235,65%,55%)' },
  { h: 275, label: 'Purple',  css: 'hsl(275,55%,55%)' },
  { h: 315, label: 'Magenta', css: 'hsl(315,70%,55%)' },
];

function HuePicker({ anchors, tolerance, minSat, onChange }) {
  const stripRef = useRef(null);
  function addAnchorAt(clientX) {
    const rect = stripRef.current.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const h = Math.round(pct * 360);
    onChange({ anchors: [...anchors, h] });
  }
  function removeAnchor(i) {
    onChange({ anchors: anchors.filter((_, j) => j !== i) });
  }
  return (
    <div>
      {/* Quick named hues */}
      <div style={{ display:'flex', flexWrap:'wrap', gap:4, marginBottom:8 }}>
        {NAMED_HUES.map(n => (
          <button key={n.label}
            onClick={() => onChange({ anchors: [...anchors, n.h] })}
            title={`${n.label} (${n.h}°)`}
            style={{
              width: 22, height: 22, borderRadius: '50%', cursor: 'pointer',
              border: '1px solid rgba(0,0,0,0.3)', background: n.css,
              transition: 'transform .1s',
            }}
            onMouseOver={e => e.currentTarget.style.transform = 'scale(1.15)'}
            onMouseOut={e  => e.currentTarget.style.transform = 'scale(1)'}
          />
        ))}
      </div>

      {/* Continuous hue strip */}
      <div style={{ fontSize: 8, color: 'var(--c-mute)', letterSpacing: '0.2em',
                    textTransform: 'uppercase', marginBottom: 4 }}>
        Or click strip to pin a custom hue
      </div>
      <div ref={stripRef}
        onClick={e => addAnchorAt(e.clientX)}
        style={{
          position: 'relative', height: 24, marginBottom: 4, cursor: 'crosshair',
          borderRadius: 'var(--radius)',
          background: 'linear-gradient(to right, hsl(0,80%,50%), hsl(30,90%,55%), hsl(60,85%,55%), hsl(120,55%,45%), hsl(180,55%,45%), hsl(210,70%,55%), hsl(270,55%,55%), hsl(330,70%,55%), hsl(360,80%,50%))',
          border: '1px solid var(--c-border)',
        }}
      >
        {anchors.map((h, i) => (
          <button key={i}
            onClick={e => { e.stopPropagation(); removeAnchor(i); }}
            title={`${h}° · click to remove`}
            style={{
              position: 'absolute', top: -3, bottom: -3,
              left: `${(h / 360) * 100}%`, transform: 'translateX(-50%)',
              width: 8, padding: 0, background: `hsl(${h},80%,55%)`,
              border: '2px solid var(--c-bg)', borderRadius: 2, cursor: 'pointer',
              boxShadow: '0 0 0 1px var(--c-accent)',
            }}
          />
        ))}
      </div>

      {/* Anchor chips */}
      {anchors.length > 0 && (
        <div style={{ display:'flex', flexWrap:'wrap', gap:4, marginTop:8 }}>
          {anchors.map((h, i) => (
            <button key={i} onClick={() => removeAnchor(i)}
              style={{
                display:'inline-flex', alignItems:'center', gap:6,
                padding:'2px 8px 2px 4px', fontSize:10,
                background: 'var(--c-bg)', border:'1px solid var(--c-border2)',
                borderRadius:'var(--radius)', cursor:'pointer', color:'var(--c-text2)',
                fontFamily:'var(--font-ui)',
              }}>
              <span style={{ width:12, height:12, borderRadius:'50%',
                              background:`hsl(${h},80%,55%)`,
                              border:'1px solid rgba(0,0,0,0.3)' }} />
              {h}°
              <span style={{ opacity:0.6, fontSize:11 }}>×</span>
            </button>
          ))}
          <button onClick={() => onChange({ anchors: [] })}
            style={{ fontSize:9, color:'var(--c-danger)', background:'none',
                     border:'none', cursor:'pointer', letterSpacing:'0.14em',
                     textTransform:'uppercase', fontFamily:'var(--font-ui)' }}>
            clear all
          </button>
        </div>
      )}

      {/* Tolerance + saturation sliders */}
      <div style={{ marginTop: 12 }}>
        <FSlider label="Hue tolerance" value={tolerance} min={5} max={90} step={5}
          onChange={v => onChange({ tolerance: v })}
          fmt={v => `±${v}°`} />
        <FSlider label="Min saturation" value={minSat} min={0} max={0.6} step={0.05}
          onChange={v => onChange({ hue_min_sat: v })}
          fmt={v => v === 0 ? 'any' : `≥${Math.round(v * 100)}%`} />
      </div>
    </div>
  );
}

// ── FilterPanel ───────────────────────────────────────────────────────────────
function FilterPanel({ filters: f, setFilters, images, onClose }) {
  const upd    = useCallback((k, v) => setFilters(prev => ({ ...prev, [k]: v })), [setFilters]);
  const toggle = useCallback(k => setFilters(prev => ({ ...prev, [k]: !prev[k] })), [setFilters]);

  const cameras = useMemo(() => [...new Set(images.map(i => i.camera_model).filter(Boolean))], [images]);
  const scenes  = useMemo(() => [...new Set(images.map(i => i.scene).filter(Boolean))].sort(), [images]);

  return (
    <div style={{ width:268, flexShrink:0, borderRight:'1px solid var(--c-border)',
                  background:'var(--c-panel)', display:'flex', flexDirection:'column',
                  overflow:'hidden' }}>
      {/* Header */}
      <div style={{ padding:'11px 16px', borderBottom:'1px solid var(--c-border)',
                    display:'flex', alignItems:'center', justifyContent:'space-between', flexShrink:0 }}>
        <span style={{ fontSize:9, letterSpacing:'0.28em', textTransform:'uppercase',
                       color:'var(--c-text)', fontFamily:'var(--font-ui)' }}>Filters</span>
        <div style={{ display:'flex', gap:10, alignItems:'center' }}>
          <button onClick={() => setFilters(DEFAULT_FILTERS)}
            style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase',
                     color:'var(--c-danger)', background:'none', border:'none',
                     cursor:'pointer', fontFamily:'var(--font-ui)' }}>
            Clear all
          </button>
          <button onClick={onClose}
            style={{ color:'var(--c-mute)', background:'none', border:'none',
                     cursor:'pointer', fontSize:16, lineHeight:1 }}>✕</button>
        </div>
      </div>

      {/* Body */}
      <div className="sg-scroll" style={{ flex:1 }}>

        {/* Stars */}
        <FSection title="Stars" active={f.stars_min > 0}>
          <FLabel>Minimum rating</FLabel>
          <div style={{ display:'flex', gap:4, alignItems:'center' }}>
            <FChip on={f.stars_min === 0} onClick={() => upd('stars_min', 0)}>Any</FChip>
            {[1,2,3,4,5].map(s => (
              <button key={s} onClick={() => upd('stars_min', s)} style={{
                fontSize:18, color: s <= f.stars_min ? 'var(--c-amber)' : 'var(--c-border2)',
                background:'none', border:'none', cursor:'pointer', padding:'0 1px',
                transition:'color .1s',
              }}>★</button>
            ))}
          </div>
        </FSection>

        {/* Quality scores */}
        <FSection title="Quality scores" active={f.sharpness_min > 0 || f.aesthetic_min > 0}>
          <Histogram
            label="Sharpness distribution"
            values={images.map(i => i.sharpness ?? 0)}
            threshold={f.sharpness_min}
            onChange={v => upd('sharpness_min', v)}
            accent="var(--c-keeper)"
          />
          <Histogram
            label="Aesthetic distribution"
            values={images.map(i => i.aesthetic_score ?? 0)}
            threshold={f.aesthetic_min}
            onChange={v => upd('aesthetic_min', v)}
            accent="var(--c-amber)"
          />
        </FSection>

        {/* Rejection flags */}
        <FSection title="Rejection flags" active={f.reason_blur || f.reason_eyes || f.reason_exposure || f.reason_tilt || f.reason_cast}
                  defaultOpen={false}>
          {[
            { key:'reason_blur',     label:'Blur / out of focus' },
            { key:'reason_eyes',     label:'Eyes closed' },
            { key:'reason_exposure', label:'Bad exposure' },
            { key:'reason_tilt',     label:'Horizon tilt' },
            { key:'reason_cast',     label:'Colour cast' },
          ].map(({ key, label }) => (
            <label key={key} style={{ display:'flex', alignItems:'center', gap:8, marginBottom:7, cursor:'pointer' }}>
              <input type="checkbox" checked={f[key]} onChange={() => toggle(key)} style={{ accentColor:'var(--c-accent)' }} />
              <span style={{ fontSize:11, color: f[key] ? 'var(--c-text)' : 'var(--c-text2)' }}>{label}</span>
            </label>
          ))}
        </FSection>

        {/* Content */}
        <FSection title="Content" active={f.content_type !== 'all' || f.scene !== 'all' || f.has_ocr || !!f.ocr_text || f.has_animals}>
          <FLabel>Type</FLabel>
          <div style={{ display:'flex', flexWrap:'wrap', gap:4, marginBottom:2 }}>
            {[['all','All'],['photo','🖼 Photo'],['screenshot','🖥 Screen'],['document','📄 Doc']].map(([v,l]) => (
              <FChip key={v} on={f.content_type === v} onClick={() => upd('content_type', v)}>{l}</FChip>
            ))}
          </div>

          <FLabel>Scene</FLabel>
          <select value={f.scene} onChange={e => upd('scene', e.target.value)}
            className="sg-select" style={{ fontSize:11, marginBottom:4 }}>
            <option value="all">All scenes</option>
            {scenes.map(s => <option key={s} value={s}>{s}</option>)}
          </select>

          <FLabel>Signals</FLabel>
          <label style={{ display:'flex', alignItems:'center', gap:8, marginBottom:7, cursor:'pointer' }}>
            <input type="checkbox" checked={f.has_ocr} onChange={() => toggle('has_ocr')} style={{ accentColor:'var(--c-accent)' }} />
            <span style={{ fontSize:11, color:'var(--c-text2)' }}>Has OCR text</span>
          </label>
          {f.has_ocr && (
            <input type="text" value={f.ocr_text} placeholder="Search within OCR text…"
              onChange={e => upd('ocr_text', e.target.value)}
              style={{ width:'100%', background:'var(--c-bg)', border:'1px solid var(--c-border)',
                       color:'var(--c-text)', padding:'6px 10px', fontSize:11,
                       fontFamily:'var(--font-ui)', borderRadius:'var(--radius)',
                       boxSizing:'border-box', marginBottom:8 }} />
          )}
          <label style={{ display:'flex', alignItems:'center', gap:8, cursor:'pointer' }}>
            <input type="checkbox" checked={f.has_animals} onChange={() => toggle('has_animals')} style={{ accentColor:'var(--c-accent)' }} />
            <span style={{ fontSize:11, color:'var(--c-text2)' }}>🐾 Has animals</span>
          </label>
        </FSection>

        {/* Colour */}
        <FSection title="Colour" active={f.temperature !== 'all' || f.saturation !== 'all' || f.cast_hue !== 'all' || f.hue_anchors.length > 0}>
          <FLabel>Dominant hue anchors</FLabel>
          <HuePicker
            anchors={f.hue_anchors}
            tolerance={f.hue_tolerance}
            minSat={f.hue_min_sat}
            onChange={changes => {
              if (changes.anchors !== undefined)   upd('hue_anchors',   changes.anchors);
              if (changes.tolerance !== undefined) upd('hue_tolerance', changes.tolerance);
              if (changes.hue_min_sat !== undefined) upd('hue_min_sat',  changes.hue_min_sat);
            }}
          />

          <FLabel>Temperature</FLabel>
          <div style={{ display:'flex', flexWrap:'wrap', gap:4, marginBottom:2 }}>
            {[['all','—'],['warm','Warm'],['neutral','Neutral'],['cool','Cool']].map(([v,l]) => (
              <FChip key={v} on={f.temperature === v} onClick={() => upd('temperature', v)}>{l}</FChip>
            ))}
          </div>

          <FLabel>Saturation</FLabel>
          <div style={{ display:'flex', flexWrap:'wrap', gap:4, marginBottom:2 }}>
            {[['all','—'],['mono','Mono'],['muted','Muted'],['vivid','Vivid']].map(([v,l]) => (
              <FChip key={v} on={f.saturation === v} onClick={() => upd('saturation', v)}>{l}</FChip>
            ))}
          </div>

          <FLabel>Colour cast</FLabel>
          <div style={{ display:'flex', gap:4 }}>
            {[['all','None'],['red','Red'],['green','Green'],['blue','Blue']].map(([v,l]) => (
              <FChip key={v} on={f.cast_hue === v} onClick={() => upd('cast_hue', v)}>{l}</FChip>
            ))}
          </div>
        </FSection>

        {/* Camera & EXIF */}
        <FSection title="Camera & EXIF" active={f.camera !== 'all' || f.iso !== 'all' || f.aperture !== 'all' || f.orientation !== 'all'}
                  defaultOpen={false}>
          <FLabel>Camera</FLabel>
          <select value={f.camera} onChange={e => upd('camera', e.target.value)}
            className="sg-select" style={{ fontSize:11, marginBottom:4 }}>
            <option value="all">All cameras</option>
            {cameras.map(c => <option key={c} value={c}>{c}</option>)}
          </select>

          <FLabel>ISO</FLabel>
          <div style={{ display:'flex', flexWrap:'wrap', gap:4, marginBottom:2 }}>
            {[['all','All'],['low','≤200'],['mid','201–1600'],['high','1601–6400'],['extreme','>6400']].map(([v,l]) => (
              <FChip key={v} on={f.iso === v} onClick={() => upd('iso', v)} style={{ fontSize:9 }}>{l}</FChip>
            ))}
          </div>

          <FLabel>Aperture</FLabel>
          <div style={{ display:'flex', flexWrap:'wrap', gap:4, marginBottom:2 }}>
            {[['all','All'],['wide','Wide <f/2.8'],['mid','f/2.8–5.6'],['narrow','Narrow >f/5.6']].map(([v,l]) => (
              <FChip key={v} on={f.aperture === v} onClick={() => upd('aperture', v)} style={{ fontSize:9 }}>{l}</FChip>
            ))}
          </div>

          <FLabel>Orientation</FLabel>
          <div style={{ display:'flex', gap:4 }}>
            {[['all','All'],['landscape','Landscape'],['portrait','Portrait'],['square','Square']].map(([v,l]) => (
              <FChip key={v} on={f.orientation === v} onClick={() => upd('orientation', v)}>{l}</FChip>
            ))}
          </div>
        </FSection>

        {/* Date */}
        <FSection title="Date range" active={!!(f.date_from || f.date_to)} defaultOpen={false}>
          {[['date_from','From'],['date_to','To']].map(([key, label]) => (
            <div key={key} style={{ marginBottom:10 }}>
              <label style={{ fontSize:10, color:'var(--c-mute)', display:'block', marginBottom:4 }}>{label}</label>
              <input type="date" value={f[key]} onChange={e => upd(key, e.target.value)}
                style={{ width:'100%', background:'var(--c-bg)', border:'1px solid var(--c-border)',
                         color:'var(--c-text)', padding:'6px 10px', fontSize:11,
                         fontFamily:'var(--font-ui)', borderRadius:'var(--radius)',
                         boxSizing:'border-box', colorScheme:'dark' }} />
            </div>
          ))}
        </FSection>

        {/* Text & Burst */}
        <FSection title="Text & Burst" active={!!(f.text_search || f.burst_only || f.burst_best)} defaultOpen={false}>
          <FLabel>Filename / path</FLabel>
          <input type="text" value={f.text_search} placeholder="e.g. DSC_0042"
            onChange={e => upd('text_search', e.target.value)}
            style={{ width:'100%', background:'var(--c-bg)', border:'1px solid var(--c-border)',
                     color:'var(--c-text)', padding:'6px 10px', fontSize:11,
                     fontFamily:'var(--font-ui)', borderRadius:'var(--radius)',
                     boxSizing:'border-box', marginBottom:10 }} />
          <label style={{ display:'flex', alignItems:'center', gap:8, marginBottom:7, cursor:'pointer' }}>
            <input type="checkbox" checked={f.burst_only} onChange={() => { toggle('burst_only'); if (f.burst_only) upd('burst_best', false); }} style={{ accentColor:'var(--c-accent)' }} />
            <span style={{ fontSize:11, color:'var(--c-text2)' }}>In a burst group</span>
          </label>
          <label style={{ display:'flex', alignItems:'center', gap:8, cursor:'pointer' }}>
            <input type="checkbox" checked={f.burst_best} disabled={!f.burst_only} onChange={() => toggle('burst_best')} style={{ accentColor:'var(--c-accent)' }} />
            <span style={{ fontSize:11, color: f.burst_only ? 'var(--c-text2)' : 'var(--c-mute)' }}>Best pick only</span>
          </label>
        </FSection>

      </div>
    </div>
  );
}

// ── Thumbnail components ──────────────────────────────────────────────────────
function VerdictMark({ verdict }) {
  if (verdict === 'reject') return (
    <svg viewBox="0 0 100 100" style={{ position:'absolute', inset:0, width:'100%', height:'100%', pointerEvents:'none' }}>
      <line x1="8" y1="8" x2="92" y2="92" stroke="var(--c-danger)" strokeWidth="3" opacity="0.75" />
      <line x1="92" y1="8" x2="8" y2="92" stroke="var(--c-danger)" strokeWidth="3" opacity="0.75" />
    </svg>
  );
  if (verdict === 'keeper') return (
    <div style={{ position:'absolute', top:10, right:10, width:28, height:28, borderRadius:'50%', border:'2px solid var(--c-keeper)', opacity:0.85, pointerEvents:'none' }} />
  );
  if (verdict === 'review') return (
    <div style={{ position:'absolute', top:6, right:10, fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:34, lineHeight:1, color:'var(--c-amber)', opacity:0.85, pointerEvents:'none' }}>?</div>
  );
  return null;
}

function ThumbCard({ item, selected, idx, onClick, onDoubleClick }) {
  return (
    <button onClick={onClick} onDoubleClick={onDoubleClick}
      className={`sg-thumb ${selected ? 'sel' : ''}`}
      style={{ animationDelay:`${Math.min(idx,30)*16}ms`, outline: selected ? '2px solid var(--c-accent)' : 'none', outlineOffset:-2 }}
    >
      {item.is_best && <span className="sg-thumb-best">Best</span>}
      <div style={{ position:'relative' }}>
        <img loading="lazy" src={item.thumb} alt=""
          style={{ display:'block', width:'100%', height:160, objectFit:'cover', filter:'contrast(1.03) saturate(0.92)' }} />
        <VerdictMark verdict={item.verdict} />
        {/* Content-type badge */}
        {item.content_type && item.content_type !== 'photo' && (
          <div style={{ position:'absolute', top:6, left:6, background: item.content_type === 'screenshot' ? 'var(--c-amber)' : 'var(--c-accent)', color: item.content_type === 'screenshot' ? '#111' : 'var(--c-bg)', fontSize:7, letterSpacing:'0.18em', textTransform:'uppercase', padding:'2px 6px', fontFamily:'var(--font-ui)', zIndex:2, borderRadius:'calc(var(--radius) + 1px)' }}>
            {item.content_type === 'screenshot' ? '🖥' : '📄'} {item.content_type}
          </div>
        )}
        {/* Dominant colour bar */}
        {item.color?.dominant?.length > 0 && (
          <div style={{ position:'absolute', bottom:30, left:0, right:0, height:3, display:'flex' }}>
            {item.color.dominant.map(([r,g,b], i) => (
              <div key={i} style={{ flex:1, background:`rgb(${r},${g},${b})` }} />
            ))}
          </div>
        )}
        {/* OCR / animals micro-badges */}
        {(item.ocr?.length > 0 || item.animals?.length > 0) && (
          <div style={{ position:'absolute', bottom:33, right:5, display:'flex', gap:3 }}>
            {item.animals?.length > 0 && (
              <div style={{ background:'rgba(0,0,0,0.6)', color:'var(--c-text)', fontSize:7, padding:'1px 5px', borderRadius:'calc(var(--radius)+1px)', fontFamily:'var(--font-ui)' }}>🐾</div>
            )}
            {item.ocr?.length > 0 && (
              <div style={{ background:'rgba(0,0,0,0.6)', color:'var(--c-amber)', fontSize:7, padding:'1px 5px', letterSpacing:'0.14em', textTransform:'uppercase', borderRadius:'calc(var(--radius)+1px)', fontFamily:'var(--font-ui)' }}>OCR</div>
            )}
          </div>
        )}
      </div>
      <div className="sg-thumb-strip">
        <span style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:15, color:'var(--c-accent)' }}>№{pad(item.id,4)}</span>
        <span style={{ letterSpacing:0, color:'var(--c-amber)', fontSize:11 }}>{'★'.repeat(item.stars||0)}{'·'.repeat(5-(item.stars||0))}</span>
      </div>
      <div style={{ height:2, background: item.verdict==='keeper'?'var(--c-keeper)':item.verdict==='review'?'var(--c-amber)':item.verdict==='reject'?'var(--c-danger)':'transparent' }} />
    </button>
  );
}

// ── Library rail ──────────────────────────────────────────────────────────────
function LibRail({ libraries, activeLib, setActiveLib }) {
  const all = libraries.reduce((a,l)=>a+l.image_count,0);
  return (
    <div className="sg-lib-rail">
      <div className="sg-lib-rail-head">Folders</div>
      <button className={`sg-lib-node ${activeLib===null?'on':''}`} onClick={()=>setActiveLib(null)}>
        <span className="sg-lib-node-name">All</span>
        <span className="sg-lib-node-meta">{all} frames · {libraries.length} libs</span>
      </button>
      {libraries.map(l=>(
        <button key={l.id} className={`sg-lib-node ${activeLib===l.id?'on':''}`} onClick={()=>setActiveLib(l.id)}>
          <span className="sg-lib-node-name">{l.display_name||l.root_path.split('/').pop()}</span>
          <span className="sg-lib-node-meta">{l.image_count} · {l.by_verdict?.keeper||0}K · {l.by_verdict?.reject||0}R</span>
        </button>
      ))}
    </div>
  );
}

// ── Grid layout ───────────────────────────────────────────────────────────────
function GridLayout({ items, selectedId, onSelect, onDoubleClick }) {
  return (
    <div className="sg-grid sg-scroll">
      {items.map((item,i)=>(
        <ThumbCard key={item.id} item={item} idx={i} selected={selectedId===item.id}
          onClick={()=>onSelect(item.id)} onDoubleClick={()=>onDoubleClick(item.id)} />
      ))}
      {!items.length&&(
        <div style={{gridColumn:'1/-1',textAlign:'center',padding:'80px 20px',color:'var(--c-mute)'}}>
          <div style={{fontFamily:'var(--font-display)',fontStyle:'italic',fontSize:32,color:'var(--c-text2)'}}>The sheet is blank.</div>
          <div style={{fontSize:9,letterSpacing:'0.22em',textTransform:'uppercase',marginTop:10,color:'var(--c-mute)'}}>No frames match these filters</div>
        </div>
      )}
    </div>
  );
}

// ── Filmstrip layout ──────────────────────────────────────────────────────────
function FilmstripLayout({ items, selectedId, onSelect, onPrev, onNext, onDoubleClick }) {
  const selected = items.find(i=>i.id===selectedId)||items[0];
  const stripRef = useRef(null);
  useEffect(()=>{
    if(!stripRef.current||!selectedId) return;
    const strip=stripRef.current;
    const btn=strip.querySelector(`[data-id="${selectedId}"]`);
    if(btn) strip.scrollLeft=btn.offsetLeft-strip.offsetWidth/2+btn.offsetWidth/2;
  },[selectedId]);
  return (
    <div style={{flex:1,display:'flex',flexDirection:'column',minHeight:0}}>
      <div style={{flex:1,background:'#000',display:'flex',alignItems:'center',justifyContent:'center',position:'relative',overflow:'hidden',cursor:'zoom-in',minHeight:0}}
        onDoubleClick={()=>selected&&onDoubleClick(selected.id)}>
        {selected?<img key={selected.id} src={selected.preview} alt="" style={{maxWidth:'100%',maxHeight:'100%',objectFit:'contain',transition:'opacity .18s'}}/>
          :<div style={{color:'var(--c-mute)',fontFamily:'var(--font-display)',fontStyle:'italic',fontSize:24}}>No frame</div>}
        <button onClick={onPrev} style={{position:'absolute',left:0,top:0,bottom:0,width:64,background:'linear-gradient(to right,rgba(0,0,0,.4),transparent)',border:'none',cursor:'pointer',color:'rgba(255,255,255,0.5)',fontSize:36,display:'flex',alignItems:'center',justifyContent:'center'}}
          onMouseOver={e=>e.currentTarget.style.color='rgba(255,255,255,0.9)'} onMouseOut={e=>e.currentTarget.style.color='rgba(255,255,255,0.5)'}>‹</button>
        <button onClick={onNext} style={{position:'absolute',right:0,top:0,bottom:0,width:64,background:'linear-gradient(to left,rgba(0,0,0,.4),transparent)',border:'none',cursor:'pointer',color:'rgba(255,255,255,0.5)',fontSize:36,display:'flex',alignItems:'center',justifyContent:'center'}}
          onMouseOver={e=>e.currentTarget.style.color='rgba(255,255,255,0.9)'} onMouseOut={e=>e.currentTarget.style.color='rgba(255,255,255,0.5)'}>›</button>
        {selected&&<div style={{position:'absolute',top:12,left:16,background:'rgba(0,0,0,.6)',padding:'3px 10px',fontSize:10,letterSpacing:'0.2em',textTransform:'uppercase',color:'rgba(255,255,255,0.7)',fontFamily:'var(--font-ui)'}}>
          {items.findIndex(i=>i.id===selected.id)+1} / {items.length}</div>}
        {selected&&<div style={{position:'absolute',top:12,right:80,padding:'3px 10px',fontSize:9,letterSpacing:'0.22em',textTransform:'uppercase',fontFamily:'var(--font-ui)',background:'rgba(0,0,0,0.6)',color:verdictColor(selected.verdict)}}>{selected.verdict||'—'}</div>}
      </div>
      <div ref={stripRef} className="sg-no-scrollbar" style={{display:'flex',gap:3,overflowX:'auto',padding:'6px 8px',background:'var(--c-panel2)',borderTop:'1px solid var(--c-border)',scrollBehavior:'smooth',flexShrink:0}}>
        {items.map(item=>{
          const isSel=item.id===selectedId;
          return(
            <button key={item.id} data-id={item.id} onClick={()=>onSelect(item.id)}
              style={{flexShrink:0,position:'relative',padding:0,border:`2px solid ${isSel?'var(--c-accent)':'transparent'}`,cursor:'pointer',background:'none',borderRadius:'calc(var(--radius)+1px)',overflow:'hidden',transition:'border-color .12s',width:96,height:68}}>
              <img src={item.thumb} alt="" style={{width:'100%',height:'100%',objectFit:'cover',display:'block',filter:isSel?'none':'brightness(0.65) saturate(0.8)'}}/>
              <div style={{position:'absolute',bottom:0,left:0,right:0,height:3,background:item.verdict==='keeper'?'var(--c-keeper)':item.verdict==='review'?'var(--c-amber)':item.verdict==='reject'?'var(--c-danger)':'transparent'}}/>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Main Triage Screen ────────────────────────────────────────────────────────
function TriageScreen({ layout, setLayout }) {
  const { MOCK_IMAGES, MOCK_LIBRARIES } = window.SG_DATA;

  const [filters, setFilters]     = useState(DEFAULT_FILTERS);
  const [activeLib, setActiveLib] = useState(null);
  const [selectedId, setSelectedId] = useState(MOCK_IMAGES[0]?.id ?? null);
  const [images, setImages]       = useState(MOCK_IMAGES);
  const [lightbox, setLightbox]   = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);

  const upd = useCallback((k, v) => setFilters(prev => ({...prev, [k]: v})), []);

  // Active count (excluding verdict which is in filterbar)
  const activeCount = useMemo(() => {
    const d = DEFAULT_FILTERS;
    return Object.keys(d).filter(k => k !== 'verdict' && filters[k] !== d[k]).length;
  }, [filters]);

  // Library-scoped image set — used by histograms in the filter panel and by
  // the timeline scrubber. Both should reflect the underlying distribution
  // without other filters applied, so the cutoffs stay meaningful as the user
  // explores.
  const libScoped = useMemo(() => activeLib !== null
    ? images.filter(i => i.library_id === activeLib) : images,
    [images, activeLib]);

  // Apply all filters + library scope
  const filtered = useMemo(() => applyFilters(libScoped, filters), [libScoped, filters]);

  const selectedImage = images.find(i => i.id === selectedId) || null;
  const filteredIdx   = filtered.findIndex(i => i.id === selectedId);

  const goPrev = useCallback(() => { if (filteredIdx > 0) setSelectedId(filtered[filteredIdx-1].id); }, [filtered, filteredIdx]);
  const goNext = useCallback(() => { if (filteredIdx < filtered.length-1) setSelectedId(filtered[filteredIdx+1].id); }, [filtered, filteredIdx]);

  const updateVerdict = useCallback((verdict, stars) => {
    if (!selectedId) return;
    setImages(imgs => imgs.map(img => img.id !== selectedId ? img : {
      ...img, ...(verdict?{verdict}:{}), ...(stars!=null?{stars}:{}),
    }));
    window.SG_API.verdict(selectedId, {
      ...(verdict ? { verdict } : {}),
      ...(stars != null ? { stars } : {}),
    }).catch(err => console.error('verdict update failed:', err));
  }, [selectedId]);

  useEffect(()=>{
    const h=e=>{
      if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT'||e.target.tagName==='TEXTAREA') return;
      if(lightbox) return;
      if(e.key==='j'||e.key==='ArrowRight') goNext();
      if(e.key==='k'||e.key==='ArrowLeft')  goPrev();
      if(e.key==='z') updateVerdict('keeper',null);
      if(e.key==='c') updateVerdict('review',null);
      if(e.key==='x') updateVerdict('reject',null);
      if('12345'.includes(e.key)) updateVerdict(null,parseInt(e.key));
    };
    window.addEventListener('keydown',h);
    return ()=>window.removeEventListener('keydown',h);
  },[goNext,goPrev,updateVerdict,lightbox]);

  const stripStats = useMemo(()=>{
    const lib = activeLib!==null?MOCK_LIBRARIES.find(l=>l.id===activeLib):null;
    if(lib){const v=lib.by_verdict||{};return{total:lib.image_count,keep:v.keeper||0,review:v.review||0,reject:v.reject||0,name:lib.display_name};}
    return{total:images.length,keep:images.filter(i=>i.verdict==='keeper').length,review:images.filter(i=>i.verdict==='review').length,reject:images.filter(i=>i.verdict==='reject').length,name:'All folders'};
  },[images,activeLib,MOCK_LIBRARIES]);

  const activeChips = useMemo(() => buildActiveChips(filters, upd), [filters, upd]);

  return (
    <div style={{display:'flex',flex:1,minHeight:0,overflow:'hidden'}}>
      <LibRail libraries={MOCK_LIBRARIES} activeLib={activeLib} setActiveLib={id=>{setActiveLib(id);}} />

      {/* Filter panel */}
      {panelOpen && (
        <FilterPanel filters={filters} setFilters={setFilters} images={libScoped} onClose={()=>setPanelOpen(false)} />
      )}

      {/* Main content */}
      <div style={{flex:1,display:'flex',flexDirection:'column',minWidth:0,minHeight:0}}>
        {/* Stat strip */}
        <div className="sg-stat-strip">
          <span style={{fontFamily:'var(--font-display)',fontStyle:'italic',fontSize:15,color:'var(--c-text)'}}>{stripStats.name}</span>
          <span>{filtered.length}<em style={{fontSize:9,letterSpacing:'0.18em',textTransform:'uppercase',color:'var(--c-mute)',fontStyle:'normal',marginLeft:4}}>shown</em></span>
          <span style={{color:'var(--c-keeper)'}}>{stripStats.keep}<em style={{fontSize:9,letterSpacing:'0.18em',textTransform:'uppercase',fontStyle:'normal',color:'var(--c-mute)',marginLeft:4}}>keep</em></span>
          <span style={{color:'var(--c-amber)'}}>{stripStats.review}<em style={{fontSize:9,letterSpacing:'0.18em',textTransform:'uppercase',fontStyle:'normal',color:'var(--c-mute)',marginLeft:4}}>review</em></span>
          <span style={{color:'var(--c-danger)'}}>{stripStats.reject}<em style={{fontSize:9,letterSpacing:'0.18em',textTransform:'uppercase',fontStyle:'normal',color:'var(--c-mute)',marginLeft:4}}>reject</em></span>
        </div>

        {/* Filter bar */}
        <div className="sg-filterbar" style={{gap:6}}>
          {/* Verdict quick chips */}
          {['all','keeper','review','reject'].map(v=>(
            <Chip key={v} on={filters.verdict===v} onClick={()=>upd('verdict',v)}>{v}</Chip>
          ))}

          <div style={{width:1,background:'var(--c-border)',height:18,margin:'0 2px',flexShrink:0}}/>

          {/* Filter panel toggle */}
          <button onClick={()=>setPanelOpen(o=>!o)} style={{
            display:'inline-flex', alignItems:'center', gap:6, padding:'5px 13px',
            fontSize:9, letterSpacing:'0.22em', textTransform:'uppercase',
            border:`1px solid ${panelOpen||activeCount>0?'var(--c-accent)':'var(--c-border2)'}`,
            color: panelOpen||activeCount>0?'var(--c-accent)':'var(--c-text2)',
            background: panelOpen?'rgba(193,68,14,0.1)':'transparent',
            borderRadius:'var(--radius)', cursor:'pointer', fontFamily:'var(--font-ui)',
            transition:'all .12s',
          }}>
            ⊟ Filters
            {activeCount>0&&(
              <span style={{
                background:'var(--c-accent)', color:'var(--c-bg)',
                fontSize:8, padding:'1px 5px', borderRadius:999,
                fontFamily:'var(--font-ui)', fontWeight:700, lineHeight:'1.4',
              }}>{activeCount}</span>
            )}
          </button>

          {/* Active filter dismissibles */}
          {activeChips.length > 0 && (
            <div style={{display:'flex',flexWrap:'wrap',gap:4,alignItems:'center'}}>
              {activeChips.map(chip=>(
                <button key={chip.id} onClick={chip.clear} style={{
                  display:'inline-flex', alignItems:'center', gap:4,
                  padding:'3px 8px', fontSize:9, letterSpacing:'0.14em',
                  border:'1px solid var(--c-accent)', color:'var(--c-accent)',
                  background:'rgba(193,68,14,0.08)', borderRadius:'var(--radius)',
                  cursor:'pointer', fontFamily:'var(--font-ui)', transition:'all .1s',
                }}>
                  {chip.label}
                  <span style={{opacity:0.7,fontSize:10}}>×</span>
                </button>
              ))}
              {activeChips.length>1&&(
                <button onClick={()=>setFilters(prev=>({...DEFAULT_FILTERS,verdict:prev.verdict}))} style={{
                  fontSize:9, letterSpacing:'0.14em', textTransform:'uppercase',
                  color:'var(--c-danger)', background:'none', border:'none',
                  cursor:'pointer', fontFamily:'var(--font-ui)',
                }}>clear all ×</button>
              )}
            </div>
          )}

          <div style={{flex:1}}/>
          <div style={{fontSize:9,letterSpacing:'0.16em',textTransform:'uppercase',color:'var(--c-mute)',display:'flex',gap:6,alignItems:'center',flexShrink:0}}>
            <kbd className="sg-kbd">J</kbd><kbd className="sg-kbd">K</kbd> nav ·
            <kbd className="sg-kbd">Z</kbd><kbd className="sg-kbd">C</kbd><kbd className="sg-kbd">X</kbd> verdict
          </div>
        </div>

        {/* Timeline scrubber */}
        <TimelineScrubber
          images={libScoped}
          dateFrom={filters.date_from}
          dateTo={filters.date_to}
          onChange={changes => {
            setFilters(prev => ({
              ...prev,
              ...('from' in changes ? { date_from: changes.from } : {}),
              ...('to'   in changes ? { date_to:   changes.to   } : {}),
            }));
          }}
        />

        {/* Grid / filmstrip */}
        <div style={{flex:1,display:'flex',minHeight:0}}>
          {layout==='grid'?(
            <GridLayout items={filtered} selectedId={selectedId} onSelect={setSelectedId}
              onDoubleClick={id=>{setSelectedId(id);setLightbox(true);}}/>
          ):(
            <FilmstripLayout items={filtered} selectedId={selectedId} onSelect={setSelectedId}
              onPrev={goPrev} onNext={goNext} onDoubleClick={id=>{setSelectedId(id);setLightbox(true);}}/>
          )}
          <DetailPanel image={selectedImage} onVerdict={updateVerdict}
            onOpenLightbox={()=>setLightbox(true)} compact={layout==='filmstrip'}/>
        </div>
      </div>

      {lightbox&&(
        <Lightbox image={selectedImage} items={filtered} onClose={()=>setLightbox(false)}
          onVerdict={updateVerdict} onPrev={goPrev} onNext={goNext}/>
      )}
    </div>
  );
}

Object.assign(window, { TriageScreen });
