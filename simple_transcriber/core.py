"""Pure logic for the speaker transcriber — no audio devices, no ASR model.

Kept separate from the window/capture code so it can be unit-tested anywhere.
Only depends on numpy.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from typing import List, Optional

import numpy as np

TARGET_SR = 16000  # what the Whisper model expects


def to_mono(data: np.ndarray) -> np.ndarray:
    """``[frames, channels]`` (or 1-D) float audio -> 1-D float32 mono."""

    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data.astype(np.float32, copy=False)


def mix_down(data: np.ndarray) -> np.ndarray:
    """Mix any input device down to mono.

    Mono/stereo devices are averaged. Multichannel devices (e.g. a 32-channel
    mixer USB/Dante interface) are *summed* and clipped instead: averaging 32
    channels where only one mic is active would shrink that mic ~32x, below
    the speech threshold.
    """

    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        return data
    if data.shape[1] <= 2:
        return data.mean(axis=1).astype(np.float32)
    return np.clip(data.sum(axis=1), -1.0, 1.0).astype(np.float32)


def select_channels(data: np.ndarray, channels: List[int]) -> np.ndarray:
    """Keep only the chosen channels (1-based numbers) of ``[frames, ch]`` audio.

    Numbers beyond what the device has are ignored. Returns ``[frames, k]``.
    """

    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    idx = [c - 1 for c in channels if 1 <= c <= data.shape[1]]
    return data[:, idx]


def channel_levels(data: np.ndarray) -> List[float]:
    """Meter value (see :func:`level`) for every channel of ``[frames, ch]`` audio."""

    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    return [level(data[:, i]) for i in range(data.shape[1])]


def channels_for(settings: dict, source: str, available: int) -> List[int]:
    """The saved channel choice for a source, limited to what it has; default all."""

    saved = (settings.get("channels") or {}).get(source)
    if isinstance(saved, list):
        valid = sorted({int(c) for c in saved if isinstance(c, int) and 1 <= c <= available})
        if valid:
            return valid
    return list(range(1, available + 1))


def level(signal: np.ndarray) -> float:
    """Loudness for the on-screen meter: 0.0 (silence) .. 1.0 (full scale),
    on a -60..0 dB scale so normal speech sits in the middle of the bar."""

    signal = np.asarray(signal, dtype=np.float32)
    if signal.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(signal * signal)))
    if rms <= 1e-6:
        return 0.0
    db = 20.0 * math.log10(rms)
    return max(0.0, min(1.0, (db + 60.0) / 60.0))


def resample(signal: np.ndarray, orig_sr: int, target_sr: int = TARGET_SR) -> np.ndarray:
    """Resample mono audio. Integer ratios (48k->16k) use block averaging, which
    doubles as a simple anti-alias filter; other ratios use linear interpolation."""

    signal = np.asarray(signal, dtype=np.float32)
    if orig_sr == target_sr or signal.size == 0:
        return signal
    if orig_sr % target_sr == 0:
        factor = orig_sr // target_sr
        usable = (signal.size // factor) * factor
        return signal[:usable].reshape(-1, factor).mean(axis=1).astype(np.float32)
    n_out = int(round(signal.size * target_sr / orig_sr))
    x_old = np.linspace(0.0, 1.0, num=signal.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, signal).astype(np.float32)


class Chunker:
    """Cut a continuous 16 kHz stream into speech chunks for the model.

    A chunk is emitted when speech is followed by ``silence_s`` of quiet (a
    natural pause), or when it reaches ``max_s`` (so long monologues still show
    up regularly). Pure silence is never emitted — only a short pre-roll is kept
    so the first syllable isn't clipped.
    """

    FRAME = 480  # 30 ms at 16 kHz

    def __init__(
        self,
        sample_rate: int = TARGET_SR,
        threshold: float = 0.004,
        silence_s: float = 0.8,
        min_s: float = 1.0,
        max_s: float = 15.0,
        preroll_s: float = 0.3,
    ):
        self.sr = sample_rate
        self.threshold = threshold
        self.silence_frames = int(silence_s * sample_rate / self.FRAME)
        self.min_samples = int(min_s * sample_rate)
        self.max_samples = int(max_s * sample_rate)
        self.preroll_frames = max(1, int(preroll_s * sample_rate / self.FRAME))
        self._frames: List[np.ndarray] = []
        self._pending = np.zeros(0, dtype=np.float32)
        self._has_speech = False
        self._quiet_run = 0

    def _is_loud(self, frame: np.ndarray) -> bool:
        return float(np.sqrt(np.mean(frame * frame))) > self.threshold

    def _take(self) -> np.ndarray:
        chunk = np.concatenate(self._frames) if self._frames else np.zeros(0, np.float32)
        self._frames = []
        self._has_speech = False
        self._quiet_run = 0
        return chunk

    def feed(self, signal: np.ndarray) -> List[np.ndarray]:
        """Add audio; return any chunks that are now complete."""

        out: List[np.ndarray] = []
        data = np.concatenate([self._pending, np.asarray(signal, dtype=np.float32)])
        n_full = (data.size // self.FRAME) * self.FRAME
        self._pending = data[n_full:]

        for start in range(0, n_full, self.FRAME):
            frame = data[start : start + self.FRAME]
            self._frames.append(frame)
            if self._is_loud(frame):
                self._has_speech = True
                self._quiet_run = 0
            else:
                self._quiet_run += 1

            size = len(self._frames) * self.FRAME
            if not self._has_speech:
                # Only silence so far: keep just a short pre-roll.
                if len(self._frames) > self.preroll_frames:
                    self._frames = self._frames[-self.preroll_frames :]
            elif size >= self.max_samples:
                out.append(self._take())
            elif self._quiet_run >= self.silence_frames and size >= self.min_samples:
                out.append(self._take())
        return out

    def flush(self) -> Optional[np.ndarray]:
        """Return whatever speech is buffered (call when stopping)."""

        if not self._has_speech:
            self._frames = []
            return None
        chunk = self._take()
        return chunk if chunk.size else None


def format_line(text: str, when: datetime, speaker: Optional[str] = None) -> str:
    prefix = f"{speaker}: " if speaker else ""
    return f"[{when:%H:%M:%S}] {prefix}{text.strip()}"


def new_transcript_path(folder: str, now: datetime) -> str:
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"תמלול_{now:%Y-%m-%d_%H-%M}.txt")  # תמלול_...


class TranscriptWriter:
    """Append lines to a UTF-8 text file, flushing each one (nothing lost on a crash)."""

    def __init__(self, path: str):
        self.path = path

    def write_line(self, line: str) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()


def load_settings(path: str) -> dict:
    """Read the small settings file; a missing or corrupt file means defaults."""

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(path: str, settings: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)


# --- input devices ------------------------------------------------------------

# Inputs that are really the *speakers* (they record what the computer plays).
_LOOPBACK_WORDS = (
    "stereo mix", "what u hear", "wave out", "loopback", "mix stereo",
    "מיקס סטריאו",   # מיקס סטריאו
    "סטריאו מיקס",   # סטריאו מיקס
)
# Virtual "mapper" entries that are not real devices.
_VIRTUAL_WORDS = ("sound mapper", "primary sound capture")


def is_loopback_name(name: str) -> bool:
    low = name.lower()
    return any(w in low for w in _LOOPBACK_WORDS)


def _api_short(api_name: str) -> Optional[str]:
    low = api_name.lower()
    if "asio" in low:
        return "ASIO"
    if "wasapi" in low:
        return "WASAPI"
    if low == "mme":
        return "MME"
    return None  # DirectSound / WDM-KS: duplicates of the same hardware


def build_device_list(devices: List[dict], hostapis: List[dict]) -> List[dict]:
    """Turn PortAudio's raw device list into the list shown to the user.

    * only real inputs (no speaker-loopback "Stereo Mix", no virtual mappers);
    * ASIO first (all channels of a pro card), then WASAPI, and MME only for
      devices that have no WASAPI entry (MME repeats the same hardware with
      names cut to 31 characters);
    * each entry: key (stable across reboots), label, index, channels,
      samplerate, api.
    """

    entries: List[dict] = []
    wasapi_names: List[str] = []
    for dev in devices:
        if dev.get("max_input_channels", 0) <= 0:
            continue
        api = _api_short(hostapis[dev["hostapi"]]["name"])
        if api is None:
            continue
        name = str(dev["name"]).strip()
        low = name.lower()
        if is_loopback_name(name) or any(w in low for w in _VIRTUAL_WORDS):
            continue
        if api == "WASAPI":
            wasapi_names.append(low)
        entries.append(
            {
                "key": f"{api}|{name}",
                "label": f"{name}   [{api} · {dev['max_input_channels']} ערוצים]",
                "index": dev["index"],
                "channels": int(dev["max_input_channels"]),
                "samplerate": int(dev.get("default_samplerate") or 48000),
                "api": api,
            }
        )

    def mme_duplicate(e: dict) -> bool:
        short = e["key"].split("|", 1)[1].lower()
        return e["api"] == "MME" and any(w.startswith(short[:31]) for w in wasapi_names)

    entries = [e for e in entries if not mme_duplicate(e)]
    order = {"ASIO": 0, "WASAPI": 1, "MME": 2}
    entries.sort(key=lambda e: order[e["api"]])
    return entries


def pick_default(entries: List[dict], saved_key: Optional[str], hostapis: List[dict]) -> Optional[dict]:
    """Saved choice if still present, else Windows' default input, else the first."""

    if not entries:
        return None
    for e in entries:
        if e["key"] == saved_key:
            return e
    for api in hostapis:
        if _api_short(api.get("name", "")) == "WASAPI":
            for e in entries:
                if e["index"] == api.get("default_input_device"):
                    return e
    return entries[0]


