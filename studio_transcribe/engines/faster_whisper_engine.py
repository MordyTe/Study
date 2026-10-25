"""Local, private, high-accuracy engine: faster-whisper running the ivrit.ai
Hebrew fine-tune (``ivrit-ai/whisper-large-v3-turbo-ct2`` by default).

Why these defaults (see the product spec, accuracy strategy):

* ``language="he"`` is forced — the ivrit.ai fine-tunes have degraded language
  detection and must be told the language explicitly.
* ``vad_filter=True`` (Silero, built into faster-whisper) is the #1
  anti-hallucination measure — Whisper invents text on silence/music.
* ``condition_on_previous_text=False`` prevents the repetition loops that
  previous-text conditioning fuels in Hebrew.
* ``compression_ratio_threshold`` / ``log_prob_threshold`` /
  ``no_speech_threshold`` drop loop/hallucination segments.
* ``initial_prompt`` carries the glossary to bias names and English terms.
"""

from __future__ import annotations

from typing import List, Optional

from ..config import Config
from ..models import Segment, Word
from .base import TranscriptionEngine


def _resolve_device(device: str):
    if device != "auto":
        return device
    try:
        import torch  # type: ignore

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"


class FasterWhisperEngine(TranscriptionEngine):
    def __init__(self, config: Config):
        self.config = config
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "faster-whisper is required: pip install faster-whisper"
            ) from exc

        device = _resolve_device(config.device)
        compute_type = _resolve_compute_type(config.compute_type, device)
        self.device = device
        self.compute_type = compute_type
        self.model = WhisperModel(
            config.model, device=device, compute_type=compute_type
        )

    def transcribe(
        self,
        audio,
        language: str = "he",
        initial_prompt: Optional[str] = None,
    ) -> List[Segment]:
        d = self.config.decode
        v = self.config.vad
        segments_iter, _info = self.model.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=d.beam_size,
            temperature=d.temperature,
            condition_on_previous_text=d.condition_on_previous_text,
            compression_ratio_threshold=d.compression_ratio_threshold,
            log_prob_threshold=d.log_prob_threshold,
            no_speech_threshold=d.no_speech_threshold,
            word_timestamps=d.word_timestamps,
            initial_prompt=initial_prompt,
            vad_filter=v.enabled,
            vad_parameters={
                "threshold": v.threshold,
                "min_speech_duration_ms": v.min_speech_ms,
                "min_silence_duration_ms": v.min_silence_ms,
                "speech_pad_ms": v.speech_pad_ms,
            },
        )

        out: List[Segment] = []
        for s in segments_iter:
            words = []
            for w in (s.words or []):
                words.append(
                    Word(text=w.word, start=w.start, end=w.end, prob=w.probability)
                )
            out.append(
                Segment(
                    start=s.start,
                    end=s.end,
                    text=s.text.strip(),
                    words=words,
                    avg_logprob=getattr(s, "avg_logprob", None),
                    no_speech_prob=getattr(s, "no_speech_prob", None),
                    compression_ratio=getattr(s, "compression_ratio", None),
                )
            )
        return out
