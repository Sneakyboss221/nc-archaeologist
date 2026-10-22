import { PartViewer, drawThumb } from "./viewer.js";
import { attachExplainer, explainLine, highlight } from "./gcode.js";
import { GLOSSARY, infoIcon } from "./glossary.js";
import { $, api, esc, famColor, fmtTime, OP_COLORS } from "./app.js";

const done = {};

export function render(name, ctx) {
  if (name === "how") return renderHow(ctx);
  if (name === "dialects") return done.dialects || renderDialects(ctx, "flange");
  if (name === "playground") return done.playground || initPlayground(ctx);
  if (name === "results") return done.results || renderResults(ctx);
  if (name === "glossary") return done.glossary || renderGlossary();
}

/* ============================================================ HOW IT WORKS */
function renderHow(ctx) {
  const rec = ctx.state.rec;
  const el = $("#page-how");
  if (!rec) { el.innerHTML = `<div class="wrap"><p class="lead">Select a program first.</p></div>`; return; }
  const st = Object.fromEntries((rec.stages || []).map((s) => [s.name, s.detail]));
  const lines = (rec.text || "").split("\n").filter((l) => /[GXYZ]\d/i.test(l)).slice(0, 7);
  const tools = Object.entries(rec.tools);
  const fam = ctx.state.index.families.find((f) => f.id === rec.family);
  const counts = {};
  rec.features.forEach((f) => { counts[f.type] = (counts[f.type] || 0) + 1; });

  el.innerHTML = `<div class="wrap">
    <div class="pagehead"><h2>How it works: 6 steps, from text to part family</h2>
      <button class="btn" id="how-go">← Back to explorer</button></div>
    <p class="lead">Every number on the right is <b>live from the selected program ${esc(rec.id)}</b>. The only input is the G-code text: no CAD model, no drawing, no labels.</p>
    <div class="steps">
      <div class="step"><div class="stepno">1</div>
        <div><h3>Read the G-code ${infoIcon("gcode")}</h3>
          <p>A G-code program is a list of commands. The parser reads it line by line and keeps track of the machine's state: is it in mm or inch, absolute or incremental, which tool is loaded, which motion mode is active. Arcs become short straight segments, and one-line drilling cycles are expanded into real moves.</p>
          <p>Parametric programs are executed too: variables like <code>#&lt;scale&gt;</code>, expressions in [brackets], loops, if/else, subroutines with arguments, and polar coordinates (@ ^). Anything it can't run faithfully (cutter compensation, subprograms in other files, lathe code) raises a <b>warning</b> instead of a guess.</p></div>
        <div class="live"><h4>Live: ${esc(st["Parse G-code"] || `${rec.n_lines} lines`)}</h4>
          <pre>${lines.map((l) => `<span data-gline>${highlight(l.trim())}</span>  <i class="c">← ${esc(explainLine(l).filter((s) => !s.startsWith("Line number"))[0] || "")}</i>`).join("\n")}</pre></div></div>

      <div class="step"><div class="stepno">2</div>
        <div><h3>Identify the cutters ${infoIcon("stepover")}</h3>
          <p>To rebuild the part you need each cutter's size. If the program states it in a comment, we use that. If not, we look for a zig-zag (raster) pattern: the gap between passes, the <b>step-over</b>, is usually about half the cutter diameter.</p>
          <div class="formula">D ≈ step-over ÷ 0.5 → snap to a standard size</div></div>
        <div class="live"><h4>Live: cutters in this program</h4>
          <table><thead><tr><th>Tool</th><th>Ø mm</th><th>Type</th><th>Where from</th></tr></thead><tbody>${tools.map(([t, v]) =>
            `<tr><td>T${t}</td><td class="num">${+(+v.diameter).toFixed(2)}</td><td>${v.kind}</td><td>${v.source === "comment" ? "written in program" : v.source === "inferred" ? "<b>inferred from step-over</b>" : "unknown: default"}</td></tr>`).join("")}</tbody></table></div></div>

      <div class="step"><div class="stepno">3</div>
        <div><h3>Simulate the machining ${infoIcon("dexel")}</h3>
          <p>The raw block is a grid of tiny columns, each 0.25 mm wide. For every cutting move, every column under the cutter is lowered to the cutter's tip. Flat, ball and drill tips each have their own shape. When the program ends, what is left <b>is the part</b>.</p>
          <div class="formula">height = min(height, tool tip + tool shape)</div>
          <p><button class="btn primary sm" id="how-sim">▶ Watch this simulation</button></p></div>
        <div class="live"><h4>Live: ${esc(st["Simulate material removal"] || "")}</h4><canvas id="how-thumb"></canvas></div></div>

      <div class="step"><div class="stepno">4</div>
        <div><h3>Recover the process plan ${infoIcon("capp")}</h3>
          <p>The program is split at every tool change. Each block is named from <b>what it removed</b>: shallow and over the whole top means facing; a ring around the part means profiling; plunges only means drilling. Cycle time comes from distance ÷ feed rate.</p></div>
        <div class="live"><h4>Live: process sheet</h4>
          <div class="arrowline">${rec.process.map((r) => `<span style="border-color:${OP_COLORS[r.operation]}">T${r.tool} ${r.operation.replace("_", " ")} · ${fmtTime(r.time_s)}</span>`).join("→")}</div>
          <p style="margin-top:8px">Total cycle time <b>${fmtTime(rec.summary.cycle_time_s)}</b>, ${(rec.summary.removed_volume_mm3 / 1000).toFixed(1)} cm³ of material removed.</p></div></div>

      <div class="step"><div class="stepno">5</div>
        <div><h3>Recognise the features ${infoIcon("feature")}</h3>
          <p>The rebuilt part is sliced at each floor depth. Each connected region becomes a feature: <b>hole</b> if small and round, <b>slot</b> if long and one cutter wide, <b>step</b> if open to the edge, <b>pocket</b> otherwise. Regions inside regions are kept as nested features, and holes are checked for a common bolt circle.</p></div>
        <div class="live"><h4>Live: recognised</h4><p><b>${esc(rec.description)}</b></p>
          <ul>${Object.entries(counts).map(([t, n]) => `<li>${n} × ${t.replace("_", " ")}</li>`).join("")}</ul>
          ${rec.pattern ? `<p>Hole pattern: ${rec.pattern.kind.replace("_", " ")}${rec.pattern.pcd ? `, PCD ${rec.pattern.pcd} mm` : ""}</p>` : ""}</div></div>

      <div class="step"><div class="stepno">6</div>
        <div><h3>Fingerprint → part family ${infoIcon("fingerprint")}</h3>
          <p>The part is summarised as <b>75 numbers</b> describing what it IS (shape statistics that don't change with rotation, feature counts, operation mix), never how the text is written. Programs with similar fingerprints form a <b>Group Technology part family</b>. ${infoIcon("gt")}</p></div>
        <div class="live"><h4>Live: this program's fingerprint</h4><div id="how-fp" style="height:150px"></div>
          <p>Family: <span class="swatch" style="background:${famColor(rec.family ?? 0)}"></span> <b>F${(rec.family ?? 0) + 1} · ${esc(fam?.label || "")}</b></p></div></div>
    </div></div>`;
  attachExplainer(el);
  drawThumb($("#how-thumb"), rec.heightmap);
  $("#how-go").onclick = () => ctx.showPage("explorer");
  $("#how-sim").onclick = () => { ctx.showPage("explorer"); setTimeout(ctx.startSim, 300); };
  fingerprintChart(rec);
}

