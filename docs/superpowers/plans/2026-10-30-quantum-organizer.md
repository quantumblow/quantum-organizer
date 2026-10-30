# quantum-organizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个开箱即用的素材整理工具：挂载一个乱文件夹，一条流水线完成「提元数据 → 查省市 → 重命名 → 按省/市归档 → 可整体撤销」，并有 CLI 与 WebUI 两个薄壳。

**Architecture:** 纯 Python 核心库（`quantum_organizer.core`）不依赖任何 Web 框架；`cli.py` 与 `web/` 只是薄壳；行政解析通过 pip 依赖 `quantum-locator` 在**同进程**内完成（不默认起容器）。扫描结果与历史都落 SQLite 到 `QORG_STATE_DIR`，素材目录里不写任何东西。

**Tech Stack:** Python 3.12、typer、FastAPI + uvicorn、Vue 3 + Vite、SQLite（stdlib）、ffprobe/ffmpeg/exiftool（外部命令）、pytest、ruff、mypy、hatchling、Docker 多阶段构建。

**Spec:** `/home/lyon/coding/tools/video/docs/superpowers/specs/2026-10-30-quantum-organizer-design.md`

## Global Constraints

- Python 3.12 基线；CI 覆盖 3.12 / 3.13。
- 包 `quantum-organizer`，导入名 `quantum_organizer`，CLI `qorg`，镜像 `ghcr.io/<org>/quantum-organizer`。
- 单容器、单端口 **8080**；`/data` 放素材，`/state` 放状态；`QORG_STATE_DIR` 默认 `~/.local/state/quantum-organizer`。
- **绝不**往用户素材目录写数据库、日志或缓存。
- 行政解析：内嵌 `quantum-locator`（WGS84→GCJ02 转换默认开启），`QORG_GEOCODER_URL` 存在时改走远程。
- 目标文件名格式 `<stem>_<省>_<第二级>_<YYMMDD><ext>`；直辖市/港澳第二级是**所在区**（`北京_东城区`）；**幂等**，绝不叠加后缀。
- 台湾（只有省级多边形）→ 未定位，`reason="needs_city_level_data"`；境外 → `reason="abroad"`。
- 城市中心点最近邻估算默认**关闭**，只有 `--allow-estimate` 开启；且只对 `outside_polygons` 生效。
- 单次操作上限 **100000** 个文件。
- 默认只扫描不修改；`apply` 必须显式 `--yes`；一次 apply = 一条操作记录，可整体撤销。
- 拒绝符号链接；所有目标路径 `resolve()` 后必须在 root 内。
- MIT 许可；README 与 UI 中英双语。

## Review Focus

- **已带 `_省_市_YYMMDD` 后缀的文件重复扫描**：必须原地不动或替换后缀，不能变成 `_江苏_南京_240815_江苏_南京_240815`（Task 4）。
- **同目录同名不同来源文件**（两个相机同一天同序号）：目标必须 `_2` 冲突消解，撤销后两个文件都回到原位（Task 8 / Task 11）。
- **无 GPS / 境外 / 台湾 素材混在同一目录**：必须原样不动、不产生 steps，并在报告里给出原因（Task 8 / Task 11）。
- **损坏或 0 字节文件**：不得中断整批，标 `invalid/unreadable` 继续，apply 时跳过（Task 5 / Task 12）。
- **超长中文名与 Windows 保留字符**：文件名必须 ≤200 字节且可跨平台，扩展名不能被截断（Task 4）。

---

### Task 1: 仓库骨架 + `qorg doctor`

**Files:**
- Create: `quantum-organizer/pyproject.toml`
- Create: `quantum-organizer/src/quantum_organizer/__init__.py`
- Create: `quantum-organizer/src/quantum_organizer/cli.py`
- Create: `quantum-organizer/.github/workflows/ci.yml`, `.gitignore`, `Makefile`
- Test: `quantum-organizer/tests/test_doctor.py`

**Interfaces:**
- Produces: `doctor_report() -> dict[str, str]`（键：`ffmpeg`、`ffprobe`、`exiftool`、`quantum_locator`、`state_dir`、`hint`）；`qorg` CLI 入口（`quantum_organizer.cli:app`）。

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_doctor.py
from quantum_organizer.cli import doctor_report

def test_reports_missing_tools(monkeypatch):
    monkeypatch.setattr("quantum_organizer.cli.shutil.which",
                        lambda n: {"ffmpeg": "/usr/bin/ffmpeg"}.get(n))
    r = doctor_report()
    assert r["ffmpeg"] == "/usr/bin/ffmpeg"
    assert r["exiftool"] == "missing"
    assert "libimage-exiftool-perl" in r["hint"]

def test_reports_all_present(monkeypatch):
    monkeypatch.setattr("quantum_organizer.cli.shutil.which", lambda n: f"/usr/bin/{n}")
    r = doctor_report()
    assert "missing" not in r["ffmpeg"] + r["exiftool"]
    assert r["quantum_locator"] != "missing"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quantum-organizer && python -m pytest tests/test_doctor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantum_organizer'`

- [ ] **Step 3: 建骨架并实现**

`pyproject.toml`：`name="quantum-organizer"`、`requires-python=">=3.12"`、`dependencies=["quantum-locator>=0.1,<1","typer>=0.12","fastapi>=0.110","uvicorn[standard]>=0.29"]`、`[project.optional-dependencies] dev=["pytest","ruff","mypy","httpx"]`、`[project.scripts] qorg="quantum_organizer.cli:app"`。
`cli.py` 先只有 `doctor` 子命令；`doctor_report` 用 `shutil.which` 查三个外部命令、`importlib.util.find_spec("quantum_locator")` 查依赖、打印 `QORG_STATE_DIR` 解析结果与按平台的安装提示（Linux `apt install ffmpeg libimage-exiftool-perl`，macOS `brew install ffmpeg exiftool`）。

- [ ] **Step 4: 运行确认通过**

Run: `cd quantum-organizer && python -m pytest tests/test_doctor.py -v && qorg doctor`
Expected: 2 passed；`qorg doctor` 打印六行状态

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml src/quantum_organizer tests/test_doctor.py .github .gitignore Makefile
git commit -m "feat: project skeleton and qorg doctor"
```

---

### Task 2: 数据模型

**Files:**
- Create: `quantum-organizer/src/quantum_organizer/models.py`
- Test: `quantum-organizer/tests/test_models.py`

**Interfaces:**
- Produces:
  - `Status(str, Enum)`：`READY/SKIPPED/INVALID/CONFLICT/DONE/FAILED`
  - `MediaItem(path:str, size:int, mtime:float, kind:str, shoot_time:str|None, time_source:str|None, lat:float|None, lon:float|None, gps_source:str|None, province:str|None, city:str|None, geo_source:str|None, geo_boundary:bool=False, status:Status=READY, reason:str|None=None)`，含 `to_dict()` / `from_dict()`
  - `PlanItem(item:MediaItem, target_name:str|None, target_path:str|None, decision:str, conflict:str|None)`；`decision ∈ {"rename","move","keep","skip"}`
  - `Plan(plan_id:str, root:str, created_at:str, options_fingerprint:str, items:list[PlanItem], counts:dict[str,int])`，含 `to_json()/from_json()`
  - `StepRecord(seq:int, action:str, src:str, dst:str, status:str, error:str|None)`
  - `OpRecord(op_id:int, started_at:str, finished_at:str|None, kind:str, root:str, options_json:str, status:str, steps:list[StepRecord])`
  - `UndoResult(op_id:int, ok:bool, reverted:int, conflicts:list[str])`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_models.py
from quantum_organizer.models import MediaItem, PlanItem, Plan, Status

def test_media_item_roundtrip():
    item = MediaItem(path="/a.jpg", size=10, mtime=1.5, kind="image", shoot_time="240815",
                     time_source="exif", lat=32.0603, lon=118.7969, gps_source="exiftool",
                     province="江苏", city="南京", geo_source="exact")
    assert MediaItem.from_dict(item.to_dict()) == item

def test_status_serialises_as_string():
    item = MediaItem(path="/a.jpg", size=0, mtime=0.0, kind="image", shoot_time=None,
                     time_source=None, lat=None, lon=None, gps_source=None,
                     province=None, city=None, geo_source=None, status=Status.INVALID)
    assert item.to_dict()["status"] == "invalid"

def test_plan_json_roundtrip():
    item = MediaItem(path="/a.jpg", size=1, mtime=1.0, kind="image", shoot_time="240815",
                     time_source="exif", lat=32.0, lon=118.0, gps_source="exiftool",
                     province="江苏", city="南京", geo_source="exact")
    plan = Plan(plan_id="p1", root="/r", created_at="2026-10-30T00:00:00",
                options_fingerprint="abc123",
                items=[PlanItem(item=item, target_name="a_江苏_南京_240815.jpg",
                                target_path="/r/江苏/南京/a_江苏_南京_240815.jpg",
                                decision="rename", conflict=None)],
                counts={"rename": 1})
    assert Plan.from_json(plan.to_json()) == plan
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 实现**

全部用 `@dataclass`；`to_dict` 里 `status` 输出 `.value`；`Plan.to_json` 用 `json.dumps(..., ensure_ascii=False)`；`from_json` 逐层还原。`counts` 由 `plan.counts` 或调用方计算。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_models.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/models.py tests/test_models.py
git commit -m "feat: core data models"
```

