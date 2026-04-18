from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape as xml_escape


_TIME_RE = re.compile(r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})")


def _parse_timestamp(ts: str) -> int:
    """
    Parse 'HH:MM:SS,mmm' or 'HH:MM:SS.mmm' and return milliseconds.
    """
    m = _TIME_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Invalid SRT timestamp: {ts!r}")
    h = int(m.group("h"))
    mm = int(m.group("m"))
    s = int(m.group("s"))
    ms = int(m.group("ms").ljust(3, "0"))
    return ((h * 60 + mm) * 60 + s) * 1000 + ms


def _format_hhmmss_mmm(ms: float) -> str:
    ms_int = int(round(ms))
    h = ms_int // 3600000
    ms_int %= 3600000
    m = ms_int // 60000
    ms_int %= 60000
    s = ms_int // 1000
    milli = ms_int % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{milli:03d}"


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


def _split_blocks(srt_text: str) -> list[str]:
    # Normalize newlines; SRT blocks are separated by empty lines.
    text = srt_text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    return [b.strip() for b in blocks if b.strip()]


def parse_srt(srt_path: Path) -> list[Cue]:
    srt_path = srt_path.resolve()
    raw = srt_path.read_text(encoding="utf-8", errors="replace")
    cues: list[Cue] = []
    for block in _split_blocks(raw):
        lines = [ln.strip("\ufeff") for ln in block.split("\n") if ln.strip() != ""]
        if len(lines) < 2:
            continue
        # Usually: index, time-range, text...
        # Some exports omit index; handle both.
        if re.match(r"^\d+$", lines[0]):
            time_line = lines[1]
            text_lines = lines[2:]
        else:
            time_line = lines[0]
            text_lines = lines[1:]

        if "-->" not in time_line:
            continue
        start_s, end_s = [p.strip() for p in time_line.split("-->", 1)]
        start_ms = _parse_timestamp(start_s)
        end_ms = _parse_timestamp(end_s)
        text = "\n".join(text_lines).strip()
        cues.append(Cue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def convert_srt_to_smpte_xml(
    *,
    srt_path: Path,
    output_xml_path: Path,
    video_fps: float | None,
    rebase_timecodes: bool,
) -> None:
    """
    Best-effort conversion from SRT to an SMPTE-TT-like caption XML.
    Without a concrete sample/schema from the Bundesarchiv, we generate a minimal, usable XML.
    """
    output_xml_path = output_xml_path.resolve()
    output_xml_path.parent.mkdir(parents=True, exist_ok=True)

    cues = parse_srt(srt_path)
    if not cues:
        raise ValueError(f"No cues found in SRT: {srt_path}")

    fps = video_fps
    if rebase_timecodes and (fps is None or fps <= 0):
        # Still create XML with original millisecond times.
        # Rebase is only possible if we know the intended FPS.
        rebase_timecodes = False

    def maybe_rebase(ms: int) -> float:
        if not rebase_timecodes or fps is None:
            return float(ms)
        # Map milliseconds to nearest frame, then map back to milliseconds.
        frame = round((ms / 1000.0) * fps)
        return (frame / fps) * 1000.0

    # Note: namespaces and exact schema details may vary by receiving system.
    # We keep the structure simple and stable.
    namespace = "http://www.smpte-ra.org/schemas/2052-1/2014/TT"
    xml_lines: list[str] = []
    xml_lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml_lines.append(f'<tt:tt xmlns:tt="{namespace}">')
    xml_lines.append("  <tt:body>")
    xml_lines.append("    <tt:div>")

    for idx, cue in enumerate(cues, start=1):
        b = maybe_rebase(cue.start_ms)
        e = maybe_rebase(cue.end_ms)
        begin = _format_hhmmss_mmm(b)
        end = _format_hhmmss_mmm(e)
        text = xml_escape(cue.text).replace("\n", "<br/>")
        # Minimal cue element.
        xml_lines.append(f'      <tt:p begin="{begin}" end="{end}" xml:id="cue{idx:05d}">{text}</tt:p>')

    xml_lines.append("    </tt:div>")
    xml_lines.append("  </tt:body>")
    xml_lines.append("</tt:tt>")

    output_xml_path.write_text("\n".join(xml_lines) + "\n", encoding="utf-8", newline="\n")

