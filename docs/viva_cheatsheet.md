# Viva cheat sheet: NC-Archaeologist

## The 30-second pitch
Shops have thousands of old CNC programs and no CAD files. Nobody knows what each program makes or which parts are similar. We read **only the G-code**, simulate the machining to rebuild the part, write the process sheet, and group programs into **Group-Technology part families**. A comparison works on *what a program makes*, not *how it's written*, so it holds across Fanuc, Haas, inch/incremental and other dialects.

## Syllabus mapping
| Module | Where it shows up |
|---|---|
| 2: CNC (axes, controllers) | modal G-code interpreter, G90/G91, G20/G21, work offsets |
| 3: CAM / part programming | G0–G3, canned cycles G81–G83, arcs (IJK and R), subprograms, cutter comp |
| 4: Intelligent machining, real-time CAM simulation | dexel material-removal simulation, cutter-size inference |
| 5: CAPP, STEP, quality control | automatic process sheet, feature recognition, STEP-NC as future work |
| 6: Group Technology / FMS | part-family formation (the core result) |
| 7: Big Data, digital transformation | turning an opaque archive into searchable data, clustering, t-SNE |

## How each part works (be able to draw these)

**1. Parser.** A modal state machine. G-code is *modal*: `G1` stays active until another motion code appears, so a line like `X10` still means "feed to X10". We track motion mode, units, absolute/incremental mode, feed, spindle, tool and canned-cycle state. Arcs are cut into short straight chords (0.05 mm tolerance). Canned cycles are expanded into rapid → R-plane → feed to depth → retract. Anything we cannot execute properly (G41/G42 cutter comp, macros `#1=…`, external subprograms, lathe code) produces a **warning instead of a guess**.

**2. Dexel simulation.** The stock is a 2D grid of heights (one height per 0.25 mm cell: a "height map", or 2.5D dexel model). For every cutting move we lower each cell under the cutter to the cutter's tip height plus its profile:
- flat end mill: profile 0
- ball end: `R − √(R² − r²)`
- drill: cone with a 118° point

For flat cutters the lowest point along a ramping move is computed exactly, in closed form. Limitation: no undercuts, so it suits 3-axis prismatic parts only.

**3. Tool-size inference (when there are no tool comments).** We look for a *raster run*: at least 3 parallel, alternating passes at one Z, joined by short link moves with no rapid in between. The spacing between passes is the **step-over**, and CAM usually uses step-over ≈ 50% of the diameter, so D ≈ 2 × spacing, snapped to a standard cutter size. Requiring at least 3 alternating passes stops us from confusing two separate parallel slots, or the two sides of a profile loop, with a raster.

**4. Process sheet.** The program is split at each tool change. Each block is classified from *what it removed*:
- facing: shallow and covers most of the area
- profiling: a ring around a big uncut island (the part)
- island pocket: a ring around a small island
- step: open to the stock edge
- slot: long and about one cutter wide
- bore: round
- pocket: anything else enclosed
- drilling: plunge-only moves

Cycle time = Σ(length / feed) + rapids at 10 m/min + 8 s per tool change.

**5. Stock footprint.** G-code never states the stock size. Facing passes overrun the stock by about one cutter radius at their ends, so: stock ≈ facing-path envelope, shrunk by R along the passes and grown by R/2 across them.

**6. Feature recognition.** Find the flat-floor depths ("plateaus"; sloped cells such as drill cones are ignored). Slice the depth map between those levels and take connected regions. Each region's parent is the region containing it one level up (nesting). Labels:
- hole: circular and small
- circular pocket: circular and larger
- slot: elongated
- step: open to the edge
- island pocket / outline: encloses an uncut island

**Fill ratio trick:** a circle fills about 78.5% of its bounding box, a rounded square about 100%. That separates square pockets from round ones, because squares also have equal principal axes.

**7. Fingerprint.**
- Geometry: depth histogram, **7 Hu moments**, radial depth profile, feature counts, elongation, hole size, bolt-circle flag. All are rotation-invariant (Hu moments are invariant to rotation, scale and translation).
- Process: share of time per operation type, operation counts, tool counts.
- We remove facing and the outer profile ring first, because whether a part was profiled depends on the blank supplied, not the design.
- Each block is standardised, weighted 50/50 (chosen on the *development* set) and normalised by its dimension.

