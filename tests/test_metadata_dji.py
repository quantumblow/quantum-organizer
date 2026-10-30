"""Tests for DJI subtitle-track GPS extraction."""

from pathlib import Path
from subprocess import run

from quantum_organizer.metadata import MediaExtractor

FX = Path("tests/fixtures/media")


def test_dji_subtitle_gps():
    m = MediaExtractor().extract(FX / "dji_gps.mp4")
    assert m.gps_source == "subtitle"
    assert (round(m.lat, 4), round(m.lon, 4)) == (32.0603, 118.7969)


def test_zero_coordinates_are_discarded(tmp_path):
    srt = tmp_path / "zero.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nGPS (0, 0, 0)\n", encoding="utf-8")
    out = tmp_path / "zero.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:d=1",
            "-i",
            str(srt),
            "-map",
            "0:v",
            "-map",
            "1:s",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:s",
            "mov_text",
            "-t",
            "1",
            str(out),
        ],
        check=True,
    )
    m = MediaExtractor().extract(out)
    assert m.lat is None and m.gps_source is None
