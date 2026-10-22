import { PartViewer, TOOL_COLORS, drawThumb } from "./viewer.js";
import { attachExplainer, explainLine, highlight } from "./gcode.js";
import { infoIcon } from "./glossary.js";
import * as pages from "./pages.js";
import { initTour } from "./tour.js";

export const FAMILY_COLORS = ["#4e9cf5", "#f2a33a", "#3ccf91", "#e5677a", "#a78bfa", "#2ec4c4",
  "#e3d25b", "#ff8a4c", "#8bd450", "#d17bd8", "#7aa2c4", "#c9a36b"];
export const OP_COLORS = { facing: "#7aa2c4", pocketing: "#4e9cf5", pocket_island: "#a78bfa", bore: "#2ec4c4",
  slotting: "#e3d25b", step_milling: "#ff8a4c", profiling: "#3ccf91", drilling: "#e5677a", other: "#8a96a3" };

export const $ = (s) => document.querySelector(s);
export const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const famColor = (f) => FAMILY_COLORS[((f % FAMILY_COLORS.length) + FAMILY_COLORS.length) % FAMILY_COLORS.length];
export const fmtTime = (s) => { s = Math.round(s); const m = Math.floor(s / 60); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(s % 60).padStart(2, "0")}`; };
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

export const state = { index: null, byId: {}, current: null, rec: null, family: null, uploads: [], page: "explorer" };

/* ------------------------------------------------------------ pages */
export function showPage(name) {
  state.page = name;
  document.querySelectorAll(".gtip, .itip").forEach((t) => { t.hidden = true; });
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.page === name));
  document.querySelectorAll(".page").forEach((p) => { p.hidden = p.id !== `page-${name}`; });
  if (name === "explorer") requestAnimationFrame(() => Plotly.Plots.resize("map"));
  pages.render(name, ctx);
  scrollTo({ top: 0 });
}

/* ------------------------------------------------------------ explorer */
function renderStats(ix) {
  const total = ix.programs.reduce((s, p) => s + p.cycle_time_s, 0);
  const warned = ix.programs.filter((p) => p.n_warnings > 0).length;
  $("#stats").innerHTML = [
    [ix.programs.length, "programs in archive"], [ix.families.length, "part families found"],
    [ix.n_outliers, "unusual programs"], [fmtTime(total), "total machining time"], [warned, "with warnings"],
  ].map(([v, l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
}

function renderFamilies(ix) {
  $("#famhint").textContent = "click to highlight";
  $("#families").innerHTML = ix.families.map((f) => `
    <li data-f="${f.id}">
      <span class="swatch" style="background:${famColor(f.id)}"></span>
      <span class="name">F${f.id + 1} · ${esc(f.label)}<small>median cycle time ${fmtTime(f.median_cycle_time_s)}</small></span>
      <span class="count">${f.size}</span>
    </li>`).join("");
  $("#families").onclick = (e) => {
    const li = e.target.closest("li");
    if (li) highlightFamily(+li.dataset.f);
  };
}

export function highlightFamily(f) {
  state.family = state.family === f ? null : f;
  document.querySelectorAll("#families li").forEach((x) => x.classList.toggle("on", +x.dataset.f === state.family));
  renderMap();
}

export function renderMap() {
  const ix = state.index, traces = [];
  for (const f of ix.families) {
    const pts = ix.programs.filter((p) => p.family === f.id);
    const dim = state.family !== null && state.family !== f.id;
    traces.push({
      type: "scattergl", mode: "markers", name: `F${f.id + 1}`, x: pts.map((p) => p.x), y: pts.map((p) => p.y),
      customdata: pts.map((p) => p.id), text: pts.map((p) => `<b>${p.id}</b> · F${p.family + 1}<br>${p.description}`), hoverinfo: "text",
      marker: { size: 7, color: famColor(f.id), opacity: dim ? 0.1 : 0.85, symbol: pts.map((p) => (p.hdbscan < 0 ? "x" : "circle")) },
    });
  }
  const sel = [state.current && state.byId[state.current], ...state.uploads].filter(Boolean);
  if (sel.length) traces.push({
    type: "scatter", mode: "markers+text", x: sel.map((p) => p.x), y: sel.map((p) => p.y), hoverinfo: "skip", showlegend: false,
    text: sel.map((p) => (p.upload ? "  new" : "")), textposition: "middle right", textfont: { color: "#fff", size: 11 },
    marker: { size: sel.map((p) => (p.upload ? 18 : 15)), symbol: sel.map((p) => (p.upload ? "star" : "circle-open")),
      color: "#ffffff", line: { width: 2, color: "#fff" } },
  });
  Plotly.react("map", traces, {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", margin: { l: 8, r: 8, t: 8, b: 8 },
    xaxis: { visible: false }, yaxis: { visible: false }, showlegend: false, dragmode: "pan",
    hoverlabel: { bgcolor: "#151a20", bordercolor: "#262e38", font: { family: "IBM Plex Mono", size: 11, color: "#dbe2ea" } },
  }, { displayModeBar: false, responsive: true, scrollZoom: true });
  const el = $("#map");
  el.removeAllListeners?.("plotly_click");
  el.on("plotly_click", (ev) => { const id = ev.points[0]?.customdata; if (id) select(id); });
}

function renderChips(rec, tools) {
  const s = rec.summary, d = rec.dialect;
  const dialect = [d.inch && "inch", d.incremental && "incremental (G91)", d.canned_cycles && "canned cycles", d.arcs && "arcs"].filter(Boolean);
  $("#chips").innerHTML = [
    `⏱ ${fmtTime(s.cycle_time_s)}`, `${s.n_tools} tools`, `${(s.removed_volume_mm3 / 1000).toFixed(1)} cm³ removed`, `${rec.n_lines} lines`,
  ].map((t) => `<span class="chip">${t}</span>`).join("") + dialect.map((t) => `<span class="chip dim">${t}</span>`).join("");
  $("#toollegend").innerHTML = state.viewer.mode === "part" && !state.viewer.sim ? "" : tools.map((t, i) => {
    const info = rec.tools[String(t)] || {};
    return `<span><i style="background:${TOOL_COLORS[i % TOOL_COLORS.length]}"></i>T${t} Ø${info.diameter != null ? +(+info.diameter).toFixed(2) : "?"} ${info.kind ?? ""}</span>`;
  }).join("");
}

function renderWarnings(rec) {
  const w = rec.warnings || [];
  $("#warn").hidden = !w.length;
  $("#warn").innerHTML = w.length ? `<b>⚠ ${w.length} warning${w.length > 1 ? "s" : ""}: the system tells you when it cannot be sure</b><ul>${w.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
}

