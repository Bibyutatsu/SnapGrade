// SnapGrade — App root + Tweaks

const { useState, useEffect, useCallback } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark-film",
  "triageLayout": "grid",
  "gridColumns": "auto",
  "grainOverlay": false
}/*EDITMODE-END*/;

function App() {
  const [tab, setTab] = useState(() => localStorage.getItem('sg.tab') || 'triage');
  useEffect(() => { localStorage.setItem('sg.tab', tab); }, [tab]);
  const [collapsed, setCol] = useState(false);
  // Triage's active library + filter-panel state are lifted here so the sidebar
  // can host the library list (folding away the old LibRail) and so opening the
  // filter panel can auto-collapse the sidebar to reclaim horizontal space.
  const [activeLib, setActiveLib] = useState(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [t, setTweak]     = useTweaks(TWEAK_DEFAULTS);

  // Filter panel open ⇒ collapse the sidebar; closing restores it. Only while on
  // triage, where the panel lives.
  useEffect(() => {
    if (tab === 'triage') setCol(panelOpen);
  }, [panelOpen, tab]);

  const [stats, setStats] = useState(window.SG_DATA.MOCK_STATS);
  // Bumped when SG_DATA is refreshed so screens that read window.SG_DATA at
  // mount (Triage, Bursts, Faces, XMP) re-mount with fresh data.
  const [dataVersion, setDataVersion] = useState(0);

  // Single refresh entry point screens can call instead of location.reload()
  // (which throws away scroll, active library, expanded burst, etc.). Refetches
  // SG_DATA and bumps the remount key so screens pick up fresh data in place.
  const refreshData = useCallback(async () => {
    await window.SG_API.refresh().catch(() => {});
    const s = await window.SG_API.refreshStats().catch(() => null);
    if (s) setStats(s);
    setDataVersion(v => v + 1);
  }, []);
  useEffect(() => { window.SG_REFRESH = refreshData; }, [refreshData]);
  // Poll /api/stats while ingest is running so the sidebar's live indicator and
  // counts reflect reality without a full reload. When an ingest finishes
  // (running flips true → false), do a full SG_DATA refresh so Triage picks up
  // the new frames without the user reloading the page.
  useEffect(() => {
    let alive = true;
    let prevIngest = false, prevFaces = false;
    const tick = async () => {
      const s = await window.SG_API.refreshStats();
      if (!alive || !s) return;
      setStats(s);
      const ingestRunning = !!s.ingest?.running;
      const facesRunning  = !!s.faces?.running;
      // true → false transition on either pipeline = refresh SG_DATA + remount screens.
      if ((prevIngest && !ingestRunning) || (prevFaces && !facesRunning)) {
        await window.SG_API.refresh().catch(() => {});
        if (alive) setDataVersion(v => v + 1);
      }
      prevIngest = ingestRunning;
      prevFaces  = facesRunning;
    };
    tick();
    const id = setInterval(tick, 2500);
    return () => { alive = false; clearInterval(id); };
  }, []);
  const MOCK_STATS = stats;

  // Apply theme class to <html>
  useEffect(() => {
    document.documentElement.className = t.theme || 'dark-film';
  }, [t.theme]);

  // Grid columns CSS variable
  useEffect(() => {
    const cols = t.gridColumns === 'auto'
      ? 'repeat(auto-fill, minmax(210px, 1fr))'
      : `repeat(${t.gridColumns}, 1fr)`;
    document.documentElement.style.setProperty('--grid-cols', cols);
  }, [t.gridColumns]);

  // Grain + vignette + sprocket are one opt-in atmosphere, dark-film only.
  // The grain-on class gates the CSS-only vignette/sprocket; #sg-grain toggles directly.
  useEffect(() => {
    const on = !!t.grainOverlay && t.theme === 'dark-film';
    const el = document.getElementById('sg-grain');
    if (el) el.style.display = on ? 'block' : 'none';
    document.documentElement.classList.toggle('grain-on', on);
  }, [t.grainOverlay, t.theme]);

  // Provide cross-screen data through context (single source) — value identity
  // changes with dataVersion so consumers re-render when SG_DATA is refreshed.
  const dataCtx = React.useMemo(() => ({
    libraries: window.SG_DATA.MOCK_LIBRARIES,
    stats: MOCK_STATS,
    refresh: refreshData,
  }), [dataVersion, MOCK_STATS, refreshData]);

  return (
    <SGDataContext.Provider value={dataCtx}>
      <div className="sg-shell" style={{ gridTemplateColumns: `${collapsed ? 56 : 220}px 1fr` }}>
        <Sidebar
          tab={tab} setTab={setTab}
          stats={MOCK_STATS}
          collapsed={collapsed}
          onToggle={() => setCol(c => !c)}
          libraries={window.SG_DATA.MOCK_LIBRARIES}
          activeLib={activeLib}
          setActiveLib={setActiveLib}
        />
        <div style={{ display:'flex', flexDirection:'column', minWidth:0, height:'100vh', overflow:'hidden' }}>
          <TopBar
            tab={tab}
            layout={t.triageLayout}
            onLayoutToggle={v => setTweak('triageLayout', v)}
            theme={t.theme}
            onThemeChange={v => setTweak('theme', v)}
          />
          <div style={{ flex:1, display:'flex', minHeight:0, overflow:'hidden' }}>
            {tab === 'library'  && <LibraryScreen  key={`lib-${dataVersion}`}  stats={MOCK_STATS} setTab={setTab} />}
            {tab === 'triage'   && <TriageScreen   key={`tri-${dataVersion}`}  layout={t.triageLayout} setLayout={v => setTweak('triageLayout', v)}
                                                    activeLib={activeLib} setActiveLib={setActiveLib}
                                                    panelOpen={panelOpen} setPanelOpen={setPanelOpen} />}
            {tab === 'bursts'   && <BurstsScreen   key={`bur-${dataVersion}`} />}
            {tab === 'faces'    && <FacesScreen    key={`fac-${dataVersion}`} />}
            {tab === 'xmp'      && <XMPExportScreen key={`xmp-${dataVersion}`} />}
            {tab === 'organize' && <OrganizeScreen />}
            {tab === 'settings' && <SettingsScreen />}
          </div>
        </div>
      </div>

      <TweaksPanel>
        <TweakSection label="Visual theme" />
        <TweakRadio
          label="Theme"
          value={t.theme}
          options={[
            { value: 'dark-film',   label: 'Cinematic' },
            { value: 'dark-modern', label: 'Modern' },
            { value: 'light-pro',   label: 'Utility (Light)' },
          ]}
          onChange={v => setTweak('theme', v)}
        />
        <TweakSection label="Triage" />
        <TweakRadio
          label="Layout"
          value={t.triageLayout}
          options={[
            { value: 'grid',      label: 'Grid' },
            { value: 'filmstrip', label: 'Filmstrip' },
          ]}
          onChange={v => setTweak('triageLayout', v)}
        />
        <TweakSelect
          label="Grid columns"
          value={t.gridColumns}
          options={[
            { value: 'auto', label: 'Auto-fill' },
            { value: '2',    label: '2 columns' },
            { value: '3',    label: '3 columns' },
            { value: '4',    label: '4 columns' },
            { value: '5',    label: '5 columns' },
          ]}
          onChange={v => setTweak('gridColumns', v)}
        />
        <TweakSection label="Effects" />
        <TweakToggle
          label="Film grain + vignette (Cinematic only)"
          value={t.grainOverlay}
          onChange={v => setTweak('grainOverlay', v)}
        />
      </TweaksPanel>
    </SGDataContext.Provider>
  );
}

window.SG_API.start(App);
