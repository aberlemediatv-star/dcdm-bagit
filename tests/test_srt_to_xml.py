import unittest
import tempfile
from pathlib import Path


from dcdm_bagit.subtitles.srt_to_smpte_xml import convert_srt_to_smpte_xml


class SrtToXmlTests(unittest.TestCase):
    def test_basic_conversion_creates_xml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            srt_path = tmp_path / "subs.srt"
            xml_path = tmp_path / "subs.smpte.xml"

            srt_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHallo Welt\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nZweite Zeile\n",
                encoding="utf-8",
            )

            convert_srt_to_smpte_xml(srt_path=srt_path, output_xml_path=xml_path, video_fps=25.0, rebase_timecodes=True)

            xml_text = xml_path.read_text(encoding="utf-8")
            self.assertIn('xml:id="cue00001"', xml_text)
            self.assertIn('xml:id="cue00002"', xml_text)


if __name__ == "__main__":
    unittest.main()

