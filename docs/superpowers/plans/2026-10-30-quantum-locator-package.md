# quantum-locator 独立包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `quantum_locator` 变成可独立发布的 Python 包 + HTTP 服务 + Docker 镜像，返回结构化的 `(省, 市/区, adcode, level)`，并修掉三处会直接影响主产品的缺陷（GCJ02 默认、区级归属、边界简化）。

**Architecture:** 纯 Python 库（shapely + rtree，不依赖 geopandas 在运行时做 CRS 变换），FastAPI 只是薄壳。数据 `china_cities.geojson` 随包发布，成为唯一数据源。

**Tech Stack:** Python 3.12、shapely 2.x、rtree、fastapi、uvicorn、pytest、ruff、mypy、hatchling。

**Spec:** `/home/lyon/coding/tools/video/docs/superpowers/specs/2026-10-30-quantum-organizer-design.md`（第 8 节）

## Global Constraints

- Python 3.12 基线；CI 覆盖 3.12 / 3.13。
- 包名 `quantum-locator`，导入名 `quantum_locator`；镜像 `ghcr.io/<org>/quantum-locator`。
- 数据文件随包发布：`china_cities.geojson`（477 个 feature：363 city + 112 district + 1 province）。
- `need_gcj02_convert` 默认 **True**：输入按 WGS84（相机/无人机 EXIF）对待。
- 多边形简化容差 `0.001`（约 110 m），不得使用 0.01。
- 命中 district 级时第二级返回**该区名**（`北京/东城区`、`香港/中西区`）；命中 province 级时返回 `reason="needs_city_level_data"`，**不猜市名**。
- 中国范围判定用 bbox `73 ≤ lon ≤ 136` 且 `3 ≤ lat ≤ 54`；范围外返回 `reason="abroad"`。
- 旧端点 `GET /api/v1/location` 的 `formatted_name` 字段保持 `省-市` 格式，新增字段只增不改。

## Review Focus

- **点落在两个多边形交界处**：`sindex.intersection` 可能返回多个候选，必须按 `city > district > province` 定序取第一个，否则同一坐标两次调用结果可能不同（T1）。
- **GCJ02 转换前后的误判**：转换只在境内生效，境外点先判 abroad 再转换，否则东京会被转到一个中国边境坐标上（T1）。
- **边界点**：距离多边形边界 < 0.002° 时要打 `boundary=True`，而不是靠猜（T1）。
- **简化后的空洞**：`simplify` 可能让极端坐标落进"被简化掉的角落"，必须返回 `outside_polygons` 而不是抛异常（T1）。
- **数据文件缺失**：包安装后 `importlib.resources` 找不到 geojson 时要在 `__init__` 抛带路径的 `FileNotFoundError`，而不是静默返回空结果（T2）。

---

### Task 1: 包骨架 + 数据文件 + 定位核心

**Files:**
- Create: `quantum-locator/pyproject.toml`
- Create: `quantum-locator/src/quantum_locator/__init__.py`
- Create: `quantum-locator/src/quantum_locator/locator.py`
- Create: `quantum-locator/src/quantum_locator/data/china_cities.geojson`（从 `city_locator/china_cities.geojson` 复制）
- Test: `quantum-locator/tests/test_locator.py`

**Interfaces:**
- Produces:
  - `quantum_locator.Location`：冻结 dataclass，字段 `province: str|None, city: str|None, adcode: str|None, level: str|None, boundary: bool, reason: str|None`
  - `quantum_locator.CityLocator(geojson_path: Path|None = None, simplify_tolerance: float = 0.001)`
  - `CityLocator.query(lon: float, lat: float, need_gcj02_convert: bool = True) -> Location`
  - `CityLocator.query_batch(coords: Sequence[tuple[float, float]], need_gcj02_convert: bool = True) -> list[Location]`
  - `quantum_locator.__version__`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_locator.py
import pytest
from quantum_locator import CityLocator, Location

@pytest.fixture(scope="module")
def loc():
    return CityLocator()

@pytest.mark.parametrize("lon,lat,prov,city,adcode,level", [
    (118.7969, 32.0603, "江苏", "南京", "320100", "city"),      # 南京
    (114.0579, 22.5431, "广东", "深圳", "440300", "city"),      # 深圳
    (91.1409, 29.6456, "西藏", "拉萨", "540100", "city"),       # 拉萨
    (116.3975, 39.9087, "北京", "东城区", "110101", "district"),  # 天安门
    (121.4737, 31.2304, "上海", "黄浦区", "310101", "district"),  # 人民广场
    (114.1588, 22.2819, "香港", "中西区", "810001", "district"),  # 中环
    (113.5439, 22.1987, "澳门", "花王堂区", "820002", "district"),
])
def test_resolves_known_points(loc, lon, lat, prov, city, adcode, level):
    r = loc.query(lon, lat)
    assert (r.province, r.city, r.adcode, r.level) == (prov, city, adcode, level)
    assert r.reason is None