async function fingerprintChart(rec) {
  let geo = rec.geo, proc = rec.proc;
  if (!geo) {
    try { const r = await api(`/api/fingerprint/${encodeURIComponent(rec.id)}`); geo = r.geo; proc = r.proc; } catch { /* uploads */ }
  }
  if (!geo) return;
  Plotly.react("how-fp", [
    { type: "bar", y: geo, marker: { color: "#4e9cf5" }, name: "geometry", hoverinfo: "y" },
    { type: "bar", x: proc.map((_, i) => geo.length + i), y: proc, marker: { color: "#f2a33a" }, name: "process", hoverinfo: "y" },
  ], { paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", margin: { l: 28, r: 4, t: 4, b: 18 }, bargap: 0.15,
    showlegend: true, legend: { orientation: "h", y: 1.15, font: { color: "#8a96a3", size: 10 } },
    xaxis: { color: "#8a96a3", tickfont: { size: 9 } }, yaxis: { color: "#8a96a3", tickfont: { size: 9 }, gridcolor: "#262e38" } },
  { displayModeBar: false, responsive: true });
}

/* ============================================================ SAME PART x4 */
async function renderDialects(ctx, part) {
  done.dialects = true;
  const el = $("#page-dialects");
  el.innerHTML = `<div class="wrap"><div class="pagehead"><h2>Same part, four completely different programs</h2>
    <div class="seg" id="dpart"><button data-p="flange" class="${part === "flange" ? "on" : ""}">Flange</button><button data-p="boss" class="${part === "boss" ? "on" : ""}">Boss</button></div></div>
    <p class="lead">One part, posted by four different "machines": Fanuc, Haas, a comment-free post, and inch + incremental. Each was also clamped at a <b>different rotation and origin</b>. The texts share almost nothing, which is why comparing G-code text fails. The system rebuilds the part from each and gets <b>the same result</b>. ${infoIcon("dialect")}</p>
    <div id="dbody"><p class="empty">Analysing all four programs…</p></div></div>`;
  el.querySelectorAll("#dpart button").forEach((b) => b.onclick = () => renderDialects(ctx, b.dataset.p));
  const r = await api(`/api/dialects?part=${part}`);
  const names = { fanuc: "Fanuc", haas: "Haas", minimal: "No comments", inch_inc: "Inch + incremental" };
  const S = r.similarity;
  const off = []; S.forEach((row, i) => row.forEach((v, j) => { if (i < j) off.push(v); }));
  const mean = off.reduce((a, b) => a + b, 0) / off.length;
  $("#dbody").innerHTML = `<div class="dialects">${r.programs.map((p, i) => `
      <div class="dcol"><h3>${names[p.dialect_name]} <small>${p.n_lines} lines</small></h3>
        <pre class="dcode">${(p.text || "").split("\n").slice(0, 120).map((l) => `<span data-gline>${highlight(l)}</span>`).join("")}</pre>
        <canvas></canvas>
        <div class="dd"><b>${esc(p.description)}</b><br><span class="hint">${[p.dialect.inch && "inch", p.dialect.incremental && "incremental", p.dialect.canned_cycles && "canned cycles", p.dialect.arcs ? "arcs" : "arcs as straight chords"].filter(Boolean).join(" · ")}</span></div>
      </div>`).join("")}</div>
    <div class="grid2" style="margin-top:14px">
      <div class="callout"><h3>Fingerprint similarity between the four versions</h3>
        <table class="simmat"><tr><th></th>${r.programs.map((p) => `<th>${names[p.dialect_name]}</th>`).join("")}</tr>
        ${S.map((row, i) => `<tr><th>${names[r.programs[i].dialect_name]}</th>${row.map((v) => `<td style="background:rgba(60,207,145,${Math.max(v, 0) * 0.45})">${v.toFixed(2)}</td>`).join("")}</tr>`).join("")}</table>
        <p class="hint" style="margin-top:8px">Average between versions: <b style="color:var(--ok)">${(mean * 100).toFixed(0)}%</b>. Average to a random program in the archive: <b>${(r.mean_to_archive * 100).toFixed(0)}%</b>.</p></div>
      <div class="callout"><h3>Why this matters</h3><ul>
        <li>Text comparison (TF-IDF) groups programs by <b>dialect</b>, not by part: ARI 0.07 for families vs 0.61 for dialects.</li>
        <li>Our fingerprint describes the <b>recovered geometry</b>, so rotation, units and formatting don't matter: ARI 0.80.</li>
        <li>On the 600-program test set, 75% of each program's nearest neighbours come from <b>another dialect</b>, and 94% of those are the right family.</li></ul></div></div>`;
  $("#dbody").querySelectorAll(".dcol canvas").forEach((c, i) => drawThumb(c, r.programs[i].heightmap));
  attachExplainer($("#dbody"));
}