---

### Task 3: 地名清洗与日期解析

**Files:**
- Create: `quantum-organizer/src/quantum_organizer/naming.py`
- Test: `quantum-organizer/tests/test_naming_clean.py`
- Create: `quantum-organizer/tests/fixtures/naming_cases.json`

**Interfaces:**
- Produces:
  - `clean_province(name: str) -> str`
  - `clean_city(name: str) -> str`
  - `format_date(raw: str | None) -> str | None`（输出 `YYMMDD`）

- [ ] **Step 1: 写失败的测试**（这些期望值是在真实 geojson 的 476 个行政区名上跑过的）

```python
# tests/test_naming_clean.py
import json, pathlib
import pytest
from quantum_organizer.naming import clean_province, clean_city, format_date

@pytest.mark.parametrize("raw,expected", [
    ("江苏省", "江苏"), ("新疆维吾尔自治区", "新疆"), ("内蒙古自治区", "内蒙古"),
    ("广西壮族自治区", "广西"), ("香港特别行政区", "香港"), ("北京市", "北京"),
])
def test_clean_province(raw, expected):
    assert clean_province(raw) == expected

@pytest.mark.parametrize("raw,expected", [
    ("南京市", "南京"), ("东城区", "东城区"), ("黄大仙区", "黄大仙区"),
    ("湘西土家族苗族自治州", "湘西"), ("海西蒙古族藏族自治州", "海西"),
    ("博尔塔拉蒙古自治州", "博尔塔拉"), ("克孜勒苏柯尔克孜自治州", "克孜勒苏"),
    ("酉阳土家族苗族自治县", "酉阳"), ("大兴安岭地区", "大兴安岭"), ("阿拉善盟", "阿拉善"),
])
def test_clean_city(raw, expected):
    assert clean_city(raw) == expected

def test_naming_cases_fixture():
    cases = json.loads(pathlib.Path("tests/fixtures/naming_cases.json").read_text("utf-8"))
    for case in cases["cities"]:
        assert clean_city(case["raw"]) == case["clean"]
        assert "族" not in clean_city(case["raw"])
        assert len(clean_city(case["raw"])) <= 8

def test_format_date():
    assert format_date("2014:08:15 10:00:00") == "140815"
    assert format_date("2014-08-15T10:00:00Z") == "140815"
    assert format_date("140815") == "140815"
    assert format_date(None) is None
    assert format_date("not a date") is None

def test_format_date_rejects_impossible_dates():
    assert format_date("2014:13:45 10:00:00") is None
```

`tests/fixtures/naming_cases.json` 内容（黄金用例，二期 Dart 实现必须跑同一份）：

```json
{"cities": [
  {"raw": "湘西土家族苗族自治州", "clean": "湘西"},
  {"raw": "海西蒙古族藏族自治州", "clean": "海西"},
  {"raw": "博尔塔拉蒙古自治州", "clean": "博尔塔拉"},
  {"raw": "克孜勒苏柯尔克孜自治州", "clean": "克孜勒苏"},
  {"raw": "酉阳土家族苗族自治县", "clean": "酉阳"},
  {"raw": "东城区", "clean": "东城区"},
  {"raw": "大兴安岭地区", "clean": "大兴安岭"},
  {"raw": "阿拉善盟", "clean": "阿拉善"}
]}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_naming_clean.py -v`
Expected: FAIL — `ImportError: clean_province`

- [ ] **Step 3: 实现**

- 省：先按显式映射 `内蒙古自治区→内蒙古、广西壮族自治区→广西、西藏自治区→西藏、宁夏回族自治区→宁夏、新疆维吾尔自治区→新疆、香港特别行政区→香港、澳门特别行政区→澳门`，其余去掉 `省|市` 后缀。
- 市：去掉级别后缀 `自治州|自治县|自治旗|特别行政区|自治区|地区|省|市|盟|县|林区`，然后**反复**剥掉结尾的 `<民族 stem>族`（stem 表见下）；若原名以 `自治州` 结尾，再剥掉一次结尾的裸 stem（`蒙古|柯尔克孜|维吾尔|哈萨克|达斡尔`，处理"博尔塔拉蒙古"这类省称）。
- stem 表（去重、按长度降序）：`土家 蒙古 朝鲜 维吾尔 哈萨克 柯尔克孜 塔吉克 乌孜别克 俄罗斯 鄂温克 鄂伦春 达斡尔 锡伯 满 回 藏 彝 苗 侗 布依 傣 白 哈尼 壮 羌 傈僳 拉祜 佤 纳西 景颇 黎 瑶 畲 东乡 仫佬 布朗 撒拉 毛南 仡佬 阿昌 普米 德昂 保安 裕固 塔塔尔 独龙 赫哲 门巴 珞巴 基诺`。
- `format_date`：接受 `YYYY:MM:DD…`、`YYYY-MM-DD…`、已 6 位；**校验**月 1–12、日 1–31，否则 `None`；返回 `YYMMDD`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_naming_clean.py -v`
Expected: 19 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/naming.py tests/test_naming_clean.py tests/fixtures/naming_cases.json
git commit -m "feat: province/city name cleaning and date parsing"
```

---

### Task 4: 文件名构建（幂等）与 sanitize

**Files:**
- Modify: `quantum-organizer/src/quantum_organizer/naming.py`
- Test: `quantum-organizer/tests/test_naming_build.py`

**Interfaces:**
- Produces:
  - `parse_existing(stem: str) -> tuple[str, str | None]`（返回 `(base_stem, 旧后缀或 None)`）
  - `build_name(stem: str, province: str, city: str, date: str, ext: str) -> str`
  - `sanitize(name: str, max_bytes: int = 200) -> str`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_naming_build.py
import pytest
from quantum_organizer.naming import parse_existing, build_name, sanitize

def test_parse_existing_strips_known_suffix():
    assert parse_existing("IMG_1234_江苏_南京_240815") == ("IMG_1234", "江苏_南京_240815")

def test_parse_existing_ignores_non_place_suffix():
    assert parse_existing("IMG_20140621_161135") == ("IMG_20140621_161135", None)
    assert parse_existing("DSC_0047_140620_140620") == ("DSC_0047_140620_140620", None)

def test_build_name_keeps_existing_suffix():
    assert build_name("IMG_1234_江苏_南京_240815", "江苏", "南京", "240815", ".jpg") \
        == "IMG_1234_江苏_南京_240815.jpg"

def test_build_name_replaces_changed_suffix():
    assert build_name("DSC_0001_北京_东城区_240101", "北京", "东城区", "240102", ".JPG") \
        == "DSC_0001_北京_东城区_240102.JPG"

def test_build_name_keeps_camera_underscores():
    assert build_name("IMG_20140531_074823_HDR", "江苏", "南京", "140531", ".jpg") \
        == "IMG_20140531_074823_HDR_江苏_南京_140531.jpg"

def test_sanitize_replaces_illegal_characters():
    assert sanitize('a<b>c:d"e/f\\g|h?i*j.jpg') == "a-b-c-d-e-f-g-h-i-j.jpg"

def test_sanitize_truncates_bytes_keeping_extension():
    out = sanitize("测" * 120 + ".jpg")
    assert len(out.encode()) <= 200
    assert out.endswith(".jpg")

