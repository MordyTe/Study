"""FastAPI application factory for the operator web app."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    Body,
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .auth import make_auth_dependency, token_ok
from .service import AppState

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(config_path: Optional[str] = None, out_dir: str = "out") -> FastAPI:
    state = AppState(config_path=config_path, out_dir=out_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.bind_loop(asyncio.get_running_loop())
        broadcaster = asyncio.create_task(_broadcast_loop(state))
        try:
            yield
        finally:
            broadcaster.cancel()
            if state.live_runner is not None:
                state.live_runner.stop()

    app = FastAPI(title="studio-transcribe", version=__version__, lifespan=lifespan)
    app.state.svc = state
    auth = Depends(make_auth_dependency(state.config))

    # --- pages / health ---
    @app.get("/")
    async def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    # --- status / config ---
    @app.get("/api/status", dependencies=[auth])
    async def status():
        return {
            "live": state.live_status(),
            "db_path": state.config.db_path,
            "glossary_path": state.config.glossary_path,
            "engine": state.config.engine,
            "model": state.config.model,
            "device": state.config.device,
        }

    @app.get("/api/config", dependencies=[auth])
    async def get_config():
        return state.config.to_dict()

    @app.put("/api/config", dependencies=[auth])
    async def put_config(payload: dict = Body(...)):
        cfg = state.save_config(payload)
        return cfg.to_dict()

    @app.get("/api/devices", dependencies=[auth])
    async def devices():
        return state.devices()

    # --- live ---
    @app.post("/api/live/start", dependencies=[auth])
    async def live_start():
        try:
            return state.start_live()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/live/stop", dependencies=[auth])
    async def live_stop():
        return state.stop_live()

    # --- transcription jobs ---
    @app.post("/api/transcribe", dependencies=[auth])
    async def transcribe(payload: dict = Body(...)):
        input_path = payload.get("input")
        if not input_path:
            raise HTTPException(status_code=400, detail="missing 'input'")
        formats = payload.get("formats") or ["txt", "srt"]
        job_id = state.start_job(input_path, formats)
        return {"job_id": job_id}

    @app.get("/api/jobs", dependencies=[auth])
    async def jobs():
        return [j.to_dict() for j in state.jobs.values()]

    @app.get("/api/jobs/{job_id}", dependencies=[auth])
    async def job(job_id: str):
        j = state.jobs.get(job_id)
        if j is None:
            raise HTTPException(status_code=404, detail="no such job")
        return j.to_dict()

    @app.get("/api/jobs/{job_id}/download/{fmt}", dependencies=[auth])
    async def job_download(job_id: str, fmt: str):
        j = state.jobs.get(job_id)
        if j is None or fmt not in j.outputs:
            raise HTTPException(status_code=404, detail="no such output")
        return FileResponse(j.outputs[fmt], filename=os.path.basename(j.outputs[fmt]))

    # --- archive ---
    @app.get("/api/search", dependencies=[auth])
    async def search(q: str, speaker: Optional[str] = None, session: Optional[int] = None, limit: int = 50):
        return state.search(q, speaker=speaker, session_id=session, limit=limit)

    @app.get("/api/sessions", dependencies=[auth])
    async def sessions():
        return state.sessions()

    # --- glossary ---
    @app.get("/api/glossary", dependencies=[auth])
    async def get_glossary():
        return {"text": state.read_glossary()}

    @app.put("/api/glossary", dependencies=[auth])
    async def put_glossary(payload: dict = Body(...)):
        state.write_glossary(payload.get("text", ""))
        return {"ok": True}

    # --- websocket ---
    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket):
        token = websocket.query_params.get("token", "")
        if not token_ok(state.config, token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        state.ws_clients.add(websocket)
        try:
            await websocket.send_json({"type": "status", "live": state.live_status()})
            while True:
                await websocket.receive_text()  # keepalive / ignore client messages
        except WebSocketDisconnect:
            pass
        finally:
            state.ws_clients.discard(websocket)

    if os.path.isdir(STATIC_DIR):
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


async def _broadcast_loop(state: AppState) -> None:
    """Fan queued messages out to all connected WebSocket clients."""

    assert state.queue is not None
    while True:
        message = await state.queue.get()
        for client in list(state.ws_clients):
            try:
                await client.send_json(message)
            except Exception:
                state.ws_clients.discard(client)