/* ============================================================ PLAYGROUND */
// Each quick edit toggles one change on the starter program and returns
// { text, note } (or null when the program no longer has the line it edits).
const SLOT = "(--- 4. SLOT: 8 MM END MILL ---)\nT4 M06 (T4 D8 FLAT ENDMILL)\nS7000 M03\nG0 X-26 Y-27 Z5\nG1 Z-4 F100\nG1 X26 F500\nG0 Z5\n\n";
const EDITS = [
  ["Pocket depth 6 ↔ 12 mm", (t) => {
    const m = t.match(/(T2 M06[\s\S]*?\nG1 Z-)(\d+(?:\.\d+)?)/);
    if (!m) return null;
    const to = +m[2] === 6 ? 12 : 6;
    return { text: t.replace(m[0], m[1] + to), note: `pocket depth ${m[2]} → ${to} mm` };
  }],
  ["Add / remove 5th hole", (t) => t.includes("\nX0 Y28\n")
    ? { text: t.replace("\nX0 Y28\n", "\n"), note: "removed the 5th hole" }
    : t.includes("X-40\nG80") ? { text: t.replace("X-40\nG80", "X-40\nX0 Y28\nG80"), note: "added a 5th hole at X0 Y28" } : null],
  ["Drill 8.5 ↔ 12 mm", (t) => {
    const m = t.match(/T3 D([\d.]+) DRILL/);
    if (!m) return null;
    const to = m[1] === "8.5" ? "12" : "8.5";
    return { text: t.replace(m[0], `T3 D${to} DRILL`), note: `drill diameter ${m[1]} → ${to} mm` };
  }],
  ["Add / remove a slot (new tool)", (t) => t.includes(SLOT)
    ? { text: t.replace(SLOT, ""), note: "removed the slot" }
    : t.includes("\nM05") ? { text: t.replace("\nM05", "\n" + SLOT + "M05"), note: "added an 8 mm slot with a new tool T4" } : null],
  ["Hide / show tool comment (forces inference)", (t) => t.includes("T2 M06 (T2 D10 FLAT ENDMILL)")
    ? { text: t.replace("T2 M06 (T2 D10 FLAT ENDMILL)", "T2 M06"), note: "removed T2's size comment: its diameter must now be inferred from the zig-zag spacing" }
    : t.includes("T2 M06\n") ? { text: t.replace("T2 M06\n", "T2 M06 (T2 D10 FLAT ENDMILL)\n"), note: "restored T2's size comment" } : null],
];

