#!/usr/bin/env python3
"""Stage 0 — capture discrete X32 channels off an ASIO device to per-channel WAV.

Runs on the studio transcription node (Windows) where the X32 is visible as an
ASIO device — either the stock **X-USB** card's Behringer ASIO driver, or
**Dante Virtual Soundcard** (ASIO) subscribing to the X-DANTE card's flows.

This is a standalone utility (not imported by the package) so it only needs
``sounddevice`` + ``soundfile`` + ``numpy``:

    pip install sounddevice soundfile numpy

List devices:

    python capture/capture_asio.py list

Record channels 1-4 for 60 seconds into ./rec (one WAV per channel):

    python capture/capture_asio.py record --device "ASIO" --channels 1 2 3 4 \
        --seconds 60 --out-dir rec

Notes:
* Channel numbers are 1-based mic numbers; they map to ASIO input index n-1.
* All channels come off one clock-locked ASIO stream, so the per-channel WAVs
  are sample-synchronous — exactly what the merge step relies on.
"""

from __future__ import annotations

import argparse
import sys
import time


def cmd_list(_args: argparse.Namespace) -> int:
    import sounddevice as sd

    print(sd.query_devices())
    print("\nHost APIs:")
    for api in sd.query_hostapis():
        print(f"  {api['name']}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    import os

    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    channels = args.channels
    max_ch = max(channels)
    os.makedirs(args.out_dir, exist_ok=True)

    # Open the device channels 1..max_ch; we keep only the requested ones.
    extra = None
    if args.device and "asio" in str(args.device).lower():
        # Select specific ASIO input channels (0-based) for efficiency.
        extra = sd.AsioSettings(channel_selectors=[c - 1 for c in channels])
        in_channels = len(channels)
        keep_index = list(range(len(channels)))
    else:
        in_channels = max_ch
        keep_index = [c - 1 for c in channels]

    writers = {
        c: sf.SoundFile(
            os.path.join(args.out_dir, f"ch{c:02d}.wav"),
            mode="w",
            samplerate=args.samplerate,
            channels=1,
            subtype="PCM_24",
        )
        for c in channels
    }

    def callback(indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        for pos, c in zip(keep_index, channels):
            writers[c].write(indata[:, pos].copy())

    try:
        with sd.InputStream(
            device=args.device,
            channels=in_channels,
            samplerate=args.samplerate,
            dtype="float32",
            callback=callback,
            extra_settings=extra,
        ):
            print(
                f"recording {len(channels)} channel(s) for {args.seconds}s "
                f"at {args.samplerate} Hz -> {args.out_dir}",
                file=sys.stderr,
            )
            time.sleep(args.seconds)
    finally:
        for w in writers.values():
            w.close()
    print("done", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture X32 channels via ASIO.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list audio devices / host APIs").set_defaults(
        func=cmd_list
    )

    r = sub.add_parser("record", help="record per-channel WAV files")
    r.add_argument("--device", default=None, help="device name/index (e.g. 'ASIO')")
    r.add_argument("--channels", nargs="+", type=int, required=True, help="1-based")
    r.add_argument("--seconds", type=float, default=30.0)
    r.add_argument("--samplerate", type=int, default=48000)
    r.add_argument("--out-dir", default="rec")
    r.set_defaults(func=cmd_record)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
