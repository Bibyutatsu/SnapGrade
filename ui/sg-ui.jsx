// SnapGrade — Shared UI components
// Exports: TABS, TAB_TITLES, pad, verdictColor,
//          Sidebar, TopBar, DetailPanel, Lightbox,
//          Chip, Btn, MetricTags

const { useState, useEffect, useCallback, useRef, useContext, createContext } = React;

// Single source of truth for cross-screen data (libraries, stats) + the refresh
// entry point, so screens stop each reading window.SG_DATA at mount and drifting.
const SGDataContext = createContext(null);
function useSGData() {
  return useContext(SGDataContext) || {
    libraries: window.SG_DATA.MOCK_LIBRARIES,
    stats: window.SG_DATA.MOCK_STATS,
    refresh: () => window.SG_REFRESH?.(),
  };
}

// Third field is the short label shown when the sidebar collapses to 56px.
const TABS = [
  ["library",  "Library",       "Lib"],
  ["triage",   "Triage",        "Tri"],
  ["bursts",   "Bursts",        "Brst"],
  ["faces",    "Face Clusters", "Face"],
  ["xmp",      "XMP Export",    "XMP"],
  ["organize", "Organize",      "Org"],
  ["settings", "Settings",      "Set"],
];

const TAB_TITLES = {
  library:  "Library",
  triage:   "Triage",
  bursts:   "Bursts",
  faces:    "Face Clusters",
  xmp:      "XMP Export",
  organize: "Organize",
  settings: "Settings",
};

function pad(n, w = 3) { return String(n ?? 0).padStart(w, "0"); }

function EmptyState({ children, padding = '60px 20px' }) {
  return (
    <div style={{ textAlign:'center', padding, color:'var(--c-mute)', fontSize:14 }}>
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
    <button className={`sg-chip ${on ? 'on' : ''}`} onClick={onClick} style={style}>
      {children}
    </button>
  );
}

// Single source for the all/keeper/review/reject verdict-scope chip row, shared
// by Triage and XMP Export (previously duplicated inline in both).
const VERDICT_FILTERS = ['all', 'keeper', 'review', 'reject'];
function VerdictChips({ value, onChange }) {
  return VERDICT_FILTERS.map(v => (
    <Chip key={v} on={value === v} onClick={() => onChange(v)}>{v}</Chip>
  ));
}

function Btn({ variant = 'ghost', onClick, disabled, children, style = {} }) {
  const cls = variant && variant !== 'ghost' ? `sg-btn sg-btn-${variant}` : 'sg-btn';
  return (
    <button className={cls} onClick={onClick} disabled={disabled} style={style}>
      {children}
    </button>
  );
}

