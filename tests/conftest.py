import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prancha.testvideo import make_video  # noqa: E402


@pytest.fixture(scope="session")
def videos(tmp_path_factory):
    d = tmp_path_factory.mktemp("videos")
    out = {}
    specs = {
        "mp4": ("libx264", "yuv420p"),
        "avi": ("mpeg4", "yuv420p"),
        "mkv": ("mjpeg", "yuvj420p"),
        "webm": ("libvpx-vp9", "yuv420p"),
        "mov": ("libx264", "yuv420p"),
    }
    for ext, (codec, pix) in specs.items():
        p = str(d / f"teste.{ext}")
        make_video(p, seconds=65, fps=25, width=320, height=240, codec=codec, pix_fmt=pix)
        out[ext] = p
    long_hd = str(d / "hd.mp4")
    make_video(long_hd, seconds=125, fps=25, width=1280, height=720)
    out["hd"] = long_hd
    return out


@pytest.fixture
def workdir(tmp_path):
    d = tmp_path / "trabalho"
    d.mkdir()
    yield str(d)
    shutil.rmtree(d, ignore_errors=True)


def ffmpeg_exe():
    return shutil.which("ffmpeg")
