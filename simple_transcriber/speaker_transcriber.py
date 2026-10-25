"""תמלול מיקרופונים — Simple Mic Transcriber.

A small window with one button. It records straight from an audio *input*
device (the microphones / the mixer's USB / Dante / line-in) — so only the
mics are transcribed, never music, videos or Windows notifications. It
transcribes locally with the Hebrew ivrit.ai Whisper model, shows the text,
and saves it to a text file.

Pick the source once from the list, then tick which of its channels to record
(each channel has its own level meter, so you can see which one is your mic).
Optionally each channel is transcribed separately and every line says which
channel spoke. Choices are remembered. Run it with start.bat (double-click).
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
from tkinter import scrolledtext, ttk

from core import (
    TARGET_SR,
    Chunker,
    channel_levels,
    channels_for,
    TranscriptWriter,
    format_line,
    level,
    load_settings,
    mix_down,
    new_transcript_path,
    resample,
    save_settings,
    select_channels,
)

# --- the only things you might ever want to change ---------------------------
MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"  # Hebrew fine-tune of Whisper
CAPTURE_SR = 48000
NO_SIGNAL_WARN_S = 6.0  # warn if the chosen source is completely silent this long
# -----------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(HERE, "transcripts")
SETTINGS_PATH = os.path.join(HERE, "settings.json")
LOG_PATH = os.path.join(HERE, "speaker_transcriber.log")

LOOPBACK_LABEL = "🔊 כל מה שברמקולים (כולל מוזיקה והתראות)"

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


def _channel_count(device) -> int:
    try:
        n = int(device.channels)
        return n if n > 0 else 2
    except Exception:
        return 2


def list_sources():
    """Return ``{label: (device_id, is_loopback, channel_count)}`` plus the default label.

    Input devices first (microphones, mixer USB, Dante, line-in), then the
    speaker-loopback option last.
    """

    import soundcard as sc

    sources = {}
    for mic in sc.all_microphones(include_loopback=False):
        label = "🎙️ " + mic.name
        n = 2
        while label in sources:  # two devices with the same name
            label = f"🎙️ {mic.name} ({n})"
            n += 1
        sources[label] = (mic.id, False, _channel_count(mic))
    try:
        speaker = sc.default_speaker()
        sources[LOOPBACK_LABEL] = (str(speaker.name), True, _channel_count(speaker))
    except Exception:
        pass

    default = None
    try:
        default_name = sc.default_microphone().name
        default = next((l for l in sources if l == "🎙️ " + default_name), None)
    except Exception:
        pass
    return sources, default


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.model = None
        self.device_label = ""
        self.running = False
        self.chunks: "queue.Queue" = queue.Queue()
        self.ui: "queue.Queue" = queue.Queue()
        self.writer = None
        self.settings = load_settings(SETTINGS_PATH)
        self.sources = {}

        root.title("תמלול מיקרופונים")
        root.geometry("900x680")
        root.configure(bg="#14181d")

        # --- row 1: source picker + meter ---
        src = tk.Frame(root, bg="#14181d")
        src.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(src, text=":מקור שמע", font=("Segoe UI", 11), bg="#14181d",
                 fg="#e6edf3").pack(side="right")
        self.source_var = tk.StringVar()
        self.source_box = ttk.Combobox(src, textvariable=self.source_var, state="readonly",
                                       font=("Segoe UI", 11), width=48)
        self.source_box.pack(side="right", padx=8)
        self.source_box.bind("<<ComboboxSelected>>", self._on_source_selected)
        self.refresh_btn = tk.Button(src, text="⟳ רענן", font=("Segoe UI", 10), relief="flat",
                                     bg="#30363d", fg="white", command=self.refresh_sources)
        self.refresh_btn.pack(side="right")
        self.meter = tk.Canvas(src, width=170, height=16, bg="#0d1117", highlightthickness=0)
        self.meter.pack(side="left")
        tk.Label(src, text="עוצמה", font=("Segoe UI", 9), bg="#14181d",
                 fg="#9da7b3").pack(side="left", padx=4)

        # --- channels panel ---
        ch_frame = tk.Frame(root, bg="#14181d")
        ch_frame.pack(fill="x", padx=12, pady=(8, 0))
        head = tk.Frame(ch_frame, bg="#14181d")
        head.pack(fill="x")
        tk.Label(head, text=":ערוצים להקלטה", font=("Segoe UI", 11), bg="#14181d",
                 fg="#e6edf3").pack(side="right")
        self.all_btn = tk.Button(head, text="הכל", font=("Segoe UI", 9), relief="flat",
                                 bg="#30363d", fg="white", command=lambda: self._set_all(True))
        self.all_btn.pack(side="right", padx=(8, 2))
        self.none_btn = tk.Button(head, text="נקה", font=("Segoe UI", 9), relief="flat",
                                  bg="#30363d", fg="white", command=lambda: self._set_all(False))
        self.none_btn.pack(side="right", padx=2)
        self.per_channel_var = tk.BooleanVar(value=bool(self.settings.get("per_channel", False)))
        self.per_channel_chk = tk.Checkbutton(
            head, text="תמלול נפרד לכל ערוץ (בכל שורה: מאיזה ערוץ)", variable=self.per_channel_var,
            font=("Segoe UI", 10), bg="#14181d", fg="#e6edf3", selectcolor="#30363d",
            activebackground="#14181d", activeforeground="#e6edf3", command=self._save_channels,
        )
        self.per_channel_chk.pack(side="left")
        self.ch_grid = tk.Frame(ch_frame, bg="#14181d")
        self.ch_grid.pack(fill="x", pady=(4, 0))
        self.ch_vars = []    # BooleanVar per channel
        self.ch_meters = []  # Canvas per channel
        self.ch_checks = []

        # --- row 2: start/stop + status ---
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
            bar, text="בחרו מקור שמע ולחצו 'התחל תמלול'.", font=("Segoe UI", 11),
            bg="#14181d", fg="#9da7b3", anchor="e",
        )
        self.status.pack(side="right", fill="x", expand=True, padx=10)

        # --- transcript ---
        self.text = scrolledtext.ScrolledText(
            root, font=("Segoe UI", 14), wrap="word", bg="#0d1117", fg="#e6edf3",
            insertbackground="white", relief="flat", padx=12, pady=10,
        )
        self.text.tag_configure("rtl", justify="right")
        self.text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.refresh_sources()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._drain_ui)

    # --- sources ---
    def refresh_sources(self):
        try:
            self.sources, default = list_sources()
        except Exception as exc:
            self.sources, default = {}, None
            self.status.config(text=f"לא ניתן לקרוא את התקני השמע: {exc}")
        labels = list(self.sources)
        self.source_box["values"] = labels
        saved = self.settings.get("source")
        choice = saved if saved in self.sources else default or (labels[0] if labels else "")
        self.source_var.set(choice)
        self._build_channels()

    def _on_source_selected(self, _event=None):
        self.settings["source"] = self.source_var.get()
        self._persist()
        self._build_channels()

    def _persist(self):
        try:
            save_settings(SETTINGS_PATH, self.settings)
        except OSError:
            pass

    # --- channels ---
    def _build_channels(self):
        for w in self.ch_grid.winfo_children():
            w.destroy()
        self.ch_vars, self.ch_meters, self.ch_checks = [], [], []
        label = self.source_var.get()
        if label not in self.sources:
            return
        count = self.sources[label][2]
        chosen = set(channels_for(self.settings, label, count))
        per_row = 6
        for i in range(count):
            cell = tk.Frame(self.ch_grid, bg="#14181d")
            cell.grid(row=i // per_row, column=per_row - 1 - (i % per_row), padx=4, pady=2, sticky="e")
            var = tk.BooleanVar(value=(i + 1) in chosen)
            chk = tk.Checkbutton(
                cell, text=f"ערוץ {i + 1}", variable=var, font=("Segoe UI", 10),
                bg="#14181d", fg="#e6edf3", selectcolor="#30363d", activebackground="#14181d",
                activeforeground="#e6edf3", command=self._save_channels,
            )
            chk.pack(side="right")
            meter = tk.Canvas(cell, width=40, height=8, bg="#0d1117", highlightthickness=0)
            meter.pack(side="right", padx=(0, 2))
            self.ch_vars.append(var)
            self.ch_meters.append(meter)
            self.ch_checks.append(chk)

    def selected_channels(self):
        return [i + 1 for i, v in enumerate(self.ch_vars) if v.get()]

    def _save_channels(self):
        label = self.source_var.get()
        self.settings.setdefault("channels", {})[label] = self.selected_channels()
        self.settings["per_channel"] = bool(self.per_channel_var.get())
        self._persist()

    def _set_all(self, on: bool):
        for v in self.ch_vars:
            v.set(on)
        self._save_channels()

    def _draw_channel_meters(self, values):
        for i, meter in enumerate(self.ch_meters):
            meter.delete("all")
            v = values[i] if i < len(values) else 0.0
            if v > 0:
                color = "#2ea043" if self.ch_vars[i].get() else "#57606a"  # grey = not recorded
                meter.create_rectangle(0, 0, int(40 * v), 8, fill=color, width=0)

    # --- UI helpers (thread-safe through the ui queue) ---
    def set_status(self, msg: str):
        self.ui.put(("status", msg))

    def _draw_meter(self, value: float):
        self.meter.delete("all")
        width = int(170 * value)
        color = "#2ea043" if value < 0.75 else ("#d29922" if value < 0.92 else "#da3633")
        if width > 0:
            self.meter.create_rectangle(0, 0, width, 16, fill=color, width=0)

    def _drain_ui(self):
        try:
            while True:
                kind, value = self.ui.get_nowait()
                if kind == "status":
                    self.status.config(text=value)
                elif kind == "line":
                    self.text.insert("end", "\u200f" + value + "\n", "rtl")
                    self.text.see("end")
                elif kind == "level":
                    self._draw_meter(value)
                elif kind == "levels":
                    self._draw_channel_meters(value)
                elif kind == "stopped":
                    self._set_running_ui(False)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_ui)

    def _set_running_ui(self, on: bool):
        if on:
            self.btn.config(text="■  עצור", bg="#da3633", activebackground="#b62324")
            self.source_box.config(state="disabled")
            for w in [self.refresh_btn, self.all_btn, self.none_btn, self.per_channel_chk, *self.ch_checks]:
                w.config(state="disabled")
        else:
            self.btn.config(text="▶  התחל תמלול", bg="#2ea043", activebackground="#238636")
            self.source_box.config(state="readonly")
            for w in [self.refresh_btn, self.all_btn, self.none_btn, self.per_channel_chk, *self.ch_checks]:
                w.config(state="normal")
            self._draw_meter(0.0)
            self._draw_channel_meters([])

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
        label = self.source_var.get()
        if label not in self.sources:
            self.status.config(text="בחרו מקור שמע מהרשימה.")
            return
        channels = self.selected_channels()
        if not channels:
            self.status.config(text="סמנו לפחות ערוץ אחד להקלטה.")
            return
        self._save_channels()
        per_channel = bool(self.per_channel_var.get())
        self.running = True
        self._set_running_ui(True)
        self.writer = TranscriptWriter(new_transcript_path(TRANSCRIPTS_DIR, datetime.now()))
        device_id, is_loopback, _count = self.sources[label]
        threading.Thread(
            target=self._start_worker,
            args=(label, device_id, is_loopback, channels, per_channel),
            daemon=True,
        ).start()

    def _start_worker(self, label, device_id, is_loopback, channels, per_channel):
        try:
            if self.model is None:
                self.model, self.device_label = load_model(self.set_status)
        except Exception as exc:
            self.running = False
            self.set_status(f"שגיאה בטעינת המודל: {exc}")
            self.ui.put(("stopped", None))
            return
        threading.Thread(target=self._transcribe_loop, daemon=True).start()
        self._capture_loop(label, device_id, is_loopback, channels, per_channel)

    def _capture_loop(self, label, device_id, is_loopback, channels, per_channel):
        _com_init()
        try:
            import soundcard as sc

            source = sc.get_microphone(id=device_id, include_loopback=is_loopback)
        except Exception as exc:
            self.running = False
            self.set_status(f"לא ניתן לפתוח את מקור השמע: {exc}")
            self.chunks.put(None)
            self.ui.put(("stopped", None))
            return

        # One chunker for the mix, or one per channel (each line tagged with its channel).
        chunkers = {f"ערוץ {c}": Chunker() for c in channels} if per_channel else {None: Chunker()}
        ch_text = ", ".join(str(c) for c in channels)
        listening = f"מקשיב: {label.replace('🎙️ ', '')} — ערוצים {ch_text}  ({self.device_label})"
        self.set_status(listening)
        silent_s = 0.0
        warned = False
        try:
            with source.recorder(samplerate=CAPTURE_SR) as rec:
                while self.running:
                    data = rec.record(numframes=CAPTURE_SR // 10)  # 100 ms
                    if data is None or len(data) == 0:
                        continue
                    data = np.asarray(data, dtype=np.float32)
                    if data.ndim == 1:
                        data = data[:, None]
                    self.ui.put(("levels", channel_levels(data)))
                    chosen = select_channels(data, channels)
                    if chosen.shape[1] == 0:
                        continue
                    mono = resample(mix_down(chosen), CAPTURE_SR, TARGET_SR)
                    lvl = level(mono)
                    self.ui.put(("level", lvl))

                    # Completely silent source -> probably the wrong device.
                    silent_s = silent_s + 0.1 if lvl == 0.0 else 0.0
                    if silent_s >= NO_SIGNAL_WARN_S and not warned:
                        self.set_status("⚠ לא מגיע קול מהערוצים שנבחרו — בדקו בפסי העוצמה איזה ערוץ זז, או בחרו מקור אחר")
                        warned = True
                    elif lvl > 0.0 and warned:
                        self.set_status(listening)
                        warned = False

                    if per_channel:
                        for pos, c in enumerate(c for c in channels if c <= data.shape[1]):
                            sig = resample(chosen[:, pos], CAPTURE_SR, TARGET_SR)
                            for chunk in chunkers[f"ערוץ {c}"].feed(sig):
                                self.chunks.put((f"ערוץ {c}", chunk))
                    else:
                        for chunk in chunkers[None].feed(mono):
                            self.chunks.put((None, chunk))
        except Exception as exc:
            self.set_status(f"שגיאת הקלטה: {exc}")
        finally:
            for speaker, chunker in chunkers.items():
                last = chunker.flush()
                if last is not None:
                    self.chunks.put((speaker, last))
            self.chunks.put(None)  # tells the transcriber to finish
            self.running = False

    def _transcribe_loop(self):
        while True:
            item = self.chunks.get()
            if item is None:
                break
            speaker, chunk = item
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
                line = format_line(text, datetime.now(), speaker)
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
