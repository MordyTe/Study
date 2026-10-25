"""תמלול מהרמקולים — Speaker Transcriber.

A small window with one button. It records whatever is playing through the
computer's default speakers (Windows WASAPI loopback — so any mic that is
monitored on the speakers gets transcribed), transcribes it locally with the
Hebrew ivrit.ai Whisper model, shows the text, and saves it to a text file.

No mixer, no settings, no API keys. Run it with start.bat (double-click).
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import warnings
from datetime import datetime

import numpy as np
import tkinter as tk
from tkinter import scrolledtext

from core import (
    TARGET_SR,
    Chunker,
    TranscriptWriter,
    format_line,
    new_transcript_path,
    resample,
    to_mono,
)

# --- the only things you might ever want to change ---------------------------
MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"  # Hebrew fine-tune of Whisper
CAPTURE_SR = 48000
# -----------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(HERE, "transcripts")
LOG_PATH = os.path.join(HERE, "speaker_transcriber.log")

# pythonw has no console: send errors to a log file instead of losing them.
if sys.stderr is None or sys.stdout is None:
    _log = open(LOG_PATH, "a", encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

warnings.filterwarnings("ignore", module="soundcard")  # "data discontinuity" noise


def load_model(status):
    """Load the model on the GPU if one works, otherwise on the CPU — automatically."""

    from faster_whisper import WhisperModel

    try:
        import ctranslate2

        has_gpu = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        has_gpu = False

    if has_gpu:
        try:
            status("טוען מודל על כרטיס המסך…")
            model = WhisperModel(MODEL, device="cuda", compute_type="float16")
            # Warm-up: missing CUDA libraries only show up on the first run.
            list(model.transcribe(np.zeros(TARGET_SR, np.float32), language="he")[0])
            return model, "GPU"
        except Exception as exc:
            print(f"GPU unavailable, falling back to CPU: {exc}", file=sys.stderr)

    status("טוען מודל (בפעם הראשונה מוריד ~1.5GB, זה לוקח כמה דקות)…")
    return WhisperModel(MODEL, device="cpu", compute_type="int8"), "CPU"


def _com_init():
    """soundcard uses COM on Windows; each new thread must initialise it."""

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.ole32.CoInitializeEx(None, 0)
        except Exception:
            pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.model = None
        self.device_label = ""
        self.running = False
        self.chunks: "queue.Queue" = queue.Queue()
        self.ui: "queue.Queue" = queue.Queue()
        self.writer = None

        root.title("תמלול מהרמקולים")
        root.geometry("760x520")
        root.configure(bg="#14181d")

        bar = tk.Frame(root, bg="#14181d")
        bar.pack(fill="x", padx=12, pady=10)

        self.btn = tk.Button(
            bar, text="▶  התחל תמלול", font=("Segoe UI", 14, "bold"), width=16,
            bg="#2ea043", fg="white", activebackground="#238636", relief="flat",
            command=self.toggle,
        )
        self.btn.pack(side="right")

        tk.Button(
            bar, text="📁 תיקיית תמלולים", font=("Segoe UI", 11), relief="flat",
            bg="#30363d", fg="white", command=self.open_folder,
        ).pack(side="right", padx=10)

        self.status = tk.Label(
            bar, text="מוכן. לחצו 'התחל תמלול'.", font=("Segoe UI", 11),
            bg="#14181d", fg="#9da7b3", anchor="e",
        )
        self.status.pack(side="right", fill="x", expand=True, padx=10)

        self.text = scrolledtext.ScrolledText(
            root, font=("Segoe UI", 14), wrap="word", bg="#0d1117", fg="#e6edf3",
            insertbackground="white", relief="flat", padx=12, pady=10,
        )
        self.text.tag_configure("rtl", justify="right")
        self.text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._drain_ui)

    # --- UI helpers (thread-safe through the ui queue) ---
    def set_status(self, msg: str):
        self.ui.put(("status", msg))

    def _drain_ui(self):
        try:
            while True:
                kind, value = self.ui.get_nowait()
                if kind == "status":
                    self.status.config(text=value)
                elif kind == "line":
                    self.text.insert("end", value + "\n", "rtl")
                    self.text.see("end")
                elif kind == "stopped":
                    self._set_button(False)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_ui)

    def _set_button(self, on: bool):
        if on:
            self.btn.config(text="■  עצור", bg="#da3633", activebackground="#b62324")
        else:
            self.btn.config(text="▶  התחל תמלול", bg="#2ea043", activebackground="#238636")

    def open_folder(self):
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        if os.name == "nt":
            os.startfile(TRANSCRIPTS_DIR)  # type: ignore[attr-defined]

    # --- start / stop ---
    def toggle(self):
        if self.running:
            self.running = False
            self.set_status("עוצר…")
            return
        self.running = True
        self._set_button(True)
        self.writer = TranscriptWriter(new_transcript_path(TRANSCRIPTS_DIR, datetime.now()))
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        try:
            if self.model is None:
                self.model, self.device_label = load_model(self.set_status)
        except Exception as exc:
            self.running = False
            self.set_status(f"שגיאה בטעינת המודל: {exc}")
            self.ui.put(("stopped", None))
            return
        threading.Thread(target=self._transcribe_loop, daemon=True).start()
        self._capture_loop()

    def _capture_loop(self):
        _com_init()
        try:
            import soundcard as sc

            speaker = sc.default_speaker()
            loopback = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        except Exception as exc:
            self.running = False
            self.set_status(f"לא נמצא התקן רמקולים: {exc}")
            self.chunks.put(None)
            self.ui.put(("stopped", None))
            return

        chunker = Chunker()
        self.set_status(f"מקשיב לרמקולים: {speaker.name}  ({self.device_label})")
        try:
            with loopback.recorder(samplerate=CAPTURE_SR) as rec:
                while self.running:
                    data = rec.record(numframes=CAPTURE_SR // 10)  # 100 ms
                    if data is None or len(data) == 0:
                        continue
                    mono = resample(to_mono(data), CAPTURE_SR, TARGET_SR)
                    for chunk in chunker.feed(mono):
                        self.chunks.put(chunk)
        except Exception as exc:
            self.set_status(f"שגיאת הקלטה: {exc}")
        finally:
            last = chunker.flush()
            if last is not None:
                self.chunks.put(last)
            self.chunks.put(None)  # tells the transcriber to finish
            self.running = False

    def _transcribe_loop(self):
        while True:
            chunk = self.chunks.get()
            if chunk is None:
                break
            try:
                segments, _ = self.model.transcribe(
                    chunk,
                    language="he",
                    beam_size=5,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                text = " ".join(s.text.strip() for s in segments).strip()
            except Exception as exc:
                self.set_status(f"שגיאת תמלול: {exc}")
                continue
            if text:
                line = format_line(text, datetime.now())
                self.writer.write_line(line)
                self.ui.put(("line", line))
        self.set_status(f"נעצר. התמלול נשמר: {os.path.basename(self.writer.path)}")
        self.ui.put(("stopped", None))

    def on_close(self):
        self.running = False
        self.root.after(300, self.root.destroy)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
