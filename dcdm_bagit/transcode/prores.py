from __future__ import annotations

import subprocess
from pathlib import Path


def _require_tool(tool: str) -> None:
    from shutil import which

    if which(tool) is None:
        raise EnvironmentError(f"Missing required tool '{tool}' on PATH.")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)


def _probe_audio_stream_indices(prores_path: Path) -> list[int]:
    # Kept for backward compatibility with older calls.
    infos = _probe_audio_stream_infos(prores_path)
    return [stream_index for stream_index, _channels in infos]


def _probe_audio_stream_infos(prores_path: Path) -> list[tuple[int, int]]:
    """
    Return list of (stream_index, channels) for all audio streams.
    """
    _require_tool("ffprobe")
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index,channels",
        "-of",
        "json",
        str(prores_path),
    ]
    res = _run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {prores_path}: {res.stderr.strip()}")
    import json

    info = json.loads(res.stdout)
    streams = info.get("streams", [])
    infos: list[tuple[int, int]] = []
    for s in streams:
        if "index" not in s:
            continue
        stream_index = int(s["index"])
        channels = int(s.get("channels", 0) or 0)
        infos.append((stream_index, channels))
    infos.sort(key=lambda t: t[0])
    return infos


def transcode_prores_to_dcdm_components(
    *,
    prores_path: Path,
    data_dir: Path,
    layout,
    video_fps: float,
    frame_range: tuple[int, int] | None,
    target_tiff: str,
    audio_split: bool,
    audio_normalize: bool,
) -> None:
    """
    ProRes ->:
      - TIFF 16-bit RGB (best-effort uncompressed) image sequence
      - WAV PCM S24LE / 48kHz audio tracks (best-effort one WAV per audio stream)
    """
    _require_tool("ffmpeg")
    _require_tool("ffprobe")

    prores_path = prores_path.resolve()
    video_dir = data_dir / layout.video_dir
    audio_dir = data_dir / layout.audio_dir
    video_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 1) Video frames
    frame_pattern = video_dir / "%08d.tif"

    scale_filter = ""
    if target_tiff in ("2k", "4k"):
        if target_tiff == "2k":
            w, h = 2048, 1080
        else:
            w, h = 4096, 2160
        scale_filter = (
            f"scale=w={w}:h={h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )

    vf_parts: list[str] = []
    if scale_filter:
        vf_parts.append(scale_filter)

    if frame_range:
        start_1based, end_1based = frame_range
        # Use 0-based n for ffmpeg select.
        start0 = start_1based - 1
        end0 = end_1based - 1
        # Keep frame timestamps consistent.
        vf_parts.append(
            f"select='between(n,{start0},{end0})',setpts=N/{video_fps}/TB"
        )

    vf = ",".join(vf_parts) if vf_parts else None

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(prores_path),
        "-an",
        "-vsync",
        "0",
        "-pix_fmt",
        "rgb48le",
    ]
    if vf:
        cmd += ["-vf", vf]

    cmd += [str(frame_pattern)]

    res = _run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg video transcode failed: {res.stderr.strip()}")

    # 2) Audio tracks
    # We output one WAV per audio stream index; if there are multiple streams this becomes multiple files.
    audio_stream_infos = _probe_audio_stream_infos(prores_path)
    if not audio_stream_infos:
        raise ValueError("No audio streams detected in ProRes input.")

    # Map to sequential track numbering 1..N for stable output.
    track_counter = 0
    for stream_index, channels in audio_stream_infos:
        if audio_split and channels and channels > 1:
            # Best-effort: split multichannel stream into mono using pan.
            for ch in range(channels):
                track_counter += 1
                out_path = audio_dir / f"track{track_counter:02d}.wav"
                cmd_a = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(prores_path),
                    "-vn",
                    "-map",
                    f"0:a:{stream_index}",
                    "-af",
                    f"pan=mono|c0=c{ch}",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s24le",
                    "-ar",
                    "48000",
                    str(out_path),
                ]
                res_a = _run(cmd_a)
                if res_a.returncode != 0:
                    raise RuntimeError(f"ffmpeg audio transcode failed: {res_a.stderr.strip()}")
        else:
            track_counter += 1
            out_path = audio_dir / f"track{track_counter:02d}.wav"
            cmd_a = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(prores_path),
                "-vn",
                "-map",
                f"0:a:{stream_index}",
                "-c:a",
                "pcm_s24le",
                "-ar",
                "48000",
                str(out_path),
            ]
            res_a = _run(cmd_a)
            if res_a.returncode != 0:
                raise RuntimeError(f"ffmpeg audio transcode failed: {res_a.stderr.strip()}")

    # Note: `audio_normalize` is effectively always applied because we re-encode to S24LE / 48kHz.

