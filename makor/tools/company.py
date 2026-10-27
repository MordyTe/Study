#!/usr/bin/env python3
"""מקור (Makor) — the company's deterministic backbone.

Everything the agents are NOT allowed to decide by themselves lives here:
whether a task is really done (evidence checked by code, never by a story),
how agents are scored, who gets fired, what the owner must decide, and how
the office page and the CEO report are built from the recorded state.

Stdlib only. Usage: python tools/company.py <command> [options]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# MAKOR_BASE lets the tests run against a throwaway copy of the company.
BASE = os.environ.get("MAKOR_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BASE, "state")
ORG = os.path.join(BASE, "org")
MEETINGS = os.path.join(BASE, "meetings")
REPORTS = os.path.join(BASE, "reports")
OFFICE = os.path.join(BASE, "office")

# Files agents must never touch (checked every verify).
PROTECTED = ["tools/company.py", "tests", "state/protected.json", "COMPANY.md"]

STAGE_GATES = [
    "כלי ראשון עובד (טסטים עוברים)",
    "כלי ראשון באוויר (פורסם במארקטפלייס)",
    "$ ראשון",
    "10 כלים משלמים",
    "$1,000 בחודש",
    "תהליך שרץ לבד (<30 דק' אדם בשבוע)",
]

TASK_STATUSES = ("todo", "in_progress", "review", "done", "failed")
FIRE_CONSECUTIVE_FAILS = 2
FIRE_AVG_BELOW = 5.0
FIRE_MIN_DAYS = 3
MAX_TASKS_PER_DAY = 6


# ---------------------------------------------------------------- io helpers
def _path(rel: str) -> str:
    return os.path.join(BASE, rel)


def load(rel: str, default: Any):
    p = _path(rel)
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save(rel: str, data: Any) -> None:
    p = _path(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> int:
    return int(load("state/day.json", {"day": 0})["day"])


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def _sha(path: str) -> str:
    h = hashlib.sha256()
    if os.path.isdir(path):
        for root, _d, files in os.walk(path):
            for fn in sorted(files):
                fp = os.path.join(root, fn)
                h.update(fn.encode())
                with open(fp, "rb") as f:
                    h.update(f.read())
    else:
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


# ------------------------------------------------------------------- init
def cmd_init(_a) -> Dict:
    defaults = {
        "state/day.json": {"day": 0, "date": now_iso(), "stage": 0, "phase": "founded"},
        "state/tasks.json": [],
        "state/metrics.json": {"history": []},
        "state/decisions.json": [],
        "state/hr.json": [],
        "state/inbox.json": [],
        "org/roster.json": [],
    }
    created = []
    for rel, val in defaults.items():
        if not os.path.exists(_path(rel)):
            save(rel, val)
            created.append(rel)
    for d in (MEETINGS, REPORTS, OFFICE, os.path.join(BASE, "product"), os.path.join(BASE, "memory")):
        os.makedirs(d, exist_ok=True)
    cmd_seal(_a)
    return {"created": created}


def cmd_seal(_a) -> Dict:
    """Record hashes of the protected files (only the orchestrator runs this)."""

    hashes = {rel: _sha(_path(rel)) for rel in PROTECTED if os.path.exists(_path(rel)) and rel != "state/protected.json"}
    save("state/protected.json", {"sealed_at": now_iso(), "hashes": hashes})
    return {"sealed": list(hashes)}


def protected_violations() -> List[str]:
    sealed = load("state/protected.json", {}).get("hashes", {})
    bad = []
    for rel, digest in sealed.items():
        p = _path(rel)
        if not os.path.exists(p) or _sha(p) != digest:
            bad.append(rel)
    return bad


# ----------------------------------------------------------------- days
def cmd_new_day(_a) -> Dict:
    day = load("state/day.json", {"day": 0, "stage": 0})
    day["day"] = int(day.get("day", 0)) + 1
    day["date"] = now_iso()
    day["phase"] = "morning"
    save("state/day.json", day)
    return {"day": day["day"]}


def cmd_phase(a) -> Dict:
    day = load("state/day.json", {"day": 0})
    day["phase"] = a.phase
    save("state/day.json", day)
    return {"phase": a.phase}


# ----------------------------------------------------------------- roster
def roster() -> List[Dict]:
    return load("org/roster.json", [])


def active_agents() -> List[Dict]:
    return [a for a in roster() if a.get("status") == "active"]


def find_agent(agent_id: str) -> Optional[Dict]:
    for a in roster():
        if a["id"] == agent_id:
            return a
    return None


def cmd_hire(a) -> Dict:
    agents = roster()
    agent = {
        "id": a.id or new_id("agt"),
        "name": a.name,
        "role": a.role,
        "dept": a.dept,
        "level": a.level,
        "persona": a.persona or "",
        "status": "active",
        "hired_day": today(),
        "fired_day": None,
        "scores": [],  # [{day, task, score}]
    }
    if find_agent(agent["id"]):
        raise SystemExit(f"agent {agent['id']} already exists")
    agents.append(agent)
    save("org/roster.json", agents)
    hr = load("state/hr.json", [])
    hr.append({"day": today(), "event": "hired", "agent": agent["id"], "name": a.name,
               "role": a.role, "reason": a.reason or "פתיחת תפקיד", "ts": now_iso()})
    save("state/hr.json", hr)
    return {"hired": agent["id"]}


def _fire(agent: Dict, reason: str, hr: List[Dict]) -> None:
    agent["status"] = "fired"
    agent["fired_day"] = today()
    hr.append({"day": today(), "event": "fired", "agent": agent["id"], "name": agent["name"],
               "role": agent["role"], "reason": reason, "ts": now_iso()})


# ----------------------------------------------------------------- tasks
def tasks() -> List[Dict]:
    return load("state/tasks.json", [])


def cmd_add_task(a) -> Dict:
    all_tasks = tasks()
    day = today()
    if len([t for t in all_tasks if t["day"] == day]) >= MAX_TASKS_PER_DAY:
        raise SystemExit(f"day {day} already has {MAX_TASKS_PER_DAY} tasks (hard cap)")
    if a.owner and not find_agent(a.owner):
        raise SystemExit(f"unknown owner {a.owner}")
    task = {
        "id": new_id("task"),
        "day": day,
        "title": a.title,
        "desc": a.desc or "",
        "owner": a.owner,
        "dept": a.dept,
        "status": "todo",
        "acceptance": {"type": a.acceptance_type, "arg": a.acceptance_arg},
        "evidence": None,
        "qa": None,
        "verify": None,
        "score": None,
        "done_day": None,
    }
    all_tasks.append(task)
    save("state/tasks.json", all_tasks)
    return {"id": task["id"]}


def _get_task(all_tasks: List[Dict], task_id: str) -> Dict:
    for t in all_tasks:
        if t["id"] == task_id:
            return t
    raise SystemExit(f"unknown task {task_id}")


def cmd_start(a) -> Dict:
    all_tasks = tasks()
    t = _get_task(all_tasks, a.id)
    if t["status"] == "todo":
        t["status"] = "in_progress"
    save("state/tasks.json", all_tasks)
    return {"id": t["id"], "status": t["status"]}


def cmd_submit(a) -> Dict:
    """The worker claims the task is done and points to the evidence."""

    all_tasks = tasks()
    t = _get_task(all_tasks, a.id)
    t["evidence"] = a.evidence
    t["notes"] = a.notes or ""
    t["status"] = "review"
    save("state/tasks.json", all_tasks)
    return {"id": t["id"], "status": "review"}


def cmd_qa(a) -> Dict:
    all_tasks = tasks()
    t = _get_task(all_tasks, a.id)
    t["qa"] = {"passed": bool(a.passed), "notes": a.notes or "", "by": a.by or "qa", "ts": now_iso()}
    save("state/tasks.json", all_tasks)
    return {"id": t["id"], "qa": t["qa"]}


def _run_acceptance(t: Dict) -> Dict:
    acc = t.get("acceptance") or {}
    kind, arg = acc.get("type"), acc.get("arg")
    try:
        if kind == "file_exists":
            p = _path(arg)
            ok = os.path.exists(p) and (os.path.isdir(p) or os.path.getsize(p) > 0)
            return {"ok": ok, "detail": f"{arg} {'exists' if ok else 'missing/empty'}"}
        if kind == "file_contains":
            path, needle = arg.split("::", 1)
            with open(_path(path), "r", encoding="utf-8") as f:
                ok = needle in f.read()
            return {"ok": ok, "detail": f"'{needle}' {'found' if ok else 'not found'} in {path}"}
        if kind == "command":
            r = subprocess.run(arg, shell=True, cwd=BASE, capture_output=True, text=True, timeout=600)
            tail = (r.stdout + r.stderr)[-400:]
            return {"ok": r.returncode == 0, "detail": f"exit {r.returncode}: {tail.strip()}"}
        if kind == "tests_pass":
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", arg], cwd=BASE,
                               capture_output=True, text=True, timeout=900)
            tail = (r.stdout + r.stderr).strip().splitlines()
            return {"ok": r.returncode == 0, "detail": tail[-1] if tail else f"exit {r.returncode}"}
        if kind == "min_lines":
            path, n = arg.split("::", 1)
            with open(_path(path), "r", encoding="utf-8") as f:
                lines = [l for l in f if l.strip()]
            ok = len(lines) >= int(n)
            return {"ok": ok, "detail": f"{len(lines)} non-empty lines (need {n})"}
        return {"ok": False, "detail": f"unknown acceptance type {kind}"}
    except Exception as exc:  # any error = not verified
        return {"ok": False, "detail": f"error: {exc}"}


def cmd_verify(a) -> Dict:
    """The only way a task becomes 'done'. Checks evidence with code."""

    all_tasks = tasks()
    results = []
    for t in all_tasks:
        if a.id and t["id"] != a.id:
            continue
        if t["status"] != "review":
            continue
        check = _run_acceptance(t)
        qa_failed = bool(t.get("qa")) and not t["qa"].get("passed", True)
        if check["ok"] and not qa_failed:
            t["status"] = "done"
            t["done_day"] = today()
        else:
            t["status"] = "failed"
            if qa_failed:
                check["detail"] = "QA failed: " + (t["qa"].get("notes") or "") + " | " + check["detail"]
        t["verify"] = {"ok": t["status"] == "done", "detail": check["detail"], "ts": now_iso()}
        results.append({"id": t["id"], "title": t["title"], "status": t["status"], "detail": check["detail"]})
    save("state/tasks.json", all_tasks)
    violations = protected_violations()
    if violations:
        dec = load("state/decisions.json", [])
        dec.append({"day": today(), "ts": now_iso(), "kind": "alert",
                    "text": f"קבצים מוגנים שונו ללא אישור: {', '.join(violations)}"})
        save("state/decisions.json", dec)
    return {"verified": results, "protected_violations": violations}


# ----------------------------------------------------------------- scores
def _task_score(t: Dict) -> Optional[int]:
    if t["status"] == "done":
        return 10 if not (t.get("qa") and t["qa"].get("notes")) else 8
    if t["status"] == "failed":
        return 0
    return None


def cmd_score(_a) -> Dict:
    agents = roster()
    by_id = {ag["id"]: ag for ag in agents}
    day = today()
    scored = []
    for t in tasks():
        if t.get("score") is not None or not t.get("owner") or t["owner"] not in by_id:
            continue
        s = _task_score(t)
        if s is None:
            continue
        t["score"] = s
        by_id[t["owner"]]["scores"].append({"day": day, "task": t["id"], "score": s})
        scored.append({"agent": t["owner"], "task": t["id"], "score": s})
    save("state/tasks.json", tasks_with_scores(scored))
    save("org/roster.json", agents)
    return {"scored": scored, "averages": {ag["id"]: agent_average(ag) for ag in agents if ag["scores"]}}


def tasks_with_scores(scored: List[Dict]) -> List[Dict]:
    all_tasks = tasks()
    m = {s["task"]: s["score"] for s in scored}
    for t in all_tasks:
        if t["id"] in m:
            t["score"] = m[t["id"]]
    return all_tasks


def agent_average(agent: Dict, last_days: int = FIRE_MIN_DAYS) -> Optional[float]:
    scores = agent.get("scores", [])
    if not scores:
        return None
    days = sorted({s["day"] for s in scores})[-last_days:]
    recent = [s["score"] for s in scores if s["day"] in days]
    return round(sum(recent) / len(recent), 2)


def cmd_hr(_a) -> Dict:
    """Apply the firing rules. Deterministic — no agent opinion involved."""

    agents = roster()
    hr = load("state/hr.json", [])
    fired = []
    for ag in agents:
        if ag["status"] != "active" or ag.get("level") == "executive":
            continue
        scores = ag.get("scores", [])
        last = [s["score"] for s in scores[-FIRE_CONSECUTIVE_FAILS:]]
        if len(last) == FIRE_CONSECUTIVE_FAILS and all(s == 0 for s in last):
            _fire(ag, f"{FIRE_CONSECUTIVE_FAILS} משימות כושלות ברצוף", hr)
            fired.append(ag["id"])
            continue
        days = {s["day"] for s in scores}
        avg = agent_average(ag)
        if len(days) >= FIRE_MIN_DAYS and avg is not None and avg < FIRE_AVG_BELOW:
            _fire(ag, f"ממוצע {avg} מתחת ל-{FIRE_AVG_BELOW} לאורך {len(days)} ימים", hr)
            fired.append(ag["id"])
    save("org/roster.json", agents)
    save("state/hr.json", hr)
    active_roles = {a["role"] for a in agents if a["status"] == "active"}
    open_roles = sorted({a["role"] for a in agents if a["id"] in fired} - active_roles)
    return {"fired": fired, "open_roles": open_roles}


# ----------------------------------------------------------- misc records
def cmd_inbox(a) -> Dict:
    inbox = load("state/inbox.json", [])
    if a.action == "add":
        item = {"id": new_id("q"), "day": today(), "question": a.text, "context": a.context or "",
                "status": "open", "answer": None, "ts": now_iso()}
        inbox.append(item)
        save("state/inbox.json", inbox)
        return {"added": item["id"]}
    for it in inbox:
        if it["id"] == a.id:
            it["answer"] = a.text
            it["status"] = "answered"
            it["answered_ts"] = now_iso()
            save("state/inbox.json", inbox)
            return {"answered": a.id}
    raise SystemExit(f"unknown inbox item {a.id}")


def cmd_decision(a) -> Dict:
    dec = load("state/decisions.json", [])
    dec.append({"day": today(), "ts": now_iso(), "kind": a.kind, "text": a.text, "by": a.by or "ceo"})
    save("state/decisions.json", dec)
    with open(_path("memory/decisions.md"), "a", encoding="utf-8") as f:
        f.write(f"- יום {today()} ({a.kind}, {a.by or 'ceo'}): {a.text}\n")
    return {"recorded": True}


def cmd_metric(a) -> Dict:
    m = load("state/metrics.json", {"history": []})
    m["history"].append({"day": today(), "key": a.key, "value": float(a.value), "ts": now_iso()})
    save("state/metrics.json", m)
    return {"recorded": a.key}


def cmd_stage(a) -> Dict:
    day = load("state/day.json", {"day": 0, "stage": 0})
    day["stage"] = int(a.stage)
    save("state/day.json", day)
    return {"stage": day["stage"], "name": STAGE_GATES[day["stage"]] if day["stage"] < len(STAGE_GATES) else "?"}


def cmd_meeting(a) -> Dict:
    """Validate and register a meeting transcript file."""

    with open(_path(a.file), "r", encoding="utf-8") as f:
        m = json.load(f)
    for key in ("day", "title", "participants", "turns"):
        if key not in m:
            raise SystemExit(f"meeting missing '{key}'")
    for turn in m["turns"]:
        if "speaker" not in turn or "text" not in turn:
            raise SystemExit("every turn needs speaker + text")
    ids = {ag["id"] for ag in roster()}
    unknown = [p for p in m["participants"] if p not in ids]
    if unknown:
        raise SystemExit(f"unknown participants: {unknown}")
    return {"ok": True, "turns": len(m["turns"]), "decisions": len(m.get("decisions", []))}


# ------------------------------------------------------------------ status
def summary() -> Dict:
    day = load("state/day.json", {"day": 0, "stage": 0})
    all_tasks = tasks()
    d = day["day"]
    todays = [t for t in all_tasks if t["day"] == d]
    agents = roster()
    return {
        "day": d,
        "stage": day.get("stage", 0),
        "stage_name": STAGE_GATES[min(day.get("stage", 0), len(STAGE_GATES) - 1)],
        "agents_active": len([a for a in agents if a["status"] == "active"]),
        "agents_fired_total": len([a for a in agents if a["status"] == "fired"]),
        "tasks_today": {s: len([t for t in todays if t["status"] == s]) for s in TASK_STATUSES},
        "tasks_total_done": len([t for t in all_tasks if t["status"] == "done"]),
        "tasks_total_failed": len([t for t in all_tasks if t["status"] == "failed"]),
        "open_questions": len([q for q in load("state/inbox.json", []) if q["status"] == "open"]),
        "protected_violations": protected_violations(),
    }


def cmd_status(_a) -> Dict:
    return summary()


# ------------------------------------------------------------------ report
def cmd_report(a) -> Dict:
    s = summary()
    d = s["day"]
    all_tasks = [t for t in tasks() if t["day"] == d]
    hr = [h for h in load("state/hr.json", []) if h["day"] == d]
    inbox_open = [q for q in load("state/inbox.json", []) if q["status"] == "open"]
    decisions = [x for x in load("state/decisions.json", []) if x["day"] == d]
    narrative = ""
    if a.narrative_file:
        with open(_path(a.narrative_file), "r", encoding="utf-8") as f:
            narrative = f.read().strip()

    lines = [f"# דוח מנכ\"ל — יום {d}", "", f"*{datetime.now().strftime('%Y-%m-%d')} · דוויין, מנכ\"ל מקור*", ""]
    if narrative:
        lines += [narrative, ""]
    lines += [f"## שער שלב: {s['stage'] + 1}/{len(STAGE_GATES)} — {s['stage_name']}", ""]
    lines += ["## משימות היום (אומתו על ידי סקריפט, לא לפי דיווח)", ""]
    if not all_tasks:
        lines.append("_אין משימות היום._")
    for t in all_tasks:
        mark = {"done": "✅", "failed": "❌"}.get(t["status"], "⏳")
        owner = find_agent(t["owner"]) if t.get("owner") else None
        who = owner["name"] if owner else "—"
        ev = f" · הוכחה: `{t['evidence']}`" if t.get("evidence") else ""
        det = f" · {t['verify']['detail']}" if t.get("verify") else ""
        lines.append(f"- {mark} **{t['title']}** — {who}{ev}{det}")
    lines += ["", "## כוח אדם", ""]
    if not hr:
        lines.append("_ללא שינויים._")
    for h in hr:
        verb = "גויס/ה" if h["event"] == "hired" else "פוטר/ה"
        lines.append(f"- {verb}: **{h['name']}** ({h['role']}) — {h['reason']}")
    lines += ["", f"צוות פעיל: {s['agents_active']} · סה\"כ משימות שבוצעו: {s['tasks_total_done']} · נכשלו: {s['tasks_total_failed']}", ""]
    if decisions:
        lines += ["## החלטות היום", ""] + [f"- {x['text']}" for x in decisions] + [""]
    lines += ["## צריך את ההחלטה שלך", ""]
    if not inbox_open:
        lines.append("_אין._")
    for q in inbox_open:
        lines.append(f"- **[{q['id']}]** {q['question']}" + (f" — {q['context']}" if q.get("context") else ""))
    if s["protected_violations"]:
        lines += ["", f"⚠️ **אזהרה:** קבצים מוגנים שונו: {', '.join(s['protected_violations'])}"]
    text = "\n".join(lines) + "\n"
    os.makedirs(REPORTS, exist_ok=True)
    out = os.path.join(REPORTS, f"day-{d}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    return {"report": os.path.relpath(out, BASE)}


# ------------------------------------------------------------- office data
ROOM_OF_DEPT = {"exec": "ceo", "ops": "ops", "product": "product", "tech": "dev",
                "marketing": "marketing", "qa": "qa", "hr": "hr", "research": "product"}


def cmd_build_office(_a) -> Dict:
    agents = roster()
    all_tasks = tasks()
    day = load("state/day.json", {"day": 0, "stage": 0})
    meetings = []
    if os.path.isdir(MEETINGS):
        for fn in sorted(os.listdir(MEETINGS)):
            if fn.endswith(".json"):
                with open(os.path.join(MEETINGS, fn), "r", encoding="utf-8") as f:
                    meetings.append(json.load(f))
    reports = []
    if os.path.isdir(REPORTS):
        for fn in sorted(os.listdir(REPORTS)):
            if fn.endswith(".md"):
                with open(os.path.join(REPORTS, fn), "r", encoding="utf-8") as f:
                    reports.append({"file": fn, "day": int(fn.split("-")[1].split(".")[0]), "text": f.read()})
    phase = day.get("phase", "")
    for ag in agents:
        current = next((t for t in reversed(all_tasks) if t.get("owner") == ag["id"] and t["status"] in ("in_progress", "review")), None)
        latest = next((t for t in reversed(all_tasks) if t.get("owner") == ag["id"]), None)
        in_meeting = phase == "morning" and ag.get("level") in ("executive", "manager")
        ag["room"] = "meeting" if in_meeting and ag["status"] == "active" else ROOM_OF_DEPT.get(ag["dept"], "dev")
        ag["activity"] = (current or latest or {}).get("title") or ("בישיבה" if in_meeting else "זמין/ה")
        ag["avg"] = agent_average(ag)
    data = {
        "company": "מקור",
        "generated": now_iso(),
        "day": day,
        "stage_gates": STAGE_GATES,
        "agents": agents,
        "tasks": all_tasks,
        "meetings": meetings,
        "hr": load("state/hr.json", []),
        "inbox": load("state/inbox.json", []),
        "decisions": load("state/decisions.json", []),
        "metrics": load("state/metrics.json", {"history": []})["history"],
        "reports": reports,
        "summary": summary(),
    }
    os.makedirs(OFFICE, exist_ok=True)
    out = os.path.join(OFFICE, "data.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write("window.MAKOR_DATA = ")
        json.dump(data, f, ensure_ascii=False)
        f.write(";\n")
    return {"written": os.path.relpath(out, BASE), "agents": len(agents), "tasks": len(all_tasks), "meetings": len(meetings)}


# -------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="company.py", description="Makor company backbone")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("seal").set_defaults(func=cmd_seal)
    sub.add_parser("new-day").set_defaults(func=cmd_new_day)
    x = sub.add_parser("phase"); x.add_argument("phase", choices=["morning", "work", "review", "report", "closed"]); x.set_defaults(func=cmd_phase)

    x = sub.add_parser("hire")
    x.add_argument("--id"); x.add_argument("--name", required=True); x.add_argument("--role", required=True)
    x.add_argument("--dept", required=True, choices=list(ROOM_OF_DEPT))
    x.add_argument("--level", default="worker", choices=["executive", "manager", "worker"])
    x.add_argument("--persona"); x.add_argument("--reason"); x.set_defaults(func=cmd_hire)

    x = sub.add_parser("add-task")
    x.add_argument("--title", required=True); x.add_argument("--desc"); x.add_argument("--owner")
    x.add_argument("--dept", required=True, choices=list(ROOM_OF_DEPT))
    x.add_argument("--acceptance-type", required=True, choices=["file_exists", "file_contains", "command", "tests_pass", "min_lines"])
    x.add_argument("--acceptance-arg", required=True); x.set_defaults(func=cmd_add_task)
    x = sub.add_parser("start"); x.add_argument("--id", required=True); x.set_defaults(func=cmd_start)
    x = sub.add_parser("submit"); x.add_argument("--id", required=True); x.add_argument("--evidence", required=True); x.add_argument("--notes"); x.set_defaults(func=cmd_submit)
    x = sub.add_parser("qa"); x.add_argument("--id", required=True); g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--pass", dest="passed", action="store_true"); g.add_argument("--fail", dest="passed", action="store_false")
    x.add_argument("--notes"); x.add_argument("--by"); x.set_defaults(func=cmd_qa)
    x = sub.add_parser("verify"); x.add_argument("--id"); x.set_defaults(func=cmd_verify)
    sub.add_parser("score").set_defaults(func=cmd_score)
    sub.add_parser("hr").set_defaults(func=cmd_hr)

    x = sub.add_parser("inbox"); x.add_argument("action", choices=["add", "answer"]); x.add_argument("--id"); x.add_argument("--text", required=True); x.add_argument("--context"); x.set_defaults(func=cmd_inbox)
    x = sub.add_parser("decision"); x.add_argument("--text", required=True); x.add_argument("--kind", default="decision", choices=["decision", "alert", "note"]); x.add_argument("--by"); x.set_defaults(func=cmd_decision)
    x = sub.add_parser("metric"); x.add_argument("--key", required=True); x.add_argument("--value", required=True); x.set_defaults(func=cmd_metric)
    x = sub.add_parser("stage"); x.add_argument("--stage", required=True); x.set_defaults(func=cmd_stage)
    x = sub.add_parser("meeting"); x.add_argument("--file", required=True); x.set_defaults(func=cmd_meeting)
    sub.add_parser("status").set_defaults(func=cmd_status)
    x = sub.add_parser("report"); x.add_argument("--narrative-file"); x.set_defaults(func=cmd_report)
    sub.add_parser("build-office").set_defaults(func=cmd_build_office)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out = args.func(args)
    if args.cmd != "report":
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
