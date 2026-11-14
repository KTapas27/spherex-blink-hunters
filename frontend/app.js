// Blink Hunters front end: load a view from the API, blink its frames, build spectra on click.
const $ = (sel) => document.querySelector(sel);

const state = {
  key: null, manifest: null, mode: "blink", det: "all", matched: false, channel: null,
  frames: [], idx: 0, playing: true, timer: null, chart: null, lcChart: null, posChart: null, aladin: null,
  lastPoints: [],
};

// Frame group currently shown: "all", a detector ("3"), or a wavelength channel ("3:7").
function currentGroup() {
  if (state.matched && state.det !== "all" && state.channel !== null) return `${state.det}:${state.channel}`;
  return String(state.det);
}

// ---------- URL hash <-> controls (so any view can be shared or embedded) ----------
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  return Object.fromEntries(p.entries());
}
function writeHash() {
  const p = new URLSearchParams({
    q: $("#q").value, fov: $("#fov").value, n: $("#per_group").value,
    det: state.det, mode: state.mode, speed: $("#speed").value, zoom: $("#zoom").value,
  });
  if (state.matched && state.channel !== null) p.set("ch", state.channel);
  if ($("#invert").checked) p.set("invert", "1");
  history.replaceState(null, "", "#" + p.toString());
}

// ---------- API ----------
async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

