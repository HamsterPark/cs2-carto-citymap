# Solving Grade Separation vs. Continuity in a Pure Python/Matplotlib City-Map Renderer

## TL;DR
- **Yes, there is a standard, well-founded algorithm that solves both goals simultaneously: assign each *whole segment* a consistent integer rendering layer by solving a *system of difference constraints* (connected segments forced equal; interior-crossing pairs forced to differ by ≥1 in elevation order), solve it with Bellman–Ford / longest-path-on-a-DAG, break inevitable cycles (spiral ramps) with a minimum-feedback-arc heuristic, then render strictly layer-by-layer with a global two-pass (all casings, then all fills) inside each layer.** This is exactly the abstraction professional engines use (OSM-Carto's `group-by: layernotnull` + SQL `ORDER BY z_order`), generalized so the layer is a property of the path, not the crossing.
- **The climbing-ramp cut is eliminated** because the ramp is one connected component, so the connectivity constraints force its entire length into a single layer (it is never cut by roads below it), and the one place it changes layer is handled by a short fill *overshoot* across the transition node so no seam shows.
- **Build the connectivity graph robustly by snapping endpoints with a KDTree/grid tolerance (≈0.5–1 m) before union-find; detect true overpasses with a shapely STRtree interior-intersection test (crosses but does not share a node); and treat cycles where a single global integer layer is infeasible by falling back to local per-crossing caps only inside the offending bi-connected component.**

## Key Findings

1. **The dilemma is real but standard.** Using elevation→zorder alone cannot distinguish "connected" from "crossing," because in 2D both are adjacency. Every approach the user tried fails because the *layer was a property of a point or a single feature, not of the connected path*. The fix is to compute a per-segment integer layer by global constraint solving *before* rendering — the same idea OSM uses with its hand-tagged `layer=*` integer, but inferred automatically.

2. **The correct formal model is a system of difference constraints (a special LP solvable by shortest/longest paths).** Let `L[i]` be the integer layer of segment *i*. Connectivity gives equality constraints `L[i] = L[j]`; interior crossings with the higher road *u* over lower road *v* give `L[u] ≥ L[v] + 1`. A feasible integer assignment exists iff the constraint graph has no positive cycle. This is textbook CLRS §24.4 (difference constraints ↔ Bellman–Ford): per Theorem 24.9, "If the Bellman-Ford algorithm returns FALSE, there is no feasible solution to the system of difference constraints," and a system of *m* constraints on *n* unknowns yields a graph of *n*+1 vertices and *n*+*m* edges, solved in O(n²+nm) time. It is also the level-assignment step of the Sugiyama layered-graph-drawing framework.

3. **Cycles (spiral ramps, stacked loops) are the genuinely hard case and are the "non-planar"/inconsistent instance.** A helical ramp that climbs over itself cannot satisfy a single global integer layer (it would require `L > L`). This is precisely the minimum-feedback-arc-set (FAS) problem from Sugiyama cycle-removal — NP-hard, solved in practice with the greedy heuristic of Eades, Lin & Smyth (1993, "A Fast and Effective Heuristic for the Feedback Arc Set Problem," *Information Processing Letters* 47(6), pp. 319–323). The relaxation is: solve globally everywhere it is feasible; isolate each infeasible biconnected component and fall back to local per-crossing caps *only there*.

4. **Professional engines do exactly "group by integer layer, order within layer, two-pass casing/fill."** OSM-Carto/Mapnik renders roads in three stacks (tunnels / ground / bridges); the bridges and tunnels layers carry `group-by: layernotnull` so each distinct integer layer renders as a separate sublayer, and *within* a layer the SQL `ORDER BY layernotnull, z_order` sets road-class precedence. osm2pgsql computes `z_order = 10 × layer + class_weight`. This confirms the recommended architecture and its known limits.

5. **Reconstructing per-vertex height is worth doing but only as a *secondary signal*, not the backbone.** Height-above-ground = Elevation − terrain works to separate the elevated stack, but with one value per feature it is too coarse to drive seams; use it to (a) seed the over/under direction at crossings and (b) split the rare feature that transitions ground↔elevated.

## Details

### A. Why each prior approach failed, in one sentence each
- (a) continuous-elevation zorder, (b) discrete bins: the single parameter ε is simultaneously casing-gap, overpass threshold, and cut tolerance — mathematically one knob cannot serve three masters.
- (c) union-find structures: right instinct, but fractures at imprecise endpoints and doesn't model crossing constraints, so structure↔ground transitions still cut.
- (e) per-crossing caps: the layer was a property of the *crossing point*, so one lower ramp gets hole-punched by every road above it.
- (f) Form three-layer: consistent but collapses all elevated-over-elevated into one plane (no stacked-interchange over/under) and still leaves the ground↔elevated transition seam.

The unifying diagnosis: **layer must be a consistent property assigned to entire connected paths, derived by global constraint solving.** That is the whole solution.

### B. Step 1 — Robust connectivity graph (defeating endpoint-precision fracture)
1. Extract every segment's two endpoints. Stack all endpoints into an (N,2) numpy array.
2. **Cluster coincident endpoints with a tolerance.** Two robust options:
   - `scipy.spatial.cKDTree(points)` then `query_pairs(r=tol)` (tol ≈ 0.5–1.0 m in the projected UTM CRS Carto exports, EPSG:326xx/327xx — confirmed Carto's default projection). Union-find (`scipy.sparse.csgraph.connected_components` on the pair graph, or `networkx`) to assign each cluster a node id.
   - Or `shapely.set_precision(geom, grid_size=tol)` / `shapely.node`/`unary_union` to snap-and-node, which dissolves and re-nodes linework to a precision grid.
   - KDTree clustering is preferred here because it does **not** split features at interior vertices (you only want endpoint identity), preserving the "feature = one edge" model.
3. Build `networkx.Graph` (or just arrays): node = snapped endpoint cluster, edge = segment. This graph's connected components are the candidate "strokes/structures."
4. **Connectivity = shared node** after snapping. This is the *equality* constraint source.

Tolerance choice: pick tol smaller than the narrowest real gap between distinct parallel roads but larger than coordinate jitter. With Carto's meter-scale UTM output, 0.5–1 m is safe; validate by checking the number of components stabilizes as you sweep tol.

### C. Step 2 — Detect TRUE overpass crossings (not shared-node connections)
The defining test (already discovered in approach (e)): a planar *connection* shares an endpoint/node; a true *grade separation* is where two segments **cross in their interiors** without sharing a node.

Implementation at ~21k features:
1. Build `shapely.STRtree(segments)`.
2. `tree.query(segments, predicate="crosses")` (vectorized in shapely 2.x) returns candidate index pairs whose interiors intersect. `crosses` already excludes pure endpoint touches, which is most of the filtering.
3. For each candidate pair, defensively confirm the intersection point is **not** within tol of either segment's endpoints (guards against near-miss noding); also require the two segments are **not** in the same connected component touching at that point. Keep only interior crossings.
4. The user's count of ~1199 such crossings is the right order of magnitude and becomes the *inequality* constraint set.

Determining over/under at each crossing: compare height-above-ground (Elevation − terrain) of the two segments, tie-broken by Form rank (Tunnel < Normal < Elevated). The higher one gets the `≥ +1` constraint.

### D. Step 3 — Formulate and solve integer layer assignment
This is the core. Work at the **stroke level** first to keep the problem small and to bake in continuity:

1. **Build strokes (good-continuation grouping).** Within each connected component, concatenate segments through degree-2 nodes, and at higher-degree nodes chain the pair with the smallest deflection angle. This is the "good continuation" stroke-building principle of Thomson & Richardson (1999, "The 'Good Continuation' Principle of Perceptual Organization Applied to the Generalization of Road Networks," *Proc. 19th International Cartographic Conference*, Ottawa, pp. 1215–1223). Use the **every-best-fit** rule for deterministic results — per the comparative study of stroke-concatenation strategies (*Int. J. Geogr. Inf. Sci.*), "if only the geometric approach is considered, the every-best-fit strategy performs best; if thematic attributes are also added, road class can be more effective than road name." Same-stroke + same-component segments are tied to one layer variable. This is what makes a climbing ramp a single unit. Use `Form` and `Category` as additional concatenation gates (don't merge a tunnel stroke into an elevated stroke across a portal).

2. **Variables:** one integer `L[s]` per stroke (or per connected component if you prefer coarser units).

3. **Constraints:**
   - *Equality / soft-equality:* strokes that share a node and continue smoothly → `L[a] = L[b]` (or penalize `|L[a]−L[b]|`). Connectivity dominates.
   - *Crossing order:* for each true interior crossing between strokes u (higher) and v (lower): `L[u] − L[v] ≥ 1`.

4. **Solve as difference constraints / longest path on a DAG:**
   - Construct the constraint digraph: an edge `v → u` of weight 1 for each `L[u] ≥ L[v] + 1`; equality edges both directions weight 0.
   - Add a super-source with 0-weight edges to all nodes; run **Bellman–Ford** (`networkx.single_source_bellman_ford` or a hand-rolled O(V·E) pass). The longest-path value (equivalently shortest path on negated weights) gives the minimal-range feasible integer layering — *exactly the Sugiyama level-assignment "assign each vertex the length of the longest path ending at it," which yields the minimum number of layers.*
   - Feasible ⇔ no positive-weight cycle. Bellman–Ford reports this (CLRS Thm 24.9).

5. **Handle contradictions/cycles (spiral ramps, double-deck loops):**
   - If Bellman–Ford detects a positive cycle, the constraints are inconsistent — a single global integer layer is impossible (the genuinely non-planar case).
   - Localize: contract all equality edges, find the strongly-connected components / biconnected components containing the bad cycle.
   - Apply a **minimum-feedback-arc-set heuristic** (Eades–Lin–Smyth greedy, or DFS back-edge removal) to *temporarily drop the fewest crossing-constraints* needed to make the component a DAG; solve the DAG; then the dropped crossings are resolved *locally* by a per-crossing bridge cap (approach (e)) **but only inside that small component**, so the global ramp is never shattered.
   - This staged relaxation is the key innovation over approach (e): global layering everywhere it is consistent; local caps only in the handful of truly self-stacking interchanges.

6. **Complexity:** snapping is O(N log N); STRtree crossing query ≈ O(N log N + K); Bellman–Ford O(V·E) over ~thousands of strokes and ~1199 crossing edges is milliseconds-to-seconds. Entirely feasible as a one-time preprocess.

### E. Step 4 — Rendering in matplotlib (seamless within layer, clean over/under across)
1. **Sort segments by computed integer layer ascending.**
2. **For each layer L, in ascending order, do a global two-pass:** add *all* casings of layer L (one `LineCollection`, dark color, wider `linewidth`, `capstyle='round'` or `'projecting'`, `joinstyle='round'`), then *all* fills of layer L (a second `LineCollection`, surface color, narrower). Because zorder increases monotonically with layer, and within a layer all fills sit above all casings, **same-layer connected roads join seamlessly** (no casing ever covers an adjacent fill endpoint) and **higher layers cleanly occlude lower ones at crossings** (genuine over/under, including elevated-over-elevated, because stacked roads now get distinct layers).
   - Set zorder per layer, e.g. `casing_zorder = 2*L`, `fill_zorder = 2*L + 1`. Note matplotlib applies one scalar zorder per `LineCollection` (per the docs, zorder/capstyle/joinstyle are collection-wide properties, not per-segment), so create one casing collection and one fill collection *per layer* and rely on draw order. Using separate collections in a deliberate add order is the robust way.
3. **The layer-transition seam (a single road that changes layer along its length — the climbing ramp's one ground→elevated switch):** handle it explicitly so it never cuts:
   - Identify the transition node where stroke crosses from layer L to L+1.
   - **Overshoot the higher segment's fill** a short distance (a few px / one casing-width) back across the transition node, *over* the lower segment, so the higher fill paints over the lower casing seam. Equivalently, draw a tiny "bridge cap" fill exactly at the transition. Because the two pieces share the same fill color, the join is invisible.
   - Alternatively assign the boundary segment to the *higher* of the two layers and let the global two-pass cover the seam — simplest and usually sufficient.
4. **Tunnels:** lowest layers, dashed `linestyle`, optionally lighter — matching OSM-Carto's tunnel casing treatment.

### F. What professional engines actually do (validation of the design)
- **OSM-Carto / Mapnik** (Christoph Hormann, "Navigating the Maze"): roads are split into tunnels / ground-casing / ground-fill / bridges stacks; the bridges and tunnels layers use Mapnik's `group-by: layernotnull` so *each distinct integer layer value renders as its own sublayer* (a layer=2 bridge entirely above a layer=1 bridge), while *within* a layer the SQL `ORDER BY layernotnull, z_order` orders by road class. `layernotnull` = the OSM `layer` tag coerced to integer with NULL→0, via `CASE WHEN layer ~ E'^-?\d+$' AND length(layer)<10 THEN layer::integer ELSE 0 END`. Hormann states the drawing order is set, in decreasing priority, by: the map-style layer stack, the layer's `group-by` parameter, the MSS `::attachments`, the SQL `ORDER BY`, and finally the slash-prefixed MSS drawing-rule instances.
- **osm2pgsql** computes the ordering key as **`z_order = 10 × layer + class_weight`**. Per osm2pgsql `style.lua` (master branch), the road-class weights are: residential/unclassified/minor **3**, tertiary/tertiary_link **4**, secondary/secondary_link **6**, primary/primary_link **7**, trunk/trunk_link **8**, motorway/motorway_link **9**, railway **5**; bridge **+10**, tunnel **−10**. The integer layer (×10) dominates, class breaks ties — the precise analogue of the recommended `2*L` zorder scheme.
- **Historical limit:** older roads.mss enumerated discrete bridge sublayers for layer −5…+5 (eleven levels, ~15 bridge layers total); values outside the range fell back to layer-0 (wrong stacking). The canonical bug — OSM trac #3678, reporter rickmastfan67, 2011 — was that grouping bridges by *road class* meant layer tags were only honored *within* a class, so multi-class interchanges mis-stacked ("It looks like all the ways are intersecting each other which is obviously not the case here since it's an elevated interchange"). This is exactly the failure mode the user must avoid by making layer the primary sort key. Hormann's fix collapsed everything into one ~1700-line SQL query ordered by a single `ORDER BY` on the layer attribute so *all* bridge/tunnel features (road lines, highway polygons, waterway bridges) stack consistently by layer.
- **QGIS** offers "Symbol Levels" (render all casings, then all fills) for the seamless-join effect, but a known limitation — QGIS issue #42428, opened by user JohnProv (24 Mar 2021): "'Control feature rendering order' should have precedence over symbol levels. Now it isn't possible to create a map with for example correct road outlines and have roads in the correct order (bridge over road etc.)." — means z-by-layer and casing/fill ordering cannot both take precedence. This is *precisely* the user's dilemma, and is why the layer must be resolved into the geometry/zorder *before* handing to the renderer rather than relying on the renderer's two mechanisms to cooperate.

The takeaway: the industry does group-by-integer-layer + two-pass; their residual bugs come from grouping by class instead of by a globally-consistent layer, and from keeping some feature types (waterway bridges, polygons, aerialways) outside the unified group. The recommended algorithm fixes both by (1) computing one consistent integer layer per stroke and (2) putting *all* feature types into the same per-layer two-pass.

### G. On per-vertex height reconstruction (expert question 5)
- **Benefit:** Elevation − terrain gives height-above-ground, which cleanly seeds the over/under direction at crossings and identifies the ground↔elevated transition feature. Smoothing along a stroke (each stroke should have monotone or gently varying height) lets you *detect and correct* the rare feature whose single Elevation value is wrong.
- **Cost/limitation:** with one value per feature you cannot recover true per-vertex height; interpolating between feature endpoints assumes linear grade, which is only approximately true and adds complexity. **Recommendation: do not make per-vertex height the backbone.** Use the integer-layer constraint solve as the backbone (it is robust to elevation noise because it only uses *relative* order at actual crossings), and use height only to (a) orient each crossing constraint and (b) place the single layer-transition on a climbing ramp.

## Recommendations

**Stage 1 — Build the topology (do first, validate before proceeding).**
1. Reproject to the UTM CRS Carto already uses (meters). Snap endpoints with `cKDTree.query_pairs(tol)`, tol≈0.75 m; union-find into nodes; build the segment graph in networkx.
2. Sweep tol over {0.25, 0.5, 0.75, 1.0, 1.5} m and pick the value where the connected-component count plateaus. *Benchmark that would change this:* if real distinct roads start merging (component count drops too far), reduce tol.

**Stage 2 — Find crossings and strokes.**
3. STRtree `query(..., predicate="crosses")` → interior crossings; filter out endpoint-touches and same-component touches. Expect ~1000–1300 crossings.
4. Build strokes by good-continuation (smallest deflection angle, every-best-fit), gated by Form/Category, so each ramp/bridge is one unit.

**Stage 3 — Solve layers.**
5. Emit equality constraints (shared-node/same-stroke) and `≥+1` crossing constraints (higher = larger height-above-ground, Form tie-break). Run Bellman–Ford / longest-path for the minimal-range integer layering.
6. On positive-cycle detection, localize to the biconnected component, run an FAS greedy heuristic (Eades–Lin–Smyth) to drop the fewest crossing constraints, solve the residual DAG, and resolve dropped crossings with *local* per-crossing caps confined to that component. *Threshold:* if >~5% of crossings end up needing local caps, your over/under direction signal (height) is probably noisy — revisit Stage G.

**Stage 4 — Render.**
7. For L ascending: add all-casings collection then all-fills collection, zorder `2L` / `2L+1`, round caps/joins.
8. At each stroke layer-transition, assign the boundary segment to the higher layer and overshoot its fill a few pixels across the node; verify visually that no climbing ramp shows a seam.

**Stage 5 — Validate against the two goals.** Pick a dense interchange and confirm (a) every ramp is continuous end-to-end and (b) stacked decks separate. If a stacked loop still flattens, it is an FAS-relaxed component — accept local caps there.

## Caveats
- **Cycles are provably unsolvable with one global integer.** A self-climbing spiral *cannot* be both continuous and fully over/under with a single integer layer; this is intrinsic (it is the non-planarity / positive-cycle case), not a bug in the method. The honest best outcome is global consistency everywhere else plus local caps inside the spiral. Any claim of a single parameterless global solution would be false.
- **Tolerance is a real risk both ways.** Too-large snap merges distinct roads (false connectivity → wrong shared layer); too-small leaves fractures. There is no universal value; validate empirically on your map.
- **matplotlib zorder is per-collection, not per-segment** (confirmed in the matplotlib issue tracker): you must materialize one casing and one fill collection per layer and control order by add sequence, not by passing a zorder array.
- **Height signal is coarse** (one value per feature, includes terrain). It is reliable enough for *relative* crossing order but not for seams; the design deliberately leans on topology, not elevation, for the cut-free guarantee.
- **OSM-Carto specifics evolve:** v6.0.0 (≈2026) moved to the osm2pgsql flex backend; the `z_order = 10×layer + class` formula quoted is the legacy pgsql transform and the flex backend reproduces the same logic in a different file — verify exact constants if you mirror them, though for your purposes only the *architecture* (layer-dominates-class, group-by-layer, two-pass) matters. The historical `mwaybridge_layerN` per-layer-value identifiers reflect older/derivative styles; current upstream master uses `group-by` instead.
- **Performance** is not a concern at 21k features; the heavy step (Bellman–Ford over a few thousand stroke variables and ~1200 crossing edges) is sub-second, consistent with the user's acceptance of heavy one-time preprocessing.