from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from .manifest import iter_manifest_paths, write_sha256_manifest


@dataclass(frozen=True)
class BagItSpec:
    bagit_version: str = "1.0"
    encoding: str = "UTF-8"
    manifest_algorithm: str = "sha256"


class BagItBuilder:
    def __init__(self, spec: BagItSpec | None = None) -> None:
        self.spec = spec or BagItSpec()

    def build(
        self,
        bag_dir: Path,
        bag_info: dict[str, str] | None = None,
        write_tagmanifest: bool = False,
    ) -> None:
        bag_dir = bag_dir.resolve()
        data_dir = bag_dir / "data"
        if not data_dir.exists():
            raise FileNotFoundError(f"Missing payload directory: {data_dir}")

        bag_info = bag_info or {}

        bagit_txt = bag_dir / "bagit.txt"
        bag_info_txt = bag_dir / "bag-info.txt"
        manifest_path = bag_dir / f"manifest-{self.spec.manifest_algorithm}.txt"
        tagmanifest_path = bag_dir / f"tagmanifest-{self.spec.manifest_algorithm}.txt"

        # Payload manifest lists files relative to the bag root.
        file_paths = iter_manifest_paths(bag_root=bag_dir, data_dir=data_dir)

        total_octets = 0
        for rel in file_paths:
            total_octets += (bag_dir / Path(rel)).stat().st_size
        total_files = len(file_paths)

        today = _dt.date.today().isoformat()
        bagit_txt.write_text(
            "\n".join(
                [
                    f"BagIt-Version: {self.spec.bagit_version}",
                    f"Tag-File-Character-Encoding: {self.spec.encoding}",
                    f"Bagging-Date: {today}",
                    f"Payload-Oxum: {total_octets}.{total_files}",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )

        # bag-info.txt lines: <key>: <value>
        with bag_info_txt.open("w", encoding="utf-8", newline="\n") as f:
            # Ensure deterministic ordering for reproducible bags.
            for k in sorted(bag_info.keys()):
                f.write(f"{k}: {bag_info[k]}\n")
            if bag_info:
                f.write("\n")

        # Write payload manifest
        write_sha256_manifest(manifest_path=manifest_path, bag_root=bag_dir, file_paths=file_paths)

        if write_tagmanifest:
            tag_files = ["bagit.txt", "bag-info.txt", manifest_path.name]
            # RFC8493 tagmanifest excludes itself.
            tag_files.sort()
            write_sha256_manifest(tagmanifest_path, bag_root=bag_dir, file_paths=tag_files)