def test_build_name_rejects_empty_place():
    with pytest.raises(ValueError):
        build_name("a", "", "南京", "240815", ".jpg")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_naming_build.py -v`
Expected: FAIL — `ImportError: parse_existing`

- [ ] **Step 3: 实现**

`_EXISTING_RE = re.compile(r"^(?P<base>.+)_(?P<prov>[^_\d]+)_(?P<city>[^_\d]+)_(?P<date>\d{6})$")`（prov/city 不允许纯数字，避免把 `DSC_0047_140620_140620` 误判为地名）。
`build_name`：先 `parse_existing(stem)` 取 base，再用 `f"{base}_{province}_{city}_{date}{ext}"`；`province`/`city` 为空 → `ValueError`。
`sanitize`：非法字符 `<>:"/\\|?*` 与控制字符 → `-`；去尾部空格与点；`utf-8` 字节数超限时按字符回退截断 stem、保留扩展名。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_naming_build.py tests/test_naming_clean.py -v`
Expected: 27 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/naming.py tests/test_naming_build.py
git commit -m "feat: idempotent filename building and sanitisation"
```

---

### Task 5: 元数据提取（图片 / 普通视频）

**Files:**
- Create: `quantum-organizer/src/quantum_organizer/metadata.py`
- Create: `quantum-organizer/tests/conftest.py`
- Create fixtures: `quantum-organizer/tests/fixtures/media/{photo_gps.jpg,photo_nogps.jpg,plain.mp4,broken.jpg}`
- Test: `quantum-organizer/tests/test_metadata.py`

**Interfaces:**
- Produces: `MediaExtractor(ffprobe=None, ffmpeg=None, exiftool=None)`；`MediaExtractor.extract(path: Path) -> MediaItem`（`province/city/geo_source` 留空，由 geocode 阶段填）

- [ ] **Step 1: 生成确定性 fixtures 并写失败的测试**

```bash
# <100 KB，可进仓库
ffmpeg -y -v error -i media-renamer/data/test_origin/IMG_20140506_105902.jpg \
  -vf scale=32:-2 -q:v 8 tests/fixtures/media/base.jpg
cp tests/fixtures/media/base.jpg tests/fixtures/media/photo_nogps.jpg
exiftool -overwrite_original -GPSLatitude=32.0603 -GPSLongitude=118.7969 \
  -GPSLatitudeRef=N -GPSLongitudeRef=E -DateTimeOriginal="2014:08:15 10:00:00" \
  tests/fixtures/media/base.jpg && mv tests/fixtures/media/base.jpg tests/fixtures/media/photo_gps.jpg
ffmpeg -y -v error -f lavfi -i color=c=black:s=64x64:d=1 -map_metadata -1 \
  -fflags +bitexact -flags:v +bitexact tests/fixtures/media/plain.mp4
printf 'not a jpeg' > tests/fixtures/media/broken.jpg
```

```python
# tests/test_metadata.py
from pathlib import Path
import pytest
from quantum_organizer.metadata import MediaExtractor
from quantum_organizer.models import Status

FX = Path("tests/fixtures/media")
ex = MediaExtractor()

def test_photo_with_gps():
    m = ex.extract(FX / "photo_gps.jpg")
    assert (m.shoot_time, m.time_source) == ("140815", "exif")
    assert (m.lat, m.lon, m.gps_source) == (32.0603, 118.7969, "exiftool")
    assert (m.province, m.city) is (None, None)

def test_photo_without_gps_keeps_time():
    m = ex.extract(FX / "photo_nogps.jpg")
    assert (m.shoot_time, m.time_source) == ("140506", "exif")
    assert m.lat is None and m.reason == "no_gps"

def test_video_without_metadata_falls_back_to_mtime():
    m = ex.extract(FX / "plain.mp4")
    assert m.kind == "video" and m.lat is None
    assert m.time_source == "mtime" and m.shoot_time is not None

def test_corrupt_file_is_invalid_not_raised():
    m = ex.extract(FX / "broken.jpg")
    assert m.status is Status.INVALID and m.reason == "unreadable"

def test_size_and_mtime_recorded():
    m = ex.extract(FX / "photo_gps.jpg")
    assert m.size == (FX / "photo_gps.jpg").stat().st_size
    assert m.mtime == pytest.approx((FX / "photo_gps.jpg").stat().st_mtime)
```

`tests/conftest.py` 提供 `tmp_media(tmp_path)`：把 fixtures 拷进临时目录，供后续任务使用。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: FAIL — `ImportError: MediaExtractor`

- [ ] **Step 3: 实现**

`extract` 流程（移植 `media-renamer/core/renamer.py` 的 `_ffprobe_extract` / `_exiftool_extract` / `_format_time`，改成纯函数结构）：
1. 读 `stat()` → `size/mtime`；按扩展名定 `kind`（`image`/`video`/`audio`）。
2. `ffprobe -v quiet -print_format json -show_format -show_streams`：`creation_time` 等时间键 → `time_source="video"`；`location` tag → `gps_source="ffprobe"`。
3. `exiftool -j -n`：`DateTimeOriginal` → `time_source="exif"`；`GPSLatitude/GPSLongitude` → `gps_source="exiftool"`。
4. 文件名里的 6 位日期 → `time_source="filename"`；都没有 → `mtime` → `time_source="mtime"`。
5. 时间统一过 `naming.format_date`；无 GPS → `reason="no_gps"`（status 仍 `READY`，因为"没 GPS"不是错误）。
6. 任一外部命令抛错/返回非 0 不致命；文件不可读（`OSError` 或两种工具都失败且文件为空）→ `status=INVALID, reason="unreadable"`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/metadata.py tests/test_metadata.py tests/conftest.py tests/fixtures/media
git commit -m "feat: media metadata extraction with graceful degradation"
```

---

### Task 6: DJI 字幕轨 GPS

**Files:**
- Modify: `quantum-organizer/src/quantum_organizer/metadata.py`
- Create fixture: `quantum-organizer/tests/fixtures/media/dji_gps.mp4`
- Test: `quantum-organizer/tests/test_metadata_dji.py`

**Interfaces:**
- Consumes: `MediaExtractor.extract`（Task 5）
- Produces: 无新 API；`gps_source="subtitle"` 分支

- [ ] **Step 1: 生成 fixture 并写失败的测试**

```bash
printf '1\n00:00:00,000 --> 00:00:01,000\nGPS (118.7969, 32.0603, 100)\n' > /tmp/gps.srt
ffmpeg -y -v error -f lavfi -i color=c=black:s=64x64:d=1 -i /tmp/gps.srt \
  -map 0:v -map 1:s -c:v libx264 -preset ultrafast -c:s mov_text -t 1 \
  tests/fixtures/media/dji_gps.mp4
```

```python
# tests/test_metadata_dji.py
from pathlib import Path
from quantum_organizer.metadata import MediaExtractor

def test_dji_subtitle_gps():
    m = MediaExtractor().extract(Path("tests/fixtures/media/dji_gps.mp4"))
    assert m.gps_source == "subtitle"
    assert (round(m.lat, 4), round(m.lon, 4)) == (32.0603, 118.7969)

def test_zero_coordinates_are_discarded(tmp_path):
    # GPS (0, 0, 0) 的素材视为无 GPS
    from subprocess import run
    srt = tmp_path / "zero.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nGPS (0, 0, 0)\n", encoding="utf-8")
    out = tmp_path / "zero.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=32x32:d=1",
         "-i", str(srt), "-map", "0:v", "-map", "1:s", "-c:v", "libx264",
         "-preset", "ultrafast", "-c:s", "mov_text", "-t", "1", str(out)], check=True)
    m = MediaExtractor().extract(out)
    assert m.lat is None and m.gps_source is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_metadata_dji.py -v`
Expected: FAIL — `assert None == 'subtitle'`

- [ ] **Step 3: 实现**

