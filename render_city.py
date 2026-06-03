# -*- coding: utf-8 -*-
"""
Cities: Skylines 2 — Carto 导出 → 经典城市地图合成图 (v3)。
新增：地标★ / 桥梁高架(深色边) / 市政细分(学校·医院·警·消·政府) /
      公用设施(发电·水务·污水·垃圾·电信) / 墓地 / 公交·电车站(极小点)。
保留：分级道路(全局两遍消接缝)、铁路(+隧道虚线)、地铁、电车、人行道、
      机场、物理航道(经典航线虚线)、水面、住/商/办/混合按密度深浅、
      特色工业(农林牧渔矿油)、公园、交通设施(降饱和)、交通站点标记。
方向 180°，~3700px。仅依赖 matplotlib / numpy / rasterio。
"""
import json, os, re, glob, time, collections
import numpy as np
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.rcParams["mathtext.fontset"] = "cm"     # 细体数学字体，字母 logo 笔画不粘连
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.patches import Rectangle
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties
from matplotlib.transforms import Affine2D

_LETTER_FP = FontProperties(family=["Segoe UI", "Arial"], weight="light")   # Segoe UI Light(最细可靠字重)
_LETTER_CACHE = {}
def letter_marker(ch):                 # 细体、居中的字母 marker(用作 scatter marker)
    m = _LETTER_CACHE.get(ch)
    if m is None:
        tp = TextPath((0, 0), ch, size=1.0, prop=_LETTER_FP)
        e = tp.get_extents()
        m = tp.transformed(Affine2D().translate(-(e.x0 + e.x1) / 2, -(e.y0 + e.y1) / 2))
        _LETTER_CACHE[ch] = m
    return m

BASE = os.path.dirname(os.path.abspath(__file__))
GJ   = os.path.join(BASE, "Carto", "GeoJSON")
TIF  = os.path.join(BASE, "Carto", "GeoTIFF")
FIGSIZE, DPI, W = 16, 300, 1.0
BASE_DPI = 600         # 底图(含 logo)用更高分辨率,字母清晰;路线图用 DPI
SPLIT_ELEV = False     # 方法①:沿高程突变(≥7.5m)切断 stroke,层号沿路变化(支线在平地段自然接入)
FILL_MERGE = True      # 方法②:跨层路口用低层路的填充汇入高层主路(盖过主路描边)
PREVIEW = False        # 预览模式:只出底图并裁一小块(看 logo 字号),跳过 10 张路线图

def next_out():   # 每次输出新文件，不覆盖旧图
    nums = []
    for f in glob.glob(os.path.join(BASE, "map_city_v*.png")):
        m = re.search(r"_v(\d+)\.png$", os.path.basename(f))
        if m: nums.append(int(m.group(1)))
    return os.path.join(BASE, f"map_city_v{(max(nums)+1) if nums else 1}.png")

LAND, WATER = "#f3efe7", "#a9cfe3"

ZONE = {  # 住/商/办/混合：密度由浅到深
    "Residential":             {"Low":"#efe6d2","Medium":"#ddcaa6","High":"#c9b083"},
    "Commercial":              {"Low":"#f3d8cf","Medium":"#e8b5a2","High":"#d9947d"},
    "Office":                  {"Low":"#dbe7f2","Medium":"#b1cbe6","High":"#7ea8d4"},
    "Residential, Commercial": {"Low":"#f7e3c4","Medium":"#edcb95","High":"#dfb36a"},
}
IND = {"generic":"#d9c7e0","agri":"#cdd86a","forest":"#6ba86a","mine":"#c9a96b","oil":"#8f8270","fish":"#74c7bb"}
def industrial_color(name):
    s = str(name)
    if "农业" in s or "Farm" in s:              return IND["agri"]
    if "林业" in s or "Forest" in s:            return IND["forest"]
    if "采矿" in s or "矿" in s or "Min" in s:   return IND["mine"]
    if "石油" in s or "油井" in s or "Oil" in s: return IND["oil"]
    if "养鱼" in s or "捕鱼" in s or "渔" in s:  return IND["fish"]
    return IND["generic"]
def zone_color(p):
    z = p.get("Zoning", "")
    if z == "Industrial": return industrial_color(p.get("Name", ""))
    fam = ZONE.get(z)
    return fam.get(p.get("Density", "Medium"), fam["Medium"]) if fam else "#e2ddd2"

