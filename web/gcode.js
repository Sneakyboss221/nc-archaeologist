// Plain-English translation and syntax highlighting of G-code lines.

const G = {
  0: "Rapid move (fast, not cutting)", 1: "Straight cutting move", 2: "Clockwise arc", 3: "Counter-clockwise arc",
  4: "Dwell (pause)", 17: "Work in the XY plane", 18: "Work in the XZ plane (lathe/side work)", 19: "Work in the YZ plane",
  20: "Units = inches", 21: "Units = millimetres", 28: "Return to machine home", 40: "Cutter compensation off",
  41: "Cutter compensation LEFT (controller offsets the path by the tool radius)",
  42: "Cutter compensation RIGHT (controller offsets the path by the tool radius)",
  43: "Apply tool length offset", 49: "Cancel tool length offset", 53: "Move in machine coordinates",
  54: "Use work offset 1 (part zero)", 55: "Use work offset 2", 56: "Use work offset 3", 64: "Path blending (smooth corners)",
  80: "Cancel drilling cycle", 81: "Drilling cycle (straight down and out)", 82: "Drilling cycle with a pause at the bottom",
  83: "Peck drilling cycle (drill in steps, clearing chips)", 90: "Absolute coordinates (positions measured from part zero)",
  91: "Incremental coordinates (each move relative to the last)", 94: "Feed in mm (or inch) per minute",
  96: "Constant surface speed (lathe)", 98: "After drilling, retract to the starting height", 99: "After drilling, retract to the R-plane",
};
const M = {
  0: "Program stop", 1: "Optional stop", 2: "End of program", 3: "Spindle ON clockwise", 4: "Spindle ON counter-clockwise",
  5: "Spindle STOP", 6: "Tool change", 8: "Coolant ON", 9: "Coolant OFF", 30: "End of program and rewind",
  98: "Call a subprogram", 99: "Return from subprogram",
};
const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : String(+v.toFixed(3)));

export function explainLine(raw) {
  const out = [];
  const comment = (raw.match(/\(([^)]*)\)|;(.*)$/) || []).slice(1).find(Boolean);
  const code = raw.replace(/\([^)]*\)/g, " ").replace(/;.*$/, "").toUpperCase();
  if (/#|\b(IF|WHILE|GOTO)\b/.test(code)) out.push("Macro programming (variables / logic): not executed by this tool, a warning is raised");
  const words = [...code.matchAll(/([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))/g)].map((m) => [m[1], parseFloat(m[2])]);
  const v = Object.fromEntries(words.filter(([l]) => !"GMN".includes(l)));
  const gs = words.filter(([l]) => l === "G").map(([, n]) => n);
  const ms = words.filter(([l]) => l === "M").map(([, n]) => n);
  const n = words.find(([l]) => l === "N");
  if (n) out.push(`Line number N${n[1]} (just a label)`);
  const pos = ["X", "Y", "Z"].filter((a) => a in v).map((a) => `${a}=${fmt(v[a])}`).join(", ");
  for (const g of gs) {
    let t = G[Math.round(g)] || `G${g}: not a standard milling code here`;
    if ([81, 82, 83].includes(g) && "Z" in v) t += `: hole bottom Z=${fmt(v.Z)}${"R" in v ? `, start feeding at R=${fmt(v.R)}` : ""}${"Q" in v ? `, peck ${fmt(v.Q)} mm at a time` : ""}`;
    else if ([0, 1, 2, 3].includes(g) && pos) t += ` to ${pos}`;
    if ([2, 3].includes(g)) t += "I" in v || "J" in v ? ` (arc centre offset I=${fmt(v.I ?? 0)}, J=${fmt(v.J ?? 0)})` : "R" in v ? ` (radius ${fmt(v.R)})` : "";
    out.push(t);
  }
  if (!gs.some((g) => [0, 1, 2, 3, 81, 82, 83].includes(g)) && pos) out.push(`Move to ${pos} (same motion type as the previous line)`);
  for (const m of ms) out.push(M[m] || `M${m}: machine-specific function`);
  if ("T" in v) out.push(`Select tool number ${v.T}`);
  if ("S" in v) out.push(`Spindle speed ${v.S} rpm`);
  if ("F" in v) out.push(`Feed rate ${v.F} per minute`);
  if ("H" in v && gs.includes(43)) out.push(`Using length offset register H${v.H}`);
  if (comment) out.push(`Comment: "${comment.trim()}"`);
  if (/^\s*O\d+/i.test(raw)) out.unshift("Program number / subprogram label");
  if (raw.trim() === "%") out.push("Start/end-of-file marker");
  return out.length ? out : ["(blank line)"];
}

const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function highlight(line) {
  return esc(line)
    .replace(/(\(.*?\)|;.*$)/g, '<i class="c">$1</i>')
    .replace(/\b(G\d+(?:\.\d)?)/g, '<i class="g">$1</i>')
    .replace(/\b(M\d+)/g, '<i class="m">$1</i>')
    .replace(/\b(T\d+)/g, '<i class="t">$1</i>') || " ";
}

// one shared tooltip that follows the mouse over any [data-gline] element
let tip;
export function attachExplainer(container) {
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "gtip";
    tip.hidden = true;
    document.body.appendChild(tip);
  }
  container.addEventListener("mousemove", (e) => {
    const el = e.target.closest("[data-gline]");
    if (!el) { tip.hidden = true; return; }
    const lines = explainLine(el.textContent);
    tip.innerHTML = `<b>${esc(el.textContent.trim() || "(blank)")}</b><ul>${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
    tip.hidden = false;
    const x = Math.min(e.clientX + 16, innerWidth - tip.offsetWidth - 8);
    const y = e.clientY + 18 + tip.offsetHeight > innerHeight ? e.clientY - tip.offsetHeight - 12 : e.clientY + 18;
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  });
  container.addEventListener("mouseleave", () => { tip.hidden = true; });
}
