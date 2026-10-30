# Quantum Organizer 设计文档

日期：2026-10-30
状态：待评审
作者：Hermes（与用户共同确定）

---

## 1. 意图

把现在散落的三个项目（`city_locator` 坐标解析服务、`media-renamer` 重命名、
`media-classifier` 省市归档）合并成一个**开箱即用的素材目录整理工具**，以
开源项目的形式发布，服务对象是摄影师、普通拍照用户、DJI 无人机与运动相机用户。

用户拿到它之后的心智模型只有一句话：

> 指给它一个乱文件夹，它把里面的照片和视频按「省/市」分好，文件名补上
> 「省/市/拍摄日期」，做错了能一键撤回。

为什么现在做：三个项目已经各自能跑（见第 4 节实测），但每跑一次要起三个
进程、开三个界面、手动保证顺序，普通用户不可能完成；且三处各自维护历史库，
出错无法整体回滚。

## 2. 目标 / 非目标 / 反面目标

### 目标（v0.1 必须满足）

- 一条命令或一个界面完成「扫描 → 预览 → 执行 → 撤销」，顺序由产品保证。
- 一次扫描只读一遍文件：元数据提取结果在同一次操作内复用，不重复 ffprobe。
- 支持图片（JPEG/HEIC/DNG/RAW 等 EXIF）与视频（ffprobe + DJI 字幕轨 GPS）。
- 只依赖一个镜像 / 一次 `pip install`，不需要用户另外起坐标服务。
- 预览是默认行为，执行需要显式确认；任何一个操作都能整体撤销。
- 中文/英文双语界面与文档。

### 非目标（v0.1 不做）

- 手机 App（Android/iOS/鸿蒙）——二期，见第 13 节契约。
- 中国大陆以外的行政层级解析（境外素材落「未定位」，见 6.4）。
- AI 场景/人脸识别、重复文件去重、云盘接入。
- 服务端多用户、账号体系、上传大文件的 Web 场景（素材量以挂载目录为主）。

### 反面目标（技术上跑通但判定为失败）

- 用户跑完发现一半文件被改了名字却不知道改了什么 → 失败。
- 撤销不完整，或撤销后目录结构与执行前不一致 → 失败。
- 同一个文件夹跑第二遍，文件名继续叠加 `_江苏_南京_240815` → 失败。
- 为了「架构漂亮」让用户必须起两个容器才能用 → 失败。

## 3. 硬约束（实测得出，不可绕过）

1. **DJI 视频的 GPS 在字幕轨里**，必须用 ffmpeg 解；照片走 exiftool。
   本机 `/usr/bin/ffprobe`、`/usr/bin/ffmpeg`、`exiftool` 均可用，实测
   `DJI_0189.mp4` 提取到 `32.0967, 118.7411` 与拍摄时间 `210921`。
2. **city_locator 的 geojson 是 GCJ02 坐标**（数据源为阿里 DataV，`东城区`
   center `[116.418757, 39.917544]` 是 GCJ02 值）。而相机/无人机 EXIF 里的
   GPS 是 WGS84。现有 renamer 调用 `/api/v1/location` 时**没有**传
   `need_gcj02_convert=true`，在城市边界附近会落错市——这是必须修的既有缺陷。
3. **移动端不是桌面端的等价物**：iOS「照片」只有平铺相簿、不能嵌套目录；
   Android 走 SAF 需目录授权；鸿蒙 NEXT 不兼容 APK；ffmpeg-kit 已于 2025 年初
   停止维护，移动端解析视频 GPS 成本高。这是二期单独评估的原因。
4. **不能再用 Streamlit 作为主界面**：它的 session 模型与「长任务 + 进度 +
   服务端目录扫描」不匹配，且界面逻辑现已全部耦合在 `app.py` 里（renamer 621 行、
   classifier 492 行），无法复用为可测试的核心。
5. 三个现有目录**都不是 git 仓库**，没有 CI 历史，新项目需要从零建立仓库纪律。

## 4. 现状盘点与复用清单

