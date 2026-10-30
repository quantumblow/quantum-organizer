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

```bash
docker run --rm -v /path/to/media:/data quantum-organizer:latest scan /data/2024-trip
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

## License

MIT.
