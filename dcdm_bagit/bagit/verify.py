from __future__ import annotations

from pathlib import Path

from .manifest import read_manifest_sha256, sha256_file


def verify_bag(bag_dir: Path) -> None:
    bag_dir = bag_dir.resolve()
    if not bag_dir.exists():
        raise FileNotFoundError(bag_dir)

    manifest_path = bag_dir / "manifest-sha256.txt"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing payload manifest: {manifest_path}")

    entries = read_manifest_sha256(manifest_path)

    # Verify payload
    for i, entry in enumerate(entries, start=1):
        abs_path = bag_dir / Path(entry.filepath)
        if not abs_path.exists():
            raise FileNotFoundError(f"[{i}/{len(entries)}] Missing payload file: {entry.filepath}")
        digest = sha256_file(abs_path)
        if digest != entry.digest:
            raise ValueError(
                f"Checksum mismatch for {entry.filepath}: expected {entry.digest}, got {digest}"
            )

    # Verify tagmanifest if present
    tagmanifest_path = bag_dir / "tagmanifest-sha256.txt"
    if tagmanifest_path.exists():
        tag_entries = read_manifest_sha256(tagmanifest_path)
        for i, entry in enumerate(tag_entries, start=1):
            abs_path = bag_dir / Path(entry.filepath)
            if not abs_path.exists():
                raise FileNotFoundError(f"[{i}/{len(tag_entries)}] Missing tag file: {entry.filepath}")
            digest = sha256_file(abs_path)
            if digest != entry.digest:
                raise ValueError(
                    f"Tag checksum mismatch for {entry.filepath}: expected {entry.digest}, got {digest}"
                )

