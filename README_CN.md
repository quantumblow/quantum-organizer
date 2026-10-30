# quantum-organizer

给摄影师、普通拍照用户、DJI 无人机与运动相机用户用的**素材目录整理工具**：
指给它一个乱文件夹，它按 GPS 解析出的「省 / 市（区）」归档，并把文件名补成
`原名_省_第二级_YYMMDD`。执行前有预览，执行后可整体撤销。

- 离线：内置 `quantum-locator`，不联网、不需要地图 API Key。
- 图片走 EXIF，视频走 ffprobe，DJI 视频走字幕轨 GPS。
- 一次扫描只读一遍文件，扫描结果缓存。
- 一条命令一个镜像，CLI 和 WebUI 共用同一套核心。

## 快速开始（Docker）

```bash
docker run --rm -p 8080:8080 \
  -v /你的素材盘:/data \
  -v qorg-state:/state \
  ghcr.io/<org>/quantum-organizer
```

浏览器打开 `http://localhost:8080` → 填 `/data/2024旅行` → 扫描 → 看预览表 → 执行 → 需要时撤销。

命令行同样能跑（同一个镜像）：

```bash
docker run --rm -v /你的素材盘:/data quantum-organizer:latest scan /data/2024旅行
docker run --rm -v /你的素材盘:/data quantum-organizer:latest apply /data/2024旅行 --yes
docker run --rm -v /你的素材盘:/data quantum-organizer:latest undo --root /data/2024旅行
```

## 从源码运行

需要 Python 3.12、`ffmpeg`、`exiftool`：

```bash
sudo apt install ffmpeg libimage-exiftool-perl   # macOS: brew install ffmpeg exiftool

git clone https://github.com/<org>/quantum-locator.git
git clone https://github.com/<org>/quantum-organizer.git
cd quantum-organizer
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ../quantum-locator
pip install -e .

qorg doctor                      # 检查 ffmpeg / exiftool / locator / 状态目录
qorg scan  ~/Pictures/杂乱目录
qorg apply ~/Pictures/杂乱目录 --yes
qorg undo  --root ~/Pictures/杂乱目录
qorg serve --data ~/Pictures --port 8080
```

前端（只有改 UI 时需要）：

```bash
cd frontend && npm install && npm run build   # 产物写入 src/quantum_organizer/web/static
```

## 命令

| 命令 | 作用 |
|---|---|
| `qorg doctor` | 检查外部工具、locator 依赖、状态目录 |
| `qorg scan ROOT [--copy] [-o DIR] [--json out.json]` | 扫描并生成计划（不改文件） |
| `qorg apply ROOT --yes` | 执行该目录最新计划（沿用 scan 的选项），一条操作记录 |
| `qorg undo --root ROOT` | 逆序撤销最近一次操作 |
| `qorg serve --data DIR` | 启动 WebUI（8080） |

`scan` 的开关决定这次整理的语义，并随计划一起存下来，`apply` 照着执行：
`--copy`（复制不移动）、`--output DIR`（统一输出）、`--move-unlocated`
（未定位文件收进 `未定位/`）、`--allow-estimate`（允许用城市中心点估算，默认关闭）。
`apply` 另有 `--dry-run`（只演示）、`--yes`（确认）、`--select FILE`（只处理列表里的文件）。
计划里没有存下选项（老计划）时 `apply` 会直接拒绝，不会退回默认的移动语义。

退出码：`0` 成功、`1` 无可处理项、`2` 需要确认/计划缺失、`3` 部分失败。

## 规则与限制

完整规则见 [`docs/rules/naming.md`](docs/rules/naming.md)（这份文档也是二期手机 App 的实现依据）。

- 直辖市与港澳：第二级写**所在区**（`北京/东城区`、`香港/中西区`）。
- 台湾目前只有省级多边形，数据不足时落「未定位」（`reason=needs_city_level_data`），不猜市名；
  v0.2 补 22 县市边界后产出 `台湾_台北`。
- 境外坐标落「未定位」（`reason=abroad`）。
- 无 GPS / 不可读文件默认原地不动，只在报告里说明原因。
- 状态（计划、历史、扫描缓存）写在 `QORG_STATE_DIR`（默认 `~/.local/state/quantum-organizer`，
  镜像里是 `/state`），**绝不写进素材目录**。
- 时区不推断：视频 `creation_time` 常是 UTC，跨午夜可能差一天，报告里标 `time_source`。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `QORG_STATE_DIR` | `~/.local/state/quantum-organizer` | 计划/历史/缓存位置 |
| `QORG_GEOCODER_URL` | 空 | 设成 `http://host:8899` 改用外部 `quantum-locator` 服务 |

## 部署

- 单镜像单端口 8080，`/data` 素材、`/state` 状态，`HEALTHCHECK` 打 `/healthz`。
- `docker compose up -d`（见 `docker-compose.yml`），可用 `MEDIA_DIR` 指定素材目录。
- 想独立维护坐标服务：启动 `quantum-locator` 容器并设 `QORG_GEOCODER_URL`。

## 开发

```bash
make test     # pytest
make lint     # ruff + mypy
make fmt      # ruff format
```

CI：Python 3.12/3.13 矩阵跑 ruff + mypy + pytest，另跑一次 docker build。

## 许可

MIT。坐标与行政区数据由 [quantum-locator](https://github.com/<org>/quantum-locator) 提供
（源自阿里 DataV 的 GCJ02 行政区划）。
