# Learning guide: understand the whole project from zero

Read this in order, with the dashboard open next to you. Allow about 1.5 hours.
Every "▶ Try it" step is something to do on the dashboard while you read.

---

## Chapter 1: CNC and G-code (20 min)

### 1.1 What a CNC mill does
A milling machine holds a spinning **cutter** (like a drill bit that also cuts sideways) and moves it through a block of metal, the **stock**, to carve a shape. A **CNC** mill moves on its own, following a program. It has three axes:
- **X**: left / right
- **Y**: forward / back
- **Z**: up / down. **Z = 0 is the top of the stock**, so cutting into the metal means negative Z.

### 1.2 What G-code looks like
A program is a list of lines. Here are real lines from our sample `samples/playground_starter.nc`:

```
T2 M06 (T2 D10 FLAT ENDMILL)   ← change to tool 2, a 10 mm flat end mill
S6000 M03                      ← spin it at 6000 rpm, clockwise
G0 X-15 Y-10 Z5                ← move fast (rapid) to X-15 Y-10, 5 mm above the metal
G1 Z-6 F120                    ← cut straight down to 6 mm deep, at 120 mm/min
G1 X15 F600                    ← cut sideways to X15 at 600 mm/min
```

The letters you need:

| Letter | Meaning |
|---|---|
| **G** | what kind of move or mode (G0 rapid, G1 cut, G2/G3 arcs, G81/G83 drilling) |
| **X Y Z** | where to go |
| **F** | feed rate (how fast it cuts) |
| **S** | spindle speed (rpm) |
| **T** | tool number; **M06** = change to it |
| **M** | machine functions (M03 spindle on, M05 off, M08 coolant, M30 end) |
| `( … )` | comment, ignored by the machine |

**Modal** means a code stays active until changed. After `G1`, the line `X15` still means "cut to X15".

▶ **Try it:** Explorer → G-code tab → hover over lines. The tooltip translates each one.

### 1.3 Why the same part can look completely different as G-code
- One machine writes `G01 X10.000`, another writes `X10.` (formatting).
- One uses mm (G21), another inches (G20).
- One gives absolute positions (G90), another gives each move relative to the last (G91).
- One writes an arc as `G2 X.. I.. J..`, another as 200 tiny straight lines.
- The part can be clamped rotated, with the zero point at the centre or at the corner.

▶ **Try it:** open the "Same part ×4" page. Four totally different texts, one part.

### 1.4 Where this fits in CIM
CIM chain: **CAD** (design) → **CAPP** (process plan) → **CAM** (generates the G-code) → **CNC** (machine runs it).
In old factories, only the last link survives: the G-code. Our project rebuilds the chain **backwards**.

---

## Chapter 2: What the project does, on one program (15 min)

▶ **Try it:** Explorer → "Run a sample…" → *Flange, Fanuc dialect*.

Watch the processing window. Each line is one stage:
1. **Parse G-code:** the text becomes a list of straight moves.
2. **Identify cutters:** the size and type of each tool.
3. **Simulate material removal:** a grid of heights is carved by the tools.
4. **Build process sheet:** the operations, in order, with times.
5. **Recognise features:** holes, pockets, bolt circle.
6. **Compute fingerprint:** 75 numbers that describe the part.

Then:
- **3D view:** the rebuilt part. Press **▶ Simulate machining** to watch it being cut.
- **Process sheet:** the plan (tool, operation, depth, feed, time).
- **Features:** what shapes were found.
- **Similar programs:** the closest parts in the archive.
- **Banner:** which family it belongs to; the ★ on the map is where it landed.

That is the whole project in one minute. The rest of this guide explains each stage.

---

## Chapter 3: How each step works (40 min)

### 3.1 Parsing
The parser reads line by line and keeps a "memory" (the **state**): current units, absolute or incremental mode, active motion type, current tool, feed. For each line it updates the state and, if the line moves the machine, records a straight segment from the old position to the new one.
- **Arcs** (G2/G3) are cut into short straight pieces, no more than 0.05 mm off the true curve.
- **Drilling cycles** (G81/G83) are expanded: one line `G83 X10 Y5 Z-12 R2` becomes rapid to the hole → down to R → feed to Z−12 → back up.
- **Subprograms** in the same file are pasted in where they're called.
- **Parametric (macro) programs** are run first: variables like `#<scale>` are filled in, `[expressions]` are calculated, and loops, if/else and subroutines are executed, producing plain G-code. **Polar coordinates** (`@` radius, `^` angle) are also understood.
- **Things we can't run** (cutter compensation G41/G42, subprograms in other files, lathe code) give a **warning** instead of a guess.

▶ **Try it:** Run a sample → "Hand-written Fanuc Macro B bolt circle". A loop computes 6 hole positions with COS and SIN, and the system finds 6 holes on an 80 mm circle. Then try "Hand-written plate with cutter compensation" to see a warning.

### 3.2 Finding the cutter size
To rebuild the part we need each cutter's diameter.
- **Easy case:** the program says so in a comment, `(T2 D10 FLAT ENDMILL)`.
- **Hard case:** no comment. Look at how the tool moves. CAM clears a pocket in a **zig-zag**, and the gap between neighbouring passes (the **step-over**) is usually about half the cutter diameter. So: measure the gap, double it, round to a standard size (6, 8, 10, 12 mm …).

