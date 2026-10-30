# quantum-organizer

Point it at a messy folder of photos and videos: it renames each file to
`<name>_<province>_<city>_<YYMMDD>.<ext>` and files it under `province/city/`,
with a preview before anything moves and one-command undo afterwards.

- CLI: `qorg scan`, `qorg apply`, `qorg undo`, `qorg serve`, `qorg doctor`
- WebUI on port 8080 (single Docker image)
- Metadata from ffprobe, DJI subtitle tracks and exiftool (photo/video GPS)
- Province/city from an embedded offline locator (`quantum-locator`) — no API key, no network

Licensed MIT.
