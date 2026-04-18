# dcdm-bagit

CLI-Tool für **Bundesarchiv DCDM + BagIt**:
- Bildsequenz + WAV-Tonspuren + Untertitel-Input als **BagIt-Paket** bauen
- Optional: ProRes → (TIFF 16-bit Sequenz + WAV PCM 24-bit/48kHz + SRT→SMPTE-XML best-effort) und dann BagIt bauen

Repository: https://github.com/aberlemediatv-star/dcdm-bagit

## Voraussetzungen

- Python >= 3.10
- `ffmpeg` und `ffprobe` im `PATH` (für Audio-Normalisierung und ggf. ProRes-Transcode)

## Installation (lokal)

```bash
python -m pip install -e .
```

## Nutzung

### A) BagIt-only (wenn TIFF + WAV + SRT bereits vorliegen)

```bash
dcdm-bagit build \
  --output ./out-bag \
  --input-tiff-dir ./frames \
  --input-audio-dir ./audio \
  --input-srt ./subs.srt \
  --video-fps 25 \
  --audio-normalize
```

Danach:

```bash
dcdm-bagit verify --bag ./out-bag
```

### B) Optional: ProRes → DCDM-Komponenten → BagIt

```bash
dcdm-bagit build \
  --output ./out-bag \
  --input-prores ./movie.mov \
  --video-fps 25 \
  --frame-range 1-240 \
  --target-tiff 2k
```

## CLI-Flags (Build)

- `--output/-o`: Zielordner (wird erstellt)
- `--tagmanifest`: schreibt zusätzlich `tagmanifest-sha256.txt`
- `--video-fps`: nötig für die SRT→XML Zeitcode-Rebase (falls aktiviert)
- `--audio-normalize`: erzwingt Audio-Output als PCM S24LE / 48kHz (via ffmpeg)
- `--subtitle-timecode-rebase`: Timecodes auf Video-FPS rebase (Default: an)
- `--frame-range START-END`: 1-based, inclusive (nur für ProRes-Transcode; Best-effort bei TIFF auch unterstützt)
- `--target-tiff`: nur für ProRes-Transcode (`keep`, `2k`, `4k`)

## Testen

```bash
python -m unittest discover -s tests
```

## Web-GUI (Browser)

Falls du kein Tkinter/GUI-Window nutzen willst, gibt es eine kleine Web-GUI (lokaler HTTP-Server):

```bash
dcdm-bagit-web-gui
```

Danach öffnet sich ein Browser-Tab mit Build/Verify-Buttons.

