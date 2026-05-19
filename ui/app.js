import React, { useEffect, useMemo, useState, useCallback } from "react";
import { createRoot } from "react-dom/client";
import htm from "htm";

const html = htm.bind(React.createElement);
const API = "";  // same-origin

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

const VERDICT_COLOR = {
  keeper: "border-emerald-500",
  review: "border-amber-400",
  reject: "border-rose-500",
};

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
  const tabs = [
    ["library", "Library"],
    ["triage", "Triage"],
    ["organize", "Organize"],
    ["settings", "Settings"],
  ];
  return html`
    <aside class="w-48 shrink-0 border-r border-zinc-800 p-4 flex flex-col gap-1">
      <h1 class="text-lg font-semibold mb-4">BlurDetector</h1>
      ${tabs.map(([k, label]) => html`
        <button
          key=${k}
          class=${`text-left px-3 py-2 rounded ${tab === k ? "bg-zinc-800" : "hover:bg-zinc-900"}`}
          onClick=${() => setTab(k)}
        >${label}</button>
      `)}
      ${stats && html`
        <div class="mt-auto pt-4 text-xs text-zinc-500">
          <div>${stats.images} images</div>
          <div>${stats.bursts} bursts</div>
          ${stats.ingest?.running && html`
            <div class="text-emerald-400 mt-2">
              Ingesting… ${stats.ingest.done}
            </div>`}
        </div>
      `}
    </aside>
  `;
}

function LibraryTab({ stats, refreshStats }) {
  const [folder, setFolder] = useState("");
  const [msg, setMsg] = useState("");

  async function ingest() {
    setMsg("starting…");
    try {
      await api(`/api/ingest?folder=${encodeURIComponent(folder)}`, { method: "POST" });
      setMsg("started");
    } catch (e) { setMsg(e.message); }
  }
  async function regroup() {
    setMsg("grouping…");
    const res = await api("/api/group", { method: "POST", body: "{}" });
    setMsg(`grouped ${res.bursts} bursts`);
    refreshStats?.();
  }

  return html`
    <section class="p-6 flex flex-col gap-6 max-w-2xl">
      <div>
        <h2 class="text-xl font-semibold mb-3">Ingest a folder</h2>
        <div class="flex gap-2">
          <input
            class="flex-1 bg-zinc-900 border border-zinc-800 rounded px-3 py-2 outline-none focus:border-zinc-600"
            placeholder="/Users/you/Pictures/2024-shoot"
            value=${folder}
            onChange=${(e) => setFolder(e.target.value)}
          />
          <button class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded" onClick=${ingest}>
            Ingest
          </button>
        </div>
        <p class="text-xs text-zinc-500 mt-2">${msg}</p>
      </div>
      <div>
        <h2 class="text-xl font-semibold mb-3">Burst grouping</h2>
        <button class="bg-zinc-800 hover:bg-zinc-700 px-4 py-2 rounded" onClick=${regroup}>
          Re-cluster bursts
        </button>
      </div>
      ${stats && html`
        <div class="mt-4 text-sm">
          <h3 class="font-semibold mb-2">Stats</h3>
          <pre class="bg-zinc-900 p-3 rounded text-xs overflow-auto">${JSON.stringify(stats, null, 2)}</pre>
        </div>
      `}
    </section>
  `;
}

function ThumbCard({ item, onClick, selected }) {
  const color = VERDICT_COLOR[item.verdict] || "border-zinc-700";
  return html`
    <button
      class=${`relative bg-zinc-900 rounded overflow-hidden border-2 ${color} ${selected ? "ring-2 ring-sky-400" : ""}`}
      onClick=${onClick}
    >
      <img loading="lazy" src=${`/api/images/${item.id}/thumb?size=320`} class="w-full h-40 object-cover" />
      <div class="absolute bottom-0 left-0 right-0 bg-black/60 text-[10px] px-1 py-0.5 flex justify-between">
        <span>${"★".repeat(item.stars || 0)}</span>
        ${item.is_best && html`<span class="text-emerald-400">BEST</span>`}
      </div>
    </button>
  `;
}

