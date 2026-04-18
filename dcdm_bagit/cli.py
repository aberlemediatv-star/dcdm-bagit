from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _add_common_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", "-o", required=True, help="Output bag directory (will be created).")
    parser.add_argument("--tagmanifest", action="store_true", help="Also write tagmanifest-sha256.txt.")

    parser.add_argument("--video-fps", type=float, default=None, help="Video FPS (needed for SRT->SMPTE-XML conversion).")
    parser.add_argument(
        "--frame-range",
        type=str,
        default=None,
        help="Optional frame range for ProRes->TIFF export: START-END (inclusive), 1-based (e.g. 1-240).",
    )

    parser.add_argument(
        "--audio-normalize",
        action="store_true",
        default=False,
        help="Normalize audio to 24-bit PCM / 48kHz via ffmpeg (best-effort).",
    )
    parser.add_argument(
        "--subtitle-timecode-rebase",
        action="store_true",
        default=True,
        help="Rebase subtitle timecodes onto the provided/derived video FPS.",
    )


def build_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser(
        "build", help="Create a BagIt package for Bundesarchiv DCDM from inputs (or optional ProRes transcoding)."
    )
    _add_common_build_args(p)
    p.add_argument("--input-prores", type=str, default=None, help="Input ProRes MOV/MXF. Optional transcoding path.")
    p.add_argument("--input-tiff-dir", type=str, default=None, help="Input TIFF frame directory (already exported).")
    p.add_argument("--input-audio-dir", type=str, default=None, help="Input audio directory (WAV files).")
    p.add_argument("--input-srt", type=str, default=None, help="Input SRT subtitle file.")
    p.add_argument(
        "--audio-split",
        action="store_true",
        default=False,
        help="If multiple channels are detected, split into separate WAVs where possible (ProRes path).",
    )
    p.add_argument(
        "--target-tiff",
        choices=["2k", "4k", "keep"],
        default="keep",
        help="If transcoding ProRes: choose target TIFF size. 'keep' keeps source dimensions (best-effort).",
    )
    p.set_defaults(command="build")


def verify_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("verify", help="Verify a BagIt package using its manifests.")
    p.add_argument("--bag", "-b", required=True, type=str, help="Bag directory to verify.")
    p.set_defaults(command="verify")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="dcdm-bagit", description="Create BagIt packages for DCDM (Bundesarchiv).")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    build_parser(subparsers)
    verify_parser(subparsers)

    args = parser.parse_args(argv)
    out_dir = Path(getattr(args, "output", "")).expanduser() if hasattr(args, "output") else None
    bag_dir = Path(args.bag).expanduser() if hasattr(args, "bag") else None

    if args.cmd == "build":
        from dcdm_bagit.build import build_dcdm_bagit

        build_dcdm_bagit(
            output_dir=Path(args.output),
            tagmanifest=args.tagmanifest,
            input_prores=args.input_prores,
            input_tiff_dir=args.input_tiff_dir,
            input_audio_dir=args.input_audio_dir,
            input_srt=args.input_srt,
            video_fps=args.video_fps,
            frame_range=args.frame_range,
            audio_normalize=args.audio_normalize,
            subtitle_timecode_rebase=args.subtitle_timecode_rebase,
            audio_split=args.audio_split,
            target_tiff=args.target_tiff,
        )
        return 0

    if args.cmd == "verify":
        from dcdm_bagit.bagit.verify import verify_bag

        verify_bag(bag_dir=Path(args.bag))
        return 0

    raise RuntimeError(f"Unhandled command: {args.cmd}")