在 ffprobe/exiftool 都没拿到 GPS 时：`ffmpeg -i <file> -map 0:s:0 -f srt -`（输出到临时文件，超时 10 s），用正则 `GPS\s*\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*\d+\s*\)` 取 `(lon, lat)`，跳过 `N/A`、越界与 `(0,0)`；命中则 `gps_source="subtitle"`。无字幕流 = 直接返回，不报错。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_metadata_dji.py tests/test_metadata.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/metadata.py tests/test_metadata_dji.py tests/fixtures/media/dji_gps.mp4
git commit -m "feat: DJI subtitle-track GPS extraction"
```

---

### Task 7: 省市解析层

**Files:**
- Create: `quantum-organizer/src/quantum_organizer/geocode.py`
- Create: `quantum-organizer/src/quantum_organizer/data/city_centers.json`（从 `media-renamer/core/china_cities.json` 复制，363 条，仅估算用）
- Test: `quantum-organizer/tests/test_geocode.py`

**Interfaces:**
- Produces:
  - `GeoResult(province: str|None, city: str|None, source: str, reason: str|None, boundary: bool=False)`；`source ∈ {"exact","remote","estimate","none"}`
  - `Geocoder(remote_url: str|None = None, allow_estimate: bool = False, locator=None)`
  - `Geocoder.resolve(lat: float, lon: float) -> GeoResult`（**注意参数顺序是 lat, lon**）
  - `Geocoder.resolve_many(coords: Sequence[tuple[float, float]]) -> dict[tuple[float, float], GeoResult]`（输入也是 `(lat, lon)`，内部去重）

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_geocode.py
import pytest
from quantum_organizer.geocode import Geocoder

@pytest.fixture(scope="module")
def g():
    return Geocoder()

def test_exact_resolution(g):
    r = g.resolve(32.0603, 118.7969)
    assert (r.province, r.city, r.source, r.reason) == ("江苏", "南京", "exact", None)

def test_works_for_municipality_district(g):
    r = g.resolve(39.9087, 116.3975)
    assert (r.province, r.city) == ("北京", "东城区")

def test_abroad(g):
    r = g.resolve(35.6895, 139.6917)
    assert (r.source, r.reason, r.province) == ("none", "abroad", None)

def test_taiwan_needs_city_level_data(g):
    r = g.resolve(25.0330, 121.5654)
    assert (r.reason, r.city, r.source) == ("needs_city_level_data", None, "none")

def test_estimate_off_by_default(g):
    assert g.resolve(35.6895, 139.6917).source == "none"

def test_estimate_never_guesses_for_taiwan_or_abroad():
    g = Geocoder(allow_estimate=True)
    assert g.resolve(25.0330, 121.5654).source == "none"
    assert g.resolve(35.6895, 139.6917).source == "none"

def test_estimate_applies_only_to_outside_polygons():
    class FakeLocator:
        def query(self, lon, lat, need_gcj02_convert=True):
            return type("Loc", (), {"province": None, "city": None, "level": None,
                                     "adcode": None, "boundary": False,
                                     "reason": "outside_polygons"})()
    g = Geocoder(allow_estimate=True, locator=FakeLocator())
    r = g.resolve(32.0603, 118.7969)
    assert (r.source, r.province, r.city) == ("estimate", "江苏", "南京")

def test_remote_mode(monkeypatch):
    import json, urllib.request
    body = json.dumps({"province": "江苏", "city": "南京", "level": "city",
                       "adcode": "320100", "reason": None}).encode()
    class Resp:
        def read(self): return body
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Resp())
    r = Geocoder(remote_url="http://localhost:8899").resolve(32.0603, 118.7969)
    assert (r.province, r.city, r.source) == ("江苏", "南京", "remote")

def test_resolve_many_dedupes(monkeypatch):
    g = Geocoder()
    calls = []
    real = g.resolve
    monkeypatch.setattr(g, "resolve", lambda lat, lon: calls.append((lat, lon)) or real(lat, lon))
    out = g.resolve_many([(32.0603, 118.7969), (32.0603, 118.7969), (32.0, 118.0)])
    assert len(calls) == 2 and len(out) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_geocode.py -v`
Expected: FAIL — `ImportError: Geocoder`

- [ ] **Step 3: 实现**

- `locator` 默认 `quantum_locator.CityLocator()`（同进程内嵌）；`remote_url` 存在时走 `GET {url}/api/v1/location?lon=&lat=&need_gcj02_convert=true`，5 s 超时，失败**回落到本地**而不是报错。
- 映射：`reason` 原样透传（`abroad` / `needs_city_level_data` / `outside_polygons`）；命中 → `source="exact"`（或 `"remote"`）。
- 估算：仅当 `allow_estimate` 且 `reason == "outside_polygons"`，用 `data/city_centers.json` 最近中心点（haversine），`source="estimate"`。
- 进程内 LRU 缓存（坐标保留 5 位小数做键）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_geocode.py -v`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/geocode.py src/quantum_organizer/data/city_centers.json tests/test_geocode.py
git commit -m "feat: province/city resolution with embedded quantum-locator"
```

---

### Task 8: 计划构建与冲突消解

**Files:**
- Create: `quantum-organizer/src/quantum_organizer/organize.py`
- Test: `quantum-organizer/tests/test_organize_plan.py`

**Interfaces:**
- Produces:
  - `PlanOptions(root: str, output_dir: str|None=None, copy: bool=False, move_unlocated: bool=False, recursive: bool=True, extensions: list[str]|None=None, allow_estimate: bool=False)`（含 `to_dict()`）
  - `options_fingerprint(opts: PlanOptions) -> str`（12 位 sha256）
  - `build_plan(items: list[MediaItem], opts: PlanOptions) -> Plan`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_organize_plan.py
import os, json
from pathlib import Path
import pytest
from quantum_organizer.organize import PlanOptions, build_plan, options_fingerprint
from quantum_organizer.models import MediaItem, Status

def item(path, prov="江苏", city="南京", date="240815", reason=None, status=Status.READY):
    return MediaItem(path=str(path), size=1, mtime=1.0, kind="image", shoot_time=date,
                     time_source="exif", lat=32.0, lon=118.0, gps_source="exiftool",
                     province=prov, city=city, geo_source="exact", status=status, reason=reason)

@pytest.fixture
def opts(tmp_path):
    return PlanOptions(root=str(tmp_path))

def test_target_path(opts, tmp_path):
    src = tmp_path / "IMG_1234.jpg"; src.write_bytes(b"x")
    p = build_plan([item(src)], opts)
    pi = p.items[0]
    assert (pi.decision, pi.target_name) == ("rename", "IMG_1234_江苏_南京_240815.jpg")
    assert pi.target_path == str(tmp_path / "江苏" / "南京" / "IMG_1234_江苏_南京_240815.jpg")
    assert Path(pi.target_path).resolve().is_relative_to(tmp_path.resolve())

def test_unlocated_items_untouched(opts, tmp_path):
    src = tmp_path / "a.jpg"; src.write_bytes(b"x")
    pi = build_plan([item(src, prov=None, city=None, reason="no_gps")], opts).items[0]
    assert pi.decision == "keep" and pi.target_path is None and pi.item.reason == "no_gps"

def test_move_unlocated_collects_without_renaming(tmp_path):
    src = tmp_path / "a.jpg"; src.write_bytes(b"x")
    o = PlanOptions(root=str(tmp_path), move_unlocated=True)
    pi = build_plan([item(src, prov=None, city=None, reason="no_gps")], o).items[0]
    assert pi.decision == "move"
    assert pi.target_path == str(tmp_path / "未定位" / "a.jpg")

def test_renaming_to_self_is_noop(opts, tmp_path):
    src = tmp_path / "a_江苏_南京_240815.jpg"; src.write_bytes(b"x")
    assert build_plan([item(src)], opts).items[0].decision == "keep"

def test_conflict_suffix_avoids_overwrite(opts, tmp_path):
    (tmp_path / "江苏" / "南京").mkdir(parents=True)
    (tmp_path / "江苏" / "南京" / "a_江苏_南京_240815.jpg").write_bytes(b"existing")
    src = tmp_path / "a.jpg"; src.write_bytes(b"x")
    plan = build_plan([item(src)], opts)
    assert Path(plan.items[0].target_name).name == "a_江苏_南京_240815_2.jpg"

def test_duplicate_targets_inside_one_plan(opts, tmp_path):
    a = tmp_path / "a.jpg"; a.write_bytes(b"1")
    b = tmp_path / "a.JPG"; b.write_bytes(b"2")
    plan = build_plan([item(a), item(b)], opts)
    names = sorted(Path(i.target_name).name for i in plan.items)
    assert names == ["a_江苏_南京_240815.JPG", "a_江苏_南京_240815.jpg"]

def test_symlink_refused(opts, tmp_path):
    real = tmp_path / "real.jpg"; real.write_bytes(b"x")
    link = tmp_path / "link.jpg"; os.symlink(real, link)
    pi = build_plan([item(link)], opts).items[0]
    assert pi.decision == "skip" and pi.item.reason == "symlink"

def test_invalid_items_kept(opts, tmp_path):
    pi = build_plan([item(tmp_path / "broken.jpg", status=Status.INVALID, reason="unreadable")],
                    opts).items[0]
    assert pi.decision == "keep"

