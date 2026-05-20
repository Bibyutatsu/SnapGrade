import React, { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { createRoot } from "react-dom/client";
import htm from "htm";

const html = htm.bind(React.createElement);
const API = "";

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

const TABS = [
  ["library",  "Library",   "I"],
  ["triage",   "Triage",    "II"],
  ["organize", "Organize",  "III"],
  ["settings", "Settings",  "IV"],
];

const TAB_TITLES = {
  library:  ["The", "Library"],
  triage:   ["The", "Contact Sheet"],
  organize: ["The", "Hierarchy"],
  settings: ["The", "Darkroom"],
};

const TAB_LEDE = {
  library:  "Point the lens at a folder. Frames are read, measured, and filed — nothing is moved, nothing is altered.",
  triage:   "Mark with the chinagraph. Keep what sings, strike what doesn't. The negatives remain untouched.",
  organize: "Compose the shelf. Levels collapse into a tree; preview before anything is written.",
  settings: "Tune the chemistry. Sharper acceptance, stricter rejection — recalibrate the whole library on a verdict.",
};

const MODEL_INFO = {
  scene:       { label: "Scene classifier",    note: "Places365 — adds {scene} token" },
  subject_seg: { label: "Salient subject seg", note: "U²-Netp — better subject mask" },
  objects:     { label: "Object detector",     note: "YOLOv8n — COCO classes" },
  screendoc:   { label: "Screenshot / doc",    note: "Auto-rejects screenshots / receipts" },
};

function pad(n, w = 3) { return String(n ?? 0).padStart(w, "0"); }

// Small event bus: components fire .emit() after mutations so others refetch.
const bus = new EventTarget();
const emitChange = () => bus.dispatchEvent(new Event("change"));
function useBusEffect(fn, deps) {
  useEffect(() => {
    const handler = () => fn();
    bus.addEventListener("change", handler);
    return () => bus.removeEventListener("change", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

function useStats(pollMs = 2000) {
  const [stats, setStats] = useState(null);
  const refresh = useCallback(async () => {
    try { setStats(await api("/api/stats")); } catch {}
  }, []);
  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const s = await api("/api/stats");
        if (alive) setStats(s);
      } catch {}
      if (alive) setTimeout(tick, pollMs);
    }
    tick();
    return () => { alive = false; };
  }, [pollMs]);
  useBusEffect(() => { refresh(); }, [refresh]);
  return [stats, refresh];
}

function Sidebar({ tab, setTab, stats, collapsed, onToggle }) {
  return html`
    <aside class="gutter" style=${{ padding: collapsed ? "20px 0" : "28px 24px 20px", alignItems: collapsed ? "center" : "" }}>
      <button
        onClick=${onToggle}
        title=${collapsed ? "Expand sidebar" : "Collapse sidebar"}
        style=${{
          alignSelf: "flex-end",
          marginBottom: collapsed ? "24px" : "0",
          marginRight: collapsed ? "0" : "-8px",
          padding: "4px 8px",
          fontSize: "14px",
          color: "var(--mute)",
          lineHeight: "1",
          transition: "color .15s",
        }}
        onMouseOver=${(e) => e.currentTarget.style.color = "var(--bone)"}
        onMouseOut=${(e) => e.currentTarget.style.color = "var(--mute)"}
      >${collapsed ? "»" : "«"}</button>

      ${!collapsed && html`
        <div class="brand">Blur<em>·</em>Detector</div>
        <div class="brand-sub">A local culling apparatus</div>
      `}

      <nav class="nav" style=${{ width: "100%" }}>
        ${TABS.map(([k, label, n]) => html`
          <button
            key=${k}
            class=${tab === k ? "on" : ""}
            onClick=${() => setTab(k)}
            title=${collapsed ? label : ""}
            style=${{ justifyContent: collapsed ? "center" : "", paddingLeft: collapsed ? "0" : "", borderLeft: collapsed && tab === k ? "2px solid var(--rust)" : "" }}
          >
            <span class="n">${n}.</span>
            ${!collapsed && html`<span>${label}</span>`}
          </button>
        `)}
      </nav>

      ${!collapsed && html`
        <div class="gutter-foot">
          <div class="row"><span>Libraries</span><span class="num">${pad(stats?.libraries ?? 0, 3)}</span></div>
          <div class="row"><span>Frames</span><span class="num">${pad(stats?.images, 5)}</span></div>
          <div class="row"><span>Bursts</span><span class="num">${pad(stats?.bursts, 4)}</span></div>
          ${stats?.ingest?.running && html`
            <div class="live">Ingest · ${stats.ingest.folder?.split("/").pop() || ""}</div>
            ${(() => {
              const { done, total } = stats.ingest;
              const pct = total && total > 0 ? Math.min(100, Math.round(100 * done / total)) : null;
              return html`
                <div class="progress-track">
                  ${pct == null
                    ? html`<div class="progress-indeterminate"></div>`
                    : html`<div class="progress-fill" style=${{ width: pct + "%" }}></div>`}
                </div>
                <div class="progress-label">
                  <span>${done}${total ? ` / ${total}` : ""} frames</span>
                  <span>${pct == null ? "scanning" : pct + "%"}</span>
                </div>`;
            })()}
          `}
        </div>
      `}
    </aside>
  `;
}

function TopBar({ tab, frameNo }) {
  const [pre, post] = TAB_TITLES[tab];
  return html`
    <div class="topbar">
      <div>
        <div class="crumbs">Roll · ${tab.toUpperCase()} · ${new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</div>
        <div class="title">${pre} <em class="italic">${post}</em></div>
      </div>
      <div class="spacer"></div>
      ${frameNo != null && html`<div class="frame-no">№ ${pad(frameNo, 4)}</div>`}
    </div>
  `;
}

function ModelChecklist({ models, selected, setSelected, downloadState, onRefresh }) {
  const [downloading, setDownloading] = useState(null);
  const [customUrl, setCustomUrl] = useState({});

  async function download(name, urlOverride) {
    setDownloading(name);
    try {
      const qs = urlOverride ? `?url=${encodeURIComponent(urlOverride)}` : "";
      await api(`/api/models/${name}/download${qs}`, { method: "POST" });
    } catch (e) {
      alert(e.message);
    } finally {
      setDownloading(null);
      setTimeout(onRefresh, 1000);
    }
  }

  if (!models?.length) return null;
  const dlActive = downloadState?.running;
  return html`
    <div class="model-checklist">
      <div class="label">Optional models · weights live in ~/.blurdetector/models/</div>
      ${models.map((m) => {
        const info = MODEL_INFO[m.name] || { label: m.name, note: "" };
        const isOn = selected.includes(m.name);
        const hasUrl = !!m.download_url;
        const isDownloadingThis = dlActive && downloadState.model === m.name;
        return html`
          <div key=${m.name}>
            <label class=${m.available ? "" : "unavail"}>
              <input type="checkbox" checked=${isOn} disabled=${!m.available}
                     onChange=${(e) => {
                       if (e.target.checked) setSelected([...selected, m.name]);
                       else setSelected(selected.filter((n) => n !== m.name));
                     }} />
              <span>${info.label}</span>
              <span class="note">— ${m.available ? info.note : (isDownloadingThis ? "downloading…" : "no weights found")}</span>
              ${!m.available && !isDownloadingThis && html`
                <button class="chip" style=${{ marginLeft: "auto", padding: "3px 10px" }}
                        disabled=${dlActive}
                        onClick=${() => download(m.name, customUrl[m.name])}>
                  ${hasUrl ? "Download" : "Need URL"}
                </button>`}
            </label>
            ${isDownloadingThis && html`
              <div class="progress-track" style=${{ marginLeft: "28px", marginTop: "4px" }}>
                ${downloadState.total
                  ? html`<div class="progress-fill" style=${{ width: Math.min(100, 100 * downloadState.downloaded / downloadState.total) + "%" }}></div>`
                  : html`<div class="progress-indeterminate"></div>`}
              </div>`}
            ${!m.available && !hasUrl && !isDownloadingThis && html`
              <div style=${{ marginLeft: "28px", marginTop: "4px", display: "flex", gap: "6px" }}>
                <input class="input" style=${{ padding: "4px 8px", fontSize: "10px" }}
                       placeholder=${`paste URL or drop file at ~/.blurdetector/models/${m.filename || m.name}`}
                       value=${customUrl[m.name] || ""}
                       onChange=${(e) => setCustomUrl({ ...customUrl, [m.name]: e.target.value })} />
              </div>`}
          </div>
        `;
      })}
      ${downloadState?.error && html`
        <div class="toast" style=${{ color: "var(--safelight)" }}>Download error: ${downloadState.error}</div>`}
    </div>
  `;
}

function LibrariesCard({ libraries, models, refresh }) {
  const [confirmId, setConfirmId] = useState(null);
  const [runOpen, setRunOpen] = useState(null);
  const [runSel, setRunSel] = useState([]);

  async function remove(id) {
    await api(`/api/libraries/${id}`, { method: "DELETE" });
    setConfirmId(null);
    emitChange();
    refresh?.();
  }

  async function runMore(id) {
    await api(`/api/libraries/${id}/run_models`, {
      method: "POST",
      body: JSON.stringify({ models: runSel }),
    });
    setRunOpen(null); setRunSel([]);
    emitChange();
    refresh?.();
  }

  async function sync(id) {
    try {
      const r = await api(`/api/libraries/${id}/sync`, { method: "POST" });
      // Toast handled by parent emitting change → ingest progress shows in sidebar.
      emitChange();
    } catch (e) {
      alert(e.message);
    }
  }

  if (!libraries?.length) {
    return html`<div class="meta" style=${{ color: "var(--mute)", fontStyle: "italic", padding: "10px 0" }}>
      No libraries ingested yet. Open a roll above.
    </div>`;
  }

  return html`
    <div class="lib-list">
      ${libraries.map((lib) => {
        const v = lib.by_verdict || {};
        const runMap = lib.models_run || {};
        const pending = lib.models_pending || [];
        const remaining = (models || []).filter(m => m.available && !runMap[m.name] && !pending.includes(m.name));
        return html`
          <div class="lib-row" key=${lib.id}>
            <div>
              <div class="name">${lib.display_name || lib.root_path.split("/").pop()}</div>
              <div class="path">${lib.root_path}</div>
              <div class="counts">
                <span><b>${lib.image_count}</b>frames</span>
                <span style=${{ color: "var(--moss)" }}><b>${v.keeper || 0}</b>keep</span>
                <span style=${{ color: "var(--amber)" }}><b>${v.review || 0}</b>review</span>
                <span style=${{ color: "var(--safelight)" }}><b>${v.reject || 0}</b>reject</span>
              </div>
              <div class="model-chips">
                ${Object.keys(runMap).map(n => html`<span class="chip done" key=${n}>${n} ✓</span>`)}
                ${pending.map(n => html`<span class="chip pending" key=${n}>${n} ⋯</span>`)}
                ${remaining.length > 0 && runOpen !== lib.id && html`
                  <button class="chip" onClick=${() => { setRunOpen(lib.id); setRunSel([]); }}>+ run more</button>`}
              </div>
              ${runOpen === lib.id && html`
                <div style=${{ marginTop: "10px", padding: "10px", border: "1px dashed var(--hair-2)" }}>
                  ${remaining.map(m => html`
                    <label key=${m.name} style=${{ display: "block", fontSize: "11px", marginBottom: "4px" }}>
                      <input type="checkbox" checked=${runSel.includes(m.name)}
                             onChange=${(e) => {
                               if (e.target.checked) setRunSel([...runSel, m.name]);
                               else setRunSel(runSel.filter(n => n !== m.name));
                             }} />
                      &nbsp;${MODEL_INFO[m.name]?.label || m.name}
                    </label>`)}
                  <div style=${{ display: "flex", gap: "8px", marginTop: "8px" }}>
                    <button class="btn ghost" style=${{ padding: "5px 12px", fontSize: "9px" }}
                            onClick=${() => { setRunOpen(null); setRunSel([]); }}>cancel</button>
                    <button class="btn primary" style=${{ padding: "5px 12px", fontSize: "9px" }}
                            disabled=${runSel.length === 0}
                            onClick=${() => runMore(lib.id)}>Run</button>
                  </div>
                </div>`}
            </div>
            <div class="actions">
              <button class="btn ghost" onClick=${() => sync(lib.id)} title="Re-scan folder: add new files, remove missing, re-run same models">Sync</button>
              <button class="btn danger" onClick=${() => setConfirmId(lib.id)}>Remove</button>
            </div>
            ${confirmId === lib.id && html`
              <div class="modal-overlay" onClick=${() => setConfirmId(null)}>
                <div class="modal-box" onClick=${(e) => e.stopPropagation()}>
                  <h3>Remove from catalog</h3>
                  <p>
                    This unlinks <b>${lib.image_count}</b> images and their verdicts from the catalog.
                    <br/>Files on disk are <b>not</b> deleted.
                  </p>
                  <div class="actions">
                    <button class="btn ghost" onClick=${() => setConfirmId(null)}>Cancel</button>
                    <button class="btn danger" onClick=${() => remove(lib.id)}>Remove</button>
                  </div>
                </div>
              </div>`}
          </div>
        `;
      })}
    </div>
  `;
}

function LibraryTab({ stats, refreshStats }) {
  const [folder, setFolder] = useState("");
  const [msg, setMsg] = useState("");
  const [models, setModels] = useState([]);
  const [selectedModels, setSelectedModels] = useState([]);
  const [libraries, setLibraries] = useState([]);
  const [downloadState, setDownloadState] = useState({ running: false });

  const loadLibs = useCallback(async () => {
    try {
      const r = await api("/api/libraries");
      setLibraries(r.items);
    } catch {}
  }, []);

  const loadModels = useCallback(async () => {
    try {
      const r = await api("/api/models");
      setModels(r.models || []);
      setDownloadState(r.download_state || { running: false });
    } catch {}
  }, []);

  useEffect(() => { loadLibs(); loadModels(); }, [loadLibs, loadModels]);
  useBusEffect(() => { loadLibs(); loadModels(); }, [loadLibs, loadModels]);
  useEffect(() => {
    // While ingest or a model download is running, the cards need to refresh.
    if (stats?.ingest?.running || downloadState?.running) {
      const t = setInterval(() => { loadLibs(); loadModels(); }, 1500);
      return () => clearInterval(t);
    }
  }, [stats?.ingest?.running, downloadState?.running, loadLibs, loadModels]);

  async function selectFolder() {
    setMsg("");
    try {
      const r = await api("/api/select_folder", { method: "POST" });
      if (r.path) setFolder(r.path);
    } catch (e) {
      setMsg("Failed to open folder picker: " + e.message);
    }
  }

  async function ingest() {
    if (!folder.trim()) { setMsg("Choose a folder first."); return; }
    setMsg("starting…");
    try {
      const qs = new URLSearchParams({ folder, models: selectedModels.join(",") });
      await api(`/api/ingest?${qs.toString()}`, { method: "POST" });
      setMsg("ingest underway");
      emitChange();
    } catch (e) { setMsg(e.message); }
  }

  const canIngest = folder.trim().length > 0 && !stats?.ingest?.running;

  return html`
    <div class="scroll">
      <section class="page">
        <p class="lede">${TAB_LEDE.library}</p>

        <div class="card" data-no="i.">
          <h2>Open a <em class="italic">roll</em>.</h2>
          <div class="sub">Ingest · scan · measure · catalogue</div>
          <div class="row-actions">
            <div class=${`folder-display ${folder ? "" : "empty"}`}>${folder || "no folder selected"}</div>
            <button class="btn ghost" onClick=${selectFolder}>Choose folder…</button>
            <button class="btn primary" disabled=${!canIngest} onClick=${ingest}>Develop</button>
          </div>
          <${ModelChecklist} models=${models} selected=${selectedModels} setSelected=${setSelectedModels}
                             downloadState=${downloadState} onRefresh=${loadModels} />
          ${msg && html`<div class="toast">${msg}</div>`}
        </div>

        <div class="card" data-no="ii.">
          <h2>Your <em class="italic">libraries</em>.</h2>
          <div class="sub">Each folder is tracked independently · remove without touching disk</div>
          <${LibrariesCard} libraries=${libraries} models=${models} refresh=${loadLibs} />
        </div>

        ${stats && html`
          <div class="card" data-no="iii." style=${{ padding: 0 }}>
            <div style=${{ padding: "28px 32px 0" }}>
              <h2>State of the <em class="italic">library</em>.</h2>
              <div class="sub">Live counts</div>
            </div>
            <div class="statgrid" style=${{ gridTemplateColumns: "repeat(6, 1fr)" }}>
              <div class="stat" style=${{ borderRight: "1px solid var(--hair)" }}><div class="v num"><em>${pad(stats.libraries ?? 0, 3)}</em></div><div class="k">Libraries</div></div>
              <div class="stat" style=${{ borderRight: "1px solid var(--hair)" }}><div class="v num">${pad(stats.images, 5)}</div><div class="k">Frames</div></div>
              <div class="stat" style=${{ borderRight: "1px solid var(--hair)" }}><div class="v num">${pad(stats.bursts ?? 0, 3)}</div><div class="k">Bursts</div></div>
              <div class="stat" style=${{ borderRight: "1px solid var(--hair)" }}><div class="v num" style=${{ color: "var(--moss)" }}>${pad(stats.by_verdict?.keeper ?? 0, 4)}</div><div class="k">Keepers</div></div>
              <div class="stat" style=${{ borderRight: "1px solid var(--hair)" }}><div class="v num" style=${{ color: "var(--amber)" }}>${pad(stats.by_verdict?.review ?? 0, 4)}</div><div class="k">Reviews</div></div>
              <div class="stat" style=${{ borderRight: "0" }}><div class="v num" style=${{ color: "var(--safelight)" }}>${pad(stats.by_verdict?.reject ?? 0, 4)}</div><div class="k">Rejects</div></div>
            </div>
          </div>
        `}
      </section>
    </div>
  `;
}

function Thumb({ item, idx, onClick, onDoubleClick, selected }) {
  const cls = ["thumb", item.verdict || "", selected ? "sel" : ""].filter(Boolean).join(" ");
  return html`
    <button class=${cls} style=${{ animationDelay: `${Math.min(idx, 24) * 18}ms` }} onClick=${onClick} onDoubleClick=${onDoubleClick}>
      ${item.is_best && html`<span class="best">Best</span>`}
      <img loading="lazy" src=${`/api/images/${item.id}/thumb?size=320`} />
      <div class="strip">
        <span class="no">№ ${pad(item.id, 4)}</span>
        <span class="stars">${"★".repeat(item.stars || 0)}${"·".repeat(5 - (item.stars || 0))}</span>
      </div>
    </button>
  `;
}

function DetailPanel({ image, onVerdict, onOpenLightbox }) {
  if (!image) return html`
    <div class="detail">
      <div class="empty">
        <div class="display italic">No frame selected.</div>
        <div class="micro">Pick from the sheet at left</div>
      </div>
    </div>`;

  const verdicts = ["keeper", "review", "reject"];
  const [xmpMsg, setXmpMsg] = useState("");
  const [showBboxes, setShowBboxes] = useState(true);

  const subjects = image.metrics?.subjects || [];
  const decoded = image.metrics?.decoded_size; // [w, h] of the analyzed image

  function bboxStyle(s) {
    if (!decoded || !s.bbox) return { display: "none" };
    const [dw, dh] = decoded;
    const [x, y, w, h] = s.bbox;
    return {
      position: "absolute",
      left:  (100 * x / dw) + "%",
      top:   (100 * y / dh) + "%",
      width: (100 * w / dw) + "%",
      height:(100 * h / dh) + "%",
      border: `2px solid ${s.is_primary ? "var(--rust)" : "var(--mute)"}`,
      pointerEvents: "none",
      boxSizing: "border-box",
    };
  }

  async function writeXmp() {
    setXmpMsg("writing...");
    try {
      await api(`/api/images/${image.id}/xmp`, { method: "POST" });
      setXmpMsg("XMP sidecar written!");
      setTimeout(() => setXmpMsg(""), 3000);
    } catch (e) {
      setXmpMsg("Error: " + e.message);
    }
  }

  return html`
    <aside class="detail">
      <div class="preview-wrap" style=${{ cursor: "zoom-in", position: "relative" }} onClick=${onOpenLightbox}>
        <div class="corners"></div>
        <div class="tl"></div>
        <div class="br"></div>
        <img src=${`/api/images/${image.id}/preview`} />
        ${showBboxes && subjects.map((s, i) => html`
          <div key=${i} style=${bboxStyle(s)}>
            <span style=${{
              position: "absolute", top: "-18px", left: "0",
              fontSize: "9px", letterSpacing: "0.18em", textTransform: "uppercase",
              padding: "1px 6px",
              background: s.is_primary ? "var(--rust)" : "var(--mute)",
              color: "var(--ink)",
            }}>${s.is_primary ? "subj" : s.kind}${s.confidence ? ` ${(s.confidence*100|0)}` : ""}</span>
          </div>
        `)}
      </div>
      <div style=${{ padding: "4px 24px", display: "flex", justifyContent: "flex-end", borderBottom: "1px solid var(--hair)" }}>
        <label class="micro" style=${{ cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}>
          <input type="checkbox" checked=${showBboxes} onChange=${(e) => setShowBboxes(e.target.checked)} />
          subject bboxes
        </label>
      </div>
      <div class="body">
        <div class="path">${image.path}</div>

        <div>
          <div class="micro" style=${{ marginBottom: "8px" }}>Verdict</div>
          <div class="verdict-row">
            ${verdicts.map((v) => html`
              <button key=${v} class=${`v ${v} ${image.verdict === v ? "on" : ""}`} onClick=${() => onVerdict(v)}>${v}</button>
            `)}
          </div>
        </div>

        <div class="star-row">
          <span class="lbl">Stars</span>
          ${[1,2,3,4,5].map((s) => html`
            <button key=${s} class=${s <= (image.stars || 0) ? "on" : ""} onClick=${() => onVerdict(null, s)}>
              ${s <= (image.stars || 0) ? "★" : "☆"}
            </button>`)}
        </div>

        <div style=${{ marginTop: "10px", display: "flex", gap: "10px", alignItems: "center" }}>
          <button class="btn ghost" onClick=${writeXmp} style=${{ width: "100%", padding: "8px", fontSize: "10px" }}>Write XMP Sidecar</button>
          <button class="btn ghost" onClick=${onOpenLightbox} style=${{ padding: "8px 14px", fontSize: "10px" }}>Full ⤢</button>
        </div>
        ${xmpMsg && html`<div class="toast" style=${{ marginTop: "8px" }}>${xmpMsg}</div>`}

        ${(image.reasons || []).length > 0 && html`
          <div class="reasons">${image.reasons.join(" · ")}</div>`}

        ${image.metrics && html`
          <details>
            <summary>Metrics ledger</summary>
            <pre>${JSON.stringify(image.metrics, null, 2)}</pre>
          </details>`}
      </div>
    </aside>
  `;
}

function Lightbox({ image, onClose, onVerdict, onPrev, onNext }) {
  const [showBboxes, setShowBboxes] = useState(true);

  useEffect(() => {
    function key(e) {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft" || e.key === "k") onPrev();
      if (e.key === "ArrowRight" || e.key === "j") onNext();
      if (e.key === "z") onVerdict("keeper");
      if (e.key === "c") onVerdict("review");
      if (e.key === "x") onVerdict("reject");
      if ("12345".includes(e.key)) onVerdict(null, parseInt(e.key));
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose, onPrev, onNext, onVerdict]);

  if (!image) return null;

  const subjects = image.metrics?.subjects || [];
  const decoded  = image.metrics?.decoded_size;

  function bboxStyle(s) {
    if (!decoded || !s.bbox) return { display: "none" };
    const [dw, dh] = decoded;
    const [x, y, w, h] = s.bbox;
    return {
      position: "absolute",
      left:   (100 * x / dw) + "%",
      top:    (100 * y / dh) + "%",
      width:  (100 * w / dw) + "%",
      height: (100 * h / dh) + "%",
      border: `2px solid ${s.is_primary ? "var(--rust)" : "var(--mute)"}`,
      pointerEvents: "none",
      boxSizing: "border-box",
    };
  }

  return html`
    <div class="lightbox" onClick=${onClose}>
      <button class="lightbox-close" onClick=${onClose}>✕</button>
      <button class="lightbox-nav prev" onClick=${(e) => { e.stopPropagation(); onPrev(); }}>‹</button>
      <button class="lightbox-nav next" onClick=${(e) => { e.stopPropagation(); onNext(); }}>›</button>

      <div class="lightbox-content" onClick=${(e) => e.stopPropagation()}>
        <div style=${{ position: "relative", display: "inline-block", lineHeight: 0 }}>
          <img src=${`/api/images/${image.id}/preview`} onClick=${onClose} />
          ${showBboxes && subjects.map((s, i) => html`
            <div key=${i} style=${bboxStyle(s)}>
              <span style=${{
                position: "absolute", top: "-20px", left: "0",
                fontSize: "9px", letterSpacing: "0.18em", textTransform: "uppercase",
                padding: "1px 6px",
                background: s.is_primary ? "var(--rust)" : "var(--mute)",
                color: "var(--ink)",
                whiteSpace: "nowrap",
              }}>${s.is_primary ? "subj" : s.kind}${s.confidence ? ` ${(s.confidence * 100 | 0)}` : ""}</span>
            </div>
          `)}
        </div>

        <div class="lightbox-meta">
          <h4>№ ${pad(image.id, 4)}</h4>
          <p style=${{ wordBreak: "break-all", fontSize: "11px" }}>${image.path}</p>
          <p style=${{ marginTop: "6px" }}>
            ${image.camera_model || "Unknown Camera"} · f/${image.f_number || "?"} · ${image.exposure_time ? `1/${Math.round(1/image.exposure_time)}s` : "?"} · ISO ${image.iso || "?"}
          </p>
          <div class="star-row" style=${{ justifyContent: "center", marginTop: "10px" }}>
            ${[1,2,3,4,5].map((s) => html`
              <button key=${s} class=${s <= (image.stars || 0) ? "on" : ""} onClick=${() => onVerdict(null, s)}>
                ${s <= (image.stars || 0) ? "★" : "☆"}
              </button>`)}
          </div>
          <div style=${{ marginTop: "12px", display: "flex", gap: "8px", justifyContent: "center" }}>
            <button class=${`btn ghost ${image.verdict === "keeper" ? "primary" : ""}`} onClick=${() => onVerdict("keeper")}>Keeper</button>
            <button class=${`btn ghost`} style=${image.verdict === "review" ? {borderColor: "var(--amber)", color: "var(--amber)"} : {}} onClick=${() => onVerdict("review")}>Review</button>
            <button class=${`btn ghost ${image.verdict === "reject" ? "danger" : ""}`} onClick=${() => onVerdict("reject")}>Reject</button>
          </div>
          ${subjects.length > 0 && html`
            <div style=${{ marginTop: "10px" }}>
              <label class="micro" style=${{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }}>
                <input type="checkbox" checked=${showBboxes} onChange=${(e) => setShowBboxes(e.target.checked)} />
                subject bboxes
              </label>
            </div>
          `}
        </div>
      </div>
    </div>
  `;
}

function TriageTab() {
  const [filter, setFilter] = useState("all");
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [libraries, setLibraries] = useState([]);
  const [activeLib, setActiveLib] = useState(null); // null = all
  const [bursts, setBursts] = useState([]);
  const [selectedBurst, setSelectedBurst] = useState("");
  const [isLightboxOpen, setIsLightboxOpen] = useState(false);

  const loadLibraries = useCallback(async () => {
    try {
      const r = await api("/api/libraries");
      setLibraries(r.items);
    } catch {}
  }, []);

  const loadBursts = useCallback(async () => {
    try {
      const r = await api("/api/bursts");
      setBursts(r.items);
    } catch {}
  }, []);

  const reload = useCallback(async () => {
    const qs = new URLSearchParams();
    if (filter !== "all") qs.set("verdict", filter);
    if (activeLib !== null) qs.set("library_id", activeLib);
    if (selectedBurst) qs.set("burst", selectedBurst);
    const q = qs.toString();
    const r = await api(`/api/images${q ? "?" + q : ""}`);
    setItems(r.items);
  }, [filter, activeLib, selectedBurst]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => { loadLibraries(); loadBursts(); }, [loadLibraries, loadBursts]);
  useBusEffect(() => { loadLibraries(); reload(); }, [loadLibraries, reload]);

  useEffect(() => {
    if (selectedId == null) { setDetail(null); return; }
    api(`/api/images/${selectedId}`).then(setDetail).catch(() => {});
  }, [selectedId]);

  useEffect(() => {
    if (selectedId) {
      const el = document.querySelector(".thumb.sel");
      if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selectedId]);

  const updateVerdict = async (verdict, stars) => {
    if (selectedId == null) return;
    const payload = {};
    if (verdict) payload.verdict = verdict;
    if (stars != null) payload.stars = stars;
    await api(`/api/images/${selectedId}/verdict`, { method: "POST", body: JSON.stringify(payload) });
    const fresh = await api(`/api/images/${selectedId}`);
    setDetail(fresh);
    setItems((xs) => xs.map((x) => x.id === selectedId ? { ...x, ...payload } : x));
    emitChange();  // notify stats + libraries to refetch
  };

  const goPrev = useCallback(() => {
    const idx = items.findIndex((x) => x.id === selectedId);
    if (idx > 0) setSelectedId(items[idx - 1].id);
  }, [items, selectedId]);

  const goNext = useCallback(() => {
    const idx = items.findIndex((x) => x.id === selectedId);
    if (idx < items.length - 1) setSelectedId(items[idx + 1].id);
  }, [items, selectedId]);

  useEffect(() => {
    function key(e) {
      if (!items.length) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      if (e.key === "j" || e.key === "ArrowRight") goNext();
      if (e.key === "k" || e.key === "ArrowLeft")  goPrev();
      if (e.key === "x") updateVerdict("reject");
      if (e.key === "z") updateVerdict("keeper");
      if (e.key === "c") updateVerdict("review");
      if ("12345".includes(e.key)) updateVerdict(null, parseInt(e.key));
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [items, selectedId, goNext, goPrev]);

  const regroupBursts = async () => {
    await api("/api/group", { method: "POST", body: "{}" });
    reload();
    loadBursts();
    emitChange();
  };

  // Per-active-library stats from the libraries endpoint (authoritative DB counts).
  const stripStats = useMemo(() => {
    if (activeLib === null) {
      let img = 0, k = 0, r = 0, x = 0;
      for (const l of libraries) {
        img += l.image_count;
        k += l.by_verdict?.keeper || 0;
        r += l.by_verdict?.review || 0;
        x += l.by_verdict?.reject || 0;
      }
      return { total: img, keepers: k, reviews: r, rejects: x, name: "All folders" };
    }
    const lib = libraries.find((l) => l.id === activeLib);
    if (!lib) return { total: 0, keepers: 0, reviews: 0, rejects: 0, name: "—" };
    const v = lib.by_verdict || {};
    return {
      total: lib.image_count,
      keepers: v.keeper || 0,
      reviews: v.review || 0,
      rejects: v.reject || 0,
      name: lib.display_name || lib.root_path.split("/").pop(),
    };
  }, [libraries, activeLib]);

  const filters = ["all", "keeper", "review", "reject"];
  return html`
    <div class="triage">
      <div class="lib-rail">
        <div class="head">Folders</div>
        <button class=${`node ${activeLib === null ? "on" : ""}`} onClick=${() => { setActiveLib(null); setSelectedId(null); }}>
          <span class="name">All</span>
          <span class="meta-line">${libraries.reduce((a,l)=>a+l.image_count,0)} frames · ${libraries.length} libraries</span>
        </button>
        ${libraries.map((l) => html`
          <button key=${l.id} class=${`node ${activeLib === l.id ? "on" : ""}`}
                  onClick=${() => { setActiveLib(l.id); setSelectedId(null); }}>
            <span class="name">${l.display_name || l.root_path.split("/").pop()}</span>
            <span class="meta-line">${l.image_count} frames · ${(l.by_verdict?.keeper || 0)} keep · ${(l.by_verdict?.reject || 0)} reject</span>
          </button>
        `)}
      </div>

      <div class="filmstrip">
        <div class="stat-strip">
          <span><b>${stripStats.name}</b></span>
          <span><b>${stripStats.total}</b>frames</span>
          <span class="k"><b>${stripStats.keepers}</b>keepers</span>
          <span class="r"><b>${stripStats.reviews}</b>reviews</span>
          <span class="x"><b>${stripStats.rejects}</b>rejects</span>
        </div>
        <div class="filterbar" style=${{ flexWrap: "wrap", gap: "12px" }}>
          ${filters.map((f) => html`
            <button key=${f} class=${`chip ${filter === f ? "on" : ""}`} onClick=${() => setFilter(f)}>${f}</button>
          `)}

          <select class="select" style=${{ width: "auto", padding: "6px 12px", fontSize: "11px", height: "auto" }}
                  value=${selectedBurst} onChange=${(e) => { setSelectedBurst(e.target.value); setSelectedId(null); }}>
            <option value="">All Bursts</option>
            ${bursts.map((b) => html`<option key=${b.burst_id} value=${b.burst_id}>Burst #${b.burst_id} (${b.count} frames)</option>`)}
          </select>

          <button class="btn ghost" style=${{ padding: "6px 12px", fontSize: "10px" }} onClick=${regroupBursts}>Re-cluster Bursts</button>

          <div class="keys" style=${{ marginLeft: "auto" }}>
            <kbd>J</kbd><kbd>K</kbd> navigate ${" · "}
            <kbd>Z</kbd> keep ${" · "}
            <kbd>C</kbd> review ${" · "}
            <kbd>X</kbd> reject ${" · "}
            <kbd>1</kbd>—<kbd>5</kbd> stars
          </div>
        </div>
        <div class="grid scroll">
          ${items.map((it, i) => html`
            <${Thumb} key=${it.id} item=${it} idx=${i} selected=${selectedId === it.id}
                       onClick=${() => setSelectedId(it.id)}
                       onDoubleClick=${() => { setSelectedId(it.id); setIsLightboxOpen(true); }} />
          `)}
          ${!items.length && html`
            <div style=${{ gridColumn: "1/-1", textAlign: "center", padding: "80px 20px", color: "var(--mute)" }}>
              <div class="display italic" style=${{ fontSize: "32px", color: "var(--bone-dim)" }}>The sheet is blank.</div>
              <div class="micro" style=${{ marginTop: "10px" }}>${activeLib === null ? "Develop a roll from the library tab" : "This folder has no frames matching the filter"}</div>
            </div>`}
        </div>
      </div>
      <${DetailPanel} image=${detail} onVerdict=${updateVerdict} onOpenLightbox=${() => setIsLightboxOpen(true)} />

      ${isLightboxOpen && detail && html`
        <${Lightbox} image=${detail} onClose=${() => setIsLightboxOpen(false)} onVerdict=${updateVerdict} onPrev=${goPrev} onNext=${goNext} />
      `}
    </div>
  `;
}

function OrganizeTab() {
  const [tokens, setTokens] = useState([]);
  const [libraries, setLibraries] = useState([]);
  const [levels, setLevels] = useState(["date:YYYY", "camera:model", "quality:verdict"]);
  const [root, setRoot] = useState("");
  const [scopeLib, setScopeLib] = useState("");  // library_id string, "" = all
  const [mode, setMode] = useState("symlink");
  const [preview, setPreview] = useState(null);
  const [inPlaceState, setInPlaceState] = useState(null); // { libName }
  const [confirmText, setConfirmText] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => { api("/api/tokens").then((r) => setTokens(r.tokens)); }, []);
  useEffect(() => { api("/api/libraries").then((r) => setLibraries(r.items)); }, []);

  function setLevel(i, v) { setLevels((xs) => xs.map((x, j) => j === i ? v : x)); }
  function addLevel() { setLevels((xs) => [...xs, tokens[0] || "date:YYYY"]); }
  function removeLevel(i) { setLevels((xs) => xs.filter((_, j) => j !== i)); }

  async function chooseRoot() {
    try {
      const r = await api("/api/select_folder", { method: "POST" });
      if (r.path) setRoot(r.path);
    } catch (e) { setMsg(e.message); }
  }

  async function run(apply) {
    setMsg("");
    try {
      const body = {
        root: root || null,
        levels,
        mode,
        apply,
        library_id: scopeLib ? Number(scopeLib) : null,
      };
      const r = await api("/api/organize", { method: "POST", body: JSON.stringify(body) });
      setPreview(r);
    } catch (e) { setMsg(e.message); }
  }

  function openInPlace() {
    if (!scopeLib) { setMsg("Pick a library to reorganize in-place."); return; }
    const lib = libraries.find((l) => String(l.id) === String(scopeLib));
    if (!lib) return;
    setInPlaceState({ libId: lib.id, libName: lib.display_name || lib.root_path.split("/").pop() });
    setConfirmText("");
  }

  async function applyInPlace() {
    if (!inPlaceState || confirmText !== inPlaceState.libName) return;
    setMsg("");
    try {
      const body = {
        root: null,
        levels,
        mode: "move",
        apply: true,
        library_id: inPlaceState.libId,
        in_place: true,
        confirm: inPlaceState.libName,
      };
      const r = await api("/api/organize", { method: "POST", body: JSON.stringify(body) });
      setPreview(r);
      setInPlaceState(null);
      setConfirmText("");
      emitChange();
    } catch (e) { setMsg(e.message); }
  }

  return html`
    <div class="scroll">
      <section class="page">
        <p class="lede">${TAB_LEDE.organize}</p>

        <div class="card" data-no="i.">
          <h2>Destination &amp; <em class="italic">scope</em>.</h2>
          <div class="sub">Where the tree is rooted · which library to draw from</div>
          <div class="field">
            <label>Destination root</label>
            <div class="row-actions">
              <div class=${`folder-display ${root ? "" : "empty"}`}>${root || "no destination chosen"}</div>
              <button class="btn ghost" onClick=${chooseRoot}>Choose folder…</button>
            </div>
          </div>
          <div class="field" style=${{ marginBottom: 0 }}>
            <label>Scope · which library</label>
            <select class="select" value=${scopeLib} onChange=${(e) => setScopeLib(e.target.value)}>
              <option value="">All libraries</option>
              ${libraries.map((l) => html`<option key=${l.id} value=${l.id}>${l.display_name || l.root_path} (${l.image_count})</option>`)}
            </select>
          </div>
          <div style=${{ marginTop: "18px", display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <button class="btn danger" disabled=${!scopeLib} onClick=${openInPlace}>Reorganize In-Place…</button>
            <span class="meta" style=${{ color: "var(--mute)", alignSelf: "center" }}>
              In-place rewrites files inside the chosen library — destructive.
            </span>
          </div>
        </div>

        <div class="card" data-no="ii.">
          <h2>The <em class="italic">hierarchy</em>.</h2>
          <div class="sub">Each level becomes a directory · order matters</div>
          ${levels.map((lv, i) => html`
            <div class="level-row" key=${i}>
              <span class="idx">${i + 1}.</span>
              <select class="select" value=${lv} onChange=${(e) => setLevel(i, e.target.value)}>
                ${tokens.map((t) => html`<option key=${t} value=${t}>${t}</option>`)}
              </select>
              <button class="rm" title="remove" onClick=${() => removeLevel(i)}>✕</button>
            </div>`)}
          <div style=${{ marginTop: "14px" }}>
            <button class="chip" onClick=${addLevel}>+ add level</button>
          </div>
        </div>

        <div class="card" data-no="iii.">
          <h2>Write the <em class="italic">tree</em>.</h2>
          <div class="sub">Dry-run first · then commit when the preview reads true</div>
          <div style=${{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
            <div class="field" style=${{ marginBottom: 0, minWidth: "220px" }}>
              <label>Mode</label>
              <select class="select" value=${mode} onChange=${(e) => setMode(e.target.value)}>
                <option value="symlink">symlink · safe</option>
                <option value="hardlink">hardlink</option>
                <option value="copy">copy</option>
                <option value="move">move · destructive</option>
              </select>
            </div>
            <div style=${{ flex: 1 }}></div>
            <button class="btn ghost" onClick=${() => run(false)}>Dry-run</button>
            <button class="btn primary" disabled=${!root} onClick=${() => run(true)}>Apply</button>
          </div>
          ${msg && html`<div class="toast">${msg}</div>`}

          ${preview && html`
            <div class="preview-block">
              <div class="head">
                <span><b>${pad(preview.plan_size, 4)}</b> files</span>
                <span><b>${pad(preview.conflicts, 3)}</b> conflicts</span>
                <span><b>${pad(preview.written, 4)}</b> ${preview.applied ? "applied" : "would write"}</span>
              </div>
              <pre>${preview.preview.map((p) => html`<span>${p.source}\n  <span class="arrow">→</span> ${p.target}\n\n</span>`)}</pre>
            </div>`}
        </div>
      </section>

      ${inPlaceState && html`
        <div class="modal-overlay" onClick=${() => setInPlaceState(null)}>
          <div class="modal-box" onClick=${(e) => e.stopPropagation()}>
            <h3>Reorganize <em class="italic" style=${{ color: "var(--bone)" }}>${inPlaceState.libName}</em> in-place</h3>
            <p>
              This <b>moves</b> every frame inside the library according to the hierarchy above. Files on disk
              will be relocated. There is no undo. To confirm, type the library name below:
            </p>
            <input class="confirm-input" value=${confirmText}
                   onChange=${(e) => setConfirmText(e.target.value)}
                   placeholder=${inPlaceState.libName} autoFocus />
            <div class="actions">
              <button class="btn ghost" onClick=${() => setInPlaceState(null)}>Cancel</button>
              <button class="btn danger" disabled=${confirmText !== inPlaceState.libName}
                      onClick=${applyInPlace}>Apply in-place</button>
            </div>
          </div>
        </div>
      `}
    </div>
  `;
}

const SETTINGS_SPEC = [
  { key: "sharp_keeper",  kind: "slider", min: 0, max: 1, step: 0.01, label: "Sharpness — keeper floor", hint: "above this, a frame is sharp enough to keep" },
  { key: "sharp_reject",  kind: "slider", min: 0, max: 1, step: 0.01, label: "Sharpness — reject ceiling", hint: "below this, rejection is automatic" },
  { key: "horizon_warn_deg", kind: "slider", min: 0, max: 10, step: 0.5, label: "Horizon — warn at degrees", hint: "tilt threshold before flagging" },
  { key: "reject_closed_eyes",   kind: "toggle", label: "Reject closed eyes",     hint: "fail any frame with a closed-eye face" },
  { key: "accept_overexposed",   kind: "toggle", label: "Accept over-exposed",    hint: "keep blown highlights despite warning" },
  { key: "accept_underexposed",  kind: "toggle", label: "Accept under-exposed",   hint: "keep crushed shadows despite warning" },
];

function SettingsTab() {
  const [t, setT] = useState({
    sharp_keeper: 0.55, sharp_reject: 0.30,
    reject_closed_eyes: true, accept_overexposed: false, accept_underexposed: false,
    horizon_warn_deg: 3.0,
  });
  const [msg, setMsg] = useState("");

  async function apply() {
    const r = await api("/api/reclassify", { method: "POST", body: JSON.stringify(t) });
    setMsg(`Reclassified ${r.updated} frames.`);
    emitChange();
  }

  return html`
    <div class="scroll">
      <section class="page" style=${{ maxWidth: 760 }}>
        <p class="lede">${TAB_LEDE.settings}</p>

        <div class="card" data-no="i.">
          <h2>Decision <em class="italic">thresholds</em>.</h2>
          <div class="sub">Sliders and switches · the tunable surface of the engine</div>

          ${SETTINGS_SPEC.map((s) => s.kind === "slider" ? html`
            <div class="slider-row" key=${s.key}>
              <div class="lbl">${s.label}<small>${s.hint}</small></div>
              <input type="range" min=${s.min} max=${s.max} step=${s.step} value=${t[s.key]}
                     onChange=${(e) => setT({ ...t, [s.key]: parseFloat(e.target.value) })} />
              <div class="val">${Number(t[s.key]).toFixed(s.step < 1 ? 2 : 1)}</div>
            </div>
          ` : html`
            <div class="slider-row" key=${s.key}>
              <div class="lbl">${s.label}<small>${s.hint}</small></div>
              <div></div>
              <div style=${{ textAlign: "right" }}>
                <input type="checkbox" checked=${t[s.key]}
                       onChange=${(e) => setT({ ...t, [s.key]: e.target.checked })} />
              </div>
            </div>
          `)}

          <div style=${{ marginTop: "24px", display: "flex", gap: "12px", alignItems: "center" }}>
            <button class="btn primary" onClick=${apply}>Reclassify the library</button>
            ${msg && html`<div class="toast" style=${{ margin: 0 }}>${msg}</div>`}
          </div>
        </div>
      </section>
    </div>
  `;
}

const VALID_TABS = new Set(TABS.map(([k]) => k));

function App() {
  const [tab, setTab] = useState(() => {
    const saved = localStorage.getItem("bd_tab");
    return VALID_TABS.has(saved) ? saved : "library";
  });
  const setTabPersist = useCallback((t) => { setTab(t); localStorage.setItem("bd_tab", t); }, []);
  const [sidebarOpen, setSidebarOpen] = useState(() => localStorage.getItem("bd_sidebar") !== "0");
  const toggleSidebar = useCallback(() => setSidebarOpen(v => {
    const next = !v;
    localStorage.setItem("bd_sidebar", next ? "1" : "0");
    return next;
  }), []);
  const [stats, refreshStats] = useStats(2000);
  let pane;
  if (tab === "library")       pane = html`<${LibraryTab} stats=${stats} refreshStats=${refreshStats} />`;
  else if (tab === "triage")   pane = html`<${TriageTab} />`;
  else if (tab === "organize") pane = html`<${OrganizeTab} />`;
  else                         pane = html`<${SettingsTab} />`;
  return html`
    <div class="shell" style=${{ gridTemplateColumns: sidebarOpen ? "240px 1fr" : "48px 1fr" }}>
      <${Sidebar} tab=${tab} setTab=${setTabPersist} stats=${stats} collapsed=${!sidebarOpen} onToggle=${toggleSidebar} />
      <main>
        <${TopBar} tab=${tab} frameNo=${stats?.images} />
        ${pane}
      </main>
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