function renderProcess(rec) {
  const rows = rec.process.map((r, i) => `
    <tr class="click" data-row="${i}" data-from="${r.line_from}" data-to="${r.line_to}">
      <td class="num">${r.seq}</td><td>T${r.tool}</td>
      <td class="num">${r.diameter}${r.diameter_source !== "comment" ? `<span class="badge ${r.diameter_source}" title="${r.diameter_source === "inferred" ? "Not written in the program: estimated from the toolpath step-over" : "Unknown: default value assumed"}">${r.diameter_source}</span>` : ""}</td>
      <td><span class="op"><i style="background:${OP_COLORS[r.operation] || "#888"}"></i>${r.operation.replace("_", " ")}</span></td>
      <td class="num">${r.count}</td><td class="num">${r.depth.toFixed(2)}</td><td class="num">${r.feed}</td>
      <td class="num">${r.spindle}</td><td class="num">${fmtTime(r.time_s)}</td><td class="num">${(r.volume_mm3 / 1000).toFixed(2)}</td>
    </tr>`).join("");
  $("#tab-process").innerHTML = `<p class="empty">Recovered process plan: one row per tool. <b>Click a row</b> to jump to its G-code. ${infoIcon("capp")}</p>
    <table><thead><tr><th>#</th><th>Tool</th><th>Ø mm</th><th>Operation</th><th>Count</th>
    <th>Depth</th><th>Feed</th><th>RPM</th><th>Time</th><th>cm³</th></tr></thead><tbody>${rows}</tbody></table>`;
  $("#tab-process").querySelectorAll("tr.click").forEach((tr) => tr.onclick = () => {
    showTab("gcode");
    highlightLines(+tr.dataset.from, +tr.dataset.to);
  });
}

