import React, { useEffect, useMemo, useState, useCallback } from "react";
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

function pad(n, w = 3) { return String(n ?? 0).padStart(w, "0"); }

function useStats(pollMs = 1500) {
  const [stats, setStats] = useState(null);
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
  return stats;
}

function Sidebar({ tab, setTab, stats }) {
  return html`
    <aside class="gutter">
      <div class="brand">Blur<em>·</em>Detector</div>
      <div class="brand-sub">A local culling apparatus</div>

      <nav class="nav">
        ${TABS.map(([k, label, n]) => html`
          <button key=${k} class=${tab === k ? "on" : ""} onClick=${() => setTab(k)}>
            <span class="n">${n}.</span><span>${label}</span>
          </button>
        `)}
      </nav>

      <div class="gutter-foot">
        <div class="row"><span>Frames</span><span class="num">${pad(stats?.images, 5)}</span></div>
        <div class="row"><span>Bursts</span><span class="num">${pad(stats?.bursts, 4)}</span></div>
        <div class="row"><span>Events</span><span class="num">${pad(stats?.events ?? 0, 3)}</span></div>
        ${stats?.ingest?.running && html`
          <div class="live">Ingest · ${stats.ingest.done}</div>`}
      </div>
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

function LibraryTab({ stats, refreshStats }) {
  const [folder, setFolder] = useState("");
  const [msg, setMsg] = useState("");

  async function ingest() {
    setMsg("starting…");
    try {
      await api(`/api/ingest?folder=${encodeURIComponent(folder)}`, { method: "POST" });
      setMsg("ingest underway");
    } catch (e) { setMsg(e.message); }
  }
  async function regroup() {
    setMsg("clustering bursts…");
    const r = await api("/api/group", { method: "POST", body: "{}" });
    setMsg(`${r.bursts} bursts assembled`);
    refreshStats?.();
  }

  return html`
    <div class="scroll">
      <section class="page">
        <p class="lede">${TAB_LEDE.library}</p>

        <div class="card" data-no="i.">
          <h2>Open a <em class="italic">roll</em>.</h2>
          <div class="sub">Ingest · scan · measure · catalogue</div>
          <div class="row-actions">
            <input class="input" placeholder="/Users/you/Pictures/2026-trip"
                   value=${folder} onChange=${(e) => setFolder(e.target.value)} />
            <button class="btn primary" onClick=${ingest}>Develop</button>
          </div>
          ${msg && html`<div class="toast">${msg}</div>`}
        </div>

        <div class="card" data-no="ii.">
          <h2>Cluster the <em class="italic">bursts</em>.</h2>
          <div class="sub">Perceptual hash · time window · best-of-burst pick</div>
          <button class="btn" onClick=${regroup}>Re-cluster</button>
        </div>

        ${stats && html`
          <div class="card" data-no="iii." style=${{ padding: 0 }}>
            <div style=${{ padding: "28px 32px 0" }}>
              <h2>State of the <em class="italic">library</em>.</h2>
              <div class="sub">Live counts · polled at 2hz</div>
            </div>
            <div class="statgrid">
              <div class="stat"><div class="v num"><em>${pad(stats.images, 4)}</em></div><div class="k">Frames</div></div>
              <div class="stat"><div class="v num">${pad(stats.bursts, 3)}</div><div class="k">Bursts</div></div>
              <div class="stat"><div class="v num">${pad(stats.keepers ?? 0, 3)}</div><div class="k">Keepers</div></div>
              <div class="stat"><div class="v num">${pad(stats.rejects ?? 0, 3)}</div><div class="k">Rejects</div></div>
            </div>
          </div>
        `}
      </section>
    </div>
  `;
}

function Thumb({ item, idx, onClick, selected }) {
  const cls = ["thumb", item.verdict || "", selected ? "sel" : ""].filter(Boolean).join(" ");
  return html`
    <button class=${cls} style=${{ animationDelay: `${Math.min(idx, 24) * 18}ms` }} onClick=${onClick}>
      ${item.is_best && html`<span class="best">Best</span>`}
      <img loading="lazy" src=${`/api/images/${item.id}/thumb?size=320`} />
      <div class="strip">
        <span class="no">№ ${pad(item.id, 4)}</span>
        <span class="stars">${"★".repeat(item.stars || 0)}${"·".repeat(5 - (item.stars || 0))}</span>
      </div>
    </button>
  `;
}

function DetailPanel({ image, onVerdict }) {
  if (!image) return html`
    <div class="detail">
      <div class="empty">
        <div class="display italic">No frame selected.</div>
        <div class="micro">Pick from the sheet at left</div>
      </div>
    </div>`;

  const verdicts = ["keeper", "review", "reject"];
  return html`
    <aside class="detail">
      <div class="preview-wrap">
        <div class="corners"></div>
        <div class="tl"></div>
        <div class="br"></div>
        <img src=${`/api/images/${image.id}/preview`} />
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

function TriageTab() {
  const [filter, setFilter] = useState("all");
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);

  const reload = useCallback(async () => {
    const q = filter === "all" ? "" : `?verdict=${filter}`;
    const r = await api(`/api/images${q}`);
    setItems(r.items);
  }, [filter]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    if (selectedId == null) { setDetail(null); return; }
    api(`/api/images/${selectedId}`).then(setDetail).catch(() => {});
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
  };

  useEffect(() => {
    function key(e) {
      if (!items.length) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      const idx = items.findIndex((x) => x.id === selectedId);
      if (e.key === "j" || e.key === "ArrowRight") setSelectedId(items[Math.min(idx + 1, items.length - 1)]?.id);
      if (e.key === "k" || e.key === "ArrowLeft")  setSelectedId(items[Math.max(idx - 1, 0)]?.id);
      if (e.key === "x") updateVerdict("reject");
      if (e.key === "z") updateVerdict("keeper");
      if (e.key === "c") updateVerdict("review");
      if ("12345".includes(e.key)) updateVerdict(null, parseInt(e.key));
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [items, selectedId]);

  const filters = ["all", "keeper", "review", "reject"];
  return html`
    <div class="triage">
      <div class="filmstrip">
        <div class="filterbar">
          ${filters.map((f) => html`
            <button key=${f} class=${`chip ${filter === f ? "on" : ""}`} onClick=${() => setFilter(f)}>${f}</button>
          `)}
          <div class="keys">
            <kbd>J</kbd><kbd>K</kbd> navigate &nbsp;·&nbsp;
            <kbd>Z</kbd> keep &nbsp;·&nbsp;
            <kbd>C</kbd> review &nbsp;·&nbsp;
            <kbd>X</kbd> reject &nbsp;·&nbsp;
            <kbd>1</kbd>—<kbd>5</kbd> stars
          </div>
        </div>
        <div class="grid scroll">
          ${items.map((it, i) => html`
            <${Thumb} key=${it.id} item=${it} idx=${i} selected=${selectedId === it.id} onClick=${() => setSelectedId(it.id)} />
          `)}
          ${!items.length && html`
            <div style=${{ gridColumn: "1/-1", textAlign: "center", padding: "80px 20px", color: "var(--mute)" }}>
              <div class="display italic" style=${{ fontSize: "32px", color: "var(--bone-dim)" }}>The sheet is blank.</div>
              <div class="micro" style=${{ marginTop: "10px" }}>Develop a roll from the library tab</div>
            </div>`}
        </div>
      </div>
      <${DetailPanel} image=${detail} onVerdict=${updateVerdict} />
    </div>
  `;
}

function OrganizeTab() {
  const [tokens, setTokens] = useState([]);
  const [levels, setLevels] = useState(["date:YYYY", "camera:model", "quality:verdict"]);
  const [root, setRoot] = useState("");
  const [scope, setScope] = useState("");
  const [mode, setMode] = useState("symlink");
  const [preview, setPreview] = useState(null);

  useEffect(() => { api("/api/tokens").then((r) => setTokens(r.tokens)); }, []);

  function setLevel(i, v) { setLevels((xs) => xs.map((x, j) => j === i ? v : x)); }
  function addLevel() { setLevels((xs) => [...xs, tokens[0] || "date:YYYY"]); }
  function removeLevel(i) { setLevels((xs) => xs.filter((_, j) => j !== i)); }

  async function run(apply) {
    const body = { root, levels, mode, apply, scope: scope || null };
    const r = await api("/api/organize", { method: "POST", body: JSON.stringify(body) });
    setPreview(r);
  }

  return html`
    <div class="scroll">
      <section class="page">
        <p class="lede">${TAB_LEDE.organize}</p>

        <div class="card" data-no="i.">
          <h2>Destination &amp; <em class="italic">scope</em>.</h2>
          <div class="sub">Where the tree is rooted · which frames are included</div>
          <div class="field">
            <label>Destination root</label>
            <input class="input" value=${root} onChange=${(e) => setRoot(e.target.value)}
                   placeholder="/Users/you/Pictures/Organized" />
          </div>
          <div class="field" style=${{ marginBottom: 0 }}>
            <label>Scope · optional</label>
            <input class="input" value=${scope} onChange=${(e) => setScope(e.target.value)}
                   placeholder="restrict to this folder" />
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
            <button class="btn primary" onClick=${() => run(true)}>Apply</button>
          </div>

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

function App() {
  const [tab, setTab] = useState("library");
  const stats = useStats(2000);
  let pane;
  if (tab === "library")       pane = html`<${LibraryTab} stats=${stats} />`;
  else if (tab === "triage")   pane = html`<${TriageTab} />`;
  else if (tab === "organize") pane = html`<${OrganizeTab} />`;
  else                         pane = html`<${SettingsTab} />`;
  return html`
    <div class="shell">
      <${Sidebar} tab=${tab} setTab=${setTab} stats=${stats} />
      <main>
        <${TopBar} tab=${tab} frameNo=${stats?.images} />
        ${pane}
      </main>
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
