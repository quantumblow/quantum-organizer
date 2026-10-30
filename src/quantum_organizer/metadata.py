"""Metadata extraction: ffprobe → DJI subtitle track → exiftool.

Every external tool is optional; a missing tool just skips its stage. A file that
neither ffprobe nor exiftool can parse is reported ``INVALID/unreadable`` instead of
raising, so one corrupt file cannot abort a batch.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from quantum_organizer import naming
from quantum_organizer.models import MediaItem, Status

IMAGE_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".dng",
    ".raw",
    ".tiff",
    ".tif",
    ".heic",
    ".cr2",
    ".nef",
    ".arw",
    ".gif",
    ".bmp",
    ".webp",
}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v", ".3gp", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"}
ALL_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS

_TIME_KEYS = (
    "creation_time",
    "date",
    "DateTimeOriginal",
    "MediaCreateDate",
    "TrackCreateDate",
    "creation_date",
    "CreateDate",
    "ModifyDate",
)

_GPS_PAIR_RE = re.compile(r"([+-]?\d+\.?\d*)\s*([+-]?\d+\.?\d*)")
_SUBTITLE_GPS_RE = re.compile(r"GPS\s*\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*\d+\s*\)")
_FILENAME_DATE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return "image"


class MediaExtractor:
    """Extract shoot time and GPS from one media file."""

    def __init__(
        self,
        ffprobe: str | None = None,
        ffmpeg: str | None = None,
        exiftool: str | None = None,
    ) -> None:
        self.ffprobe = ffprobe if ffprobe is not None else shutil.which("ffprobe")
        self.ffmpeg = ffmpeg if ffmpeg is not None else shutil.which("ffmpeg")
        self.exiftool = exiftool if exiftool is not None else shutil.which("exiftool")

    # ------------------------------------------------------------------ extract

    def extract(self, path: Path) -> MediaItem:
        path = Path(path)
        stat = path.stat()
        item = MediaItem(
            path=str(path.absolute()),
            size=stat.st_size,
            mtime=stat.st_mtime,
            kind=kind_of(path),
        )

        probe = self._ffprobe(path) if self.ffprobe else None
        exif = self._exiftool(path) if self.exiftool else None

        if probe is None and exif is None:
            item.status = Status.INVALID
            item.reason = "unreadable"
            return item

        # 扩展名是图片/视频，但内容其实是文本（改名后残缺、误放）：exiftool 会给出 MIMEType。
        mime = str((exif or {}).get("MIMEType", ""))
        if mime.startswith("text/") or (exif or {}).get("FileType") in {"TXT", "HTML", "XML"}:
            item.status = Status.INVALID
            item.reason = "unreadable"
            return item

        raw_time = self._pick_time(probe, exif)
        if raw_time:
            item.shoot_time = naming.format_date(raw_time.value)
            item.time_source = raw_time.source

        lat, lon, gps_source = self._pick_gps(path, probe, exif, item.kind)
        if lat is not None and lon is not None:
            item.lat, item.lon, item.gps_source = lat, lon, gps_source

        if item.shoot_time is None:
            from_name = _FILENAME_DATE_RE.search(path.stem)
            if from_name and naming.format_date(from_name.group(1)):
                item.shoot_time = naming.format_date(from_name.group(1))
                item.time_source = "filename"
            else:
                item.shoot_time = naming.format_date(
                    datetime.datetime.fromtimestamp(item.mtime).strftime("%Y:%m:%d")
                )
                item.time_source = "mtime"

        if item.lat is None:
            item.reason = "no_gps"
        return item

    # ------------------------------------------------------------------ helpers

    class _Stamp:
        __slots__ = ("source", "value")

        def __init__(self, value: str, source: str) -> None:
            self.value = value
            self.source = source

    def _pick_time(self, probe: dict | None, exif: dict | None) -> _Stamp | None:
        if exif:
            for key in ("DateTimeOriginal", "CreateDate", "ModifyDate"):
                value = exif.get(key)
                if isinstance(value, str) and value:
                    return self._Stamp(value, "exif")
        if probe:
            for key in _TIME_KEYS:
                value = probe.get("format", {}).get("tags", {}).get(key)
                if isinstance(value, str) and value:
                    return self._Stamp(value, "video")
            for stream in probe.get("streams", []):
                tags = stream.get("tags") or {}
                for key in _TIME_KEYS:
                    value = tags.get(key)
                    if isinstance(value, str) and value:
                        return self._Stamp(value, "video")
        return None

    def _pick_gps(
        self,
        path: Path,
        probe: dict | None,
        exif: dict | None,
        kind: str,
    ) -> tuple[float | None, float | None, str | None]:
        if probe:
            tags = probe.get("format", {}).get("tags") or {}
            if "location" in tags and (pair := self._parse_location(tags["location"])):
                return pair[0], pair[1], "ffprobe"
            for stream in probe.get("streams", []):
                tags = stream.get("tags") or {}
                if "location" in tags:
                    pair = self._parse_location(tags["location"])
                    if pair:
                        return pair[0], pair[1], "ffprobe"

        if kind in ("video", "audio"):
            pair = self._subtitle_gps(path)
            if pair:
                return pair[0], pair[1], "subtitle"

        if exif:
            lat, lon = exif.get("GPSLatitude"), exif.get("GPSLongitude")
            if (
                isinstance(lat, (int, float))
                and isinstance(lon, (int, float))
                and (lat, lon) != (0, 0)
            ):
                return float(lat), float(lon), "exiftool"
        return None, None, None

    @staticmethod
    def _parse_location(raw: str) -> tuple[float, float] | None:
        cleaned = str(raw).strip().replace("/", "")
        match = _GPS_PAIR_RE.search(cleaned)
        if not match:
            return None
        try:
            lat = float(match.group(1))
            lon = float(match.group(2))
        except ValueError:
            return None
        if abs(lat) <= 90 and abs(lon) <= 180 and (lat != 0.0 or lon != 0.0):
            return lat, lon
        return None

    def _ffprobe(self, path: Path) -> dict | None:
        tool = self.ffprobe
        if not tool:
            return None
        try:
            result = subprocess.run(
                [
                    tool,
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return None
            return json.loads(result.stdout)
        except Exception:
            return None

    def _exiftool(self, path: Path) -> dict | None:
        tool = self.exiftool
        if not tool:
            return None
        try:
            result = subprocess.run(
                [tool, "-j", "-n", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            if not data:
                return None
            return data[0]
        except Exception:
            return None

    def _subtitle_gps(self, path: Path) -> tuple[float, float] | None:
        tool = self.ffmpeg
        if not tool:
            return None
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as tmp:
                tmp_path = tmp.name
            subprocess.run(
                [
                    tool,
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:s:0",
                    "-f",
                    "srt",
                    "-y",
                    tmp_path,
                ],
                capture_output=True,
                timeout=60,
            )
            if not os.path.exists(tmp_path):
                return None
            content = Path(tmp_path).read_text("utf-8", errors="ignore")
            for lon_str, lat_str in _SUBTITLE_GPS_RE.findall(content):
                if lon_str.strip().lower() in ("n/a", "na") or lat_str.strip().lower() in (
                    "n/a",
                    "na",
                ):
                    continue
                try:
                    lon = float(lon_str)
                    lat = float(lat_str)
                except ValueError:
                    continue
                if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0.0, 0.0):
                    return lat, lon
        except Exception:
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        return None
