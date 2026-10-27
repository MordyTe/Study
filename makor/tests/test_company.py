"""Tests for the company backbone — the rules agents cannot bend."""

import importlib
import json
import os
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)


@pytest.fixture
def co(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKOR_BASE", str(tmp_path))
    import company

    importlib.reload(company)
    company.main(["init"])
    return company


def run(co, *argv):
    """Run a CLI command and return its parsed JSON output."""

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        co.main(list(argv))
    out = buf.getvalue().strip()
    return json.loads(out) if out.startswith("{") else out


def hire(co, name="דנה", role="מפתחת", dept="tech", level="worker", id=None):
    args = ["hire", "--name", name, "--role", role, "--dept", dept, "--level", level]
    if id:
        args += ["--id", id]
    return run(co, *args)["hired"]


# ----------------------------------------------------------------- basics
def test_init_creates_state(co):
    assert co.today() == 0
    assert co.roster() == []
    assert os.path.exists(os.path.join(co.BASE, "state", "protected.json"))


def test_new_day_increments(co):
    run(co, "new-day")
    run(co, "new-day")
    assert co.today() == 2


def test_hire_records_hr_event(co):
    aid = hire(co)
    assert co.find_agent(aid)["status"] == "active"
    hr = co.load("state/hr.json", [])
    assert hr[-1]["event"] == "hired" and hr[-1]["agent"] == aid


# ------------------------------------------------------- proof of work
def test_task_without_evidence_is_not_done(co):
    aid = hire(co)
    tid = run(co, "add-task", "--title", "כלי", "--owner", aid, "--dept", "tech",
              "--acceptance-type", "file_exists", "--acceptance-arg", "product/missing.py")["id"]
    run(co, "submit", "--id", tid, "--evidence", "product/missing.py")
    res = run(co, "verify")
    assert res["verified"][0]["status"] == "failed"
    assert co._get_task(co.tasks(), tid)["status"] == "failed"


def test_task_with_evidence_is_done(co):
    aid = hire(co)
    os.makedirs(os.path.join(co.BASE, "product"), exist_ok=True)
    with open(os.path.join(co.BASE, "product", "tool.py"), "w") as f:
        f.write("print('hi')\n")
    tid = run(co, "add-task", "--title", "כלי", "--owner", aid, "--dept", "tech",
              "--acceptance-type", "file_exists", "--acceptance-arg", "product/tool.py")["id"]
    run(co, "submit", "--id", tid, "--evidence", "product/tool.py")
    assert run(co, "verify")["verified"][0]["status"] == "done"


def test_command_acceptance(co):
    aid = hire(co)
    tid = run(co, "add-task", "--title", "x", "--owner", aid, "--dept", "tech",
              "--acceptance-type", "command", "--acceptance-arg", "python3 -c 'import sys; sys.exit(0)'")["id"]
    run(co, "submit", "--id", tid, "--evidence", "cmd")
    assert run(co, "verify")["verified"][0]["status"] == "done"
    tid2 = run(co, "add-task", "--title", "y", "--owner", aid, "--dept", "tech",
               "--acceptance-type", "command", "--acceptance-arg", "python3 -c 'import sys; sys.exit(3)'")["id"]
    run(co, "submit", "--id", tid2, "--evidence", "cmd")
    assert run(co, "verify")["verified"][0]["status"] == "failed"


def test_qa_fail_blocks_done_even_with_evidence(co):
    aid = hire(co)
    tid = run(co, "add-task", "--title", "x", "--owner", aid, "--dept", "tech",
              "--acceptance-type", "command", "--acceptance-arg", "true")["id"]
    run(co, "submit", "--id", tid, "--evidence", "cmd")
    run(co, "qa", "--id", tid, "--fail", "--notes", "לא עומד בדרישה")
    assert run(co, "verify")["verified"][0]["status"] == "failed"


def test_unverified_tasks_are_untouched(co):
    aid = hire(co)
    tid = run(co, "add-task", "--title", "x", "--owner", aid, "--dept", "tech",
              "--acceptance-type", "command", "--acceptance-arg", "true")["id"]
    run(co, "verify")  # never submitted -> stays todo
    assert co._get_task(co.tasks(), tid)["status"] == "todo"


def test_daily_task_cap(co):
    aid = hire(co)
    for i in range(co.MAX_TASKS_PER_DAY):
        run(co, "add-task", "--title", f"t{i}", "--owner", aid, "--dept", "tech",
            "--acceptance-type", "command", "--acceptance-arg", "true")
    with pytest.raises(SystemExit):
        run(co, "add-task", "--title", "one too many", "--owner", aid, "--dept", "tech",
            "--acceptance-type", "command", "--acceptance-arg", "true")


# ------------------------------------------------------------ scores + HR
def _do_task(co, aid, ok=True):
    tid = run(co, "add-task", "--title", "t", "--owner", aid, "--dept", "tech",
              "--acceptance-type", "command", "--acceptance-arg", "true" if ok else "false")["id"]
    run(co, "submit", "--id", tid, "--evidence", "cmd")
    run(co, "verify")
    run(co, "score")
    return tid


def test_score_from_verification(co):
    aid = hire(co)
    _do_task(co, aid, ok=True)
    _do_task(co, aid, ok=False)
    scores = [s["score"] for s in co.find_agent(aid)["scores"]]
    assert scores == [10, 0]


def test_two_consecutive_failures_fire_worker(co):
    aid = hire(co)
    _do_task(co, aid, ok=False)
    assert run(co, "hr")["fired"] == []
    _do_task(co, aid, ok=False)
    res = run(co, "hr")
    assert res["fired"] == [aid]
    assert co.find_agent(aid)["status"] == "fired"
    assert "מפתחת" in res["open_roles"]
    assert co.load("state/hr.json", [])[-1]["event"] == "fired"


def test_low_average_over_three_days_fires(co):
    aid = hire(co)
    for _ in range(3):
        run(co, "new-day")
        _do_task(co, aid, ok=False)
        _do_task(co, aid, ok=True)  # 5.0 average, never 2 fails in a row
    assert co.agent_average(co.find_agent(aid)) == 5.0
    assert run(co, "hr")["fired"] == []  # exactly 5 is not below 5
    run(co, "new-day")
    _do_task(co, aid, ok=False)
    _do_task(co, aid, ok=True)
    _do_task(co, aid, ok=False)  # day avg 3.3 -> 3-day avg below 5
    assert run(co, "hr")["fired"] == [aid]


def test_executives_are_not_auto_fired(co):
    aid = hire(co, name="דוויין", role="מנכ\"ל", dept="exec", level="executive")
    _do_task(co, aid, ok=False)
    _do_task(co, aid, ok=False)
    assert run(co, "hr")["fired"] == []


# ---------------------------------------------------- protected + records
def test_protected_file_change_is_flagged(co):
    p = os.path.join(co.BASE, "COMPANY.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("charter\n")
    run(co, "seal")
    with open(p, "a", encoding="utf-8") as f:
        f.write("agent edited this\n")
    assert run(co, "verify")["protected_violations"] == ["COMPANY.md"]
    assert co.load("state/decisions.json", [])[-1]["kind"] == "alert"


def test_inbox_add_and_answer(co):
    qid = run(co, "inbox", "add", "--text", "לפתוח חשבון Apify?", "--context", "נדרש לפרסום")["added"]
    assert co.summary()["open_questions"] == 1
    run(co, "inbox", "answer", "--id", qid, "--text", "כן, פתחתי")
    assert co.summary()["open_questions"] == 0


def test_meeting_validation(co):
    a1 = hire(co, name="דוויין", role="מנכ\"ל", dept="exec", level="executive")
    m = {"day": 0, "title": "ייסוד", "participants": [a1], "turns": [{"speaker": a1, "text": "שלום"}], "decisions": []}
    os.makedirs(os.path.join(co.BASE, "meetings"), exist_ok=True)
    with open(os.path.join(co.BASE, "meetings", "day-0.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    assert run(co, "meeting", "--file", "meetings/day-0.json")["ok"] is True
    m["participants"] = ["nobody"]
    with open(os.path.join(co.BASE, "meetings", "day-0.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    with pytest.raises(SystemExit):
        run(co, "meeting", "--file", "meetings/day-0.json")


# ------------------------------------------------------ report + office
def test_report_and_office_build(co):
    aid = hire(co, name="דנה", role="מפתחת", dept="tech")
    _do_task(co, aid, ok=True)
    run(co, "inbox", "add", "--text", "שאלה לבעלים")
    os.makedirs(os.path.join(co.BASE, "memory"), exist_ok=True)
    with open(os.path.join(co.BASE, "memory", "narr.md"), "w", encoding="utf-8") as f:
        f.write("יום ראשון טוב.")
    text = run(co, "report", "--narrative-file", "memory/narr.md")
    assert "דוח מנכ" in text and "✅" in text and "שאלה לבעלים" in text and "יום ראשון טוב." in text
    assert os.path.exists(os.path.join(co.BASE, "reports", "day-0.md"))

    res = run(co, "build-office")
    assert res["agents"] == 1 and res["tasks"] == 1
    with open(os.path.join(co.BASE, "office", "data.js"), encoding="utf-8") as f:
        js = f.read()
    assert js.startswith("window.MAKOR_DATA = ")
    data = json.loads(js[len("window.MAKOR_DATA = "):].rstrip().rstrip(";"))
    assert data["agents"][0]["room"] == "dev"
    assert data["reports"][0]["day"] == 0