# --- transcription quality ------------------------------------------------------

# Phrases Whisper is known to *invent* on silence / noise (learned from subtitles).
_HALLUCINATIONS = {
    "תודה שצפיתם",            # תודה שצפיתם
    "תודה על הצפייה",  # תודה על הצפייה
    "תודה לצפייה",            # תודה לצפייה
    "תודה רבה",                        # תודה רבה
    "תודה",                                    # תודה
    "כתוביות",                          # כתוביות
    "תרגום כתוביות",    # תרגום כתוביות
    "תורגם על ידי",            # תורגם על ידי
    "thanks for watching", "thank you for watching", "thank you",
    "subtitles by the amara org community", "amara org",
}


def _norm(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return " ".join("".join(out).split())


def is_hallucination_phrase(text: str) -> bool:
    return _norm(text) in _HALLUCINATIONS


def keep_segment(
    text: str,
    avg_logprob: float = 0.0,
    no_speech_prob: float = 0.0,
    compression_ratio: float = 1.0,
) -> bool:
    """Drop segments that are most likely invented rather than heard."""

    if not _norm(text):
        return False  # punctuation / music notes only
    if compression_ratio > 2.4:
        return False  # repetition loop
    if avg_logprob < -1.0:
        return False  # the model itself is very unsure
    if no_speech_prob > 0.6 and avg_logprob < -0.5:
        return False  # probably silence/noise
    if is_hallucination_phrase(text) and (no_speech_prob > 0.2 or avg_logprob < -0.4):
        return False  # classic subtitle hallucination, not confidently heard
    return True


def collapse_repeats(text: str, max_repeats: int = 3) -> str:
    """Collapse a word or short phrase repeated more than ``max_repeats`` times in
    a row (a Whisper loop) to a single occurrence. "לא לא לא" stays as is."""

    words = text.split()
    for n in (3, 2, 1):
        i, out = 0, []
        while i < len(words):
            gram = words[i : i + n]
            reps = 1
            while words[i + reps * n : i + (reps + 1) * n] == gram and len(gram) == n:
                reps += 1
            if reps > max_repeats:
                out.extend(gram)
                i += reps * n
            else:
                out.append(words[i])
                i += 1
        words = out
    return " ".join(words)


def normalize_gain(chunk: np.ndarray, target_peak: float = 0.6, max_gain: float = 8.0) -> np.ndarray:
    """Boost quiet microphones so the model gets a healthy level (never attenuates)."""

    chunk = np.asarray(chunk, dtype=np.float32)
    peak = float(np.max(np.abs(chunk))) if chunk.size else 0.0
    if peak < 1e-4:
        return chunk
    gain = min(max_gain, target_peak / peak)
    return chunk * gain if gain > 1.0 else chunk


def load_glossary(path: str) -> List[str]:
    """Names / terms (one per line) that the model should prefer. Optional file."""

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return [l.strip() for l in handle if l.strip() and not l.lstrip().startswith("#")]
    except OSError:
        return []
