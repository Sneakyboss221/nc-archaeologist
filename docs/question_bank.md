# Question bank: what the professor may ask, and what to say

Each question has a **short answer** (say this first) and, where useful, a **follow-up** if they push.
🖥 means "show this on the dashboard": point at the screen instead of talking.

---

## Part 1: Basics (CNC, G-code, CIM)

**1. What is CNC?**
A machine tool (mill, lathe) whose movements are controlled by a program instead of a person turning handles. CNC stands for Computer Numerical Control.

**2. What is G-code?**
The language CNC machines read, standardised as ISO 6983. Each line is a command, e.g. `G01 X10 Y5 F300` = cut in a straight line to X10, Y5 at 300 mm/min.
🖥 G-code tab → hover any line.

**3. What do G00, G01, G02, G03 mean?**
G00 = rapid move (fast, not cutting). G01 = straight cutting move. G02 / G03 = clockwise / counter-clockwise arc.

**4. What are G90 and G91?**
G90 = absolute coordinates (every position is measured from the part zero). G91 = incremental (each move is relative to the previous position). The same part can be written either way, which is one reason the text of programs differs so much.

**5. What are G20 / G21?**
G20 = inch units, G21 = millimetres. We convert everything to mm internally.

**6. What is a canned cycle (G81, G83)?**
A one-line shortcut for a whole drilling routine. `G83 X10 Y5 Z-12 R2 Q3` = go to X10 Y5, rapid down to R=2, then peck-drill to Z−12 in 3 mm steps, then retract. Every following X/Y line drills another hole.

**7. What is M06? M03? M30?**
M06 = tool change, M03 = spindle on clockwise, M05 = spindle stop, M08/M09 = coolant on/off, M30 = end of program.

**8. What is CIM?**
Computer-Integrated Manufacturing: connecting design (CAD), process planning (CAPP), CNC programming (CAM) and the machine (CNC) through shared digital information, so data flows through the whole factory.

**9. What is CAPP?**
Computer-Aided Process Planning: deciding the sequence of operations, tools, speeds, feeds and times to make a part. Two types: *retrieval* (reuse the plan of a similar part) and *generative* (create a plan from part features). Our process sheet is a plan recovered **backwards** from the program.

**10. What is Group Technology?**
Grouping similar parts into **families** so they can share machines, tools, fixtures and set-ups. Classic coding systems include Opitz. It's used to design manufacturing cells and to reuse plans. (Syllabus Module 6.)

**11. What is a part family?**
A set of parts similar in shape and/or in how they're made, e.g. all flanges with a bolt circle.

**12. What is FMS?**
Flexible Manufacturing System: a group of CNC machines linked by automated material handling and controlled by a computer, able to make a variety of parts. GT families are how you decide which parts an FMS cell should make.

**13. What is STEP / STEP-NC?**
STEP (ISO 10303) is a neutral CAD data format. STEP-NC (ISO 14649) describes *what* to machine (features, operations) instead of low-level G-code moves. Our feature recognition is a first step toward converting legacy G-code into STEP-NC-style features; that's listed as future work.

**14. What is a digital twin?**
A virtual model that mirrors a physical process. Our dexel simulation is a simple digital twin of the machining: it replays what the machine would do to the stock.

---

## Part 2: The problem and the idea

**15. What problem are you solving?**
Factories have thousands of old CNC programs whose CAD files are lost. Nobody knows what each program makes, which programs are similar, or which can be reused. We read only the G-code and recover the part, the process plan and the part family.

**16. Why does that matter in industry?**
- **Reuse:** a new order resembles a part already made, so the proven program can be adapted instead of reprogramming from scratch.
- **GT:** forming families helps design machine cells and standardise tooling.
- **Digital transformation:** turning an unreadable archive into searchable data.

**17. Why not just compare the G-code text?**
The same part can be written in completely different ways: different machines (Fanuc vs Haas), mm or inch, absolute or incremental, arcs or many tiny lines, and any rotation or position on the table. Text comparison groups programs by **writing style**, not by part.
🖥 "Same part ×4" page. Numbers: text ARI 0.07 for families, but 0.61 for dialects.

**18. Why not just read the coordinates? Why simulate?**
The coordinates are the **tool centre path**, not the part. The part is what remains after a round cutter of a certain size sweeps along that path. Without simulating the cutter, you can't know where material was removed or how wide a slot is.