| 现有资产 | 实测状态 | 新项目中的处置 |
|---|---|---|
| `city_locator/city_locator_server.py` | FastAPI + GeoPandas/Rtree，8899 在跑，477 个多边形（363 市 + 112 区 + 1 省），返回 `江苏-南京` | 抽出为独立包 `quantum-locator`，被主程序以库方式内嵌（第 8 节） |
| `city_locator/china_cities.geojson` | 3.7 MB，GCJ02 | 随 `quantum-locator` 包发布，成为唯一数据源 |
| `media-renamer/core/renamer.py` (737 行) | `MediaExtractor` 三级提取（ffprobe → ffmpeg 字幕 → exiftool）实测有效 | 移植为 `quantum_organizer.core.metadata` |
| `media-renamer/core/gps_resolver.py` (250 行) | 三级解析；**默认 `api_type="gaode"`，无 key 时直接退化为 363 城市中心点最近邻**（精度 ~数十公里） | 重写为 `quantum_organizer.core.geocode`，默认走内嵌精确解析，估算仅作最后兜底 |
| `media-classifier/core/classifier.py` (642 行) | 正则 `^(.+)_(.+?)_(.+?)_(\d{6})$`，原地/统一输出两种模式，SQLite 撤销 | 移植为 `quantum_organizer.core.organize` + `naming` |
| `media-renamer/app.py`、`media-classifier/app.py` | Streamlit，各自 8503/8504 | 不移植；界面逻辑重写为薄层 |
| `renamer/`、`classfier/`（旧单文件脚本） | 功能是上面两个的早期版本 | 迁移完成后删除 |
| `media-video-cut-webui/` | 视频粗剪项目，与本产品无关 | 不纳入新仓库 |

## 5. 方案取舍

三条路线在对话中比较过，用户选择 **C：分阶段**。

- **A Python 全栈**：最快，但二期 App 必须重写核心。
- **B 共享核心（Rust + Flutter FFI）**：三端一致，成本 2–3 倍，鸿蒙仍需单独适配。
- **C 分阶段（选中）**：v0.1 用 Python 出整装工具，核心写成**无 UI 依赖的纯函数库**；
  二期 App 用 Flutter/Dart 原生实现，与桌面端共用 geojson、城市表和**命名规则文档 +
  黄金用例**（第 13 节）。风险是两套实现漂移，用共享用例锁住。

选择 C 的理由：开源项目的使用者和 star 来自「能挂载一整个素材盘」的桌面/服务器场景；
App 的价值集中在手机直拍照片，与 DJI/SD 卡素材的主战场不同。先把主战场做扎实，且核心
与 UI 解耦后，二期若要改成 B 路线也只需换核心语言，而不是推翻产品。

## 6. 产品形态

### 6.1 一次典型使用

```
docker run --rm -p 8080:8080 -v /mnt/photos:/data -v qorg-state:/state \
  ghcr.io/<org>/quantum-organizer   serve
```
浏览器打开 `http://localhost:8080` → 选 `/data` 下的目录 → 看到一张预览表（每行：原文件名、
拍摄时间、坐标、解析出的省市、目标路径、状态、失败原因）→ 勾选/全选 → 执行 →
进度条实时推进 → 完成后可「撤销本次操作」。

命令行等价：

```
qorg scan  /data/2024旅行            # 只扫描，产出预览（JSON + 表格）
qorg apply /data/2024旅行 --dry-run  # 默认 dry-run
qorg apply /data/2024旅行 --yes      # 真正执行（先改名再归档，一次操作记录）
qorg undo  --last                    # 整体回滚
qorg serve --data /data --port 8080  # WebUI
```

### 6.2 CLI 与 Web 的关系

同一套核心库的两个薄壳。**Web 不做任何 CLI 做不到的事**；Web 的价值是预览表、
筛选（按状态/省份/城市/失败原因）、勾选子集执行。这样保证：核心可测、行为一致、
二期 App 只需再写第三个壳。

### 6.3 目录与输出模式

- 默认**原地整理**：`<源目录>/<省>/<市>/<新文件名>`。
- `--output DIR` 统一输出到另一个根目录（保留原始文件不动，配合 `--move`/`--copy`）。
- `--copy` 模式复制而非移动（原目录保持原样，适合先试水）。

### 6.4 无 GPS / 无法解析的文件