def test_taiwan_never_guesses_city(loc):
    r = loc.query(121.5654, 25.0330)
    assert r.province == "台湾"
    assert r.city is None
    assert r.reason == "needs_city_level_data"

def test_abroad_is_not_converted(loc):
    r = loc.query(139.6917, 35.6895)          # 东京
    assert r.reason == "abroad" and r.province is None

def test_wgs84_input_is_converted_by_default(loc):
    # 天安门 WGS84 与 GCJ02 差约 500 m；不转换会落到别的区
    assert loc.query(116.3975, 39.9087).city == "东城区"
    assert loc.query(116.3975, 39.9087, need_gcj02_convert=False).city != "东城区"

def test_boundary_flag(loc):
    poly = loc._polygon_for("320100")          # 南京市的 shapely 多边形
    inside = poly.representative_point()
    near = poly.exterior.interpolate(0.5, normalized=True)
    assert loc.query(*inside.coords[0], need_gcj02_convert=False).boundary is False
    assert loc.query(near.x + 0.0003, near.y, need_gcj02_convert=False).boundary is True

def test_missing_geojson_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        CityLocator(geojson_path=tmp_path / "nope.geojson")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd quantum-locator && python -m pytest tests/test_locator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantum_locator'`

- [ ] **Step 3: 建包骨架与实现**

`pyproject.toml`：`[project] name="quantum-locator"`、`requires-python=">=3.12"`、`dependencies=["shapely>=2.0","rtree>=1.2"]`、`[project.scripts] quantum-locator-serve="quantum_locator.server:main"`、hatchling 构建，`[tool.hatch.build.targets.wheel] packages=["src/quantum_locator"]`，并把 `src/quantum_locator/data/*.geojson` 打进 wheel。

`locator.py` 实现要点（签名与测试已定，body 由实现者写）：
- 用 `shapely.geometry.shape` 读 feature，`simplify(tolerance, preserve_topology=True)`；按 `level` 建三组几何 + `rtree.index.Index`。
- `_wgs84_to_gcj02` 从现有 `quantum_locator/quantum_locator_server.py` 原样移植（含 `out_of_china` 判断）。
- 省名清洗：去掉 `省|自治区|特别行政区`，并把 `内蒙古自治区→内蒙古`、`广西壮族自治区→广西`、`西藏自治区→西藏`、`宁夏回族自治区→宁夏`、`新疆维吾尔自治区→新疆`、`香港特别行政区→香港`、`澳门特别行政区→澳门`。
- 市名清洗：去掉 `市|地区|盟|自治州…` 后缀，**保留 `区`**。
- 多候选取序 `city > district > province`；`boundary = (poly.exterior.distance(point) < 0.002)`。
- 无命中且境内 → `Location(None, None, None, None, False, "outside_polygons")`。
- `_polygon_for(adcode)` 供测试取原始（未简化前）多边形也可，测试里用的是简化后的几何——实现时保留一个 `self._polys: dict[str, BaseGeometry]`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd quantum-locator && python -m pytest tests/test_locator.py -v`
Expected: 全部 PASS（12 个用例）

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml src/quantum_locator tests/test_locator.py
git commit -m "feat: quantum_locator package with structured province/city resolution"
```

---

### Task 2: HTTP 服务（兼容旧端点）

**Files:**
- Create: `quantum-locator/src/quantum_locator/server.py`
- Test: `quantum-locator/tests/test_server.py`

**Interfaces:**
- Consumes: `CityLocator.query/query_batch`（Task 1）
- Produces:
  - `app: FastAPI`（`quantum_locator.server:app`）
  - `GET /api/v1/location?lon=&lat=&need_gcj02_convert=true` → `{"formatted_name","raw_name","adcode","province","city","level","reason"}`
  - `POST /api/v1/location/batch` → `{"total","results":[...]}`
  - `GET /healthz` → `{"status":"healthy","locator_ready":true}`
  - `main()` 启动 uvicorn（host 0.0.0.0，port 8899）

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_server.py
from fastapi.testclient import TestClient
from quantum_locator.server import app

def test_legacy_single_point_shape():
    c = TestClient(app)
    r = c.get("/api/v1/location", params={"lon": 118.7969, "lat": 32.0603})
    assert r.status_code == 200
    body = r.json()
    assert body["formatted_name"] == "江苏-南京"
    assert body["province"] == "江苏" and body["city"] == "南京"
    assert body["level"] == "city"