function renderFeatures(rec) {
  if (!rec.features.length) { $("#tab-features").innerHTML = `<p class="empty">No features below the faced surface.</p>`; return; }
  const pat = rec.pattern ? `Hole pattern: <b>${rec.pattern.kind.replace("_", " ")}</b> · ${rec.pattern.n} holes${rec.pattern.pcd ? ` · pitch-circle diameter ${rec.pattern.pcd} mm` : ""}. ` : "";
  $("#tab-features").innerHTML = `<p class="empty">${pat}Shapes recognised on the rebuilt part. ${infoIcon("feature")}</p><table><thead><tr><th>#</th><th>Type</th><th>X</th><th>Y</th><th>Size (mm)</th><th>Floor depth</th><th>Max depth</th><th>Inside #</th></tr></thead><tbody>${
    rec.features.map((f) => `<tr><td class="num">${f.id}</td><td>${f.type.replace("_", " ")}</td><td class="num">${f.x.toFixed(1)}</td><td class="num">${f.y.toFixed(1)}</td>
      <td class="num">${f.diameter ? "Ø" + f.diameter : `${f.length.toFixed(1)} × ${f.width.toFixed(1)}`}</td>
      <td class="num">${f.depth.toFixed(2)}</td><td class="num">${f.max_depth.toFixed(2)}</td><td>${f.parent ?? "—"}</td></tr>`).join("")}</tbody></table>`;
}

function renderGcode(rec) {
  const lines = (rec.text || "").split("\n").slice(0, 8000);
  $("#gcode").innerHTML = lines.map((ln) => `<span data-gline>${highlight(ln)}</span>`).join("");
}

function highlightLines(a, b, cls = "hl") {
  const spans = $("#gcode").children;
  for (let i = 0; i < spans.length; i++) spans[i].classList.toggle(cls, i + 1 >= a && i + 1 <= b);
  spans[Math.max(0, a - 3)]?.scrollIntoView({ block: "start" });
}

async function renderSimilar(id, list) {
  const sims = list || await api(`/api/similar/${encodeURIComponent(id)}`);
  const recs = await Promise.all(sims.map((s) => api(`/api/program/${encodeURIComponent(s.id)}`)));
  $("#tab-similar").innerHTML = `<p class="empty">Closest programs in the archive by fingerprint: <b>"have we made something like this before?"</b> ${infoIcon("fingerprint")}</p><div class="cards">${sims.map((s, i) => `
    <div class="card" data-id="${s.id}">
      <canvas></canvas>
      <div class="meta"><span>${s.id}</span><b>${Math.round(s.score * 100)}%</b></div>
      <small><span class="swatch" style="width:8px;height:8px;background:${famColor(s.family)}"></span> F${s.family + 1} · ${esc(recs[i].description)}</small>
      <button class="cmp" data-cmp="${s.id}">Compare side by side</button>
    </div>`).join("")}</div>`;
  $("#tab-similar").querySelectorAll(".card").forEach((c, i) => {
    drawThumb(c.querySelector("canvas"), recs[i].heightmap);
    c.onclick = (e) => {
      if (e.target.dataset.cmp) { openCompare(id, e.target.dataset.cmp); return; }
      select(c.dataset.id);
    };
  });
}

export async function openCompare(a, b) {
  const r = await api(`/api/compare?a_id=${encodeURIComponent(a)}&b_id=${encodeURIComponent(b)}`);
  const col = (rec) => `<div><h2>${esc(rec.id)}</h2><p class="desc">${esc(rec.description)}</p>
    <canvas></canvas><pre>${esc((rec.text || "").split("\n").slice(0, 60).join("\n"))}</pre></div>`;
  $("#compare").innerHTML = `<div class="sim">${Math.round(r.similarity * 100)}% fingerprint similarity
    <small>Compared by what they make, not by their text: look how different the G-code is.</small></div>${col(r.a)}${col(r.b)}`;
  $("#modal").hidden = false;
  const cv = $("#compare").querySelectorAll("canvas");
  drawThumb(cv[0], r.a.heightmap);
  drawThumb(cv[1], r.b.heightmap);
}

export function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll("#p-tabs .tab").forEach((t) => { t.hidden = t.id !== `tab-${name}`; });
}

export async function select(id, preloaded) {
  stopSim();
  state.current = id;
  const rec = preloaded || await api(`/api/program/${encodeURIComponent(id)}`);
  state.rec = rec;
  const shown = rec.id.startsWith("upload-") ? `${rec.id.replace(/^upload-\d+-/, "")} (new)` : rec.id;
  $("#title").textContent = rec.family !== undefined && rec.family !== null ? `${shown}  ·  F${rec.family + 1}` : shown;
  $("#desc").textContent = rec.description;
  $("#stl").hidden = !!preloaded;
  $("#stl").href = `/api/stl/${encodeURIComponent(id)}`;
  state.tools = state.viewer.setProgram(rec);
  renderChips(rec, state.tools);
  renderWarnings(rec);
  renderProcess(rec);
  renderFeatures(rec);
  renderGcode(rec);
  if (!preloaded) { $("#banner").hidden = true; renderSimilar(id); }
  renderMap();
  return rec;
}

