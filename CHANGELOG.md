# Changelog

## 0.1.0 (unreleased)

- One pipeline: metadata → province/city → rename → file under `province/second-level`.
- CLI (`scan`/`apply`/`undo`/`serve`/`doctor`) and a Vue WebUI sharing one core.
- Preview by default; `apply` requires `--yes`; every apply is one undoable operation.
- Photos (EXIF), videos (ffprobe) and DJI subtitle-track GPS.
- Offline locator dependency, WGS84→GCJ02 conversion, district-level results for municipalities.
- `launch.sh` grants the whole `$HOME` by default (override with `QORG_DATA_ROOTS`), and the
  out-of-root 400 explains the difference between mounting and granting access.
- Renaming is optional: `--rename/--no-rename` plus `--name-parts province,city,time` (any
  combination) in the CLI, a switch + three checkboxes in the WebUI, remembered locally.
  Folders are still created when renaming is off, and re-runs never stack suffixes.
- Atomic move per file; conflicts never overwrite; undo prunes created directories.
- WebUI takes several media roots (`--data` repeatable, `QORG_DATA_ROOTS`) and ships a folder
  browser, so any folder under a declared root can be scanned without restarting the container.
  Defaults to `~/Pictures` and `~/Videos`; paths outside the declared roots are refused.