```
→→→→→→→→→→→→
            ↓  ← step-over = 5 mm
←←←←←←←←←←←←
↓                ⇒ cutter ≈ 10 mm
→→→→→→→→→→→→
```

We only trust a real zig-zag (3+ alternating passes joined by short moves), so two separate slots side by side don't fool it.

▶ **Try it:** Playground → "Remove tool comment (forces inference)" → Run. The process sheet says "inferred".

### 3.3 The simulation (the heart of it)
Imagine the stock as a field of tiny square columns, each 0.25 × 0.25 mm, all starting at height 0, the top of the block.
For every cutting move, every column the cutter passes over is pushed down to the cutter's bottom:

```
height = min(current height, cutter tip height + cutter shape)
```

- Flat end mill: flat bottom.
- Ball end mill: rounded bottom.
- Drill: pointed (118°) bottom.

After the last move, the remaining columns **are the part**. The 3D view simply draws this field. This kind of model is called a **dexel** or **height map**; it's 2.5D because each XY point has one height. That's enough for 3-axis parts, but not for undercuts.

▶ **Try it:** ▶ Simulate machining, at 1× speed. Watch the columns go down under the cutter.

### 3.4 Process sheet (CAPP backwards)
Split the program at every tool change, and look at what each tool removed:

| What it removed | Name |
|---|---|
| a thin layer over the whole top | facing |
| a ring around the part | profiling (cutting the outline) |
| only straight plunges | drilling |
| a long strip one cutter wide | slotting |
| a round hole bigger than a drill | bore |
| a region open to the side | step milling |
| an enclosed region | pocketing |

Time = distance ÷ feed rate for each cutting move, plus fast moves and tool changes.

### 3.5 Feature recognition
Look at the depth map like a contour map. Find the depths where there are flat floors (pocket bottoms, steps). Slice between those depths and take each connected region. Then classify it by shape:
- **round + small** → hole
- **round + big** → circular pocket
- **long + narrow** → slot
- **open to the edge** → step
- **ring around an uncut island** → island pocket, or the outline if the island is the whole part
- otherwise → pocket

Holes at equal distances around a centre with even spacing form a **bolt circle**, and we report its diameter (PCD).

### 3.6 Fingerprint and families
To compare parts, each one is turned into **75 numbers**, its fingerprint:
- **Shape numbers:** how deep the cuts are (a histogram), 7 **Hu moments** (shape descriptors that don't change if the part is rotated or moved), how the depth spreads out from the centre, how many holes / pockets / slots there are, and so on.
- **Process numbers:** what share of time is facing, pocketing, drilling …; how many tools.

Two parts are similar if their 75 numbers are close; we use the angle between the two lists (cosine similarity).
**Families:** a clustering method (Ward) groups programs with close fingerprints. A second method (HDBSCAN) finds groups by density and marks programs that fit nowhere as **unusual**.
The **map** squeezes the 75 numbers into 2D for display (t-SNE): close dots are similar programs.

▶ **Try it:** How it works page → step 6 shows the fingerprint as a bar chart.

---

## Chapter 4: What the results mean (15 min)

▶ **Try it:** open the Results page.

### 4.1 How we tested
- There is no public dataset of labelled CNC programs, so we **generated** 1,200 programs: 8 part families, random sizes, four G-code dialects, random rotation and origin. Because we generated them, we know the true answer for each one.
- 600 were used while building the system (development set). The other 600 were used **once**, at the end (test set). This prevents "cheating" by tuning on the test.

### 4.2 The numbers
| Number | Meaning | Ours | Compare with |
|---|---|---|---|
| **ARI** | agreement of found families with true families (1 = perfect, 0 = random) | **0.80** | text comparison: 0.07 |
| **P@5** | of 5 "similar" results, how many are truly the same family | **93.9%** | text: 56% |
| **IoU** | overlap of rebuilt part with designed part (1 = identical) | **0.999** with tool comments | 0.71 without |
| Same part, 4 dialects | fingerprint similarity | **0.92** | different families: −0.08 |
| Holes | found / correct | 100% / 99.9% | position error 0.18 mm |

### 4.3 The key insight in one sentence
**Text comparison groups programs by how they're written; we group them by what they make.**
Text clusters match the *dialect* labels (ARI 0.61) but not the families (0.07).

### 4.4 Honest limits (say these confidently)
- The benchmark data is synthetic. We also ran 15 real open-source LinuxCNC programs (13 analysed, and they match their own comments), but those have no family labels. A labelled shop archive is the next step.
- Without tool comments, accuracy drops.
- 3-axis parts only (2.5D).
- Cutter compensation and subprograms stored in other files are flagged, not executed.

---

## Checklist: can you explain these in one sentence each?
- [ ] What G-code is, and what G0, G1 and G83 mean
- [ ] Why the same part can look different as text
- [ ] Why we simulate instead of just reading coordinates
- [ ] How the height-map simulation works
- [ ] How we guess a cutter's size from the step-over
- [ ] What the fingerprint is and why Hu moments are used
- [ ] What ARI = 0.80 means and why text scored 0.07
- [ ] Two honest limitations

If you can tick all of these, you're ready. Then read `question_bank.md`.