默认**不动它们**，只出现在报告的「未处理」分组里，给出原因（无 GPS、坐标在境外、
时间缺失、目标冲突）。可选 `--move-unlocated` 统一收进 `<源目录>/未定位/`，**不重命名**。
理由：错改名比不改名代价高得多。

## 7. 架构

### 7.1 模块划分（`src/quantum_organizer/`）

```
core/
  models.py      MediaItem / ScanReport / PlanItem / OpRecord（dataclass，可 JSON 序列化）
  metadata.py    MediaExtractor：ffprobe → ffmpeg 字幕(DJI) → exiftool；并发受控
  geocode.py     Geocoder：内嵌 quantum-locator 精确解析 → 外部 HTTP → 城市中心点兜底
  naming.py      命名规约的唯一真源：构建文件名、解析既有后缀、日期格式化
  organize.py    规划与执行：改名 + 归档 + 冲突消解 + 幂等
  history.py     SQLite 操作日志与撤销（一次操作 = 一条记录，含多步）
  pipeline.py    scan() / plan() / apply() / undo() 的编排，唯一的对外门面
data/            （空；行政数据由 quantum-locator 包提供）
cli.py           argparse/typer 命令：scan / apply / undo / serve / doctor
web/             FastAPI + SSE + 静态前端（Vue 3 构建产物）
```

依赖方向严格单向：`web`/`cli` → `pipeline` → {metadata, geocode, naming, organize, history} → `models`。
`core` 下任何模块不得 import `streamlit`/`fastapi`/`typer`。

### 7.2 数据模型

```python
MediaItem:   path, size, mtime, kind(image|video|audio), shoot_time(YYYYMMDD|None),
             time_source(exif|gps|filename|mtime), lat, lon, gps_source(ffprobe|subtitle|exiftool),
             province, city, geo_source(exact|remote|estimate|none), status, reason
PlanItem:    item, target_path, conflict(str|None), decision(rename|keep|move|skip)
OpRecord:    id, started_at, finished_at, kind, root, options_json, status, steps[]
```

`ScanReport` / `PlanItem` 全部可序列化为 JSON，写 `--json` 输出，供二期 App 和其它
工具消费（这是跨端契约的一部分）。

### 7.3 流水线阶段

1. **enumerate**：按扩展名收集文件（`--recursive` 默认开）。
2. **extract**：`ThreadPoolExecutor(max_workers=8)` 并发提取元数据；每文件结果带
   `(size, mtime)` 指纹，写入扫描缓存，重跑时命中即跳过（这是"只读一遍"的实现）。
3. **geocode**：对唯一坐标去重后查询（同一机位几百张照片只查一次），批量接口优先。
4. **plan**：naming 生成目标名，organize 计算目标路径并检查冲突，产出 `PlanItem[]`。
5. **apply**：先改名、再移动（两步都进同一条 OpRecord），逐条落盘后写日志。
6. **report**：JSON + 终端表格 / Web 预览表。

### 7.4 命名规约（单一真源 `naming.py`）

- 目标格式：`<stem>_<省>_<市>_<YYMMDD><ext>`，例如
  `IMG_1234_江苏_南京_240815.jpg`、`DJI_0189_江苏_南京_210921.mp4`。
- 省市清洗：去掉「省/市/自治区/自治州/地区/盟」后缀；直辖市 city 取同省名
  （沿用现有 `_clean_province` / `_clean_city` 规则）。
- **幂等**：若 stem 已匹配 `(.+)_(省)_(市)_(\d{6})$`，先剥掉旧后缀再追加新后缀；
  绝不允许叠加。这是现有 classifier 正则的已知隐患，必须在 naming 层统一处理。
- 日期来源优先级：EXIF `DateTimeOriginal`（本地时间）→ 视频 `creation_time` →
  文件名里已有的 6 位日期 → 文件 mtime（报告里标注 `time_source=mtime`）。
  v0.1 不做时区推断，已知限制写进 README（跨午夜可能差一天）。
- 长度与字符：目标名长度上限 200 字节；非法字符（Windows 保留字符）替换为 `-`。

### 7.5 历史与撤销

- 状态目录 `QORG_STATE_DIR`，默认 `~/.local/state/quantum-organizer`，Docker 里挂 `/state`。
  **不往用户的素材目录里写数据库**（现有实现会把 `.renamer_history.db` 写进素材目录）。