def test_batch_endpoint():
    c = TestClient(app)
    r = c.post("/api/v1/location/batch", json={"coordinates": [
        {"lon": 118.7969, "lat": 32.0603},
        {"lon": 116.3975, "lat": 39.9087},
    ]})
    assert r.json()["total"] == 2
    assert [x["city"] for x in r.json()["results"]] == ["南京", "东城区"]

def test_healthz():
    assert TestClient(app).get("/healthz").json()["locator_ready"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd quantum-locator && python -m pytest tests/test_server.py -v`
Expected: FAIL — `ImportError: cannot import name 'app'`

- [ ] **Step 3: 实现服务**

从 `quantum_locator/quantum_locator_server.py` 移植 FastAPI 结构；`lifespan` 里构造 `CityLocator()`；`formatted_name` 规则：`f"{province}-{city}"`，city 为 None 时只返回 province，abroad 时返回 `"未知区域/公海"`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd quantum-locator && python -m pytest tests/ -v`
Expected: 15 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_locator/server.py tests/test_server.py
git commit -m "feat: legacy-compatible HTTP service with structured fields"
```

---

### Task 3: Docker 镜像 + CI

**Files:**
- Create: `quantum-locator/Dockerfile`
- Create: `quantum-locator/.dockerignore`
- Create: `quantum-locator/.github/workflows/ci.yml`

**Interfaces:**
- Produces: 镜像 `ghcr.io/<org>/quantum-locator`，暴露 8899，`HEALTHCHECK` 打 `/healthz`

- [ ] **Step 1: 写 Dockerfile**

`FROM python:3.12-slim` → 装 `libspatialindex-dev`（rtree 运行时需要 `libspatialindex`，用 `--no-install-recommends`）→ `pip install .` → `EXPOSE 8899` → `HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8899/healthz')"` → `CMD ["uvicorn","quantum_locator.server:app","--host","0.0.0.0","--port","8899","--workers","1"]`。

- [ ] **Step 2: 构建并冒烟**

Run: `docker build -t quantum-locator:dev . && docker run --rm -d -p 18899:8899 --name cl-smoke quantum-locator:dev && sleep 8 && curl -s http://localhost:18899/api/v1/location?lon=118.7969\&lat=32.0603 && docker rm -f cl-smoke`
Expected: `{"formatted_name":"江苏-南京",...}`

- [ ] **Step 3: CI 工作流**

`.github/workflows/ci.yml`：`ruff check`、`mypy src/`、pytest 矩阵 `3.12`/`3.13`、`docker build`。

- [ ] **Step 4: 提交**

```bash
git add Dockerfile .dockerignore .github/workflows/ci.yml
git commit -m "build: docker image and CI"
```

---

### Task 4: 发布工作流（PyPI + 数据工件）

**Files:**
- Create: `quantum-locator/.github/workflows/release.yml`
- Modify: `quantum-locator/README.md`（写明 `pip install quantum-locator` 与数据工件 sha256）

**Interfaces:**
- Produces: `quantum-locator 0.1.0` 上 PyPI；release 附件含 `china_cities.geojson` 与 `china_cities.geojson.sha256`

- [ ] **Step 1: 写发布工作流**

tag `v*` 触发：`python -m build` + `pypa/gh-action-pypi-publish`（trusted publisher）；随后 `sha256sum src/quantum_locator/data/china_cities.geojson > china_cities.geojson.sha256` 并 `gh release upload` 两个文件。

- [ ] **Step 2: 验证工件校验和**

Run: `sha256sum src/quantum_locator/data/china_cities.geojson && cat china_cities.geojson.sha256`
Expected: 两行 sha256 一致

- [ ] **Step 3: 提交并记录版本**

```bash
git add .github/workflows/release.yml README.md CHANGELOG.md
git commit -m "ci: publish to PyPI with data artifact"
```

---

## Self-Review

- Spec 覆盖：8.1（包/服务/镜像/数据工件）→ T1/T3/T4；8.2（被主产品内嵌）→ 依赖声明在 T1 的 `pyproject.toml`；8.3（GCJ02、区级归属、台湾、简化容差、结构化返回）→ T1 全部有测试；8.4（数据更新只在本仓）→ T4。
- Review Focus 五条都落在 T1 的测试里（多候选取序、境外不转换、边界标记、outside_polygons、缺数据文件）。
- 类型一致性：`Location` 字段名在三处（locator/server/主产品）统一为 `province/city/adcode/level/boundary/reason`。