// ── ConfirmModal ──────────────────────────────────────────────────────────────
// Themed replacement for window.confirm — Esc cancels, Enter confirms. `body`
// may be any node so callers can show real counts at risk, not generic prose.
function ConfirmModal({ open, title, body, confirmLabel = 'Confirm', danger, onConfirm, onCancel }) {
  useEffect(() => {
    if (!open) return;
    const h = e => {
      if (e.key === 'Escape') onCancel();
      if (e.key === 'Enter')  onConfirm();
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [open, onConfirm, onCancel]);
  if (!open) return null;
  return (
    <div className="sg-modal-backdrop" onClick={onCancel}>
      <div className="sg-modal" onClick={e => e.stopPropagation()}>
        <h3 className="sg-modal-title">{title}</h3>
        <div className="sg-modal-body">{body}</div>
        <div className="sg-modal-actions">
          <Btn variant="ghost" onClick={onCancel}>Cancel</Btn>
          <Btn variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</Btn>
        </div>
      </div>
    </div>
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
    padding: '3px 9px', fontSize: 10, letterSpacing: '0.18em',
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
                {sceneConf != null && <span style={{ marginLeft: 4, opacity: 0.6, fontSize: 10 }}>{Math.round(sceneConf * 100)}%</span>}
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
                <span style={{ fontSize: 10, opacity: 0.6 }}> {Math.round(a.confidence * 100)}%</span>
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
                  <span style={{ fontSize: 10, color: 'var(--c-mute)', letterSpacing: '0.14em',
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
                fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
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

// Click-to-expand job error — the full message is no longer truncated away.
function JobError({ kind, error }) {
  const [open, setOpen] = useState(false);
  const long = error.length > 80;
  return (
    <div onClick={() => long && setOpen(o => !o)}
         title={long ? 'Click to expand' : ''}
         style={{ marginTop: 8, color: 'var(--c-danger)', cursor: long ? 'pointer' : 'default' }}>
      <div style={{ fontSize: 'var(--cap-size)', letterSpacing: '.1em', textTransform: 'uppercase' }}>
        {kind} error {long && <span style={{ opacity: .7 }}>{open ? '▴' : '▾'}</span>}
      </div>
      <div style={{ fontSize: 11, lineHeight: 1.4, wordBreak: 'break-word', marginTop: 2 }}>
        {open || !long ? error : error.slice(0, 80) + '…'}
      </div>
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
        {TABS.map(([k, label, short]) => (
          <React.Fragment key={k}>
            <button
              className={`sg-nav-btn ${tab === k ? 'on' : ''}`}
              onClick={() => setTab(k)}
              title={collapsed ? label : ''}
              style={{ justifyContent: collapsed ? 'center' : 'flex-start' }}
            >
              {collapsed
                ? <span className="sg-nav-n">{short}</span>
                : <span className="sg-nav-label">{label}</span>}
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
      {/* Collapsed: still surface that a background job is live so feedback isn't
          hidden behind the rail. */}
      {collapsed && stats && (stats.ingest?.running || stats.faces?.running) && (
        <div style={{ marginTop: 'auto', display: 'flex', justifyContent: 'center', paddingTop: 12 }}
             title={stats.ingest?.running ? 'Ingest running' : 'Face clustering running'}>
          <span className="sg-live-dot" />
        </div>
      )}
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
                {(stats.ingest.folders_total || 0) > 1 && (
                  <div className="sg-progress-label" style={{ marginBottom: 4 }}>
                    <span>folder {Math.min((stats.ingest.folders_done || 0) + 1, stats.ingest.folders_total)} / {stats.ingest.folders_total}</span>
                  </div>
                )}
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
          {stats.ingest?.error && <JobError kind="ingest" error={stats.ingest.error} />}
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
          {stats.faces?.error && <JobError kind="faces" error={stats.faces.error} />}
        </div>
      )}
    </aside>
  );
}

// ── Theme picker (lives in topbar) ────────────────────────────────────────────
// "Cinematic" is the only theme that can carry the (opt-in, off-by-default) grain
// + vignette + sprocket atmosphere; "Modern"/"Utility" are flat neutral working
// surfaces. (Underlying dark-film / dark-modern / light-pro token sets.)
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
          fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase',
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
        <span style={{ fontSize: 10, color: 'var(--c-mute)' }}>▾</span>
      </button>
      {open && (
        // Must clear the photo panes (.sg-grid/.sg-detail/.sg-scroll = 10000) and
        // lightbox/modal (10000/10001); otherwise the menu renders behind page
        // content and its lower items become both invisible and unclickable.
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', right: 0,
          minWidth: 180, zIndex: 10002,
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
  const title = TAB_TITLES[tab] || tab;
  return (
    <div className="sg-topbar">
      <div>
        <div className="sg-crumbs">SnapGrade · {new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</div>
        <div className="sg-page-title">{title}</div>
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
            fontSize: 10, letterSpacing: '0.18em', textTransform: 'uppercase',
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
const DETAIL_MIN_W = 300, DETAIL_MAX_W = 620;

// Color labels are independent of the verdict (which already owns keeper/review/
// reject). They express workflow state — e.g. blue = needs edit, purple = ready
// to share — and are written into the XMP sidecar.
const LABELS = [
  { key: null,     swatch: 'transparent',     name: 'None' },
  { key: 'blue',   swatch: '#3b82c4',         name: 'Needs edit' },
  { key: 'purple', swatch: '#9b59b6',         name: 'To print' },
  { key: 'green',  swatch: 'var(--c-keeper)', name: 'Ready' },
];

function DetailPanel({ image, onVerdict, onReveal, onOpenLightbox, compact }) {
  const [xmpMsg, setXmpMsg] = useState('');
  const [showBoxes, setShowBoxes] = useState(true);
  const writeXmp = () => {
    setXmpMsg('writing…');
    window.SG_API.xmp(image.id)
      .then(() => setXmpMsg('XMP sidecar written'))
      .catch(err => setXmpMsg(`XMP failed: ${err.message}`));
  };
  // User-resizable width (persisted) so the panel isn't a fixed 26%-of-screen
  // wall on a 1440px laptop. Compact (filmstrip) layout keeps its narrow width.
  const [width, setWidth] = useState(() => {
    const s = +localStorage.getItem('sg.detailW');
    return s >= DETAIL_MIN_W && s <= DETAIL_MAX_W ? s : 380;
  });
  const resizeRef = useRef(null);
  useEffect(() => {
    const move = e => {
      if (!resizeRef.current) return;
      const w = Math.min(DETAIL_MAX_W, Math.max(DETAIL_MIN_W,
        resizeRef.current.w + (resizeRef.current.x - e.clientX)));
      setWidth(w);
      localStorage.setItem('sg.detailW', String(w));
    };
    const up = () => { resizeRef.current = null; document.body.style.userSelect = ''; };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); };
  }, []);
  const startResize = e => {
    resizeRef.current = { x: e.clientX, w: width };
    document.body.style.userSelect = 'none';
    e.preventDefault();
  };
  const panelW = compact ? 280 : width;
  const ResizeHandle = compact ? null : (
    <div onMouseDown={startResize} title="Drag to resize"
         style={{ position:'absolute', left:-3, top:0, bottom:0, width:6, cursor:'col-resize', zIndex:2 }} />
  );

  if (!image) return (
    <aside className="sg-detail" style={{ width: panelW, position:'relative' }}>
      {ResizeHandle}
      <div className="sg-detail-empty">
        <div style={{ fontSize: 14, color: 'var(--c-text2)', marginBottom: 8 }}>No frame selected.</div>
        <div style={{ fontSize: 'var(--cap-size)', letterSpacing: 'var(--cap-track)', textTransform: 'uppercase',
                      color: 'var(--c-mute)' }}>Pick from the grid</div>
      </div>
    </aside>
  );

  const m = image;
  const vColors = { keeper: 'var(--c-keeper)', review: 'var(--c-amber)', reject: 'var(--c-danger)' };

  return (
    <aside className="sg-detail" style={{ width: panelW, position:'relative' }}>
      {ResizeHandle}
      {/* Preview */}
      {!compact && (
        <div className="sg-detail-preview" onClick={onOpenLightbox}
             style={{ cursor: 'zoom-in', position: 'relative' }}>
          <img src={m.thumb} alt="" style={{ width: '100%', display: 'block' }}
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
              fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
              padding: '3px 8px', fontFamily: 'var(--font-ui)',
            }}>
              {m.content_type === 'screenshot' ? '🖥' : '📄'} {m.content_type}
            </div>
          )}
          {m.metrics?.live_photo && (
            <div title={`Live Photo · ${m.metrics.live_photo.video || ''}`} style={{
              position: 'absolute', top: 8, left: 10,
              background: 'rgba(10,9,7,0.7)', color: 'var(--c-text)',
              fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
              padding: '3px 8px', fontFamily: 'var(--font-ui)', borderRadius: 'var(--radius)',
            }}>◉ Live</div>
          )}
          <div style={{ position: 'absolute', bottom: 8, right: 10, fontSize: 10, opacity: 0.6,
                        letterSpacing: '0.1em', color: 'var(--c-text)', fontFamily: 'var(--font-ui)' }}>⤢ full</div>
        </div>
      )}

      <div className="sg-detail-body">
        <div className="sg-detail-path">{m.path.split('/').pop()}</div>

        {!compact && m.metrics?.subjects?.length > 0 && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10,
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
                flex: 1, padding: '9px 0', fontSize: 10, letterSpacing: '0.1em',
                textTransform: 'uppercase',
                border: `1px solid ${m.verdict === v ? vColors[v] : 'var(--c-border2)'}`,
                color: m.verdict === v ? vColors[v] : 'var(--c-mute)',
                background: 'transparent', cursor: 'pointer', borderRadius: 'var(--radius)',
                fontFamily: 'var(--font-ui)',
              }}>{v}</button>
            ))}
          </div>
        </div>

        {/* Stars — only on keeper/review; rejects show no rating (Lightroom model). */}
        {m.verdict !== 'reject' && (
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
        )}

        {/* Color label — workflow state, independent of verdict. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="sg-detail-label" style={{ marginBottom: 0, marginRight: 4 }}>Label</span>
          {LABELS.map(l => (
            <button key={l.key || 'none'} title={l.name} onClick={() => onVerdict(null, null, l.key)}
              style={{ width: 18, height: 18, borderRadius: '50%', cursor: 'pointer',
                       background: l.swatch,
                       border: `2px solid ${m.label === l.key ? 'var(--c-text)' : 'var(--c-border2)'}`,
                       boxShadow: m.label === l.key ? '0 0 0 1px var(--c-text)' : 'none' }} />
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
                      style={{ marginLeft:4, padding:'1px 6px', borderRadius:'999px', border:'1px solid var(--c-amber)', color:'var(--c-amber)', fontSize:10, fontFamily:'var(--font-ui)', fontStyle:'normal', letterSpacing:'.1em', cursor:'help', verticalAlign:'1px' }}
                    >?</span>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        )}

        {/* Advisories — informational, did not drive the verdict. */}
        {m.warnings && m.warnings.length > 0 && (
          <div style={{ fontSize: 11, color: 'var(--c-text2)', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {m.warnings.map((w, i) => (
              <span key={i} style={{ padding: '2px 8px', border: '1px dashed var(--c-border2)',
                                     borderRadius: 'var(--radius)', color: 'var(--c-mute)' }}>ⓘ {w}</span>
            ))}
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

        {/* File actions */}
        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
          <Btn variant="ghost" onClick={writeXmp} style={{ flex: 1, padding: '8px 0' }}>Write XMP</Btn>
          {onReveal && <Btn variant="ghost" onClick={() => onReveal(image.id)} style={{ flex: 1, padding: '8px 0' }}>Reveal ↗</Btn>}
        </div>

        {xmpMsg && <div style={{ fontSize: 10, color: 'var(--c-amber)', marginTop: 6 }}>→ {xmpMsg}</div>}
      </div>
    </aside>
  );
}

// ── Lightbox ──────────────────────────────────────────────────────────────────
function lbZoomBtn(active) {
  return {
    padding: '5px 11px', fontSize: 10, letterSpacing: '0.18em', textTransform: 'uppercase',
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
  // subject/OCR boxes stay registered at any zoom. Zoom is incremental and
  // focused on the cursor; offset keeps the focal point fixed under the pointer.
  const [scale, setScale]   = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [hiRes, setHiRes]   = useState(null);  // native-res src, fetched once on first zoom-in
  const dragRef     = useRef(null);
  const viewportRef = useRef(null);

  // Reset when the frame changes.
  useEffect(() => { setScale(1); setOffset({ x: 0, y: 0 }); setHiRes(null); }, [image && image.id]);

  // Force a recompute of maxScale on window resize so 1:1 stays honest.
  const [, forceTick] = useState(0);
  useEffect(() => {
    const h = () => forceTick(t => t + 1);
    window.addEventListener('resize', h);
    return () => window.removeEventListener('resize', h);
  }, []);

  // Native-pixel ("1:1") scale relative to the fit-rendered size — the max useful
  // magnification (beyond it we'd just upscale). Measure the live viewport rect
  // rather than window.innerHeight*0.78 so it's correct after a resize.
  const oneToOne = useCallback(() => {
    const W = image?.width || 6016, H = image?.height || 4016;
    const vp = viewportRef.current?.getBoundingClientRect();
    const vw = vp?.width  || window.innerWidth  * 0.86;
    const vh = vp?.height || window.innerHeight * 0.78;
    const ar = W / H;
    const renderedW = (vw / vh > ar) ? vh * ar : vw;
    return Math.max(1, Math.min(8, W / renderedW));
  }, [image]);
  const maxScale = oneToOne();

  // Zoom to `next` while keeping the point (fx,fy) — measured from the viewport
  // centre — pinned under the cursor. With transformOrigin at centre, a point at
  // offset p from centre maps to p*scale + translate; solving to hold it fixed:
  //   t' = t + (fx - cx)·(next - prev) ... expressed about the centre.
  const zoomTo = useCallback((next, clientX, clientY) => {
    next = Math.max(1, Math.min(maxScale, next));
    setScale(prev => {
      if (next <= 1) { setOffset({ x: 0, y: 0 }); return 1; }
      const vp = viewportRef.current?.getBoundingClientRect();
      if (vp && clientX != null) {
        const fx = clientX - (vp.left + vp.width / 2);
        const fy = clientY - (vp.top + vp.height / 2);
        const ratio = next / prev;
        setOffset(o => ({ x: fx - (fx - o.x) * ratio, y: fy - (fy - o.y) * ratio }));
      }
      return next;
    });
  }, [maxScale]);

  const reset = useCallback(() => { setScale(1); setOffset({ x: 0, y: 0 }); }, []);

  useEffect(() => {
    const handler = e => {
      if (e.key === 'Escape')                      onClose();
      if (e.key === 'ArrowLeft'  || e.key === 'k') onPrev();
      if (e.key === 'ArrowRight' || e.key === 'j') onNext();
      if (e.key === 'z') onVerdict('keeper', null);
      if (e.key === 'c') onVerdict('review', null);
      if (e.key === 'x') onVerdict('reject', null);
      if (e.key === '0' || e.key === 'f') reset();
      if (e.key === '1') zoomTo(maxScale);
      if (e.key === '+' || e.key === '=') zoomTo(scale * 1.4);
      if (e.key === '-' || e.key === '_') zoomTo(scale / 1.4);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose, onPrev, onNext, onVerdict, reset, zoomTo, maxScale, scale]);

  // Fetch native-res pixels the first time the user zooms past fit, so detail is
  // real instead of an upscaled 1600px preview. Loads once per frame.
  useEffect(() => {
    if (scale > 1 && !hiRes && image) setHiRes(`${image.preview}?long_edge=6000`);
  }, [scale, hiRes, image]);

  // Native non-passive listener so preventDefault() can stop the page scrolling
  // while wheel-zooming (React's synthetic onWheel is passive and would warn).
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = e => {
      e.preventDefault();
      zoomTo(scale * (e.deltaY < 0 ? 1.2 : 1 / 1.2), e.clientX, e.clientY);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomTo, scale]);

  function onDoubleClick(e) {
    e.preventDefault();
    if (scale > 1) reset();
    else zoomTo(Math.min(2.5, maxScale), e.clientX, e.clientY);
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
          ref={viewportRef}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={endDrag}
          onMouseLeave={endDrag}
          onDoubleClick={onDoubleClick}
          style={{ position: 'relative', width: '86vw', height: '78vh', overflow: 'hidden',
                   cursor: zoomed ? (dragRef.current ? 'grabbing' : 'grab') : 'zoom-in' }}>
          <div style={{ position: 'absolute', inset: 0,
                        transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
                        transformOrigin: 'center center',
                        transition: dragRef.current ? 'none' : 'transform .12s ease-out' }}>
            <ImageWithOverlays
              src={hiRes || image.preview}
              fallbackSrc={image.thumb}
              subjects={image.metrics?.subjects}
              decoded={image.metrics?.decoded_size}
              ocr={image.ocr}
              naturalSize={[image.width || 6016, image.height || 4016]}
              showBoxes={showBoxes}
              imgStyle={{ boxShadow: '0 30px 80px rgba(0,0,0,0.9)', border: '1px solid var(--c-border)',
                          imageRendering: zoomed ? 'auto' : 'auto' }}
            />
          </div>
          {/* Zoom controls */}
          <div style={{ position:'absolute', bottom:14, right:14, display:'flex', gap:6, zIndex:3 }}
               onClick={e => e.stopPropagation()}>
            <button onClick={() => zoomTo(scale / 1.4)} disabled={!zoomed} style={lbZoomBtn(false)}>−</button>
            <button onClick={() => zoomTo(scale * 1.4)} style={lbZoomBtn(false)}>+</button>
            <button onClick={() => (zoomed ? reset() : zoomTo(maxScale))} style={lbZoomBtn(zoomed)}>{zoomed ? 'Fit' : '1:1'}</button>
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
          {/* Quality strip — the numbers that drove the verdict, pinned here so
              you can confirm sharpness at 100% without reopening the detail panel. */}
          <div style={{ marginTop: 8, display:'flex', gap:14, justifyContent:'center', flexWrap:'wrap',
                        fontFamily:'var(--font-ui)', fontVariantNumeric:'tabular-nums', fontSize:11 }}>
            <span style={{ color: image.sharpness > 0.55 ? 'var(--c-keeper)' : image.sharpness > 0.32 ? 'var(--c-amber)' : 'var(--c-danger)' }}>
              Sharp {Math.round((image.sharpness || 0) * 100)}%
            </span>
            <span style={{ color: 'var(--c-text2)' }}>
              Aesthetic {image.aesthetic_score != null ? Math.round(image.aesthetic_score * 100) + '%' : '—'}
            </span>
            <span style={{ color: verdictColor(image.verdict), textTransform:'uppercase', letterSpacing:'.1em' }}>
              {image.verdict || 'unrated'}
            </span>
          </div>
          {(image.metrics?.subjects?.length > 0 || image.ocr?.length > 0) && (
            <label style={{ display:'inline-flex', alignItems:'center', gap:6, marginTop:8,
                            fontSize:10, letterSpacing:'.18em', textTransform:'uppercase',
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
                  padding: '8px 16px', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase',
                  border: `1px solid ${image.verdict === v ? c : 'var(--c-border2)'}`,
                  color: image.verdict === v ? c : 'var(--c-text2)',
                  background: 'transparent', cursor: 'pointer', borderRadius: 'var(--radius)',
                  fontFamily: 'var(--font-ui)',
                }}>{v}</button>
              );
            })}
          </div>
          {image.verdict !== 'reject' && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: 2, marginTop: 10 }}>
              {[1,2,3,4,5].map(s => (
                <button key={s} onClick={() => onVerdict(null, s)} style={{
                  fontSize: 20, color: s <= (image.stars || 0) ? 'var(--c-amber)' : 'var(--c-border2)',
                  background: 'none', border: 'none', cursor: 'pointer',
                }}>{s <= (image.stars || 0) ? '★' : '☆'}</button>
              ))}
            </div>
          )}
          {/* Compact tags strip in lightbox */}
          {(image.content_type !== 'photo' || image.animals?.length > 0 || image.ocr?.length > 0) && (
            <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 5, justifyContent: 'center' }}>
              {image.content_type !== 'photo' && (
                <span style={{ padding: '2px 8px', fontSize: 10, letterSpacing: '0.12em',
                               textTransform: 'uppercase', fontFamily: 'var(--font-ui)',
                               background: image.content_type === 'screenshot' ? 'var(--c-amber)' : 'var(--c-accent)',
                               color: 'var(--c-bg)', borderRadius: 'var(--radius)' }}>
                  {image.content_type === 'screenshot' ? '🖥' : '📄'} {image.content_type}
                </span>
              )}
              {image.animals?.map((a, i) => (
                <span key={i} style={{ padding: '2px 8px', fontSize: 10, letterSpacing: '0.12em',
                                       textTransform: 'uppercase', fontFamily: 'var(--font-ui)',
                                       border: '1px solid var(--c-border2)', color: 'var(--c-text2)',
                                       borderRadius: 'var(--radius)' }}>
                  🐾 {a.species}
                </span>
              ))}
              {image.ocr?.length > 0 && (
                <span style={{ padding: '2px 8px', fontSize: 10, letterSpacing: '0.12em',
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
  TABS, TAB_TITLES, pad, verdictColor, Chip, Btn, VerdictChips, EmptyState, ConfirmModal,
  MetricTags, Sidebar, TopBar, DetailPanel, Lightbox, SGDataContext, useSGData,
});
