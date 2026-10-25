"""Command-line interface.

Subcommands:

* ``transcribe`` — transcribe a multichannel file / per-channel directory and
  export (needs the ASR engine deps; runs on the studio node).
* ``eval`` — measure WER/CER of a hypothesis against a reference (pure stdlib).
* ``version`` — print the version.

Heavy imports happen inside ``transcribe`` only, so ``eval`` and ``--help`` work
without the ASR dependencies installed.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def _cmd_eval(args: argparse.Namespace) -> int:
    from .eval_wer import cer, wer

    with open(args.reference, "r", encoding="utf-8") as handle:
        reference = handle.read()
    with open(args.hypothesis, "r", encoding="utf-8") as handle:
        hypothesis = handle.read()

    w = wer(reference, hypothesis)
    c = cer(reference, hypothesis)
    print(f"WER: {w['wer'] * 100:.2f}%  "
          f"(S={w['substitutions']} D={w['deletions']} I={w['insertions']} "
          f"N={w['ref_len']})")
    print(f"CER: {c['cer'] * 100:.2f}%")
    return 0


def _cmd_transcribe(args: argparse.Namespace) -> int:
    import os

    from .config import Config
    from .pipeline import export_all, transcribe_file

    config = Config.from_yaml(args.config) if args.config else Config.from_dict({})
    if args.model:
        config.model = args.model
    if args.device:
        config.device = args.device
    if not config.channels and args.channels:
        from .config import ChannelConfig

        config.channels = [ChannelConfig(index=i) for i in args.channels]

    segments = transcribe_file(args.input, config, progress=lambda m: print(m, file=sys.stderr))
    base = os.path.splitext(os.path.basename(args.input.rstrip("/")))[0] or "transcript"
    written = export_all(segments, args.out_dir, base, args.formats, title=base)
    for path in written:
        print(path)

    db_path = args.db or config.db_path
    if db_path:
        from .store import TranscriptStore

        with TranscriptStore(db_path) as store:
            session_id = store.create_session(
                name=args.session_name or base, source=args.input
            )
            n = store.add_segments(session_id, segments)
        print(f"stored {n} segments in {db_path} (session {session_id})", file=sys.stderr)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    from .store import TranscriptStore

    with TranscriptStore(args.db) as store:
        hits = store.search(
            args.query,
            speaker=args.speaker,
            session_id=args.session,
            limit=args.limit,
        )
    for h in hits:
        ts = f"{h['start']:.1f}" if h.get("start") is not None else "?"
        print(f"[{h.get('session_name', '')} @ {ts}s] {h.get('speaker', '')}: {h['text']}")
    if not hits:
        print("no matches", file=sys.stderr)
    return 0


def _cmd_live(args: argparse.Namespace) -> int:
    from .config import Config
    from .live.runner import LiveRunner

    config = Config.from_yaml(args.config) if args.config else Config.from_dict({})
    config.live.enabled = True
    if args.db:
        config.db_path = args.db
    print("live captions running — Ctrl-C to stop", file=sys.stderr)
    LiveRunner(config).run()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .config import Config
    from .server import create_app

    config = Config.from_yaml(args.config) if args.config else Config.from_dict({})
    host = args.host or config.server.host
    port = args.port or config.server.port
    app = create_app(config_path=args.config, out_dir=args.out_dir)
    print(f"operator UI on http://{host}:{port}", file=sys.stderr)
    uvicorn.run(app, host=host, port=port)
    return 0


def _cmd_version(_args: argparse.Namespace) -> int:
    from . import __version__

    print(__version__)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studio-transcribe",
        description="High-accuracy studio transcription (Hebrew + English).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("transcribe", help="transcribe a recording and export")
    t.add_argument("input", help="multichannel file, or a directory of per-channel files")
    t.add_argument("-c", "--config", help="YAML config path")
    t.add_argument("-o", "--out-dir", default="out", help="output directory")
    t.add_argument(
        "-f",
        "--formats",
        nargs="+",
        default=["txt", "srt"],
        help="export formats: txt srt vtt docx",
    )
    t.add_argument("--channels", nargs="+", type=int, help="1-based channel numbers")
    t.add_argument("--model", help="override the ASR model")
    t.add_argument("--device", help="auto | cuda | cpu")
    t.add_argument("--db", help="persist segments to this SQLite DB")
    t.add_argument("--session-name", help="session name for the DB")
    t.set_defaults(func=_cmd_transcribe)

    s = sub.add_parser("search", help="full-text search the transcript DB")
    s.add_argument("query", help="text to search for")
    s.add_argument("--db", required=True, help="SQLite DB path")
    s.add_argument("--speaker", help="filter by speaker")
    s.add_argument("--session", type=int, help="filter by session id")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=_cmd_search)

    live = sub.add_parser("live", help="run live captions (Soniox -> OBS/vMix)")
    live.add_argument("-c", "--config", help="YAML config path")
    live.add_argument("--db", help="persist finalized captions to this SQLite DB")
    live.set_defaults(func=_cmd_live)

    e = sub.add_parser("eval", help="measure WER/CER against a reference")
    e.add_argument("reference", help="ground-truth transcript (text file)")
    e.add_argument("hypothesis", help="system output transcript (text file)")
    e.set_defaults(func=_cmd_eval)

    sv = sub.add_parser("serve", help="run the operator web app (UI)")
    sv.add_argument("-c", "--config", help="YAML config path")
    sv.add_argument("--host", help="bind host (0.0.0.0 for LAN access)")
    sv.add_argument("--port", type=int, help="bind port (default 8000)")
    sv.add_argument("--out-dir", default="out", help="output directory for jobs")
    sv.set_defaults(func=_cmd_serve)

    v = sub.add_parser("version", help="print version")
    v.set_defaults(func=_cmd_version)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