# 建筑分桶 (填充, 描边, zorder)
BLD = {
    "building":  ("#c5b9a3","#b0a48d",20),
    "parking":   ("#d8d6cb","#c1bdaf",21),
    "park":      ("#9ccf6b","#79b04a",22),
    "cemetery":  ("#bcc7a8","#9fae86",22),
    "utility":   ("#a9aa90","#8f9075",23),
    "transport": ("#9fb4c8","#7d96ac",24),   # 交通设施 降饱和
    "education": ("#e9cf85","#cdae57",25),    # 学校
    "admin":     ("#c2a0cf","#a37cb5",25),    # 政府
    "civic":     ("#cdb06a","#ab8e44",25),    # 其它公共
    "police":    ("#8f9fd0","#6c7cb5",26),    # 警察
    "fire":      ("#d97d63","#bb5b41",26),    # 消防
    "health":    ("#e29191","#c66a6a",26),    # 医院
}
def _darken(hx, f):
    r, g, b = (int(hx[i:i+2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r*f), int(g*f), int(b*f))

def _density(name):
    s = str(name)
    if "高密度" in s or "High" in s or "廉租" in s:                  return "High"
    if "中密度" in s or "Medium" in s or "联排" in s:                return "Medium"
    if "低密度" in s or "Low" in s or "独栋" in s or "半独立" in s:   return "Low"
    return "Medium"

def _special_ind(cat, name):
    s = str(name)
    if cat & {"Farmland", "Ranch"} or "农业" in s or "Farm" in s:     return IND["agri"]
    if "Forestry" in cat or "林业" in s or "Forest" in s:            return IND["forest"]
    if "Quarry" in cat or "采矿" in s or "矿" in s:                   return IND["mine"]
    if "OilField" in cat or "石油" in s or "油井" in s or "Oil" in s: return IND["oil"]
    if "Fishery" in cat or "养鱼" in s or "捕鱼" in s or "渔" in s:   return IND["fish"]
    return None

# 建筑取色：专用设施用 BLD 固定色；RICO 建筑按功能+密度取同色系略深，避免灰片盖住分区
def building_style(p):
    cat = set(str(p.get("Category", "")).split(", "))
    if "Park" in cat:           return BLD["park"]
    if "Transportation" in cat: return BLD["transport"]
    if "Health" in cat:         return BLD["health"]
    if "Education" in cat:      return BLD["education"]
    if "Police" in cat:         return BLD["police"]
    if "Fire" in cat:           return BLD["fire"]
    if "Admin" in cat:          return BLD["admin"]
    if "Mortuary" in cat:       return BLD["cemetery"]
    if cat & {"Power","Sewage","Water","Waste","Communication","Maintenance"}: return BLD["utility"]
    name = p.get("Zone", "")
    if p.get("Object") == "Extractor" or (cat & {"Farmland","Forestry","Quarry","OilField","Fishery","Ranch"}):
        col = _special_ind(cat, name) or IND["generic"]
        return (_darken(col, 0.90), _darken(col, 0.72), 20)
    if "Public" in cat or (cat & {"Post","Research","Disaster"}): return BLD["civic"]
    if "Parking" in cat:        return BLD["parking"]
    z = p.get("Zoning", "")
    if z == "Industrial":
        col = _special_ind(cat, name) or IND["generic"]
        return (_darken(col, 0.92), _darken(col, 0.74), 20)
    fam = ZONE.get(z)
    if fam:
        col = fam[_density(name)]
        return (_darken(col, 0.85), _darken(col, 0.68), 20)
    return BLD["building"]

ORD  = ["Highway", "Large", "Medium", "Small"]
ROAD = {
    "Highway": dict(fc="#f29400", cc="#c06f12", fw=0.85, cw=1.45),
    "Large":   dict(fc="#fbc24f", cc="#d99e2c", fw=0.65, cw=1.10),
    "Medium":  dict(fc="#fde9a9", cc="#d6c47e", fw=0.50, cw=0.85),
    "Small":   dict(fc="#ffffff", cc="#cdc7ba", fw=0.36, cw=0.62),
}

def load(name):
    t = time.time()
    with open(os.path.join(GJ, name + ".json"), encoding="utf-8-sig") as f:
        feats = json.load(f)["features"]
    print(f"  [读入] {name}: {len(feats)} ({time.time()-t:.1f}s)")
    return feats

def rings_of(g):
    t, c = g.get("type"), g.get("coordinates")
    if t == "Polygon":      return [[(p[0], p[1]) for p in c[0]]] if c else []
    if t == "MultiPolygon": return [[(p[0], p[1]) for p in poly[0]] for poly in c if poly]
    return []

def lines_of(g):
    t, c = g.get("type"), g.get("coordinates")
    if t == "LineString":      return [[(p[0], p[1]) for p in c]] if c else []
    if t == "MultiLineString": return [[(p[0], p[1]) for p in ln] for ln in c if ln]
    return []

def seg_x(a, b, eps=0.01):
    """两线段严格交于各自内部时返回交点(用于判定立交X形交叉)，否则 None。"""
    ax0, ay0, ax1, ay1 = a; bx0, by0, bx1, by1 = b
    rx, ry = ax1 - ax0, ay1 - ay0
    sx, sy = bx1 - bx0, by1 - by0
    d = rx * sy - ry * sx
    if d == 0:
        return None
    t = ((bx0 - ax0) * sy - (by0 - ay0) * sx) / d
    u = ((bx0 - ax0) * ry - (by0 - ay0) * rx) / d
    if eps < t < 1 - eps and eps < u < 1 - eps:
        return (ax0 + rx * t, ay0 + ry * t)
    return None

def compute_road_layers(feats, split_elev=True, snap=6e-6, cell=0.0006, maxlayer=5):
    """专家方案:把"层级"作为整条连通路径的属性，用差分约束(连接=等、立交=≥+1)解整数分层。
    feats: [{pts, elev, cls}]; 返回每条 feat 的整数层(0=地面)。"""
    n = len(feats)
    par = list(range(n))
    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: par[rb] = ra
    # 1) good-continuation 连成 stroke：同节点处,离地切线最接近反向(平直通过)的两端相连
    def nk(pt): return (round(pt[0] / snap), round(pt[1] / snap))
    def unit(vx, vy):
        m = (vx * vx + vy * vy) ** 0.5
        return (vx / m, vy / m) if m else (0.0, 0.0)
    node_ends = collections.defaultdict(list)
    for i, f in enumerate(feats):
        pts = f["pts"]
        node_ends[nk(pts[0])].append((i, unit(pts[1][0]-pts[0][0], pts[1][1]-pts[0][1]), pts[0], pts[1]))
        node_ends[nk(pts[-1])].append((i, unit(pts[-2][0]-pts[-1][0], pts[-2][1]-pts[-1][1]), pts[-1], pts[-2]))
    for ends in node_ends.values():
        if len(ends) < 2:
            continue
        cand = []
        for a in range(len(ends)):
            for b in range(a + 1, len(ends)):
                ia, ta, _, _ = ends[a]; ib, tb, _, _ = ends[b]
                if ia == ib:
                    continue
                if split_elev and abs(feats[ia]["elev"] - feats[ib]["elev"]) >= 7.5:
                    continue                                       # 方法①:高程突变处不连成同一 stroke → 层号沿路变化
                cand.append((ta[0]*tb[0] + ta[1]*tb[1], ia, ib))   # 越接近 -1 越平直
        cand.sort()
        used = set()
        for dot, ia, ib in cand:
            if dot > -0.5:                                          # 夹角<120°视为转弯,不连成同一stroke
                break
            if ia in used or ib in used:
                continue
            uni(ia, ib); used.add(ia); used.add(ib)
    # 2) 逐交叉点约束：严格交于内部=立交;高程高者层级更高
    grid = collections.defaultdict(list)
    seg = []
    for i, f in enumerate(feats):
        pts = f["pts"]
        for k in range(len(pts) - 1):
            j = len(seg); seg.append((pts[k][0], pts[k][1], pts[k+1][0], pts[k+1][1], i))
            steps = int(max(abs(seg[j][2]-seg[j][0]), abs(seg[j][3]-seg[j][1])) / cell) + 1
            for t in range(steps + 1):
                grid[(int((seg[j][0]+(seg[j][2]-seg[j][0])*t/steps)/cell),
                      int((seg[j][1]+(seg[j][3]-seg[j][1])*t/steps)/cell))].append(j)
    edges = set(); seen = set()
    for ids in grid.values():
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                ja, jb = ids[a], ids[b]
                kk = (ja, jb) if ja < jb else (jb, ja)
                if kk in seen:
                    continue
                seen.add(kk)
                fa, fb = seg[ja][4], seg[jb][4]
                if find(fa) == find(fb):
                    continue
                if seg_x(seg[ja][:4], seg[jb][:4]) is None:
                    continue
                ea, eb = feats[fa]["elev"], feats[fb]["elev"]
                if abs(ea - eb) < 1.0:
                    continue
                hi, lo = (fa, fb) if ea > eb else (fb, fa)
                edges.add((find(lo), find(hi)))                    # 低 → 高 (高 ≥ 低+1)
    # 3) 最长路径层号 (Bellman-Ford 松弛, 限层数)
    layer = collections.defaultdict(int)
    el = list(edges)
    for _ in range(maxlayer + 2):
        ch = False
        for u, o in el:
            if layer[o] < layer[u] + 1:
                layer[o] = min(layer[u] + 1, maxlayer); ch = True
        if not ch:
            break
    out = [layer[find(i)] for i in range(n)]
    # 方法②素材:跨层路口,记录低层支线的"结尾段"(端点+相邻顶点),用其填充重画一遍汇入高层主路
    merges = []
    for ends in node_ends.values():
        if len(ends) < 2:
            continue
        lays = [out[fi] for fi, _, _, _ in ends]
        hi = max(lays)
        if min(lays) == hi:
            continue
        for fi, tang, coord, adj in ends:
            if out[fi] < hi:
                merges.append((feats[fi]["cls"], hi, coord[0], coord[1], adj[0], adj[1]))
    return out, len(edges), merges

def grade_caps(feats, thr=7.5, cell=0.0006, half=0.00016):
    """用户方案:所有路视为全程连续;遍历两两相交,仅在高差≥thr(m)处判为立交,
    让高程高者在交点架一小段"桥盖"盖过低者。空间网格 → 只查同格,无需全矩阵。"""
    grid = collections.defaultdict(list)
    seg = []
    for i, f in enumerate(feats):
        pts = f["pts"]
        for k in range(len(pts) - 1):
            j = len(seg); seg.append((pts[k][0], pts[k][1], pts[k+1][0], pts[k+1][1], i))
            steps = int(max(abs(seg[j][2]-seg[j][0]), abs(seg[j][3]-seg[j][1])) / cell) + 1
            for t in range(steps + 1):
                grid[(int((seg[j][0]+(seg[j][2]-seg[j][0])*t/steps)/cell),
                      int((seg[j][1]+(seg[j][3]-seg[j][1])*t/steps)/cell))].append(j)
    caps = collections.defaultdict(list); seen = set(); ncap = 0
    for ids in grid.values():
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                ja, jb = ids[a], ids[b]
                kk = (ja, jb) if ja < jb else (jb, ja)
                if kk in seen:
                    continue
                seen.add(kk)
                fa, fb = seg[ja][4], seg[jb][4]
                if fa == fb:
                    continue
                ea, eb = feats[fa]["elev"], feats[fb]["elev"]
                if abs(ea - eb) < thr:                       # 高差不足 → 平面相接,不架桥
                    continue
                X = seg_x(seg[ja][:4], seg[jb][:4])
                if X is None:
                    continue
                o = seg[ja] if ea >= eb else seg[jb]         # 高者的那段
                dx, dy = o[2]-o[0], o[3]-o[1]
                L = (dx*dx + dy*dy) ** 0.5
                if L == 0:
                    continue
                ux, uy = dx/L, dy/L
                caps[feats[o[4]]["cls"]].append((X[0], X[1], ux, uy))   # 交点 + 桥方向
                ncap += 1
    return caps, ncap

def merge_pts(pts, thr=0.0004):
    """相邻点(同一站的站台/出入口)合并为质心，~44m 内归一。"""
    out = []
    for x, y in pts:
        for i, c in enumerate(out):
            if abs(x - c[0]) < thr and abs(y - c[1]) < thr:
                out[i] = ((c[0]*c[2]+x)/(c[2]+1), (c[1]*c[2]+y)/(c[2]+1), c[2]+1)
                break
        else:
            out.append((x, y, 1))
    return [(c[0], c[1]) for c in out]

def water_layer():
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from rasterio.transform import array_bounds
    with rasterio.open(os.path.join(TIF, "Depth.tif")) as src:
        tr, w, h = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        arr = np.full((h, w), src.nodata, dtype="float32")
        reproject(rasterio.band(src, 1), arr, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=tr, dst_crs="EPSG:4326", resampling=Resampling.nearest)
        nd = src.nodata
    l, b, r, t = array_bounds(h, w, tr)
    rgba = np.zeros((h, w, 4)); wb = tuple(int(WATER[i:i+2], 16)/255 for i in (1, 3, 5))
    rgba[arr != nd] = (*wb, 1.0)
    return rgba, [l, r, b, t]

def hillshade_layer(base=0.18):
    """极微弱地形阴影(仅暗部，叠在陆地上)。"""
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from rasterio.transform import array_bounds
    from matplotlib.colors import LightSource
    with rasterio.open(os.path.join(TIF, "Elevation.tif")) as src:
        tr, w, h = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        elev = np.full((h, w), src.nodata, dtype="float32")
        reproject(rasterio.band(src, 1), elev, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=tr, dst_crs="EPSG:4326", resampling=Resampling.bilinear)
        end = src.nodata
    with rasterio.open(os.path.join(TIF, "Depth.tif")) as src:    # 投到与高程相同的网格
        dep = np.full((h, w), src.nodata, dtype="float32")
        reproject(rasterio.band(src, 1), dep, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=tr, dst_crs="EPSG:4326", resampling=Resampling.nearest)
        dnd = src.nodata
    lo = float(np.nanmin(elev[elev != end])) if np.any(elev != end) else 0.0
    fill = np.where(elev == end, lo, elev)
    hs = LightSource(azdeg=315, altdeg=45).hillshade(fill, vert_exag=2.0, dx=7, dy=7)
    rgba = np.zeros((h, w, 4))
    alpha = (1.0 - hs) * base
    alpha[dep != dnd] = 0.0                       # 水面不加阴影
    rgba[..., 3] = alpha
    l, b, r, t = array_bounds(h, w, tr)
    return rgba, [l, r, b, t]

def terrain_sampler():
    """返回 sample(lon,lat)->地形高程(米)，用于算道路离地高度。"""
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    with rasterio.open(os.path.join(TIF, "Elevation.tif")) as src:
        tr, w, h = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        arr = np.full((h, w), src.nodata, dtype="float32")
        reproject(rasterio.band(src, 1), arr, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=tr, dst_crs="EPSG:4326", resampling=Resampling.bilinear)
        nd = src.nodata
    a, e, c0, f0 = tr.a, tr.e, tr.c, tr.f
    H, Wd = arr.shape
    def sample(lon, lat):
        col = int((lon - c0) / a); row = int((lat - f0) / e)
        if 0 <= row < H and 0 <= col < Wd:
            v = arr[row, col]
            if v != nd: return float(v)
        return None
    return sample

def render_terrain_rot(out_path, title="Cities: Skylines 2 — Terrain (180°)"):
    """单独渲染地形图:内容旋转180°(轴反转),标题保持正立。"""
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from rasterio.transform import array_bounds
    from matplotlib.colors import LightSource
    with rasterio.open(os.path.join(TIF, "Elevation.tif")) as src:
        tr, w, h = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        arr = np.full((h, w), src.nodata, dtype="float32")
        reproject(rasterio.band(src, 1), arr, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=tr, dst_crs="EPSG:4326", resampling=Resampling.bilinear)
        nd = src.nodata
    arr = np.where(arr == nd, np.nan, arr)
    l, b, r, t = array_bounds(h, w, tr)
    lo = float(np.nanmin(arr))
    rgb = LightSource(azdeg=315, altdeg=45).shade(np.nan_to_num(arr, nan=lo), cmap=plt.cm.terrain,
                                                  blend_mode="soft", vert_exag=3)
    fig, ax = plt.subplots(figsize=(FIGSIZE, FIGSIZE))
    ax.set_aspect("equal"); ax.axis("off")
    ax.imshow(rgb, extent=[l, r, b, t], origin="upper")
    ax.set_xlim(l, r); ax.set_ylim(b, t)
    ax.invert_xaxis(); ax.invert_yaxis()            # 内容旋转180°(标题不受影响,仍正立)
    ax.set_title(title, fontsize=16, pad=10)
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    plt.close(fig)
    print(f"[输出] {out_path}")

def main():
    t0 = time.time()
    fig, ax = plt.subplots(figsize=(FIGSIZE, FIGSIZE))
    ax.set_facecolor(LAND); ax.set_aspect("equal"); ax.axis("off")

    print("== 水面 + 地形微阴影 ==")
    rgba, extent = water_layer()
    ax.imshow(rgba, extent=extent, origin="upper", zorder=5, interpolation="nearest")
    hrgba, hext = hillshade_layer()
    ax.imshow(hrgba, extent=hext, origin="upper", zorder=28, interpolation="bilinear")
    ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
    _p0 = ax.transData.transform((0.0, extent[2])); _p1 = ax.transData.transform((0.001, extent[2]))
    deg_per_pt = fig.dpi / (72.0 * (abs(_p1[0] - _p0[0]) / 0.001))   # 1 磅线宽 ≈ ? 度(线宽→数据偏移)

    print("== 分区(含特色工业) ==")
    zp = collections.defaultdict(list)
    for ft in load("Zoning_Boundary"):
        zp[zone_color(ft["properties"])].extend(rings_of(ft["geometry"]))
    for col, polys in zp.items():
        ax.add_collection(PolyCollection(polys, facecolors=col, edgecolors="none", zorder=10))
    del zp

    print("== 建筑(按功能上色)/市政/公用/交通设施 ==")
    bp = collections.defaultdict(list)
    all_bld = []                                   # 全部建筑轮廓(供街道图灰色建筑用)
    sig = collections.defaultdict(list)            # 地标(签名)建筑:按用地类型(住/商/办/工/混合)
    # 签名建筑判据(经 18196 栋交叉验证):Level5 + 真实分区 + 资产名无生长标记 ⟺ 全城唯一(双向0例外)。
    # 生长标记正则覆盖本地化变体:'_L5_2x2'、'(L4)'、'农业 03 L3'、'工业制造 01 - L1 2x2' 等。
    GROWTH_RE = re.compile(r"(_L[1-5]|\(L[1-5]\)|\bL[1-5]\b|\b\d+x\d+\b| - L[1-5] | L[1-5] )")
    for ft in load("Building_Boundary"):
        p = ft["properties"]
        r = rings_of(ft["geometry"])
        bp[building_style(p)].extend(r)
        all_bld.extend(r)
        asset = str(p.get("Asset", ""))
        zon = str(p.get("Zoning") or "")
        is_sig = (str(p.get("Level")) == "5" and zon not in ("", "None")
                  and not GROWTH_RE.search(asset))
        if (is_sig or "Signature" in asset) and r:    # +Pack10 字面签名子件(Level0/Zoning None)
            if   "," in zon:           zt = "mixed"       # 'Residential, Commercial' = 混合地标
            elif zon == "Residential": zt = "residential"
            elif zon == "Commercial":  zt = "commercial"
            elif zon == "Office":      zt = "office"
            elif zon == "Industrial":  zt = "industrial"
            else:                                          # Pack10 字面签名:按资产前缀字母 RH/OH/M…
                m = re.search(r"([A-Za-z]+)Signature", asset)
                c0 = (m.group(1).upper()[:1] if m else "M")
                zt = {"R": "residential", "C": "commercial", "O": "office", "I": "industrial"}.get(c0, "mixed")
            xs0 = [x for x, _ in r[0]]; ys0 = [y for _, y in r[0]]
            sig[zt].append((sum(xs0)/len(xs0), sum(ys0)/len(ys0)))
    for (fc, ec, z), polys in sorted(bp.items(), key=lambda kv: kv[0][2]):
        ax.add_collection(PolyCollection(polys, facecolors=fc, edgecolors=ec, linewidths=0.1*W, zorder=z))
    print(f"     建筑样式 {len(bp)} 种，共 {sum(len(v) for v in bp.values())} 栋; 地标建筑 {sum(len(v) for v in sig.values())}")
    del bp

    print("== 路网/轨道/航道 (约束求解整数分层) ==")
    feats = []                                   # 非隧道道路逐条 {pts, elev, cls}
    tun = {k: [] for k in ORD}                   # 隧道 Form=Tunnel(单独画在最底)
    rail, rail_tun, subway, tram, path, runway, taxiway = ([] for _ in range(7))
    ww_narrow, ww_large, ww_pier = [], [], []
    for ft in load("Network_Centerline"):
        p = ft["properties"]; obj = p.get("Object"); cat = str(p.get("Category", "")); form = p.get("Form")
        segs = lines_of(ft["geometry"])
        if obj == "Road":
            cls = next((c for c in ORD if c in cat), "Small")
            if form == "Tunnel":
                tun[cls].extend(segs)
            else:
                ev = p.get("Elevation") or 0.0
                for ln in segs:
                    if len(ln) >= 2:
                        feats.append({"pts": ln, "elev": ev, "cls": cls})
        elif obj == "Track":
            if   "Train"  in cat: (rail_tun if form == "Tunnel" else rail).extend(segs)
            elif "Subway" in cat: subway.extend(segs)
            elif "Tram"   in cat: tram.extend(segs)
        elif obj == "Pathway":  path.extend(segs)
        elif obj == "Runway":   runway.extend(segs)
        elif obj == "Taxiway":  taxiway.extend(segs)
        elif obj == "Waterway":
            asset = str(p.get("Asset", ""))
            if "Pier" in asset:                                   # 码头/平台周边服务航道 → 降级
                ww_pier.extend(segs)
            elif (p.get("Width") or 0) >= 100:
                ww_large.extend(segs)
            else:
                ww_narrow.extend(segs)

    # 航道：平台/码头服务航道=极细淡(降级)，窄=细，大航道(3宽合并)=粗一号；经典航线半透明蓝虚线
    ax.add_collection(LineCollection(ww_pier,   colors="#2c5d8a", linewidths=0.4*W, alpha=0.35, linestyles=[(0,(4,4))], zorder=25.8))
    ax.add_collection(LineCollection(ww_narrow, colors="#2c5d8a", linewidths=0.7*W, alpha=0.55, linestyles=[(0,(7,4))], zorder=26))
    ax.add_collection(LineCollection(ww_large,  colors="#2c5d8a", linewidths=1.3*W, alpha=0.55, linestyles=[(0,(8,4))], zorder=26.5))
    ax.add_collection(LineCollection(path, colors="#b7a589", linewidths=0.28*W, linestyles=[(0,(1.5,1.5))], zorder=30))
    ax.add_collection(LineCollection(runway,  colors="#c8c8c8", linewidths=2.2*W, zorder=31))
    ax.add_collection(LineCollection(taxiway, colors="#d9c97a", linewidths=0.9*W, zorder=32))
    ax.add_collection(LineCollection(tram, colors="#8a8a8a", linewidths=0.3*W, zorder=33))
    ax.add_collection(LineCollection(rail_tun, colors="#777777", linewidths=0.6*W, alpha=0.85, linestyles=[(0,(4,3))], zorder=34))
    for i, cls in enumerate(reversed(ORD)):
        s = ROAD[cls]
        ax.add_collection(LineCollection(tun[cls], colors=s["fc"], linewidths=s["fw"]*W, linestyles=[(0,(4,3))], alpha=0.8, zorder=35+i*0.1))
    ax.add_collection(LineCollection(subway, colors="#6b6b6b", linewidths=0.55*W, alpha=0.5, zorder=36))
    ax.add_collection(LineCollection(subway, colors="#ffffff", linewidths=0.4*W, alpha=0.5, linestyles=[(0,(4,4))], zorder=36.1))

    # 道路：连续高程分层。casing z=BASE+q，fill z=BASE+q+EPS（地面q=0用本色，高架用深桥边）
    print("== 道路：约束分层 + 高等级 butt 端点" +
          ("｜方法①沿高程分层" if SPLIT_ELEV else "") + ("｜方法②路口填充汇入" if FILL_MERGE else "") + " ==")
    tl = time.time()
    layers, ne, merges = compute_road_layers(feats, split_elev=SPLIT_ELEV)
    maxL = max(layers) if layers else 0
    bylc = collections.defaultdict(list)
    allroad = collections.defaultdict(list)
    for i, f in enumerate(feats):
        bylc[(layers[i], f["cls"])].append(f["pts"])
        allroad[f["cls"]].append(f["pts"])
    NOEND = {"Highway", "Large", "Medium"}              # 高等级/高速:端点用 butt(平头不探出)→ 分层过渡处不再被盖出接缝
    def cap_of(cls): return "butt" if cls in NOEND else "round"
    # 逐层(升序)两遍：层内 casing→fill;高层整层压低层 → 上跨(含高架跨高架)
    for L in range(maxL + 1):
        zc = 40 + L * 10
        for i, cls in enumerate(reversed(ORD)):
            s = ROAD[cls]
            ax.add_collection(LineCollection(bylc.get((L, cls), []), colors=s["cc"], linewidths=s["cw"]*W,
                                             zorder=zc+i, capstyle=cap_of(cls), joinstyle="round"))
        for i, cls in enumerate(reversed(ORD)):
            s = ROAD[cls]
            ax.add_collection(LineCollection(bylc.get((L, cls), []), colors=s["fc"], linewidths=s["fw"]*W,
                                             zorder=zc+5+i, capstyle=cap_of(cls), joinstyle="round"))
        if L == 0:                                      # 铁路:地面层之上、高架层之下
            ax.add_collection(LineCollection(rail, colors="#5f5f5f", linewidths=0.85*W, zorder=zc+9.3))
            ax.add_collection(LineCollection(rail, colors="#ffffff", linewidths=0.5*W,
                                             linestyles=[(0, (4, 4))], zorder=zc+9.4))
    if FILL_MERGE:                                   # 方法②:重画支线"结尾段"的填充,盖过主路描边→汇入主路(不延长)
        MAXLEN = 0.0003                              # 结尾段过长则截到这个长度(够盖住主路描边即可)
        mg = collections.defaultdict(list)
        for cls, hi, ex, ey, axv, ayv in merges:
            dx, dy = axv - ex, ayv - ey
            L = (dx*dx + dy*dy) ** 0.5
            if L == 0:
                continue
            f = min(L, MAXLEN) / L
            mg[(cls, hi)].append([(ex, ey), (ex + dx*f, ey + dy*f)])
        for (cls, hi), segs in mg.items():
            s = ROAD[cls]
            ax.add_collection(LineCollection(segs, colors=s["fc"], linewidths=s["fw"]*W,
                                             zorder=40 + hi*10 + 4, capstyle="round"))
    print(f"     道路 {len(feats)} 条 → {maxL+1} 层, {ne} 立交约束, 跨层口 {len(merges)} ({time.time()-tl:.1f}s)")
    print(f"     隧道 {sum(len(v) for v in tun.values())} 铁路 {len(rail)} 地铁 {len(subway)} "
          f"电车 {len(tram)} 人行 {len(path)} 航道 窄{len(ww_narrow)}/大{len(ww_large)}/平台{len(ww_pier)}")

    # 标记：交通站点 / 地标 / 公交·电车站
    print("== 标记 ==")
    EX_KW = ("天桥", "入口", "自行车")          # 公园里排除：人行天桥/入口/自行车设施
    mk = collections.defaultdict(list)
    for ft in load("POI_Location"):
        p = ft["properties"]; obj = p.get("Object"); cat = str(p.get("Category", ""))
        c = ft["geometry"]["coordinates"]; xy = (c[0], c[1])
        if obj == "POITransport":
            if   "Building" in cat and "PassengerTrain" in cat: mk["train"].append(xy)
            elif "CargoTrain" in cat:                           mk["cargo_train"].append(xy)  # 货运火车站(含港口内)
            elif "Building" in cat and "Subway" in cat:         mk["metro"].append(xy)
            elif "StopSubway" in cat:                           mk["_substop"].append(xy)
            elif "PassengerAirplane" in cat:                    mk["airport"].append(xy)
            elif "Building" in cat and "CargoShip" in cat:      mk["port_cargo"].append(xy)
            elif "Building" in cat and "PassengerShip" in cat:  mk["port_pax"].append(xy)
            elif "Building" in cat and "Ferry" in cat:          mk["ferry"].append(xy)
            elif "StopBus" in cat:  mk["bus"].append(xy)
            elif "StopTram" in cat: mk["tram"].append(xy)
        elif obj == "POIPublic":
            nm = str(p.get("Name", ""))
            if   "Health" in cat:                  mk["hospital"].append(xy)
            elif "Police" in cat:                  mk["police"].append(xy)
            elif "Fire" in cat:                    mk["fire"].append(xy)
            elif "Admin" in cat:                   mk["gov"].append(xy)
            elif "EducationUniversity" in cat or "EducationCollege" in cat: mk["uni"].append(xy)
            elif "EducationHigh" in cat:           mk["middle"].append(xy)
            elif "EducationElementary" in cat:     mk["elementary"].append(xy)
            elif "Research" in cat:                mk["research"].append(xy)
            elif "Education" in cat:               mk["elementary"].append(xy)   # 泛教育并入小学
            elif ("Attraction" in cat or "Park" in cat) and not any(k in nm for k in EX_KW):
                mk["landmark"].append(xy)
    extra = [pt for pt in mk["_substop"]
             if not any(abs(pt[0]-u) < 0.0005 and abs(pt[1]-v) < 0.0005 for u, v in mk["metro"])]
    mk["metro"] = mk["metro"] + extra                              # 火车站等建筑附带的地铁站(独立 StopSubway)补入
    mk.pop("_substop", None)
    for k in ("tram", "train", "cargo_train", "port_cargo", "port_pax", "ferry",
              "hospital", "police", "fire", "gov", "uni", "middle", "elementary", "research"):
        mk[k] = merge_pts(mk[k])                                   # 主楼+附属建筑合并（公交/地铁不合并）
    S = 0.78                                                       # 标签统一缩小
    def scat(key, marker, color, s, z, ec="white", lw=0.4):
        if mk[key]:
            xs, ys = zip(*mk[key]); ax.scatter(xs, ys, marker=marker, s=s, c=color,
                                               edgecolors=ec, linewidths=lw, zorder=z)
        print(f"     {key}: {len(mk[key])}")
    def logo(key, letter, fill, shape="o", s=29*S):                # 徽标(整体×1.2)：市政=圆 / 学校=方 + 白字母
        if not mk[key]:
            print(f"     {key}: 0"); return
        xs, ys = zip(*mk[key])
        ax.scatter(xs, ys, marker=shape, s=s, c=fill, edgecolors=_darken(fill, 0.6), linewidths=0.3, zorder=153)
        ax.scatter(xs, ys, marker=letter_marker(letter), s=s*0.33, c="white", zorder=153.1)
        print(f"     {key}: {len(mk[key])}")
    scat("bus",  ".", "#666666", 2*S,  150, ec="none", lw=0)
    scat("tram", ".", "#9a6b9a", 2*S,  150, ec="none", lw=0)
    scat("train",      "s", "#b5341f", 24*S, 151, ec="#2e2e2e", lw=0.25)   # 客运火车站
    scat("cargo_train","s", "#5b3a1a", 19*S, 151, ec="#2e2e2e", lw=0.25)   # 货运火车站
    scat("metro",      "o", "#1f6fb0", 11*S, 151, ec="#2e2e2e", lw=0.25)   # 地铁站
    scat("airport",    "^", "#7d3ca5", 30*S, 151, ec="#2e2e2e", lw=0.25)   # 机场
    scat("port_cargo", "D", "#8a5a2b", 20*S, 151, ec="#2e2e2e", lw=0.25)   # 货运港 棕
    scat("port_pax",   "D", "#1f6f8f", 20*S, 151, ec="#2e2e2e", lw=0.25)   # 客运港 青
    scat("ferry",      "d", "#36a0c8", 9*S,  151, ec="#2e2e2e", lw=0.25)   # 摆渡
    scat("landmark",   "*", "#e8a81a", 17*S, 152, ec="#6e4f00", lw=0.4)    # 地标星
    logo("hospital", "H", "#c62828", "o")    # 医院
    logo("fire",     "F", "#e65100", "o")    # 消防
    logo("police",   "P", "#1565c0", "o")    # 警局
    logo("gov",      "G", "#6a1b9a", "o")    # 政府
    logo("uni",        "U", "#1a237e", "s")  # 大学
    logo("middle",     "M", "#3949ab", "s")  # 中学
    logo("elementary", "E", "#5c6bc0", "s")  # 小学
    logo("research",   "R", "#00695c", "s")  # 研究院
    SIGCOL = {"residential": "#2e8b57", "commercial": "#1f6fb0", "office": "#7d3ca5",
              "industrial": "#b5912a", "mixed": "#d2691e"}                         # 地标建筑:金边菱形,按用地分色
    for zt, pts in sig.items():
        xs, ys = zip(*pts)
        ax.scatter(xs, ys, marker="D", s=13*S, c=SIGCOL[zt], edgecolors="#e8a81a", linewidths=0.4, zorder=154)
        print(f"     地标 {zt}: {len(pts)}")

    ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
    ax.invert_xaxis(); ax.invert_yaxis()
    ax.set_title("Cities: Skylines 2 — City Map", fontsize=16, pad=10)
    if PREVIEW:                                      # 只裁一小块看 logo 字号,跳过路线图
        pf = os.path.join(BASE, "_preview_base.png")
        fig.savefig(pf, dpi=DPI, bbox_inches="tight", pad_inches=0.05, facecolor="white")
        plt.close(fig)
        from PIL import Image
        im = Image.open(pf); w, h = im.size
        im.crop((int(w*0.42), int(h*0.43), int(w*0.51), int(h*0.51))).save(
            os.path.join(BASE, "_logo_preview.png"))   # 600dpi 原分辨率裁切,不缩小
        print("[预览] _logo_preview.png  总用时 %.1fs" % (time.time()-t0))
        return
    out = next_out()
    fig.savefig(out, dpi=BASE_DPI, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    print(f"[输出] {out}  ({os.path.getsize(out)/1e6:.1f} MB)")
    ver = re.search(r"_v(\d+)\.png$", out).group(1)

    # ---------- 路线图叠加版本：压暗底图 + 高亮 ----------
    route_feats = load("Route_Centerline")
    PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42a5d4", "#f032e6", "#7cb342",
               "#00897b", "#9a6324", "#8e44ad", "#c0392b", "#16a085", "#d35400", "#2c3e50", "#e67e22"]
    DASH = [(0, (6, 3))]
    def segs_of(transports, obj=None):
        return [s for ft in route_feats if ft["properties"].get("Transport") in transports
                and (obj is None or ft["properties"].get("Object") == obj)
                for s in lines_of(ft["geometry"])]
    def lines_by_route(transports, obj=None):
        g = collections.defaultdict(list)
        for ft in route_feats:
            pr = ft["properties"]
            if pr.get("Transport") in transports and (obj is None or pr.get("Object") == obj):
                g[(pr.get("Route"), pr.get("Name"))].extend(lines_of(ft["geometry"]))
        return list(g.values())
    def add_lc(arts, segs, color, lw, z, ls="solid", alpha=1.0):
        if segs:
            arts.append(ax.add_collection(LineCollection(segs, colors=color, linewidths=lw, zorder=z,
                        linestyles=ls, alpha=alpha, capstyle="round", joinstyle="round")))
    def add_perline(arts, groups, lw, z, ls="solid", casing="white"):
        add_lc(arts, [s for g in groups for s in g], casing, lw + 1.8, z, alpha=0.9)
        for i, segs in enumerate(groups):
            add_lc(arts, segs, PALETTE[i % len(PALETTE)], lw, z + 0.02, ls=ls)
    def add_stations(arts, items, ec="white", lw=0.9, z0=240):   # 交通图站点：放大 2.8×
        for key, shape, col, s in items:
            if mk[key]:
                xs, ys = zip(*mk[key])
                arts.append(ax.scatter(xs, ys, marker=shape, s=s * 2.8, c=col,
                                       edgecolors=ec, linewidths=lw, zorder=z0))
    def add_logo(arts, key, letter, fill, s=70 * S):
        if mk[key]:
            xs, ys = zip(*mk[key])
            arts.append(ax.scatter(xs, ys, marker="o", s=s, c=fill, edgecolors="white", linewidths=1.0, zorder=241))
            arts.append(ax.scatter(xs, ys, marker="$%s$" % letter, s=s * 0.34, c="white", zorder=241.1))
    def save_overlay(name, title, build):
        arts = [ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                                       facecolor="white", alpha=0.72, zorder=155))]
        build(arts)
        old = ax.get_title(); ax.set_title(title, fontsize=16, pad=10)
        p = os.path.join(BASE, f"map_{name}_v{ver}.png")
        fig.savefig(p, dpi=DPI, bbox_inches="tight", pad_inches=0.05, facecolor="white")
        for a in arts: a.remove()
        ax.set_title(old, fontsize=16, pad=10)
        print(f"[输出] {p}")

    def build_metro(arts):
        add_perline(arts, lines_by_route({"Subway"}), 2.6, 200)
        add_stations(arts, [("metro", "o", "#1f6fb0", 22 * S)])
    def build_train(arts):
        add_lc(arts, segs_of({"Train"}, "RouteCargo"), "#5b3a1a", 1.8, 199)                      # 货运火车 暗棕实线
        add_perline(arts, lines_by_route({"Train"}, "RoutePassenger"), 2.4, 200)                 # 客运分线 实线
        add_stations(arts, [("cargo_train", "s", "#5b3a1a", 16 * S), ("train", "s", "#b5341f", 22 * S)])
    def build_tram(arts):
        add_perline(arts, lines_by_route({"Tram"}), 1.8, 200)
        add_stations(arts, [("tram", "o", "#9a4fc0", 16 * S)], ec="#5e2f78", lw=0.5)   # 大圆点、深紫边(非白)
    def build_bus(arts):
        add_perline(arts, lines_by_route({"Bus"}), 1.4, 200)
        add_stations(arts, [("bus", "o", "#1aa3a3", 16 * S)], ec="#0e5d5d", lw=0.5)   # 大圆点、深青边(非白)
    def build_shipping(arts):                       # 航运：客运+货运 船线
        add_perline(arts, lines_by_route({"Ship"}), 1.8, 200)
        add_stations(arts, [("port_cargo", "D", "#8a5a2b", 16 * S), ("port_pax", "D", "#1f6f8f", 18 * S)])
    def build_waterway(arts):                       # 航线/航道：物理水道(含货运服务航道)
        add_lc(arts, ww_pier,   "#3a78a8", 0.9, 200, ls=[(0, (4, 4))], alpha=0.85)
        add_lc(arts, ww_narrow, "#2c5d8a", 1.4, 201, ls=[(0, (7, 4))])
        add_lc(arts, ww_large,  "#1f4e79", 2.6, 202, ls=[(0, (8, 4))])
        add_stations(arts, [("port_cargo", "D", "#8a5a2b", 15 * S), ("port_pax", "D", "#1f6f8f", 15 * S),
                            ("ferry", "d", "#36a0c8", 12 * S)])
    def build_ferry(arts):
        add_perline(arts, lines_by_route({"Ferry"}), 1.6, 200)
        add_stations(arts, [("ferry", "d", "#36a0c8", 16 * S)])
    def build_transit(arts):                        # 综合:地铁(线+站)最重要在最上 → 火车其次 → 其他更次
        # 其他(最次):公交/电车/客运航运/摆渡 细线
        add_lc(arts, segs_of({"Ship"}, "RoutePassenger"), "#2c5d8a", 0.9, 195.5, ls=DASH, alpha=0.7)
        add_lc(arts, segs_of({"Ferry"}), "#2c5d8a", 0.7, 195.6, ls=DASH, alpha=0.7)
        add_lc(arts, segs_of({"Bus"}),  "#1aa3a3", 0.8, 196, alpha=0.75)
        add_lc(arts, segs_of({"Tram"}), "#9a4fc0", 0.8, 196.2, alpha=0.75)
        add_logo(arts, "airport", "A", "#7d3ca5", 64 * S)                                      # 机场
        # 火车(其次):黑边
        add_perline(arts, lines_by_route({"Train"}, "RoutePassenger"), 2.2, 200, casing="#111111")
        # 地铁(最重要):线在最上
        add_perline(arts, lines_by_route({"Subway"}), 2.6, 204, ls="solid")
        # 站点叠压:其他 < 火车 < 地铁
        add_stations(arts, [("bus", ".", "#555555", 4 * S), ("port_pax", "D", "#1f6f8f", 16 * S),
                            ("ferry", "d", "#36a0c8", 13 * S)], z0=238)
        add_stations(arts, [("train", "s", "#b5341f", 18 * S)], z0=242)
        add_stations(arts, [("metro", "o", "#1f6fb0", 20 * S)], z0=246)
    def build_highway(arts):                        # 干净底(陆/水)+基础路网淡灰(入覆盖层)+高等级黑+高速橙(最上)
        arts.append(ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor="#f4f1ea", zorder=158)))
        arts.append(ax.imshow(rgba, extent=extent, origin="upper", zorder=159, interpolation="nearest"))
        hw = allroad["Highway"] + tun["Highway"]
        lg = allroad["Large"] + tun["Large"]
        md = allroad["Medium"] + tun["Medium"]
        sm = allroad["Small"] + tun["Small"]
        add_lc(arts, path, "#000000", 0.25, 160)    # 基础路网全黑,只用粗细区分等级
        add_lc(arts, sm,   "#000000", 0.5,  161)
        add_lc(arts, md,   "#000000", 1.1,  162)
        add_lc(arts, lg,   "#000000", 2.0,  163)    # 次高等级(4车道类)黑
        add_lc(arts, hw,   "#c06f12", 3.9,  164)    # 高速:深橙描边
        add_lc(arts, hw,   "#f29400", 2.7,  165)    # 高速:景点橙(颜色不变,压最上)
    def build_rail(arts):                           # 只有地铁 + 客运火车(不含货运)
        add_perline(arts, lines_by_route({"Subway"}), 2.4, 200)                                    # 地铁 白边
        add_perline(arts, lines_by_route({"Train"}, "RoutePassenger"), 2.4, 202, casing="#111111") # 火车 黑边
        add_stations(arts, [("metro", "o", "#1f6fb0", 20 * S), ("train", "s", "#b5341f", 20 * S)])
    def build_street(arts):                         # 极简街道图：陆/水 + 单色细线道路(不分级/无描边) + 单色建筑
        arts.append(ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor="#f2efe8", zorder=160)))
        arts.append(ax.imshow(rgba, extent=extent, origin="upper", zorder=161, interpolation="nearest"))
        arts.append(ax.add_collection(PolyCollection(all_bld, facecolors="#dcd3c2", edgecolors="none", zorder=162)))
        allsegs = ([s for cls in ORD for s in allroad[cls]]
                   + [s for cls in ORD for s in tun[cls]])           # 所有道路(含隧道)合并,不分级,同实线
        arts.append(ax.add_collection(LineCollection(allsegs, colors="#585858", linewidths=0.5*W,
                    zorder=163, capstyle="round", joinstyle="round")))   # 单色细线、无 casing
        arts.append(ax.add_collection(LineCollection(rail + rail_tun, colors="#9a9a9a", linewidths=0.4*W, zorder=164)))   # 含铁路隧道
    save_overlay("metro",    "Metro Lines",          build_metro)
    save_overlay("train",    "Railway Lines",        build_train)
    save_overlay("rail",     "Metro & Rail",         build_rail)
    save_overlay("tram",     "Tram Lines",           build_tram)
    save_overlay("bus",      "Bus Lines",            build_bus)
    save_overlay("shipping", "Shipping Routes",      build_shipping)
    save_overlay("waterway", "Waterways",            build_waterway)
    save_overlay("transit",  "Public Transit",       build_transit)
    save_overlay("highway",  "Highways & Arterials", build_highway)
    save_overlay("street",   "Street Map",           build_street)
    plt.close(fig)
    render_terrain_rot(os.path.join(BASE, "map_terrain_180.png"))
    print(f"\n总用时 {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