def test_fingerprint_is_stable(tmp_path):
    a = PlanOptions(root=str(tmp_path))
    b = PlanOptions(root=str(tmp_path))
    assert options_fingerprint(a) == options_fingerprint(b)
    assert options_fingerprint(a) != options_fingerprint(PlanOptions(root=str(tmp_path), copy=True))
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_organize_plan.py -v`
Expected: FAIL — `ImportError: PlanOptions`

- [ ] **Step 3: 实现**

决策顺序：`status != READY` → `keep`；`province is None` → `keep`（或 `move` 到 `未定位/`，当 `move_unlocated`）；符号链接 → `skip`；否则 `rename`。
目标根 = `output_dir or root`；目标目录 = `<目标根>/<province>/<city>`。
同目录同名（`target == source`）→ `keep`。冲突时在 stem 尾部追加 `_2/_3…`（用 `naming.parse_existing` 保证不和已有序号混淆）。`taken` 集合要包含现有文件与**本 plan 已分配**的目标。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_organize_plan.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/organize.py tests/test_organize_plan.py
git commit -m "feat: plan building with conflict resolution and safety rules"
```

---

### Task 9: 操作历史

**Files:**
- Create: `quantum-organizer/src/quantum_organizer/history.py`
- Test: `quantum-organizer/tests/test_history.py`

**Interfaces:**
- Produces:
  - `HistoryStore(db_path: Path)`；表 `operations(id, started_at, finished_at, kind, root, options_json, status)`、`steps(op_id, seq, action, src, dst, status, error)`
  - `begin(kind, root, options_json) -> int`、`record_step(op_id, seq, action, src, dst, status, error=None)`、`finish(op_id, status)`、`get(op_id) -> OpRecord`、`last(root=None) -> OpRecord | None`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_history.py
from pathlib import Path
import pytest
from quantum_organizer.history import HistoryStore

@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "h.db")

def test_record_and_read_back(store):
    op = store.begin("apply", "/photos", "{}")
    store.record_step(op, 1, "rename", "/photos/a.jpg", "/photos/a_江苏_南京_240815.jpg", "done")
    store.record_step(op, 2, "move", "/photos/a_江苏_南京_240815.jpg",
                      "/photos/江苏/南京/a_江苏_南京_240815.jpg", "done")
    store.finish(op, "done")
    rec = store.get(op)
    assert [s.action for s in rec.steps] == ["rename", "move"]
    assert rec.status == "done" and rec.finished_at

def test_last_by_root(store):
    a = store.begin("apply", "/photos", "{}")
    b = store.begin("apply", "/other", "{}")
    store.finish(b, "done")
    assert store.last("/photos").op_id == a
    assert store.last().op_id == b

def test_failed_step_keeps_error(store):
    op = store.begin("apply", "/photos", "{}")
    store.record_step(op, 1, "move", "/x", "/y", "failed", "Permission denied")
    assert store.get(op).steps[0].error == "Permission denied"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_history.py -v`
Expected: FAIL — `ImportError: HistoryStore`

- [ ] **Step 3: 实现**

用 `sqlite3`，建表用 `IF NOT EXISTS`；每次写入单独 `with sqlite3.connect(...)` 事务（并发安全靠 WAL：`PRAGMA journal_mode=WAL`）。`get` 按 `seq` 排序返回 `OpRecord`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_history.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/history.py tests/test_history.py
git commit -m "feat: SQLite operation history"
```

---

### Task 10: 撤销

**Files:**
- Modify: `quantum-organizer/src/quantum_organizer/history.py`
- Test: `quantum-organizer/tests/test_history_undo.py`

**Interfaces:**
- Produces: `HistoryStore.undo(op_id: int, dry_run: bool=False) -> UndoResult`；`HistoryStore.mark_undone(op_id: int)`（`operations.status="undone"`）

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_history_undo.py
from pathlib import Path
import pytest
from quantum_organizer.history import HistoryStore

@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "h.db")

def _op(store, root):
    op = store.begin("apply", str(root), "{}")
    return op

def test_undo_reverts_rename_and_move(store, tmp_path):
    src = tmp_path / "a.jpg"; src.write_bytes(b"x")
    named = tmp_path / "a_江苏_南京_240815.jpg"
    dst = tmp_path / "江苏" / "南京" / named.name
    dst.parent.mkdir(parents=True)
    src.rename(named); named.rename(dst)

    op = _op(store, tmp_path)
    store.record_step(op, 1, "rename", str(src), str(named), "done")
    store.record_step(op, 2, "move", str(named), str(dst), "done")
    store.finish(op, "done")

    res = store.undo(op)
    assert res.ok and res.reverted == 2
    assert src.exists() and not dst.exists()
    assert store.get(op).status == "undone"

def test_undo_stops_on_missing_target(store, tmp_path):
    src = tmp_path / "a.jpg"; src.write_bytes(b"x")
    missing = tmp_path / "gone.jpg"
    op = _op(store, tmp_path)
    store.record_step(op, 1, "rename", str(src), str(missing), "done")
    store.finish(op, "done")
    res = store.undo(op)
    assert not res.ok and res.reverted == 0
    assert str(missing) in res.conflicts
    assert src.exists()          # 源文件没被动过

def test_undo_dry_run_touches_nothing(store, tmp_path):
    src = tmp_path / "a.jpg"; src.write_bytes(b"x")
    dst = tmp_path / "b.jpg"; src.rename(dst)
    op = _op(store, tmp_path)
    store.record_step(op, 1, "rename", str(src), str(dst), "done")
    store.finish(op, "done")
    res = store.undo(op, dry_run=True)
    assert res.ok and res.reverted == 1
    assert dst.exists() and not src.exists()

def test_undo_twice_is_refused(store, tmp_path):
    src = tmp_path / "a.jpg"; src.write_bytes(b"x")
    dst = tmp_path / "b.jpg"; src.rename(dst)
    op = _op(store, tmp_path)
    store.record_step(op, 1, "rename", str(src), str(dst), "done")
    store.finish(op, "done")
    store.undo(op)
    with pytest.raises(RuntimeError):
        store.undo(op)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_history_undo.py -v`
Expected: FAIL — `AttributeError: 'HistoryStore' object has no attribute 'undo'`

- [ ] **Step 3: 实现**

按 `seq` 逆序：`dst` 必须存在且 `src` 必须不存在，否则该步记 `conflict` 并**停止**（已回滚的保留）；`action=="copy"` 的撤销是 copy 回 src 后删除 dst；每步成功后把该 step 的 `status` 改成 `reverted"`。全部成功 → `mark_undone`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_history_undo.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/history.py tests/test_history_undo.py
git commit -m "feat: reverse-order undo with conflict abort"
```

---

### Task 11: 执行计划

**Files:**
- Modify: `quantum-organizer/src/quantum_organizer/organize.py`
- Test: `quantum-organizer/tests/test_organize_apply.py`

**Interfaces:**
- Consumes: `Plan`/`PlanItem`（Task 2、8）、`HistoryStore`（Task 9）
- Produces: `apply_plan(plan: Plan, history: HistoryStore, dry_run: bool=False, selection: Sequence[str] | None = None) -> OpRecord`（`selection` 是 `item.path` 列表）；模块内辅助 `_writable(path: Path) -> bool`（预检用，测试会 monkeypatch 它）

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_organize_apply.py
from pathlib import Path
import pytest
from quantum_organizer.history import HistoryStore
from quantum_organizer.organize import PlanOptions, apply_plan, build_plan
from quantum_organizer.models import MediaItem

def _item(path, prov="江苏", city="南京", date="240815"):
    return MediaItem(path=str(path), size=1, mtime=1.0, kind="image", shoot_time=date,
                     time_source="exif", lat=32.0, lon=118.0, gps_source="exiftool",
                     province=prov, city=city, geo_source="exact")

@pytest.fixture
def env(tmp_path):
    media = tmp_path / "src"; media.mkdir()
    a = media / "a.jpg"; a.write_bytes(b"1")
    b = media / "b.jpg"; b.write_bytes(b"2")
    opts = PlanOptions(root=str(media))
    plan = build_plan([_item(a), _item(b, prov=None, city=None)], opts)
    return media, plan, HistoryStore(tmp_path / "h.db")

def test_apply_renames_and_moves(env):
    media, plan, hist = env
    rec = apply_plan(plan, hist)
    assert rec.status == "done"
    target = media / "江苏" / "南京" / "a_江苏_南京_240815.jpg"
    assert target.exists() and not (media / "a.jpg").exists()
    assert [s.action for s in rec.steps] == ["rename", "move"]
    # 无省市的那张必须原地不动、不进 steps
    assert (media / "b.jpg").exists()

def test_apply_dry_run_changes_nothing(env):
    media, plan, hist = env
    rec = apply_plan(plan, hist, dry_run=True)
    assert rec.status == "planned"
    assert (media / "a.jpg").exists() and not (media / "江苏").exists()
    assert rec.steps == []

def test_apply_selection_only(env):
    media, plan, hist = env
    apply_plan(plan, hist, selection=[str(media / "b.jpg")])
    assert (media / "a.jpg").exists()      # 未被选中
    assert (media / "b.jpg").exists()      # keep 决策，无动作

def test_apply_is_idempotent(env, tmp_path):
    media, plan, hist = env
    apply_plan(plan, hist)
    again = build_plan([_item(media / "江苏" / "南京" / "a_江苏_南京_240815.jpg")],
                       PlanOptions(root=str(media)))
    assert again.items[0].decision == "keep"

def test_copy_mode_keeps_source(tmp_path):
    media = tmp_path / "src"; media.mkdir()
    a = media / "a.jpg"; a.write_bytes(b"1")
    opts = PlanOptions(root=str(media), copy=True)
    plan = build_plan([_item(a)], opts)
    hist = HistoryStore(tmp_path / "h.db")
    rec = apply_plan(plan, hist)
    assert (media / "a.jpg").exists()                       # 源文件保留
    assert (media / "江苏" / "南京" / "a_江苏_南京_240815.jpg").exists()
    assert rec.steps[-1].action == "copy"

def test_apply_aborts_before_touching_when_target_unwritable(env, monkeypatch):
    media, plan, hist = env
    monkeypatch.setattr("quantum_organizer.organize._writable", lambda p: False, raising=False)
    with pytest.raises(PermissionError):
        apply_plan(plan, hist)
    assert (media / "a.jpg").exists()
```

