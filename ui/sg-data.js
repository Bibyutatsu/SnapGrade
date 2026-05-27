// SnapGrade — Data layer
// Hydrates window.SG_DATA from the FastAPI backend. Exposes SG_API with helpers
// for the action handlers in the screen components.

(function () {
  const API = '';   // same origin as the UI

  // ── Empty defaults so components that read SG_DATA at parse-time don't crash.
  window.SG_DATA = {
    MOCK_IMAGES: [],
    MOCK_LIBRARIES: [],
    MOCK_BURSTS: [],
    MOCK_CLUSTERS: [],
    MOCK_STATS: { images: 0, libraries: 0, bursts: 0, by_verdict: {}, ingest: { running: false } },
    ORGANIZE_TOKENS: [],
  };

  async function jget(path) {
    const r = await fetch(API + path);
    if (!r.ok) throw new Error(`${path} → ${r.status}`);
    return r.json();
  }
  // Custom header required by the backend's CSRF guard (require_local). Its
  // presence forces a CORS preflight, which the locked-down origin list rejects
  // for any cross-site page — so only the same-origin UI can drive mutations.
  const CSRF = { 'X-SnapGrade': '1' };

  async function jpost(path, body) {
    const r = await fetch(API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...CSRF },
      body: body == null ? null : JSON.stringify(body),
    });
    if (!r.ok) {
      let detail = '';
      try { detail = (await r.json()).detail || ''; } catch {}
      throw new Error(`${path} → ${r.status} ${detail}`);
    }
    return r.json();
  }
  async function jdel(path) {
    const r = await fetch(API + path, { method: 'DELETE', headers: { ...CSRF } });
    if (!r.ok) throw new Error(`${path} → ${r.status}`);
    return r.json();
  }
  async function jpatch(path, body) {
    const r = await fetch(API + path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...CSRF },
      body: body == null ? null : JSON.stringify(body),
    });
    if (!r.ok) {
      let detail = '';
      try { detail = (await r.json()).detail || ''; } catch {}
      throw new Error(`${path} → ${r.status} ${detail}`);
    }
    return r.json();
  }

  // ── Shape adapters ──────────────────────────────────────────────────────────
  // API rows → the shape the prototype components expect.
  function shapeImage(r) {
    const bust = r.content_hash ? `&h=${r.content_hash.slice(-8)}` : '';
    const thumb   = `/api/images/${r.id}/thumb?size=420${bust}`;
    const preview = `/api/images/${r.id}/preview?h=${r.content_hash ? r.content_hash.slice(-8) : ''}`;
    return {
      id: r.id,
      path: r.path,
      thumb,
      preview,
      verdict: r.verdict || null,
      stars: r.stars || 0,
      reasons: r.reasons || [],
      camera_model: r.camera_model || '—',
      lens: r.lens || '—',
      iso: r.iso ?? '—',
      f_number: r.f_number ?? '—',
      exposure_time: r.exposure_time || '—',
      sharpness: typeof r.sharpness === 'number' ? r.sharpness : 0,
      aesthetic_score: r.aesthetic_score ?? null,
      burst_id: r.burst_id ?? null,
      is_best: !!r.is_best,
      capture_time: r.capture_time || null,
      library_id: r.library_id ?? null,
      width: r.width || 0,
      height: r.height || 0,
      scene: r.scene || null,
      content_type: r.content_type || 'photo',
      color: r.color || null,
      ocr: r.ocr || [],
      animals: r.animals || [],
      user_override: !!r.user_override,
    };
  }

  function shapeLibrary(l) {
    // /api/libraries items already carry display_name, root_path, image_count,
    // by_verdict, models_run, models_pending. Just normalise.
    return {
      id: l.id,
      display_name: l.display_name || (l.root_path ? l.root_path.split('/').pop() : 'untitled'),
      root_path: l.root_path,
      image_count: l.image_count || 0,
      by_verdict: l.by_verdict || {},
      models_run: l.models_run || {},
      models_pending: l.models_pending || [],
    };
  }

  // ── Bootstrap: fetch everything in parallel ────────────────────────────────
  async function bootstrap() {
    const [stats, libs, imgs, bursts, tokens] = await Promise.all([
      jget('/api/stats').catch(() => null),
      jget('/api/libraries').catch(() => ({ items: [] })),
      jget('/api/images?limit=2000').catch(() => ({ items: [] })),
      jget('/api/bursts').catch(() => ({ items: [] })),
      jget('/api/tokens').catch(() => ({ tokens: [] })),
    ]);

    const MOCK_IMAGES    = (imgs.items || []).map(shapeImage);
    const MOCK_LIBRARIES = (libs.items || []).map(shapeLibrary);

    // For Bursts screen — group images by burst_id; the /api/bursts list is
    // just (burst_id, count) so we use the in-memory images.
    const burstMap = new Map();
    for (const img of MOCK_IMAGES) {
      if (img.burst_id == null) continue;
      if (!burstMap.has(img.burst_id)) burstMap.set(img.burst_id, []);
      burstMap.get(img.burst_id).push(img);
    }
    const MOCK_BURSTS = [...burstMap.entries()]
      .filter(([, images]) => images.length >= 2)
      .map(([burst_id, images]) => ({ burst_id, count: images.length, images }))
      .sort((a, b) => a.burst_id - b.burst_id);

    const MOCK_STATS = stats || {
      images: MOCK_IMAGES.length,
      libraries: MOCK_LIBRARIES.length,
      bursts: MOCK_BURSTS.length,
      by_verdict: {},
      ingest: { running: false },
    };

    const ORGANIZE_TOKENS = tokens.tokens && tokens.tokens.length
      ? tokens.tokens
      : [
          'date:YYYY','date:YYYY-MM','date:YYYY-MM-DD','date:YYYY/MM','date:YYYY/MM/DD',
          'camera:make','camera:model','camera:make_model','lens:model',
          'focal_bucket','orientation','iso_bucket','flash',
          'quality:verdict','quality:stars',
          'scene','object:class','content_type',
          'palette:temperature','palette:saturation',
          'gps:country','gps:city','event',
        ];

    // Face clusters: no API yet — keep empty. The Faces screen renders an
    // empty-state with the `snapgrade faces` hint.
    window.SG_DATA = {
      MOCK_IMAGES, MOCK_LIBRARIES, MOCK_BURSTS,
      MOCK_CLUSTERS: [], MOCK_STATS, ORGANIZE_TOKENS,
    };
  }

  // ── Public API used by screen components ───────────────────────────────────
  const ready = bootstrap().catch(err => {
    console.error('[SnapGrade] bootstrap failed:', err);
    const boot = document.getElementById('sg-boot');
    if (boot) {
      boot.className = 'err';
      const msg = boot.querySelector('.sg-boot-msg');
      if (msg) msg.textContent = `Couldn't reach the SnapGrade server — ${err.message}`;
    }
    throw err;
  });

  window.SG_API = {
    ready,

    async start(App) {
      try { await ready; } catch { return; }
      const boot = document.getElementById('sg-boot');
      if (boot) boot.remove();
      const root = ReactDOM.createRoot(document.getElementById('root'));
      root.render(React.createElement(App));
    },

    async refresh() {
      await bootstrap();
    },
    async refreshStats() {
      const s = await jget('/api/stats').catch(() => null);
      if (s) window.SG_DATA.MOCK_STATS = s;
      return s;
    },
    async pickFolder() {
      const r = await jpost('/api/select_folder');
      return r.paths || [];
    },
    ingest(folders, models) {
      return jpost('/api/ingest', { folders, models: models || [] });
    },
    listModels() { return jget('/api/models'); },
    downloadModel(name) { return jpost(`/api/models/${name}/download`); },
    syncLibrary(id) { return jpost(`/api/libraries/${id}/sync`); },
    removeLibrary(id) { return jdel(`/api/libraries/${id}`); },
    loadLibraryErrors(id) { return jget(`/api/libraries/${id}/errors`); },

    verdict(id, payload) { return jpost(`/api/images/${id}/verdict`, payload); },
    verdictBatch(imageIds, payload) { return jpost('/api/verdicts', { image_ids: imageIds, ...payload }); },
    xmp(id) { return jpost(`/api/images/${id}/xmp`); },
    reveal(id) { return jpost(`/api/images/${id}/reveal`); },

    organize(payload) { return jpost('/api/organize', payload); },
    reclassify(t) { return jpost('/api/reclassify', t); },

    loadImageMetrics(id) { return jget(`/api/images/${id}`); },
    regroup({ hamming = 10, seconds = 3 } = {}) {
      const qs = new URLSearchParams({ hamming, seconds });
      return jpost(`/api/group?${qs.toString()}`);
    },
    setBurstBest(burstId, imageId) {
      return jpatch(`/api/bursts/${burstId}/best`, { image_id: imageId });
    },
    runFaces({ incremental = false, threshold } = {}) {
      const prefs = window.SG_PREFS || {};
      const t = threshold ?? prefs.faceThreshold ?? 0.30;
      const qs = new URLSearchParams({ incremental: incremental ? 'true' : 'false', threshold: t });
      return jpost(`/api/faces/run?${qs.toString()}`);
    },
    loadClusters({ minSize } = {}) {
      const prefs = window.SG_PREFS || {};
      const m = minSize ?? prefs.faceMinSize ?? 5;
      return jget(`/api/faces/clusters?min_size=${m}`).then(r => r.items || []);
    },
    labelCluster(clusterId, label) {
      return jpost(`/api/faces/clusters/${clusterId}/label`, { label });
    },
    mergeClusters(into, from) {
      return jpost('/api/faces/clusters/merge', { into, from });
    },
    removeFace(faceId) {
      return jpost(`/api/faces/${faceId}/cluster`, { cluster_id: null });
    },
    reassignFace(faceId, clusterId) {
      return jpost(`/api/faces/${faceId}/cluster`, { cluster_id: clusterId });
    },
    previewClusters(threshold) {
      return jget(`/api/faces/clusters/preview?threshold=${threshold}`);
    },
    search(q, { k = 24, libraryId } = {}) {
      const qs = new URLSearchParams({ q, k });
      if (libraryId != null) qs.set('library_id', libraryId);
      return jget(`/api/search?${qs.toString()}`).then(r => r.items || []);
    },
    bestPhotoForCluster(clusterId) {
      return jget(`/api/faces/clusters/${clusterId}/best`);
    },
  };

  // ── Persisted UI preferences (face clustering thresholds, etc.) ────────────
  function loadPrefs() {
    try { return JSON.parse(localStorage.getItem('sg.prefs') || '{}'); }
    catch { return {}; }
  }
  window.SG_PREFS = { faceMinSize: 2, faceThreshold: 0.30, ...loadPrefs() };
  window.SG_API.savePrefs = (patch) => {
    window.SG_PREFS = { ...window.SG_PREFS, ...patch };
    localStorage.setItem('sg.prefs', JSON.stringify(window.SG_PREFS));
    return window.SG_PREFS;
  };
})();
