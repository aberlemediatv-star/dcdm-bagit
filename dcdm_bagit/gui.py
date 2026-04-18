from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from dcdm_bagit.bagit.verify import verify_bag
from dcdm_bagit.build import build_dcdm_bagit


@dataclass(frozen=True)
class GuiState:
    mode: str  # "bagit-only" | "prores"
    output_dir: Path
    tagmanifest: bool
    subtitle_timecode_rebase: bool
    audio_normalize: bool

    # bagit-only inputs
    tiff_dir: Optional[Path]
    audio_dir: Optional[Path]
    srt_path: Optional[Path]
    video_fps: Optional[float]

    # prores inputs
    prores_path: Optional[Path]
    frame_range: Optional[str]
    target_tiff: str  # keep|2k|4k
    audio_split: bool


class DcdmBagItGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DCDM + BagIt Builder")
        self.minsize(820, 560)

        self._queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None

        self._build_layout()
        self._set_mode("bagit-only")
        self._poll_queue()

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Top: mode + output + common options
        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        self.mode_var = tk.StringVar(value="bagit-only")
        mode_row = ttk.Frame(top)
        mode_row.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(mode_row, text="Modus:").pack(side="left")
        ttk.Radiobutton(
            mode_row, text="BagIt-only (TIFF/WAV/SRT vorhanden)", value="bagit-only", variable=self.mode_var
        ).pack(side="left", padx=8)
        ttk.Radiobutton(
            mode_row, text="Optional: ProRes -> DCDM -> BagIt", value="prores", variable=self.mode_var
        ).pack(side="left", padx=8)
        self.mode_var.trace_add("write", lambda *_: self._set_mode(self.mode_var.get()))

        # Output dir
        ttk.Label(top, text="Ausgabe-BagIt Ordner:").grid(row=1, column=0, sticky="w", pady=(12, 0))
        out_frame = ttk.Frame(top)
        out_frame.grid(row=1, column=1, sticky="ew", pady=(12, 0))
        out_frame.columnconfigure(0, weight=1)
        self.output_var = tk.StringVar(value=str(Path("./out-bag").resolve()))
        ttk.Entry(out_frame, textvariable=self.output_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(out_frame, text="Wählen…", command=self._pick_output_dir).grid(row=0, column=1, padx=8)

        # Common options
        common = ttk.LabelFrame(top, text="Optionen", padding=12)
        common.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        common.columnconfigure(1, weight=1)

        self.tagmanifest_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(common, text="tagmanifest zusätzlich schreiben", variable=self.tagmanifest_var).grid(
            row=0, column=0, sticky="w"
        )

        self.rebase_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(common, text="Subtitle Timecodes auf Video-FPS rebase", variable=self.rebase_var).grid(
            row=0, column=1, sticky="w", padx=12
        )

        self.audio_normalize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(common, text="Audio normalisieren (PCM 24-bit / 48kHz)", variable=self.audio_normalize_var).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

        # Middle: inputs
        self.inputs_frame = ttk.Frame(self, padding=12)
        self.inputs_frame.grid(row=1, column=0, sticky="nsew")
        self.inputs_frame.columnconfigure(1, weight=1)
        self.inputs_frame.rowconfigure(0, weight=0)
        self.inputs_frame.rowconfigure(1, weight=0)
        self.inputs_frame.rowconfigure(2, weight=0)
        self.inputs_frame.rowconfigure(3, weight=1)

        # BagIt-only input group
        self.bagit_inputs = ttk.LabelFrame(self.inputs_frame, text="Input (TIFF/WAV/SRT)", padding=12)
        self.bagit_inputs.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._build_bagit_inputs()

        # ProRes input group
        self.prores_inputs = ttk.LabelFrame(self.inputs_frame, text="ProRes Input (optional)", padding=12)
        self.prores_inputs.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._build_prores_inputs()

        # Bottom: actions + logs
        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=0)
        bottom.columnconfigure(1, weight=1)

        actions = ttk.Frame(bottom)
        actions.grid(row=0, column=0, sticky="w")

        self.auto_verify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(actions, text="nach Build automatisch verifizieren", variable=self.auto_verify_var).pack(
            side="top", anchor="w"
        )

        btn_row = ttk.Frame(actions)
        btn_row.pack(side="top", pady=(8, 0), anchor="w")

        ttk.Button(btn_row, text="Build BagIt", command=self._on_build).pack(side="left")
        ttk.Button(btn_row, text="Verify BagIt", command=self._on_verify).pack(side="left", padx=8)

        self.status_var = tk.StringVar(value="Bereit.")
        ttk.Label(bottom, textvariable=self.status_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.log_text = tk.Text(bottom, height=10, wrap="word")
        self.log_text.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        bottom.rowconfigure(0, weight=1)
        bottom.rowconfigure(1, weight=0)
        self.log_text.configure(state="disabled")

        # Log initial hint
        self._append_log("INFO", "Wähle Inputs, dann Build. Output wird als BagIt-Ordner erstellt.")

    def _build_bagit_inputs(self) -> None:
        frm = self.bagit_inputs
        for c in range(4):
            frm.columnconfigure(c, weight=1 if c == 2 else 0)

        # TIFF dir
        ttk.Label(frm, text="TIFF Frames Ordner:").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.tiff_dir_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.tiff_dir_var).grid(row=0, column=2, sticky="ew", pady=(0, 6))
        ttk.Button(frm, text="Wählen…", command=self._pick_tiff_dir).grid(row=0, column=3, padx=8)

        # Audio dir
        ttk.Label(frm, text="Audio WAV Ordner:").grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.audio_dir_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.audio_dir_var).grid(row=1, column=2, sticky="ew", pady=(0, 6))
        ttk.Button(frm, text="Wählen…", command=self._pick_audio_dir).grid(row=1, column=3, padx=8)

        # SRT file
        ttk.Label(frm, text="SRT Untertitel Datei:").grid(row=2, column=0, sticky="w", pady=(0, 6))
        self.srt_path_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.srt_path_var).grid(row=2, column=2, sticky="ew", pady=(0, 6))
        ttk.Button(frm, text="Wählen…", command=self._pick_srt_file).grid(row=2, column=3, padx=8)

        # Video fps
        ttk.Label(frm, text="Video FPS:").grid(row=3, column=0, sticky="w")
        self.video_fps_var = tk.StringVar(value="25.0")
        ttk.Entry(frm, textvariable=self.video_fps_var).grid(row=3, column=2, sticky="w")

    def _build_prores_inputs(self) -> None:
        frm = self.prores_inputs
        for c in range(4):
            frm.columnconfigure(c, weight=1 if c == 2 else 0)

        ttk.Label(frm, text="ProRes Datei:").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.prores_path_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.prores_path_var).grid(row=0, column=2, sticky="ew", pady=(0, 6))
        ttk.Button(frm, text="Wählen…", command=self._pick_prores_file).grid(row=0, column=3, padx=8)

        ttk.Label(frm, text="Frame-Range (z.B. 1-240):").grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.frame_range_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.frame_range_var).grid(row=1, column=2, sticky="w", pady=(0, 6))

        ttk.Label(frm, text="Target TIFF:").grid(row=2, column=0, sticky="w", pady=(0, 6))
        self.target_tiff_var = tk.StringVar(value="keep")
        ttk.Combobox(frm, textvariable=self.target_tiff_var, values=["keep", "2k", "4k"], state="readonly").grid(
            row=2, column=2, sticky="w", pady=(0, 6)
        )

        self.audio_split_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Audio Split (Mono pro Kanal)", variable=self.audio_split_var).grid(
            row=3, column=0, sticky="w"
        )

        ttk.Label(frm, text="Video FPS (optional):").grid(row=3, column=1, sticky="w")
        self.video_fps_prores_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.video_fps_prores_var).grid(row=3, column=2, sticky="w")

    def _set_mode(self, mode: str) -> None:
        if mode == "bagit-only":
            self.bagit_inputs.grid()
            self.prores_inputs.grid_remove()
        else:
            self.prores_inputs.grid()
            self.bagit_inputs.grid_remove()

    def _pick_output_dir(self) -> None:
        p = filedialog.askdirectory(title="Ausgabe-BagIt Ordner wählen")
        if p:
            self.output_var.set(str(Path(p).resolve()))

    def _pick_tiff_dir(self) -> None:
        p = filedialog.askdirectory(title="TIFF Frames Ordner wählen")
        if p:
            self.tiff_dir_var.set(str(Path(p).resolve()))

    def _pick_audio_dir(self) -> None:
        p = filedialog.askdirectory(title="Audio WAV Ordner wählen")
        if p:
            self.audio_dir_var.set(str(Path(p).resolve()))

    def _pick_srt_file(self) -> None:
        p = filedialog.askopenfilename(title="SRT Datei wählen", filetypes=[("SRT files", "*.srt"), ("All", "*.*")])
        if p:
            self.srt_path_var.set(str(Path(p).resolve()))

    def _pick_prores_file(self) -> None:
        p = filedialog.askopenfilename(title="ProRes Datei wählen", filetypes=[("Media files", "*.mov *.mxf *.mp4 *.m4v"), ("All", "*.*")])
        if p:
            self.prores_path_var.set(str(Path(p).resolve()))

    def _append_log(self, level: str, msg: str) -> None:
        # level is only displayed; no color to keep it portable.
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{level}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_queue(self) -> None:
        try:
            while True:
                level, msg = self._queue.get_nowait()
                self._append_log(level, msg)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _set_busy(self, busy: bool) -> None:
        # Disable the window main action buttons by flipping the cursor & status.
        # Keeping it simple: just toggle the root disabled state for child buttons.
        for child in self.winfo_children():
            # Not all widgets are Buttons; ignore.
            try:
                if isinstance(child, ttk.Button):
                    child.configure(state="disabled" if busy else "normal")
            except Exception:
                pass
        self.status_var.set("Bitte warten..." if busy else "Bereit.")
        self.config(cursor="watch" if busy else "")

    def _show_error_async(self, title: str, message: str) -> None:
        # Tkinter UI calls must run in the main thread.
        self.after(0, lambda: messagebox.showerror(title, message))

    def _gather_state(self) -> GuiState:
        output_dir = Path(self.output_var.get()).expanduser().resolve()
        tagmanifest = bool(self.tagmanifest_var.get())
        subtitle_timecode_rebase = bool(self.rebase_var.get())
        audio_normalize = bool(self.audio_normalize_var.get())

        mode = str(self.mode_var.get())

        video_fps: Optional[float] = None
        tiff_dir = audio_dir = srt_path = prores_path = None
        frame_range = None
        if mode == "bagit-only":
            tiff_dir = Path(self.tiff_dir_var.get()).expanduser().resolve() if self.tiff_dir_var.get().strip() else None
            audio_dir = Path(self.audio_dir_var.get()).expanduser().resolve() if self.audio_dir_var.get().strip() else None
            srt_path = Path(self.srt_path_var.get()).expanduser().resolve() if self.srt_path_var.get().strip() else None
            if self.video_fps_var.get().strip():
                video_fps = float(self.video_fps_var.get().strip())
        else:
            prores_path = Path(self.prores_path_var.get()).expanduser().resolve() if self.prores_path_var.get().strip() else None
            if self.video_fps_prores_var.get().strip():
                video_fps = float(self.video_fps_prores_var.get().strip())
            if self.frame_range_var.get().strip():
                frame_range = self.frame_range_var.get().strip()

        return GuiState(
            mode=mode,
            output_dir=output_dir,
            tagmanifest=tagmanifest,
            subtitle_timecode_rebase=subtitle_timecode_rebase,
            audio_normalize=audio_normalize,
            tiff_dir=tiff_dir,
            audio_dir=audio_dir,
            srt_path=srt_path,
            video_fps=video_fps,
            prores_path=prores_path,
            frame_range=frame_range,
            target_tiff=str(self.target_tiff_var.get()),
            audio_split=bool(self.audio_split_var.get()),
        )

    def _run_build(self, state: GuiState) -> None:
        # Build is long running; run in background.
        self._queue.put(("INFO", f"Starte Build (Mode={state.mode}) ..."))
        kwargs: dict[str, object] = dict(
            output_dir=state.output_dir,
            tagmanifest=state.tagmanifest,
            input_prores=str(state.prores_path) if state.prores_path else None,
            input_tiff_dir=str(state.tiff_dir) if state.tiff_dir else None,
            input_audio_dir=str(state.audio_dir) if state.audio_dir else None,
            input_srt=str(state.srt_path) if state.srt_path else None,
            video_fps=state.video_fps,
            frame_range=state.frame_range,
            audio_normalize=state.audio_normalize,
            subtitle_timecode_rebase=state.subtitle_timecode_rebase,
            audio_split=state.audio_split,
            target_tiff=state.target_tiff,
        )
        build_dcdm_bagit(**kwargs)
        self._queue.put(("INFO", "Build fertig."))

        if self.auto_verify_var.get():
            self._queue.put(("INFO", "Starte Verify ..."))
            verify_bag(bag_dir=state.output_dir)
            self._queue.put(("INFO", "Verify OK."))

    def _on_build(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Läuft bereits", "Ein Vorgang ist bereits aktiv.")
            return
        state = self._gather_state()

        # Quick validation for UX.
        if state.mode == "bagit-only":
            missing = []
            if not state.tiff_dir:
                missing.append("TIFF dir")
            if not state.audio_dir:
                missing.append("Audio dir")
            if not state.srt_path:
                missing.append("SRT Datei")
            if state.video_fps is None:
                missing.append("Video FPS")
            if missing:
                messagebox.showerror("Fehlende Inputs", "Bitte ergänzen: " + ", ".join(missing))
                return
        else:
            if not state.prores_path:
                messagebox.showerror("Fehlende Inputs", "Bitte ProRes Datei auswählen.")
                return

        self._set_busy(True)
        self._worker = threading.Thread(target=self._safe_worker_wrapper, args=(state,))
        self._worker.start()

    def _safe_worker_wrapper(self, state: GuiState) -> None:
        try:
            self._run_build(state)
        except Exception as e:
            tb = traceback.format_exc()
            self._queue.put(("ERROR", f"Build/Verify fehlgeschlagen: {e}"))
            self._queue.put(("DEBUG", tb))
            self._show_error_async("Fehler", f"{e}\n\nDetails siehe Log.")
        finally:
            self.after(0, lambda: self._set_busy(False))

    def _on_verify(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Läuft bereits", "Ein Vorgang ist bereits aktiv.")
            return

        state = self._gather_state()
        bag_dir = state.output_dir
        if not (bag_dir / "manifest-sha256.txt").exists():
            messagebox.showerror("Bag nicht gefunden", f"Keine manifest-sha256.txt in: {bag_dir}")
            return

        self._set_busy(True)
        self._worker = threading.Thread(target=self._safe_verify_worker, args=(bag_dir,))
        self._worker.start()

    def _safe_verify_worker(self, bag_dir: Path) -> None:
        try:
            self._queue.put(("INFO", "Verify startet ..."))
            verify_bag(bag_dir=bag_dir)
            self._queue.put(("INFO", "Verify OK."))
        except Exception as e:
            tb = traceback.format_exc()
            self._queue.put(("ERROR", f"Verify fehlgeschlagen: {e}"))
            self._queue.put(("DEBUG", tb))
            self._show_error_async("Fehler", f"{e}\n\nDetails siehe Log.")
        finally:
            self.after(0, lambda: self._set_busy(False))


def main() -> None:
    app = DcdmBagItGui()
    app.mainloop()


if __name__ == "__main__":
    main()

