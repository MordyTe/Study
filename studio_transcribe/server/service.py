"""Application state and orchestration behind the web API.

Owns the loaded config, the live runner, the WebSocket broadcast plumbing, and
the offline transcription job registry. One instance lives on ``app.state``.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from typing import Dict, List, Optional

from ..config import Config
from ..pipeline import export_all, transcribe_file  # module-level for test patching


class Job:
    def __init__(self, job_id: str, input_path: str, formats: List[str]):
        self.id = job_id
        self.input = input_path
        self.formats = formats
        self.status = "queued"  # queued | running | done | error
        self.progress: List[str] = []
        self.outputs: Dict[str, str] = {}
        self.error: Optional[str] = None
        self.session_id: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "input": self.input,
            "formats": self.formats,
            "status": self.status,
            "progress": self.progress,
            "outputs": {k: os.path.basename(v) for k, v in self.outputs.items()},
            "error": self.error,
            "session_id": self.session_id,
        }


class AppState:
    def __init__(self, config_path: Optional[str] = None, out_dir: str = "out"):
        self.config_path = config_path
        self.out_dir = out_dir
        self.config = self._load_config()
        self.live_runner = None
        self.mic_runner = None
        self.jobs: Dict[str, Job] = {}
        self.ws_clients: set = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.queue: Optional[asyncio.Queue] = None

    # --- config ---
    def _load_config(self) -> Config:
        if self.config_path and os.path.exists(self.config_path):
            return Config.from_yaml(self.config_path)
        return Config.from_dict({})

    def save_config(self, data: Dict) -> Config:
        self.config = Config.from_dict(data)
        if self.config_path:
            self.config.save_yaml(self.config_path)
        return self.config

    # --- websocket broadcast (thread-safe) ---
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue = asyncio.Queue()

    def publish(self, message: Dict) -> None:
        """Push a message to all WebSocket clients; safe to call from any thread."""

        if self.loop is None or self.queue is None:
            return
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, message)
        except RuntimeError:
            pass

    # --- live ---
    def start_live(self) -> Dict:
        from ..live.runner import LiveRunner
        from ..live.sinks import CallbackSink

        if self.live_runner is not None and self.live_runner.running:
            return self.live_status()

        def on_caption(text: str):
            self.publish({"type": "caption", "text": text, "ts": time.time()})

        runner = LiveRunner(self.config, extra_sinks=[CallbackSink(on_caption)])
        runner.start()
        self.live_runner = runner
        self.publish({"type": "status", "live": True})
        return self.live_status()

    def stop_live(self) -> Dict:
        if self.live_runner is not None:
            self.live_runner.stop()
        self.publish({"type": "status", "live": False})
        return self.live_status()

    def live_status(self) -> Dict:
        if self.live_runner is None:
            return {"running": False, "channels": self.config.enabled_channels()[:4]}
        return self.live_runner.status()

    # --- quick mic test ---
    def start_mic_test(self) -> Dict:
        from ..live.mic_test import MicTestRunner

        if self.mic_runner is not None and self.mic_runner.running:
            return {"running": True}

        def on_event(ev: Dict):
            self.publish({"type": "mic", **ev})

        self.mic_runner = MicTestRunner(self.config, on_event)
        self.mic_runner.start()
        return {"running": True}

    def stop_mic_test(self) -> Dict:
        if self.mic_runner is not None:
            self.mic_runner.stop()
        return {"running": False}

    def mic_running(self) -> bool:
        return self.mic_runner is not None and self.mic_runner.running

    # --- offline transcription jobs ---
    def start_job(self, input_path: str, formats: List[str]) -> str:
        job_id = uuid.uuid4().hex[:8]
        job = Job(job_id, input_path, formats)
        self.jobs[job_id] = job
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return job_id

    def _run_job(self, job: Job) -> None:
        job.status = "running"
        self.publish({"type": "job", "job": job.to_dict()})
        try:
            def progress(msg: str):
                job.progress.append(msg)
                self.publish({"type": "job", "job": job.to_dict()})

            segments = transcribe_file(job.input, self.config, progress=progress)
            base = os.path.splitext(os.path.basename(job.input.rstrip("/")))[0] or job.id
            job_out = os.path.join(self.out_dir, job.id)
            written = export_all(segments, job_out, base, job.formats, title=base)
            job.outputs = {os.path.splitext(p)[1].lstrip("."): p for p in written}

            if self.config.db_path:
                from ..store import TranscriptStore

                with TranscriptStore(self.config.db_path) as store:
                    job.session_id = store.create_session(name=base, source=job.input)
                    store.add_segments(job.session_id, segments)

            job.status = "done"
        except Exception as exc:  # surface the error to the UI, never crash the server
            job.status = "error"
            job.error = str(exc)
        self.publish({"type": "job", "job": job.to_dict()})

    # --- archive ---
    def search(self, query: str, speaker=None, session_id=None, limit=50) -> List[Dict]:
        if not self.config.db_path or not os.path.exists(self.config.db_path):
            return []
        from ..store import TranscriptStore

        with TranscriptStore(self.config.db_path) as store:
            return store.search(query, speaker=speaker, session_id=session_id, limit=limit)

    def sessions(self) -> List[Dict]:
        if not self.config.db_path or not os.path.exists(self.config.db_path):
            return []
        from ..store import TranscriptStore

        with TranscriptStore(self.config.db_path) as store:
            rows = store.conn.execute(
                "SELECT id, name, source, started_at FROM sessions ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- glossary ---
    def read_glossary(self) -> str:
        path = self.config.glossary_path
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        return ""

    def write_glossary(self, text: str) -> None:
        path = self.config.glossary_path or "config/glossary.txt"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.config.glossary_path = path

    # --- devices ---
    def devices(self) -> List[Dict]:
        try:
            import sounddevice as sd  # type: ignore
        except Exception:
            return []
        out = []
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                out.append(
                    {
                        "index": idx,
                        "name": dev.get("name", ""),
                        "channels": dev.get("max_input_channels", 0),
                    }
                )
        return out
