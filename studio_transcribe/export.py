"""Export a merged timeline to SRT / WebVTT / plain text / DOCX.

SRT, VTT and TXT are pure-stdlib string builders (unit-tested here). DOCX uses
``python-docx`` and imports it lazily, so the rest of the module works without
it installed.
"""

from __future__ import annotations

from typing import List

from .models import Segment
from .normalize_he import normalize_display


def _fmt_timestamp(seconds: float, millis_sep: str = ",") -> str:
    """Format seconds as ``HH:MM:SS,mmm`` (SRT) or ``HH:MM:SS.mmm`` (VTT)."""

    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{millis_sep}{ms:03d}"


def _line(seg: Segment, with_speaker: bool) -> str:
    text = normalize_display(seg.text)
    if with_speaker and seg.speaker:
        return f"{seg.speaker}: {text}"
    return text


def to_srt(segments: List[Segment], with_speaker: bool = True) -> str:
    blocks = []
    for idx, seg in enumerate(segments, start=1):
        start = _fmt_timestamp(seg.start, ",")
        end = _fmt_timestamp(seg.end, ",")
        blocks.append(f"{idx}\n{start} --> {end}\n{_line(seg, with_speaker)}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_vtt(segments: List[Segment], with_speaker: bool = True) -> str:
    blocks = ["WEBVTT", ""]
    for seg in segments:
        start = _fmt_timestamp(seg.start, ".")
        end = _fmt_timestamp(seg.end, ".")
        blocks.append(f"{start} --> {end}\n{_line(seg, with_speaker)}")
    return "\n\n".join(blocks) + "\n"


def to_txt(segments: List[Segment], with_speaker: bool = True) -> str:
    """Readable transcript: one ``speaker: text`` line per segment."""

    return "\n".join(_line(seg, with_speaker) for seg in segments) + (
        "\n" if segments else ""
    )


def to_docx(
    segments: List[Segment],
    path: str,
    with_speaker: bool = True,
    rtl: bool = True,
    title: str = "",
) -> None:
    """Write a speaker-labeled Word document (RTL-aware for Hebrew).

    Requires ``python-docx`` (``pip install python-docx``).
    """

    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise RuntimeError(
            "python-docx is required for DOCX export: pip install python-docx"
        ) from exc

    doc = Document()
    if title:
        heading = doc.add_heading(title, level=1)
        if rtl:
            heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    for seg in segments:
        para = doc.add_paragraph()
        if rtl:
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            para.paragraph_format.right_to_left = True
        if with_speaker and seg.speaker:
            run = para.add_run(f"{seg.speaker}: ")
            run.bold = True
        para.add_run(normalize_display(seg.text))

    doc.save(path)
