// Guided demo: arrow keys step through a scripted presentation.
// `say` is what the presenter says out loud; `notes` is the extra detail behind it (N key).

const $ = (s) => document.querySelector(s);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function steps(ctx) {
  const flange = () => ctx.state.index.programs.find((p) => /PCD/.test(p.description) && /circular pocket/.test(p.description))
    || ctx.state.index.programs[0];
  return [
    { page: "explorer", target: "#stats",
      say: "Factories keep <b>thousands of CNC programs</b>, but the CAD drawings behind them are often lost. Nobody knows what each program makes or which parts are alike. This archive has <b>600 programs, with no drawings and no labels</b>.",
      notes: "This is a Computer-Integrated Manufacturing problem: the CAD → CAPP → CAM → CNC chain is broken, and only the CNC end survives. Our system rebuilds the chain backwards, from the program to the part, the plan and the family." },
    { page: "explorer", target: "#p-map",
      say: "Each dot is <b>one program</b>. The system read only the G-code and grouped similar parts together. The colours are part families it <b>discovered by itself</b>; it was never told the answers.",
      notes: "This is Group Technology (Module 6): grouping parts into families for shared tooling, fixtures and machine cells. The map is a t-SNE projection of each program's 75-number fingerprint, for display only. ✕ marks programs HDBSCAN flagged as unusual." },
    { page: "explorer", target: "#p-families", run: async () => { ctx.highlightFamily(ctx.state.index.families[0].id); },
      say: "Each family is <b>named automatically</b> after what its members share, for example 'pocket island + hole'. Clicking a family highlights it on the map.",
      notes: "Names come from the features present in at least 40% of members. We use 8–9 families here; the true number in the benchmark is 8, and the silhouette criterion picked 9 by itself." },
    { page: "explorer", target: "#p-viewer", run: async () => { ctx.highlightFamily(ctx.state.family); await ctx.select(flange().id); },
      say: "Here is one program. From the G-code alone, the system <b>rebuilt the actual part in 3D</b>: a flange with a centre bore and a bolt circle. I can rotate and zoom it.",
      notes: "The model is a height map with 0.25 mm cells, a 2.5D dexel model. Every cutting move lowers the cells under the cutter. The chips show cycle time, tools and removed volume, all computed from the program." },
    { page: "explorer", target: "#p-viewer", run: async () => {
        document.querySelector('#simspeed [data-s="4"]').click(); ctx.startSim(); },
      say: "Now watch it <b>replay the machining</b>. The cutter follows the real toolpath and removes material, and the bar below shows the <b>exact G-code line</b> being executed.",
      notes: "This replay runs in the browser and ends exactly on the server's simulation. Tool shapes are modelled: flat end mill, ball end, and drill with a 118° point. This is real-time CAM simulation (Module 4)." },
    { page: "explorer", target: "#p-tabs", run: async () => ctx.showTab("process"),
      say: "At the same time it builds the <b>process sheet</b>: which tool, which operation, depth, feed, speed and time. It's the process plan, recovered backwards from the program.",
      notes: "This is CAPP (Module 5). Each tool block is classified from what it removed: shallow over the whole top is facing, a ring around the part is profiling, plunges only is drilling. An 'inferred' badge means the tool size wasn't written and was estimated from the step-over." },
    { page: "explorer", target: "#p-tabs", run: async () => { ctx.stopSim(); ctx.showTab("gcode"); },
      say: "This is the original program. If you <b>hover over any line</b>, it explains it in plain English. For example, G83 is a peck-drilling cycle.",
      notes: "The parser is a modal state machine following ISO 6983: it tracks motion mode, units, absolute/incremental, tool and canned-cycle state. It also executes parametric programs (variables, expressions, loops, subroutines, polar coordinates). Things it can't run faithfully, like G41 cutter compensation or subprograms in other files, give a warning instead of a guess." },
    { page: "explorer", target: "#p-tabs", run: async () => ctx.showTab("similar"),
      say: "And it answers the question every shop asks: <b>have we made something like this before?</b> These are the closest programs in the archive, ranked by similarity.",
      notes: "Cosine similarity over fingerprints. On the test set, 94% of the top-5 results are the correct family (P@5 = 0.939). 'Compare side by side' shows how different the texts are." },
    { page: "dialects", target: "#page-dialects .dialects", run: async () => wait(1500),
      say: "Here's the key idea. This is <b>one part written four completely different ways</b>: Fanuc, Haas, no comments, and inch with incremental moves, each clamped at a different angle. The text is different, but the rebuilt parts are <b>the same</b>.",
      notes: "That's why comparing G-code text fails: TF-IDF text clustering scores ARI 0.07 for families, because it groups by dialect instead (0.61). Our fingerprint is rotation-invariant (Hu moments, radial profile) and works on recovered geometry, so it scores 0.80." },
    { page: "explorer", target: null, run: async () => { ctx.state.fastStages = false; await ctx.runSample("same_part/flange_minimal.nc"); },
      say: "Now a program it has <b>never seen before</b>: no tool comments, and arcs written as hundreds of short lines. Watch each stage run: parse, identify cutters, simulate, process sheet, features, fingerprint.",
      notes: "The stage times are real measurements. Because this file has no tool comments, cutter sizes are inferred from the zig-zag step-over; drills can't be inferred, so a default is assumed and a warning is shown." },
    { page: "explorer", target: "#banner",
      say: "It placed the new program in the <b>flange family</b> and marked it with a star on the map. Its closest match in the archive is shown too.",
      notes: "Family assignment uses the nearest family centroid in fingerprint space; the confidence is how typical that distance is among the family's own members." },
    { page: "playground", target: "#page-playground .pg", run: async () => {
        await wait(1200); document.querySelector('[data-edit="0"]')?.click(); await wait(1500); },
      say: "Nothing here is pre-recorded. In the <b>playground</b> I just changed the pocket depth from 6 to 12 mm and ran it again: the part and its description update live. You can try your own program too.",
      notes: "Other quick edits: add a 5th hole, change the drill size, add a slot with a new tool, or hide a tool comment to force inference. Each edit shows what changed and the part description before and after; every button toggles back." },
    { page: "results", target: "#page-results .kpis", run: async () => wait(1200),
      say: "Results on <b>600 programs it was never tuned on</b>: part families found with ARI <b>0.80</b>, against <b>0.07</b> for text comparison; 94% top-5 accuracy; and parts rebuilt almost exactly (IoU 0.999) when tools are named.",
      notes: "ARI: 1 = perfect, 0 = random. Developed on 600 programs (seed 7), measured once on a separate 600 (seed 11). Honest limits: the benchmark is synthetic, recovery drops when tool sizes are unknown, and only 3-axis 2.5D parts are handled." },
    { page: "how", target: "#page-how .steps",
      say: "And this page explains <b>how it works in six steps</b>, using live numbers from the program we just looked at. Happy to go into any step. <b>Questions?</b>",
      notes: "If asked about novelty: earlier G-code reverse engineering targets 3D printing (Tsoutsos 2017, Kiński 2020), and Group Technology classification has always needed CAD models or route sheets. To our knowledge, this is the first approach to form GT families directly from subtractive CNC programs." },
  ];
}

