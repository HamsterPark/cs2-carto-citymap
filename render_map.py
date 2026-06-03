# -*- coding: utf-8 -*-
"""
从 Carto (Cities: Skylines 2) 导出的数据直接出图。
只依赖 matplotlib / numpy / rasterio（无需 geopandas）。
用法:
    py -3.14 render_map.py            # 画街道图 + 地形图（默认，较快）
    py -3.14 render_map.py --zoning   # 额外画分区彩图（要读 238MB，较慢）
"""
import json, os, sys, time
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection

BASE = os.path.dirname(os.path.abspath(__file__))
GJ   = os.path.join(BASE, "Carto", "GeoJSON")
TIF  = os.path.join(BASE, "Carto", "GeoTIFF")
OUT  = BASE

def load(name):
    p = os.path.join(GJ, name)
    if not os.path.exists(p):
        print(f"  [跳过] 缺少 {name}"); return None
    t = time.time()
    with open(p, "r", encoding="utf-8-sig") as f:   # Carto 的 GeoJSON 带 BOM
        d = json.load(f)
    n = len(d.get("features", []))
    print(f"  [读入] {name}: {n} 个要素, {time.time()-t:.1f}s")
    return d

def _ring(coords):           # 取一个环的 (x,y)，丢弃 z
    return [(c[0], c[1]) for c in coords]

def polygons(fc):
    out = []
    if not fc: return out
    for ft in fc["features"]:
        g = ft.get("geometry") or {}
        t, c = g.get("type"), g.get("coordinates")
        if t == "Polygon" and c:
            out.append(_ring(c[0]))
        elif t == "MultiPolygon" and c:
            for poly in c:
                if poly: out.append(_ring(poly[0]))
    return out

def polygons_by(fc, field):
    """返回 {属性值: [多边形,...]}，用于分类着色。"""
    groups = {}
    if not fc: return groups
    for ft in fc["features"]:
        g = ft.get("geometry") or {}
        t, c = g.get("type"), g.get("coordinates")
        key = (ft.get("properties") or {}).get(field, "None")
        rings = []
        if t == "Polygon" and c:
            rings = [_ring(c[0])]
        elif t == "MultiPolygon" and c:
            rings = [_ring(p[0]) for p in c if p]
        groups.setdefault(key, []).extend(rings)
    return groups

def lines(fc):
    out = []
    if not fc: return out
    for ft in fc["features"]:
        g = ft.get("geometry") or {}
        t, c = g.get("type"), g.get("coordinates")
        if t == "LineString" and c:
            out.append(_ring(c))
        elif t == "MultiLineString" and c:
            for ln in c:
                if ln: out.append(_ring(ln))
    return out

def new_ax(title):
    fig, ax = plt.subplots(figsize=(14, 14))
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(title, fontsize=14)
    return fig, ax

def save(fig, name):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=160, bbox_inches="tight", pad_inches=0.1, facecolor="white")
    plt.close(fig)
    mb = os.path.getsize(p) / 1e6
    print(f"  [输出] {p}  ({mb:.1f} MB)")

# ---------- 1) 街道/平面图 ----------
def render_street():
    print("== 街道图 ==")
    area  = load("Area_Boundary.json")
    bld   = load("Building_Boundary.json")
    net   = load("Network_Centerline.json")
    fig, ax = new_ax("Cities: Skylines 2 — Street Map")

    ap = polygons(area)
    if ap:
        ax.add_collection(PolyCollection(ap, facecolors="#eeeae3",
                                         edgecolors="#cfc9bf", linewidths=0.3, zorder=0))
    bp = polygons(bld)
    if bp:
        ax.add_collection(PolyCollection(bp, facecolors="#c9bfa8",
                                         edgecolors="none", zorder=1))
        print(f"     建筑多边形: {len(bp)}")
    nl = lines(net)
    if nl:
        ax.add_collection(LineCollection(nl, colors="#3a3a3a",
                                         linewidths=0.35, zorder=2))
        print(f"     路网线段: {len(nl)}")

    ax.autoscale_view()
    save(fig, "map_street.png")

# ---------- 2) 分区彩图（可选，重） ----------
PALETTE = {
    "Residential": "#7cb342", "Commercial": "#1e88e5", "Industrial": "#fdd835",
    "Office": "#8e24aa", "Residential, Commercial": "#26a69a",
    "Residential, Industrial": "#c0ca33", "Residential, Office": "#ab47bc",
    "Commercial, Industrial": "#ffa726", "Commercial, Office": "#5c6bc0",
    "Industrial, Office": "#d4a017", "None": "#e0e0e0",
}
def render_zoning():
    print("== 分区彩图（读 238MB，请稍候）==")
    z = load("Zoning_Boundary.json")
    if not z: return
    fig, ax = new_ax("Cities: Skylines 2 — Zoning Map")
    groups = polygons_by(z, "Zoning")
    for key, polys in sorted(groups.items()):
        col = PALETTE.get(key, "#bdbdbd")
        ax.add_collection(PolyCollection(polys, facecolors=col,
                                         edgecolors="none", label=f"{key} ({len(polys)})"))
    ax.autoscale_view()
    ax.legend(loc="upper right", fontsize=7, framealpha=0.9, markerscale=2)
    save(fig, "map_zoning.png")

# ---------- 3) 地形晕渲图（GeoTIFF）----------
def render_terrain():
    print("== 地形晕渲图 ==")
    try:
        import rasterio
    except Exception as e:
        print(f"  [跳过] rasterio 不可用: {e}"); return
    p = os.path.join(TIF, "Elevation.tif")
    if not os.path.exists(p):
        print("  [跳过] 缺少 Elevation.tif"); return
    with rasterio.open(p) as ds:
        arr = ds.read(1).astype("float32")
        nodata = ds.nodata
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    from matplotlib.colors import LightSource
    ls = LightSource(azdeg=315, altdeg=45)
    finite = np.isfinite(arr)
    vmin, vmax = (np.nanmin(arr), np.nanmax(arr)) if finite.any() else (0, 1)
    print(f"     高程范围: {vmin:.1f} ~ {vmax:.1f}, 尺寸 {arr.shape}")
    filled = np.where(finite, arr, vmin)
    rgb = ls.shade(filled, cmap=plt.cm.terrain, blend_mode="soft",
                   vert_exag=3, vmin=vmin, vmax=vmax)
    fig, ax = new_ax("Cities: Skylines 2 — Terrain (Elevation)")
    ax.imshow(rgb)
    save(fig, "map_terrain.png")

if __name__ == "__main__":
    t0 = time.time()
    render_terrain()
    render_street()
    if "--zoning" in sys.argv:
        render_zoning()
    print(f"全部完成, 用时 {time.time()-t0:.1f}s")