/* ------------------------------------------------------------ simulation controls */
export function startSim() {
  if (!state.rec) return;
  const v = state.viewer;
  if (v.sim) { $("#simbtn").textContent = v.pauseSim() ? "⏸ Pause" : "▶ Resume"; return; }
  showTab("process");
  v.startSim({
    onStep: ({ progress, line, block, rapid }) => {
      $("#simfill").style.width = `${(progress * 100).toFixed(1)}%`;
      const rows = document.querySelectorAll("#tab-process tr[data-row]");
      rows.forEach((r) => r.classList.toggle("live", +r.dataset.row === block));
      if (line && line !== state.simLine) {
        state.simLine = line;
        const txt = (state.rec.text || "").split("\n")[line - 1] || "";
        const op = state.rec.process[block]?.operation?.replace("_", " ") || "";
        $("#simline").innerHTML = `<b>Line ${line}</b> · ${esc(txt.trim().slice(0, 48))} → ${esc(explainLine(txt).filter((s) => !s.startsWith("Line number"))[0] || "")}${op ? ` · <b>${esc(op)}</b>` : ""}${rapid ? " (rapid)" : ""}`;
      }
    },
    onDone: () => {
      $("#simbtn").textContent = "▶ Simulate machining";
      $("#simfill").style.width = "100%";
      $("#simline").innerHTML = `<b>Done.</b> The replay ends exactly on the part recovered by the server's simulation.`;
      document.querySelectorAll("#tab-process tr.live").forEach((r) => r.classList.remove("live"));
      renderChips(state.rec, state.tools);
    },
  });
  v.setSimSpeed(+document.querySelector("#simspeed .on").dataset.s);
  $("#simbtn").textContent = "⏸ Pause";
  renderChips(state.rec, state.tools);
}

export function stopSim() {
  state.viewer?.stopSim(true);
  $("#simbtn").textContent = "▶ Simulate machining";
  $("#simfill").style.width = "0";
  $("#simline").textContent = "Replays the program: watch the cutter remove material, operation by operation.";
  state.simLine = null;
}

/* ------------------------------------------------------------ analysis with live stages */
export async function playStages(rec, title) {
  $("#proctitle").textContent = title;
  $("#procfoot").textContent = "";
  $("#stages").innerHTML = rec.stages.map((s) => `<li><span class="ico"></span><span class="nm">${esc(s.name)}</span>
    <span class="ms">${s.ms < 1 ? "<1" : s.ms.toFixed(0)} ms</span><span class="dt">${esc(s.detail)}</span></li>`).join("");
  $("#procmodal").hidden = false;
  const lis = [...$("#stages").children];
  for (const li of lis) {
    li.className = "run";
    await sleep(state.fastStages ? 120 : 520);
    li.className = "ok";
    li.querySelector(".ico").textContent = "✓";
  }
  $("#procfoot").innerHTML = `Finished in <b>${rec.runtime_s.toFixed(2)} s</b> of real computation (the times shown are measured; the pacing is slowed so you can read it).`;
  await sleep(state.fastStages ? 300 : 1300);
  $("#procmodal").hidden = true;
}

