import json

from agent_play.cli import main


def _run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out.strip().splitlines()[-1]
    return code, json.loads(out)


def test_status_and_skills(capsys, tmp_path):
    code, envelope = _run(capsys, "--home", str(tmp_path), "status")
    assert code == 0 and envelope["ok"] and envelope["command"] == "status"
    assert envelope["data"]["perception"]["template"] is True
    code, envelope = _run(capsys, "skills", "list")
    assert "core" in envelope["data"]["skills"] and "genres/puzzle" in envelope["data"]["skills"]
    code, envelope = _run(capsys, "skills", "get", "core")
    assert "The loop" in envelope["data"]["content"]
    code, envelope = _run(capsys, "skills", "get", "nope")
    assert code == 1 and envelope["error"]["code"] == "INVALID_ARGS"


def test_sim_frame_and_snapshot(capsys, tmp_path):
    out = tmp_path / "frame.png"
    code, envelope = _run(capsys, "--home", str(tmp_path), "sim", "frame", "--out", str(out), "--state", "playing")
    assert code == 0 and out.exists() and envelope["command"] == "sim.frame"
    code, envelope = _run(capsys, "--home", str(tmp_path), "sim", "snapshot")
    assert code == 0 and envelope["data"]["ref_count"] == 1 and '[button] "start"' in envelope["data"]["scene"]


def test_snapshot_then_click_across_processes_with_an_image(capsys, tmp_path):
    from agent_play.sim.grid_game import GridGame

    game = GridGame()
    frame = tmp_path / "title.png"
    game.render().save(frame)
    templates = tmp_path / "templates"
    templates.mkdir()
    for template in game.templates():
        from PIL import Image

        Image.fromarray(template.image.astype("uint8")).save(templates / f"{template.role}__{template.name.replace(' ', '_')}.png")
    common = ["--home", str(tmp_path), "--session", "t1", "--image", str(frame), "--templates", str(templates), "--no-vision", "--no-ocr"]
    code, envelope = _run(capsys, *common, "snapshot", "--text", "-i")
    assert code == 0 and envelope["data"]["ref_count"] == 1
    ref = next(line.split()[0] for line in envelope["data"]["scene"].splitlines() if "[button]" in line)
    code, envelope = _run(capsys, *common, "click", ref)
    assert code == 0 and envelope["data"]["reidentified_by"] == "scene"
    assert envelope["data"]["disposition"] == {"delivery": "delivered_unverified", "retry": "unsafe"}
    code, envelope = _run(capsys, *common, "click", "@sdoesnotx:e1")
    assert code == 1 and envelope["error"]["code"] == "SNAPSHOT_NOT_FOUND"
    code, envelope = _run(capsys, *common, "press", "enter")
    assert code == 0 and envelope["data"]["action"] == "press"


def test_scripted_sim_play(capsys, tmp_path):
    code, envelope = _run(capsys, "--home", str(tmp_path), "sim", "play", "--scripted", "--max-steps", "40")
    assert code == 0, envelope
    assert envelope["data"]["status"] == "success" and envelope["data"]["game"]["state"] == "won"


def test_sim_state_persists_across_cli_processes(capsys, tmp_path):
    common = ["--home", str(tmp_path), "--session", "persist", "--sim"]
    code, envelope = _run(capsys, *common, "snapshot", "--text")
    assert code == 0 and envelope["data"]["ref_count"] == 1
    ref = next(line.split()[0] for line in envelope["data"]["scene"].splitlines() if "[button]" in line)
    code, envelope = _run(capsys, *common, "click", ref)
    assert code == 0 and envelope["data"]["disposition"]["delivery"] == "delivered_verified"
    code, envelope = _run(capsys, *common, "press", "enter")
    assert code == 0 and envelope["data"]["disposition"]["delivery"] == "delivered_verified"
    code, envelope = _run(capsys, "--home", str(tmp_path), "--session", "persist", "sim", "status")
    assert envelope["data"]["game"]["state"] == "playing"
    code, envelope = _run(capsys, *common, "press", "right")
    assert envelope["data"]["events"][0]["kind"] == "node_moved"
    code, envelope = _run(capsys, "--home", str(tmp_path), "--session", "persist", "sim", "reset")
    assert envelope["data"]["game"]["state"] == "title"
