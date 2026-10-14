"""Testes 1, 2, 3, 6 e 8 dos critérios de aceitação (núcleo de extração)."""

import os
import random
import subprocess

import pytest
from PIL import Image

from prancha.core.extraction import (Distribution, ExtractionRequest, Mode, extract_frames, grab_single,
                                     load_display_image, plan_times)
from prancha.core.hashing import sha256_file
from prancha.core.probe import VideoError, probe_video
from prancha.testvideo import read_frame_index

from .conftest import ffmpeg_exe

FPS = 25


def frame_index(rec):
    return read_frame_index(Image.open(rec.image_path))


@pytest.mark.parametrize("fmt", ["mp4", "avi", "mkv", "webm", "mov"])
def test_probe_formats(videos, fmt):
    info = probe_video(videos[fmt])
    assert info.duration == pytest.approx(65, abs=0.05)
    assert (info.width, info.height) == (320, 240)
    assert info.fps == pytest.approx(25)
    assert info.file_size == os.path.getsize(videos[fmt])
    assert info.modified is not None


@pytest.mark.parametrize("fmt", ["mp4", "avi", "mkv", "webm", "mov"])
def test_1_interval_10s(videos, fmt, workdir):
    info = probe_video(videos[fmt])
    req = ExtractionRequest(Mode.INTERVAL, 0, info.duration, interval=10)
    times = plan_times(req, info.duration)
    assert times == [0, 10, 20, 30, 40, 50, 60]
    res = extract_frames(info, times, workdir, req.mode, req.describe(), range_start=0, range_end=info.duration)
    assert not res.errors
    assert [r.effective_time for r in res.records] == [0, 10, 20, 30, 40, 50, 60]
    for r in res.records:
        assert frame_index(r) == round(r.effective_time * FPS)  # o conteúdo é o do instante informado
        assert r.time_source == "PTS"


def test_2_count_12_within_range(videos, workdir):
    info = probe_video(videos["mp4"])
    for dist in Distribution:
        req = ExtractionRequest(Mode.COUNT, 7.3, 41.9, count=12, distribution=dist)
        times = plan_times(req, info.duration)
        assert len(times) == 12
        res = extract_frames(info, times, workdir, req.mode, req.describe(), range_start=7.3, range_end=41.9)
        assert 0 < len(res.records) <= 12
        assert all(7.3 <= r.effective_time <= 41.9 for r in res.records)  # nada fora do trecho
        for r in res.records:
            assert frame_index(r) == round(r.effective_time * FPS)


def test_range_start_between_frames_uses_next_frame(videos, workdir):
    info = probe_video(videos["mp4"])
    # 10,01 s fica entre os quadros 10,00 e 10,04: o quadro em exibição (10,00) começa antes do trecho
    req = ExtractionRequest(Mode.INTERVAL, 10.01, 12.0, interval=1)
    res = extract_frames(info, plan_times(req, info.duration), workdir, req.mode, "x", range_start=10.01,
                         range_end=12.0)
    assert res.records[0].effective_time == pytest.approx(10.04)
    assert all(10.01 <= r.effective_time <= 12.0 for r in res.records)


def test_3_manual_random_access(videos, workdir):
    info = probe_video(videos["mp4"])
    rnd = random.Random(42)
    times = [rnd.uniform(0, 64.9) for _ in range(25)]
    res = extract_frames(info, times, workdir, Mode.MANUAL, "manual")
    for r in res.records:
        expected = int(r.requested_time * FPS + 1e-9)
        assert frame_index(r) == expected
        assert r.effective_time == pytest.approx(expected / FPS)
        assert r.effective_time <= r.requested_time + 1e-6
        assert r.requested_time - r.effective_time < 1 / FPS


def test_duplicate_requests_are_merged_not_duplicated(videos, workdir):
    info = probe_video(videos["mp4"])
    res = extract_frames(info, [5.0, 5.01, 5.02], workdir, Mode.MANUAL, "m")
    assert len(res.records) == 1 and len(res.merged) == 2


def test_end_of_video_returns_last_frame(videos, workdir):
    info = probe_video(videos["mp4"])
    rec = grab_single(info, info.duration, workdir)
    assert frame_index(rec) == 65 * FPS - 1


def test_invalid_ranges(videos):
    info = probe_video(videos["mp4"])
    with pytest.raises(VideoError):
        plan_times(ExtractionRequest(Mode.INTERVAL, 20, 10, interval=1), info.duration)
    with pytest.raises(VideoError):
        plan_times(ExtractionRequest(Mode.INTERVAL, 0, 999, interval=1), info.duration)
    with pytest.raises(VideoError):
        plan_times(ExtractionRequest(Mode.INTERVAL, 0, 10, interval=0), info.duration)
    with pytest.raises(VideoError):
        plan_times(ExtractionRequest(Mode.COUNT, 0, 10, count=0), info.duration)


def test_6_original_untouched(videos, workdir):
    path = videos["mov"]
    h0, st0 = sha256_file(path), os.stat(path)
    info = probe_video(path)
    req = ExtractionRequest(Mode.INTERVAL, 0, info.duration, interval=1)
    extract_frames(info, plan_times(req, info.duration), workdir, req.mode, "x")
    st1 = os.stat(path)
    assert sha256_file(path) == h0
    assert (st1.st_size, st1.st_mtime) == (st0.st_size, st0.st_mtime)


@pytest.mark.parametrize("content,expected", [
    (b"", "vazio"),
    (b"isto nao e um video" * 200, "não pôde ser reconhecido"),
])
def test_8_invalid_files(tmp_path, content, expected):
    p = tmp_path / "x.mp4"
    p.write_bytes(content)
    with pytest.raises(VideoError) as e:
        probe_video(str(p))
    assert expected in str(e.value)


def test_8_truncated_and_missing(videos, tmp_path):
    data = open(videos["mp4"], "rb").read()
    p = tmp_path / "cortado.mp4"
    p.write_bytes(data[:5000])
    with pytest.raises(VideoError):
        probe_video(str(p))
    with pytest.raises(VideoError) as e:
        probe_video(str(tmp_path / "nao_existe.mp4"))
    assert "não foi encontrado" in str(e.value)
    with pytest.raises(VideoError):
        probe_video(str(tmp_path))  # pasta


def test_audio_only_file(tmp_path):
    import av

    p = str(tmp_path / "audio.wav")
    with av.open(p, "w") as c:
        s = c.add_stream("pcm_s16le", rate=8000)
        f = av.AudioFrame(format="s16", layout="mono", samples=800)
        for plane in f.planes:
            plane.update(bytes(plane.buffer_size))
        f.sample_rate = 8000
        for pkt in s.encode(f):
            c.mux(pkt)
        for pkt in s.encode():
            c.mux(pkt)
    with pytest.raises(VideoError) as e:
        probe_video(p)
    assert "não contém trilha de vídeo" in str(e.value)


@pytest.mark.skipif(not ffmpeg_exe(), reason="ffmpeg não disponível no PATH para gerar o vídeo com rotação")
def test_rotation_metadata_matches_ffmpeg(videos, tmp_path):
    src = videos["mp4"]
    rot = str(tmp_path / "rot.mp4")
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", src, "-c", "copy", "-metadata:s:v", "rotate=90", rot],
                   check=True)
    ref = str(tmp_path / "ref.png")
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", rot, "-frames:v", "1", ref], check=True)
    info = probe_video(rot)
    assert info.display_size == (240, 320)
    rec = grab_single(info, 0, str(tmp_path))
    mine = load_display_image(rec)
    with Image.open(ref) as im:
        assert mine.tobytes() == im.convert("RGB").tobytes()
