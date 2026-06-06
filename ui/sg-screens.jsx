// SnapGrade — Secondary Screens
// Library, Bursts, Faces, XMP Export, Organize, Settings

const { useState, useEffect, useMemo, useCallback, useRef } = React;

// ── Shared library filter bar ─────────────────────────────────────────────────
function LibraryFilterBar({ activeLib, setActiveLib, counts }) {
  const { libraries: MOCK_LIBRARIES } = useSGData();
  return (
    <div style={{
      display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap',
      padding: '9px 20px', borderBottom: '1px solid var(--c-border)',
      background: 'var(--c-panel2)', flexShrink: 0,
    }}>
      <span style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase',
                     color: 'var(--c-mute)', marginRight: 4 }}>Folder</span>
      <Chip on={activeLib === null} onClick={() => setActiveLib(null)}>
        All {counts?.all != null && <span style={{ marginLeft: 5, opacity: 0.55 }}>{counts.all}</span>}
      </Chip>
      {MOCK_LIBRARIES.map(lib => (
        <Chip key={lib.id} on={activeLib === lib.id} onClick={() => setActiveLib(lib.id)}>
          {lib.display_name || lib.root_path.split('/').pop()}
          {counts?.[lib.id] != null && <span style={{ marginLeft: 5, opacity: 0.55 }}>{counts[lib.id]}</span>}
        </Chip>
      ))}
    </div>
  );
}

