from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dcdm_bagit.bagit.builder import BagItBuilder
from dcdm_bagit.inputs import (
    copy_tiff_sequence_into_data,
    copy_wav_tracks_into_data,
    get_video_fps_from_prores,
    normalize_wav_tracks,
    validate_wav_tracks,
)
from dcdm_bagit.spec.layout import DcdmLayout
from dcdm_bagit.subtitles.srt_to_smpte_xml import convert_srt_to_smpte_xml
from dcdm_bagit.transcode.prores import transcode_prores_to_dcdm_components


def _parse_frame_range(frame_range: str | None) -> tuple[int, int] | None:
    """
    Parse START-END (inclusive), 1-based.
    """
    if not frame_range:
        return None
    start_s, end_s = frame_range.split("-", 1)
    start = int(start_s)
    end = int(end_s)
    if start < 1 or end < start:
        raise ValueError(f"Invalid frame-range: {frame_range}")
    return start, end


def build_dcdm_bagit(
    *,
    output_dir: Path,
    tagmanifest: bool,
    input_prores: str | None,
    input_tiff_dir: str | None,
    input_audio_dir: str | None,
    input_srt: str | None,
    video_fps: float | None,
    frame_range: str | None,
    audio_normalize: bool,
    subtitle_timecode_rebase: bool,
    audio_split: bool,
    target_tiff: str,
) -> None:
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output dir already exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    layout = DcdmLayout()
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Create payload subdirs
    (data_dir / layout.video_dir).mkdir(parents=True, exist_ok=True)
    (data_dir / layout.audio_dir).mkdir(parents=True, exist_ok=True)
    (data_dir / layout.subtitles_dir).mkdir(parents=True, exist_ok=True)
    (data_dir / layout.metadata_dir).mkdir(parents=True, exist_ok=True)

    prores_path = Path(input_prores).expanduser() if input_prores else None
    tiff_dir_path = Path(input_tiff_dir).expanduser() if input_tiff_dir else None
    audio_dir_path = Path(input_audio_dir).expanduser() if input_audio_dir else None
    srt_path = Path(input_srt).expanduser() if input_srt else None

    range_1based = _parse_frame_range(frame_range)

    derived_fps = video_fps
    if prores_path:
        if not prores_path.exists():
            raise FileNotFoundError(prores_path)
        if derived_fps is None:
            derived_fps = get_video_fps_from_prores(prores_path)

        transcode_prores_to_dcdm_components(
            prores_path=prores_path,
            data_dir=data_dir,
            layout=layout,
            video_fps=derived_fps,
            frame_range=range_1based,
            target_tiff=target_tiff,
            audio_split=audio_split,
            audio_normalize=audio_normalize,
        )
    else:
        if tiff_dir_path is None:
            raise ValueError("Missing --input-tiff-dir (or provide --input-prores).")
        if audio_dir_path is None:
            raise ValueError("Missing --input-audio-dir (or provide --input-prores).")
        if not tiff_dir_path.exists():
            raise FileNotFoundError(tiff_dir_path)
        if not audio_dir_path.exists():
            raise FileNotFoundError(audio_dir_path)

        copy_tiff_sequence_into_data(tiff_dir_path=tiff_dir_path, data_dir=data_dir, layout=layout, frame_range=range_1based)
        copied_tracks = copy_wav_tracks_into_data(audio_dir_path=audio_dir_path, data_dir=data_dir, layout=layout)
        if audio_normalize:
            # Normalize overwriting into the same track filenames (best-effort).
            normalize_wav_tracks(tracks=copied_tracks, layout=layout, data_dir=data_dir)
        else:
            validate_wav_tracks(tracks=copied_tracks)

    # Subtitles: always copy original SRT if provided; additionally generate SMPTE XML.
    srt_dst = layout.srt_subtitle_path(data_dir, layout.srt_subtitle_filename)
    if srt_path:
        if not srt_path.exists():
            raise FileNotFoundError(srt_path)
        srt_dst.parent.mkdir(parents=True, exist_ok=True)
        srt_dst.write_bytes(srt_path.read_bytes())

        smpte_dst = layout.subtitles_path(data_dir, layout.smpte_subtitle_filename)
        convert_srt_to_smpte_xml(
            srt_path=srt_path,
            output_xml_path=smpte_dst,
            video_fps=derived_fps,
            rebase_timecodes=subtitle_timecode_rebase,
        )

    # Minimal metadata
    meta: dict[str, Any] = {
        "tool": "dcdm-bagit",
        "video_fps": derived_fps,
        "has_prores_input": bool(prores_path),
        "has_tiff_input": bool(tiff_dir_path),
        "has_audio_input": bool(audio_dir_path),
        "has_srt_input": bool(srt_path),
        "frame_range_1based": list(range_1based) if range_1based else None,
        "audio_normalize": audio_normalize,
        "subtitle_timecode_rebase": subtitle_timecode_rebase,
        "target_tiff": target_tiff,
    }
    (data_dir / layout.metadata_dir / layout.info_json_filename).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # BagIt packaging
    bag_info = {
        "Source-Format": "DCDM (Bundesarchiv) payload",
        "Generated-By": "dcdm-bagit",
        "Video-FPS": str(derived_fps) if derived_fps is not None else "unknown",
    }
    BagItBuilder().build(bag_dir=output_dir, bag_info=bag_info, write_tagmanifest=tagmanifest)

