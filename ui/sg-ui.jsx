// SnapGrade — Shared UI components
// Exports: TABS, TAB_TITLES, pad, verdictColor,
//          Sidebar, TopBar, DetailPanel, Lightbox,
//          Chip, Btn, MetricTags

const { useState, useEffect, useCallback, useRef } = React;

const TABS = [
  ["library",  "Library",      "I"],
  ["triage",   "Triage",       "II"],
  ["bursts",   "Bursts",       "III"],
  ["faces",    "Face Clusters","IV"],
  ["xmp",      "XMP Export",  "V"],
  ["organize", "Organize",    "VI"],
  ["settings", "Settings",    "VII"],
];

const TAB_TITLES = {
  library:  ["The", "Library"],
  triage:   ["The", "Contact Sheet"],
  bursts:   ["Burst", "Comparison"],
  faces:    ["Face", "Clusters"],
  xmp:      ["Batch", "XMP Export"],
  organize: ["The", "Hierarchy"],
  settings: ["The", "Darkroom"],
};

function pad(n, w = 3) { return String(n ?? 0).padStart(w, "0"); }

function EmptyState({ children, padding = '60px 20px' }) {
  return (
    <div style={{ textAlign:'center', padding, color:'var(--c-mute)', fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:22 }}>
      {children}
    </div>
  );
}

function verdictColor(v) {
  if (v === 'keeper') return 'var(--c-keeper)';
  if (v === 'review') return 'var(--c-amber)';
  if (v === 'reject') return 'var(--c-danger)';
  return 'var(--c-mute)';
}

function Chip({ on, onClick, children, style = {} }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '5px 13px',
        fontSize: 9, letterSpacing: '0.22em', textTransform: 'uppercase',
        border: `1px solid ${on ? 'var(--c-accent)' : 'var(--c-border2)'}`,
        color: on ? 'var(--c-accent)' : 'var(--c-text2)',
        background: 'transparent',
        borderRadius: 'var(--radius)',
        cursor: 'pointer', transition: 'all .12s', fontFamily: 'var(--font-ui)',
        ...style,
      }}
    >{children}</button>
  );
}

function Btn({ variant = 'ghost', onClick, disabled, children, style = {} }) {
  const variants = {
    ghost:   { border: '1px solid var(--c-border2)', color: 'var(--c-text2)' },
    primary: { border: '1px solid var(--c-accent)',  color: 'var(--c-accent)' },
    danger:  { border: '1px solid var(--c-danger)',  color: 'var(--c-danger)' },
    solid:   { border: '1px solid var(--c-accent)',  color: 'var(--c-bg)',  background: 'var(--c-accent)' },
  };
  const s = variants[variant] || variants.ghost;
  return (
    <button onClick={onClick} disabled={disabled} style={{
      padding: '9px 20px',
      fontSize: 9, letterSpacing: '0.26em', textTransform: 'uppercase',
      background: 'transparent', cursor: disabled ? 'not-allowed' : 'pointer',
      borderRadius: 'var(--radius)', transition: 'all .15s', opacity: disabled ? 0.4 : 1,
      fontFamily: 'var(--font-ui)',
      ...s, ...style,
    }}>{children}</button>
  );
}