// ── Library Screen ─────────────────────────────────────────────────────────
function LibraryScreen({ stats, setTab }) {
  const { MOCK_LIBRARIES } = window.SG_DATA;
  const [folders, setFolders] = useState([]);
  const [msg, setMsg]       = useState('');
  const [enabled, setEnabled] = useState({ content_type: true, scene: true, subject_seg: true, objects: true, semantic: true, depth: true, face_landmarker: true });
  const [postSteps, setPostSteps] = useState({ group: true, faces: true });
  const [query, setQuery]   = useState('');
  const [results, setResults] = useState(null);  // null = no search yet, [] = empty results
  const [searching, setSearching] = useState(false);
  const [searchMsg, setSearchMsg] = useState('');
  const [recent, setRecent] = useState(() => {
    try { return JSON.parse(localStorage.getItem('sg.recentSearches') || '[]'); } catch { return []; }
  });
  const pushRecent = q => setRecent(prev => {
    const next = [q, ...prev.filter(x => x !== q)].slice(0, 6);
    localStorage.setItem('sg.recentSearches', JSON.stringify(next));
    return next;
  });
  // Hand the result ids to Triage as a scoped view instead of a tab per result.
  const openInTriage = () => {
    if (!results || !results.length) return;
    window.SG_SEARCH = { query, ids: results.map(r => r.image_id) };
    setTab && setTab('triage');
  };
  const [statsOpen, setStatsOpen] = useState(false);  // stats collapsed by default for returning users
  const [confirmRemove, setConfirmRemove] = useState(null);  // {id, name} pending removal
  
  // State for ingestion errors modal
  const [activeErrorLib, setActiveErrorLib] = useState(null);  // { id, name }
  const [errorList, setErrorList] = useState([]);
  const [errorLoading, setErrorLoading] = useState(false);

  const showErrorsForLibrary = async (id, name) => {
    setActiveErrorLib({ id, name });
    setErrorLoading(true);
    try {
      const r = await window.SG_API.loadLibraryErrors(id);
      setErrorList(r.errors || []);
    } catch (e) {
      setErrorList([{ path: 'Error loading', error: e.message }]);
    } finally {
      setErrorLoading(false);
    }
  };

  // Model availability — fetched once on mount and after each download completes.
  const [modelStatus, setModelStatus] = useState(null);
  const [downloadMsg, setDownloadMsg] = useState({});  // {name: 'downloading'|'done'|'error'}

  useEffect(() => {
    let alive = true;
    async function fetchModels() {
      try {
        const r = await window.SG_API.listModels();
        if (alive) {
          setModelStatus(r.models || []);
          setEnabled(prev => {
            const next = { ...prev };
            (r.models || []).forEach(m => {
              if (next[m.name] === undefined) {
                next[m.name] = true;
              }
            });
            return next;
          });
        }
      } catch { /* backend not ready yet or API missing */ }
    }
    fetchModels();
    return () => { alive = false; };
  }, []);

  async function downloadModel(name) {
    if (downloadMsg[name] === 'downloading') return;
    setDownloadMsg(m => ({ ...m, [name]: 'downloading' }));
    try {
      await window.SG_API.downloadModel(name);
      // Poll until the model file is confirmed available on disk.
      const poll = setInterval(async () => {
        try {
          const r = await window.SG_API.listModels();
          const found = (r.models || []).find(x => x.name === name);
          if (found?.available) {
            clearInterval(poll);
            setModelStatus(r.models || []);
            setDownloadMsg(d => ({ ...d, [name]: 'done' }));
          }
        } catch { clearInterval(poll); setDownloadMsg(d => ({ ...d, [name]: 'error' })); }
      }, 1500);
      // Safety: stop polling after 10 min regardless
      setTimeout(() => clearInterval(poll), 600_000);
    } catch (e) {
      setDownloadMsg(d => ({ ...d, [name]: 'error' }));
    }
  }

  // Auto-download when checkbox is ticked and model is not yet cached.
  function handleModelToggle(k, checked) {
    setEnabled(s => ({ ...s, [k]: checked }));
    if (checked && MODEL_INFO[k]?.download) {
      const status = (modelStatus || []).find(m => m.name === k);
      if (status && !status.available && !downloadMsg[k]) {
        downloadModel(k);
      }
    }
  }

  async function runSearch(qOverride) {
    const q = (qOverride ?? query).trim();
    if (!q) return;
    if (qOverride != null) setQuery(qOverride);
    setSearching(true);
    setSearchMsg('');
    try {
      const items = await window.SG_API.search(q, { k: 24 });
      setResults(items);
      if (items.length) pushRecent(q);
      if (!items.length) {
        setSearchMsg('No matches. Re-run analyze with SNAPGRADE_ENABLE_SEMANTIC=1 if no embeddings exist yet.');
      }
    } catch (e) {
      setSearchMsg(`search failed: ${e.message}`);
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  async function pickFolder() {
    setMsg('');
    try {
      const picked = await window.SG_API.pickFolder();
      if (picked && picked.length) {
        setFolders(prev => [...prev, ...picked.filter(p => !prev.includes(p))]);
      }
    } catch (e) { setMsg(`folder picker failed: ${e.message}`); }
  }

  async function pickPhotosLibrary() {
    setMsg('');
    try {
      const picked = await window.SG_API.pickPhotosLibrary();
      if (picked && picked.length) {
        setFolders(prev => [...prev, ...picked.filter(p => !prev.includes(p))]);
      }
    } catch (e) { setMsg(`Photos library picker failed: ${e.message}`); }
  }

  // Poll /api/stats.ingest until it goes idle, then resolve. Used to chain
  // /api/group and /api/faces/run after the ingest BackgroundTask finishes.
  function waitForIngestIdle(timeoutMs = 30 * 60 * 1000) {
    return new Promise((resolve, reject) => {
      const t0 = Date.now();
      const id = setInterval(async () => {
        try {
          const s = await window.SG_API.refreshStats();
          if (s && !s.ingest?.running) { clearInterval(id); resolve(s); }
          else if (Date.now() - t0 > timeoutMs) { clearInterval(id); reject(new Error('ingest timeout')); }
        } catch (e) { /* keep polling */ }
      }, 2000);
    });
  }

  async function develop() {
    if (!folders.length) return;
    setMsg('');
    try {
      const models = Object.entries(enabled).filter(([, v]) => v).map(([k]) => k);
      const r = await window.SG_API.ingest(folders, models);
      const n = r.libraries?.length ?? folders.length;
      setMsg(`ingest started for ${n} folder${n === 1 ? '' : 's'}`);
      if (postSteps.group || postSteps.faces) {
        await waitForIngestIdle();
        if (postSteps.group) {
          setMsg('ingest done · grouping bursts…');
          try { await window.SG_API.regroup(); }
          catch (e) { setMsg(`regroup failed: ${e.message}`); return; }
        }
        if (postSteps.faces) {
          setMsg('grouping done · launching face clustering…');
          try { await window.SG_API.runFaces(); }
          catch (e) { setMsg(`face clustering launch failed: ${e.message}`); return; }
        }
        setMsg('post-ingest steps started · progress shows in the sidebar');
      }
    } catch (e) { setMsg(`ingest failed: ${e.message}`); }
  }
  async function syncLib(id) {
    setMsg('');
    try { await window.SG_API.syncLibrary(id); setMsg(`sync started for library #${id}`); }
    catch (e) { setMsg(`sync failed: ${e.message}`); }
  }
  async function removeLib(id) {
    setConfirmRemove(null);
    setMsg('');
    try { await window.SG_API.removeLibrary(id); setMsg(`removed library #${id}`); await window.SG_REFRESH?.(); }
    catch (e) { setMsg(`remove failed: ${e.message}`); }
  }

  // Human-readable labels/notes for known model names.
  // The checklist iterates over the API response (modelStatus) — this map is
  // only for display. Models the API knows about but not listed here fall back
  // to their raw name and filename as label/note.
  const MODEL_INFO = {
    scene:          { label: 'Scene classifier',       note: 'Places365 — adds {scene} organise token',                      download: true  },
    subject_seg:    { label: 'Salient subject seg',    note: 'U²-Netp — better subject mask for sharpness',                  download: true  },
    objects:        { label: 'Object detector',        note: 'YOLO26n — COCO classes, adds {object:class} token',            download: true  },
    depth:          { label: 'Depth estimation',       note: 'Depth Anything V2 Small — per-pixel depth map',                download: true  },
    content_type:   { label: 'Screenshot / document',  note: 'Apple Vision — no download, runs on Neural Engine',            download: false },
    semantic:       { label: 'Semantic search index',  note: 'MobileCLIP-S0 — 512-d embedding per image, enables text search', download: true },
    face_landmarker:{ label: 'Face landmarker',        note: 'MediaPipe — blink detection & expression scoring',             download: true  },
  };

  // Merge: start from API models (source of truth for availability), then append
  // any MODEL_INFO entries not returned by the API (e.g. content_type = built-in).
  const apiNames = new Set((modelStatus || []).map(m => m.name));
  const builtInRows = Object.entries(MODEL_INFO)
    .filter(([k, v]) => !v.download && !apiNames.has(k))
    .map(([k, v]) => ({ name: k, available: true, download_url: '', filename: '' }));
  const allModelRows = [...(modelStatus || []), ...builtInRows];



  return (
    <div className="sg-scroll">
      <div className="sg-page">
        <p className="sg-lede">Point the lens at a folder. Frames are read, measured, and filed — nothing is moved, nothing is altered.</p>

        {/* Search — a slim affordance above the data, not a numbered workflow step. */}
        <div style={{ display:'flex', gap:8, alignItems:'stretch', marginBottom:24 }}>
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') runSearch(); }}
            placeholder='⌕  Search by description — "crowd of people", "text on a sign"…'
            className="sg-folder-display"
            style={{ flex:1, minHeight:'auto', padding:'9px 12px', color:'var(--c-text)', fontStyle:'normal' }}
          />
          <Btn variant="primary" disabled={!query.trim() || searching} onClick={() => runSearch()}>
            {searching ? 'Searching…' : 'Search'}
          </Btn>
        </div>
        {recent.length > 0 && !results && (
          <div style={{ display:'flex', gap:6, alignItems:'center', flexWrap:'wrap', marginTop:-14, marginBottom:18 }}>
            <span style={{ fontSize:'var(--cap-size)', letterSpacing:'var(--cap-track)', textTransform:'uppercase', color:'var(--c-mute)' }}>Recent</span>
            {recent.map(q => <Chip key={q} onClick={() => runSearch(q)}>{q}</Chip>)}
          </div>
        )}
        {searchMsg && <div className="sg-toast" style={{ marginTop:-14, marginBottom:18 }}>{searchMsg}</div>}
        {results && results.length > 0 && (
          <>
            <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10 }}>
              <span style={{ fontSize:'var(--cap-size)', letterSpacing:'var(--cap-track)', textTransform:'uppercase', color:'var(--c-mute)' }}>
                {results.length} matches for “{query}”
              </span>
              <Btn variant="primary" onClick={openInTriage} style={{ padding:'5px 13px' }}>Open in Triage →</Btn>
              <button onClick={() => setResults(null)} style={{ fontSize:'var(--cap-size)', letterSpacing:'var(--cap-track)', textTransform:'uppercase', color:'var(--c-mute)', background:'none', border:'none', cursor:'pointer', fontFamily:'var(--font-ui)' }}>clear ×</button>
            </div>
            <div style={{ marginBottom:24, display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(140px, 1fr))', gap:10 }}>
              {results.map(r => (
                <a key={r.image_id} href={`/api/images/${r.image_id}/preview?long_edge=2000`} target="_blank" rel="noreferrer"
                   style={{ position:'relative', display:'block', aspectRatio:'1/1', overflow:'hidden', borderRadius:'var(--radius)', border:'1px solid var(--c-border2)' }}>
                  <img src={r.thumb} alt="" loading="lazy" style={{ width:'100%', height:'100%', objectFit:'cover', display:'block' }} />
                  <span style={{ position:'absolute', bottom:4, right:4, fontSize:10, padding:'2px 6px', background:'rgba(0,0,0,0.7)', color:'#fff', borderRadius:'var(--radius)', letterSpacing:'0.05em', fontVariantNumeric:'tabular-nums' }}>
                    {r.score.toFixed(3)}
                  </span>
                </a>
              ))}
            </div>
          </>
        )}

        {/* Hero: the actual data a returning user came for. */}
        <div className="sg-card">
          <h2 className="sg-card-h2">Your <em>libraries</em>.</h2>
          <div className="sg-card-sub">Each folder tracked independently · remove without touching disk</div>
          <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
            {MOCK_LIBRARIES.map(lib => {
              const v = lib.by_verdict || {};
              return (
                <div key={lib.id} className="sg-lib-row">
                  <div style={{ flex:1 }}>
                    <div style={{ fontWeight:600, fontSize:15, color:'var(--c-text)', marginBottom:2 }}>{lib.display_name}</div>
                    <div style={{ fontSize:10, color:'var(--c-mute)', marginBottom:8, wordBreak:'break-all' }}>{lib.root_path}</div>
                    <div style={{ display:'flex', gap:18, fontSize:11, color:'var(--c-text2)', flexWrap:'wrap' }}>
                      <span><b style={{ color:'var(--c-text)', fontVariantNumeric:'tabular-nums' }}>{lib.image_count}</b> frames</span>
                      <span style={{ color:'var(--c-keeper)' }}><b>{v.keeper||0}</b> keep</span>
                      <span style={{ color:'var(--c-amber)' }}><b>{v.review||0}</b> review</span>
                      <span style={{ color:'var(--c-danger)' }}><b>{v.reject||0}</b> reject</span>
                      {lib.error_count > 0 && (
                        <span style={{ color:'var(--c-danger)', cursor:'pointer', textDecoration:'underline' }} onClick={() => showErrorsForLibrary(lib.id, lib.display_name || lib.root_path)}>
                          <b>{lib.error_count}</b> failed
                        </span>
                      )}
                    </div>
                    <div style={{ display:'flex', gap:6, marginTop:8, flexWrap:'wrap' }}>
                      {Object.keys(lib.models_run || {}).map(m => (
                        <span key={m} style={{ fontSize:10, letterSpacing: '0.12em', textTransform:'uppercase', padding:'3px 8px', border:'1px solid var(--c-keeper)', color:'var(--c-keeper)', borderRadius:'var(--radius)' }}>{m} ✓</span>
                      ))}
                    </div>
                  </div>
                  <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
                    <Btn variant="ghost"  style={{ fontSize:10, padding:'6px 12px' }} onClick={() => syncLib(lib.id)}>Sync</Btn>
                    <Btn variant="danger" style={{ fontSize:10, padding:'6px 12px' }} onClick={() => setConfirmRemove({ id: lib.id, name: lib.display_name || lib.root_path })}>Remove</Btn>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Stats — collapsed by default; a returning user wants the list, not counts. */}
        {stats && (
          <div className="sg-card" style={{ padding:0 }}>
            <button onClick={() => setStatsOpen(o => !o)}
              style={{ width:'100%', textAlign:'left', background:'none', border:'none',
                       cursor:'pointer', padding:'18px 28px', display:'flex',
                       alignItems:'center', justifyContent:'space-between' }}>
              <span>
                <span className="sg-card-h2" style={{ display:'block' }}>State of the <em>library</em>.</span>
                <span className="sg-card-sub" style={{ display:'block', marginBottom:0 }}>
                  {pad(stats.images,1)} frames · {pad(stats.libraries,1)} libraries · live counts
                </span>
              </span>
              <span style={{ fontSize:12, color:'var(--c-mute)', transition:'transform .15s',
                             transform: statsOpen ? 'none' : 'rotate(-90deg)' }}>▾</span>
            </button>
            {statsOpen && (
              <div className="sg-statgrid">
                {[
                  { v: pad(stats.libraries,3),              k:'Libraries',  c:'var(--c-accent)' },
                  { v: pad(stats.images,5),                 k:'Frames' },
                  { v: pad(stats.bursts,4),                 k:'Bursts' },
                  { v: pad(stats.by_verdict?.keeper||0,4),  k:'Keepers', c:'var(--c-keeper)' },
                  { v: pad(stats.by_verdict?.review||0,4),  k:'Reviews', c:'var(--c-amber)' },
                  { v: pad(stats.by_verdict?.reject||0,4),  k:'Rejects',  c:'var(--c-danger)' },
                ].map(({ v, k, c }) => (
                  <div key={k} className="sg-stat">
                    <div className="sg-stat-v" style={{ color: c || 'var(--c-text)' }}>{v}</div>
                    <div className="sg-stat-k">{k}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}


        {/* Add another roll — secondary action, below the data. */}
        <div className="sg-card">
          <h2 className="sg-card-h2">Add another <em>roll</em>.</h2>
          <div className="sg-card-sub">Ingest · scan · measure · catalogue · multiple folders run in sequence</div>
          {folders.length > 0 && (
            <div style={{ display:'flex', flexDirection:'column', gap:6, marginBottom:10 }}>
              {folders.map(f => (
                <div key={f} className="sg-folder-display" style={{ display:'flex', alignItems:'center', gap:8, color:'var(--c-text)', fontStyle:'normal' }}>
                  <span style={{ flex:1, wordBreak:'break-all' }}>{f}</span>
                  <button
                    onClick={() => setFolders(prev => prev.filter(p => p !== f))}
                    title="Remove from queue"
                    style={{ background:'none', border:'none', cursor:'pointer', color:'var(--c-mute)', fontSize:14, lineHeight:1, padding:'0 2px' }}>×</button>
                </div>
              ))}
            </div>
          )}
          <div style={{ display:'flex', gap:10, alignItems:'stretch' }}>
            <div className="sg-folder-display" style={{ flex:1, color:'var(--c-mute)', fontStyle:'italic' }}>
              {folders.length ? `${folders.length} folder${folders.length === 1 ? '' : 's'} queued` : 'no folder selected'}
            </div>
            <Btn variant="ghost" onClick={pickFolder}>Choose folder…</Btn>
            <Btn variant="ghost" onClick={pickPhotosLibrary}>Open Photos Library</Btn>
            <Btn variant="primary" disabled={!folders.length} onClick={develop}>Develop</Btn>
          </div>
          <div className="sg-model-checklist">
            <div className="sg-model-label">Optional models · weights in ~/.snapgrade/models/</div>
            {allModelRows.map(m => {
              const k    = m.name;
              const info = MODEL_INFO[k] || { label: k, note: m.filename || k, download: !!m.download_url };
              const available = !info.download || m.available;
              const dlState   = downloadMsg[k];
              return (
                <div key={k} style={{ display:'flex', alignItems:'center', gap:10, padding:'5px 0', borderBottom:'1px solid var(--c-border2)' }}>
                  <input
                    type="checkbox"
                    checked={!!enabled[k]}
                    onChange={e => handleModelToggle(k, e.target.checked)}
                    style={{ accentColor:'var(--c-accent)', flexShrink:0 }}
                  />
                  <label
                    style={{ flex:1, fontSize:12, color:'var(--c-text)', cursor:'pointer', lineHeight:1.4 }}
                    onClick={() => handleModelToggle(k, !enabled[k])}
                  >
                    <span style={{ fontWeight:600 }}>{info.label}</span>
                    <span style={{ fontSize:10, color:'var(--c-mute)', marginLeft:8 }}>— {info.note}</span>
                  </label>
                  {!info.download ? (
                    <span style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-keeper)', padding:'2px 6px', border:'1px solid var(--c-keeper)', borderRadius:'var(--radius)', flexShrink:0 }}>built-in</span>
                  ) : available || dlState === 'done' ? (
                    <span style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-keeper)', padding:'2px 6px', border:'1px solid var(--c-keeper)', borderRadius:'var(--radius)', flexShrink:0 }}>✓ cached</span>
                  ) : dlState === 'downloading' ? (
                    <span style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-amber)', padding:'2px 6px', flexShrink:0 }}>↓ loading…</span>
                  ) : dlState === 'error' ? (
                    <span style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-danger)', padding:'2px 6px', flexShrink:0 }}>failed</span>
                  ) : (
                    <span style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', padding:'2px 6px', flexShrink:0 }}>↓ not cached</span>
                  )}
                  {info.download && (
                    <Btn
                      variant="ghost"
                      disabled={dlState === 'downloading' || available || dlState === 'done'}
                      style={{ fontSize:9, padding:'3px 10px', flexShrink:0 }}
                      onClick={() => downloadModel(k)}
                    >
                      {dlState === 'downloading' ? '↓…' : dlState === 'error' ? 'Retry' : 'Download'}
                    </Btn>
                  )}
                </div>
              );
            })}
          </div>
          <div className="sg-model-checklist" style={{ marginTop:10 }}>
            <div className="sg-model-label">After ingest · chained automatically</div>
            <label style={{ display:'flex', alignItems:'center', gap:10, fontSize:12, color:'var(--c-text)', cursor:'pointer', padding:'3px 0' }}>
              <input type="checkbox" checked={postSteps.group} onChange={e => setPostSteps(s => ({ ...s, group: e.target.checked }))} style={{ accentColor:'var(--c-accent)' }} />
              <span>Group bursts</span>
              <span style={{ fontSize:10, color:'var(--c-mute)' }}>— pHash + time-window grouping (fast)</span>
            </label>
            <label style={{ display:'flex', alignItems:'center', gap:10, fontSize:12, color:'var(--c-text)', cursor:'pointer', padding:'3px 0' }}>
              <input type="checkbox" checked={postSteps.faces} onChange={e => setPostSteps(s => ({ ...s, faces: e.target.checked }))} style={{ accentColor:'var(--c-accent)' }} />
              <span>Cluster faces</span>
              <span style={{ fontSize:10, color:'var(--c-mute)' }}>— InsightFace detect + greedy cluster (slow on large libraries)</span>
            </label>
          </div>
          {msg && <div className="sg-toast">{msg}</div>}
        </div>
      </div>
      <ConfirmModal
        open={!!confirmRemove}
        title="Remove library?"
        danger
        confirmLabel="Remove"
        onConfirm={() => removeLib(confirmRemove.id)}
        onCancel={() => setConfirmRemove(null)}
        body={confirmRemove && <>Remove <b style={{ color:'var(--c-text)' }}>{confirmRemove.name}</b> from the catalogue? The analysis records are dropped, but the photos on disk stay put.</>}
      />

      {activeErrorLib && (
        <div className="sg-modal-backdrop" style={{ display:'flex', position:'fixed', inset:0, zIndex:1000, background:'rgba(0,0,0,0.6)', alignItems:'center', justifyContent:'center' }}>
          <div className="sg-modal" style={{ background:'var(--c-bg)', border:'1px solid var(--c-border)', padding:24, width:640, maxWidth:'90%', maxHeight:'80%', display:'flex', flexDirection:'column', borderRadius:'var(--radius)' }}>
            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
              <h3 style={{ margin:0, fontSize:16, fontWeight:600, color:'var(--c-text)' }}>
                Ingestion Errors — {activeErrorLib.name}
              </h3>
              <button onClick={() => setActiveErrorLib(null)} style={{ background:'none', border:'none', cursor:'pointer', color:'var(--c-mute)', fontSize:18 }}>×</button>
            </div>
            <div style={{ flex:1, overflowY:'auto', fontSize:12, display:'flex', flexDirection:'column', gap:10, paddingRight:6 }} className="sg-scroll">
              {errorLoading ? (
                <EmptyState>Loading error list…</EmptyState>
              ) : errorList.length === 0 ? (
                <EmptyState>No errors recorded for this library.</EmptyState>
              ) : (
                errorList.map((err, i) => (
                  <div key={i} style={{ padding:'10px 14px', border:'1px solid var(--c-border2)', borderRadius:'var(--radius)', background:'var(--c-panel)' }}>
                    <div style={{ fontWeight:600, color:'var(--c-text)', wordBreak:'break-all', marginBottom:4 }}>
                      {err.path}
                    </div>
                    <div style={{ color:'var(--c-danger)', fontFamily:'var(--font-mono)', fontSize:11, whiteSpace:'pre-wrap' }}>
                      {err.error}
                    </div>
                  </div>
                ))
              )}
            </div>
            <div style={{ display:'flex', justifyContent:'flex-end', marginTop:16 }}>
              <Btn variant="ghost" onClick={() => setActiveErrorLib(null)}>Close</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Bursts Screen ─────────────────────────────────────────────────────────────
function BurstsScreen() {
  const { MOCK_BURSTS, MOCK_LIBRARIES } = window.SG_DATA;
  const [activeLib, setActiveLib] = useState(null);
  // Seed from persisted is_best so a reload reflects prior picks.
  const [picked, setPicked]       = useState(() => {
    const seed = {};
    for (const b of MOCK_BURSTS) {
      const best = b.images.find(i => i.is_best);
      if (best) seed[b.burst_id] = best.id;
    }
    return seed;
  });
  const [pickMsg, setPickMsg]     = useState('');
  const [compareMode, setCompareMode] = useState('grid');  // grid | 2 | 3
  // Shared (synced) zoom/pan across all compare panes.
  const [cmpScale, setCmpScale] = useState(1);
  const [cmpOff, setCmpOff]     = useState({ x: 0, y: 0 });
  const cmpDrag = useRef(null);

  const libCounts = useMemo(() => {
    const counts = { all: MOCK_BURSTS.length };
    MOCK_LIBRARIES.forEach(lib => { counts[lib.id] = MOCK_BURSTS.filter(b => b.images.some(img => img.library_id === lib.id)).length; });
    return counts;
  }, [MOCK_BURSTS, MOCK_LIBRARIES]);

  const visibleBursts = useMemo(() => {
    if (activeLib === null) return MOCK_BURSTS;
    return MOCK_BURSTS.filter(b => b.images.some(img => img.library_id === activeLib));
  }, [MOCK_BURSTS, activeLib]);

  const [selectedBurst, setSelectedBurst] = useState(visibleBursts[0]?.burst_id ?? null);
  useEffect(() => { setSelectedBurst(visibleBursts[0]?.burst_id ?? null); }, [activeLib]);

  const burst = visibleBursts.find(b => b.burst_id === selectedBurst);
  const burstImages = useMemo(() => {
    if (!burst) return [];
    if (activeLib === null) return burst.images;
    return burst.images.filter(img => img.library_id === activeLib);
  }, [burst, activeLib]);

  const [grouping, setGrouping] = useState(false);
  const [groupMsg, setGroupMsg] = useState('');
  async function regroup() {
    setGrouping(true); setGroupMsg('');
    try {
      const r = await window.SG_API.regroup({ hamming: 10, seconds: 3 });
      setGroupMsg(`grouped → ${r.bursts ?? 0} bursts`);
      // Refetch + remount in place (keeps scroll / active library) instead of reloading.
      await window.SG_REFRESH?.();
    } catch (e) { setGroupMsg(`regroup failed: ${e.message}`); }
    finally { setGrouping(false); }
  }

  // Persist the pick to the backend; optimistic locally, revert on failure.
  async function pickBest(bid, img) {
    const prev = picked[bid];
    setPicked(p => ({ ...p, [bid]: img.id }));
    setPickMsg('');
    try {
      await window.SG_API.setBurstBest(bid, img.id);
      // Keep in-memory is_best consistent so other views agree without a reload.
      if (burst) burst.images.forEach(i => { i.is_best = i.id === img.id; });
    } catch (e) {
      setPicked(p => ({ ...p, [bid]: prev }));
      setPickMsg(`could not save pick: ${e.message}`);
    }
  }

  // Reset synced zoom when the burst or compare mode changes.
  useEffect(() => { setCmpScale(1); setCmpOff({ x: 0, y: 0 }); }, [selectedBurst, compareMode]);
  function cmpWheel(e) {
    if (compareMode === 'grid') return;
    e.preventDefault();
    setCmpScale(s => Math.max(1, Math.min(8, s * (e.deltaY < 0 ? 1.15 : 1 / 1.15))));
  }
  function cmpDown(e) {
    if (compareMode === 'grid' || cmpScale <= 1) return;
    cmpDrag.current = { x: e.clientX, y: e.clientY, ox: cmpOff.x, oy: cmpOff.y };
  }
  function cmpMove(e) {
    if (!cmpDrag.current) return;
    setCmpOff({ x: cmpDrag.current.ox + (e.clientX - cmpDrag.current.x),
                y: cmpDrag.current.oy + (e.clientY - cmpDrag.current.y) });
  }
  function cmpUp() { cmpDrag.current = null; }

  const isCompare = compareMode !== 'grid';
  const gridCols = compareMode === '2' ? 'repeat(2, 1fr)'
                 : compareMode === '3' ? 'repeat(3, 1fr)'
                 : 'repeat(auto-fill, minmax(260px, 1fr))';
  const imgH = compareMode === '2' ? 400 : compareMode === '3' ? 300 : 180;

  return (
    <div style={{ display:'flex', flex:1, minHeight:0, overflow:'hidden', flexDirection:'column' }}>
      <LibraryFilterBar activeLib={activeLib} setActiveLib={setActiveLib} counts={libCounts} />
      <div style={{ display:'flex', gap:10, alignItems:'center', padding:'8px 20px', borderBottom:'1px solid var(--c-border)', background:'var(--c-bg)', flexShrink:0 }}>
        <span style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-mute)' }}>
          Bursts grouped by pHash hamming · time window
        </span>
        <div style={{ flex:1 }} />
        {groupMsg && <span className="sg-toast" style={{ marginTop:0 }}>{groupMsg}</span>}
        <Btn variant="primary" disabled={grouping} onClick={regroup}>{grouping ? 'Regrouping…' : 'Regroup'}</Btn>
      </div>
      <div style={{ display:'flex', flex:1, minHeight:0, overflow:'hidden' }}>
        <div className="sg-lib-rail" style={{ width:190 }}>
          <div className="sg-lib-rail-head">Burst groups · {visibleBursts.length}</div>
          {visibleBursts.length === 0 ? (
            <div style={{ padding:'18px', fontSize:10, color:'var(--c-mute)', fontStyle:'italic' }}>No bursts in this folder</div>
          ) : visibleBursts.map(b => {
            const libImgs = activeLib === null ? b.images : b.images.filter(img => img.library_id === activeLib);
            return (
              <button key={b.burst_id} className={`sg-lib-node ${selectedBurst === b.burst_id ? 'on' : ''}`} onClick={() => setSelectedBurst(b.burst_id)}>
                <span className="sg-lib-node-name">Burst #{b.burst_id}</span>
                <span className="sg-lib-node-meta">{libImgs.length} frame{libImgs.length !== 1 ? 's' : ''}{picked[b.burst_id] ? ' · ✓ picked' : ''}</span>
              </button>
            );
          })}
        </div>
        <div className="sg-scroll" style={{ flex:1, padding:'24px 28px' }}>
          {burst && burstImages.length > 0 ? (
            <>
              <div style={{ display:'flex', alignItems:'center', gap:16, marginBottom:20, flexWrap:'wrap' }}>
                <h2 style={{ fontSize:20, fontWeight:600, letterSpacing:'-0.01em', margin:0 }}>
                  Burst <em style={{ color:'var(--c-accent)', fontStyle:'normal' }}>#{burst.burst_id}</em>
                </h2>
                <span style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-mute)' }}>
                  {burstImages.length} frames · compare &amp; pick sharpest
                </span>
                <div style={{ flex:1 }} />
                {/* Compare layout — grid for many frames, 2-up/3-up for close looks
                    with synced zoom (wheel) + pan (drag). */}
                <div style={{ display:'flex', gap:6, alignItems:'center' }}>
                  {[['grid','⊞ Grid'],['2','2-up'],['3','3-up']].map(([m,l]) => (
                    <Chip key={m} on={compareMode===m} onClick={() => setCompareMode(m)}>{l}</Chip>
                  ))}
                  {isCompare && (
                    <span style={{ fontSize:10, letterSpacing:'0.16em', textTransform:'uppercase', color:'var(--c-mute)', fontVariantNumeric:'tabular-nums' }}>
                      {Math.round(cmpScale*100)}% · wheel zoom
                    </span>
                  )}
                </div>
              </div>
              {pickMsg && <div className="sg-toast" style={{ marginTop:0, marginBottom:12, color:'var(--c-danger)' }}>{pickMsg}</div>}
              <div style={{ display:'grid', gridTemplateColumns:gridCols, gap:16 }}>
                {burstImages.map(img => {
                  const isBest = picked[burst.burst_id] === img.id || (!picked[burst.burst_id] && img.is_best);
                  return (
                    <div key={img.id} style={{ outline: isBest ? '2px solid var(--c-accent)' : '1px solid var(--c-border)', outlineOffset:-1, borderRadius:'var(--radius)', overflow:'hidden', background:'var(--c-panel)', position:'relative' }}>
                      {isBest && (
                        <div style={{ position:'absolute', top:10, left:10, background:'var(--c-accent)', color:'var(--c-bg)', fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', padding:'3px 8px', zIndex:3 }}>Best pick</div>
                      )}
                      <div
                        onWheel={cmpWheel} onMouseDown={cmpDown} onMouseMove={cmpMove}
                        onMouseUp={cmpUp} onMouseLeave={cmpUp}
                        style={{ height:imgH, overflow:'hidden', background:'#000',
                                 cursor: isCompare ? (cmpScale>1 ? 'grab' : 'zoom-in') : 'default' }}>
                        <img src={isCompare ? img.preview : img.thumb} alt=""
                          onError={e => { if (e.currentTarget.src !== img.thumb) e.currentTarget.src = img.thumb; }}
                          style={{ width:'100%', height:'100%',
                                   objectFit: isCompare ? 'contain' : 'cover', display:'block',
                                   position:'relative', zIndex:1,
                                   transform: isCompare ? `translate(${cmpOff.x}px, ${cmpOff.y}px) scale(${cmpScale})` : 'none',
                                   transformOrigin:'center center',
                                   transition: cmpDrag.current ? 'none' : 'transform .12s ease-out' }} />
                      </div>
                      <div style={{ padding:'12px 14px' }}>
                        <div style={{ display:'flex', justifyContent:'flex-end', alignItems:'center', marginBottom:8 }}>
                          <span style={{ fontSize:10, letterSpacing: '0.12em', textTransform:'uppercase', color: verdictColor(img.verdict) }}>{img.verdict}</span>
                        </div>
                        <div style={{ marginBottom:10 }}>
                          <div style={{ display:'flex', justifyContent:'space-between', fontSize:10, letterSpacing:'0.16em', textTransform:'uppercase', color:'var(--c-mute)', marginBottom:4 }}>
                            <span>Sharpness</span>
                            <span style={{ color: img.sharpness > 0.55 ? 'var(--c-keeper)' : img.sharpness > 0.3 ? 'var(--c-amber)' : 'var(--c-danger)' }}>{Math.round(img.sharpness * 100)}%</span>
                          </div>
                          <div style={{ height:4, background:'var(--c-border)', borderRadius:2 }}>
                            <div style={{ height:'100%', width:`${img.sharpness * 100}%`, background: img.sharpness > 0.55 ? 'var(--c-keeper)' : img.sharpness > 0.3 ? 'var(--c-amber)' : 'var(--c-danger)', borderRadius:2, transition:'width .3s' }} />
                          </div>
                        </div>
                        {/* Aesthetic score (new) */}
                        {img.aesthetic_score != null && (
                          <div style={{ marginBottom:10 }}>
                            <div style={{ display:'flex', justifyContent:'space-between', fontSize:10, letterSpacing:'0.16em', textTransform:'uppercase', color:'var(--c-mute)', marginBottom:4 }}>
                              <span>Aesthetic</span>
                              <span style={{ color:'var(--c-text2)' }}>{Math.round(img.aesthetic_score * 100)}%</span>
                            </div>
                            <div style={{ height:4, background:'var(--c-border)', borderRadius:2 }}>
                              <div style={{ height:'100%', width:`${img.aesthetic_score * 100}%`, background:'var(--c-text2)', borderRadius:2 }} />
                            </div>
                          </div>
                        )}
                        <div style={{ display:'flex', justifyContent:'space-between', fontSize:10, color:'var(--c-mute)', marginBottom:10 }}>
                          <span>f/{img.f_number}</span><span>{img.exposure_time}</span><span>ISO {img.iso}</span>
                        </div>
                        <button onClick={() => pickBest(burst.burst_id, img)} style={{ width:'100%', padding:'8px', fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', border:`1px solid ${isBest ? 'var(--c-accent)' : 'var(--c-border2)'}`, color: isBest ? 'var(--c-accent)' : 'var(--c-mute)', background: isBest ? 'rgba(193,68,14,0.08)' : 'transparent', cursor:'pointer', borderRadius:'var(--radius)', fontFamily:'var(--font-ui)' }}>
                          {isBest ? '✓ Picked' : 'Pick this'}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100%', color:'var(--c-mute)', fontSize:14 }}>
              {visibleBursts.length === 0 ? 'No bursts in this folder' : 'Select a burst to compare'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Face Clusters Screen ──────────────────────────────────────────────────────
// Inline rename of a cluster's label (click the name).
function ClusterName({ cluster, onRename, big }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(cluster.label);
  useEffect(() => { setVal(cluster.label); }, [cluster.label]);
  const commit = () => { setEditing(false); if (val.trim() && val !== cluster.label) onRename(cluster.id, val.trim()); };
  if (editing) return (
    <input autoFocus value={val}
      onChange={e => setVal(e.target.value)}
      onClick={e => e.stopPropagation()}
      onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setVal(cluster.label); setEditing(false); } }}
      onBlur={commit}
      style={{ fontWeight:600, fontSize: big ? 19 : 14,
               color:'var(--c-text)', background:'var(--c-bg)', border:'1px solid var(--c-accent)',
               borderRadius:'var(--radius)', padding:'2px 8px', width:'100%', boxSizing:'border-box' }} />
  );
  return (
    <span onClick={e => { e.stopPropagation(); setEditing(true); }}
      title="Click to rename"
      style={{ fontWeight:600, fontSize: big ? 19 : 14,
               color: cluster.named ? 'var(--c-text)' : 'var(--c-text2)', cursor:'text',
               borderBottom: '1px dashed transparent' }}
      onMouseOver={e => e.currentTarget.style.borderBottomColor = 'var(--c-border2)'}
      onMouseOut={e => e.currentTarget.style.borderBottomColor = 'transparent'}>
      {cluster.label}{!cluster.named && <span style={{ fontSize: big ? 13 : 10, color:'var(--c-mute)', marginLeft:6, fontStyle:'normal' }}>✎</span>}
    </span>
  );
}

function FacesScreen() {
  const { MOCK_LIBRARIES } = window.SG_DATA;
  const [activeLib, setActiveLib] = useState(null);
  const [expanded, setExpanded]   = useState(null);
  const [clusters, setClusters]   = useState([]);
  const [loading, setLoading]     = useState(true);
  const [running, setRunning]     = useState(false);
  const [runMsg, setRunMsg]       = useState('');
  const [threshold, setThreshold] = useState(window.SG_PREFS?.faceThreshold ?? 0.30);
  const [sortMode, setSortMode]   = useState('size_desc');  // size_desc | size_asc
  const [mergeSel, setMergeSel]   = useState(null);  // {id,label} target awaiting a source
  const [preview, setPreview]     = useState(null);  // {faces,clusters} at the slider's threshold
  const [curateMsg, setCurateMsg] = useState('');
  const [confirmRecluster, setConfirmRecluster] = useState(false);
  const runThreshold = useRef(threshold);            // threshold the current clusters were built at
  useEffect(() => { setExpanded(null); setMergeSel(null); }, [activeLib]);

  const reload = useCallback(async () => {
    setLoading(true);
    try { setClusters(await window.SG_API.loadClusters()); }
    catch (e) { console.error('loadClusters failed:', e); setClusters([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  // Debounced "≈N clusters at this threshold" preview (no writes).
  useEffect(() => {
    if (Math.abs(threshold - runThreshold.current) < 0.005) { setPreview(null); return; }
    let alive = true;
    const id = setTimeout(async () => {
      try { const p = await window.SG_API.previewClusters(threshold); if (alive) setPreview(p); }
      catch { if (alive) setPreview(null); }
    }, 350);
    return () => { alive = false; clearTimeout(id); };
  }, [threshold]);

  const rename = useCallback(async (cid, label) => {
    setCurateMsg('');
    try {
      await window.SG_API.labelCluster(cid, label);
      setClusters(cs => cs.map(c => c.id === cid ? { ...c, label, named: true } : c));
    } catch (e) { setCurateMsg(`rename failed: ${e.message}`); }
  }, []);

  const doMerge = useCallback(async (into, from) => {
    setCurateMsg('');
    try {
      await window.SG_API.mergeClusters(into, from);
      setMergeSel(null);
      await reload();
    } catch (e) { setCurateMsg(`merge failed: ${e.message}`); }
  }, [reload]);

  const removeFace = useCallback(async (cid, faceId) => {
    setCurateMsg('');
    setClusters(cs => cs.map(c => c.id === cid
      ? { ...c, thumbs: c.thumbs.filter(t => t.face_id !== faceId), count: Math.max(0, c.count - 1) } : c));
    try { await window.SG_API.removeFace(faceId); }
    catch (e) { setCurateMsg(`remove failed: ${e.message}`); reload(); }
  }, [reload]);

  // Poll /api/stats.faces while a run is in flight; reload clusters on finish.
  useEffect(() => {
    if (!running) return;
    let alive = true;
    const id = setInterval(async () => {
      const s = await window.SG_API.refreshStats();
      if (!alive || !s) return;
      const f = s.faces || {};
      if (!f.running) {
        clearInterval(id);
        setRunning(false);
        setRunMsg(f.error ? `failed: ${f.error}` : `clustered ${f.clusters} groups · ${f.detected} new faces`);
        reload();
      }
    }, 1500);
    return () => { alive = false; clearInterval(id); };
  }, [running, reload]);

  const namedCount = useMemo(() => clusters.filter(c => c.named).length, [clusters]);

  async function runClustering() {
    setConfirmRecluster(false);
    setRunMsg(''); setRunning(true); setPreview(null);
    runThreshold.current = threshold;
    try {
      window.SG_API.savePrefs?.({ faceThreshold: threshold });
      await window.SG_API.runFaces({ threshold });
    }
    catch (e) { setRunning(false); setRunMsg(`launch failed: ${e.message}`); }
  }

  const visibleClusters = useMemo(() => {
    // /api/faces/clusters doesn't expose per-library mapping yet — show all.
    const arr = [...clusters];
    arr.sort((a, b) => sortMode === 'size_asc' ? a.count - b.count : b.count - a.count);
    return arr;
  }, [clusters, sortMode]);

  const libCounts = useMemo(() => {
    const counts = { all: visibleClusters.length };
    MOCK_LIBRARIES.forEach(lib => { counts[lib.id] = visibleClusters.length; });
    return counts;
  }, [visibleClusters, MOCK_LIBRARIES]);

  const cluster = expanded !== null ? visibleClusters.find(c => c.id === expanded) : null;

  return (
    <div style={{ display:'flex', flex:1, minHeight:0, flexDirection:'column', overflow:'hidden' }}>
      <LibraryFilterBar activeLib={activeLib} setActiveLib={setActiveLib} counts={libCounts} />
      <div style={{ display:'flex', gap:14, alignItems:'center', padding:'8px 20px', borderBottom:'1px solid var(--c-border)', background:'var(--c-bg)', flexShrink:0, flexWrap:'wrap' }}>
        <span style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-mute)' }}>
          {clusters.length} cluster{clusters.length === 1 ? '' : 's'} · InsightFace + greedy/HNSW
        </span>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-mute)' }}>Sort</span>
          <button
            onClick={() => setSortMode(s => s === 'size_desc' ? 'size_asc' : 'size_desc')}
            style={{ fontSize:10, letterSpacing:'.18em', textTransform:'uppercase', padding:'4px 10px', border:'1px solid var(--c-border)', background:'var(--c-panel)', color:'var(--c-text)', cursor:'pointer', borderRadius:'var(--radius)', fontFamily:'var(--font-ui)' }}
            title="Toggle cluster sort order"
          >
            size {sortMode === 'size_desc' ? '↓' : '↑'}
          </button>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-mute)' }}>Threshold</span>
          <input type="range" min={0.15} max={0.55} step={0.01} value={threshold}
            onChange={e => setThreshold(parseFloat(e.target.value))}
            disabled={running}
            style={{ width:140, accentColor:'var(--c-accent)' }}
            title="Cosine similarity threshold for clustering (lower = lumpier)" />
          <span style={{ fontFamily:'var(--font-ui)', fontSize:14, color:'var(--c-accent)', minWidth:36, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{threshold.toFixed(2)}</span>
          {preview && (
            <span style={{ fontSize:10, letterSpacing:'.16em', textTransform:'uppercase', color:'var(--c-text2)', fontVariantNumeric:'tabular-nums' }}>
              ≈{preview.clusters} clusters
            </span>
          )}
        </div>
        <div style={{ flex:1 }} />
        {curateMsg && <span className="sg-toast" style={{ marginTop:0, color:'var(--c-danger)' }}>{curateMsg}</span>}
        {runMsg && <span className="sg-toast" style={{ marginTop:0 }}>{runMsg}</span>}
        <Btn variant="primary" disabled={running} onClick={() => setConfirmRecluster(true)}>
          {running ? 'Clustering…' : 'Recluster'}
        </Btn>
      </div>
      <ConfirmModal
        open={confirmRecluster}
        title="Recluster all faces?"
        danger
        confirmLabel="Recluster"
        onConfirm={runClustering}
        onCancel={() => setConfirmRecluster(false)}
        body={
          <>
            Reclustering rebuilds every group from scratch at the new threshold.
            {namedCount > 0
              ? <> Your <b style={{ color:'var(--c-text)' }}>{namedCount} named cluster{namedCount === 1 ? '' : 's'}</b> are re-anchored to the closest matching new group by face similarity, so names usually carry over — but a name is dropped if that person no longer forms a confident cluster. Manual merges/removals are not preserved.</>
              : <> No clusters are named yet, so nothing labelled is at risk.</>}
          </>
        }
      />
      <div className="sg-scroll">
        <div className="sg-page">
          <p className="sg-lede">Faces grouped by similarity across the library. Identify recurring subjects and curate by person.</p>
          {!cluster ? (
            <>
              {mergeSel && (
                <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:16, padding:'10px 14px',
                              border:'1px solid var(--c-accent)', borderRadius:'var(--radius)', background:'rgba(193,68,14,0.06)' }}>
                  <span style={{ fontSize:11, color:'var(--c-text2)' }}>
                    Merging into <b style={{ color:'var(--c-accent)' }}>{mergeSel.label}</b> — pick the cluster to fold in.
                  </span>
                  <button onClick={() => setMergeSel(null)}
                    style={{ fontSize:10, letterSpacing:'0.16em', textTransform:'uppercase', color:'var(--c-danger)', background:'none', border:'none', cursor:'pointer', fontFamily:'var(--font-ui)' }}>cancel ×</button>
                </div>
              )}
              {loading ? (
                <EmptyState>Loading clusters…</EmptyState>
              ) : visibleClusters.length === 0 ? (
                <EmptyState>No face clusters yet — press "Recluster".</EmptyState>
              ) : (
                <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(200px, 1fr))', gap:16, marginBottom:32 }}>
                  {visibleClusters.map(c => {
                    const pool = c.thumbs || [];
                    // Static 2×2 collage of the cluster's representative faces — a
                    // glanceable identity card (the prior 3.5s rotation fought
                    // side-by-side comparison).
                    const shown = pool.slice(0, 4);
                    const isMergeTarget = mergeSel && mergeSel.id === c.id;
                    return (
                    <div key={c.id} onClick={() => { if (mergeSel && mergeSel.id !== c.id) doMerge(mergeSel.id, c.id); else setExpanded(c.id); }}
                      style={{ border:`1px solid ${isMergeTarget ? 'var(--c-accent)' : 'var(--c-border)'}`, background:'var(--c-panel)', padding:0, cursor:'pointer', borderRadius:'var(--radius)', overflow:'hidden', transition:'border-color .15s, transform .15s', textAlign:'left' }}
                      onMouseOver={e => { e.currentTarget.style.borderColor='var(--c-text2)'; e.currentTarget.style.transform='translateY(-2px)'; }}
                      onMouseOut={e  => { e.currentTarget.style.borderColor= isMergeTarget ? 'var(--c-accent)' : 'var(--c-border)';  e.currentTarget.style.transform='none'; }}
                    >
                      <div style={{ position:'relative', height:160, background:'var(--c-border)', overflow:'hidden' }}>
                        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gridTemplateRows:'1fr 1fr', gap:1, height:'100%' }}>
                          {shown.map((t, i) => (
                            <img key={`${t ? t.id : 'x'}-${i}`} src={t ? t.url : ''} alt="" style={{ width:'100%', height:'100%', objectFit:'cover', display:'block', position:'relative', zIndex:1, minWidth:0, minHeight:0, transition:'opacity .4s' }} />
                          ))}
                        </div>
                        <div style={{ position:'absolute', top:8, left:8, padding:'3px 8px', background:'rgba(0,0,0,0.65)', color:'var(--c-accent)', fontFamily:'var(--font-ui)', fontSize:12, lineHeight:1, borderRadius:'var(--radius)', backdropFilter:'blur(2px)', fontVariantNumeric:'tabular-nums' }}>
                          {c.count}
                        </div>
                      </div>
                      <div style={{ padding:'12px 14px' }}>
                        <div style={{ marginBottom:4 }}><ClusterName cluster={c} onRename={rename} /></div>
                        <div style={{ fontSize:10, color:'var(--c-mute)', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                          <span style={{ fontVariantNumeric:'tabular-nums' }}>{c.count} appearances</span>
                          <button onClick={e => { e.stopPropagation(); setMergeSel(mergeSel && mergeSel.id === c.id ? null : { id: c.id, label: c.label }); }}
                            style={{ fontSize:10, letterSpacing:'0.14em', textTransform:'uppercase', color: isMergeTarget ? 'var(--c-accent)' : 'var(--c-mute)', background:'none', border:'none', cursor:'pointer', fontFamily:'var(--font-ui)' }}>
                            {isMergeTarget ? 'target ✓' : '⇆ merge'}
                          </button>
                        </div>
                      </div>
                    </div>
                  );})}
                </div>
              )}
            </>
          ) : (
            <>
              <button onClick={() => setExpanded(null)} style={{ fontSize:10, letterSpacing: '0.12em', textTransform:'uppercase', color:'var(--c-mute)', background:'none', border:'none', cursor:'pointer', marginBottom:20, display:'flex', alignItems:'center', gap:8, fontFamily:'var(--font-ui)' }}>‹ Back to clusters</button>
              <div style={{ display:'flex', alignItems:'center', gap:16, marginBottom:24 }}>
                <img src={cluster.rep_thumb} alt="" style={{ width:60, height:60, objectFit:'cover', borderRadius:'50%', border:'2px solid var(--c-border2)' }} />
                <div>
                  <div style={{ marginBottom:4 }}><ClusterName cluster={cluster} onRename={rename} big /></div>
                  <div style={{ fontSize:10, color:'var(--c-mute)', letterSpacing:'0.18em', textTransform:'uppercase', fontVariantNumeric:'tabular-nums' }}>{cluster.count} appearances across library · click the name to rename</div>
                </div>
              </div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(180px, 1fr))', gap:10 }}>
                {cluster.thumbs.map(t => (
                  <div key={t.id} style={{ border:'1px solid var(--c-border)', borderRadius:'var(--radius)', overflow:'hidden', background:'var(--c-panel)', position:'relative' }}>
                    <img src={t.url} alt="" style={{ width:'100%', height:130, objectFit:'cover', display:'block', position:'relative', zIndex:1 }} />
                    <button onClick={() => removeFace(cluster.id, t.face_id)}
                      title="Not this person — remove from cluster"
                      style={{ position:'absolute', top:6, right:6, zIndex:2, width:22, height:22, borderRadius:'50%',
                               background:'rgba(10,9,7,0.75)', color:'var(--c-danger)', border:'1px solid var(--c-danger)',
                               cursor:'pointer', fontSize:12, lineHeight:1, display:'flex', alignItems:'center', justifyContent:'center' }}>✕</button>
                    <div style={{ padding:'8px 10px', fontSize:10, color:'var(--c-mute)', letterSpacing:'0.18em', textTransform:'uppercase', display:'flex', justifyContent:'flex-end' }}>
                      <a href={`/api/images/${t.image_id}/preview`} target="_blank" rel="noreferrer"
                         onClick={e => e.stopPropagation()} style={{ color:'var(--c-accent)' }}>open ↗</a>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Batch XMP Export Screen ───────────────────────────────────────────────────
function XMPExportScreen() {
  const { MOCK_IMAGES, MOCK_LIBRARIES } = window.SG_DATA;
  const [activeLib, setActiveLib]         = useState(null);
  const [verdictFilter, setVerdictFilter] = useState('keeper');
  const [selected, setSelected]           = useState(new Set());
  const [progress, setProgress]           = useState(null);
  const [done, setDone]                   = useState(new Set());

  const libCounts = useMemo(() => {
    const counts = { all: MOCK_IMAGES.length };
    MOCK_LIBRARIES.forEach(lib => { counts[lib.id] = MOCK_IMAGES.filter(i => i.library_id === lib.id).length; });
    return counts;
  }, [MOCK_IMAGES, MOCK_LIBRARIES]);

  const filtered = useMemo(() => MOCK_IMAGES.filter(i =>
    (activeLib === null || i.library_id === activeLib) &&
    (verdictFilter === 'all' || i.verdict === verdictFilter)
  ), [MOCK_IMAGES, activeLib, verdictFilter]);

  useEffect(() => { setSelected(new Set(filtered.map(i => i.id))); }, [filtered]);

  const allChecked = filtered.length > 0 && filtered.every(i => selected.has(i.id));
  const toggleAll  = () => setSelected(allChecked ? new Set() : new Set(filtered.map(i => i.id)));
  const toggleOne  = id => setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  async function runExport() {
    const ids = filtered.filter(i => selected.has(i.id)).map(i => i.id);
    setProgress({ done: 0, total: ids.length });
    let i = 0;
    for (const id of ids) {
      try { await window.SG_API.xmp(id); }
      catch (err) { console.error(`xmp ${id} failed:`, err); }
      i++;
      setProgress({ done: i, total: ids.length });
      setDone(d => new Set([...d, id]));
    }
    setTimeout(() => setProgress(null), 1200);
  }

  const selectedCount = filtered.filter(i => selected.has(i.id)).length;

  return (
    <div style={{ display:'flex', flex:1, minHeight:0, flexDirection:'column', overflow:'hidden' }}>
      <LibraryFilterBar activeLib={activeLib} setActiveLib={id => { setActiveLib(id); setDone(new Set()); }} counts={libCounts} />
      <div style={{ padding:'10px 20px', borderBottom:'1px solid var(--c-border)', background:'var(--c-bg)', display:'flex', gap:8, alignItems:'center', flexWrap:'wrap', flexShrink:0 }}>
        <span style={{ fontWeight:600, fontSize:13, color:'var(--c-text)', marginRight:6 }}>Write XMP sidecars</span>
        <VerdictChips value={verdictFilter} onChange={setVerdictFilter} />
        <div style={{ flex:1 }} />
        <label style={{ fontSize:10, color:'var(--c-text2)', cursor:'pointer', display:'flex', alignItems:'center', gap:8, letterSpacing:'0.16em', textTransform:'uppercase', fontFamily:'var(--font-ui)' }}>
          <input type="checkbox" checked={allChecked} onChange={toggleAll} style={{ accentColor:'var(--c-accent)' }} />
          Select all ({filtered.length})
        </label>
        <Btn variant="primary" disabled={selectedCount === 0 || progress !== null} onClick={runExport}>
          Export{selectedCount > 0 ? ` (${selectedCount})` : ''}
        </Btn>
      </div>
      {progress && (
        <div style={{ padding:'7px 20px', background:'var(--c-panel)', borderBottom:'1px solid var(--c-border)', flexShrink:0 }}>
          <div style={{ display:'flex', justifyContent:'space-between', fontSize:10, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-text2)', marginBottom:5 }}>
            <span>Writing XMP sidecars…</span><span>{progress.done} / {progress.total}</span>
          </div>
          <div style={{ height:3, background:'var(--c-border)', borderRadius:2 }}>
            <div style={{ height:'100%', width:`${100 * progress.done / progress.total}%`, background:'var(--c-accent)', borderRadius:2, transition:'width .1s' }} />
          </div>
        </div>
      )}
      <div className="sg-scroll" style={{ flex:1 }}>
        {filtered.length === 0 ? (
          <EmptyState>No frames match this filter</EmptyState>
        ) : (
          <table style={{ width:'100%', borderCollapse:'collapse' }}>
            <thead>
              <tr style={{ borderBottom:'1px solid var(--c-border)', background:'var(--c-panel2)', position:'sticky', top:0, zIndex:1 }}>
                {['', 'Frame', 'Folder', 'Verdict', 'Stars', 'Type', 'Reasons', 'Camera', 'Status'].map(h => (
                  <th key={h} style={{ padding:'8px 12px', textAlign:'left', fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-mute)', fontWeight:400, fontFamily:'var(--font-ui)', whiteSpace:'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(img => {
                const isSel = selected.has(img.id);
                const isDone = done.has(img.id);
                const lib = MOCK_LIBRARIES.find(l => l.id === img.library_id);
                return (
                  <tr key={img.id} onClick={() => toggleOne(img.id)}
                    style={{ borderBottom:'1px solid var(--c-border)', cursor:'pointer', background: isSel ? 'rgba(193,68,14,0.05)' : 'transparent', transition:'background .1s' }}
                    onMouseOver={e => { if (!isSel) e.currentTarget.style.background='var(--c-panel)'; }}
                    onMouseOut={e  => { if (!isSel) e.currentTarget.style.background='transparent'; }}
                  >
                    <td style={{ padding:'9px 12px' }}><input type="checkbox" checked={isSel} onChange={() => toggleOne(img.id)} style={{ accentColor:'var(--c-accent)' }} onClick={e => e.stopPropagation()} /></td>
                    <td style={{ padding:'9px 12px' }}>
                      <div style={{ display:'flex', alignItems:'center', gap:10 }}>
                        <img src={img.thumb} alt="" style={{ width:40, height:28, objectFit:'cover', borderRadius:'var(--radius)', flexShrink:0 }} />
                      </div>
                    </td>
                    <td style={{ padding:'9px 12px', fontSize:10, color:'var(--c-mute)', whiteSpace:'nowrap', maxWidth:140, overflow:'hidden', textOverflow:'ellipsis' }}>{lib ? (lib.display_name || lib.root_path.split('/').pop()) : '—'}</td>
                    <td style={{ padding:'9px 12px', fontSize:10, letterSpacing:'0.18em', textTransform:'uppercase', color: verdictColor(img.verdict) }}>{img.verdict}</td>
                    <td style={{ padding:'9px 12px', color:'var(--c-amber)', fontSize:12, letterSpacing:'-1px' }}>{'★'.repeat(img.stars||0)}</td>
                    {/* Content type column (new) */}
                    <td style={{ padding:'9px 12px', fontSize:10 }}>
                      {img.content_type && img.content_type !== 'photo' ? (
                        <span style={{ padding:'2px 6px', fontSize:10, letterSpacing:'0.16em', textTransform:'uppercase', background: img.content_type === 'screenshot' ? 'var(--c-amber)' : 'var(--c-accent)', color:'var(--c-bg)', borderRadius:'var(--radius)', fontFamily:'var(--font-ui)' }}>
                          {img.content_type === 'screenshot' ? '🖥' : '📄'} {img.content_type}
                        </span>
                      ) : (
                        <span style={{ color:'var(--c-mute)' }}>photo</span>
                      )}
                    </td>
                    <td style={{ padding:'9px 12px', fontSize:10, color:'var(--c-mute)', maxWidth:180, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{(img.reasons||[]).join(', ') || '—'}</td>
                    <td style={{ padding:'9px 12px', fontSize:10, color:'var(--c-text2)', whiteSpace:'nowrap' }}>{img.camera_model}</td>
                    <td style={{ padding:'9px 12px', fontSize:10, letterSpacing:'0.18em', color: isDone ? 'var(--c-keeper)' : 'var(--c-mute)', whiteSpace:'nowrap' }}>{isDone ? '✓ written' : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Organize Screen ───────────────────────────────────────────────────────────
function OrganizeScreen() {
  const { MOCK_LIBRARIES, ORGANIZE_TOKENS } = window.SG_DATA;
  const [levels, setLevels] = useState(['date:YYYY', 'camera:model', 'quality:verdict']);
  const [mode, setMode]     = useState('symlink');
  const [scopeLib, setScopeLib] = useState('');
  const [dest, setDest]     = useState('');
  const [preview, setPreview]   = useState(null);
  const [status, setStatus] = useState('');

  async function call(apply) {
    setStatus(apply ? 'applying…' : 'building dry-run preview…');
    setPreview(null);
    try {
      const payload = {
        levels,
        mode,
        apply,
        ...(scopeLib ? { library_id: parseInt(scopeLib, 10) } : {}),
        ...(dest ? { root: dest } : { in_place: true, confirm: scopeLib ? (MOCK_LIBRARIES.find(l => String(l.id) === scopeLib)?.display_name || '') : '' }),
      };
      const r = await window.SG_API.organize(payload);
      setPreview(r.preview || []);
      setStatus(`${apply ? 'wrote' : 'planned'} ${r.written ?? r.plan_size} entries${r.conflicts?.length ? ` · ${r.conflicts.length} conflicts` : ''}`);
    } catch (e) { setStatus(`organize failed: ${e.message}`); }
  }
  function buildPreview() { call(false); }

  // Example values for each token — mirrors organize.py _*_token functions
  const EXAMPLE = {
    'date:YYYY':           '2024',
    'date:YYYY-MM':        '2024-06',
    'date:YYYY-MM-DD':     '2024-06-15',
    'date:YYYY/MM':        '2024/06',
    'date:YYYY/MM/DD':     '2024/06/15',
    'camera:make':         'Nikon',
    'camera:model':        'Nikon_D7200',
    'camera:make_model':   'Nikon_D7200',
    'lens:model':          '50mm_f1_8',
    'focal_bucket':        'standard',
    'orientation':         'landscape',
    'iso_bucket':          'iso-low',
    'flash':               'flash-off',
    'quality:verdict':     'keeper',
    'quality:stars':       '5-star',
    'scene':               'wedding',
    'object:class':        'person',
    'content_type':        'photo',
    'palette:temperature': 'warm',
    'palette:saturation':  'vivid',
    'gps:country':         'India',
    'gps:city':            'Mumbai',
    'event':               'event-0001',
  };

  // Group tokens visually
  const TOKEN_GROUPS = [
    { label: 'Date', tokens: ['date:YYYY','date:YYYY-MM','date:YYYY-MM-DD','date:YYYY/MM','date:YYYY/MM/DD'] },
    { label: 'Camera', tokens: ['camera:make','camera:model','camera:make_model','lens:model','focal_bucket','iso_bucket','flash'] },
    { label: 'Quality', tokens: ['quality:verdict','quality:stars','orientation'] },
    { label: 'Content', tokens: ['scene','object:class','content_type'] },
    { label: 'Colour', tokens: ['palette:temperature','palette:saturation'] },
    { label: 'Location', tokens: ['gps:country','gps:city','event'] },
  ];

  return (
    <div className="sg-scroll">
      <div className="sg-page">
        <p className="sg-lede">Compose the shelf. Levels collapse into a tree; preview before anything is written.</p>

        <div className="sg-card">
          <div className="sg-card-no">i.</div>
          <h2 className="sg-card-h2">Scope &amp; <em>destination</em>.</h2>
          <div className="sg-card-sub">Which library · where to write the tree</div>
          <select className="sg-select" value={scopeLib} onChange={e => setScopeLib(e.target.value)}>
            <option value="">All libraries</option>
            {MOCK_LIBRARIES.map(l => <option key={l.id} value={l.id}>{l.display_name} ({l.image_count})</option>)}
          </select>
          <input
            type="text" value={dest}
            onChange={e => setDest(e.target.value)}
            placeholder="Destination root (blank = in-place, requires single library)"
            style={{ marginTop:10, width:'100%', padding:'9px 12px', background:'var(--c-panel2)',
                     border:'1px solid var(--c-border)', color:'var(--c-text)', fontSize:12,
                     fontFamily:'var(--font-ui)', borderRadius:'var(--radius)' }}
          />
        </div>

        <div className="sg-card">
          <div className="sg-card-no">ii.</div>
          <h2 className="sg-card-h2">The <em>hierarchy</em>.</h2>
          <div className="sg-card-sub">Each level becomes a directory · order matters · 23 tokens available</div>
          {levels.map((lv, i) => (
            <div key={i} style={{ display:'grid', gridTemplateColumns:'36px 1fr 36px', gap:10, alignItems:'center', marginBottom:10 }}>
              <span style={{ fontFamily:'var(--font-ui)', fontSize:14, fontWeight:600, color:'var(--c-accent)', textAlign:'center', fontVariantNumeric:'tabular-nums' }}>{i+1}.</span>
              <select className="sg-select" value={lv} onChange={e => { const n=[...levels]; n[i]=e.target.value; setLevels(n); }}>
                {TOKEN_GROUPS.map(g => (
                  <optgroup key={g.label} label={g.label}>
                    {g.tokens.map(t => <option key={t} value={t}>{t}{EXAMPLE[t] ? ` — e.g. "${EXAMPLE[t]}"` : ''}</option>)}
                  </optgroup>
                ))}
              </select>
              <button onClick={() => setLevels(levels.filter((_,j)=>j!==i))} style={{ color:'var(--c-danger)', background:'none', border:'none', cursor:'pointer', fontSize:16 }}>✕</button>
            </div>
          ))}
          <button onClick={() => setLevels([...levels, ORGANIZE_TOKENS[0]])} style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-text2)', background:'none', border:'1px dashed var(--c-border2)', padding:'7px 14px', cursor:'pointer', marginTop:4, borderRadius:'var(--radius)', fontFamily:'var(--font-ui)' }}>+ add level</button>

          {/* Token reference card */}
          <div style={{ marginTop:20, padding:'14px 16px', border:'1px dashed var(--c-border2)', borderRadius:'var(--radius)', background:'var(--c-bg)' }}>
            <div style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-mute)', marginBottom:12 }}>Token reference</div>
            <div style={{ display:'flex', flexWrap:'wrap', gap:16 }}>
              {TOKEN_GROUPS.map(g => (
                <div key={g.label}>
                  <div style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-accent)', marginBottom:6 }}>{g.label}</div>
                  {g.tokens.map(t => (
                    <div key={t} style={{ fontSize:10, color:'var(--c-text2)', marginBottom:3, fontFamily:'var(--font-ui)', display:'flex', gap:8 }}>
                      <code style={{ color:'var(--c-text)', minWidth:160, display:'inline-block' }}>{t}</code>
                      <span style={{ color:'var(--c-mute)' }}>{EXAMPLE[t]}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="sg-card">
          <div className="sg-card-no">iii.</div>
          <h2 className="sg-card-h2">Write the <em>tree</em>.</h2>
          <div className="sg-card-sub">Dry-run first · commit when the preview reads true</div>
          <div style={{ display:'flex', gap:10, alignItems:'center', flexWrap:'wrap', marginBottom:14 }}>
            <select className="sg-select" value={mode} onChange={e => setMode(e.target.value)} style={{ width:'auto', flex:'0 0 auto' }}>
              <option value="symlink">symlink · safe, non-destructive</option>
              <option value="hardlink">hardlink</option>
              <option value="copy">copy</option>
              <option value="move">move · destructive</option>
            </select>
            <div style={{ flex:1 }} />
            <Btn variant="ghost" onClick={buildPreview}>Dry-run preview</Btn>
            <Btn variant="primary" onClick={() => call(true)}>Apply</Btn>
          </div>
          {status && <div className="sg-toast">{status}</div>}
          {preview && preview.length > 0 && (
            <div style={{ border:'1px solid var(--c-border)', background:'var(--c-panel2)', padding:16, borderRadius:'var(--radius)', marginTop:14 }}>
              <div style={{ fontSize:10, letterSpacing: '0.1em', textTransform:'uppercase', color:'var(--c-mute)', marginBottom:10 }}>
                First {preview.length} entries
              </div>
              <pre style={{ margin:0, fontSize:11, color:'var(--c-text2)', lineHeight:1.7, wordBreak:'break-all', whiteSpace:'pre-wrap', maxHeight:340, overflow:'auto' }}>
                {preview.map((p, i) => `${p.source}\n  → ${p.target}`).join('\n')}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Settings Screen ───────────────────────────────────────────────────────────
function SettingsScreen() {
  const [t, setT] = useState({
    sharp_keeper: 0.55, sharp_reject: 0.30,
    reject_closed_eyes: true, accept_overexposed: false, accept_underexposed: false,
    horizon_warn_deg: 3.0,
    w_sharpness: 0.50, w_exposure: 0.18, w_eyes: 0.14, w_composition: 0.08, w_aesthetic: 0.10,
  });
  const [reclassified, setReclassified] = useState(null);
  const [reclassifyBusy, setReclassifyBusy] = useState(false);
  const [regroupMsg, setRegroupMsg] = useState(null);

  const SLIDERS = [
    { key:'sharp_keeper',     label:'Sharp keeper threshold',  note:'Score ≥ this → keeper quality sharpness', min:0.3,  max:0.9, step:0.01 },
    { key:'sharp_reject',     label:'Sharp reject threshold',  note:'Score < this → automatic reject',         min:0.05, max:0.5, step:0.01 },
    { key:'horizon_warn_deg', label:'Horizon tilt warning',    note:'Degrees of tilt before flagging',         min:0.5,  max:10,  step:0.5  },
    { key:'w_sharpness',      label:'Sharpness weight',        note:'Contribution to combined quality score',  min:0,    max:1,   step:0.05 },
    { key:'w_exposure',       label:'Exposure weight',         note:'',                                        min:0,    max:1,   step:0.05 },
    { key:'w_eyes',           label:'Eyes weight',             note:'Face-landmark EAR signal',                min:0,    max:1,   step:0.05 },
    { key:'w_aesthetic',      label:'Aesthetic weight',        note:'NIMA score — requires CoreML model',      min:0,    max:1,   step:0.05 },
  ];

  const TOGGLES = [
    { key:'reject_closed_eyes',  label:'Reject closed eyes',   note:'Requires MediaPipe FaceMesh' },
    { key:'accept_overexposed',  label:'Accept overexposed',   note:"Overexposed frames skip the review flag" },
    { key:'accept_underexposed', label:'Accept underexposed',  note:"Underexposed frames skip the review flag" },
  ];

  return (
    <div className="sg-scroll">
      <div className="sg-page">
        <p className="sg-lede">Tune the chemistry. Sharper acceptance, stricter rejection — recalibrate the whole library on a verdict.</p>

        <div className="sg-card">
          <div className="sg-card-no">i.</div>
          <h2 className="sg-card-h2">Quality <em>thresholds</em>.</h2>
          <div className="sg-card-sub">Adjusting these recalculates verdicts for all non-overridden frames</div>
          {SLIDERS.map(s => (
            <div key={s.key} style={{ display:'grid', gridTemplateColumns:'1fr auto 56px', gap:16, alignItems:'center', padding:'12px 0', borderBottom:'1px dashed var(--c-border)' }}>
              <div>
                <div style={{ fontSize:12, color:'var(--c-text)' }}>{s.label}</div>
                {s.note && <div style={{ fontSize:10, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', marginTop:3 }}>{s.note}</div>}
              </div>
              <input type="range" min={s.min} max={s.max} step={s.step} value={t[s.key]}
                onChange={e => setT({...t, [s.key]: parseFloat(e.target.value)})}
                style={{ width:180, accentColor:'var(--c-accent)' }}
              />
              <div style={{ fontFamily:'var(--font-ui)', fontSize:18, fontWeight:500, fontVariantNumeric:'tabular-nums', color:'var(--c-accent)', textAlign:'right' }}>{t[s.key]}</div>
            </div>
          ))}
        </div>

        <div className="sg-card">
          <div className="sg-card-no">ii.</div>
          <h2 className="sg-card-h2">Rule <em>flags</em>.</h2>
          <div className="sg-card-sub">Boolean overrides to the verdict engine</div>
          {TOGGLES.map(tog => (
            <div key={tog.key} style={{ display:'flex', alignItems:'center', gap:14, padding:'12px 0', borderBottom:'1px dashed var(--c-border)' }}>
              <input type="checkbox" checked={t[tog.key]} onChange={e => setT({...t, [tog.key]: e.target.checked})} style={{ width:18, height:18, accentColor:'var(--c-accent)', flexShrink:0 }} />
              <div>
                <div style={{ fontSize:12, color:'var(--c-text)' }}>{tog.label}</div>
                <div style={{ fontSize:10, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', marginTop:2 }}>{tog.note}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="sg-card" style={{ display:'flex', gap:16, alignItems:'center' }}>
          <div style={{ flex:1 }}>
            <h2 className="sg-card-h2" style={{ marginBottom:4 }}>Re<em>classify</em>.</h2>
            <div className="sg-card-sub" style={{ marginBottom:0 }}>Apply thresholds above to all non-overridden frames</div>
          </div>
          <Btn variant="solid" disabled={reclassifyBusy} onClick={async () => {
            setReclassifyBusy(true);
            setRegroupMsg(null);
            try {
              const payload = {
                sharp_keeper: t.sharp_keeper,
                sharp_reject: t.sharp_reject,
                reject_closed_eyes: t.reject_closed_eyes,
                accept_overexposed: t.accept_overexposed,
                accept_underexposed: t.accept_underexposed,
                horizon_warn_deg: t.horizon_warn_deg,
              };
              const r = await window.SG_API.reclassify(payload);
              const updated = r.updated ?? 0;
              setReclassified(updated);
              if (updated > 0) {
                setRegroupMsg('re-grouping bursts…');
                try {
                  await window.SG_API.regroup({ hamming: 10, seconds: 3 });
                  setRegroupMsg('bursts re-grouped');
                } catch (e) {
                  setRegroupMsg(`bursts: regroup failed (${e.message}) — run manually`);
                }
              }
              window.SG_API.refresh().catch(()=>{});
            } catch (e) {
              setReclassified(`failed: ${e.message}`);
            } finally {
              setReclassifyBusy(false);
            }
          }}>{reclassifyBusy ? 'Reclassifying…' : 'Reclassify with these thresholds'}</Btn>
        </div>
        {reclassified !== null && (
          <div className="sg-toast">
            <div>→ {reclassified} frames reclassified with new thresholds</div>
            {regroupMsg && <div style={{ marginTop:4 }}>↳ {regroupMsg}</div>}
          </div>
        )}

        <FaceClusterSettings />
      </div>
    </div>
  );
}

// ── Face clustering settings card (lives at the bottom of SettingsScreen) ────
function FaceClusterSettings() {
  const [minSize, setMinSize]     = useState(window.SG_PREFS.faceMinSize);
  const [threshold, setThreshold] = useState(window.SG_PREFS.faceThreshold);
  const [msg, setMsg]             = useState('');

  function save() {
    window.SG_API.savePrefs({ faceMinSize: minSize, faceThreshold: threshold });
    setMsg(`saved · min size ${minSize}, threshold ${threshold.toFixed(2)}`);
    setTimeout(() => setMsg(''), 2500);
  }

  return (
    <div className="sg-card">
      <div className="sg-card-no">iv.</div>
      <h2 className="sg-card-h2">Face <em>clustering</em>.</h2>
      <div className="sg-card-sub">Applies the next time you run "Cluster faces"</div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr auto 70px', gap:16, alignItems:'center', padding:'12px 0', borderBottom:'1px dashed var(--c-border)' }}>
        <div>
          <div style={{ fontSize:12, color:'var(--c-text)' }}>Minimum cluster size</div>
          <div style={{ fontSize:10, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', marginTop:3 }}>
            Hide clusters with fewer than N member images
          </div>
        </div>
        <input type="range" min={1} max={20} step={1} value={minSize}
          onChange={e => setMinSize(parseInt(e.target.value, 10))}
          style={{ width:180, accentColor:'var(--c-accent)' }} />
        <div style={{ fontFamily:'var(--font-ui)', fontSize:18, fontWeight:500, fontVariantNumeric:'tabular-nums', color:'var(--c-accent)', textAlign:'right' }}>{minSize}</div>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr auto 70px', gap:16, alignItems:'center', padding:'12px 0', borderBottom:'1px dashed var(--c-border)' }}>
        <div>
          <div style={{ fontSize:12, color:'var(--c-text)' }}>Similarity threshold</div>
          <div style={{ fontSize:10, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', marginTop:3 }}>
            Cosine sim ≥ this → same person · lower = lumpier · default 0.30 (InsightFace buffalo_s)
          </div>
        </div>
        <input type="range" min={0.15} max={0.55} step={0.01} value={threshold}
          onChange={e => setThreshold(parseFloat(e.target.value))}
          style={{ width:180, accentColor:'var(--c-accent)' }} />
        <div style={{ fontFamily:'var(--font-ui)', fontSize:18, fontWeight:500, fontVariantNumeric:'tabular-nums', color:'var(--c-accent)', textAlign:'right' }}>{threshold.toFixed(2)}</div>
      </div>

      <div style={{ display:'flex', alignItems:'center', gap:14, marginTop:14 }}>
        <Btn variant="primary" onClick={save}>Save preferences</Btn>
        {msg && <span className="sg-toast" style={{ marginTop:0 }}>{msg}</span>}
        <div style={{ flex:1 }} />
        <Btn variant="ghost" onClick={async () => {
          setMsg('launching re-clustering…');
          try {
            window.SG_API.savePrefs({ faceMinSize: minSize, faceThreshold: threshold });
            await window.SG_API.runFaces({ threshold });
            setMsg('re-clustering started — watch the sidebar');
          } catch (e) { setMsg(`failed: ${e.message}`); }
        }}>Re-cluster now</Btn>
      </div>
    </div>
  );
}

function DuplicatesScreen() {
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [verdictMsg, setVerdictMsg] = useState('');

  const fetchDuplicates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await window.SG_API.getDuplicates();
      setGroups(res.groups || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDuplicates();
  }, [fetchDuplicates]);

  async function handleVerdict(imageId, verdict) {
    try {
      await window.SG_API.verdict(imageId, { verdict, stars: verdict === 'reject' ? 0 : 3, label: verdict === 'reject' ? 'red' : 'green' });
      // Update local state instead of full refetch for immediate feedback
      setGroups(prev => prev.map(g => ({
        ...g,
        images: g.images.map(img => img.id === imageId ? { ...img, verdict } : img)
      })));
      setVerdictMsg(`Marked image as ${verdict}`);
      setTimeout(() => setVerdictMsg(''), 3000);
      window.SG_REFRESH_UI?.();
    } catch (e) {
      setVerdictMsg(`Failed: {e.message}`);
    }
  }

  async function handleReveal(imageId) {
    try {
      await window.SG_API.reveal(imageId);
    } catch (e) {
      alert(`Reveal failed: ${e.message}`);
    }
  }

  if (loading) {
    return (
      <div style={{ display:'flex', flex:1, alignItems:'center', justifyContent:'center', color:'var(--c-text)' }}>
        <div style={{ fontSize:14, display:'flex', alignItems:'center', gap:10, fontFamily:'var(--font-ui)', letterSpacing:'0.05em', textTransform:'uppercase' }}>
          Detecting near-duplicates across libraries...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ display:'flex', flex:1, flexDirection:'column', alignItems:'center', justifyContent:'center', color:'var(--c-danger)', gap:10 }}>
        <h3>Error detecting duplicates</h3>
        <p style={{ color:'var(--c-text2)', fontSize:13 }}>{error}</p>
        <Btn onClick={fetchDuplicates}>Retry</Btn>
      </div>
    );
  }

  const totalDuplicateImages = groups.reduce((acc, g) => acc + g.images.length, 0);
  const totalLibraries = new Set(groups.flatMap(g => g.images.map(i => i.library_id))).size;

  return (
    <div style={{ display:'flex', flex:1, flexDirection:'column', overflow:'hidden', padding:24, gap:20 }}>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', flexShrink:0 }}>
        <div>
          <h1 style={{ margin:0, fontSize:20, fontWeight:600, color:'var(--c-text)', fontFamily:'var(--font-ui)', letterSpacing:'-0.01em' }}>Cross-Library Duplicates</h1>
          <p style={{ margin:'4px 0 0', color:'var(--c-mute)', fontSize:12, fontFamily:'var(--font-ui)' }}>
            Detecting images with similar contents (phash hamming distance ≤ 10) spread across different folders/libraries.
          </p>
        </div>
        <Btn onClick={fetchDuplicates}>Refresh Report</Btn>
      </div>

      {verdictMsg && (
        <div style={{ background:'rgba(193,68,14,0.1)', color:'var(--c-accent)', padding:'8px 16px', borderRadius:'var(--radius)', fontSize:12, fontFamily:'var(--font-ui)' }}>
          {verdictMsg}
        </div>
      )}

      {groups.length === 0 ? (
        <div style={{ flex:1, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', border:'2px dashed var(--c-border)', borderRadius:'var(--radius)', color:'var(--c-mute)', gap:10 }}>
          <span style={{ fontSize:32 }}>🎉</span>
          <h3 style={{ margin:0, color:'var(--c-text)', fontWeight:600 }}>No Cross-Library Duplicates Found</h3>
          <p style={{ margin:0, fontSize:12 }}>All your libraries are clean of cross-library duplicate sets.</p>
        </div>
      ) : (
        <div style={{ flex:1, overflowY:'auto', display:'flex', flexDirection:'column', gap:20, paddingRight:6 }}>
          <div style={{ background:'rgba(193,68,14,0.06)', border:'1px solid var(--c-border2)', padding:12, borderRadius:'var(--radius)', fontSize:12, color:'var(--c-text2)', fontFamily:'var(--font-ui)' }}>
            Found <strong>{groups.length} duplicate groups</strong> containing <strong>{totalDuplicateImages} near-identical images</strong> spread across <strong>{totalLibraries} libraries</strong>.
          </div>

          {groups.map((g, idx) => {
            const groupLibraries = Array.from(new Set(g.images.map(img => img.library_name))).join(', ');
            return (
              <div key={g.group_id || idx} style={{ border:'1px solid var(--c-border)', borderRadius:'var(--radius)', background:'var(--c-card-bg)', overflow:'hidden' }}>
                <div style={{ background:'var(--c-border2)', padding:'10px 16px', display:'flex', justifyContent:'space-between', alignItems:'center', borderBottom:'1px solid var(--c-border)', fontFamily:'var(--font-ui)' }}>
                  <span style={{ fontWeight:600, fontSize:12, color:'var(--c-text)', textTransform:'uppercase', letterSpacing:'0.05em' }}>
                    Group #{idx + 1}
                  </span>
                  <span style={{ fontSize:11, color:'var(--c-mute)' }}>
                    Spread across: <strong style={{ color:'var(--c-text)' }}>{groupLibraries}</strong>
                  </span>
                </div>
                
                <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(280px, 1fr))', gap:16, padding:16 }}>
                  {g.images.map(img => {
                    const bust = img.content_hash ? `&h=${img.content_hash.slice(-8)}` : '';
                    const thumbUrl = `/api/images/${img.id}/thumb?size=420${bust}`;
                    
                    return (
                      <div key={img.id} style={{ display:'flex', flexDirection:'column', border:'1px solid var(--c-border2)', borderRadius:'var(--radius)', overflow:'hidden', background:'var(--c-bg)' }}>
                        <div style={{ position:'relative', height:180, display:'flex', alignItems:'center', justifyContent:'center', background:'rgba(0,0,0,0.2)', borderBottom:'1px solid var(--c-border2)' }}>
                          <img 
                            src={thumbUrl} 
                            alt="Duplicate candidate"
                            style={{ maxWidth:'100%', maxHeight:'100%', objectFit:'contain' }}
                          />
                          {img.verdict === 'keeper' && (
                            <span style={{ position:'absolute', top:8, left:8, background:'var(--c-keeper)', color:'white', fontSize:9, fontWeight:700, padding:'2px 6px', borderRadius:4, textTransform:'uppercase' }}>
                              Keeper
                            </span>
                          )}
                          {img.verdict === 'reject' && (
                            <span style={{ position:'absolute', top:8, left:8, background:'var(--c-danger)', color:'white', fontSize:9, fontWeight:700, padding:'2px 6px', borderRadius:4, textTransform:'uppercase' }}>
                              Reject
                            </span>
                          )}
                        </div>
                        
                        <div style={{ padding:12, flex:1, display:'flex', flexDirection:'column', gap:8 }}>
                          <div style={{ display:'flex', flexDirection:'column', gap:3 }}>
                            <span style={{ fontSize:10, color:'var(--c-accent)', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.05em', fontFamily:'var(--font-ui)' }}>
                              {img.library_name}
                            </span>
                            <span 
                              style={{ fontSize:12, color:'var(--c-text)', wordBreak:'break-all', fontFamily:'monospace' }}
                              title={img.path}
                            >
                              {img.path.split('/').pop()}
                            </span>
                          </div>
                          
                          <div style={{ fontSize:11, color:'var(--c-mute)', display:'flex', flexDirection:'column', gap:2, fontFamily:'var(--font-ui)' }}>
                            <span style={{ wordBreak:'break-all' }}>Path: {img.path}</span>
                            <span>Rating: <span style={{ color:'var(--c-amber)' }}>{'★'.repeat(img.stars)}</span>{'·'.repeat(5 - img.stars)}</span>
                          </div>
                          
                          <div style={{ marginTop:'auto', paddingTop:8, borderTop:'1px solid var(--c-border2)', display:'flex', gap:6 }}>
                            <Btn 
                              variant={img.verdict === 'keeper' ? 'primary' : 'ghost'} 
                              onClick={() => handleVerdict(img.id, 'keeper')}
                              style={{ flex: 1, fontSize: 10, padding: '4px 8px' }}
                            >
                              Keeper
                            </Btn>
                            <Btn 
                              variant={img.verdict === 'reject' ? 'danger' : 'ghost'} 
                              onClick={() => handleVerdict(img.id, 'reject')}
                              style={{ flex: 1, fontSize: 10, padding: '4px 8px' }}
                            >
                              Reject
                            </Btn>
                            <Btn 
                              variant="ghost" 
                              onClick={() => handleReveal(img.id)}
                              style={{ fontSize: 10, padding: '4px 8px' }}
                              title="Reveal in Finder"
                            >
                              🔍
                            </Btn>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { LibraryScreen, BurstsScreen, DuplicatesScreen, FacesScreen, XMPExportScreen, OrganizeScreen, SettingsScreen });