> 说明：`copy` 模式由 `PlanOptions.copy` 决定。`copy=True` 时 `apply_plan` 把整个「改名+移动」合并成一次复制：读到目标名后 `shutil.copy2(src, dst)`，源文件保留，记录 `action="copy"`。撤销时复制回原位并删除副本。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_organize_apply.py -v`
Expected: FAIL — `ImportError: apply_plan`

- [ ] **Step 3: 实现**

- 执行前对每个目标父目录做可写检查（`os.access`），任一失败 → 抛 `PermissionError`，**不动文件**。
- 单条：先 rename（同目录），再 move（`shutil.move`，先 `mkdir(parents=True)`）；跨设备（`st_dev` 不同）→ 改用 `shutil.copy2` + `os.unlink`，记录 `action="copy"`。
- 每步成功后立刻 `record_step`；失败 → `record_step(status="failed", error=...)`，`finish("partial")` 并继续下一个 item。
- `dry_run` → 不写文件系统、写历史（`status="planned"`、无 steps）。
- 保留 mtime：`os.utime(dst, ns=(atime, mtime))`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_organize_apply.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/organize.py tests/test_organize_apply.py
git commit -m "feat: apply plan with pre-flight checks and per-step history"
```

---

### Task 12: 扫描流水线（并发、进度、缓存、上限）

**Files:**
- Create: `quantum-organizer/src/quantum_organizer/pipeline.py`
- Test: `quantum-organizer/tests/test_pipeline_scan.py`

**Interfaces:**
- Produces:
  - `ProgressFn = Callable[[int, int, str], bool]`（返回 False 中止）
  - `Pipeline(state_dir: Path, geocoder=None, extractor=None, concurrency: int=8, max_files: int=100_000)`
  - `Pipeline.scan(opts: PlanOptions, progress: ProgressFn | None = None) -> Plan`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_pipeline_scan.py
import shutil
from pathlib import Path
import pytest
from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline

FX = Path("tests/fixtures/media")

@pytest.fixture
def media(tmp_path):
    d = tmp_path / "src"; d.mkdir()
    for name in ("photo_gps.jpg", "photo_nogps.jpg", "plain.mp4", "broken.jpg"):
        shutil.copy(FX / name, d / name)
    return d

def test_scan_fills_geocode_and_plan(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    by_name = {Path(i.item.path).name: i for i in plan.items}
    assert by_name["photo_gps.jpg"].item.province == "江苏"
    assert by_name["photo_gps.jpg"].item.city == "南京"
    assert by_name["photo_gps.jpg"].decision == "rename"
    assert by_name["photo_nogps.jpg"].decision == "keep"
    assert by_name["plain.mp4"].decision == "keep"
    assert by_name["broken.jpg"].item.status.value == "invalid"

def test_scan_reports_progress(media, tmp_path):
    seen = []
    p = Pipeline(tmp_path / "state")
    p.scan(PlanOptions(root=str(media)), progress=lambda i, n, name: seen.append((i, n)) or True)
    assert seen[-1] == (4, 4)

def test_scan_can_be_aborted(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)),
                  progress=lambda i, n, name: i < 1)      # 第一个文件后就中止
    assert len(plan.items) == 1

