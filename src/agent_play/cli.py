"""The agent-play CLI. Every command prints one JSON envelope on stdout; logs go to stderr."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from agent_play import __version__
from agent_play.actions.backend import default_backend
from agent_play.actions.executor import ActionRequest
from agent_play.actions.policy import InteractionPolicy
from agent_play.envelope import AgentPlayError, ErrorCode, Response
from agent_play.scene.node import Rect
from agent_play.session import Session, default_state_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-play", description="Computer-use agent for games and desktop apps.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--headed", action="store_true", help="Send real input. Without it every action is dry-run.")
    parser.add_argument("--input", choices=["dryrun", "pynput", "win32"], help="Input backend for --headed")
    parser.add_argument("--session", help="Session namespace for refs and traces (default: AGENT_PLAY_SESSION or 'default')")
    parser.add_argument("--home", help="State root (default: AGENT_PLAY_HOME or ~/.agent-play)")
    parser.add_argument("--app", help="Native app name: adds the agent-desktop accessibility bridge")
    parser.add_argument("--templates", help="Directory of <role>__<name>.png templates")
    parser.add_argument("--no-vision", action="store_true", help="Do not call the vision model")
    parser.add_argument("--no-ocr", action="store_true", help="Skip OCR even when installed")
    parser.add_argument("--model", default=os.environ.get("AGENT_PLAY_MODEL", "claude-opus-5-5"))
    parser.add_argument("--effort", default=os.environ.get("AGENT_PLAY_EFFORT", "medium"), choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--monitor", type=int, default=1)
    parser.add_argument("--region", help="x,y,w,h region of the monitor to capture")
    parser.add_argument("--image", help="Use a PNG file as the screen instead of capturing (tests, replays)")
    parser.add_argument("--no-redact", action="store_true", help="Keep text values in the trace")
    parser.add_argument("--sim", action="store_true", help="Drive the built-in simulator instead of the screen; its state persists per session")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Platform, backends and perceivers available here")
    snap = sub.add_parser("snapshot", help="Observe the screen and print the scene with refs")
    snap.add_argument("--skeleton", action="store_true")
    snap.add_argument("-i", "--interactive", action="store_true", help="Interactive nodes only")
    snap.add_argument("--text", action="store_true", help="Compact text instead of the JSON tree")
    snap.add_argument("--fast", action="store_true", help="Cheap perceivers only")
    for name in ("click", "double-click", "right-click", "hover"):
        p = sub.add_parser(name)
        p.add_argument("ref")
        p.add_argument("--expect", help="Text that should be visible afterwards")
    mc = sub.add_parser("mouse-click", help="Click a coordinate (needs --headed)")
    mc.add_argument("--xy", required=True)
    mc.add_argument("--button", default="left", choices=["left", "right", "middle"])
    pr = sub.add_parser("press")
    pr.add_argument("key")
    hk = sub.add_parser("hold-key")
    hk.add_argument("key")
    hk.add_argument("--ms", type=int, default=200)
    ty = sub.add_parser("type")
    ty.add_argument("text")
    sc = sub.add_parser("scroll")
    sc.add_argument("ref")
    sc.add_argument("--direction", default="down", choices=["up", "down", "left", "right"])
    sc.add_argument("--amount", type=int, default=3)
    dr = sub.add_parser("drag")
    dr.add_argument("ref")
    dr.add_argument("--to", required=True)
    wt = sub.add_parser("wait")
    wt.add_argument("--text")
    wt.add_argument("--ref")
    wt.add_argument("--gone", action="store_true")
    wt.add_argument("--stable", action="store_true")
    wt.add_argument("--timeout", type=int, default=5000)
    run = sub.add_parser("run", help="Let the agent carry out a task on the screen")
    run.add_argument("task")
    run.add_argument("--max-steps", type=int, default=40)
    run.add_argument("--skill", action="append", default=[], help="Extra skill, e.g. genres/puzzle")
    run.add_argument("--instructions", default="")
    sk = sub.add_parser("skills")
    sk_sub = sk.add_subparsers(dest="skills_command", required=True)
    sk_sub.add_parser("list")
    sk_get = sk_sub.add_parser("get")
    sk_get.add_argument("name")
    ac = sub.add_parser("anticheat", help="Classify a game or task against the anti-cheat registry")
    ac.add_argument("text", nargs="?", default="")
    ac.add_argument("--list", action="store_true", help="List the known systems and games")
    kn = sub.add_parser("knowledge", help="Durable notes the agent keeps across runs")
    kn_sub = kn.add_subparsers(dest="knowledge_command", required=True)
    kn_sub.add_parser("list")
    kn_show = kn_sub.add_parser("show")
    kn_show.add_argument("topic")
    kn_add = kn_sub.add_parser("add")
    kn_add.add_argument("topic")
    kn_add.add_argument("text")
    sim = sub.add_parser("sim", help="The built-in grid game")
    sim_sub = sim.add_subparsers(dest="sim_command", required=True)
    frame = sim_sub.add_parser("frame", help="Render one frame to a PNG")
    frame.add_argument("--out", required=True)
    frame.add_argument("--state", default="title", choices=["title", "dialog", "playing", "won"])
    sim_sub.add_parser("snapshot", help="Observe the simulator through the template perceiver")
    sim_sub.add_parser("status", help="Ground-truth state of the persisted simulator (for humans, not for the agent)")
    sim_sub.add_parser("reset", help="Reset the persisted simulator to the title screen")
    play = sim_sub.add_parser("play", help="Let the model play the simulator")
    play.add_argument("task", nargs="?", default="Reach the star.")
    play.add_argument("--max-steps", type=int, default=30)
    play.add_argument("--vision", action="store_true", help="Also use the vision model for perception")
    play.add_argument("--scripted", action="store_true", help="Use the built-in scripted player instead of a model")
    return parser


def _state_root(args: argparse.Namespace) -> Path:
    return Path(args.home) if args.home else default_state_root()


def _session_id(args: argparse.Namespace) -> str:
    return args.session or os.environ.get("AGENT_PLAY_SESSION") or "default"


def _sim_state_path(args: argparse.Namespace) -> Path:
    return _state_root(args) / "sessions" / _session_id(args) / "sim-state.json"


def _load_sim(args: argparse.Namespace) -> Any:
    from agent_play.sim.grid_game import GridGame

    return GridGame.load(_sim_state_path(args))


def build_session(args: argparse.Namespace) -> Session:
    from agent_play.perception.capture import ScreenCapture, StaticFrameSource
    from agent_play.perception.ocr import OcrPerceiver
    from agent_play.perception.template import TemplateLibrary, TemplatePerceiver

    if args.sim:
        from agent_play.sim.grid_game import make_session

        game = _load_sim(args)
        session = make_session(game, root=_state_root(args), session_id=_session_id(args))
        session.sim_game = game  # type: ignore[attr-defined]
        return session
    if args.image:
        from PIL import Image

        with Image.open(args.image) as image:
            source: Any = StaticFrameSource(image.convert("RGB").copy())
    else:
        region = None
        if args.region:
            x, y, w, h = (float(v) for v in args.region.split(","))
            region = Rect(x, y, w, h)
        source = ScreenCapture(monitor=args.monitor, region=region)
    perceivers: list[Any] = []
    a11y_click = None
    if args.app:
        from agent_play.perception.a11y_bridge import (
            AccessibilityBridge,
            AccessibilityPerceiver,
        )

        bridge = AccessibilityBridge()
        perceivers.append(AccessibilityPerceiver(bridge, app=args.app))
        a11y_click = bridge.click
    if args.templates:
        perceivers.append(TemplatePerceiver(TemplateLibrary.load_dir(Path(args.templates))))
    if not args.no_ocr:
        perceivers.append(OcrPerceiver())
    if not args.no_vision:
        from agent_play.perception.vision_llm import (
            AnthropicVisionModel,
            VisionPerceiver,
        )

        perceivers.append(VisionPerceiver(AnthropicVisionModel(model=args.model, effort="low")))
    backend = default_backend(args.headed, args.input)
    policy = InteractionPolicy(headed=args.headed)
    return Session(source, perceivers, backend, policy, root=_state_root(args), session_id=_session_id(args), a11y_click=a11y_click, redact_trace=not args.no_redact)


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    import platform
    import shutil

    def has(module: str) -> bool:
        try:
            __import__(module)
            return True
        except Exception:
            return False

    data: dict[str, Any] = {
        "version": __version__,
        "platform": platform.system().lower(),
        "python": platform.python_version(),
        "state_root": str(_state_root(args)),
        "session_id": _session_id(args),
        "capture": {"mss": has("mss")},
        "input": {"pynput": has("pynput"), "win32": sys.platform == "win32", "headed": args.headed},
        "perception": {
            "template": True,
            "opencv": has("cv2"),
            "ocr": has("rapidocr_onnxruntime") or has("pytesseract"),
            "vision_model": args.model,
            "api_key_present": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
            "agent_desktop": shutil.which("agent-desktop") is not None,
        },
    }
    return data


def cmd_snapshot(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    snapshot = session.observe(fast_only=args.fast)
    shown = snapshot.skeleton(2) if args.skeleton else snapshot
    data: dict[str, Any] = {
        "snapshot_id": snapshot.snapshot_id,
        "ref_count": snapshot.ref_count(),
        "sources": snapshot.sources,
        "surfaces": snapshot.surfaces,
        "complete": snapshot.complete,
        "screen": {"width": snapshot.screen[0], "height": snapshot.screen[1]},
    }
    if snapshot.summary:
        data["summary"] = snapshot.summary
    if args.text:
        data["scene"] = shown.compact_text(interactive_only=args.interactive)
    else:
        tree = shown.to_dict()["tree"]
        if args.interactive:
            tree = [n.to_dict() for n in shown.nodes() if n.interactive or n.children_count]
        data["tree"] = tree
    return data


def _action(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    command = args.command
    if command in ("click", "double-click", "right-click", "hover"):
        request = ActionRequest(command.replace("-", "_"), ref_id=args.ref, expect_text=args.expect)
    elif command == "mouse-click":
        x, y = (float(v) for v in args.xy.split(","))
        request = ActionRequest("mouse_click", x=x, y=y, button=args.button)
    elif command == "press":
        request = ActionRequest("press", key=args.key)
    elif command == "hold-key":
        request = ActionRequest("hold_key", key=args.key, duration_ms=args.ms)
    elif command == "type":
        request = ActionRequest("type_text", text=args.text)
    elif command == "scroll":
        request = ActionRequest("scroll", ref_id=args.ref, direction=args.direction, amount=args.amount)
    elif command == "drag":
        request = ActionRequest("drag", ref_id=args.ref, to_ref=args.to)
    else:
        raise AgentPlayError(ErrorCode.INVALID_ARGS, f"Unknown command {command}")
    return session.act(request).to_dict()


def cmd_run(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    from agent_play.agent.loop import AgentConfig, GameAgent
    from agent_play.agent.model import AnthropicModelClient

    model = AnthropicModelClient(model=args.model, effort=args.effort)
    agent = GameAgent(session, model, AgentConfig(max_steps=args.max_steps), skills=["core", *args.skill], extra_instructions=args.instructions, log=_stderr)
    return agent.run(args.task).to_dict()


def cmd_sim(args: argparse.Namespace) -> dict[str, Any]:
    from agent_play.sim.grid_game import GridGame, make_session, path_to_goal

    if args.sim_command == "frame":
        game = GridGame()
        game.state = args.state
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        game.render().save(out)
        return {"path": str(out), "state": args.state, "width": game.render().width, "height": game.render().height}
    if args.sim_command == "status":
        return {"game": _load_sim(args).status(), "state_path": str(_sim_state_path(args))}
    if args.sim_command == "reset":
        game = GridGame()
        game.save(_sim_state_path(args))
        return {"game": game.status(), "state_path": str(_sim_state_path(args))}
    game = _load_sim(args)
    extra: list[Any] = []
    if args.sim_command == "play" and args.vision:
        from agent_play.perception.vision_llm import (
            AnthropicVisionModel,
            VisionPerceiver,
        )

        extra.append(VisionPerceiver(AnthropicVisionModel(model=args.model, effort="low")))
    session = make_session(game, root=_state_root(args), extra_perceivers=extra, session_id=_session_id(args))
    if args.sim_command == "snapshot":
        snapshot = session.observe()
        game.save(_sim_state_path(args))
        return {"snapshot_id": snapshot.snapshot_id, "ref_count": snapshot.ref_count(), "scene": snapshot.compact_text()}
    from agent_play.agent.loop import AgentConfig, GameAgent

    if args.scripted:
        from agent_play.agent.model import ScriptedModelClient, ToolCall

        def script(messages: list[dict[str, Any]], index: int) -> list[ToolCall] | None:
            if game.state == "title":
                latest = session.last_snapshot
                start = next((n for n in latest.nodes() if n.name == "start" and n.ref_id), None) if latest else None
                return [ToolCall("", "click", {"ref_id": start.ref_id})] if start else [ToolCall("", "observe", {"detail": "full"})]
            if game.state == "dialog":
                return [ToolCall("", "press", {"key": "enter"})]
            if game.state == "playing":
                path = path_to_goal(game)
                return [ToolCall("", "press", {"key": path[0]})] if path else [ToolCall("", "done", {"success": False, "summary": "no path"})]
            return [ToolCall("", "done", {"success": True, "summary": "YOU WIN is on screen"})]

        model: Any = ScriptedModelClient(script)
    else:
        from agent_play.agent.model import AnthropicModelClient

        model = AnthropicModelClient(model=args.model, effort=args.effort)
    agent = GameAgent(session, model, AgentConfig(max_steps=args.max_steps, include_image=not args.scripted), skills=["core", "genres/puzzle"], log=_stderr)
    result = agent.run(args.task).to_dict()
    result["game"] = game.status()
    game.save(_sim_state_path(args))
    return result


def _stderr(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "status":
        return cmd_status(args)
    if args.command == "skills":
        from agent_play.skills import list_skills, load_skill

        if args.skills_command == "list":
            return {"skills": list_skills()}
        return {"name": args.name, "content": load_skill(args.name)}
    if args.command == "anticheat":
        from agent_play.knowledge.anticheat import assess, known_games, known_systems

        if args.list or not args.text:
            return {"systems": known_systems(), "games": known_games()}
        return assess(args.text).to_dict()
    if args.command == "knowledge":
        from agent_play.knowledge.store import KnowledgeStore

        store = KnowledgeStore(_state_root(args))
        if args.knowledge_command == "list":
            return {"topics": store.topics(), "dir": str(store.dir)}
        if args.knowledge_command == "show":
            text = store.read(args.topic)
            if text is None:
                raise AgentPlayError(ErrorCode.INVALID_ARGS, f"No knowledge topic {args.topic!r}", f"Known topics: {', '.join(store.topics()) or 'none'}")
            return {"topic": args.topic, "content": text}
        slug = store.add(args.topic, args.text)
        return {"topic": slug, "topics": store.topics()}
    if args.command == "sim":
        return cmd_sim(args)
    session = build_session(args)
    try:
        if args.command == "snapshot":
            return cmd_snapshot(args, session)
        if args.command == "wait":
            return session.wait(text=args.text, ref_id=args.ref, gone=args.gone, stable=args.stable, timeout_ms=args.timeout)
        if args.command == "run":
            return cmd_run(args, session)
        return _action(args, session)
    finally:
        game = getattr(session, "sim_game", None)
        if game is not None:
            game.save(_sim_state_path(args))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command if args.command != "sim" else f"sim.{args.sim_command}"
    try:
        data = dispatch(args)
    except AgentPlayError as exc:
        print(Response.to_json(Response.err(command, exc)))
        return 1
    except KeyboardInterrupt:
        print(Response.to_json(Response.err(command, AgentPlayError(ErrorCode.INTERNAL, "Interrupted"))))
        return 130
    print(Response.to_json(Response.ok(command, data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
