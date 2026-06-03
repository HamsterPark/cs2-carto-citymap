# CS2 Carto 城市地图渲染器

把 **《都市天际线 2》(Cities: Skylines II)** 的存档,渲染成出版级城市地图——**纯 Python(matplotlib)** 实现,数据来自 **Carto** mod 的导出。无需 QGIS,无需 geopandas。

[English](README.md) · **中文**

![城市底图](gallery/city.png)

一份 Carto 导出 → **13 张地图**:一张精细的城市底图,外加多张专题叠加图(高速公路、公共交通、地铁、铁路、有轨电车、公交、航运、航道、极简街道图),以及地形晕渲图。

---

## 图廊

| 高速与干道 | 公共交通 |
|:---:|:---:|
| ![highway](gallery/highway.png) | ![transit](gallery/transit.png) |
| **地铁线路** | **铁路(客运)线路** |
| ![metro](gallery/metro.png) | ![train](gallery/train.png) |
| **地铁 + 铁路** | **有轨电车线路** |
| ![rail](gallery/rail.png) | ![tram](gallery/tram.png) |
| **公交线路** | **航运航线** |
| ![bus](gallery/bus.png) | ![shipping](gallery/shipping.png) |
| **航道** | **街道图** |
| ![waterway](gallery/waterway.png) | ![street](gallery/street.png) |
| **地形(晕渲)** | **地形(旋转 180°)** |
| ![terrain](gallery/terrain.png) | ![terrain 180](gallery/terrain_180.png) |

> 图廊为缩小后的网页预览图。运行脚本会生成全分辨率原图(底图最高 600 DPI)。

---

## 亮点

- **纯 Python 管线** — 仅用 `matplotlib` + `numpy` + `rasterio`,不依赖 QGIS、geopandas/shapely。
- **正确的道路立交分层** — 用约束求解处理上跨:端点吸附 + good-continuation 连成连续路段,检测真正的立交交叉(空间网格上的线段内部相交),转成差分约束(`高层 ≥ 低层 + 1`),再用 Bellman–Ford 最长路松弛求整数层。于是高架正确叠压,**且匝道/爬坡段不被切碎**。高等级道路用 `butt` 平头端点消除过渡接缝,并对支线"结尾段"重画填充,使其汇入主路时观感连续。详见 [`docs/`](docs/)。
- **标志性建筑与地标识别** — CS2 的*标志性建筑(Signature Building)*用结构化判据识别:`Level == 5` + 真实分区 + 资产名无生长标记 ⟺ 全城唯一(在 18196 栋建筑上交叉验证,**双向零例外**),按用地类型(住宅 / 商业 / 办公 / 工业 / 混合)绘成分色菱形。DLC 的*独特景点(Attraction,来自 POI 数据)*绘成金色五角星。
- **经典制图风格** — 分区按密度配色、道路分级设宽、铁路/地铁/电车专用配色、半透明航道、市政设施徽标、底图下方的地形微晕渲。
- **线路分色**(带描边),并在整合交通图上按 地铁 > 铁路 > 其他 的叠压顺序保证可读性。
- **地形晕渲** — 由高程 GeoTIFF + 水深 GeoTIFF 合成,含真正的 180° 旋转版本(旋转的是图面内容,标题保持正立)。
- **安全的版本化输出** — 每次运行写出 `map_*_vN.png`,版本号自动递增,**绝不覆盖**旧图。

---

## 环境要求

- Python 3.9+
- `pip install -r requirements.txt`(matplotlib、numpy、rasterio、pillow)

> Windows 上 `rasterio` 的 pip 轮子已自带 GDAL,无需单独安装。

---

## 快速开始(使用示例城市)

```bash
git clone https://github.com/HamsterPark/cs2-carto-citymap.git
cd cs2-carto-citymap
pip install -r requirements.txt
```

然后从 [**Releases**](../../releases) 页面下载 **`carto-example-data.zip`**,解压到仓库根目录,使结构变为:

```
cs2-carto-citymap/
├── Carto/
│   ├── GeoJSON/   Zoning_Boundary.json、Building_Boundary.json、Network_Centerline.json、Route_Centerline.json、POI_Location.json、Area_Boundary.json
│   └── GeoTIFF/   Elevation.tif、Depth.tif
└── render_city.py
```

渲染全部地图:

```bash
python render_city.py
```

会在仓库根目录生成 `map_city_vN.png`(底图,600 DPI)以及全部专题图与地形图。

`render_map.py` 是更早的简版渲染器(一张简单街道图、一张可选分区图、一张地形图),作为最小参考示例保留:

```bash
python render_map.py            # 街道图 + 地形图
python render_map.py --zoning   # 另外画分区图(要读大文件,较慢)
```

---

## 使用你自己的城市

1. 在《都市天际线 2》里用 **Carto** mod(Paradox Mods 上可获取)导出存档。Carto 会写出 **GeoJSON**、**GeoTIFF** 和 Shapefile 图层。
2. 把本项目用到的图层拷进仓库:
   - `Carto/GeoJSON/` — `Zoning_Boundary.json`、`Building_Boundary.json`、`Network_Centerline.json`、`Route_Centerline.json`、`POI_Location.json`(以及可选的 `Area_Boundary.json`)
   - `Carto/GeoTIFF/` — `Elevation.tif`、`Depth.tif`
3. `python render_city.py`

> Carto 的 GeoJSON 是 EPSG:4326、UTF-8 带 BOM;GeoTIFF 是 UTM 投影。脚本都已处理(按 BOM 读取,并把水深栅格实时重投影到高程栅格的网格上)。

---

## 实现原理

`render_city.py` 是一份注释详尽的单文件脚本(约 750 行),关键部分:

- **`compute_road_layers()`** — 按 good-continuation 连成连续路段,判定哪些交叉是真正的立交(空间网格上的线段内部相交),转成差分约束(`高层 ≥ 低层 + 1`),用 Bellman–Ford 最长路松弛求整数层。高等级道路用 `butt` 平头端点避免层间过渡留下接缝;再用一次填充汇入(fill-merge)把支线结尾段重画在主路之上,使匝道连续。
- 建筑循环里的**标志性建筑 / 地标分类**,以及线路图的**逐线路分组**。
- **地形** — 在高程栅格上用 `LightSource` 晕渲,并把水深栅格重投影到同一网格。

设计笔记(中文)见 [`docs/`](docs/):画图指南、立交分层问题报告,以及一份关于道路分层的专家参考报告。

---

## 仓库结构

```
.
├── render_city.py     # 主渲染器 → 13 张图
├── render_map.py      # 早期简版渲染器(参考)
├── requirements.txt
├── gallery/           # 上面展示的网页预览图
├── docs/              # 设计笔记与报告(中文)
├── README.md          # 英文
├── README.zh-CN.md    # 本文件(中文)
└── LICENSE
```

源数据(`Carto/`)和全分辨率原图**不纳入仓库**——数据从 Releases 获取,原图请运行脚本自行生成。

---

## 许可

- **代码** — [MIT](LICENSE)。
- **渲染图(`gallery/`)与示例城市数据** — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。

## 致谢

- 《都市天际线 2》的 **Carto** mod,它导出了底层的 GeoJSON / GeoTIFF 数据。
- Cities: Skylines II © Colossal Order / Paradox Interactive。本项目为非官方同人项目。
- 本渲染器借助 **Claude Code**(Anthropic)迭代开发完成。
