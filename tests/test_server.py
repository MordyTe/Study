import time

import pytest
from fastapi.testclient import TestClient

from studio_transcribe.models import Segment
from studio_transcribe.server.app import create_app
from studio_transcribe.store import TranscriptStore


@pytest.fixture(autouse=True)
def _no_password(monkeypatch):
    monkeypatch.delenv("STUDIO_TRANSCRIBE_PASSWORD", raising=False)


def test_health_no_auth():
    with TestClient(create_app()) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_status_and_config_roundtrip(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("language: he\n", encoding="utf-8")
    with TestClient(create_app(config_path=str(cfg))) as client:
        assert client.get("/api/status").status_code == 200

        new = client.get("/api/config").json()
        new["channels"] = [{"index": 1, "speaker": "מנחה", "enabled": True}]
        r = client.put("/api/config", json=new)
        assert r.status_code == 200
        assert r.json()["channels"][0]["speaker"] == "מנחה"
        # persisted to disk
        assert "מנחה" in cfg.read_text(encoding="utf-8")


def test_search_endpoint(tmp_path):
    db = tmp_path / "s.db"
    with TranscriptStore(str(db)) as store:
        sid = store.create_session("פרק 1")
        store.add_segments(sid, [Segment(0, 1, "נדבר על Dante", speaker="מנחה", channel=1)])

    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db_path: {db}\n", encoding="utf-8")
    with TestClient(create_app(config_path=str(cfg))) as client:
        hits = client.get("/api/search", params={"q": "Dante"}).json()
        assert len(hits) == 1
        assert hits[0]["speaker"] == "מנחה"
        sessions = client.get("/api/sessions").json()
        assert sessions[0]["name"] == "פרק 1"


def test_transcribe_job(monkeypatch, tmp_path):
    # Patch the heavy transcription with a fake so the job runs without ASR deps.
    import studio_transcribe.server.service as service

    def fake_transcribe(input_path, config, progress=None):
        if progress:
            progress("channel 1: transcribing")
        return [Segment(0.0, 1.0, "שלום", speaker="מנחה", channel=1)]

    monkeypatch.setattr(service, "transcribe_file", fake_transcribe)

    with TestClient(create_app(out_dir=str(tmp_path / "out"))) as client:
        r = client.post("/api/transcribe", json={"input": "rec/", "formats": ["txt", "srt"]})
        job_id = r.json()["job_id"]

        for _ in range(50):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert job["status"] == "done", job
        assert set(job["outputs"].keys()) == {"txt", "srt"}

        dl = client.get(f"/api/jobs/{job_id}/download/txt")
        assert dl.status_code == 200
        assert "מנחה: שלום" in dl.text


def test_websocket_sends_initial_status():
    with TestClient(create_app()) as client:
        with client.websocket_connect("/api/ws?token=") as websocket:
            msg = websocket.receive_json()
            assert msg["type"] == "status"


def test_auth_enforced_when_password_set(monkeypatch):
    monkeypatch.setenv("STUDIO_TRANSCRIBE_PASSWORD", "secret")
    with TestClient(create_app()) as client:
        assert client.get("/api/status").status_code == 401
        ok = client.get("/api/status", headers={"X-Auth-Token": "secret"})
        assert ok.status_code == 200