def test_scan_cache_skips_reextraction(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    p.scan(PlanOptions(root=str(media)))
    calls = []
    real = p.extractor.extract
    p.extractor.extract = lambda path: calls.append(path) or real(path)
    p.scan(PlanOptions(root=str(media)))
    assert calls == []

def test_scan_refuses_above_limit(media, tmp_path):
    p = Pipeline(tmp_path / "state", max_files=2)
    with pytest.raises(ValueError, match="max_files"):
        p.scan(PlanOptions(root=str(media)))

def test_scan_ignores_non_media(media, tmp_path):
    (media / "notes.txt").write_text("x")
    plan = Pipeline(tmp_path / "state").scan(PlanOptions(root=str(media)))
    assert all(Path(i.item.path).suffix != ".txt" for i in plan.items)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pipeline_scan.py -v`
Expected: FAIL — `ImportError: Pipeline`

- [ ] **Step 3: 实现**

1. 枚举：扩展名集合取自 `metadata`（图片/视频/音频），`rglob` 当 `recursive`；数量 > `max_files` → `ValueError(f"found N files, exceeds max_files={max}")`。
2. 缓存表 `scan_cache(path PRIMARY KEY, size, mtime, item_json)`：命中 → 直接复用 `MediaItem`（这是"一次扫描只读一遍"的实现）。
3. `ThreadPoolExecutor(max_workers=concurrency)` 提取；每完成一个回调 `progress(i, total, name)`，返回 False 则停止提交新任务。
4. 坐标去重后 `geocoder.resolve_many`，回填 `province/city/geo_source/geo_boundary`；`reason` 为空且无 GPS 时置 `no_gps`。
5. `build_plan` 产出 `Plan`（`plan_id` 用 `uuid4().hex[:12]`）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_pipeline_scan.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/pipeline.py tests/test_pipeline_scan.py
git commit -m "feat: scanning pipeline with cache, progress and hard limit"
```

---

### Task 13: 计划持久化与执行/撤销门面

**Files:**
- Modify: `quantum-organizer/src/quantum_organizer/pipeline.py`
- Test: `quantum-organizer/tests/test_pipeline_apply.py`

**Interfaces:**
- Produces:
  - `Pipeline.save_plan(plan: Plan) -> str`
  - `Pipeline.load_plan(plan_id: str | None, root: str, options: PlanOptions | None = None) -> Plan`
  - `Pipeline.apply(plan: Plan, selection=None, dry_run=False) -> OpRecord`
  - `Pipeline.undo(op_id: int | None = None, root: str | None = None, dry_run: bool = False) -> UndoResult`
  - `Pipeline.history() -> HistoryStore`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_pipeline_apply.py
import shutil
from pathlib import Path
import pytest
from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline

FX = Path("tests/fixtures/media")

@pytest.fixture
def media(tmp_path):
    d = tmp_path / "src"; d.mkdir()
    shutil.copy(FX / "photo_gps.jpg", d / "photo_gps.jpg")
    shutil.copy(FX / "photo_nogps.jpg", d / "photo_nogps.jpg")
    return d

def test_save_and_load_plan(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    pid = p.save_plan(plan)
    loaded = p.load_plan(pid, str(media))
    assert loaded.plan_id == pid and len(loaded.items) == len(plan.items)

def test_load_latest_plan_by_root(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    p.save_plan(p.scan(PlanOptions(root=str(media))))
    assert p.load_plan(None, str(media)).root == str(media)

def test_fingerprint_mismatch_raises(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    p.save_plan(p.scan(PlanOptions(root=str(media))))
    with pytest.raises(ValueError, match="fingerprint"):
        p.load_plan(None, str(media), options=PlanOptions(root=str(media), copy=True))

def test_apply_then_undo_restores_tree(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    p.save_plan(plan)
    rec = p.apply(plan)
    assert rec.status == "done"
    assert (media / "江苏" / "南京").is_dir()
    res = p.undo(op_id=rec.op_id)
    assert res.ok
    assert (media / "photo_gps.jpg").exists()
    assert not (media / "江苏").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pipeline_apply.py -v`
Expected: FAIL — `AttributeError: 'Pipeline' object has no attribute 'save_plan'`

- [ ] **Step 3: 实现**

`save_plan`：写 `plans(plan_id, root, created_at, options_fingerprint, json)` 与 `scan_items(plan_id, path, item_json, decision)`；`load_plan(plan_id=None, root=..., options=None)`：无 id 取该 root 最新；传入 `options` 时比对 `options_fingerprint`，不符抛 `ValueError("fingerprint mismatch, rescan required")`。
`apply`：委托 `organize.apply_plan`，`op_id` 取 `history.last` 最新记录 id。
`undo`：`op_id` 为空时取 `root` 下最新（未撤销的）操作；已被撤销 → `RuntimeError`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_pipeline_apply.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/pipeline.py tests/test_pipeline_apply.py
git commit -m "feat: plan persistence, apply and undo facade"
```

---

### Task 14: CLI

**Files:**
- Modify: `quantum-organizer/src/quantum_organizer/cli.py`
- Test: `quantum-organizer/tests/test_cli.py`

**Interfaces:**
- Produces（typer）：
  - `qorg scan ROOT [--output DIR] [--recursive/--no-recursive] [--json PATH]`
  - `qorg apply ROOT [--plan ID] [--select PATH] [--dry-run] [--yes] [--copy] [--move-unlocated] [--allow-estimate]`
  - `qorg undo [--op ID] [--root DIR] [--dry-run]`
  - `qorg serve [--data DIR] [--port 8080]`
  - `qorg doctor`
  - 退出码：`0` 成功；`1` 无可处理项；`2` 参数/预检失败；`3` 部分失败

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_cli.py
import json, shutil
from pathlib import Path
from typer.testing import CliRunner
from quantum_organizer.cli import app

FX = Path("tests/fixtures/media")
runner = CliRunner()

def test_scan_writes_json(tmp_path, monkeypatch):
    media = tmp_path / "src"; media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "photo_gps.jpg")
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    out = tmp_path / "plan.json"
    r = runner.invoke(app, ["scan", str(media), "--json", str(out)])
    assert r.exit_code == 0
    data = json.loads(out.read_text("utf-8"))
    assert data["items"][0]["item"]["province"] == "江苏"

def test_apply_requires_yes(tmp_path, monkeypatch):
    media = tmp_path / "src"; media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "photo_gps.jpg")
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    r = runner.invoke(app, ["apply", str(media)])
    assert r.exit_code == 2 and "confirm" in r.stdout.lower()
    assert (media / "photo_gps.jpg").exists()

def test_apply_then_undo(tmp_path, monkeypatch):
    media = tmp_path / "src"; media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "photo_gps.jpg")
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    assert runner.invoke(app, ["scan", str(media)]).exit_code == 0
    assert runner.invoke(app, ["apply", str(media), "--yes"]).exit_code == 0
    assert (media / "江苏" / "南京").is_dir()
    assert runner.invoke(app, ["undo", "--root", str(media)]).exit_code == 0
    assert (media / "photo_gps.jpg").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — 未知子命令/退出码不符

- [ ] **Step 3: 实现**

每个命令组装 `PlanOptions`（`--allow-estimate` 转 `Geocoder(allow_estimate=True)`），`scan` 打印前 30 行预览表（原文件名 → 目标路径、原因），`apply` 无 `--yes` 时打印 `confirm with --yes` 并以 2 退出。`serve` 调用 `web.app.create_app`（Task 15 尚未实现时先留 `NotImplementedError` 并在 Task 15 接上）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_cli.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/cli.py tests/test_cli.py
git commit -m "feat: CLI scan/apply/undo"
```

---

### Task 15: Web API

**Files:**
- Create: `quantum-organizer/src/quantum_organizer/web/__init__.py`
- Create: `quantum-organizer/src/quantum_organizer/web/app.py`
- Create: `quantum-organizer/src/quantum_organizer/web/jobs.py`
- Test: `quantum-organizer/tests/test_web_api.py`

**Interfaces:**
- Produces:
  - `create_app(state_dir: Path, data_root: str | None = None) -> FastAPI`
  - `POST /api/v1/plans` `{root, output_dir?, copy?, move_unlocated?, allow_estimate?}` → `{plan_id, counts}`
  - `GET /api/v1/plans/{plan_id}/items?page=1&size=200&decision=&reason=` → `{total, page, size, items}`
  - `POST /api/v1/plans/{plan_id}/apply` `{paths?: [str], dry_run?: bool}` → `{op_id}`
  - `GET /api/v1/ops/{op_id}` → `{status, steps}`
  - `POST /api/v1/ops/{op_id}/undo` → `{ok, reverted, conflicts}`
  - `GET /api/v1/progress/{job_id}` → SSE，事件 `progress` 携带 `{done, total, current}`
  - `GET /healthz` → `{"status":"ok"}`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_web_api.py
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from quantum_organizer.web.app import create_app

FX = Path("tests/fixtures/media")

@pytest.fixture
def client(tmp_path):
    media = tmp_path / "src"; media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "photo_gps.jpg")
    shutil.copy(FX / "photo_nogps.jpg", media / "photo_nogps.jpg")
    app = create_app(state_dir=tmp_path / "state", data_root=str(tmp_path))
    return TestClient(app), media

def test_health(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}

def test_plan_items_are_paginated(client):
    c, media = client
    pid = c.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]
    body = c.get(f"/api/v1/plans/{pid}/items", params={"page": 1, "size": 1}).json()
    assert body["total"] == 2 and len(body["items"]) == 1

def test_apply_and_undo(client):
    c, media = client
    pid = c.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]
    op = c.post(f"/api/v1/plans/{pid}/apply", json={"dry_run": False}).json()["op_id"]
    assert c.get(f"/api/v1/ops/{op}").json()["status"] == "done"
    assert (media / "江苏" / "南京").is_dir()
    assert c.post(f"/api/v1/ops/{op}/undo").json()["ok"] is True
    assert (media / "photo_gps.jpg").exists()

def test_apply_rejects_foreign_path(client):
    c, media = client
    pid = c.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]
    r = c.post(f"/api/v1/plans/{pid}/apply", json={"paths": ["/etc/passwd"]})
    assert r.status_code == 400

def test_root_must_be_under_data_root(client):
    c, tmp_path = client
    r = c.post("/api/v1/plans", json={"root": "/etc"})
    assert r.status_code == 400
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_web_api.py -v`
Expected: FAIL — `ImportError: create_app`

- [ ] **Step 3: 实现**

- 单 worker 内存内 `jobs` 注册表（`dict[str, dict]`），后台线程跑 scan，`asyncio.Queue` + `StreamingResponse(text/event-stream)` 推送进度。
- `data_root` 限制：`root` 解析后必须是 `data_root` 的子路径，否则 400（防任意目录读取）。
- `apply` 的 `paths` 必须出现在该 plan 中，否则 400。
- `qorg serve` 接 `uvicorn.run(app, host="0.0.0.0", port=port, workers=1)`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_web_api.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/quantum_organizer/web tests/test_web_api.py
git commit -m "feat: web API with paginated preview, apply, undo and SSE progress"
```

---

### Task 16: Web 前端的实现与运行验证

**Files:**
- Create: `quantum-organizer/frontend/package.json`, `vite.config.js`, `index.html`
- Create: `quantum-organizer/frontend/src/{main.js,App.vue,api.js,components/PreviewTable.vue,components/ProgressBar.vue}`
- Test: `quantum-organizer/tests/test_web_static.py`

**Interfaces:**
- Consumes: Task 15 的 HTTP 接口
- Produces: `npm run build` → `src/quantum_organizer/web/static/`（`index.html` + `assets/*`），FastAPI 用 `StaticFiles` 挂 `/`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_web_static.py
from pathlib import Path
from fastapi.testclient import TestClient
from quantum_organizer.web.app import create_app

def test_serves_built_index(tmp_path):
    static = Path("src/quantum_organizer/web/static")
    assert (static / "index.html").exists(), "run `npm run build` in frontend/ first"
    c = TestClient(create_app(state_dir=tmp_path / "state"))
    r = c.get("/")
    assert r.status_code == 200 and "qorg" in r.text.lower()
```

- [ ] **Step 2: 建前端并构建**

Vue 3 + Vite 单页：顶部「目录输入 + 扫描」；中部分页表（列：原文件名、时间、坐标、省、市、目标路径、状态/原因），支持按 decision/reason 筛选、全选/反选；底部「执行所选」「撤销本次」「导出结果 JSON」。
`vite.config.js` 设 `build.outDir = "../src/quantum_organizer/web/static"`、`emptyOutDir: true`。

Run: `cd frontend && npm ci && npm run build`
Expected: `static/index.html` 与 `static/assets/` 生成

- [ ] **Step 3: 运行确认通过**

Run: `python -m pytest tests/test_web_static.py -v`
Expected: 1 passed

- [ ] **Step 4: 真人浏览器验收（必做，不能只看测试）**

Run: `qorg serve --data /tmp/qorg-demo --port 8080`，浏览器打开 `http://localhost:8080`：
1. 把 `tests/fixtures/media/photo_gps.jpg` 与 `photo_nogps.jpg` 拷进 `/tmp/qorg-demo`；
2. 页面上扫描 → 表格出现两行，GPS 那张目标路径含 `江苏/南京`，另一张显示 `no_gps`；
3. 执行 → 文件真的被移动；撤销 → 回到原位。

Expected: 三步都在真实浏览器里完成（截图或录屏留在 PR 描述里）

- [ ] **Step 5: 提交**

```bash
git add frontend src/quantum_organizer/web/static tests/test_web_static.py
git commit -m "feat: Vue preview UI"
```

---

### Task 17: Docker 镜像与 compose

**Files:**
- Create: `quantum-organizer/Dockerfile`
- Create: `quantum-organizer/docker-compose.yml`, `.dockerignore`

**Interfaces:**
- Produces: 镜像 `ghcr.io/<org>/quantum-organizer`，`ENTRYPOINT ["qorg"]`，`CMD ["serve","--data","/data","--port","8080"]`，`HEALTHCHECK` 打 `/healthz`

- [ ] **Step 1: 写多阶段 Dockerfile**

阶段一 `node:20-alpine`：`npm ci && npm run build`；阶段二 `python:3.12-slim`：`apt-get install -y --no-install-recommends ffmpeg libimage-exiftool-perl`，`pip install .`，`COPY --from=build /app/src/quantum_organizer/web/static ...`，`EXPOSE 8080`，`VOLUME ["/data","/state"]`，`ENV QORG_STATE_DIR=/state`。

- [ ] **Step 2: compose 与冒烟**

```bash
docker build -t quantum-organizer:dev .
docker run --rm -d -p 18080:8080 -v /tmp/qorg-demo:/data -v /tmp/qorg-state:/state \
  --name qorg-smoke quantum-organizer:dev
sleep 10 && curl -s http://localhost:18080/healthz
docker run --rm -v /tmp/qorg-demo:/data quantum-organizer:dev scan /data
docker rm -f qorg-smoke
```

Expected: `{"status":"ok"}`；`scan` 打印预览表；容器内 `qorg doctor` 三件工具齐全

- [ ] **Step 3: 校验状态隔离**

Run: `docker run --rm -v /tmp/qorg-demo:/data quantum-organizer:dev apply /data --yes && ls -a /tmp/qorg-demo`
Expected: 素材目录里除了整理后的省市目录，**没有** `.db`/`.log`；`/tmp/qorg-state` 里才有

- [ ] **Step 4: 提交**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "build: single-image docker deployment"
```

---

### Task 18: 端到端回归、文档与发布

**Files:**
- Create: `quantum-organizer/tests/test_e2e.py`
- Create: `quantum-organizer/README.md`, `README_CN.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE`
- Create: `quantum-organizer/.github/workflows/release.yml`
- Create: `quantum-organizer/docs/rules/naming.md`

**Interfaces:**
- Consumes: 全部前置任务

- [ ] **Step 1: 写端到端测试**

```python
# tests/test_e2e.py
import shutil
from pathlib import Path
from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline

FX = Path("tests/fixtures/media")

def test_dirty_folder_to_sorted_tree_and_back(tmp_path):
    media = tmp_path / "乱文件夹"; media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "IMG_0001.jpg")
    shutil.copy(FX / "photo_gps.jpg", media / "IMG_0001.JPG")   # 同名不同扩展名
    shutil.copy(FX / "photo_nogps.jpg", media / "IMG_0002.jpg")
    shutil.copy(FX / "dji_gps.mp4", media / "DJI_0001.mp4")
    shutil.copy(FX / "broken.jpg", media / "坏文件.jpg")
    (media / "IMG_0001_江苏_南京_140815.jpg").write_bytes(b"already done")

    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    rec = p.apply(plan)

    names = sorted(x.name for x in (media / "江苏" / "南京").iterdir())
    assert "IMG_0001_江苏_南京_140815.jpg" in names
    assert not any(n.count("江苏") > 1 for n in names)          # 幂等
    assert (media / "IMG_0002.jpg").exists()                    # 无 GPS 不动
    assert (media / "坏文件.jpg").exists()                      # 坏文件不动
    assert any((media / "江苏" / "南京").glob("DJI_0001_江苏_南京_*.mp4"))

    res = p.undo(op_id=rec.op_id)
    assert res.ok
    assert sorted(x.name for x in media.iterdir()) == sorted([
        "IMG_0001.jpg", "IMG_0001.JPG", "IMG_0002.jpg", "DJI_0001.mp4",
        "坏文件.jpg", "IMG_0001_江苏_南京_140815.jpg"])
```

- [ ] **Step 2: 运行端到端测试**

Run: `python -m pytest tests/test_e2e.py -v`
Expected: 1 passed（若失败，修实现而不是改断言）

- [ ] **Step 3: 写文档与规则**

`docs/rules/naming.md`：格式串、清洗规则（含 stem 表）、幂等规则、冲突 `_2` 规则、直辖市/港澳第二级=所在区、台湾未定位、日期来源优先级。这份文档是二期 Dart 实现的唯一依据。
`README_CN.md`/`README.md`：一句话定位、「docker run 一条命令」、CLI 四个命令、撤销、已知限制（境外/台湾/时区不推断）、`quantum-locator` 的独立仓库链接。README 里每条命令都要在本机实测过再写。

- [ ] **Step 4: 发布工作流 + 全量验证**

`release.yml`：tag `v*` → 跑全量测试 → `docker buildx build --platform linux/amd64,linux/arm64 --push` 到 ghcr。

Run: `ruff check . && mypy src/ && python -m pytest -q`
Expected: 全绿；`pytest` 总数 ≥ 60

- [ ] **Step 5: 提交**

```bash
git add tests/test_e2e.py README.md README_CN.md CONTRIBUTING.md CHANGELOG.md LICENSE docs .github
git commit -m "docs: bilingual docs, naming rules and release pipeline"
```

---

## Self-Review

- **Spec 覆盖**：§6.1/6.2 使用方式（T14/T15/T16）；§6.3 输出模式与 copy（T8/T11）；§6.4 未定位与 `--move-unlocated`（T8）；§7.3 流水线六阶段（T12/T11）；§7.4 命名幂等（T3/T4）；§7.5 状态目录与撤销（T9/T10/T13）；§7.6 冲突/跨设备/符号链接/预检（T8/T11）；§8.2 内嵌 quantum-locator 与远程模式（T7）；§9 仓库结构（T1 起）；§10 部署（T17）；§11 测试与黄金用例（T3/T18）；§12 里程碑 M1–M4（T1–T18 对应）；§13 二期契约（T3 的 `naming_cases.json` + T18 的 `naming_rules.md`）；§14 迁移（T18 后执行删除旧目录，单独提交）。
- **Review Focus 落点**：幂等 → T4/T18；同名冲突 → T8/T18；无 GPS/境外/台湾 → T8/T11/T18；坏文件 → T5/T12/T18；长名/非法字符 → T4。
- **类型一致性**：`MediaItem` 字段在 T2 定义、T5/T6/T12 填充、T8 读取；`PlanItem.decision` 取值固定 `{rename,move,keep,skip}`；`Geocoder.resolve(lat, lon)` 与 `quantum_locator.query(lon, lat)` 的顺序差异已在 T7 接口块注明。
- **未决但明确留给实现者**：并发默认 8（可调）、扫描缓存表结构细节、Web 分页大小 200、日志格式。