- 表：`operations(id, started_at, finished_at, kind, root, options_json, status)`、
  `steps(op_id, seq, action(rename|move|copy), src, dst, status, error)`。
- 撤销 = 按 `seq` 逆序回滚 steps（先移回、再改回原名），并在同一事务里标记 `undone`。
- 撤销前校验目标文件仍在、内容大小一致；不一致则该步标记 `conflict` 并**停下**报告，
  不静默跳过。

### 7.6 冲突与安全规则

- 目标已存在 → 追加 `_2`、`_3`……直到不冲突（记录在 steps 里，撤销可逆）。
- 禁止跨设备移动（先判断 `st_dev`，跨设备自动降级为 copy+delete 并在报告标注）。
- 拒绝处理符号链接；拒绝 `..` 逃逸；所有路径 `resolve()` 后必须在 root 内。
- 执行前对每个目标做可写性检查；任一失败则整批中止（宁可全不改）。
- 保留 mtime，图片额外可选保留 atime（默认不改）。

## 8. quantum-locator 拆分为独立项目

### 8.1 仓库与发布物

独立仓库 `quantum-locator`（保留现有名字，独立维护）：

- Python 包 `quantum-locator`：`CityLocator.query(lon, lat, need_gcj02_convert=True)` + 批量，
  随包携带 `china_cities.geojson`（唯一数据源，3.7 MB）。
- FastAPI 服务 `quantum-locator-server`（现有端点保持兼容）+ 独立镜像
  `ghcr.io/<org>/quantum-locator`。
- 自己的测试、CI、版本号、CHANGELOG。
- 版本化数据工件：发布时附 `china_cities.geojson` + `sha256`，给二期 App 用。

### 8.2 主产品如何用它

`quantum-organizer` 把 `quantum-locator` 作为**普通 pip 依赖内嵌**（同进程加载，不走 HTTP）：

- 单镜像、单容器，用户不需要额外起服务 —— 这是"开箱即用"的前提。
- 需要独立服务/共享/换数据源时，设 `QORG_GEOCODER_URL=http://host:8899`
  即切换到远程模式，此时行为与现有 renamer 一致。
- 解析来源在报告里标注：`geo_source = exact | remote | estimate | none`。

### 8.3 必须修的坐标与数据问题

1. `need_gcj02_convert` 默认 **true**（EXIF GPS 是 WGS84，geojson 是 GCJ02）；
   坐标落在境外时跳过转换，直接判为「境外 → 未定位」。
2. **层级规则**（实测数据：363 个 city 级、112 个 district 级、1 个 province 级＝台湾省；
   district 的 `parent.adcode` 只有 110000/120000/310000/500000（直辖市）与 810000/820000（港澳））：
   命中 district 级时，省由 `adcode[:2]` 经 `PROVINCE_MAP` 得到，**第二级就是该区的名字**
   ——`北京/东城区`、`上海/浦东新区`、`香港/中西区`。文档约定：第二级在直辖市与港澳表示
   「所在区」，在其他省表示「市」；分类器、App、下游工具一律按「省=第一段、第二级=最后一段」
   取层级，**不依赖第二级的语义**。这与现有素材库的既有命名一致，不制造新旧两套格式。
3. 命中 province 级（台湾省）时**绝不猜市名**：判为「未定位」并标注
   `reason=needs_city_level_data`。台湾 22 县市的边界数据在 v0.2 补入 `quantum-locator`，
   补齐后自动产出 `台湾_台北`、`台湾_新竹`。同一原则适用于任何"只有省级多边形"的地区：
   宁可不动，也不把台北标成"台湾"。
4. **多边形简化容差**：现有 `simplify_tolerance=0.01`（约 1.1 km）会把城市边界向内收缩，
   边界附近的点被判为「未知区域」。新实现容差取 `0.001`（约 110 m），并对边界附近的
   不确定点（距边界 < 200 m）在报告里标注 `geo_boundary=true`，不静默改判。
5. 现有端点的 `formatted_name` 是 `省-市`；包内 API 改为直接返回结构化
   `(province, city, adcode, level)`，避免字符串再解析。

### 8.4 数据更新

