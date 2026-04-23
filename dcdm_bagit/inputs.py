from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_TIFF_EXTS = {".tif", ".tiff"}
_WAV_EXTS = {".wav"}


def _require_tool(tool: str) -> None:
    from shutil import which

    if which(tool) is None:
        raise EnvironmentError(f"Missing required tool '{tool}' on PATH.")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)


def _probe_avg_frame_rate(prores_path: Path) -> float:
    _require_tool("ffprobe")
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate",
        "-of",
        "json",
        str(prores_path),
    ]
    res = _run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {prores_path}: {res.stderr.strip()}")
    info = json.loads(res.stdout)
    fr = info["streams"][0]["avg_frame_rate"]  # e.g. "30000/1001"
    if "/" in fr:
        num_s, den_s = fr.split("/", 1)
        return float(num_s) / float(den_s)
    return float(fr)


def get_video_fps_from_prores(prores_path: Path) -> float:
    return _probe_avg_frame_rate(prores_path)


def _sorted_tiff_files(tiff_dir_path: Path) -> list[Path]:
    files = [p for p in tiff_dir_path.rglob("*") if p.is_file() and p.suffix.lower() in _TIFF_EXTS]

    def sort_key(p: Path) -> tuple[int, str]:
        m = re.search(r"(\d+)", p.name)
        if m:
            return (int(m.group(1)), p.name)
        return (0, p.name)

    files.sort(key=sort_key)
    return files


def copy_tiff_sequence_into_data(
    *,
    tiff_dir_path: Path,
    data_dir: Path,
    layout,
    frame_range: tuple[int, int] | None,
) -> None:
    tiff_dir_path = tiff_dir_path.resolve()
    files = _sorted_tiff_files(tiff_dir_path)
    if not files:
        raise FileNotFoundError(f"No TIFF files found in {tiff_dir_path}")

    start = 1
    end = len(files)
    if frame_range:
        start, end = frame_range
        # frame_range refers to the *ordered* input files (best-effort).
        if start > len(files) or end > len(files):
            raise ValueError(f"frame_range {frame_range} out of bounds for {len(files)} input TIFFs")

    selected = files[start - 1 : end]
    dst_dir = data_dir / layout.video_dir
    dst_dir.mkdir(parents=True, exist_ok=True)

    for i, src in enumerate(selected, start=1):
        dst = dst_dir / layout.frame_filename_template.format(frame=i)
        shutil.copy2(src, dst)


@dataclass(frozen=True)
class AudioTrack:
    dst_path: Path


def copy_wav_tracks_into_data(*, audio_dir_path: Path, data_dir: Path, layout) -> list[AudioTrack]:
    audio_dir_path = audio_dir_path.resolve()
    files = [p for p in audio_dir_path.rglob("*") if p.is_file() and p.suffix.lower() in _WAV_EXTS]
    if not files:
        raise FileNotFoundError(f"No WAV files found in {audio_dir_path}")

    files.sort(key=lambda p: p.name)
    dst_dir = data_dir / layout.audio_dir
    dst_dir.mkdir(parents=True, exist_ok=True)

    tracks: list[AudioTrack] = []
    for idx, src in enumerate(files, start=1):
        dst = dst_dir / f"track{idx:02d}.wav"
        shutil.copy2(src, dst)
        tracks.append(AudioTrack(dst_path=dst))
    return tracks


def _ffmpeg_pcm_s24le_48k(*, input_path: Path, output_path: Path) -> None:
    _require_tool("ffmpeg")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        "pcm_s24le",
        "-ar",
        "48000",
        str(output_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {input_path}: {res.stderr.strip()}")


def _probe_audio_format(path: Path) -> dict[str, object]:
    _require_tool("ffprobe")
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,sample_fmt,channels",
        "-of",
        "json",
        str(path),
    ]
    res = _run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {res.stderr.strip()}")
    import json

    info = json.loads(res.stdout)
    streams = info.get("streams", [])
    if not streams:
        raise ValueError(f"No audio streams found in {path}")
    stream0 = streams[0]
    return {
        "sample_rate": int(float(stream0.get("sample_rate", 0))),
        "sample_fmt": str(stream0.get("sample_fmt", "")),
        "channels": int(stream0.get("channels", 0)),
    }


def validate_wav_tracks(*, tracks: Iterable[AudioTrack], expected_sample_rate: int = 48000) -> None:
    """
    Validate WAV tracks for basic DCDM constraints:
    - PCM audio
    - sample rate == expected_sample_rate
    - Prefer 24-bit inputs (if not, callers should use --audio-normalize).
    """
    # Heuristic check based on ffprobe's sample_fmt output.
    for t in tracks:
        fmt = _probe_audio_format(t.dst_path)
        sample_rate = int(fmt["sample_rate"])
        sample_fmt = str(fmt["sample_fmt"])

        if sample_rate != expected_sample_rate:
            raise ValueError(
                f"Audio sample rate mismatch for {t.dst_path.name}: expected {expected_sample_rate}, got {sample_rate}"
            )

        # ffprobe sample_fmt for PCM 24-bit often appears as s32p/s24le depending on decoder.
        # We accept any sample_fmt containing "24" as well as s32* (packed-24 best-effort).
        is_24bit = "24" in sample_fmt
        is_s32_packed = sample_fmt.startswith("s32")
        if not (is_24bit or is_s32_packed):
            raise ValueError(
                f"Audio bit depth not 24-bit for {t.dst_path.name} (ffprobe sample_fmt={sample_fmt}). "
                f"Run with --audio-normalize to generate PCM 24-bit / {expected_sample_rate}Hz."
            )


def normalize_wav_tracks(*, tracks: Iterable[AudioTrack], layout, data_dir: Path) -> None:
    # Best-effort: always re-encode to PCM S24LE / 48kHz.
    for t in tracks:
        input_path = t.dst_path
        tmp = input_path.with_suffix(".tmp.wav")
        try:
            _ffmpeg_pcm_s24le_48k(input_path=input_path, output_path=tmp)
            tmp.replace(input_path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