async function loadView() {
  const body = { q: $("#q").value.trim(), fov: +$("#fov").value, per_group: +$("#per_group").value };
  if (!body.q) return;
  writeHash();
  setStatus("Resolving target…", 0);
  $("#go").disabled = true;
  try {
    let job = await api("/api/views", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    state.key = job.key;
    while (job.status !== "done" && job.status !== "error") {
      const pct = job.total ? job.done / job.total : 0;
      setStatus(`${job.message || job.status}${job.total ? ` (${job.done}/${job.total})` : ""}`, pct);
      await new Promise((r) => setTimeout(r, 1500));
      job = await api(`/api/views/${job.key}`);
    }
    if (job.status === "error") throw new Error(job.message);
    setStatus(null);
    showManifest(job.manifest);
  } catch (err) {
    setStatus("Error: " + err.message, 0);
  } finally {
    $("#go").disabled = false;
  }
}

function setStatus(msg, pct) {
  const box = $("#status");
  box.hidden = !msg;
  if (!msg) return;
  box.querySelector(".msg").textContent = msg;
  box.querySelector(".bar > div").style.width = `${Math.round((pct || 0) * 100)}%`;
}

// ---------- rendering ----------
function showManifest(m) {
  state.manifest = m;
  const groupOf = (f) => f.group ?? String(f.detector); // older manifests have no group
  m.frames.forEach((f) => { f.group = groupOf(f); });
  m.diffs.forEach((f) => { f.group = groupOf(f); });
  m.channels = m.channels || [];
  const dets = ["all", 1, 2, 3, 4, 5, 6].filter((d) => m.frames.some((f) => f.group === String(d)));
  if (!dets.map(String).includes(String(state.det))) state.det = "all";
  $("#dets").innerHTML = dets.map((d) => {
    const fr = m.frames.filter((f) => f.group === String(d));
    const lo = Math.min(...fr.map((f) => f.wl_min)), hi = Math.max(...fr.map((f) => f.wl_max));
    const sub = d === "all" ? "0.75–5 µm" : `${lo.toFixed(2)}–${hi.toFixed(2)}`;
    return `<button data-det="${d}">${d === "all" ? "All" : "D" + d}<small>${sub}</small></button>`;
  }).join("");
  $("#controls").hidden = false;
  renderInfo(m);
  selectFrames();
  updateAladin(m);
  resetSpectrum();
  toggleGaia();
}

function selectFrames() {
  const m = state.manifest;
  if (!m) return;
  renderChannelPicker();
  const list = state.mode === "diff" ? m.diffs : m.frames;
  const group = currentGroup();
  state.frames = list.filter((f) => f.group === group).sort((a, b) => a.visit - b.visit);
  state.idx = 0;
  document.querySelectorAll("#dets button").forEach((b) => b.classList.toggle("on", b.dataset.det === String(state.det)));
  document.querySelectorAll("#mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === state.mode));
  $("#timeline").innerHTML = state.frames.map((f, i) =>
    `<button data-i="${i}">Visit ${f.visit + 1} · ${f.start}</button>`).join("");
  if (!state.frames.length) {
    $("#frameLabel").innerHTML = state.mode === "diff"
      ? "Only one visit here, so there is nothing to difference yet" : "No frames for this detector";
    return;
  }
  // Preload so blinking never flickers.
  state.frames.forEach((f) => { new Image().src = frameUrl(f); new Image().src = frameUrl(f, true); });
  showFrame();
  restartTimer();
  writeHash();
}

function renderChannelPicker() {
  const m = state.manifest;
  const sel = $("#channel");
  const chans = m.channels.filter((c) => String(c.detector) === String(state.det));
  const usable = state.det !== "all" && chans.length > 0;
  sel.disabled = !usable || !state.matched;
  $("#matched").disabled = !usable;
  if (!usable) {
    sel.innerHTML = `<option>${state.det === "all" ? "Pick a detector (D1–D6) first" : "No channel seen in 2+ visits; try more exposures"}</option>`;
    if (state.det === "all" || !chans.length) state.matched = false;
    $("#matched").checked = state.matched;
    return;
  }
  if (state.channel === null || !chans.some((c) => c.channel === state.channel)) {
    // default: the channel observed in the most visits
    state.channel = chans.slice().sort((a, b) => b.visits.length - a.visits.length)[0].channel;
  }
  sel.innerHTML = chans.map((c) =>
    `<option value="${c.channel}" ${c.channel === state.channel ? "selected" : ""}>` +
    `${c.wl_center.toFixed(3)} µm · ${c.visits.length} visits</option>`).join("");
  $("#matched").checked = state.matched;
}

function frameUrl(f, mask = false) {
  return `/views/${state.manifest.key}/${mask ? "mask_" : ""}${f.file}`;
}

function showFrame() {
  const f = state.frames[state.idx];
  if (!f) return;
  const m = state.manifest;
  const zoom = +$("#zoom").value;
  const [ny, nx] = m.shape;
  for (const el of [$("#frame"), $("#mask")]) { el.width = nx * zoom; el.height = ny * zoom; }
  $("#frame").src = frameUrl(f);
  $("#frame").hidden = false;
  $("#mask").src = frameUrl(f, true);
  $("#mask").hidden = !$("#flags").checked;
  $("#frame").classList.toggle("invert", $("#invert").checked);
  $("#crosshair").hidden = !$("#cross").checked;
  drawGaia();
  const det = f.detector === "all" ? "All detectors"
    : `D${f.detector}${f.channel !== null && f.channel !== undefined ? ` channel ${f.channel + 1}/17` : ""}`;
  const head = state.mode === "diff"
    ? `Visit ${f.visit + 1} − Visit ${f.ref_visit + 1}`
    : `Visit ${f.visit + 1}`;
  const wl = f.wl_min !== undefined ? ` · ${f.wl_min.toFixed(2)}–${f.wl_max.toFixed(2)} µm · ${f.n_exposures} exp` : "";
  $("#frameLabel").innerHTML = `${head} <span class="muted">${f.start} → ${f.end} · ${det}${wl}</span>`;
  document.querySelectorAll("#timeline button").forEach((b) => b.classList.toggle("on", +b.dataset.i === state.idx));
}

function step(d) {
  if (!state.frames.length) return;
  state.idx = (state.idx + d + state.frames.length) % state.frames.length;
  showFrame();
}

function restartTimer() {
  clearInterval(state.timer);
  $("#speedVal").textContent = `${$("#speed").value} ms`;
  $("#play").textContent = state.playing ? "❚❚" : "▶︎";
  if (state.playing && state.frames.length > 1) state.timer = setInterval(() => step(1), +$("#speed").value);
}

function renderInfo(m) {
  const t = m.target;
  const pm = Math.hypot(t.pmra, t.pmdec) / 1000;
  const visits = m.visits.map((v) => `<tr><td>Visit ${v.visit + 1}</td><td>${v.start} → ${v.end}</td><td>${v.n} img</td></tr>`).join("");
  $("#info").hidden = false;
  $("#info").innerHTML = `
    <div><b>${t.name}</b></div>
    <div>RA ${t.ra.toFixed(5)}°, Dec ${t.dec.toFixed(5)}° (epoch 2026.0)</div>
    <div>Proper motion ${pm.toFixed(2)}″/yr${t.parallax ? ` · parallax ${t.parallax.toFixed(1)} mas` : ""}</div>
    <div>Moved ${t.moved_arcsec.toFixed(1)}″ since J2000 (${(t.moved_arcsec / m.pixel_scale_arcsec).toFixed(1)} SPHEREx pixels)</div>
    <table>${visits}</table>
    <div style="margin-top:6px">Using ${m.n_exposures_used} of ${m.n_available} exposures · ${m.collections.join(", ")}${m.elapsed_s ? ` · built in ${m.elapsed_s}s` : ""}</div>
    <button id="copyLink">Copy shareable link</button>`;
  $("#copyLink").onclick = () => navigator.clipboard.writeText(location.href);
}

// ---------- click -> sky position -> spectrum ----------
function pixelToSky(px, py) {
  // Inverse gnomonic (TAN) projection for the view grid built by the backend.
  const m = state.manifest, t = m.target, [ny, nx] = m.shape;
  const s = m.pixel_scale_arcsec / 3600 * Math.PI / 180;
  const cx = (nx + 1) / 2, cy = (ny + 1) / 2;
  const xi = -(px - cx) * s, eta = (py - cy) * s;
  const ra0 = t.ra * Math.PI / 180, dec0 = t.dec * Math.PI / 180;
  const D = Math.cos(dec0) - eta * Math.sin(dec0);
  const ra = ra0 + Math.atan2(xi, D);
  const dec = Math.atan2(Math.sin(dec0) + eta * Math.cos(dec0), Math.hypot(xi, D));
  return { ra: ((ra * 180 / Math.PI) + 360) % 360, dec: dec * 180 / Math.PI };
}

async function onImageClick(ev) {
  const m = state.manifest;
  if (!m) return;
  const zoom = +$("#zoom").value;
  const rect = $("#frame").getBoundingClientRect();
  const col = Math.floor((ev.clientX - rect.left) / zoom), row = Math.floor((ev.clientY - rect.top) / zoom);
  const px = col + 1, py = m.shape[0] - row; // FITS 1-based pixel, y up
  const { ra, dec } = pixelToSky(px, py);
  const mark = $("#clickMark");
  mark.hidden = false;
  mark.style.left = `${(col + 0.5) * zoom}px`;
  mark.style.top = `${(row + 0.5) * zoom}px`;
  $("#specWhere").textContent = `RA ${ra.toFixed(4)}°, Dec ${dec.toFixed(4)}° · measuring…`;
  api(`/api/views/${m.key}/positions?ra=${ra}&dec=${dec}`)
    .then((res) => drawPositions(res.points))
    .catch(() => drawPositions([]));
  try {
    const res = await api(`/api/views/${m.key}/spectrum?ra=${ra}&dec=${dec}`);
    drawSpectrum(res.points, res.n_flagged);
    $("#specWhere").textContent = `RA ${ra.toFixed(4)}°, Dec ${dec.toFixed(4)}° · ${res.points.length} points`;
  } catch (err) {
    $("#specWhere").textContent = "Error: " + err.message;
  }
}

const VISIT_COLORS = ["#4dabf7", "#ff9f43", "#51cf66", "#f06595", "#ffd43b"];
const DET_COLORS = { 1: "#748ffc", 2: "#4dabf7", 3: "#38d9a9", 4: "#a9e34b", 5: "#ffa94d", 6: "#ff6b6b" };
const mjdToDate = (mjd) => new Date((mjd - 40587) * 86400000);

// Brightness vs time at the clicked position. Shows one detector (or one wavelength channel when
// "Match wavelength" is on) so that colour differences aren't mistaken for variability.
function drawLightCurve() {
  const pts = state.lastPoints || [];
  let sel = pts, what = "all detectors (colours differ by wavelength)";
  if (state.det !== "all") {
    sel = pts.filter((p) => String(p.detector) === String(state.det));
    what = `D${state.det}`;
    if (state.matched && state.channel !== null) {
      sel = sel.filter((p) => p.channel === state.channel);
      what += ` channel ${state.channel + 1}/17`;
    }
  }
  $("#lc").hidden = !sel.length;
  $("#lcEmpty").hidden = sel.length > 0;
  $("#lcWhere").textContent = pts.length ? `${what} · ${sel.length} points` : "";
  if (!sel.length) {
    $("#lcEmpty").textContent = pts.length ? "No clean points for this detector/channel here." : "Click an object to see how it changes between visits.";
    return;
  }
  const dets = [...new Set(sel.map((p) => p.detector))].sort();
  const datasets = dets.map((d) => ({
    label: `D${d}`,
    data: sel.filter((p) => p.detector === d).map((p) => ({ x: (p.mjd - 40587) * 86400000, y: p.flux_mjy, wl: p.wavelength_um })),
    backgroundColor: DET_COLORS[d], pointRadius: 3,
  }));
  if (state.lcChart) state.lcChart.destroy();
  state.lcChart = new Chart($("#lc"), {
    type: "scatter", data: { datasets },
    options: {
      animation: false,
      scales: {
        x: { ticks: { color: "#8a97ad", callback: (v) => new Date(v).toISOString().slice(0, 7), maxTicksLimit: 6 },
             grid: { color: "#243046" } },
        y: { title: { display: true, text: "Flux (mJy)", color: "#8a97ad" }, ticks: { color: "#8a97ad" }, grid: { color: "#243046" } },
      },
      plugins: {
        legend: { labels: { color: "#e6ebf5" } },
        tooltip: { callbacks: { label: (c) => `${new Date(c.raw.x).toISOString().slice(0, 10)} · ${c.raw.wl.toFixed(3)} µm · ${c.raw.y.toFixed(1)} mJy` } },
      },
    },
  });
}

function drawPositions(points) {
  $("#pos").hidden = !points.length;
  $("#posEmpty").hidden = points.length > 0;
  $("#posWhere").textContent = points.length ? `${points.length} measurements` : "";
  if (state.posChart) state.posChart.destroy();
  if (!points.length) return;
  const dets = [...new Set(points.map((p) => p.detector))].sort();
  const datasets = dets.map((d) => ({
    label: `D${d}`, showLine: true, borderColor: DET_COLORS[d], backgroundColor: DET_COLORS[d], pointRadius: 3,
    data: points.filter((p) => p.detector === d).sort((a, b) => a.mjd - b.mjd)
      .map((p) => ({ x: (p.mjd - 40587) * 86400000, y: p.east_arcsec, n: p.north_arcsec })),
  }));
  state.posChart = new Chart($("#pos"), {
    type: "scatter", data: { datasets },
    options: {
      animation: false,
      scales: {
        x: { ticks: { color: "#8a97ad", callback: (v) => new Date(v).toISOString().slice(0, 7), maxTicksLimit: 6 },
             grid: { color: "#243046" } },
        y: { title: { display: true, text: "East offset (″)", color: "#8a97ad" }, ticks: { color: "#8a97ad" }, grid: { color: "#243046" } },
      },
      plugins: {
        legend: { labels: { color: "#e6ebf5" } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label} ${new Date(c.raw.x).toISOString().slice(0, 10)} · E ${c.raw.y.toFixed(1)}″, N ${c.raw.n.toFixed(1)}″` } },
      },
    },
  });
}

function drawSpectrum(points, nFlagged = 0) {
  state.lastPoints = points;
  drawLightCurve();
  $("#specEmpty").hidden = points.length > 0;
  $("#spec").hidden = !points.length;
  if (!points.length) {
    $("#specEmpty").textContent = nFlagged
      ? `All ${nFlagged} measurements here are flagged. This is usually a saturated bright star; try a fainter object.`
      : "No measurements here (off the detector edge).";
    return;
  }
  const visits = [...new Set(points.map((p) => p.visit))].sort();
  const datasets = visits.map((v) => ({
    label: `Visit ${v + 1}`,
    data: points.filter((p) => p.visit === v).map((p) => ({ x: p.wavelength_um, y: p.flux_mjy })),
    backgroundColor: VISIT_COLORS[v % VISIT_COLORS.length], pointRadius: 3,
  }));
  if (state.chart) state.chart.destroy();
  state.chart = new Chart($("#spec"), {
    type: "scatter", data: { datasets },
    options: {
      animation: false,
      scales: {
        x: { title: { display: true, text: "Wavelength (µm)", color: "#8a97ad" }, ticks: { color: "#8a97ad" }, grid: { color: "#243046" } },
        y: { title: { display: true, text: "Flux (mJy)", color: "#8a97ad" }, ticks: { color: "#8a97ad" }, grid: { color: "#243046" } },
      },
      plugins: { legend: { labels: { color: "#e6ebf5" } } },
    },
  });
}

function resetSpectrum() {
  state.lastPoints = [];
  drawLightCurve();
  drawPositions([]);
  $("#clickMark").hidden = true;
  $("#spec").hidden = true;
  $("#specEmpty").hidden = false;
  $("#specEmpty").textContent = "Click an object in the image.";
  $("#specWhere").textContent = "";
}

// ---------- Gaia DR3 overlay drawn on the SPHEREx image (positions at epoch 2026.0) ----------
async function toggleGaia() {
  const m = state.manifest;
  if (!$("#gaia").checked || !m) { drawGaia(); return; }
  if (state.gaiaKey !== m.key) {
    $("#gaiaNote").textContent = "loading…";
    try {
      const res = await api(`/api/views/${m.key}/gaia`);
      state.gaia = res.sources;
      state.gaiaKey = m.key;
      const fast = res.sources.filter((s) => s.fast).length;
      $("#gaiaNote").textContent = `${res.sources.length} stars${fast ? `, ${fast} fast` : ""}`;
    } catch (err) {
      $("#gaiaNote").textContent = "unavailable";
      state.gaia = [];
    }
  }
  drawGaia();
}

function drawGaia() {
  const svg = $("#gaiaLayer");
  const m = state.manifest;
  const hide = !$("#gaia").checked || !m || state.gaiaKey !== m?.key;
  svg.toggleAttribute("hidden", hide); // SVG elements have no .hidden property
  if (hide) return;
  const zoom = +$("#zoom").value, n = m.shape[0];
  const X = (x) => (x + 0.5) * zoom, Y = (y) => (n - 1 - y + 0.5) * zoom;
  const ARROW_YEARS = 10; // exaggerate motion so arrows are visible
  const GAIA_MAX_G = 17; // fainter stars clutter the view; fast movers are always shown
  svg.innerHTML = state.gaia.filter((s) => s.fast || s.g <= GAIA_MAX_G).map((s) => {
    const r = Math.max(3, 9 - (s.g - 8) * 0.6);
    const title = `<title>Gaia DR3 ${s.id}\nG=${s.g}  pm=${s.pm} mas/yr${s.parallax ? `  plx=${s.parallax} mas` : ""}</title>`;
    if (!s.fast) return `<g><circle cx="${X(s.x)}" cy="${Y(s.y)}" r="${r}">${title}</circle></g>`;
    const x2 = X(s.x + s.dx_per_yr * ARROW_YEARS), y2 = Y(s.y + s.dy_per_yr * ARROW_YEARS);
    return `<g class="fast"><circle cx="${X(s.x)}" cy="${Y(s.y)}" r="${r + 3}">${title}</circle>` +
      `<line x1="${X(s.x)}" y1="${Y(s.y)}" x2="${x2}" y2="${y2}"/>` +
      `<text x="${X(s.x) + r + 6}" y="${Y(s.y) - r - 4}">${(s.pm / 1000).toFixed(2)}″/yr</text></g>`;
  }).join("");
}

// ---------- Aladin context view with Gaia DR3 ----------
function updateAladin(m) {
  if (typeof A === "undefined") { // module still loading (or CDN down): retry once it arrives
    window.addEventListener("aladin-ready", () => updateAladin(m), { once: true });
    return;
  }
  const { ra, dec } = m.target;
  A.init.then(() => {
    if (!state.aladin) {
      state.aladin = A.aladin("#aladin", {
        survey: "P/allWISE/color", fov: m.fov_deg * 2, target: `${ra} ${dec}`,
        showReticle: true, showCooGridControl: false, showProjectionControl: false, showFullscreenControl: true,
      });
    } else {
      try { state.aladin.removeLayers(); } catch (_) { /* older API */ }
      state.aladin.gotoRaDec(ra, dec);
      state.aladin.setFoV(m.fov_deg * 2);
    }
    const gaia = A.catalogFromVizieR("I/355/gaiadr3", `${ra} ${dec}`, m.fov_deg * 0.75,
      { sourceSize: 10, color: "#ffd43b", onClick: "showTable" });
    state.aladin.addCatalog(gaia);
  }).catch(() => {});
}

// ---------- wiring ----------
async function init() {
  const presets = await api("/api/presets").catch(() => []);
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  $("#presets").innerHTML = presets.map((p) =>
    `<button type="button" title="${esc(p.note)}" data-q="${esc(p.query)}">${esc(p.label)}</button>`).join("");
  $("#presets").onclick = (e) => {
    const b = e.target.closest("button");
    if (b) { $("#q").value = b.dataset.q; loadView(); }
  };
  $("#search").onsubmit = (e) => { e.preventDefault(); loadView(); };
  $("#mode").onclick = (e) => { const b = e.target.closest("button"); if (b) { state.mode = b.dataset.mode; selectFrames(); } };
  $("#dets").onclick = (e) => { const b = e.target.closest("button"); if (b) { state.det = b.dataset.det; state.channel = null; selectFrames(); drawLightCurve(); } };
  $("#matched").onchange = () => { state.matched = $("#matched").checked; selectFrames(); drawLightCurve(); };
  $("#channel").onchange = () => { state.channel = +$("#channel").value; selectFrames(); drawLightCurve(); };
  $("#timeline").onclick = (e) => { const b = e.target.closest("button"); if (b) { state.idx = +b.dataset.i; state.playing = false; restartTimer(); showFrame(); } };
  $("#prev").onclick = () => { state.playing = false; restartTimer(); step(-1); };
  $("#next").onclick = () => { state.playing = false; restartTimer(); step(1); };
  $("#play").onclick = () => { state.playing = !state.playing; restartTimer(); };
  $("#speed").oninput = () => { restartTimer(); writeHash(); };
  $("#zoom").oninput = () => { showFrame(); writeHash(); };
  for (const id of ["#invert", "#flags", "#cross"]) $(id).onchange = () => { showFrame(); writeHash(); };
  $("#gaia").onchange = toggleGaia;
  $("#canvasWrap").onclick = onImageClick;
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight") $("#next").click();
    if (e.key === "ArrowLeft") $("#prev").click();
    if (e.key === " ") { e.preventDefault(); $("#play").click(); }
  });

  applyHash();
  // Links like #q=R%20Dra pasted into an open tab should load too.
  window.addEventListener("hashchange", () => {
    if (readHash().q !== $("#q").value) applyHash();
  });
}

function applyHash() {
  const h = readHash();
  if (h.fov) $("#fov").value = h.fov;
  if (h.n) $("#per_group").value = h.n;
  if (h.speed) $("#speed").value = h.speed;
  if (h.zoom) $("#zoom").value = h.zoom;
  if (h.invert) $("#invert").checked = true;
  if (h.det) state.det = h.det;
  if (h.mode) state.mode = h.mode;
  if (h.ch !== undefined) { state.matched = true; state.channel = +h.ch; }
  if (h.ra && h.dec && !h.q) h.q = `${h.ra} ${h.dec}`;
  if (h.q) { $("#q").value = h.q; loadView(); }
}
init();