行政数据更新只发生在 `quantum-locator` 仓库；`quantum-organizer` 升级依赖版本即获得新数据。
不使用 git submodule（避免用户 clone 后还要初始化子模块）。

## 9. 仓库结构

```
quantum-organizer/
├── src/quantum_organizer/{core,web,cli.py}
├── frontend/                 # Vue 3 + Vite，构建产物进 src/quantum_organizer/web/static
├── tests/{unit,integration,fixtures}
├── docs/{superpowers/specs,rules/naming.md,deploy.md}
├── .github/workflows/{ci.yml,release.yml}
├── Dockerfile  docker-compose.yml  Makefile  pyproject.toml
├── README.md  README_CN.md  LICENSE(MIT)  CONTRIBUTING.md  CHANGELOG.md
```

`docs/rules/naming.md` 是给二期 App 和第三方实现的**唯一规则来源**，与
`naming.py` 的黄金用例同目录。

## 10. 部署

- **源码运行**：Python 3.12+，`pip install -e .`，`qorg serve`；系统需 ffmpeg + exiftool
  （`doctor` 子命令检查并给出安装指引）。
- **Docker（推荐）**：多阶段构建（Node 构建前端 → slim 后端 + ffmpeg + exiftool），
  单个镜像，`/data` 素材、`/state` 状态。默认 `CMD ["qorg","serve","--data","/data"]`。
- **compose**：一份 `docker-compose.yml`，只起一个服务；标注可选启用独立
  `quantum-locator` 服务（社区版/多用户部署）。
- 健康检查 `/healthz`，镜像带 `HEALTHCHECK`。

## 11. 测试与 CI

- 单测：naming（含幂等/直辖市/非法字符）、geocode（WGS84→GCJ02、境外、边界城市）、
  organize（冲突、跨设备、路径逃逸）、history（撤销顺序、冲突中止）。
- 集成：对真实素材目录跑完整流水线并断言目录树（用 `media-renamer/data/test_origin`
  与 `DJI_0189.mp4` 的裁剪样本，体积控制在 <20 MB 进仓库）。
- 黄金用例：`tests/fixtures/naming_cases.json`（输入文件名 + 元数据 → 期望输出），
  二期 Dart 实现必须跑同一份用例。
- CI：ruff + mypy + pytest（3.12/3.13）+ docker build；release 推 ghcr 多架构。

## 12. 里程碑

| 阶段 | 内容 | 验收 |
|---|---|---|
| M1 | core：metadata/naming/geocode/organize/history + pipeline + CLI | 命令行在真实目录跑通 scan/apply/undo，重跑不叠加后缀 |
| M2 | WebUI：预览表、筛选、勾选执行、SSE 进度、撤销 | 浏览器完成一次完整操作并撤销成功 |
| M3 | 打包：Dockerfile/compose/doctor/文档双语 | 一条 `docker run` 可用；README 的每条命令都实测过 |
| M4 | 回归与发布：真实脏目录、跨设备、境外素材、CI 绿灯、v0.1 tag | 发布说明 + 镜像 |
| v0.2 | 台湾 22 县市边界数据、时区推断、境外数据源、性能、Flutter App | 另立设计文档 |

## 13. 二期 App 的契约（现在就要定，避免漂移）

- App 必须实现的规则只有三件事：解析文件名/EXIF → 点面判断得省市 → 生成目标名。
  三者都由 `docs/rules/naming.md` + `tests/fixtures/naming_cases.json` 定义。
- 行政数据：从 `quantum-locator` release 取 `china_cities.geojson` + sha256，不自行克隆。
- 输出格式：App 扫描结果必须能序列化成与 `ScanReport` 相同的 JSON 结构。
- App 端限制在 README 明确写出（相册内不能建嵌套目录、视频 GPS 解析需内置 ffmpeg）。

## 14. 迁移计划

1. 在 `city_locator/` 基础上建 `quantum-locator` 仓库：加 pyproject、测试、CI，代码基本不动。
2. 建 `quantum-organizer` 仓库：先把 `metadata`/`naming`/`organize`/`history` 从现有两个项目移植并
   补测试（移植时同步修：GCJ02 默认值、幂等后缀、状态库移出素材目录、Streamlit 解耦）。