**19. What is new (novel) here?**
Two things nobody had combined:
1. Reverse-engineering parts from G-code has only been done for **3D printing** (Tsoutsos 2017; Kiński & Sobieski 2020). In printing, the toolpath *is* the part. In milling, the part is what's *left*, which is a harder problem.
2. Group Technology classification has always needed CAD models, drawings or route sheets. To our knowledge, we're the first to form GT families **directly from CNC programs**.

**20. Who else has done similar work?**
- 3D-printing toolpath reconstruction (Tsoutsos et al. 2017; Kiński & Sobieski 2020).
- CAD-model retrieval for process-plan reuse (Pitta & Marefat 2005).
- Feature recognition from CAD solids (Han, Pratt, Regli 2000).
- LLMs that *generate* G-code (GLLM, 2025).

All of these either target printing or need the CAD model. We work from the G-code alone.

---

## Part 3: How it works (method)

**21. Walk me through the pipeline.**
Six steps: parse G-code → identify cutters → simulate material removal → build process sheet → recognise features → fingerprint and cluster into families.
🖥 "How it works" page: read along.

**22. How does the parser work?**
It's a **modal state machine**. G-code is modal: a `G1` stays active until changed, so a line like `X10` still means "cut to X10". We track motion mode, units, absolute/incremental mode, feed, spindle, current tool and drilling-cycle state. Arcs are cut into short straight chords (0.05 mm tolerance). Canned cycles are expanded into real moves. Subprograms in the same file are inlined.

**23. What happens with things it can't handle?**
It raises a **warning** instead of guessing: cutter compensation (G41/G42), calls to subprograms stored in other files, non-XY planes, several work offsets, lathe programs.
🖥 Run sample "Hand-written plate with cutter compensation" → yellow banner.

**23b. What about macro / parametric programs?**
They're executed. A macro layer runs before the interpreter: variables (`#1`, `#<scale>`), expressions in brackets, loops (`repeat`, `while`, Fanuc `WHILE…DO`), if/else, subroutines with arguments, and polar coordinates (`@` radius, `^` angle).
🖥 Run sample "Hand-written Fanuc Macro B bolt circle" → 6 holes on PCD 80.

**24. What is a dexel / height map?**
The raw block is a grid of tiny columns, each 0.25 mm wide. Each column stores its height. For every cutting move, every column under the cutter is lowered to the cutter's tip height plus its shape. What's left at the end is the part.
Formula: `height = min(height, tool tip + tool profile(r))`

**25. How do you handle different tool shapes?**
Flat end mill: the profile is flat. Ball end: `R − √(R² − r²)`. Drill: a 118° cone. Chamfer tool: 90° cone.

**26. Why 2.5D and not full 3D?**
3-axis prismatic parts (plates, pockets, holes) can be described by one height per XY point, so it's fast (about 1–2 s per program) and adequate. The limit: undercuts and 5-axis parts can't be represented. It's listed as a limitation; a tri-dexel model would be the extension.

**27. How do you get the tool size if the program doesn't say?**
We look for a **zig-zag (raster) pattern**: at least 3 parallel back-and-forth passes at the same depth. The gap between passes is the step-over, and CAM usually uses step-over ≈ 50% of the diameter. So D ≈ step-over ÷ 0.5, snapped to a standard size. We require that pattern so two separate parallel slots aren't mistaken for a raster.

**28. How accurate is that?**
On comment-free programs it found sizes for 55% of milling tools; 82% of those were within one standard size, 43% exact. The rest fall back to a default and the program is flagged.

**29. Can you infer drill sizes?**
No. A drill just plunges, so the path carries no information about its diameter. We assume a default and warn. That's an honest limitation.

**30. How do you know where the stock edge is?**
G-code never states the stock size. If there is a facing pass, we estimate it from that: facing passes usually overrun the block by about one cutter radius, so we shrink the facing envelope accordingly. Without facing, we only know the machined area.

**31. How is the process sheet built?**
The program is split at each tool change. Each block is named from *what it removed*:
- shallow over most of the top → facing
- a ring around a large uncut island → profiling
- open to the stock edge → step milling
- long and one cutter wide → slotting
- round → bore
- plunges only → drilling
- otherwise enclosed → pocketing

Cycle time = Σ(distance ÷ feed) + rapids at 10 m/min + 8 s per tool change.

**32. How do you recognise features?**
We find the flat floor depths, slice the depth map between them and take connected regions, keeping nesting: a hole inside a pocket becomes a child feature. Each region is labelled by shape: circular and small = hole, elongated = slot, open to the edge = step, encloses an uncut island = island pocket or outline, otherwise pocket.

**33. How do you tell a round pocket from a square one?**
Circularity alone isn't enough. We also use the **fill ratio**: a circle fills about 78.5% of its bounding box, a rounded square about 100%.