async function initPlayground(ctx) {
  done.playground = true;
  const el = $("#page-playground");
  el.innerHTML = `<div class="wrap"><div class="pagehead"><h2>Playground: write or edit G-code, see the part</h2></div>
    <p class="lead">This proves nothing is pre-recorded. Change any number and press <b>Run</b>: the program is parsed, simulated, recognised and placed in a family on the spot. Try a quick edit, or let the professor type their own program.</p>
    <div class="pg">
      <div><div class="pg-bar"><button class="btn primary" id="pg-run">▶ Run</button><button class="btn" id="pg-reset">Reset</button></div>
        <div class="pg-bar">${EDITS.map(([l], i) => `<button class="btn sm" data-edit="${i}">${esc(l)}</button>`).join("")}</div>
        <textarea class="editor" id="pg-text" spellcheck="false"></textarea></div>
      <div class="panel" style="padding:12px"><div class="pg-view" id="pg-view"></div>
        <div class="pg-out" id="pg-out"><p class="empty">Press Run to analyse the program.</p></div></div>
    </div></div>`;
  const viewer = new PartViewer($("#pg-view"));
  const t = await api("/api/playground_template");
  const box = $("#pg-text");
  box.value = t.text;
  let lastDesc = null, lastSig = null;
  const run = async (note) => {
    $("#pg-run").disabled = true;
    $("#pg-out").innerHTML = `<p class="empty">Analysing…</p>`;
    try {
      const r = await api("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: box.value, name: "playground" }) });
      const p = r.program;
      viewer.setProgram(p);
      const fam = ctx.state.index.families.find((f) => f.id === p.family);
      // compare features (type, size, depth) so depth-only edits are visible too
      const sig = p.features.map((f) => `${f.type}|${f.diameter ?? f.length.toFixed(0) + "x" + f.width.toFixed(0)}|${f.max_depth.toFixed(1)}`).join(";");
      const depthNote = lastSig && lastSig !== sig && lastDesc === p.description ? "<br>Feature sizes or depths changed: see the feature table." : "";
      const changed = typeof note === "string"
        ? `<div class="banner" style="margin-bottom:10px">Edit: <b>${esc(note)}</b>${lastDesc && lastDesc !== p.description ? `<br>Before: ${esc(lastDesc)}` : depthNote || (lastDesc ? "<br>Recovered part unchanged." : "")}</div>` : "";
      lastDesc = p.description;
      lastSig = sig;
      const tools = Object.entries(p.tools).map(([k, v]) => `<tr><td>T${k}</td><td class="num">${+(+v.diameter).toFixed(2)}</td><td>${esc(v.kind)}</td><td>${v.source === "comment" ? "from comment" : v.source === "inferred" ? "<b>inferred from step-over</b>" : "default (unknown)"}</td></tr>`).join("");
      $("#pg-out").innerHTML = `${changed}<div class="desc2">${esc(p.description)}</div>
        ${p.warnings.length ? `<div class="warn" style="border-radius:8px;margin-bottom:8px">⚠ ${p.warnings.map(esc).join("<br>⚠ ")}</div>` : ""}
        <table style="margin-bottom:8px"><thead><tr><th>Feature</th><th>X</th><th>Y</th><th>Size mm</th><th>Depth mm</th></tr></thead><tbody>${
          p.features.map((f) => `<tr><td>${esc(f.type.replace("_", " "))}</td><td class="num">${f.x.toFixed(1)}</td><td class="num">${f.y.toFixed(1)}</td><td class="num">${f.diameter ? "Ø" + f.diameter : `${f.length.toFixed(0)} × ${f.width.toFixed(0)}`}</td><td class="num">${f.max_depth.toFixed(1)}</td></tr>`).join("")}</tbody></table>
        <table style="margin-bottom:8px"><thead><tr><th>Tool</th><th>Ø mm</th><th>Type</th><th>Size from</th></tr></thead><tbody>${tools}</tbody></table>
        <ol class="stages" style="padding:0">${p.stages.map((s) => `<li class="ok"><span class="ico">✓</span><span class="nm">${esc(s.name)}</span><span class="ms">${s.ms < 1 ? "<1" : s.ms.toFixed(0)} ms</span><span class="dt">${esc(s.detail)}</span></li>`).join("")}</ol>
        <p>Closest family: <span class="swatch" style="background:${famColor(p.family)}"></span> <b>F${p.family + 1} · ${esc(fam?.label || "")}</b> · total ${p.runtime_s.toFixed(2)} s
        <button class="btn sm" id="pg-open">Open in explorer →</button></p>`;
      $("#pg-open").onclick = async () => { ctx.showPage("explorer"); await ctx.select(p.id, p); };
    } catch (e) {
      $("#pg-out").innerHTML = `<div class="warn" style="border-radius:8px">Could not analyse: ${esc(e.message)}</div>`;
    } finally { $("#pg-run").disabled = false; }
  };
  $("#pg-run").onclick = () => run("your changes to the program");
  $("#pg-reset").onclick = () => { box.value = t.text; lastDesc = lastSig = null; run(); };
  el.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => {
    const res = EDITS[+b.dataset.edit][1](box.value);
    if (!res) { run("this quick edit needs the original lines; press Reset first"); return; }
    box.value = res.text;
    run(res.note);
  });
  ctx.playgroundRun = run;
  run();
}

