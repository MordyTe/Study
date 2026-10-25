"""Offline transcription pipeline (Stage 1 of the build plan).

Ties the pieces together: for each enabled channel, pull 16 kHz mono audio,
transcribe it with the configured engine (ivrit.ai local by default), merge all
channels into one speaker-tagged timeline, optionally run the gated LLM
correction, and export.

The heavy engine/audio imports live inside the functions so importing this
module stays cheap.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .config import Config
from .models import ChannelResult, Segment


def _initial_prompt(config: Config) -> Optional[str]:
    if not config.glossary_path:
        return None
    from .glossary import build_initial_prompt, load_glossary

    terms = load_glossary(config.glossary_path)
    return build_initial_prompt(terms) or None


def transcribe_file(
    input_path: str,
    config: Config,
    engine=None,
    progress=None,
) -> List[Segment]:
    """Transcribe a multichannel file (or per-channel directory) to a timeline."""

    from .audio_io import iter_channels
    from .engines import build_engine
    from .merge import merge_timeline

    engine = engine or build_engine(config)
    channels = config.enabled_channels()
    if not channels:
        raise ValueError("no enabled channels in config")

    initial_prompt = _initial_prompt(config)
    results: List[ChannelResult] = []
    for channel, signal in iter_channels(input_path, channels, config.sample_rate):
        if progress:
            progress(f"channel {channel}: transcribing")
        segments = engine.transcribe(
            signal, language=config.language, initial_prompt=initial_prompt
        )
        results.append(ChannelResult(channel=channel, segments=segments))

    merged = merge_timeline(results, config.speaker_map(), join_gap=config.join_gap)

    if config.llm_correction.enabled:
        from .glossary import load_glossary
        from .llm_correction import correct_segments

        terms = load_glossary(config.glossary_path) if config.glossary_path else []
        if progress:
            progress("llm correction (low-confidence segments)")
        merged = correct_segments(merged, config, terms)

    return merged


def export_all(
    segments: List[Segment],
    out_dir: str,
    base_name: str,
    formats: List[str],
    title: str = "",
) -> List[str]:
    """Write the timeline to the requested formats; return the paths written."""

    from . import export as ex

    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []
    for fmt in formats:
        fmt = fmt.lower()
        path = os.path.join(out_dir, f"{base_name}.{fmt}")
        if fmt == "srt":
            _write_text(path, ex.to_srt(segments))
        elif fmt == "vtt":
            _write_text(path, ex.to_vtt(segments))
        elif fmt == "txt":
            _write_text(path, ex.to_txt(segments))
        elif fmt == "docx":
            ex.to_docx(segments, path, title=title)
        else:
            raise ValueError(f"unknown export format: {fmt}")
        written.append(path)
    return written


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