**34. How do you detect a bolt circle?**
If 3 or more holes are at the same distance from their common centre AND evenly spaced around it. (Rectangle corners are also on a circle, so the even spacing matters.)

**35. What is the fingerprint?**
75 numbers per program describing *what it makes*:
- **Geometry (46):** depth histogram, 7 Hu moments, radial depth profile, feature counts, elongation, hole size, bolt-circle flag.
- **Process (29):** share of time per operation type, operation counts, tool counts.

**36. Why Hu moments?**
They're 7 numbers that describe a shape and **don't change when the shape is moved, rotated or scaled**. A part clamped at 37° on the table therefore gets the same fingerprint as one clamped straight.

**37. Why remove the facing pass and the outer profile from the fingerprint?**
Whether a part was faced or profiled depends on the raw blank supplied, not on the design. Keeping them made the same design split into two families. We fixed that on the development set.

**38. How are families formed?**
**Ward agglomerative clustering**, which repeatedly merges the two groups whose merger adds the least spread. With unknown k, we pick k by the silhouette score, and it picked 9 (the true number is 8). We also run **HDBSCAN**, which finds the number of families by itself and flags unusual programs as outliers.

**39. What is t-SNE?**
A way to draw the 75-number fingerprints on a 2D map so that similar programs sit close together. It's for display only; the clustering doesn't use it.

**40. How does "find similar" work?**
Cosine similarity between fingerprints: the angle between the two 75-number vectors. A closer angle means a more similar part.

**41. How do you assign a newly uploaded program to a family?**
We compute its fingerprint, scale it the same way as the archive, and pick the family with the nearest centre. The "fits X%" number shows how typical that distance is among the family's own members.

---

## Part 4: Results

**42. What dataset did you use?**
No public labelled dataset of CNC programs exists, so we generated a benchmark: 8 part families, a mini CAM system, and 4 G-code dialects, with random sizes, rotation and work origin. That's 1,200 programs: 600 for development and 600 held out for testing.

**43. Isn't that data fake?**
It's synthetic, and the paper says so openly. It's standard when no labelled data exists, and it gives exact ground truth. We made it hard on purpose: four dialects, random rotation and origin, missing tool comments. We tuned only on the development set and measured once on the held-out set. We also tested **15 real, unmodified open-source programs from the LinuxCNC project**; see question 43b. Quantitative validation on a labelled shop archive is the next step.

**43b. Did you test on real programs?**
Yes: 15 unmodified example programs from the LinuxCNC project (open source, GPL-2.0), including a 4,700-line 3D carving, a motor mount from a workshop machine, and bolt circles. 13 were analysed; the other 2 aren't part programs (a remap subroutine and an empty template) and were correctly rejected. Since there's no ground truth, we checked results against what each file's comments say: `polar` should have 26 holes and we found 26; `hole-circle` has a 3-inch bolt circle and we measured PCD 76 mm (3 in = 76.2 mm). Testing on them also exposed parametric programming, loops and polar coordinates, which the synthetic data didn't have, so we extended the interpreter to run them.
🖥 Run sample "REAL (LinuxCNC): 3D carving" or "REAL (LinuxCNC): stepper-motor mount".

**44. What does ARI 0.797 mean?**
ARI (Adjusted Rand Index) measures how well discovered clusters match the true families: 1 = perfect, 0 = random. 0.797 is strong. Text comparison scores 0.074, essentially random.
🖥 Results page.

**45. What is P@5 = 0.939?**
Of the 5 most similar programs the system returns, 93.9% are truly from the same family.

**46. How accurate is the part reconstruction?**
IoU 0.999 (median depth error 0.11 mm) when tools are named in the program, and 0.925 over all programs. It drops to 0.71 when tool sizes must be guessed.

**47. What is IoU?**
Intersection over Union: the overlap between the rebuilt removed region and the designed one, divided by their union. 1 = identical.

**48. Why does the combination beat geometry-only and process-only?**
Some families look alike in shape but are machined differently, and vice versa. Each block fixes the other's confusions: ARI 0.62 (geometry) and 0.57 (process) become 0.80 together.

**49. What shows dialect invariance?**
We posted the same 40 parts in all 4 dialects with different fixturing. Same part, different dialect: similarity 0.92. Different parts of the same family: 0.50. Other families: −0.08. On the test set, 75% of each program's nearest neighbours are written in a *different* dialect, and 94% of those are still the right family.
🖥 "Same part ×4" page.

