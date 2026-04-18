from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DcdmLayout:
    """
    Pragmatic DCDM component layout inside the BagIt payload (`data/`).
    Naming rules are documented in `docs/OUTPUT_SPEC.md`.
    """

    video_dir: str = "video"
    audio_dir: str = "audio"
    subtitles_dir: str = "subtitles"
    metadata_dir: str = "metadata"

    # Payload file naming
    frame_filename_template: str = "{frame:08d}.tif"
    smpte_subtitle_filename: str = "subtitles.smpte.xml"
    srt_subtitle_filename: str = "subtitles.srt"
    info_json_filename: str = "dcdm-info.json"

    def video_frame_path(self, data_dir: Path, frame_index_1_based: int) -> Path:
        return data_dir / self.video_dir / self.frame_filename_template.format(frame=frame_index_1_based)

    def audio_path(self, data_dir: Path, filename: str) -> Path:
        return data_dir / self.audio_dir / filename

    def subtitles_path(self, data_dir: Path, filename: str) -> Path:
        return data_dir / self.subtitles_dir / filename

    def metadata_path(self, data_dir: Path, filename: str) -> Path:
        return data_dir / self.metadata_dir / filename

