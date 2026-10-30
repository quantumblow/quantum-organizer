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

镜像默认以 uid/gid **1000** 运行，所以整理后的文件在宿主机上仍归你所有（不会变成 root）。
如果你的宿主机用户名 id 不是 1000，用 `--user "$(id -u):$(id -g)"` 覆盖；`/state` 卷需要该 uid 可写：
命名卷首次创建时会继承镜像里 1000 的属主，绑挂载目录则请先 `chown` 一次。

### 想扫你自己电脑上的任意目录

容器看到的路径就是宿主机路径，所以把目录按**同一条路径**挂进来最省事：

```bash
# 整份家目录挂进去，之后在 WebUI 里点「浏览…」想看哪个目录都行，不需要重启容器
docker run --rm -p 8080:8080 \
  -v "$HOME:$HOME" \
  -v qorg-state:/state \
  -e QORG_DATA_ROOTS="$HOME/Pictures:$HOME/Videos" \
  ghcr.io/<org>/quantum-organizer
```

只挂一两个相册也可以，路径保持一致就行（撤销记录里的路径才和你在宿主机看到的一样）：

```bash
docker run --rm -p 8080:8080 \
  -v "$HOME/Pictures:$HOME/Pictures" \
  -v "$HOME/Videos:$HOME/Videos" \
  -v qorg-state:/state \
  ghcr.io/<org>/quantum-organizer
```

WebUI 能碰的目录由你决定，服务端会拒绝根目录之外的路径（包括指向根外的符号链接）：

- 不给参数时，`qorg serve` 默认用 `~/Pictures` 和 `~/Videos`（存在则用，容器里都没有时退回 `/data`）
- 多个根：`--data ~/Pictures --data /mnt/nas/DCIM`，或环境变量 `QORG_DATA_ROOTS="/a:/b"`
- WebUI 的「浏览…」是按需列目录的，遇到没有读取权限的目录会提示换一个，不会让整次浏览失败

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
| `qorg scan ROOT --no-rename --name-parts province,city` | 同上，但只按目录归档、文件名原样 |
| `qorg apply ROOT --yes` | 执行该目录最新计划（沿用 scan 的选项），一条操作记录 |
| `qorg undo --root ROOT` | 逆序撤销最近一次操作 |
| `qorg serve [--data DIR]...` | 启动 WebUI（8080），`--data` 可重复，缺省是 `~/Pictures`、`~/Videos` |

`scan` 的开关决定这次整理的语义，并随计划一起存下来，`apply` 照着执行：
`--copy`（复制不移动）、`--output DIR`（统一输出）、`--move-unlocated`
（未定位文件收进 `未定位/`）、`--allow-estimate`（允许用城市中心点估算，默认关闭）。
`--rename/--no-rename`（默认开）决定是否给源文件补后缀，`--name-parts` 从
`province,city,time` 里挑段（默认三段全要，顺序固定；也可以写 `省,市`）。
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

## 命名与改名

归档目录（`<省>/<市>/`）始终会建；文件名后缀是可选的，WebUI 上有「重命名源文件」+
「省 / 市 / 时间」三个勾选框，界面会实时显示示例名，并记住你上次的选择（存在浏览器本地）：

| 勾选 | 结果 |
|---|---|
| 省 + 市 + 时间 | `IMG_1234_江苏_南京_140815.jpg` |
| 省 + 市 | `IMG_1234_江苏_南京.jpg` |
| 时间 | `IMG_1234_140815.jpg` |
| 不勾（或关掉重命名） | `IMG_1234.jpg`，只按目录归档 |

重复跑不会叠后缀；从三段切到两段会把旧的时间段去掉。规则细节见 `docs/rules/naming.md`。

## 常见问题

**`attempt to write a readonly database`**

状态目录（容器里是 `/state`）不可写。最常见的原因是那个 Docker 卷是**老镜像（root 运行）**
创建的，文件属主是 root，而现在的镜像以 uid 1000 运行。`qorg serve` 启动时会先探测一次，
不通过就直接拒绝启动并打印修复命令；也可以用 `qorg doctor` 看 `state_writable` 一行。

修复（保留已有计划和历史）：

```bash
docker run --rm -v qorg-state:/state python:3.12-slim chown -R 1000:1000 /state
```

或者换一个新卷。绑挂载目录则是 `sudo chown -R 1000:1000 你的状态目录`。

**扫出来的文件全是 `keep` / 不移动**

说明这些文件里没有 GPS：无人机视频的 GPS 在字幕轨（DJI）或元数据里，剪辑/转码后的导出
通常会把轨道丢干净。用 `ffprobe -show_streams` 只看到 video/audio 两个流，就属于这种情况。

## 构建镜像

镜像需要 `quantum-locator`，两条路选一条：

```bash
# A. 本地 wheel（不需要发布到 PyPI，也不需要 npm）
cd ../quantum-locator && python -m build --wheel -o ../quantum-organizer/docker/wheels
cd ../quantum-organizer && docker build -t quantum-organizer:dev .

# B. 已发布到 PyPI 后直接构建
docker build -t quantum-organizer:dev .
```

本机若需要代理才能访问 apt / PyPI，构建时把代理传进去（不要让容器用 `172.17.0.1`）：

```bash
docker build --network=host \
  --build-arg HTTP_PROXY=http://127.0.0.1:7897 \
  --build-arg HTTPS_PROXY=http://127.0.0.1:7897 \
  -t quantum-organizer:dev .
```

## 部署

- 单镜像单端口 8080，素材目录按需挂载（`/data` 只是缺省根），`/state` 放状态，`HEALTHCHECK` 打 `/healthz`。
- `docker compose up -d`（见 `docker-compose.yml`），可用 `MEDIA_DIR` 指定素材目录。
- 想独立维护坐标服务：启动 `quantum-locator` 容器并设 `QORG_GEOCODER_URL`。

## 开发

```bash
make test     # pytest
make lint     # ruff + mypy
make fmt      # ruff format
```

CI：Python 3.12/3.13 矩阵跑 ruff + mypy + pytest；docker job 会 checkout `quantumblow/quantum-locator`、本地打 wheel 再建镜像，并对镜像跑一次 `qorg doctor` 与 locator 导入冒烟——因此上游 locator 还没上 PyPI 时 CI 也能绿。上游仓库目前私有，需要在
Settings → Secrets 里配置 `LOCATOR_REPO_TOKEN`（fine-grained PAT，对 quantum-locator 仅给 Contents: Read）。

## 许可

MIT。坐标与行政区数据由 [quantum-locator](https://github.com/<org>/quantum-locator) 提供
（源自阿里 DataV 的 GCJ02 行政区划）。