**50. Where does it fail?**
- Programs without tool comments (recovery drops).
- Step recall is 80%.
- Slot precision is 83%: some pockets get called slots.
- One hand-written program was mislabelled (pockets at the edge of an unfaced part were called steps).
- Real files rarely state tool sizes, so their dimensions use a default (flagged).
- Cutter compensation and subprograms stored in other files aren't executed (flagged).

**51. How fast is it?**
About 1.7 s per program on a laptop, run in parallel across CPU cores. All 600 programs take about 2–4 minutes.

**52. Why didn't a finer grid improve accuracy?**
The error comes mostly from modelling factors (guessed tool sizes, the stock estimate), not grid size. 0.5, 0.25 and 0.1 mm cells give the same RMS error, but 0.1 mm is 10× slower.

---

## Part 5: Tough and "trap" questions

**53. Did you write all this yourself?**
Answer in terms of what you understand and can explain. I designed the approach and the experiments, built the system in Python using standard libraries (NumPy, SciPy, scikit-learn) and used AI coding assistance during development. I can explain every component, and the code is organised by pipeline stage.
*(Only say what's true for you. Being open about tools is safer than being caught out.)*

**54. Why not just use an AI / LLM?**
LLMs generate G-code but don't reliably *understand* geometry; even the GLLM paper notes that G-code carries no semantic geometry. Our approach is deterministic and physical: it simulates the cutter, so results are explainable and verifiable. An LLM could be added later for writing natural-language reports.

**55. Why these 8 families?**
They're common prismatic part types (plates with hole patterns, pockets, slots, flanges, steps, trays, keyways, bosses) that cover the main milling features: holes, pockets, slots, steps and islands.

**56. What happens with a 5-axis program?**
Not supported. The height map can't represent undercuts. We'd flag non-XY planes; a tri-dexel model is future work.

**57. What about cutter compensation (G41/G42)?**
With compensation, the program describes the part edge and the controller shifts the path by the tool radius. We can't see the radius in the file, so we flag it: the geometry is off by one radius. Resolving it is future work.

**58. Can it handle a lathe program?**
No, and it detects that: it warns "looks like a lathe (turning) program".
🖥 Sample: lathe_program.nc.

**59. How would a factory actually use this?**
Run it once over the whole program archive. Then:
1. Search "have we made something like this?" when quoting a new part.
2. Use the families to plan cells and standardise tools.
3. Use the recovered parts and process sheets as documentation for legacy parts.

**60. What was the hardest problem?**
Telling the real part apart from cuts made in empty air, because G-code never says how big the raw block was. We estimate the stock outline from the facing pass. Another was tool-size inference without mistaking parallel slots for a zig-zag.

**61. What bugs did you find?**
One example: section comments like `(POCKET: 10 MM END MILL)` were first read as tool definitions and assigned to the wrong tool. Now a comment only defines a tool if it names it or sits on the tool-change line.

**62. How do you know you didn't overfit?**
All tuning was done on one dataset (seed 7), and the final numbers come from a separate held-out dataset (seed 11) measured once.

**63. Why HDBSCAN and Ward both?**
Ward needs the number of families but gives clean groups. HDBSCAN finds the number itself and flags odd programs, which is useful for spotting one-off parts.

**64. What would you improve with more time?**
1. Validate on a labelled shop archive (with known part families).
2. Resolve cutter compensation and read tool tables.
3. Use 5-axis / tri-dexel models.
4. Export STEP-NC features.
5. Learn the fingerprint from data.

**65. How does this connect to your syllabus?**
- Module 2: CNC.
- Module 3: part programming.
- Module 4: real-time CAM simulation / digital twin.
- Module 5: CAPP and STEP.
- Module 6: Group Technology and FMS.
- Module 7: Big Data and digital transformation.

**66. Is the 3D animation real or just a video?**
It's real. It replays the actual toolpath in the browser and lowers the height grid move by move, ending exactly on the server's result.
🖥 Playground: change a number and run.

**67. Can I (the professor) test it?**
Yes. Type or edit a program in the Playground, or upload any `.nc` file.

**68. What's the accuracy of hole positions?**
0.18 mm mean error; 100% of holes found, 99.9% precision.

**69. Why is "fits X%" sometimes low for an upload?**
It compares the distance to the family centre with the family's own members. Comment-free programs with guessed drill sizes sit a bit further out, but they still go to the right family.

**70. What libraries did you use?**
Python: NumPy, SciPy, scikit-learn, trimesh, FastAPI. (Perimeter and Hu moments are implemented directly in NumPy.) Web: Three.js (3D) and Plotly (charts). The paper is in LaTeX (IEEEtran).
