import unittest
from pathlib import Path
import tempfile


from dcdm_bagit.bagit.builder import BagItBuilder
from dcdm_bagit.bagit.verify import verify_bag


class BagItTests(unittest.TestCase):
    def test_bagit_build_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bag_dir = Path(tmp) / "bag"
            data_dir = bag_dir / "data"
            (data_dir / "video").mkdir(parents=True)
            (data_dir / "sub").mkdir(parents=True)
            (data_dir / "video" / "00000001.tif").write_bytes(b"frame1")
            (data_dir / "video" / "00000002.tif").write_bytes(b"frame2")
            (data_dir / "sub" / "file.bin").write_bytes(b"abc")

            bag_dir.mkdir(parents=True, exist_ok=True)
            BagItBuilder().build(
                bag_dir=bag_dir,
                bag_info={"Generated-By": "test", "Test-Key": "Test-Value"},
                write_tagmanifest=True,
            )

            self.assertTrue((bag_dir / "bagit.txt").exists())
            self.assertTrue((bag_dir / "bag-info.txt").exists())
            self.assertTrue((bag_dir / "manifest-sha256.txt").exists())
            self.assertTrue((bag_dir / "tagmanifest-sha256.txt").exists())

            # Should not raise
            verify_bag(bag_dir)

            # Break one payload file and ensure verify fails.
            (data_dir / "video" / "00000001.tif").write_bytes(b"tampered")
            with self.assertRaises((ValueError, FileNotFoundError)):
                verify_bag(bag_dir)


if __name__ == "__main__":
    unittest.main()