// ── MetricTags ────────────────────────────────────────────────────────────────
// Surfaces OCR text, content-type classification, scene, animals and the
// colour palette extracted by color.py — mirrors the real app.js MetricTags.
function MetricTags({ image }) {
  const [ocrOpen, setOcrOpen] = useState(false);
  if (!image) return null;

  const { content_type, scene, ocr = [], animals = [], color, reasons = [], metrics } = image;

  // Content-type badge — only show when non-photo (or if screenshot/document)
  const CT_BADGE = {
    screenshot: { bg: 'var(--c-amber)',  label: 'screenshot', icon: '🖥' },
    document:   { bg: 'var(--c-accent)', label: 'document',   icon: '📄' },
  };
  const ctInfo = CT_BADGE[content_type];
  const ctConf = metrics?.content_type?.conf;
  const sceneConf = typeof metrics?.scene === 'object' ? metrics.scene.conf : null;

  // YOLO object detections — distinct classes, most-confident first.
  const objClasses = [];
  for (const d of (metrics?.objects?.detections || [])) {
    if (!objClasses.includes(d.class)) objClasses.push(d.class);
  }

  const hasAnything = ctInfo || scene || ocr.length > 0 || animals.length > 0 || color?.dominant?.length || objClasses.length > 0;
  if (!hasAnything) return null;

  const tagStyle = {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: '3px 9px', fontSize: 9, letterSpacing: '0.18em',
    textTransform: 'uppercase', borderRadius: 'var(--radius)',
    fontFamily: 'var(--font-ui)',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 10,
                  borderTop: '1px dashed var(--c-border2)' }}>

      {/* ── Tags row ── */}
      {(ctInfo || scene || animals.length > 0 || objClasses.length > 0) && (
        <div>
          <div className="sg-detail-label">Tags</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {ctInfo && (
              <span style={{ ...tagStyle, background: ctInfo.bg,
                             color: 'var(--c-bg)', fontWeight: 600 }}>
                {ctInfo.icon} {ctInfo.label}
                {ctConf != null && <span style={{ marginLeft: 4, opacity: 0.7 }}>{Math.round(ctConf * 100)}%</span>}
              </span>
            )}
            {scene && (
              <span style={{ ...tagStyle,
                             border: '1px solid var(--c-border2)', color: 'var(--c-text2)' }}>
                ⛰ {scene}
                {sceneConf != null && <span style={{ marginLeft: 4, opacity: 0.6, fontSize: 8 }}>{Math.round(sceneConf * 100)}%</span>}
              </span>
            )}
            {objClasses.slice(0, 8).map(c => (
              <span key={c} style={{ ...tagStyle,
                                     border: '1px solid var(--c-border2)', color: 'var(--c-text2)' }}>
                {c}
              </span>
            ))}
            {animals.map((a, i) => (
              <span key={`an${i}`} style={{ ...tagStyle,
                                     border: '1px solid var(--c-border2)', color: 'var(--c-text2)' }}>
                🐾 {a.species}
                <span style={{ fontSize: 8, opacity: 0.6 }}> {Math.round(a.confidence * 100)}%</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── OCR regions ── */}
      {ocr.length > 0 && (
        <div>
          <button
            onClick={() => setOcrOpen(o => !o)}
            style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none',
                     border: 'none', cursor: 'pointer', padding: 0, width: '100%',
                     justifyContent: 'space-between' }}
          >
            <div className="sg-detail-label" style={{ marginBottom: 0 }}>
              OCR · {ocr.length} region{ocr.length !== 1 ? 's' : ''}
            </div>
            <span style={{ fontSize: 10, color: 'var(--c-accent)', fontFamily: 'var(--font-ui)',
                           letterSpacing: '0.1em' }}>
              {ocrOpen ? '▲' : '▼'}
            </span>
          </button>
          {ocrOpen && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {ocr.map((r, i) => (
                <div key={i} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                  padding: '5px 8px', background: 'var(--c-bg)',
                  borderLeft: '2px solid var(--c-border2)',
                }}>
                  <span style={{ fontSize: 11, color: 'var(--c-text)', fontFamily: 'var(--font-ui)',
                                 letterSpacing: '0.01em', wordBreak: 'break-all' }}>
                    {r.text}
                  </span>
                  <span style={{ fontSize: 8, color: 'var(--c-mute)', letterSpacing: '0.14em',
                                 flexShrink: 0, marginLeft: 8 }}>
                    {Math.round(r.confidence * 100)}%
                  </span>
                </div>
              ))}
            </div>
          )}
          {/* Show collapsed preview */}
          {!ocrOpen && (
            <div style={{ marginTop: 5, fontSize: 10, color: 'var(--c-text2)', lineHeight: 1.5,
                          fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap' }}>
              {ocr.map(r => r.text).join(' · ')}
            </div>
          )}
        </div>
      )}

      {/* ── Colour palette ── */}
      {color?.dominant?.length > 0 && (
        <div>
          <div className="sg-detail-label">
            Palette · {color.temperature} · {color.saturation}
            {color.cast_hue && (
              <span style={{ color: 'var(--c-amber)', marginLeft: 8 }}>
                {color.cast_hue} cast
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
            {color.dominant.map(([r, g, b], i) => (
              <div
                key={i}
                title={`rgb(${r},${g},${b})`}
                style={{
                  width: 32, height: 32,
                  background: `rgb(${r},${g},${b})`,
                  borderRadius: 'var(--radius)',
                  border: '1px solid rgba(0,0,0,0.25)',
                  flexShrink: 0,
                  transition: 'transform .12s',
                  cursor: 'default',
                }}
                onMouseOver={e => e.currentTarget.style.transform = 'scale(1.15)'}
                onMouseOut={e => e.currentTarget.style.transform = 'scale(1)'}
              />
            ))}
            {color.cast_hue && color.cast_strength > 0.2 && (
              <div style={{
                marginLeft: 6, padding: '2px 8px',
                fontSize: 8, letterSpacing: '0.2em', textTransform: 'uppercase',
                border: '1px solid var(--c-amber)', color: 'var(--c-amber)',
                borderRadius: 'var(--radius)', fontFamily: 'var(--font-ui)',
              }}>
                cast {Math.round(color.cast_strength * 100)}%
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function Sidebar({ tab, setTab, stats, collapsed, onToggle, libraries = [], activeLib, setActiveLib }) {
  // The Triage library picker (formerly the standalone LibRail) folds into the
  // nav here: when on Triage and expanded, the libraries appear as indented
  // nav rows that drive `activeLib`, reclaiming a whole vertical strip.
  const libsAll = libraries.reduce((a, l) => a + (l.image_count || 0), 0);
  return (
    <aside className="sg-sidebar" style={{ width: collapsed ? 56 : 220 }}>
      <button className="sg-collapse-btn" onClick={onToggle} title={collapsed ? 'Expand' : 'Collapse'}>
        {collapsed ? '›' : '‹'}
      </button>
      {!collapsed && (
        <>
          <div className="sg-brand">Snap<em>·</em>Grade</div>
          <div className="sg-brand-sub">A local culling apparatus</div>
        </>
      )}
      <nav className="sg-nav sg-scroll" style={{ overflowX: 'hidden' }}>
        {TABS.map(([k, label, n]) => (
          <React.Fragment key={k}>
            <button
              className={`sg-nav-btn ${tab === k ? 'on' : ''}`}
              onClick={() => setTab(k)}
              title={collapsed ? label : ''}
              style={{ justifyContent: collapsed ? 'center' : 'flex-start' }}
            >
              <span className="sg-nav-n">{n}.</span>
              {!collapsed && <span className="sg-nav-label">{label}</span>}
            </button>
            {/* Triage library group */}
            {k === 'triage' && tab === 'triage' && !collapsed && setActiveLib && (
              <div className="sg-nav-libs">
                <button className={`sg-nav-lib ${activeLib === null ? 'on' : ''}`}
                  onClick={() => setActiveLib(null)}>
                  <span>All folders</span><span className="sg-nav-lib-n">{libsAll}</span>
                </button>
                {libraries.map(l => (
                  <button key={l.id} className={`sg-nav-lib ${activeLib === l.id ? 'on' : ''}`}
                    onClick={() => setActiveLib(l.id)} title={l.display_name || l.root_path}>
                    <span>{l.display_name || l.root_path.split('/').pop()}</span>
                    <span className="sg-nav-lib-n">{l.image_count}</span>
                  </button>
                ))}
              </div>
            )}
          </React.Fragment>
        ))}
      </nav>
      {!collapsed && stats && (
        <div className="sg-sidebar-foot">
          <div className="sg-foot-row"><span>Libraries</span><span>{pad(stats.libraries ?? 0, 3)}</span></div>
          <div className="sg-foot-row"><span>Frames</span><span>{pad(stats.images, 5)}</span></div>
          <div className="sg-foot-row"><span>Bursts</span><span>{pad(stats.bursts, 4)}</span></div>
          {stats.ingest?.running && (() => {
            const done = stats.ingest.done || 0;
            const total = stats.ingest.total || 0;
            const pct = total > 0 ? Math.min(100, Math.round(100 * done / total)) : null;
            return (
              <div style={{ marginTop: 10 }}>
                <div className="sg-live"><span className="sg-live-dot" />Ingest running</div>
                <div className="sg-progress-track">
                  {pct == null
                    ? <div className="sg-progress-indeterminate" />
                    : <div className="sg-progress-fill" style={{ width: `${pct}%` }} />}
                </div>
                <div className="sg-progress-label">
                  <span>{done}{total ? ` / ${total}` : ''} frames</span>
                  <span>{pct != null ? `${pct}%` : '…'}</span>
                </div>
              </div>
            );
          })()}
          {stats.ingest?.error && (
            <div style={{ marginTop:8, fontSize:9, letterSpacing:'.16em', textTransform:'uppercase', color:'var(--c-danger)' }}>
              ingest error · {stats.ingest.error.slice(0, 80)}
            </div>
          )}
          {stats.faces?.running && (() => {
            const f = stats.faces;
            const done = f.done || 0;
            const total = f.total || 0;
            const pct = total > 0 ? Math.min(100, Math.round(100 * done / total)) : null;
            const stageLabel = f.stage === 'cluster' ? 'Clustering' : 'Detecting faces';
            return (
              <div style={{ marginTop: 12 }}>
                <div className="sg-live"><span className="sg-live-dot" />{stageLabel}</div>
                <div className="sg-progress-track">
                  {pct == null
                    ? <div className="sg-progress-indeterminate" />
                    : <div className="sg-progress-fill" style={{ width: `${pct}%` }} />}
                </div>
                <div className="sg-progress-label">
                  <span>{done}{total ? ` / ${total}` : ''} frames</span>
                  <span>{pct != null ? `${pct}%` : '…'}</span>
                </div>
              </div>
            );
          })()}
          {stats.faces?.error && (
            <div style={{ marginTop:8, fontSize:9, letterSpacing:'.16em', textTransform:'uppercase', color:'var(--c-danger)' }}>
              faces error · {stats.faces.error.slice(0, 80)}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

// ── Theme picker (lives in topbar) ────────────────────────────────────────────
// Labels set expectations about *what changes*: "Cinematic" carries the grain /
// vignette / sprocket / serif treatment; "Utility" drops them for a flat,
// neutral working surface. (Themes are functionally the same dark-film /
// dark-modern / light-pro tokens underneath.)
const THEMES = [
  { id: 'dark-film',   label: 'Cinematic',     swatch: ['#0a0907', '#c1440e', '#d4a017'] },
  { id: 'dark-modern', label: 'Modern',        swatch: ['#0f0f12', '#e05a35', '#42b878'] },
  { id: 'light-pro',   label: 'Utility (Light)', swatch: ['#f0ede8', '#c1440e', '#3d6e28'] },
];

function ThemePicker({ theme, onThemeChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const h = e => { if (!ref.current?.contains(e.target)) setOpen(false); };
    window.addEventListener('click', h);
    return () => window.removeEventListener('click', h);
  }, []);
  const active = THEMES.find(t => t.id === theme) || THEMES[0];
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button onClick={e => { e.stopPropagation(); setOpen(o => !o); }}
        title="Theme" style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px',
          border: `1px solid ${open ? 'var(--c-accent)' : 'var(--c-border2)'}`,
          background: open ? 'rgba(193,68,14,0.05)' : 'transparent',
          color: 'var(--c-text2)', cursor: 'pointer',
          borderRadius: 'var(--radius)', fontFamily: 'var(--font-ui)',
          fontSize: 9, letterSpacing: '0.22em', textTransform: 'uppercase',
          transition: 'all .12s',
        }}>
        <span style={{ display: 'inline-flex', gap: 2 }}>
          {active.swatch.map((c, i) => (
            <span key={i} style={{ width: 8, height: 12,
                                    background: c, borderRadius: 1,
                                    border: '1px solid rgba(0,0,0,0.2)' }} />
          ))}
        </span>
        <span>{active.label}</span>
        <span style={{ fontSize: 9, color: 'var(--c-mute)' }}>▾</span>
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', right: 0,
          minWidth: 180, zIndex: 100,
          background: 'var(--c-panel)', border: '1px solid var(--c-border2)',
          boxShadow: 'var(--shadow)', borderRadius: 'var(--radius)',
          padding: 4, fontFamily: 'var(--font-ui)',
        }}>
          {THEMES.map(t => (
            <button key={t.id} onClick={() => { onThemeChange(t.id); setOpen(false); }}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                width: '100%', padding: '8px 10px',
                background: theme === t.id ? 'rgba(193,68,14,0.08)' : 'transparent',
                border: 'none', cursor: 'pointer',
                color: theme === t.id ? 'var(--c-accent)' : 'var(--c-text)',
                borderRadius: 'calc(var(--radius) - 1px)',
                fontFamily: 'var(--font-ui)',
                textAlign: 'left', transition: 'background .1s',
              }}>
              <span style={{ display: 'inline-flex', gap: 2 }}>
                {t.swatch.map((c, i) => (
                  <span key={i} style={{ width: 10, height: 16, background: c,
                                          borderRadius: 1, border: '1px solid rgba(0,0,0,0.2)' }} />
                ))}
              </span>
              <span style={{ fontSize: 11 }}>{t.label}</span>
              {theme === t.id && <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--c-accent)' }}>✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── TopBar ────────────────────────────────────────────────────────────────────
function TopBar({ tab, layout, onLayoutToggle, theme, onThemeChange }) {
  const [pre, post] = TAB_TITLES[tab] || ['', tab];
  return (
    <div className="sg-topbar">
      <div>
        <div className="sg-crumbs">Roll · {tab.toUpperCase()} · {new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</div>
        <div className="sg-page-title">{pre} <em>{post}</em></div>
      </div>
      <div style={{ flex: 1 }} />
      {tab === 'triage' && onLayoutToggle && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginRight: 12 }}>
          <Chip on={layout === 'grid'}      onClick={() => onLayoutToggle('grid')}>⊞ Grid</Chip>
          <Chip on={layout === 'filmstrip'} onClick={() => onLayoutToggle('filmstrip')}>▬ Filmstrip</Chip>
        </div>
      )}
      {onThemeChange && <ThemePicker theme={theme} onThemeChange={onThemeChange} />}
    </div>
  );
}

// Bbox overlay shared by DetailPanel + Lightbox. Subjects coords are in the
// decoded image's pixel space; metrics.decoded_size = [w, h]. We map to % so it
// scales with whatever the <img> rendered at.
function bboxStyle(s, decoded) {
  if (!decoded || !s?.bbox) return { display: 'none' };
  const [dw, dh] = decoded;
  const [x, y, w, h] = s.bbox;
  return {
    position: 'absolute',
    left: `${100 * x / dw}%`, top: `${100 * y / dh}%`,
    width: `${100 * w / dw}%`, height: `${100 * h / dh}%`,
    border: `2px solid ${s.is_primary ? 'var(--c-accent)' : 'var(--c-text2)'}`,
    pointerEvents: 'none', boxSizing: 'border-box',
  };
}

// ImageWithOverlays — renders an <img> via objectFit:contain inside a wrapper,
// then positions an absolute overlay box that EXACTLY matches the rendered
// (letterboxed) image rect, so SubjectOverlay / OCR rects scale correctly.
// Without this, bbox percentages would be relative to the full wrapper, not
// the visible image, and the boxes would float into the black bars.
function ImageWithOverlays({ src, fallbackSrc, subjects, decoded, ocr, naturalSize, showBoxes = true, imgStyle = {} }) {
  const imgRef  = useRef(null);
  const wrapRef = useRef(null);
  const [box, setBox] = useState(null);

  const measure = useCallback(() => {
    const img  = imgRef.current;
    const wrap = wrapRef.current;
    if (!img || !wrap || !img.naturalWidth || !img.naturalHeight) return;
    const r = wrap.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const ar = img.naturalWidth / img.naturalHeight;
    let w, h;
    if (r.width / r.height > ar) { h = r.height; w = r.height * ar; }
    else                          { w = r.width;  h = r.width / ar;  }
    setBox({ left: (r.width - w) / 2, top: (r.height - h) / 2, width: w, height: h });
  }, []);

  useEffect(() => {
    measure();
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [measure, src]);

  // OCR bboxes are in original-image pixel coordinates; pass the photo's
  // intrinsic w/h via `naturalSize` so the % math is correct.
  const [W, H] = naturalSize || [0, 0];

  return (
    <div ref={wrapRef} style={{ position: 'relative', width: '100%', height: '100%' }}>
      <img ref={imgRef} src={src} alt="" onLoad={measure}
           onError={e => { if (fallbackSrc && e.currentTarget.src !== fallbackSrc) e.currentTarget.src = fallbackSrc; }}
           style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block', ...imgStyle }} />
      {showBoxes && box && (
        <div style={{ position: 'absolute', left: box.left, top: box.top,
                      width: box.width, height: box.height, pointerEvents: 'none' }}>
          {subjects?.length > 0 && <SubjectOverlay subjects={subjects} decoded={decoded} />}
          {ocr?.length > 0 && W > 0 && H > 0 && ocr.map((r, i) => {
            const [x0, y0, x1, y1] = r.bbox;
            return (
              <div key={`ocr${i}`} style={{
                position: 'absolute',
                left:   `${100 * x0 / W}%`, top:    `${100 * y0 / H}%`,
                width:  `${100 * (x1 - x0) / W}%`, height: `${100 * (y1 - y0) / H}%`,
                border: '1px solid rgba(212,160,23,0.65)', boxSizing: 'border-box',
              }} />
            );
          })}
        </div>
      )}
    </div>
  );
}

function SubjectOverlay({ subjects, decoded }) {
  if (!subjects?.length || !decoded) return null;
  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
      {subjects.map((s, i) => (
        <div key={i} style={bboxStyle(s, decoded)}>
          <span style={{
            position: 'absolute', top: -16, left: 0,
            fontSize: 8, letterSpacing: '0.18em', textTransform: 'uppercase',
            padding: '1px 5px', fontFamily: 'var(--font-ui)',
            background: s.is_primary ? 'var(--c-accent)' : 'var(--c-text2)',
            color: 'var(--c-bg)',
          }}>
            {s.is_primary ? 'subj' : (s.kind || 'obj')}
            {s.confidence != null && <span style={{ marginLeft: 4, opacity: 0.8 }}>{Math.round(s.confidence * 100)}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── DetailPanel ───────────────────────────────────────────────────────────────
function DetailPanel({ image, onVerdict, onOpenLightbox, compact }) {
  const [xmpMsg, setXmpMsg] = useState('');
  const [showBoxes, setShowBoxes] = useState(true);

  if (!image) return (
    <aside className="sg-detail" style={{ width: compact ? 280 : 380 }}>
      <div className="sg-detail-empty">
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontStyle: 'italic',
                      color: 'var(--c-text2)', marginBottom: 8 }}>No frame selected.</div>
        <div style={{ fontSize: 9, letterSpacing: '0.22em', textTransform: 'uppercase',
                      color: 'var(--c-mute)' }}>Pick from the sheet</div>
      </div>
    </aside>
  );

  const m = image;
  const vColors = { keeper: 'var(--c-keeper)', review: 'var(--c-amber)', reject: 'var(--c-danger)' };

  return (
    <aside className="sg-detail" style={{ width: compact ? 280 : 380 }}>
      {/* Preview */}
      {!compact && (
        <div className="sg-detail-preview" onClick={onOpenLightbox}
             style={{ cursor: 'zoom-in', position: 'relative' }}>
          <img src={m.thumb} alt="" style={{ width: '100%', display: 'block', position: 'relative', zIndex: 1 }}
               onError={e => { if (e.currentTarget.src !== m.preview) e.currentTarget.src = m.preview; }} />
          {showBoxes && <SubjectOverlay subjects={m.metrics?.subjects} decoded={m.metrics?.decoded_size} />}
          <div className="sg-corners" />
          <div className="sg-corners-br" />
          {/* Content-type badge on preview */}
          {m.content_type !== 'photo' && (
            <div style={{
              position: 'absolute', bottom: 8, left: 10,
              background: m.content_type === 'screenshot' ? 'var(--c-amber)' : 'var(--c-accent)',
              color: 'var(--c-bg)',
              fontSize: 8, letterSpacing: '0.2em', textTransform: 'uppercase',
              padding: '3px 8px', fontFamily: 'var(--font-ui)',
            }}>
              {m.content_type === 'screenshot' ? '🖥' : '📄'} {m.content_type}
            </div>
          )}
          <div style={{ position: 'absolute', bottom: 8, right: 10, fontSize: 10, opacity: 0.6,
                        letterSpacing: '0.1em', color: 'var(--c-text)', fontFamily: 'var(--font-ui)' }}>⤢ full</div>
        </div>
      )}

      <div className="sg-detail-body">
        <div className="sg-detail-path">{m.path.split('/').pop()}</div>

        {!compact && m.metrics?.subjects?.length > 0 && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 9,
                          letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--c-text2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={showBoxes} onChange={e => setShowBoxes(e.target.checked)}
                   style={{ accentColor: 'var(--c-accent)' }} />
            Subject bboxes · {m.metrics.subjects.length}
          </label>
        )}

        {/* Verdict */}
        <div>
          <div className="sg-detail-label">Verdict</div>
          <div style={{ display: 'flex', gap: 6 }}>
            {['keeper', 'review', 'reject'].map(v => (
              <button key={v} onClick={() => onVerdict(v, null)} style={{
                flex: 1, padding: '9px 0', fontSize: 9, letterSpacing: '0.22em',
                textTransform: 'uppercase',
                border: `1px solid ${m.verdict === v ? vColors[v] : 'var(--c-border2)'}`,
                color: m.verdict === v ? vColors[v] : 'var(--c-mute)',
                background: 'transparent', cursor: 'pointer', borderRadius: 'var(--radius)',
                fontFamily: 'var(--font-ui)',
              }}>{v}</button>
            ))}
          </div>
        </div>

        {/* Stars */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="sg-detail-label" style={{ marginBottom: 0, marginRight: 8 }}>Stars</span>
          {[1,2,3,4,5].map(s => (
            <button key={s} onClick={() => onVerdict(null, s)} style={{
              fontSize: 18, color: s <= (m.stars || 0) ? 'var(--c-amber)' : 'var(--c-border2)',
              background: 'none', border: 'none', cursor: 'pointer', padding: '0 1px',
              transition: 'color .12s',
            }}>{s <= (m.stars || 0) ? '★' : '☆'}</button>
          ))}
        </div>

        {/* Key metrics */}
        <div className="sg-metrics-grid">
          <div className="sg-metric">
            <div className="sg-metric-label">Sharpness</div>
            <div className="sg-metric-val" style={{ color: m.sharpness > 0.55 ? 'var(--c-keeper)' : m.sharpness > 0.32 ? 'var(--c-amber)' : 'var(--c-danger)' }}>
              {Math.round(m.sharpness * 100)}<span style={{ fontSize: 10 }}>%</span>
            </div>
          </div>
          <div className="sg-metric">
            <div className="sg-metric-label">Aesthetic</div>
            <div className="sg-metric-val" style={{ color: (m.aesthetic_score || 0) > 0.65 ? 'var(--c-keeper)' : 'var(--c-text)' }}>
              {m.aesthetic_score != null ? Math.round(m.aesthetic_score * 100) : '—'}<span style={{ fontSize: 10 }}>{m.aesthetic_score != null ? '%' : ''}</span>
            </div>
          </div>
          <div className="sg-metric">
            <div className="sg-metric-label">ISO</div>
            <div className="sg-metric-val">{m.iso}</div>
          </div>
          <div className="sg-metric">
            <div className="sg-metric-label">f/</div>
            <div className="sg-metric-val">{m.f_number}</div>
          </div>
          <div className="sg-metric">
            <div className="sg-metric-label">Speed</div>
            <div className="sg-metric-val" style={{ fontSize: 16 }}>{m.exposure_time}</div>
          </div>
          <div className="sg-metric">
            <div className="sg-metric-label">Scene</div>
            <div style={{ fontSize: 10, color: 'var(--c-text2)', marginTop: 4,
                          fontFamily: 'var(--font-ui)', letterSpacing: '0.12em',
                          textTransform: 'uppercase' }}>{m.scene || '—'}</div>
          </div>
        </div>

        {/* Reasons */}
        {m.reasons && m.reasons.length > 0 && (
          <div className="sg-reasons">
            {m.reasons.map((r, i) => {
              const isClosedEyes = /eyes[_ ]?closed|closed[_ ]?eyes/i.test(r);
              return (
                <React.Fragment key={i}>
                  {i > 0 && <span style={{ opacity:0.5 }}> · </span>}
                  <span style={isClosedEyes ? { borderBottom:'1px dotted var(--c-amber)' } : null}>{r}</span>
                  {isClosedEyes && (
                    <span
                      title="Eyes-closed detection uses landmark geometry only — hair, sunglasses, or other occlusion can cause false positives. Override the verdict if the eyes look open."
                      style={{ marginLeft:4, padding:'1px 6px', borderRadius:'999px', border:'1px solid var(--c-amber)', color:'var(--c-amber)', fontSize:9, fontFamily:'var(--font-ui)', fontStyle:'normal', letterSpacing:'.1em', cursor:'help', verticalAlign:'1px' }}
                    >?</span>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        )}

        {/* MetricTags — OCR, content type, colour, animals */}
        <MetricTags image={m} />

        {/* EXIF */}
        <div style={{ fontSize: 10, color: 'var(--c-mute)', lineHeight: 1.7 }}>
          <div>{m.camera_model}</div>
          <div>{m.lens}</div>
          <div>{m.capture_time?.slice(0, 10)}</div>
        </div>

        {compact && (
          <Btn variant="ghost" onClick={onOpenLightbox} style={{ width: '100%', marginTop: 4 }}>Full view ⤢</Btn>
        )}

        {xmpMsg && <div style={{ fontSize: 10, color: 'var(--c-amber)', marginTop: 6 }}>→ {xmpMsg}</div>}
      </div>
    </aside>
  );
}

// ── Lightbox ──────────────────────────────────────────────────────────────────
function lbZoomBtn(active) {
  return {
    padding: '5px 11px', fontSize: 9, letterSpacing: '0.18em', textTransform: 'uppercase',
    fontFamily: 'var(--font-ui)', borderRadius: 'var(--radius)',
    background: 'rgba(10,9,7,0.7)', cursor: 'pointer',
    border: `1px solid ${active ? 'var(--c-accent)' : 'var(--c-border2)'}`,
    color: active ? 'var(--c-accent)' : 'var(--c-text)',
  };
}

function Lightbox({ image, items, onClose, onVerdict, onPrev, onNext }) {
  const [showBoxes, setShowBoxes] = useState(true);
  // Zoom/pan for pixel-level sharpness review (the single biggest functional
  // gap before). The whole image+overlay wrapper is transformed uniformly, so
  // subject/OCR boxes stay registered at any zoom.
  const [scale, setScale]   = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragRef = useRef(null);

  // Reset when the frame changes.
  useEffect(() => { setScale(1); setOffset({ x: 0, y: 0 }); }, [image && image.id]);

  // Approximate the natural-pixel ("1:1") scale from the fit-rendered size.
  const oneToOne = useCallback(() => {
    const W = image?.width || 6016, H = image?.height || 4016;
    const vw = window.innerWidth * 0.86, vh = window.innerHeight * 0.78;
    const ar = W / H;
    const renderedW = (vw / vh > ar) ? vh * ar : vw;
    return Math.max(1, Math.min(8, W / renderedW));
  }, [image]);

  const reset = useCallback(() => { setScale(1); setOffset({ x: 0, y: 0 }); }, []);
  const toggleZoom = useCallback(() => {
    setScale(s => (s > 1 ? 1 : oneToOne()));
    setOffset({ x: 0, y: 0 });
  }, [oneToOne]);

  useEffect(() => {
    const handler = e => {
      if (e.key === 'Escape')                      onClose();
      if (e.key === 'ArrowLeft'  || e.key === 'k') onPrev();
      if (e.key === 'ArrowRight' || e.key === 'j') onNext();
      if (e.key === 'z') onVerdict('keeper', null);
      if (e.key === 'c') onVerdict('review', null);
      if (e.key === 'x') onVerdict('reject', null);
      if (e.key === '0' || e.key === 'f') reset();
      if (e.key === '1') toggleZoom();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose, onPrev, onNext, onVerdict, reset, toggleZoom]);

  function onWheel(e) {
    e.preventDefault();
    setScale(s => Math.max(1, Math.min(8, s * (e.deltaY < 0 ? 1.15 : 1 / 1.15))));
  }
  function onMouseDown(e) {
    if (scale <= 1) return;
    e.preventDefault();
    dragRef.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
  }
  function onMouseMove(e) {
    if (!dragRef.current) return;
    setOffset({ x: dragRef.current.ox + (e.clientX - dragRef.current.x),
                y: dragRef.current.oy + (e.clientY - dragRef.current.y) });
  }
  function endDrag() { dragRef.current = null; }

  if (!image) return null;
  const idx = items ? items.findIndex(i => i.id === image.id) : -1;
  const zoomed = scale > 1;

  return (
    <div className="sg-lightbox" onClick={onClose}>
      <button className="sg-lb-close" onClick={onClose}>✕</button>
      <button className="sg-lb-nav prev" onClick={e => { e.stopPropagation(); onPrev(); }}>‹</button>
      <button className="sg-lb-nav next" onClick={e => { e.stopPropagation(); onNext(); }}>›</button>

      <div className="sg-lb-content" onClick={e => e.stopPropagation()}>
        {/* Fixed-size viewport (86vw × 78vh). The inner wrapper is uniformly
            transformed for zoom/pan so ImageWithOverlays' contain-fit boxes stay
            registered. Wheel = zoom, drag = pan (when zoomed). */}
        <div
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={endDrag}
          onMouseLeave={endDrag}
          onDoubleClick={toggleZoom}
          style={{ position: 'relative', width: '86vw', height: '78vh', overflow: 'hidden',
                   cursor: zoomed ? (dragRef.current ? 'grabbing' : 'grab') : 'zoom-in' }}>
          <div style={{ position: 'absolute', inset: 0,
                        transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
                        transformOrigin: 'center center',
                        transition: dragRef.current ? 'none' : 'transform .12s ease-out' }}>
            <ImageWithOverlays
              src={image.preview}
              fallbackSrc={image.thumb}
              subjects={image.metrics?.subjects}
              decoded={image.metrics?.decoded_size}
              ocr={image.ocr}
              naturalSize={[image.width || 6016, image.height || 4016]}
              showBoxes={showBoxes && !zoomed}
              imgStyle={{ boxShadow: '0 30px 80px rgba(0,0,0,0.9)', border: '1px solid var(--c-border)',
                          imageRendering: zoomed ? 'auto' : 'auto' }}
            />
          </div>
          {/* Zoom controls */}
          <div style={{ position:'absolute', bottom:14, right:14, display:'flex', gap:6, zIndex:3 }}
               onClick={e => e.stopPropagation()}>
            <button onClick={toggleZoom} style={lbZoomBtn(zoomed)}>{zoomed ? 'Fit' : '1:1'}</button>
            <span style={{ ...lbZoomBtn(false), cursor:'default', fontVariantNumeric:'tabular-nums' }}>
              {Math.round(scale * 100)}%
            </span>
          </div>
        </div>
        <div className="sg-lb-meta">
          <h4 style={{ fontFamily: 'var(--font-ui)', fontStyle: 'normal', fontSize: 15,
                       fontVariantNumeric: 'tabular-nums', letterSpacing: '0.02em' }}>
            №{pad(image.id, 4)}{' '}
            {idx >= 0 && items && (
              <span style={{ fontSize: 12, color: 'var(--c-mute)' }}>· {idx + 1}/{items.length}</span>
            )}
          </h4>
          <p>{image.path}</p>
          <p style={{ marginTop: 4 }}>{image.camera_model} · f/{image.f_number} · {image.exposure_time} · ISO {image.iso}</p>
          {(image.metrics?.subjects?.length > 0 || image.ocr?.length > 0) && (
            <label style={{ display:'inline-flex', alignItems:'center', gap:6, marginTop:8,
                            fontSize:9, letterSpacing:'.18em', textTransform:'uppercase',
                            color:'var(--c-text2)', cursor:'pointer' }}>
              <input type="checkbox" checked={showBoxes} onChange={e => setShowBoxes(e.target.checked)}
                     style={{ accentColor:'var(--c-accent)' }} />
              overlays
            </label>
          )}
          {/* Verdict + stars */}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 12 }}>
            {['keeper','review','reject'].map(v => {
              const c = verdictColor(v);
              return (
                <button key={v} onClick={() => onVerdict(v, null)} style={{
                  padding: '8px 16px', fontSize: 9, letterSpacing: '0.22em', textTransform: 'uppercase',
                  border: `1px solid ${image.verdict === v ? c : 'var(--c-border2)'}`,
                  color: image.verdict === v ? c : 'var(--c-text2)',
                  background: 'transparent', cursor: 'pointer', borderRadius: 'var(--radius)',
                  fontFamily: 'var(--font-ui)',
                }}>{v}</button>
              );
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 2, marginTop: 10 }}>
            {[1,2,3,4,5].map(s => (
              <button key={s} onClick={() => onVerdict(null, s)} style={{
                fontSize: 20, color: s <= (image.stars || 0) ? 'var(--c-amber)' : 'var(--c-border2)',
                background: 'none', border: 'none', cursor: 'pointer',
              }}>{s <= (image.stars || 0) ? '★' : '☆'}</button>
            ))}
          </div>
          {/* Compact tags strip in lightbox */}
          {(image.content_type !== 'photo' || image.animals?.length > 0 || image.ocr?.length > 0) && (
            <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 5, justifyContent: 'center' }}>
              {image.content_type !== 'photo' && (
                <span style={{ padding: '2px 8px', fontSize: 8, letterSpacing: '0.2em',
                               textTransform: 'uppercase', fontFamily: 'var(--font-ui)',
                               background: image.content_type === 'screenshot' ? 'var(--c-amber)' : 'var(--c-accent)',
                               color: 'var(--c-bg)', borderRadius: 'var(--radius)' }}>
                  {image.content_type === 'screenshot' ? '🖥' : '📄'} {image.content_type}
                </span>
              )}
              {image.animals?.map((a, i) => (
                <span key={i} style={{ padding: '2px 8px', fontSize: 8, letterSpacing: '0.2em',
                                       textTransform: 'uppercase', fontFamily: 'var(--font-ui)',
                                       border: '1px solid var(--c-border2)', color: 'var(--c-text2)',
                                       borderRadius: 'var(--radius)' }}>
                  🐾 {a.species}
                </span>
              ))}
              {image.ocr?.length > 0 && (
                <span style={{ padding: '2px 8px', fontSize: 8, letterSpacing: '0.2em',
                               textTransform: 'uppercase', fontFamily: 'var(--font-ui)',
                               border: '1px solid var(--c-border2)', color: 'var(--c-text2)',
                               borderRadius: 'var(--radius)' }}>
                  OCR · {image.ocr.length} regions
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  TABS, TAB_TITLES, pad, verdictColor, Chip, Btn, EmptyState,
  MetricTags, Sidebar, TopBar, DetailPanel, Lightbox,
});
