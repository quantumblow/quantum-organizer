# quantum-organizer

Folder organizer for photographers, phone shooters, DJI drone and action-camera users:
point it at a messy folder and it files each photo/video under `province/city`
(resolved from GPS) and renames it to `name_province_city_YYMMDD.ext`.

Preview before anything moves; undo everything afterwards.

- Offline: the locator is embedded (`quantum-locator`) — no network, no map API key.
- Photos via EXIF, videos via ffprobe, DJI videos via their subtitle-track GPS.
- A scan reads each file once; results are cached.
- One image, one command, one UI; CLI and WebUI share the same core.

## Quick start (Docker)

```bash
docker run --rm -p 8080:8080 \
  -v /path/to/media:/data \
  -v qorg-state:/state \
  ghcr.io/<org>/quantum-organizer
```

Open `http://localhost:8080`, enter `/data/2024-trip`, scan, review the table, apply, undo if needed.

The image runs as uid/gid **1000**, so files it writes stay owned by you on the host instead of
root. If your ids differ, pass `--user "$(id -u):$(id -g)"` and make sure `/state` is writable by
that uid (the named volume inherits ownership 1000 from the image).

### Pointing it at your own folders

Paths inside the container are the host paths, so mount them at the same location:

```bash
# Mount the whole home directory once; then browse to any folder in the WebUI, no restart needed
docker run --rm -p 8080:8080 \
  -v "$HOME:$HOME" \
  -v qorg-state:/state \
  -e QORG_DATA_ROOTS="$HOME/Pictures:$HOME/Videos" \
  ghcr.io/<org>/quantum-organizer
```

Mounting only the albums you care about works too, as long as the path stays identical:

```bash
docker run --rm -p 8080:8080 \
  -v "$HOME/Pictures:$HOME/Pictures" \
  -v "$HOME/Videos:$HOME/Videos" \
  -v qorg-state:/state \
  ghcr.io/<org>/quantum-organizer
```

The WebUI can only touch roots you declare; anything else (including symlinks pointing out of a root)
is rejected:

- `qorg serve` with no arguments defaults to `~/Pictures` and `~/Videos` (falls back to `/data` in the image)
- several roots: `--data ~/Pictures --data /mnt/nas/DCIM`, or `QORG_DATA_ROOTS="/a:/b"`
- **Browse…** lists folders on demand and reports unreadable ones instead of failing

```bash
docker run --rm -v /path/to/media:/data quantum-organizer:latest scan /data/2024-trip [--copy] [-o DIR]
docker run --rm -v /path/to/media:/data quantum-organizer:latest apply /data/2024-trip --yes
docker run --rm -v /path/to/media:/data quantum-organizer:latest undo --root /data/2024-trip
```

## From source

Python 3.12 + `ffmpeg` + `exiftool` (`apt install ffmpeg libimage-exiftool-perl`,
or `brew install ffmpeg exiftool`):

```bash
git clone https://github.com/<org>/quantum-locator.git
git clone https://github.com/<org>/quantum-organizer.git
cd quantum-organizer
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ../quantum-locator && pip install -e .

qorg doctor
qorg scan  ~/Pictures/messy
qorg apply ~/Pictures/messy --yes
qorg undo  --root ~/Pictures/messy
qorg serve --data ~/Pictures --port 8080
```

## Building the image

The image needs `quantum-locator`. Either build its wheel locally (no PyPI, no npm):

```bash
cd ../quantum-locator && python -m build --wheel -o ../quantum-organizer/docker/wheels
cd ../quantum-organizer && docker build -t quantum-organizer:dev .
```

or `docker build .` once the locator is on PyPI. Behind a proxy:

```bash
docker build --network=host \
  --build-arg HTTP_PROXY=http://127.0.0.1:7897 \
  --build-arg HTTPS_PROXY=http://127.0.0.1:7897 \
  -t quantum-organizer:dev .
```

## Rules and limitations

See [`docs/rules/naming.md`](docs/rules/naming.md) — the single source of truth for both this
Python implementation and the planned mobile app.

- Municipalities and Hong Kong/Macau use the **district** as the second level (`北京/东城区`).
- Taiwan currently only has a province-level polygon: files land in "unlocated"
  (`reason=needs_city_level_data`) instead of guessing a city name.
- Coordinates outside China land in "unlocated" (`reason=abroad`).
- Files without GPS, or unreadable files, are left untouched and reported.
- State (plans, history, scan cache) lives in `QORG_STATE_DIR` (default
  `~/.local/state/quantum-organizer`, `/state` in the image) — never inside the media folders.
- No timezone inference in v0.1: video `creation_time` is usually UTC, so a midnight-crossing
  shoot can be off by a day; the report marks `time_source`.

## CI

Tests run on Python 3.12/3.13 with ruff + mypy; the docker job checks out
`quantumblow/quantum-locator`, builds its wheel locally and then the image, and smoke-tests
`qorg doctor` plus the locator import — so CI stays green before the locator is on PyPI.

## License

MIT.
