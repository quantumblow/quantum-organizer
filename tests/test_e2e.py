"""End-to-end: a messy folder becomes a sorted tree, then goes back unchanged."""

import shutil
from pathlib import Path

from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline

FX = Path("tests/fixtures/media")


def test_dirty_folder_to_sorted_tree_and_back(tmp_path):
    media = tmp_path / "乱文件夹"
    media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "IMG_0001.jpg")
    shutil.copy(FX / "photo_gps.jpg", media / "IMG_0001.JPG")
    shutil.copy(FX / "photo_nogps.jpg", media / "IMG_0002.jpg")
    shutil.copy(FX / "dji_gps.mp4", media / "DJI_0001.mp4")
    shutil.copy(FX / "broken.jpg", media / "坏文件.jpg")
    shutil.copy(FX / "photo_gps.jpg", media / "IMG_0001_江苏_南京_140815.jpg")  # 已命名、同机位

    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    record = p.apply(plan, options=PlanOptions(root=str(media)))

    names = sorted(x.name for x in (media / "江苏" / "南京").iterdir())
    assert names and all("江苏_南京" in n for n in names)
    assert not any(n.count("江苏") > 1 for n in names), names  # 幂等，不叠加后缀
    assert (media / "IMG_0002.jpg").exists()  # 无 GPS 不动
    assert (media / "坏文件.jpg").exists()  # 坏文件不动
    assert list((media / "江苏" / "南京").glob("DJI_0001_江苏_南京_*.mp4"))

    result = p.undo(op_id=record.op_id)
    assert result.ok, result.conflicts
    assert sorted(x.name for x in media.iterdir()) == sorted(
        [
            "IMG_0001.jpg",
            "IMG_0001.JPG",
            "IMG_0002.jpg",
            "DJI_0001.mp4",
            "坏文件.jpg",
            "IMG_0001_江苏_南京_140815.jpg",
        ]
    )