export async function analyzeAndShow(promise, label) {
  $("#proctitle").textContent = `Analysing ${label}…`;
  $("#stages").innerHTML = `<li class="run"><span class="ico"></span><span class="nm">Sending to the analysis engine</span><span class="ms"></span><span class="dt">parsing, simulating, recognising, fingerprinting</span></li>`;
  $("#procfoot").textContent = "";
  $("#procmodal").hidden = false;
  try {
    const r = await promise;
    const p = r.program;
    await playStages(p, `Analysed ${label}`);
    const near = r.similar.slice(0, 3).map((s) => state.byId[s.id]).filter(Boolean);
    if (near.length) state.uploads.push({ id: p.id, upload: true, x: near.reduce((a, q) => a + q.x, 0) / near.length, y: near.reduce((a, q) => a + q.y, 0) / near.length });
    showPage("explorer");
    await select(p.id, p);
    const fam = state.index.families.find((f) => f.id === p.family);
    $("#banner").hidden = false;
    const best = r.similar[0];
    $("#banner").innerHTML = best.score >= 0.75 && p.family_confidence >= 0.05
      ? `<b>${esc(label)}</b> → part family <b>F${p.family + 1} · ${esc(fam?.label || "")}</b>
        (fits ${Math.round(p.family_confidence * 100)}% of that family as well or better). Closest archived program:
        <b>${best.id}</b> at ${Math.round(best.score * 100)}% similarity. The ★ on the map shows where it landed.`
      : `<b>${esc(label)}</b> is <b>unlike anything in the archive</b>: the closest program, <b>${best.id}</b>, is only
        ${Math.round(best.score * 100)}% similar (nearest family F${p.family + 1} · ${esc(fam?.label || "")}). In a shop this
        would be flagged as a <b>new part type</b> rather than forced into an existing family.`;
    renderSimilar(p.id, r.similar);
    return r;
  } catch (e) {
    $("#stages").innerHTML = `<li class="ok"><span class="ico">!</span><span class="nm">Could not analyse ${esc(label)}</span><span class="ms"></span><span class="dt">${esc(e.message)}</span></li>`;
    $("#procfoot").innerHTML = `<button class="btn sm" onclick="document.getElementById('procmodal').hidden=true">Close</button>`;
    throw e;
  }
}

export const runSample = (path) =>
  analyzeAndShow(api(`/api/identify_sample?path=${encodeURIComponent(path)}`, { method: "POST" }), path.split("/").pop());

/* ------------------------------------------------------------ info tooltips */
function hydrateInfo(root = document) {
  root.querySelectorAll("[data-info]").forEach((el) => { el.outerHTML = infoIcon(el.dataset.info); });
}

function setupInfoTips() {
  const tip = document.createElement("div");
  tip.className = "itip";
  tip.hidden = true;
  document.body.appendChild(tip);
  const show = (el) => {
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
    const r = el.getBoundingClientRect();
    tip.style.left = `${Math.min(r.left, innerWidth - tip.offsetWidth - 10)}px`;
    tip.style.top = `${r.bottom + 8 + tip.offsetHeight > innerHeight ? r.top - tip.offsetHeight - 8 : r.bottom + 8}px`;
  };
  document.addEventListener("mouseover", (e) => { const el = e.target.closest(".info"); if (el) show(el); else tip.hidden = true; });
  document.addEventListener("focusin", (e) => { const el = e.target.closest(".info"); if (el) show(el); });
}

/* ------------------------------------------------------------ boot */
export const ctx = { state, api, select, showPage, showTab, startSim, stopSim, runSample, openCompare, highlightFamily,
  analyzeAndShow, playStages, hydrateInfo, renderMap };

async function boot() {
  hydrateInfo();
  setupInfoTips();
  attachExplainer($("#gcode"));
  state.viewer = new PartViewer($("#viewer"));
  const ix = await api("/api/index");
  state.index = ix;
  ix.programs.forEach((p) => { state.byId[p.id] = p; });
  renderStats(ix);
  renderFamilies(ix);
  renderMap();

  document.querySelectorAll("#nav button").forEach((b) => b.onclick = () => showPage(b.dataset.page));
  document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
  document.querySelectorAll("#viewmode button").forEach((b) => b.onclick = () => {
    document.querySelectorAll("#viewmode button").forEach((x) => x.classList.toggle("on", x === b));
    state.viewer.mode = b.dataset.mode;
    state.viewer.applyMode();
    if (state.rec) renderChips(state.rec, state.tools);
  });
  $("#simbtn").onclick = startSim;
  document.querySelectorAll("#simspeed button").forEach((b) => b.onclick = () => {
    document.querySelectorAll("#simspeed button").forEach((x) => x.classList.toggle("on", x === b));
    state.viewer.setSimSpeed(+b.dataset.s);
  });
  $("#upload").onclick = () => $("#file").click();
  $("#file").onchange = async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    analyzeAndShow(api("/api/identify", { method: "POST", body: fd }), f.name).catch(() => {});
  };
  const samples = await api("/api/samples");
  $("#samples").innerHTML = `<option value="">Run a sample…</option>` + samples.map((s) => `<option value="${s.path}">${esc(s.label)}</option>`).join("");
  $("#samples").onchange = (e) => { const p = e.target.value; e.target.value = ""; if (p) runSample(p).catch(() => {}); };
  $("#closemodal").onclick = () => { $("#modal").hidden = true; };
  $("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").hidden = true; };

  initTour(ctx);
  const first = ix.programs.find((p) => p.description.includes("PCD")) || ix.programs[0];
  await select(first.id);
}

boot();
