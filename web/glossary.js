// Plain-English explanations shown by the ⓘ icons and on the Glossary page.

export const GLOSSARY = {
  cnc: ["CNC", "Computer Numerical Control: a machine tool (mill, lathe) whose movements are driven by a program instead of a person turning handles."],
  gcode: ["G-code", "The language CNC machines read (ISO 6983). Each line is a command: G01 X10 Y5 F300 means 'cut in a straight line to X=10, Y=5 at 300 mm/min'."],
  dialect: ["Dialect", "Different machine brands and CAM systems write G-code differently: Fanuc vs Haas style, mm vs inch, absolute vs incremental, arcs vs many short lines. The same part can therefore look completely different as text."],
  legacy: ["Legacy program", "An old NC program still stored in a shop, often with the CAD model lost and nobody who remembers what it makes."],
  cim: ["CIM", "Computer-Integrated Manufacturing: connecting design (CAD), planning (CAPP), programming (CAM) and the machine (CNC) through shared digital information."],
  capp: ["CAPP / process sheet", "Computer-Aided Process Planning: the list of operations, tools, speeds, feeds and times needed to make a part. We generate it backwards from the G-code."],
  gt: ["Group Technology (GT)", "Grouping similar parts into families so they can share machines, tooling, fixtures and set-ups. Classically done with coding systems like Opitz; we do it from G-code."],
  family: ["Part family", "A group of parts that are similar in shape and/or in how they are made, e.g. all flanges with a bolt circle."],
  dexel: ["Dexel / height map", "The stock is modelled as a grid of tiny columns (0.25 mm wide). Each column stores its current height. Every cutting move lowers the columns under the cutter. What remains is the part."],
  stepover: ["Step-over", "The sideways distance between neighbouring cutting passes, usually 40-60% of the cutter diameter. Measuring it lets us estimate a cutter's size when the program doesn't state it."],
  raster: ["Raster run", "A zig-zag pattern: at least three parallel back-and-forth passes at the same depth joined by short moves. Only these are trusted for step-over measurement."],
  footprint: ["Stock footprint", "The outline of the raw block. G-code never states it, so we estimate it from the facing pass, which usually overruns the block by about one cutter radius."],
  feature: ["Machining feature", "A meaningful shape on the part: hole, pocket, slot, step, outline, island. Recognised from the rebuilt depth map."],
  hu: ["Hu moments", "Seven numbers that describe a shape and stay the same when the shape is moved, rotated or scaled. That keeps a part's fingerprint identical however it was clamped on the table."],
  fingerprint: ["Fingerprint", "A list of 75 numbers describing WHAT a program makes (shape + process), not HOW it is written. Similar parts get similar fingerprints."],
  ward: ["Ward clustering", "Groups items step by step, always merging the two groups whose merger adds the least spread. We stop at the chosen number of families."],
  hdbscan: ["HDBSCAN", "A density-based clustering method that finds the number of families by itself and marks programs that fit nowhere as 'unusual' outliers."],
  tsne: ["t-SNE map", "A way to draw high-dimensional fingerprints on a 2D map so that similar programs end up close together. For display only."],
  ari: ["ARI (Adjusted Rand Index)", "How well discovered clusters agree with the true families. 1 = perfect, 0 = no better than random. Ours: 0.797; comparing G-code text: 0.074."],
  nmi: ["NMI", "Normalised Mutual Information: another 0-to-1 score of agreement between clusters and true families."],
  p5: ["P@5 (precision at 5)", "Out of the 5 most similar programs the system returns, the fraction that really belong to the same family. Ours: 93.9%."],
  iou: ["IoU", "Intersection over Union: overlap between the rebuilt removed region and the designed one, divided by their union. 1 = identical."],
  cutcomp: ["Cutter compensation (G41/G42)", "The program describes the part edge and the controller shifts the path by the tool radius. We can't see the radius in the file, so we warn."],
  canned: ["Canned cycle", "A one-line shortcut for a whole drilling routine (G81/G83): position, feed down, retract, repeated at each X/Y listed."],
  benchmark: ["Benchmark (synthetic)", "1,200 programs we generated with known answers: 8 part families × 4 dialects with random sizes, rotation and origin. Tuned on 600, all results reported on the other 600."],
};

// short help for each dashboard panel
export const PANEL_HELP = {
  map: "Every dot is one G-code program. Programs that make similar parts sit close together. Colours are the families the system DISCOVERED; it was never told the answers. ✕ = programs it flagged as unusual.",
  families: "The part families found automatically. Each is named after the features most of its members share.",
  viewer: "The part rebuilt purely from the G-code by simulating material removal. Drag to rotate, scroll to zoom. ▶ Simulate replays the machining.",
  process: "The process plan recovered from the program: one row per tool. Click a row to see its G-code.",
  features: "Shapes recognised on the rebuilt part, with position, size and depth. 'Nested in' means it sits inside another feature.",
  similar: "The archive programs whose fingerprints are closest: 'have we made something like this before?'",
  gcode: "The original program. Hover over any line for a plain-English explanation.",
};

export function infoIcon(key) {
  const t = PANEL_HELP[key] || (GLOSSARY[key] && GLOSSARY[key][1]) || "";
  return `<span class="info" tabindex="0" data-tip="${t.replace(/"/g, "&quot;")}">ⓘ</span>`;
}