3. 真实素材回归通过后，删除 `renamer/`、`classfier/`、`media-renamer/`、`media-classifier/`
   四个目录（`media-video-cut-webui/` 与本产品无关，保留原地）。
4. 旧目录里的 `data/test_origin`、`DJI_0189.mp4` 裁剪样本迁入新仓库 fixtures。

## 15. 我做的判断（请确认，写错了现在改最便宜）

1. 产品名 **quantum-organizer**（`pip install quantum-organizer`、CLI `qorg`、
   Python 包 `quantum_organizer`、镜像 `ghcr.io/<org>/quantum-organizer`），
   中文名「Quantum Organizer 素材整理」。名字未查重，首次发布前可改。
2. 中国大陆优先，境外素材落「未定位」，v0.1 不做全球数据源。
3. 默认**原地整理**，同时提供 `--output` / `--copy`。
4. 无 GPS 的文件默认不动、只报告；`--move-unlocated` 才收进「未定位」且不改名。
5. 界面用 **FastAPI + Vue 3**，弃用 Streamlit（理由见约束 4）。
6. `quantum-locator` 以 **pip 依赖内嵌**，不默认起独立容器；远程模式由环境变量切换。
7. **Python 3.12** 基线（源码与镜像统一 3.12，CI 覆盖 3.12/3.13），单镜像单端口 8080，
   状态目录 `/state` 不写进素材目录。
8. MIT 许可 + 中英双语 README/界面。
9. **直辖市/港澳沿用现有做法**：第二级写所在区（`北京_东城区`、`香港_中西区`），
   不改成 `北京_北京`，也不缩成单级。文档约定第二级语义，下游只按位置取层级。
10. **台湾**：市名必须是真实市名，v0.1 数据不足故落「未定位」；v0.2 补 22 县市边界后
    产出 `台湾_台北`。不采用"市取省名"的猜测规则。

## 16. 留给实现者的空间

- Web 预览表的具体交互（虚拟滚动 vs 分页）、Vue 组件组织。
- 并发度默认值、扫描缓存的具体格式（JSON vs sqlite）。
- `--json` 输出的字段命名细节（只要保留 `PlanItem` 的核心字段）。
- 日志格式、错误码划分。
- 具体测试夹具的裁剪方式。

## 17. 实现审查后的补充决定

独立工程师按本文档试拟计划，提出五个必须回答的问题。全部由本文档拍板如下，
不再留给实现者猜：

1. **单次操作规模上限：10 万文件。** 超过上限直接拒绝并提示分批。扫描结果
   **落盘**（`scans` / `scan_items` 两张表），内存只保留当前页；Web 端分页 +
   SSE 进度，`--json` 输出按页写 JSONL。这样 pipeline 门面签名、Web API、SSE 粒度
   都不依赖"全部驻留内存"。
2. **quantum-locator 的依赖方式：** M1 期间用本地 path 依赖
   （`pip install -e ../quantum-locator`，Docker 构建用 `--build-arg` 传上下文），
   **v0.1 发布前**发布 `quantum-locator 0.1.0` 到 PyPI；此后 `quantum-organizer` 依赖
   `quantum-locator>=0.1,<1`，Dockerfile 里 `pip install quantum-locator==0.1.0`。
   M1 不等发版，M3 打包前必须发版。
3. **区级/省级多边形归属：** 见 8.3 第 2、3 条（直辖市/港澳第二级写所在区；台湾无市级数据
   时落未定位），已在数据层定死。geocode 单测覆盖：北京（东城区）、上海、香港、澳门、
   台湾（未定位）五个用例。
4. **城市中心点最近邻估算：默认关闭**（`--allow-estimate` 显式开启）。理由：数十公里
   误差与"错改名代价高"的反面目标冲突；默认失败即「未定位」。开启时报告里
   `geo_source=estimate` 并强制在 Web 预览表标红。
5. **scan 与 apply 之间持久化：** `scan` 产出一个 `plan_id`（含 root、options 指纹、
   时间戳）并落盘；`apply` 默认读该 root 的最新 plan，指纹不符时报错要求重扫；
   `--plan <id>` 可显式指定。WebUI 的"筛选 + 勾选子集执行"就是对同一 plan 的子集应用，
   不会重扫。