export function initTour(ctx) {
  let list = null, i = 0, active = false;
  const ring = $("#tourring"), bar = $("#tour");

  const place = () => {
    const s = list?.[i];
    const el = s?.target && document.querySelector(s.target);
    if (!active || !el || el.offsetParent === null) { ring.hidden = true; return; }
    const r = el.getBoundingClientRect();
    ring.hidden = false;
    Object.assign(ring.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
  };

  const go = async (k) => {
    if (k < 0 || k >= list.length) return;
    i = k;
    const s = list[i];
    $("#tourstep").textContent = `${i + 1} / ${list.length}`;
    $("#toursay").innerHTML = s.say;
    $("#tournotes").innerHTML = `<b>Speaker notes:</b> ${s.notes || ""}`;
    $("#tournext").textContent = i === list.length - 1 ? "Finish" : "Next →";
    $("#modal").hidden = true;
    ring.hidden = true;
    if (ctx.state.page !== s.page) ctx.showPage(s.page);
    await wait(250);
    const el = s.target && document.querySelector(s.target);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
    await wait(350);
    place();
    try { await s.run?.(); } catch (e) { console.warn("tour step", e); }
    const el2 = s.target && document.querySelector(s.target);
    if (el2) { el2.scrollIntoView({ block: "center", behavior: "smooth" }); await wait(300); }
    place();
  };

  const start = () => { list = steps(ctx); active = true; bar.hidden = false; go(0); };
  const stop = () => { active = false; bar.hidden = true; ring.hidden = true; };

  $("#tourbtn").onclick = start;
  $("#tournext").onclick = () => (i === list.length - 1 ? stop() : go(i + 1));
  $("#tourprev").onclick = () => go(i - 1);
  $("#tourclose").onclick = stop;
  $("#tournotesbtn").onclick = () => { $("#tournotes").hidden = !$("#tournotes").hidden; };
  addEventListener("keydown", (e) => {
    if (!active || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) return;
    if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); $("#tournext").click(); }
    if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go(i - 1); }
    if (e.key === "Escape") stop();
    if (e.key.toLowerCase() === "n") $("#tournotesbtn").click();
  });
  addEventListener("scroll", place, { passive: true });
  addEventListener("resize", place);
  setInterval(() => active && place(), 500);
}