/* ============================================================ RESULTS */
async function renderResults(ctx) {
  done.results = true;
  const el = $("#page-results");
  el.innerHTML = `<div class="wrap"><p class="empty">Loading results…</p></div>`;
  const M = await api("/api/results");
  const R = M.reconstruction.summary, F = M.families, T = M.tool_inference, D = M.dialect_invariance;
  const pct = (x) => `${(x * 100).toFixed(1)}%`;
  el.innerHTML = `<div class="wrap">
    <div class="pagehead"><h2>Results: measured on 600 programs the system was never tuned on</h2></div>
    <p class="lead">Everything was developed on one set of 600 programs and measured once on a <b>separate held-out set</b> of 600. Each program has a known true answer, used <b>only for scoring</b>. ${infoIcon("benchmark")}</p>
    <div class="kpis">
      <div class="kpi good"><div class="big">${F.full.ari.toFixed(2)}</div><div class="lbl">Family discovery (ARI) ${infoIcon("ari")}</div><p>1.0 = perfect, 0 = random. Comparing G-code text scores only <b>${F.text_tfidf_raw.ari.toFixed(2)}</b>.</p></div>
      <div class="kpi good"><div class="big">${pct(F.full.p_at_5)}</div><div class="lbl">"Find similar" accuracy (P@5) ${infoIcon("p5")}</div><p>Of the 5 most similar programs returned, how many are truly the same family.</p></div>
      <div class="kpi good"><div class="big">${R.tools_from_comments.iou.toFixed(3)}</div><div class="lbl">Part recovery (IoU) ${infoIcon("iou")}</div><p>Rebuilt vs designed part when tools are named; ${R.all.iou.toFixed(3)} over all programs.</p></div>
      <div class="kpi good"><div class="big">${D.sim_same_part.toFixed(2)} <small>vs ${D.sim_other_family.toFixed(2)}</small></div><div class="lbl">Same part, 4 dialects</div><p>Fingerprint similarity of one part written 4 ways, vs different families.</p></div>
      <div class="kpi"><div class="big">${pct(R.all.hole_recall)}</div><div class="lbl">Holes found</div><p>Precision ${pct(R.all.hole_precision)}, position error ${R.all.hole_pos_mae_mm.toFixed(2)} mm.</p></div>
      <div class="kpi"><div class="big">${M.dataset.failed.length}<small> / ${M.dataset.n_programs}</small></div><div class="lbl">Programs that crashed</div><p>Average ${M.reconstruction.runtime_mean_s.toFixed(1)} s per program on a laptop.</p></div>
    </div>
    <div class="grid2">
      <div class="figure"><h3>Ablation: which part of the fingerprint matters?</h3><div id="res-abl" style="height:300px"></div>
        <div class="cap">Text methods mostly learn the <b>dialect</b> (their clusters match dialect at ARI ${F.text_tfidf_raw.ari_vs_dialect?.toFixed(2) ?? "0.61"}). Geometry or process alone does well; <b>combining both is best</b>.</div></div>
      <div class="figure"><h3>Discovered clusters vs true families</h3><img src="/figs/confusion.png" alt="confusion matrix">
        <div class="cap">Each row is a true family and each column a discovered cluster; a strong diagonal means correct grouping.</div></div>
      <div class="figure"><h3>Fingerprint map of the test set</h3><img src="/figs/tsne.png" alt="t-SNE map">
        <div class="cap">Colour = true family, marker shape = dialect. Shapes mix inside each colour cluster: <b>dialect doesn't matter</b>.</div></div>
      <div class="figure"><h3>Feature recognition</h3><table><thead><tr><th>Feature</th><th>Count</th><th>Precision</th><th>Recall</th></tr></thead><tbody>${
        Object.entries(M.reconstruction.features).map(([t, v]) => `<tr><td>${t.replace("_", " ")}</td><td class="num">${v.tp + v.fn}</td><td class="num">${pct(v.precision)}</td><td class="num">${pct(v.recall)}</td></tr>`).join("")}</tbody></table>
        <div class="cap">Cutter inference (no comments): covers ${pct(T.coverage)} of milling tools; ${pct(T.within_one_size_of_inferred)} within one standard size.</div></div>
    </div>
    <div class="callout honest"><h3>Honest limitations (also in the paper)</h3><ul>
      <li>The benchmark is <b>synthetic</b>: we generated it because no labelled public dataset of CNC programs exists. Real-archive validation is the next step.</li>
      <li>When cutter sizes can't be stated or inferred, recovery drops (IoU ${R.tools_inferred.iou.toFixed(2)} vs ${R.tools_from_comments.iou.toFixed(3)}).</li>
      <li>2.5D height map: 3-axis parts only (no undercuts). Cutter compensation and subprograms stored in other files are flagged, not executed.</li>
      <li>Real-file check: 13 of 15 open-source LinuxCNC programs analysed (the other 2 are not part programs); there is no ground truth for them, so this is qualitative.</li></ul></div>
  </div>`;
  const order = ["text_tfidf_raw", "text_tfidf_codes", "process_only", "geometry_only", "full"];
  const labels = ["Text (raw)", "Text (codes)", "Process only", "Geometry only", "Full (ours)"];
  Plotly.react("res-abl", [["ari", "ARI", "#4e9cf5"], ["nmi", "NMI", "#f2a33a"], ["p_at_5", "P@5", "#3ccf91"]].map(([k, n, c]) => ({
    type: "bar", name: n, x: labels, y: order.map((o) => F[o][k]), marker: { color: c }, text: order.map((o) => F[o][k].toFixed(2)), textposition: "outside", textfont: { size: 10, color: "#8a96a3" },
  })), { barmode: "group", paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", margin: { l: 30, r: 8, t: 10, b: 40 },
    legend: { orientation: "h", y: 1.12, font: { color: "#dbe2ea" } }, xaxis: { color: "#8a96a3" }, yaxis: { color: "#8a96a3", range: [0, 1.1], gridcolor: "#262e38" } },
  { displayModeBar: false, responsive: true });
}

/* ============================================================ GLOSSARY */
function renderGlossary() {
  done.glossary = true;
  const el = $("#page-glossary");
  el.innerHTML = `<div class="wrap"><div class="pagehead"><h2>Glossary</h2><input class="gsearch" id="gq" placeholder="Search a term…"></div>
    <p class="lead">Every technical word used in the project, in plain English.</p><div class="gloss" id="gl"></div></div>`;
  const draw = (q = "") => {
    $("#gl").innerHTML = Object.values(GLOSSARY).filter(([t, d]) => (t + d).toLowerCase().includes(q.toLowerCase()))
      .map(([t, d]) => `<div><h3>${esc(t)}</h3><p>${esc(d)}</p></div>`).join("") || `<p class="empty">No match.</p>`;
  };
  draw();
  $("#gq").oninput = (e) => draw(e.target.value);
}
