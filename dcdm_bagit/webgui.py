from __future__ import annotations

import json
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from dcdm_bagit.bagit.verify import verify_bag
from dcdm_bagit.build import build_dcdm_bagit


HTML_INDEX = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>dcdm-bagit Web GUI</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 18px; color: #111; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .card { border: 1px solid #ddd; border-radius: 10px; padding: 14px; }
    label { display: block; font-size: 13px; color: #444; margin-bottom: 6px; }
    input[type="text"], input[type="number"], input[type="file"], select { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 8px; box-sizing: border-box; }
    .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    button { padding: 10px 14px; border: 0; border-radius: 10px; background: #1463ff; color: white; cursor: pointer; }
    button.secondary { background: #444; }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    .status { margin-top: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; white-space: pre-wrap; }
    .hidden { display: none; }
    .hr { height: 1px; background: #eee; margin: 12px 0; }
  </style>
</head>
<body>
  <h2>dcdm-bagit Web GUI</h2>
  <div class="card">
    <div class="row">
      <label><input type="radio" name="mode" value="bagit-only" checked/> BagIt-only (TIFF/WAV/SRT vorhanden)</label>
      <label><input type="radio" name="mode" value="prores"/> Optional: ProRes → DCDM → BagIt</label>
    </div>
    <div class="hr"></div>
    <div class="grid">
      <div>
        <label>Ausgabe-BagIt Ordner</label>
        <input id="outputDir" type="text" value="./out-bag"/>
      </div>
      <div>
        <label>video FPS (für Subtitle rebase)</label>
        <input id="videoFps" type="text" value="25.0"/>
      </div>
    </div>
    <div class="row" style="margin-top: 10px;">
      <label><input id="tagmanifest" type="checkbox"/> tagmanifest zusätzlich schreiben</label>
      <label><input id="rebase" type="checkbox" checked/> Subtitle Timecodes rebase</label>
      <label><input id="audioNormalize" type="checkbox" checked/> Audio normalisieren (PCM 24-bit / 48kHz)</label>
    </div>
  </div>

  <div style="height: 12px;"></div>

  <div class="card" id="bagitSection">
    <h3 style="margin-top:0;">Inputs (BagIt-only)</h3>
    <div class="grid">
      <div>
        <label>TIFF Frames Ordner</label>
        <input id="tiffDir" type="text" placeholder="/path/frames"/>
      </div>
      <div>
        <label>Audio WAV Ordner</label>
        <input id="audioDir" type="text" placeholder="/path/audio"/>
      </div>
    </div>
    <div style="margin-top: 12px;">
      <label>SRT Untertitel Datei</label>
      <input id="srtPath" type="text" placeholder="/path/subs.srt"/>
    </div>
  </div>

  <div class="card hidden" id="proresSection">
    <h3 style="margin-top:0;">Inputs (ProRes)</h3>
    <div class="grid">
      <div>
        <label>ProRes Datei</label>
        <input id="proresPath" type="text" placeholder="/path/movie.mov"/>
      </div>
      <div>
        <label>Frame Range (optional) z.B. 1-240</label>
        <input id="frameRange" type="text" placeholder=""/>
      </div>
    </div>
    <div class="grid" style="margin-top: 12px;">
      <div>
        <label>target TIFF</label>
        <select id="targetTiff">
          <option value="keep" selected>keep</option>
          <option value="2k">2k</option>
          <option value="4k">4k</option>
        </select>
      </div>
      <div>
        <label>Audio Split (Mono pro Kanal, best-effort)</label>
        <input id="audioSplit" type="checkbox"/>
      </div>
    </div>
    <div style="margin-top: 12px;">
      <label>SRT Untertitel Datei</label>
      <input id="proresSrtPath" type="text" placeholder="/path/subs.srt"/>
    </div>
  </div>

  <div style="height: 12px;"></div>

  <div class="row">
    <button id="buildBtn">Build BagIt</button>
    <button class="secondary" id="verifyBtn">Verify</button>
  </div>

  <div class="status" id="statusBox">Bereit.</div>

  <script>
    const $ = (id) => document.getElementById(id);
    const statusBox = $("statusBox");
    const setStatus = (s) => { statusBox.textContent = s; };

    function getMode() {
      return document.querySelector('input[name="mode"]:checked').value;
    }

    function refreshSections() {
      const mode = getMode();
      $("bagitSection").classList.toggle("hidden", mode !== "bagit-only");
      $("proresSection").classList.toggle("hidden", mode !== "prores");
    }
    document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", refreshSections));
    refreshSections();

    async function startJob(kind, payload) {
      const res = await fetch(kind, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || ("HTTP " + res.status));
      }
      return await res.json();
    }

    async function pollJob(jobId) {
      while (true) {
        const res = await fetch("/api/job/" + encodeURIComponent(jobId));
        const data = await res.json();
        if (data.status === "running") {
          setStatus("running...\\n" + (data.log || "").toString());
          await new Promise(r => setTimeout(r, 700));
          continue;
        }
        if (data.status === "done") {
          setStatus("done\\n" + (data.log || "").toString());
          return;
        }
        if (data.status === "error") {
          setStatus("error\\n" + (data.error || "") + "\\n\\n" + (data.log || ""));
          throw new Error(data.error || "Job failed");
        }
        setStatus("unknown status: " + data.status);
        throw new Error("Unknown job state");
      }
    }

    $("buildBtn").addEventListener("click", async () => {
      $("buildBtn").disabled = true;
      $("verifyBtn").disabled = true;
      try {
        const payload = {
          output_dir: $("outputDir").value,
          tagmanifest: $("tagmanifest").checked,
          video_fps: parseFloat($("videoFps").value),
          subtitle_timecode_rebase: $("rebase").checked,
          audio_normalize: $("audioNormalize").checked,
          mode: getMode(),
        };

        if (payload.mode === "bagit-only") {
          payload.tiff_dir = $("tiffDir").value;
          payload.audio_dir = $("audioDir").value;
          payload.srt_path = $("srtPath").value;
        } else {
          payload.prores_path = $("proresPath").value;
          payload.frame_range = $("frameRange").value || null;
          payload.target_tiff = $("targetTiff").value;
          payload.audio_split = $("audioSplit").checked;
          payload.srt_path = $("proresSrtPath").value;
        }

        setStatus("starting build...");
        const { job_id } = await startJob("/api/build", payload);
        await pollJob(job_id);
      } catch (e) {
        setStatus("error: " + e.message);
      } finally {
        $("buildBtn").disabled = false;
        $("verifyBtn").disabled = false;
      }
    });

    $("verifyBtn").addEventListener("click", async () => {
      $("buildBtn").disabled = true;
      $("verifyBtn").disabled = true;
      try {
        const payload = { bag_dir: $("outputDir").value };
        setStatus("starting verify...");
        const { job_id } = await startJob("/api/verify", payload);
        await pollJob(job_id);
      } catch (e) {
        setStatus("error: " + e.message);
      } finally {
        $("buildBtn").disabled = false;
        $("verifyBtn").disabled = false;
      }
    });
  </script>
</body>
</html>
"""


@dataclass
class Job:
    status: str = "queued"  # queued|running|done|error
    log: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = Job()
        return job_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def set_running(self, job_id: str) -> None:
        with self._lock:
            j = self._jobs[job_id]
            j.status = "running"
            j.updated_at = time.time()

    def add_log(self, job_id: str, line: str) -> None:
        with self._lock:
            j = self._jobs[job_id]
            j.log.append(line)
            j.updated_at = time.time()

    def set_done(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        with self._lock:
            j = self._jobs[job_id]
            j.status = "done"
            j.result = result or {}
            j.updated_at = time.time()

    def set_error(self, job_id: str, error: str) -> None:
        with self._lock:
            j = self._jobs[job_id]
            j.status = "error"
            j.error = error
            j.updated_at = time.time()

    def to_json(self, job: Job) -> dict[str, Any]:
        return {
            "status": job.status,
            "log": "\n".join(job.log),
            "result": job.result,
            "error": job.error,
        }


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length_str = handler.headers.get("Content-Length", "0")
    try:
        length = int(length_str)
    except ValueError:
        length = 0
    raw = handler.rfile.read(length) if length > 0 else b""
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def main(port: int = 8765) -> None:
    host = "127.0.0.1"
    job_mgr = JobManager()

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/" or parsed.path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML_INDEX.encode("utf-8"))
                return

            if parsed.path.startswith("/api/job/"):
                job_id = parsed.path.split("/api/job/", 1)[1]
                job = job_mgr.get(job_id)
                if not job:
                    self._send_json(404, {"error": "Unknown job"})
                    return
                self._send_json(200, job_mgr.to_json(job))
                return

            self._send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in ("/api/build", "/api/verify"):
                self._send_json(404, {"error": "Not found"})
                return

            body = _read_json_body(self)
            job_id = job_mgr.create()
            job_mgr.set_running(job_id)

            def run_build() -> None:
                try:
                    if parsed.path == "/api/build":
                        job_mgr.add_log(job_id, "build: started")
                        mode = body.get("mode")
                        output_dir = Path(body["output_dir"])
                        tagmanifest = bool(body.get("tagmanifest"))
                        subtitle_timecode_rebase = bool(body.get("subtitle_timecode_rebase", True))
                        audio_normalize = bool(body.get("audio_normalize", True))
                        video_fps = body.get("video_fps")

                        if mode == "bagit-only":
                            build_dcdm_bagit(
                                output_dir=output_dir,
                                tagmanifest=tagmanifest,
                                input_prores=None,
                                input_tiff_dir=body.get("tiff_dir"),
                                input_audio_dir=body.get("audio_dir"),
                                input_srt=body.get("srt_path"),
                                video_fps=float(video_fps) if video_fps is not None else None,
                                frame_range=body.get("frame_range"),
                                audio_normalize=audio_normalize,
                                subtitle_timecode_rebase=subtitle_timecode_rebase,
                                audio_split=False,
                                target_tiff="keep",
                            )
                        elif mode == "prores":
                            build_dcdm_bagit(
                                output_dir=output_dir,
                                tagmanifest=tagmanifest,
                                input_prores=body.get("prores_path"),
                                input_tiff_dir=None,
                                input_audio_dir=None,
                                input_srt=body.get("srt_path"),
                                video_fps=float(video_fps) if video_fps is not None else None,
                                frame_range=body.get("frame_range"),
                                audio_normalize=audio_normalize,
                                subtitle_timecode_rebase=subtitle_timecode_rebase,
                                audio_split=bool(body.get("audio_split")),
                                target_tiff=str(body.get("target_tiff", "keep")),
                            )
                        else:
                            raise ValueError("Unknown mode")

                        job_mgr.add_log(job_id, "build: done")
                        job_mgr.set_done(job_id, {"output_dir": str(output_dir)})
                        return

                    if parsed.path == "/api/verify":
                        job_mgr.add_log(job_id, "verify: started")
                        bag_dir = Path(body["bag_dir"])
                        verify_bag(bag_dir=bag_dir)
                        job_mgr.add_log(job_id, "verify: done")
                        job_mgr.set_done(job_id, {"bag_dir": str(bag_dir)})
                        return

                    raise RuntimeError("Unhandled endpoint")
                except Exception as e:
                    job_mgr.add_log(job_id, f"error: {e}")
                    job_mgr.set_error(job_id, str(e))
                    return

            t = threading.Thread(target=run_build, daemon=True)
            t.start()

            self._send_json(200, {"job_id": job_id})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # Keep the console quiet; the GUI shows errors/logs.
            return

    server = HTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Web GUI started: {url}")

    try:
        webbrowser.open(url)
    except Exception:
        # If browser auto-open fails, user can still visit the URL.
        pass

    server.serve_forever()


if __name__ == "__main__":
    main()

