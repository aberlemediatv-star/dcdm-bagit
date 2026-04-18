# OUTPUT_SPEC.md (BagIt + DCDM)

Dieses Dokument beschreibt die **pragmatische** Ausgabe-Struktur, die dieses Tool in der BagIt-Payload erzeugt.

Wichtig: Für `SMPTE-XML` Untertitel gibt es in der MVP-Version **keinen** verbindlichen Bundesarchiv-Schema-Sample. Die erzeugte XML ist daher **best-effort** und dient als nutzbarer Ausgangspunkt.

## Bagit Basisset (RFC 8493)

Im Bag-Root (direkt unter `OUTPUT_BAG/`):

- `bagit.txt`
- `bag-info.txt`
- `manifest-sha256.txt`
- optional: `tagmanifest-sha256.txt` (wenn `--tagmanifest` gesetzt)

Payload liegt in:

- `data/`

## Payload Layout

Unter `data/` werden folgende Unterordner erzeugt:

- `data/video/`
  - Bildsequenz als TIFF Frames
  - Benennung: `00000001.tif`, `00000002.tif`, ...
  - Dateien werden im Tool in dieser 1-based Reihenfolge abgelegt (bei TIFF-Input: nach numerischem Sortieren des Input-Namens; bei ProRes-Transcode: nach Export-Reihenfolge).

- `data/audio/`
  - WAV Dateien (PCM) pro Tonspur
  - Benennung: `track01.wav`, `track02.wav`, ...
  - Bei ProRes-Input: bei `--audio-split` werden Multichannel-Streams best-effort in Mono-Dateien aufgeteilt.

- `data/subtitles/`
  - `subtitles.srt` (Original-Input, falls `--input-srt` gesetzt)
  - `subtitles.smpte.xml` (SRT→XML best-effort, falls `--input-srt` gesetzt)

- `data/metadata/`
  - `dcdm-info.json` (minimale Metadaten für Debug/Nachvollziehbarkeit)

## Generiertes `dcdm-info.json` (Minimal)

Enthält u.a.:

- `tool`
- `video_fps`
- Input-Flags (ProRes vs TIFF, Vorhandensein von Audio/SRT)
- Optionen (audio_normalize, subtitle_timecode_rebase, target_tiff)