function DetailPanel({ image, onVerdict }) {
  if (!image) return html`<div class="p-6 text-zinc-500">Select an image.</div>`;
  return html`
    <div class="p-4 overflow-auto h-full">
      <img src=${`/api/images/${image.id}/preview`} class="w-full rounded mb-3" />
      <div class="space-y-2 text-sm">
        <div class="font-mono text-xs text-zinc-400 break-all">${image.path}</div>
        <div class="flex gap-2">
          ${["keeper", "review", "reject"].map((v) => html`
            <button
              key=${v}
              class=${`px-3 py-1 rounded text-xs ${image.verdict === v ? "bg-sky-600" : "bg-zinc-800 hover:bg-zinc-700"}`}
              onClick=${() => onVerdict(v)}
            >${v}</button>
          `)}
        </div>
        <div>
          <span class="text-zinc-500">Stars: </span>
          ${[1, 2, 3, 4, 5].map((s) => html`
            <button key=${s} class="px-1" onClick=${() => onVerdict(null, s)}>
              ${s <= (image.stars || 0) ? "★" : "☆"}
            </button>`)}
        </div>
        ${(image.reasons || []).length > 0 && html`
          <div class="text-amber-300 text-xs">${image.reasons.join(", ")}</div>`}
        ${image.metrics && html`
          <details class="text-xs">
            <summary class="cursor-pointer text-zinc-400">Metrics</summary>
            <pre class="mt-2 bg-zinc-900 p-2 rounded overflow-auto text-[10px]">${JSON.stringify(image.metrics, null, 2)}</pre>
          </details>`}
      </div>
    </div>
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
      const idx = items.findIndex((x) => x.id === selectedId);
      if (e.key === "j" || e.key === "ArrowRight") setSelectedId(items[Math.min(idx + 1, items.length - 1)]?.id);
      if (e.key === "k" || e.key === "ArrowLeft") setSelectedId(items[Math.max(idx - 1, 0)]?.id);
      if (e.key === "x") updateVerdict("reject");
      if (e.key === "z") updateVerdict("keeper");
      if (e.key === "c") updateVerdict("review");
      if ("12345".includes(e.key)) updateVerdict(null, parseInt(e.key));
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [items, selectedId]);

  return html`
    <section class="flex-1 flex min-h-0">
      <div class="flex-1 flex flex-col min-w-0">
        <div class="p-3 border-b border-zinc-800 flex gap-2">
          ${["all", "keeper", "review", "reject"].map((f) => html`
            <button
              key=${f}
              class=${`px-3 py-1 rounded text-xs ${filter === f ? "bg-zinc-700" : "bg-zinc-900 hover:bg-zinc-800"}`}
              onClick=${() => setFilter(f)}
            >${f}</button>`)}
          <span class="ml-auto text-xs text-zinc-500 self-center">
            j/k navigate · z=keep · c=review · x=reject · 1-5 stars
          </span>
        </div>
        <div class="flex-1 overflow-auto scrollbar-thin p-3 grid gap-2"
             style=${{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
          ${items.map((it) => html`
            <${ThumbCard} key=${it.id} item=${it} selected=${selectedId === it.id} onClick=${() => setSelectedId(it.id)} />
          `)}
        </div>
      </div>
      <div class="w-96 border-l border-zinc-800 shrink-0 overflow-y-auto">
        <${DetailPanel} image=${detail} onVerdict=${updateVerdict} />
      </div>
    </section>
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
    <section class="p-6 max-w-3xl space-y-4">
      <h2 class="text-xl font-semibold">Hierarchical organize</h2>
      <div class="space-y-2">
        <label class="block text-sm">Destination root</label>
        <input class="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2"
               value=${root} onChange=${(e) => setRoot(e.target.value)} placeholder="/Users/you/Pictures/Organized" />
        <label class="block text-sm">Scope (optional, restrict to this folder)</label>
        <input class="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2"
               value=${scope} onChange=${(e) => setScope(e.target.value)} placeholder="/Users/you/Pictures/2024-shoot" />
      </div>
      <div class="space-y-2">
        <div class="text-sm">Levels</div>
        ${levels.map((lv, i) => html`
          <div key=${i} class="flex gap-2 items-center">
            <span class="text-xs text-zinc-500 w-6">${i + 1}.</span>
            <select class="flex-1 bg-zinc-900 border border-zinc-800 rounded px-3 py-2"
                    value=${lv} onChange=${(e) => setLevel(i, e.target.value)}>
              ${tokens.map((t) => html`<option key=${t} value=${t}>${t}</option>`)}
            </select>
            <button class="text-rose-400 px-2" onClick=${() => removeLevel(i)}>✕</button>
          </div>`)}
        <button class="text-xs text-sky-400" onClick=${addLevel}>+ add level</button>
      </div>
      <div class="flex gap-2 items-center">
        <label class="text-sm">Mode</label>
        <select class="bg-zinc-900 border border-zinc-800 rounded px-3 py-2"
                value=${mode} onChange=${(e) => setMode(e.target.value)}>
          <option value="symlink">symlink (safe)</option>
          <option value="hardlink">hardlink</option>
          <option value="copy">copy</option>
          <option value="move">move (destructive)</option>
        </select>
        <button class="bg-zinc-800 hover:bg-zinc-700 px-4 py-2 rounded" onClick=${() => run(false)}>
          Dry-run
        </button>
        <button class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded" onClick=${() => run(true)}>
          Apply
        </button>
      </div>
      ${preview && html`
        <div class="text-sm">
          <div>${preview.plan_size} files · ${preview.conflicts} conflicts · ${preview.written} ${preview.applied ? "applied" : "would-write"}</div>
          <pre class="mt-2 bg-zinc-900 p-3 rounded text-xs overflow-auto max-h-96">${preview.preview.map((p) => `${p.source}\n  → ${p.target}`).join("\n\n")}</pre>
        </div>`}
    </section>
  `;
}

function SettingsTab() {
  const [t, setT] = useState({
    sharp_keeper: 0.55, sharp_reject: 0.30,
    reject_closed_eyes: true, accept_overexposed: false, accept_underexposed: false,
    horizon_warn_deg: 3.0,
  });
  const [msg, setMsg] = useState("");

  async function apply() {
    const r = await api("/api/reclassify", { method: "POST", body: JSON.stringify(t) });
    setMsg(`Reclassified ${r.updated} images.`);
  }
  const slider = (key, min, max, step) => html`
    <div class="flex items-center gap-3">
      <label class="w-44 text-sm">${key}</label>
      <input type="range" min=${min} max=${max} step=${step} value=${t[key]}
             onChange=${(e) => setT({ ...t, [key]: parseFloat(e.target.value) })} class="flex-1" />
      <span class="w-12 text-xs text-right">${t[key]}</span>
    </div>`;
  const toggle = (key) => html`
    <div class="flex items-center gap-3">
      <label class="w-44 text-sm">${key}</label>
      <input type="checkbox" checked=${t[key]} onChange=${(e) => setT({ ...t, [key]: e.target.checked })} />
    </div>`;
  return html`
    <section class="p-6 max-w-xl space-y-3">
      <h2 class="text-xl font-semibold">Decision thresholds</h2>
      ${slider("sharp_keeper", 0, 1, 0.01)}
      ${slider("sharp_reject", 0, 1, 0.01)}
      ${slider("horizon_warn_deg", 0, 10, 0.5)}
      ${toggle("reject_closed_eyes")}
      ${toggle("accept_overexposed")}
      ${toggle("accept_underexposed")}
      <button class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded" onClick=${apply}>
        Reclassify now
      </button>
      <p class="text-xs text-zinc-500">${msg}</p>
    </section>
  `;
}

function App() {
  const [tab, setTab] = useState("library");
  const stats = useStats(2000);
  let pane;
  if (tab === "library") pane = html`<${LibraryTab} stats=${stats} />`;
  else if (tab === "triage") pane = html`<${TriageTab} />`;
  else if (tab === "organize") pane = html`<${OrganizeTab} />`;
  else pane = html`<${SettingsTab} />`;
  return html`
    <div class="flex h-screen">
      <${Sidebar} tab=${tab} setTab=${setTab} stats=${stats} />
      <main class="flex-1 flex flex-col min-w-0">${pane}</main>
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