**8. Families.**
- **Ward** agglomerative clustering merges the pair of clusters whose merger increases the within-cluster variance least. k comes from the silhouette score.
- **HDBSCAN** is density-based: it finds the number of families itself and marks unusual programs as outliers.
- **t-SNE** produces the 2D map, for display only.
- Similarity search uses cosine nearest neighbours.

## Metrics (know what they mean)
- **IoU**: overlap / union of the recovered vs designed removed region. 1 = perfect.
- **RMS depth error**: average depth mismatch in mm.
- **ARI (adjusted Rand index)**: agreement between our clusters and the true families, corrected for chance. 0 = random, 1 = perfect.
- **NMI**: normalised mutual information. Also 0–1.
- **Purity**: share of programs in their cluster's majority family.
- **P@5**: of the 5 most similar programs returned, the fraction from the correct family.
- **mAP**: mean average precision over the whole ranking.

## Results (held-out test set, 600 programs; source: `results/metrics.json`)
| What | Number | How to say it |
|---|---|---|
| Programs that crashed the pipeline | 0 / 600 | robust |
| Part recovery IoU, all programs | 0.925 | |
| … when tool sizes are in comments | **0.999** (median RMS 0.11 mm) | essentially exact |
| … when tool sizes had to be inferred | 0.709 | the weak spot, and we say so |
| Hole detection | recall 100%, precision 99.9%, position error 0.18 mm | |
| Family discovery, full fingerprint | **ARI 0.797**, NMI 0.822, purity 0.907 | |
| Text TF-IDF baseline | ARI 0.074 | text finds the *dialect* (ARI 0.61 vs dialect labels), not the part |
| Process-only / geometry-only | ARI 0.572 / 0.618 | combining both is best |
| Retrieval | P@5 0.939, mAP 0.851 | "have we made this before?" works |
| Neighbours from a *different* dialect | 74.8%, of which 94.0% are the right family | dialect-invariant |
| Same part posted in 4 dialects | cosine 0.92 vs 0.50 (same family) vs −0.08 (other families) | |
| Unknown k (silhouette) | picks k = 9 (true 8), ARI 0.770 | |
| HDBSCAN | 10 dense families, ARI 0.815 on inliers, 12.7% flagged unusual | |
| Tool inference (comment-free dialect) | covers 55.5% of milling tools; 43% exact, 82% within one standard size | |
| Runtime | 1.7 s per program on average | |

**Honest weak spots to admit if asked:**
- When tool sizes default, accuracy drops (IoU 0.71).
- Step recall is 0.80.
- Slot precision is 0.83: some pockets get called slots.
- Two hand-written programs were mislabelled (pockets at the edge of an unfaced part were called steps).

## Likely questions and answers
1. **"Isn't the data fake?"** The benchmark is synthetic, and the paper says so openly. That's standard when no labelled public dataset exists, and it gives exact ground truth. We made it hard on purpose: 4 dialects, random rotation and origin, missing tool comments. We tuned on one dataset (seed 7) and reported on a separate held-out one (seed 11). We also tested hand-written vendor programs that our generator did not produce.
2. **"Why not just compare the G-code text?"** The same part can be written in inch or mm, absolute or incremental, with arcs or chords, at any rotation. The text baselines in the ablation show it: they mostly learn the *dialect*, not the part.
3. **"How do you know the stock size?"** We don't, in general. We estimate it from the facing toolpath when one exists, otherwise we use the machined area. This is listed as a limitation.
4. **"What about G41/G42?"** The coordinates are then the part edge, not the tool centre. We flag it and warn that the geometry is approximate (offset by one radius). Resolving it properly is future work.
5. **"Why Hu moments?"** They are invariant to rotation, translation and scale, so a part clamped at 37° on the table gives the same fingerprint.
6. **"Why two clustering methods?"** Ward needs k but gives clean, balanced families. HDBSCAN finds k itself and flags odd programs, which is useful for spotting one-off parts in an archive.
7. **"Accuracy of tool inference?"** Report coverage, exact match and within-one-size from the results. Drills can't be inferred from geometry, because a hole looks the same whatever its history.
8. **"How is this CIM?"** It reconnects the broken CAD → CAPP → CAM → CNC chain *backwards*: CNC program → recovered geometry → process plan → GT family. STEP-NC export would close the loop.
9. **"Runtime?"** About a second per program on a laptop, run in parallel across CPU cores.
10. **"What would you do next?"** Validate on a real shop archive, add 5-axis (tri-dexel), execute Macro B, and export STEP-NC.
