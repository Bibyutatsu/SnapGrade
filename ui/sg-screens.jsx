// SnapGrade — Secondary Screens
// Library, Bursts, Faces, XMP Export, Organize, Settings

const { useState, useEffect, useMemo, useCallback } = React;

// ── Shared library filter bar ─────────────────────────────────────────────────
function LibraryFilterBar({ activeLib, setActiveLib, counts }) {
  const { MOCK_LIBRARIES } = window.SG_DATA;
  return (
    <div style={{
      display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap',
      padding: '9px 20px', borderBottom: '1px solid var(--c-border)',
      background: 'var(--c-panel2)', flexShrink: 0,
    }}>
      <span style={{ fontSize: 8, letterSpacing: '0.28em', textTransform: 'uppercase',
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
function LibraryScreen({ stats }) {
  const { MOCK_LIBRARIES } = window.SG_DATA;
  const [folder, setFolder] = useState('');
  const [msg, setMsg]       = useState('');
  const [enabled, setEnabled] = useState({ content_type: true, scene: true, subject_seg: false, objects: false, semantic: false });
  const [postSteps, setPostSteps] = useState({ group: true, faces: false });
  const [query, setQuery]   = useState('');
  const [results, setResults] = useState(null);  // null = no search yet, [] = empty results
  const [searching, setSearching] = useState(false);
  const [searchMsg, setSearchMsg] = useState('');

  async function runSearch() {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setSearchMsg('');
    try {
      const items = await window.SG_API.search(q, { k: 24 });
      setResults(items);
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
      const path = await window.SG_API.pickFolder();
      if (path) setFolder(path);
    } catch (e) { setMsg(`folder picker failed: ${e.message}`); }
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
    if (!folder) return;
    setMsg('');
    try {
      const models = Object.entries(enabled).filter(([, v]) => v).map(([k]) => k);
      const r = await window.SG_API.ingest(folder, models);
      setMsg(`ingest started for ${r.folder} (library #${r.library_id})`);
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
        setMsg('post-ingest steps started · watch the sidebar for progress');
      }
    } catch (e) { setMsg(`ingest failed: ${e.message}`); }
  }
  async function syncLib(id) {
    setMsg('');
    try { await window.SG_API.syncLibrary(id); setMsg(`sync started for library #${id}`); }
    catch (e) { setMsg(`sync failed: ${e.message}`); }
  }
  async function removeLib(id, name) {
    if (!confirm(`Remove "${name}" from the catalogue? Disk files stay put.`)) return;
    setMsg('');
    try { await window.SG_API.removeLibrary(id); setMsg(`removed library #${id} — reloading`); setTimeout(()=>location.reload(), 600); }
    catch (e) { setMsg(`remove failed: ${e.message}`); }
  }

  // Reflects the real api.py MODEL_INFO + pipeline.py capabilities.
  // content_type replaces the old screendoc CoreML model — uses Apple Vision,
  // no download required.
  const MODEL_INFO = {
    scene:        { label: 'Scene classifier',       note: 'Places365 — adds {scene} organise token', download: true  },
    subject_seg:  { label: 'Salient subject seg',    note: 'U²-Netp — better subject mask for sharpness', download: true  },
    objects:      { label: 'Object detector',        note: 'YOLO26n — COCO classes, adds {object:class} token', download: true  },
    content_type: { label: 'Screenshot / document',  note: 'Apple Vision — no download, runs on Neural Engine', download: false },
    semantic:     { label: 'Semantic search index',   note: 'MobileCLIP-S0 — 512-d embedding per image, enables text search', download: true  },
  };

  return (
    <div className="sg-scroll">
      <div className="sg-page">
        <p className="sg-lede">Point the lens at a folder. Frames are read, measured, and filed — nothing is moved, nothing is altered.</p>

        <div className="sg-card">
          <div className="sg-card-no">i.</div>
          <h2 className="sg-card-h2">Open a <em>roll</em>.</h2>
          <div className="sg-card-sub">Ingest · scan · measure · catalogue</div>
          <div style={{ display:'flex', gap:10, alignItems:'stretch' }}>
            <div className="sg-folder-display" style={{ flex:1, color: folder ? 'var(--c-text)' : 'var(--c-mute)', fontStyle: folder ? 'normal' : 'italic' }}>
              {folder || 'no folder selected'}
            </div>
            <Btn variant="ghost" onClick={pickFolder}>Choose folder…</Btn>
            <Btn variant="primary" disabled={!folder} onClick={develop}>Develop</Btn>
          </div>
          <div className="sg-model-checklist">
            <div className="sg-model-label">Optional models · weights in ~/.snapgrade/models/</div>
            {Object.entries(MODEL_INFO).map(([k, info]) => (
              <label key={k} style={{ display:'flex', alignItems:'center', gap:10, fontSize:12, color:'var(--c-text)', cursor:'pointer', padding:'3px 0' }}>
                <input type="checkbox" checked={!!enabled[k]} onChange={e => setEnabled(s => ({ ...s, [k]: e.target.checked }))} style={{ accentColor:'var(--c-accent)' }} />
                <span>{info.label}</span>
                <span style={{ fontSize:10, color:'var(--c-mute)' }}>— {info.note}</span>
                {!info.download && (
                  <span style={{ fontSize:8, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-keeper)', marginLeft:'auto', padding:'2px 6px', border:'1px solid var(--c-keeper)', borderRadius:'var(--radius)' }}>built-in</span>
                )}
              </label>
            ))}
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

        <div className="sg-card">
          <div className="sg-card-no">★</div>
          <h2 className="sg-card-h2">Search by <em>description</em>.</h2>
          <div className="sg-card-sub">MobileCLIP semantic search · requires embeddings (set SNAPGRADE_ENABLE_SEMANTIC=1 during ingest)</div>
          <div style={{ display:'flex', gap:10, alignItems:'stretch' }}>
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') runSearch(); }}
              placeholder='e.g. "crowd of people", "blurry photo", "text on a sign"'
              className="sg-folder-display"
              style={{ flex:1, color:'var(--c-text)', fontStyle:'normal' }}
            />
            <Btn variant="primary" disabled={!query.trim() || searching} onClick={runSearch}>
              {searching ? 'Searching…' : 'Search'}
            </Btn>
          </div>
          {searchMsg && <div className="sg-toast">{searchMsg}</div>}
          {results && results.length > 0 && (
            <div style={{ marginTop:14, display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(140px, 1fr))', gap:10 }}>
              {results.map(r => (
                <a key={r.image_id} href={`/api/images/${r.image_id}/preview`} target="_blank" rel="noreferrer"
                   style={{ position:'relative', display:'block', aspectRatio:'1/1', overflow:'hidden', borderRadius:'var(--radius)', border:'1px solid var(--c-border2)' }}>
                  <img src={r.thumb} alt="" loading="lazy" style={{ width:'100%', height:'100%', objectFit:'cover', display:'block' }} />
                  <span style={{ position:'absolute', bottom:4, right:4, fontSize:9, padding:'2px 6px', background:'rgba(0,0,0,0.7)', color:'#fff', borderRadius:'var(--radius)', letterSpacing:'0.05em' }}>
                    {r.score.toFixed(3)}
                  </span>
                </a>
              ))}
            </div>
          )}
        </div>

        <div className="sg-card">
          <div className="sg-card-no">ii.</div>
          <h2 className="sg-card-h2">Your <em>libraries</em>.</h2>
          <div className="sg-card-sub">Each folder tracked independently · remove without touching disk</div>
          <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
            {MOCK_LIBRARIES.map(lib => {
              const v = lib.by_verdict || {};
              return (
                <div key={lib.id} className="sg-lib-row">
                  <div style={{ flex:1 }}>
                    <div style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:20, color:'var(--c-text)', marginBottom:2 }}>{lib.display_name}</div>
                    <div style={{ fontSize:10, color:'var(--c-mute)', marginBottom:8, wordBreak:'break-all' }}>{lib.root_path}</div>
                    <div style={{ display:'flex', gap:18, fontSize:11, color:'var(--c-text2)' }}>
                      <span><b style={{ fontFamily:'var(--font-display)', fontStyle:'italic', color:'var(--c-text)' }}>{lib.image_count}</b> frames</span>
                      <span style={{ color:'var(--c-keeper)' }}><b>{v.keeper||0}</b> keep</span>
                      <span style={{ color:'var(--c-amber)' }}><b>{v.review||0}</b> review</span>
                      <span style={{ color:'var(--c-danger)' }}><b>{v.reject||0}</b> reject</span>
                    </div>
                    <div style={{ display:'flex', gap:6, marginTop:8, flexWrap:'wrap' }}>
                      {Object.keys(lib.models_run || {}).map(m => (
                        <span key={m} style={{ fontSize:8, letterSpacing:'0.2em', textTransform:'uppercase', padding:'3px 8px', border:'1px solid var(--c-keeper)', color:'var(--c-keeper)', borderRadius:'var(--radius)' }}>{m} ✓</span>
                      ))}
                    </div>
                  </div>
                  <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
                    <Btn variant="ghost"  style={{ fontSize:9, padding:'6px 12px' }} onClick={() => syncLib(lib.id)}>Sync</Btn>
                    <Btn variant="danger" style={{ fontSize:9, padding:'6px 12px' }} onClick={() => removeLib(lib.id, lib.display_name)}>Remove</Btn>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {stats && (
          <div className="sg-card" style={{ padding:0 }}>
            <div className="sg-card-no">iii.</div>
            <div style={{ padding:'24px 28px 0' }}>
              <h2 className="sg-card-h2">State of the <em>library</em>.</h2>
              <div className="sg-card-sub">Live counts</div>
            </div>
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
          </div>
        )}
      </div>
    </div>
  );
}

// ── Bursts Screen ─────────────────────────────────────────────────────────────
function BurstsScreen() {
  const { MOCK_BURSTS, MOCK_LIBRARIES } = window.SG_DATA;
  const [activeLib, setActiveLib] = useState(null);
  const [picked, setPicked]       = useState({});

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
      await window.SG_API.refresh();
      setTimeout(() => location.reload(), 500);
    } catch (e) { setGroupMsg(`regroup failed: ${e.message}`); }
    finally { setGrouping(false); }
  }

  return (
    <div style={{ display:'flex', flex:1, minHeight:0, overflow:'hidden', flexDirection:'column' }}>
      <LibraryFilterBar activeLib={activeLib} setActiveLib={setActiveLib} counts={libCounts} />
      <div style={{ display:'flex', gap:10, alignItems:'center', padding:'8px 20px', borderBottom:'1px solid var(--c-border)', background:'var(--c-bg)', flexShrink:0 }}>
        <span style={{ fontSize:9, letterSpacing:'.22em', textTransform:'uppercase', color:'var(--c-mute)' }}>
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
              <div style={{ display:'flex', alignItems:'baseline', gap:16, marginBottom:20 }}>
                <h2 style={{ fontFamily:'var(--font-display)', fontSize:32, fontWeight:400, letterSpacing:'-0.01em', margin:0 }}>
                  Burst <em style={{ color:'var(--c-accent)' }}>#{burst.burst_id}</em>
                </h2>
                <span style={{ fontSize:10, letterSpacing:'0.22em', textTransform:'uppercase', color:'var(--c-mute)' }}>
                  {burstImages.length} frames · compare &amp; pick sharpest
                </span>
              </div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(260px, 1fr))', gap:16 }}>
                {burstImages.map(img => {
                  const isBest = picked[burst.burst_id] === img.id || (!picked[burst.burst_id] && img.is_best);
                  return (
                    <div key={img.id} style={{ outline: isBest ? '2px solid var(--c-accent)' : '1px solid var(--c-border)', outlineOffset:-1, borderRadius:'var(--radius)', overflow:'hidden', background:'var(--c-panel)', position:'relative' }}>
                      {isBest && (
                        <div style={{ position:'absolute', top:10, left:10, background:'var(--c-accent)', color:'var(--c-bg)', fontSize:8, letterSpacing:'0.22em', textTransform:'uppercase', padding:'3px 8px', zIndex:2 }}>Best pick</div>
                      )}
                      <img src={img.thumb} alt="" style={{ width:'100%', height:180, objectFit:'cover', display:'block', filter:'contrast(1.04)' }} />
                      <div style={{ padding:'12px 14px' }}>
                        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
                          <span style={{ fontFamily:'var(--font-display)', fontStyle:'italic', color:'var(--c-accent)', fontSize:16 }}>№{pad(img.id,4)}</span>
                          <span style={{ fontSize:9, letterSpacing:'0.2em', textTransform:'uppercase', color: verdictColor(img.verdict) }}>{img.verdict}</span>
                        </div>
                        <div style={{ marginBottom:10 }}>
                          <div style={{ display:'flex', justifyContent:'space-between', fontSize:9, letterSpacing:'0.16em', textTransform:'uppercase', color:'var(--c-mute)', marginBottom:4 }}>
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
                            <div style={{ display:'flex', justifyContent:'space-between', fontSize:9, letterSpacing:'0.16em', textTransform:'uppercase', color:'var(--c-mute)', marginBottom:4 }}>
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
                        <button onClick={() => setPicked(p => ({ ...p, [burst.burst_id]: img.id }))} style={{ width:'100%', padding:'8px', fontSize:9, letterSpacing:'0.22em', textTransform:'uppercase', border:`1px solid ${isBest ? 'var(--c-accent)' : 'var(--c-border2)'}`, color: isBest ? 'var(--c-accent)' : 'var(--c-mute)', background: isBest ? 'rgba(193,68,14,0.08)' : 'transparent', cursor:'pointer', borderRadius:'var(--radius)', fontFamily:'var(--font-ui)' }}>
                          {isBest ? '✓ Picked' : 'Pick this'}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100%', color:'var(--c-mute)', fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:24 }}>
              {visibleBursts.length === 0 ? 'No bursts in this folder' : 'Select a burst to compare'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Face Clusters Screen ──────────────────────────────────────────────────────
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
  useEffect(() => { setExpanded(null); }, [activeLib]);

  const reload = useCallback(async () => {
    setLoading(true);
    try { setClusters(await window.SG_API.loadClusters()); }
    catch (e) { console.error('loadClusters failed:', e); setClusters([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

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

  async function runClustering() {
    setRunMsg(''); setRunning(true);
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
        <span style={{ fontSize:9, letterSpacing:'.22em', textTransform:'uppercase', color:'var(--c-mute)' }}>
          {clusters.length} cluster{clusters.length === 1 ? '' : 's'} · InsightFace + greedy/HNSW
        </span>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:9, letterSpacing:'.22em', textTransform:'uppercase', color:'var(--c-mute)' }}>Sort</span>
          <button
            onClick={() => setSortMode(s => s === 'size_desc' ? 'size_asc' : 'size_desc')}
            style={{ fontSize:10, letterSpacing:'.18em', textTransform:'uppercase', padding:'4px 10px', border:'1px solid var(--c-border)', background:'var(--c-panel)', color:'var(--c-text)', cursor:'pointer', borderRadius:'var(--radius)', fontFamily:'var(--font-ui)' }}
            title="Toggle cluster sort order"
          >
            size {sortMode === 'size_desc' ? '↓' : '↑'}
          </button>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:9, letterSpacing:'.22em', textTransform:'uppercase', color:'var(--c-mute)' }}>Threshold</span>
          <input type="range" min={0.15} max={0.55} step={0.01} value={threshold}
            onChange={e => setThreshold(parseFloat(e.target.value))}
            disabled={running}
            style={{ width:140, accentColor:'var(--c-accent)' }}
            title="Cosine similarity threshold for clustering (lower = lumpier)" />
          <span style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:16, color:'var(--c-accent)', minWidth:36, textAlign:'right' }}>{threshold.toFixed(2)}</span>
        </div>
        <div style={{ flex:1 }} />
        {runMsg && <span className="sg-toast" style={{ marginTop:0 }}>{runMsg}</span>}
        <Btn variant="primary" disabled={running} onClick={runClustering}>
          {running ? 'Clustering…' : 'Recluster'}
        </Btn>
      </div>
      <div className="sg-scroll">
        <div className="sg-page">
          <p className="sg-lede">Faces grouped by similarity across the library. Identify recurring subjects and curate by person.</p>
          {!cluster ? (
            <>
              {loading ? (
                <EmptyState>Loading clusters…</EmptyState>
              ) : visibleClusters.length === 0 ? (
                <EmptyState>No face clusters yet — press "Recluster".</EmptyState>
              ) : (
                <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(200px, 1fr))', gap:16, marginBottom:32 }}>
                  {visibleClusters.map(c => (
                    <button key={c.id} onClick={() => setExpanded(c.id)}
                      style={{ border:'1px solid var(--c-border)', background:'var(--c-panel)', padding:0, cursor:'pointer', borderRadius:'var(--radius)', overflow:'hidden', transition:'border-color .15s, transform .15s', textAlign:'left' }}
                      onMouseOver={e => { e.currentTarget.style.borderColor='var(--c-text2)'; e.currentTarget.style.transform='translateY(-2px)'; }}
                      onMouseOut={e  => { e.currentTarget.style.borderColor='var(--c-border)';  e.currentTarget.style.transform='none'; }}
                    >
                      <div style={{ position:'relative', height:160, background:'var(--c-border)', overflow:'hidden' }}>
                        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gridTemplateRows:'1fr 1fr', gap:1, height:'100%' }}>
                          {c.thumbs.slice(0,4).map(t => (
                            <img key={t.id} src={t.url} alt="" style={{ width:'100%', height:'100%', objectFit:'cover', display:'block', filter:'saturate(0.85)', minWidth:0, minHeight:0 }} />
                          ))}
                        </div>
                        <div style={{ position:'absolute', top:8, left:8, padding:'3px 8px', background:'rgba(0,0,0,0.65)', color:'var(--c-accent)', fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:14, lineHeight:1, borderRadius:'var(--radius)', backdropFilter:'blur(2px)' }}>
                          {c.count}
                        </div>
                      </div>
                      <div style={{ padding:'12px 14px' }}>
                        <div style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:18, color:'var(--c-text)', marginBottom:4 }}>{c.label}</div>
                        <div style={{ fontSize:10, color:'var(--c-mute)', display:'flex', justifyContent:'space-between' }}>
                          <span>{c.count} appearances</span>
                          <span style={{ color:'var(--c-accent)' }}>View all →</span>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <button onClick={() => setExpanded(null)} style={{ fontSize:10, letterSpacing:'0.2em', textTransform:'uppercase', color:'var(--c-mute)', background:'none', border:'none', cursor:'pointer', marginBottom:20, display:'flex', alignItems:'center', gap:8, fontFamily:'var(--font-ui)' }}>‹ Back to clusters</button>
              <div style={{ display:'flex', alignItems:'center', gap:16, marginBottom:24 }}>
                <img src={cluster.rep_thumb} alt="" style={{ width:60, height:60, objectFit:'cover', borderRadius:'50%', border:'2px solid var(--c-border2)' }} />
                <div>
                  <h2 style={{ fontFamily:'var(--font-display)', fontSize:28, fontWeight:400, margin:'0 0 4px', color:'var(--c-text)' }}>{cluster.label}</h2>
                  <div style={{ fontSize:10, color:'var(--c-mute)', letterSpacing:'0.18em', textTransform:'uppercase' }}>{cluster.count} appearances across library</div>
                </div>
              </div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(180px, 1fr))', gap:10 }}>
                {cluster.thumbs.map(t => (
                  <div key={t.id} style={{ border:'1px solid var(--c-border)', borderRadius:'var(--radius)', overflow:'hidden', background:'var(--c-panel)' }}>
                    <img src={t.url} alt="" style={{ width:'100%', height:130, objectFit:'cover', display:'block', filter:'contrast(1.03)' }} />
                    <div style={{ padding:'8px 10px', fontSize:9, color:'var(--c-mute)', letterSpacing:'0.18em', textTransform:'uppercase', display:'flex', justifyContent:'space-between' }}>
                      <span>№{pad(t.id,4)}</span>
                      <span style={{ color:'var(--c-keeper)' }}>keeper</span>
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
        <span style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:17, color:'var(--c-text)', marginRight:6 }}>Write XMP sidecars</span>
        {['all','keeper','review','reject'].map(f => (
          <Chip key={f} on={verdictFilter === f} onClick={() => setVerdictFilter(f)}>{f}</Chip>
        ))}
        <div style={{ flex:1 }} />
        <label style={{ fontSize:9, color:'var(--c-text2)', cursor:'pointer', display:'flex', alignItems:'center', gap:8, letterSpacing:'0.16em', textTransform:'uppercase', fontFamily:'var(--font-ui)' }}>
          <input type="checkbox" checked={allChecked} onChange={toggleAll} style={{ accentColor:'var(--c-accent)' }} />
          Select all ({filtered.length})
        </label>
        <Btn variant="primary" disabled={selectedCount === 0 || progress !== null} onClick={runExport}>
          Export{selectedCount > 0 ? ` (${selectedCount})` : ''}
        </Btn>
      </div>
      {progress && (
        <div style={{ padding:'7px 20px', background:'var(--c-panel)', borderBottom:'1px solid var(--c-border)', flexShrink:0 }}>
          <div style={{ display:'flex', justifyContent:'space-between', fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-text2)', marginBottom:5 }}>
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
                  <th key={h} style={{ padding:'8px 12px', textAlign:'left', fontSize:8, letterSpacing:'0.26em', textTransform:'uppercase', color:'var(--c-mute)', fontWeight:400, fontFamily:'var(--font-ui)', whiteSpace:'nowrap' }}>{h}</th>
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
                        <span style={{ fontFamily:'var(--font-display)', fontStyle:'italic', color:'var(--c-accent)', fontSize:14 }}>№{pad(img.id,4)}</span>
                      </div>
                    </td>
                    <td style={{ padding:'9px 12px', fontSize:10, color:'var(--c-mute)', whiteSpace:'nowrap', maxWidth:140, overflow:'hidden', textOverflow:'ellipsis' }}>{lib ? (lib.display_name || lib.root_path.split('/').pop()) : '—'}</td>
                    <td style={{ padding:'9px 12px', fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color: verdictColor(img.verdict) }}>{img.verdict}</td>
                    <td style={{ padding:'9px 12px', color:'var(--c-amber)', fontSize:12, letterSpacing:'-1px' }}>{'★'.repeat(img.stars||0)}</td>
                    {/* Content type column (new) */}
                    <td style={{ padding:'9px 12px', fontSize:9 }}>
                      {img.content_type && img.content_type !== 'photo' ? (
                        <span style={{ padding:'2px 6px', fontSize:8, letterSpacing:'0.16em', textTransform:'uppercase', background: img.content_type === 'screenshot' ? 'var(--c-amber)' : 'var(--c-accent)', color:'var(--c-bg)', borderRadius:'var(--radius)', fontFamily:'var(--font-ui)' }}>
                          {img.content_type === 'screenshot' ? '🖥' : '📄'} {img.content_type}
                        </span>
                      ) : (
                        <span style={{ color:'var(--c-mute)' }}>photo</span>
                      )}
                    </td>
                    <td style={{ padding:'9px 12px', fontSize:10, color:'var(--c-mute)', maxWidth:180, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{(img.reasons||[]).join(', ') || '—'}</td>
                    <td style={{ padding:'9px 12px', fontSize:10, color:'var(--c-text2)', whiteSpace:'nowrap' }}>{img.camera_model}</td>
                    <td style={{ padding:'9px 12px', fontSize:9, letterSpacing:'0.18em', color: isDone ? 'var(--c-keeper)' : 'var(--c-mute)', whiteSpace:'nowrap' }}>{isDone ? '✓ written' : '—'}</td>
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
              <span style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:20, color:'var(--c-accent)', textAlign:'center' }}>{i+1}.</span>
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
          <button onClick={() => setLevels([...levels, ORGANIZE_TOKENS[0]])} style={{ fontSize:9, letterSpacing:'0.22em', textTransform:'uppercase', color:'var(--c-text2)', background:'none', border:'1px dashed var(--c-border2)', padding:'7px 14px', cursor:'pointer', marginTop:4, borderRadius:'var(--radius)', fontFamily:'var(--font-ui)' }}>+ add level</button>

          {/* Token reference card */}
          <div style={{ marginTop:20, padding:'14px 16px', border:'1px dashed var(--c-border2)', borderRadius:'var(--radius)', background:'var(--c-bg)' }}>
            <div style={{ fontSize:8, letterSpacing:'0.28em', textTransform:'uppercase', color:'var(--c-mute)', marginBottom:12 }}>Token reference</div>
            <div style={{ display:'flex', flexWrap:'wrap', gap:16 }}>
              {TOKEN_GROUPS.map(g => (
                <div key={g.label}>
                  <div style={{ fontSize:9, letterSpacing:'0.22em', textTransform:'uppercase', color:'var(--c-accent)', marginBottom:6 }}>{g.label}</div>
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
              <div style={{ fontSize:9, letterSpacing:'0.22em', textTransform:'uppercase', color:'var(--c-mute)', marginBottom:10 }}>
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
                {s.note && <div style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', marginTop:3 }}>{s.note}</div>}
              </div>
              <input type="range" min={s.min} max={s.max} step={s.step} value={t[s.key]}
                onChange={e => setT({...t, [s.key]: parseFloat(e.target.value)})}
                style={{ width:180, accentColor:'var(--c-accent)' }}
              />
              <div style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:22, color:'var(--c-accent)', textAlign:'right' }}>{t[s.key]}</div>
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
                <div style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', marginTop:2 }}>{tog.note}</div>
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
          <div style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', marginTop:3 }}>
            Hide clusters with fewer than N member images
          </div>
        </div>
        <input type="range" min={1} max={20} step={1} value={minSize}
          onChange={e => setMinSize(parseInt(e.target.value, 10))}
          style={{ width:180, accentColor:'var(--c-accent)' }} />
        <div style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:22, color:'var(--c-accent)', textAlign:'right' }}>{minSize}</div>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr auto 70px', gap:16, alignItems:'center', padding:'12px 0', borderBottom:'1px dashed var(--c-border)' }}>
        <div>
          <div style={{ fontSize:12, color:'var(--c-text)' }}>Similarity threshold</div>
          <div style={{ fontSize:9, letterSpacing:'0.18em', textTransform:'uppercase', color:'var(--c-mute)', marginTop:3 }}>
            Cosine sim ≥ this → same person · lower = lumpier · default 0.30 (InsightFace buffalo_s)
          </div>
        </div>
        <input type="range" min={0.15} max={0.55} step={0.01} value={threshold}
          onChange={e => setThreshold(parseFloat(e.target.value))}
          style={{ width:180, accentColor:'var(--c-accent)' }} />
        <div style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:22, color:'var(--c-accent)', textAlign:'right' }}>{threshold.toFixed(2)}</div>
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

Object.assign(window, { LibraryScreen, BurstsScreen, FacesScreen, XMPExportScreen, OrganizeScreen, SettingsScreen });
