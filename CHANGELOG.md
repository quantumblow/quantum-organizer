# Changelog

## 0.1.0 (unreleased)

- One pipeline: metadata → province/city → rename → file under `province/second-level`.
- CLI (`scan`/`apply`/`undo`/`serve`/`doctor`) and a Vue WebUI sharing one core.
- Preview by default; `apply` requires `--yes`; every apply is one undoable operation.
- Photos (EXIF), videos (ffprobe) and DJI subtitle-track GPS.
- Offline locator dependency, WGS84→GCJ02 conversion, district-level results for municipalities.
- Atomic move per file; conflicts never overwrite; undo prunes created directories.
