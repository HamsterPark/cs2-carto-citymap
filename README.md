# CS2 Carto City Map Renderer

Turn a **Cities: Skylines II** save into publication-quality city maps — rendered in **pure Python (matplotlib)** from data exported by the **Carto** mod (a separate, third-party in-game mod). No QGIS, no geopandas.

**English** · [中文说明](README.zh-CN.md)

![Base city map](gallery/city.png)

One Carto export → **13 cartographic maps**: a detailed base city map plus thematic overlays (highways, public transit, metro, rail, tram, bus, shipping, waterways, a minimal street map) and terrain hillshade.

> **Where the data comes from.** All input data is produced **inside the game** by the **Carto** mod — an existing third-party mod (**not** part of this project). In Cities: Skylines II, install Carto from Paradox Mods and use it to export your city; it writes the GeoJSON / GeoTIFF layers that this renderer reads. This project does not generate or scrape any data — it only renders Carto's output. The example city in [Releases](../../releases) is simply one such Carto export.

---

## Gallery

| Highways & Arterials | Public Transit |
|:---:|:---:|
| ![highway](gallery/highway.png) | ![transit](gallery/transit.png) |
| **Metro Lines** | **Railway Lines** |
| ![metro](gallery/metro.png) | ![train](gallery/train.png) |
| **Metro & Rail** | **Tram Lines** |
| ![rail](gallery/rail.png) | ![tram](gallery/tram.png) |
| **Bus Lines** | **Shipping Routes** |
| ![bus](gallery/bus.png) | ![shipping](gallery/shipping.png) |
| **Waterways** | **Street Map** |
| ![waterway](gallery/waterway.png) | ![street](gallery/street.png) |
| **Terrain (hillshade)** | **Terrain (180° rotated)** |
| ![terrain](gallery/terrain.png) | ![terrain 180](gallery/terrain_180.png) |

> Gallery images are downscaled web previews. Full-resolution maps (up to 600 DPI) are produced when you run the script.

---

## Highlights

- **Pure Python pipeline** — `matplotlib` + `numpy` + `rasterio` only. No QGIS, no geopandas/shapely.
- **Correct road grade separation** — overpasses are resolved by a constraint solver (integer layers via good-continuation strokes + interior-crossing constraints + Bellman–Ford relaxation), so flyovers stack correctly **without fragmenting on-ramps**. `butt`-capped high-grade roads and a branch-merge pass keep junctions seamless. See [docs](docs/).
- **Signature & landmark detection** — CS2 *Signature Buildings* are identified structurally (`Level == 5` + a real zoning + no growth marker in the asset name ⟺ unique city-wide, verified with zero exceptions across 18,196 buildings) and drawn as zone-coloured diamonds by type (residential / commercial / office / industrial / mixed). DLC *Attractions* (from POI data) become gold stars.
- **Classic cartographic styling** — zone colours by density, graded road widths, railway/metro/tram palettes, half-transparent shipping lanes, civic-service badges, terrain micro-shading under the base map.
- **Per-line transit colouring** with casings, and a layering order that keeps metro > rail > other modes legible on the combined transit map.
- **Terrain hillshade** composited from GeoTIFF elevation + water depth, including a true 180°-rotated variant (content rotated, title kept upright).
- **Safe versioned output** — every run writes `map_*_vN.png` with an auto-incrementing version; it never overwrites previous renders.

---

## Requirements

- Python 3.9+
- `pip install -r requirements.txt` (matplotlib, numpy, rasterio, pillow)

> On Windows, the `rasterio` pip wheel bundles GDAL — no separate install needed.

---

## Quick start (with the example city)

```bash
git clone https://github.com/HamsterPark/cs2-carto-citymap.git
cd cs2-carto-citymap
pip install -r requirements.txt
```

Then download **`carto-example-data.zip`** from the [**Releases**](../../releases) page and unzip it into the repo root, so the layout becomes:

```
cs2-carto-citymap/
├── Carto/
│   ├── GeoJSON/   Zoning_Boundary.json, Building_Boundary.json, Network_Centerline.json, Route_Centerline.json, POI_Location.json, Area_Boundary.json
│   └── GeoTIFF/   Elevation.tif, Depth.tif
└── render_city.py
```

Render everything:

```bash
python render_city.py
```

This writes `map_city_vN.png` (the base map, 600 DPI) plus all thematic maps and the terrain maps into the repo root.

`render_map.py` is a smaller, earlier renderer (a simple street map, an optional zoning map, and a terrain map) kept as a minimal reference example:

```bash
python render_map.py            # street + terrain
python render_map.py --zoning   # also the zoning map (reads the large file, slower)
```

---

## Using your own city

1. In Cities: Skylines II, export your save with the **Carto** mod — a third-party mod (not part of this project), available on Paradox Mods. Carto writes **GeoJSON**, **GeoTIFF** and Shapefile layers.
2. Copy the layers this project uses into the repo:
   - `Carto/GeoJSON/` — `Zoning_Boundary.json`, `Building_Boundary.json`, `Network_Centerline.json`, `Route_Centerline.json`, `POI_Location.json` (and optionally `Area_Boundary.json`)
   - `Carto/GeoTIFF/` — `Elevation.tif`, `Depth.tif`
3. `python render_city.py`

> Carto's GeoJSON is in EPSG:4326 and UTF-8 with a BOM; its GeoTIFF is in a UTM projection. The script handles both (BOM-aware reads and on-the-fly reprojection of the depth raster onto the elevation grid).

---

## How it works

`render_city.py` is a single, heavily-commented script (~750 lines). The interesting parts:

- **`compute_road_layers()`** — builds continuous road strokes by good-continuation, detects which crossings are real grade separations (segment-interior intersection on a spatial grid), turns them into difference constraints (`higher ≥ lower + 1`) and solves integer layers with Bellman–Ford longest-path relaxation. High-grade roads use `butt` caps so layer transitions don't leave seams; a fill-merge pass redraws a branch's final segment over the main road so on-ramps read as continuous.
- **Signature / landmark classification** in the building loop, and **per-line transit grouping** for the route maps.
- **Terrain** — `LightSource` hillshade over the elevation raster, with the water-depth raster reprojected into the same grid.

Background notes (Chinese) live in [`docs/`](docs/): the drawing guide, the grade-separation problem report, and an expert reference report on road layering.

---

## Repository layout

```
.
├── render_city.py     # main renderer → 13 maps
├── render_map.py      # early/simple renderer (reference)
├── requirements.txt
├── gallery/           # web-preview images shown above
├── docs/              # design notes & reports (Chinese)
├── README.md          # this file (English)
├── README.zh-CN.md    # Chinese
└── LICENSE
```

Source data (`Carto/`) and full-resolution renders are **not** committed — get the data from Releases, and regenerate the renders by running the script.

---

## License

- **Code** — [MIT](LICENSE).
- **Rendered images (`gallery/`) and the example city data** — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Acknowledgements

- The **Carto** mod for Cities: Skylines II — an independent third-party mod (not affiliated with this project) — which exports the underlying GeoJSON / GeoTIFF data.
- Cities: Skylines II © Colossal Order / Paradox Interactive. This is an unofficial fan project.
- The renderer was developed iteratively with the help of **Claude Code** (Anthropic).
