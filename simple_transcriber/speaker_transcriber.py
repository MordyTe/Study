"""תמלול מיקרופונים — Simple Mic Transcriber.

Records straight from the sound card's *inputs* (never from the speakers),
lets you see every input channel live with its own level meter and choose
which ones to transcribe, and transcribes locally with the Hebrew ivrit.ai
Whisper model. Lines are shown in the window and saved to a text file.

Run it with start.bat (double-click).
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from datetime import datetime

import numpy as np
import tkinter as tk
from tkinter import scrolledtext, ttk

from core import (
    TARGET_SR,
    Chunker,
    TranscriptWriter,
    build_device_list,
    channel_levels,
    channels_for,
    collapse_repeats,
    format_line,
    keep_segment,
    level,
    load_glossary,
    load_settings,
    mix_down,
    new_transcript_path,
    normalize_gain,
    pick_default,
    resample,
    save_settings,
    select_channels,
)

# --- the only things you might ever want to change ---------------------------
MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"  # Hebrew fine-tune of Whisper
NO_SIGNAL_WARN_S = 6.0  # warn if the chosen channels are completely silent this long
# -----------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(HERE, "transcripts")
SETTINGS_PATH = os.path.join(HERE, "settings.json")
GLOSSARY_PATH = os.path.join(HERE, "glossary.txt")
LOG_PATH = os.path.join(HERE, "speaker_transcriber.log")

# Decoding settings tuned for accuracy and against invented text.
DECODE = dict(
    language="he",
    task="transcribe",
    beam_size=5,
    best_of=5,
    temperature=[0.0, 0.2, 0.4],
    condition_on_previous_text=False,  # stops one mistake from snowballing
    vad_filter=True,  # only real speech reaches the model
    vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=300),
    no_speech_threshold=0.6,
    log_prob_threshold=-1.0,
    compression_ratio_threshold=2.4,
    word_timestamps=True,
    hallucination_silence_threshold=1.0,  # skip text "heard" inside silence
)

# pythonw has no console: send errors to a log file instead of losing them.
if sys.stderr is None or sys.stdout is None:
    _log = open(LOG_PATH, "a", encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log


def enable_asio_if_safe(settings: dict) -> bool:
    """Turn on sounddevice's ASIO support (all channels of a pro sound card).

    The ASIO driver is probed in a separate process first, so a misbehaving
    driver can never crash this window. Must run before sounddevice is imported.
    """

    if os.name != "nt" or settings.get("use_asio", True) is False:
        return False
    code = (
        "import os; os.environ['SD_ENABLE_ASIO']='1'; import sounddevice as sd; "
        "sd.query_devices(); print('OK')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and "OK" in result.stdout:
            os.environ["SD_ENABLE_ASIO"] = "1"
            return True
    except Exception as exc:
        print(f"ASIO probe failed: {exc}", file=sys.stderr)
    return False


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


def make_resampler(orig_sr: int):
    """Streaming high-quality resampler to 16 kHz (keeps state between blocks,
    so there are no clicks at block edges). Falls back to the simple one."""

    if orig_sr == TARGET_SR:
        return lambda x: np.asarray(x, dtype=np.float32)
    try:
        import soxr

        stream = soxr.ResampleStream(orig_sr, TARGET_SR, 1, dtype="float32", quality="HQ")
        return lambda x: stream.resample_chunk(np.ascontiguousarray(x, dtype=np.float32))
    except Exception:
        return lambda x: resample(x, orig_sr, TARGET_SR)


class Session:
    """One transcription run: which channels, mixed or per channel."""

    def __init__(self, channels, per_channel, samplerate, out: "queue.Queue"):
        self.channels = channels
        self.per_channel = per_channel
        self.out = out
        if per_channel:
            self.streams = {f"ערוץ {c}": (Chunker(), make_resampler(samplerate)) for c in channels}
        else:
            self.streams = {None: (Chunker(), make_resampler(samplerate))}
        self.silent_s = 0.0

    def feed(self, data: np.ndarray, block_s: float) -> float:
        chosen = select_channels(data, self.channels)
        if chosen.shape[1] == 0:
            return 0.0
        mix = mix_down(chosen)
        lvl = level(mix)
        self.silent_s = self.silent_s + block_s if lvl == 0.0 else 0.0
        if self.per_channel:
            present = [c for c in self.channels if c <= data.shape[1]]
            for pos, c in enumerate(present):
                chunker, rs = self.streams[f"ערוץ {c}"]
                for chunk in chunker.feed(rs(chosen[:, pos])):
                    self.out.put((f"ערוץ {c}", chunk))
        else:
            chunker, rs = self.streams[None]
            for chunk in chunker.feed(rs(mix)):
                self.out.put((None, chunk))
        return lvl

    def flush(self):
        for speaker, (chunker, _rs) in self.streams.items():
            last = chunker.flush()
            if last is not None:
                self.out.put((speaker, last))


class App:
    def __init__(self, root: tk.Tk, sd):
        self.root = root
        self.sd = sd
        self.settings = load_settings(SETTINGS_PATH)
        self.model = None
        self.device_label = ""
        self.entries = {}
        self.current = None
        self.stream = None
        self.audio_q: "queue.Queue" = queue.Queue(maxsize=200)
        self.chunks: "queue.Queue" = queue.Queue()
        self.ui: "queue.Queue" = queue.Queue()
        self.session = None
        self.transcribing = False
        self.stop_requested = False
        self.writer = None
        self.warned = False

        root.title("תמלול מיקרופונים")
        root.geometry("920x700")
        root.configure(bg="#14181d")
        style = dict(bg="#14181d", fg="#e6edf3")

        # --- row 1: sound card input ---
        src = tk.Frame(root, bg="#14181d")
        src.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(src, text=":כרטיס קול / כניסה", font=("Segoe UI", 11), **style).pack(side="right")
        self.source_var = tk.StringVar()
        self.source_box = ttk.Combobox(src, textvariable=self.source_var, state="readonly",
                                       font=("Segoe UI", 11), width=56)
        self.source_box.pack(side="right", padx=8)
        self.source_box.bind("<<ComboboxSelected>>", self._on_device_selected)
        self.refresh_btn = tk.Button(src, text="⟳ רענן", font=("Segoe UI", 10), relief="flat",
                                     bg="#30363d", fg="white", command=self.refresh_devices)
        self.refresh_btn.pack(side="right")

        # --- channels panel ---
        ch_frame = tk.Frame(root, bg="#14181d")
        ch_frame.pack(fill="x", padx=12, pady=(10, 0))
        head = tk.Frame(ch_frame, bg="#14181d")
        head.pack(fill="x")
        tk.Label(head, text=":ערוצים — דברו במיקרופון וראו איזה פס זז, וסמנו אותו",
                 font=("Segoe UI", 11), **style).pack(side="right")
        self.all_btn = tk.Button(head, text="הכל", font=("Segoe UI", 9), relief="flat",
                                 bg="#30363d", fg="white", command=lambda: self._set_all(True))
        self.all_btn.pack(side="right", padx=(8, 2))
        self.none_btn = tk.Button(head, text="נקה", font=("Segoe UI", 9), relief="flat",
                                  bg="#30363d", fg="white", command=lambda: self._set_all(False))
        self.none_btn.pack(side="right", padx=2)
        self.per_channel_var = tk.BooleanVar(value=bool(self.settings.get("per_channel", True)))
        self.per_channel_chk = tk.Checkbutton(
            head, text="תמלול נפרד לכל ערוץ (מציין מי דיבר)", variable=self.per_channel_var,
            font=("Segoe UI", 10), bg="#14181d", fg="#e6edf3", selectcolor="#30363d",
            activebackground="#14181d", activeforeground="#e6edf3", command=self._save_channels,
        )
        self.per_channel_chk.pack(side="left")
        self.ch_grid = tk.Frame(ch_frame, bg="#14181d")
        self.ch_grid.pack(fill="x", pady=(6, 0))
        self.ch_vars, self.ch_meters, self.ch_checks = [], [], []

        # --- row 2: start/stop + overall meter + status ---
        bar = tk.Frame(root, bg="#14181d")
        bar.pack(fill="x", padx=12, pady=10)
        self.btn = tk.Button(
            bar, text="▶  התחל תמלול", font=("Segoe UI", 14, "bold"), width=16,
            bg="#2ea043", fg="white", activebackground="#238636", relief="flat",
            command=self.toggle,
        )
        self.btn.pack(side="right")
        tk.Button(bar, text="📁 תיקיית תמלולים", font=("Segoe UI", 11), relief="flat",
                  bg="#30363d", fg="white", command=self.open_folder).pack(side="right", padx=10)
        self.meter = tk.Canvas(bar, width=140, height=16, bg="#0d1117", highlightthickness=0)
        self.meter.pack(side="left")
        self.status = tk.Label(bar, text="", font=("Segoe UI", 11), bg="#14181d",
                               fg="#9da7b3", anchor="e", wraplength=430, justify="right")
        self.status.pack(side="right", fill="x", expand=True, padx=10)

        # --- transcript ---
        self.text = scrolledtext.ScrolledText(
            root, font=("Segoe UI", 14), wrap="word", bg="#0d1117", fg="#e6edf3",
            insertbackground="white", relief="flat", padx=12, pady=10,
        )
        self.text.tag_configure("rtl", justify="right")
        self.text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        threading.Thread(target=self._process_loop, daemon=True).start()
        self.refresh_devices()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._drain_ui)

    # ------------------------------------------------------------------ devices
    def refresh_devices(self):
        try:
            devices = [dict(d, index=i) for i, d in enumerate(self.sd.query_devices())]
            hostapis = [dict(h) for h in self.sd.query_hostapis()]
            entries = build_device_list(devices, hostapis)
        except Exception as exc:
            self.status.config(text=f"לא ניתן לקרוא את כרטיסי הקול: {exc}")
            return
        self.entries = {e["label"]: e for e in entries}
        self.source_box["values"] = list(self.entries)
        if not entries:
            self.status.config(text="לא נמצאו כניסות שמע. חברו את כרטיס הקול ולחצו 'רענן'.")
            return
        choice = pick_default(entries, self.settings.get("device_key"), hostapis)
        self.source_var.set(choice["label"])
        self._open_device(choice)

    def _on_device_selected(self, _event=None):
        entry = self.entries.get(self.source_var.get())
        if entry:
            self.settings["device_key"] = entry["key"]
            self._persist()
            self._open_device(entry)

    def _close_stream(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def _open_device(self, entry):
        self._close_stream()
        self.current = entry
        self._build_channels(entry)
        try:
            self.stream = self.sd.InputStream(
                device=entry["index"], channels=entry["channels"],
                samplerate=entry["samplerate"], dtype="float32",
                blocksize=max(1, entry["samplerate"] // 10), callback=self._audio_cb,
            )
            self.stream.start()
            self.status.config(text="בדיקת ערוצים פעילה: דברו במיקרופון, סמנו את הערוצים שזזים, "
                                    "ולחצו 'התחל תמלול'.")
        except Exception as exc:
            self.stream = None
            hint = (" ייתכן שה‑ASIO תפוס ע\"י תוכנה אחרת (vMix/OBS) — בחרו את אותו כרטיס בגרסת WASAPI."
                    if entry["api"] == "ASIO" else "")
            self.status.config(text=f"לא ניתן לפתוח את הכניסה: {exc}.{hint}")

    def _audio_cb(self, indata, frames, time_info, status):  # audio thread: keep it tiny
        try:
            self.audio_q.put_nowait(indata.copy())
        except queue.Full:
            pass

    # ----------------------------------------------------------------- channels
    def _build_channels(self, entry):
        for w in self.ch_grid.winfo_children():
            w.destroy()
        self.ch_vars, self.ch_meters, self.ch_checks = [], [], []
        chosen = set(channels_for(self.settings, entry["key"], entry["channels"]))
        per_row = 6
        for i in range(entry["channels"]):
            cell = tk.Frame(self.ch_grid, bg="#14181d")
            cell.grid(row=i // per_row, column=per_row - 1 - (i % per_row), padx=10, pady=2, sticky="e")
            var = tk.BooleanVar(value=(i + 1) in chosen)
            chk = tk.Checkbutton(
                cell, text=f"ערוץ {i + 1}", variable=var, font=("Segoe UI", 10),
                bg="#14181d", fg="#e6edf3", selectcolor="#30363d", activebackground="#14181d",
                activeforeground="#e6edf3", command=self._save_channels,
            )
            chk.pack(side="top", anchor="e")
            meter = tk.Canvas(cell, width=80, height=8, bg="#0d1117", highlightthickness=0)
            meter.pack(side="top", anchor="e", pady=(0, 4))  # directly under its own checkbox
            self.ch_vars.append(var)
            self.ch_meters.append(meter)
            self.ch_checks.append(chk)

    def selected_channels(self):
        return [i + 1 for i, v in enumerate(self.ch_vars) if v.get()]

    def _save_channels(self):
        if self.current:
            self.settings.setdefault("channels", {})[self.current["key"]] = self.selected_channels()
        self.settings["per_channel"] = bool(self.per_channel_var.get())
        self._persist()

    def _set_all(self, on: bool):
        for v in self.ch_vars:
            v.set(on)
        self._save_channels()

    def _persist(self):
        try:
            save_settings(SETTINGS_PATH, self.settings)
        except OSError:
            pass

    # ------------------------------------------------------------- processing
    def _process_loop(self):
        """Always running: meters for every channel; feeds the session if one is active."""

        while True:
            try:
                data = self.audio_q.get(timeout=0.3)
            except queue.Empty:
                data = None
            session = self.session
            if data is not None:
                data = np.asarray(data, dtype=np.float32)
                if data.ndim == 1:
                    data = data[:, None]
                self.ui.put(("levels", channel_levels(data)))
                if session is not None:
                    sr = self.current["samplerate"] if self.current else 48000
                    lvl = session.feed(data, data.shape[0] / sr)
                    self.ui.put(("level", lvl))
                    if session.silent_s >= NO_SIGNAL_WARN_S and not self.warned:
                        self.warned = True
                        self.set_status("⚠ לא מגיע קול מהערוצים שסומנו — בדקו בפסים איזה ערוץ זז")
                    elif lvl > 0 and self.warned:
                        self.warned = False
                        self.set_status(self._listening_text(session))
            if session is not None and self.stop_requested:
                session.flush()
                self.session = None
                self.stop_requested = False
                self.chunks.put(None)  # tells the transcriber to finish

    def _transcribe_loop(self):
        hotwords = ", ".join(load_glossary(GLOSSARY_PATH)) or None
        while True:
            item = self.chunks.get()
            if item is None:
                break
            speaker, chunk = item
            try:
                kwargs = dict(DECODE)
                if hotwords:
                    kwargs["hotwords"] = hotwords
                segments, _ = self.model.transcribe(normalize_gain(chunk), **kwargs)
                parts = [
                    collapse_repeats(s.text.strip())
                    for s in segments
                    if keep_segment(s.text, s.avg_logprob, s.no_speech_prob, s.compression_ratio)
                ]
                text = " ".join(p for p in parts if p).strip()
            except Exception as exc:
                self.set_status(f"שגיאת תמלול: {exc}")
                continue
            if text:
                line = format_line(text, datetime.now(), speaker)
                self.writer.write_line(line)
                self.ui.put(("line", line))
        self.set_status(f"נעצר. התמלול נשמר: {os.path.basename(self.writer.path)}")
        self.ui.put(("stopped", None))

    # ----------------------------------------------------------------- UI glue
    def set_status(self, msg: str):
        self.ui.put(("status", msg))

    def _listening_text(self, session):
        chs = ", ".join(str(c) for c in session.channels)
        return f"מתמלל ערוצים {chs}  ({self.device_label})"

    def _draw_bar(self, canvas, width, height, value, color):
        canvas.delete("all")
        if value > 0:
            canvas.create_rectangle(0, 0, int(width * value), height, fill=color, width=0)

    def _drain_ui(self):
        try:
            while True:
                kind, value = self.ui.get_nowait()
                if kind == "status":
                    self.status.config(text=value)
                elif kind == "line":
                    self.text.insert("end", "‏" + value + "\n", "rtl")
                    self.text.see("end")
                elif kind == "levels":
                    for i, meter in enumerate(self.ch_meters):
                        v = value[i] if i < len(value) else 0.0
                        on = i < len(self.ch_vars) and self.ch_vars[i].get()
                        self._draw_bar(meter, 80, 8, v, "#2ea043" if on else "#6e7681")
                elif kind == "level":
                    color = "#2ea043" if value < 0.75 else ("#d29922" if value < 0.92 else "#da3633")
                    self._draw_bar(self.meter, 140, 16, value, color)
                elif kind == "stopped":
                    self._set_running_ui(False)
        except queue.Empty:
            pass
        self.root.after(80, self._drain_ui)

    def _set_running_ui(self, on: bool):
        state = "disabled" if on else "normal"
        self.source_box.config(state="disabled" if on else "readonly")
        for w in [self.refresh_btn, self.all_btn, self.none_btn, self.per_channel_chk, *self.ch_checks]:
            w.config(state=state)
        if on:
            self.btn.config(text="■  עצור", bg="#da3633", activebackground="#b62324")
        else:
            self.btn.config(text="▶  התחל תמלול", bg="#2ea043", activebackground="#238636")
            self._draw_bar(self.meter, 140, 16, 0.0, "#2ea043")

    def open_folder(self):
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        if os.name == "nt":
            os.startfile(TRANSCRIPTS_DIR)  # type: ignore[attr-defined]

    # ------------------------------------------------------------ start / stop
    def toggle(self):
        if self.transcribing:
            self.transcribing = False
            self.stop_requested = True
            self.set_status("עוצר… (מסיים לתמלל את מה שכבר נקלט)")
            return
        if self.stream is None or self.current is None:
            self.status.config(text="בחרו כרטיס קול / כניסה שנפתחה בהצלחה.")
            return
        channels = self.selected_channels()
        if not channels:
            self.status.config(text="סמנו לפחות ערוץ אחד.")
            return
        self._save_channels()
        self.transcribing = True
        self.stop_requested = False
        self.warned = False
        self._set_running_ui(True)
        self.writer = TranscriptWriter(new_transcript_path(TRANSCRIPTS_DIR, datetime.now()))
        threading.Thread(
            target=self._start_worker, args=(channels, bool(self.per_channel_var.get())), daemon=True
        ).start()

    def _start_worker(self, channels, per_channel):
        try:
            if self.model is None:
                self.model, self.device_label = load_model(self.set_status)
        except Exception as exc:
            self.transcribing = False
            self.set_status(f"שגיאה בטעינת המודל: {exc}")
            self.ui.put(("stopped", None))
            return
        if not self.transcribing:  # stopped while the model was loading
            self.stop_requested = False
            self.set_status("נעצר.")
            self.ui.put(("stopped", None))
            return
        threading.Thread(target=self._transcribe_loop, daemon=True).start()
        session = Session(channels, per_channel, self.current["samplerate"], self.chunks)
        self.set_status(self._listening_text(session))
        self.session = session

    def on_close(self):
        self.transcribing = False
        self.stop_requested = True
        self._close_stream()
        self.root.after(300, self.root.destroy)


def main():
    settings = load_settings(SETTINGS_PATH)
    enable_asio_if_safe(settings)  # before importing sounddevice
    import sounddevice as sd

    root = tk.Tk()
    App(root, sd)
    root.mainloop()


if __name__ == "__main__":
    main()
