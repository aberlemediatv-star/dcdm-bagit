from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class ManifestEntry:
    digest: str
    filepath: str  # path relative to bag root, using '/' separators


def _to_posix_relpath(path: Path) -> str:
    # BagIt manifests always use '/' separators.
    return path.as_posix()


def iter_payload_files(data_dir: Path) -> Iterator[Path]:
    """
    Yield absolute paths for payload files under `data_dir`, recursively.
    """
    for p in data_dir.rglob("*"):
        if p.is_file():
            yield p


def iter_manifest_paths(bag_root: Path, data_dir: Path) -> list[str]:
    rel_paths: list[str] = []
    for abs_path in iter_payload_files(data_dir):
        rel_paths.append(_to_posix_relpath(abs_path.relative_to(bag_root)))
    rel_paths.sort()
    return rel_paths


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def write_sha256_manifest(manifest_path: Path, bag_root: Path, file_paths: Iterable[str]) -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="\n") as out:
        for rel in file_paths:
            abs_path = bag_root / Path(rel)
            digest = sha256_file(abs_path)
            entries.append(ManifestEntry(digest=digest, filepath=rel))
            out.write(f"{digest} {rel}\n")
    return entries


def read_manifest_sha256(manifest_path: Path) -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    with manifest_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Format: "<digest> <filepath>"
            digest, rel = line.split(" ", 1)
            entries.append(ManifestEntry(digest=digest, filepath=rel))
    return entries

