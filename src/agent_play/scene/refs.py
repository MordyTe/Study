"""RefStore: allocates snapshot-qualified refs and resolves them later.

A ref is `@<snapshot_id>:e<N>`. The entry stores the identity agent-desktop uses (role, native id,
name, description), plus bounds and a pixel fingerprint, because a game sprite has no native id and its
twins differ only by position.
"""

from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_play.envelope import AgentPlayError, ErrorCode
from agent_play.scene.node import Rect, SceneNode
from agent_play.scene.snapshot import Snapshot

_REF_RE = re.compile(r"^@(s[0-9a-z]{4,16}):e([1-9][0-9]{0,5})$")


def parse_ref(ref_id: str) -> tuple[str, int]:
    match = _REF_RE.match(ref_id.strip())
    if not match:
        raise AgentPlayError(
            ErrorCode.INVALID_ARGS,
            f"Invalid ref_id {ref_id!r}: expected @<snapshot_id>:e<N>",
            "Use the snapshot-qualified ref that snapshot prints, for example @s8f3k2p9:e1.",
            {"ref_id": ref_id},
        )
    return match.group(1), int(match.group(2))


@dataclass
class RefEntry:
    ref_id: str
    snapshot_id: str
    role: str
    name: str | None
    description: str | None
    native_id: str | None
    bounds: dict[str, float] | None
    source: str
    confidence: float
    identity_unique: bool
    captured_at_ms: int
    fingerprint: list[int] | None = None
    states: list[str] = field(default_factory=list)

    def rect(self) -> Rect | None:
        return Rect.from_dict(self.bounds) if self.bounds else None

    def identity_key(self) -> tuple[str, str | None, str | None, str | None]:
        return (self.role, self.native_id, self.name, self.description)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "RefEntry":
        return RefEntry(**data)


FingerprintFn = Any


class RefStore:
    """Persists ref maps per snapshot. `root=None` keeps everything in memory (tests, embedded use)."""

    def __init__(self, root: Path | None = None, keep_in_memory: int = 32) -> None:
        self.root = root
        self._snapshots: "OrderedDict[str, Snapshot]" = OrderedDict()
        self._entries: dict[str, dict[str, RefEntry]] = {}
        self._keep = keep_in_memory
        self._lock = threading.Lock()
        if root is not None:
            (root / "snapshots").mkdir(parents=True, exist_ok=True)

    def allocate(self, snapshot: Snapshot, fingerprint_fn: FingerprintFn | None = None) -> Snapshot:
        """Assigns refs to interactive nodes with bounds and records their identity."""
        counts: dict[tuple[str, str | None, str | None, str | None], int] = {}
        for node in snapshot.nodes():
            key = node.identity_key()
            counts[key] = counts.get(key, 0) + 1
        entries: dict[str, RefEntry] = {}
        counter = 0
        for node in snapshot.nodes():
            if not node.interactive or node.bounds is None:
                node.ref_id = None
                continue
            counter += 1
            node.ref_id = f"@{snapshot.snapshot_id}:e{counter}"
            fingerprint = fingerprint_fn(node.bounds) if fingerprint_fn else None
            entries[node.ref_id] = RefEntry(
                ref_id=node.ref_id,
                snapshot_id=snapshot.snapshot_id,
                role=node.role,
                name=node.name,
                description=node.description,
                native_id=node.native_id,
                bounds=node.bounds.to_dict(),
                source=node.source,
                confidence=node.confidence,
                identity_unique=counts[node.identity_key()] == 1,
                captured_at_ms=snapshot.captured_at_ms,
                fingerprint=fingerprint,
                states=list(node.states),
            )
        with self._lock:
            self._snapshots[snapshot.snapshot_id] = snapshot
            self._entries[snapshot.snapshot_id] = entries
            self._snapshots.move_to_end(snapshot.snapshot_id)
            while len(self._snapshots) > self._keep:
                old_id, _ = self._snapshots.popitem(last=False)
                self._entries.pop(old_id, None)
        self._persist(snapshot, entries)
        return snapshot

    def resolve(self, ref_id: str) -> RefEntry:
        snapshot_id, _ = parse_ref(ref_id)
        entries = self._load_entries(snapshot_id)
        if entries is None:
            raise AgentPlayError(
                ErrorCode.SNAPSHOT_NOT_FOUND,
                f"Snapshot {snapshot_id} is not available",
                "Take a new snapshot and use a ref from it.",
                {"snapshot_id": snapshot_id},
            )
        entry = entries.get(ref_id)
        if entry is None:
            raise AgentPlayError(
                ErrorCode.STALE_REF,
                f"Ref {ref_id} was not allocated by snapshot {snapshot_id}",
                "Take a fresh snapshot and use a ref that it prints.",
                {"kind": "saved_ref_absent", "ref_id": ref_id},
            )
        return entry

    def snapshot(self, snapshot_id: str) -> Snapshot | None:
        with self._lock:
            cached = self._snapshots.get(snapshot_id)
        if cached is not None:
            return cached
        if self.root is None:
            return None
        path = self.root / "snapshots" / f"{snapshot_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Snapshot.from_dict(data["snapshot"])

    def latest(self) -> Snapshot | None:
        with self._lock:
            if not self._snapshots:
                return self._latest_on_disk()
            return next(reversed(self._snapshots.values()))

    def _latest_on_disk(self) -> Snapshot | None:
        if self.root is None:
            return None
        files = sorted((self.root / "snapshots").glob("s*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            return None
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        return Snapshot.from_dict(data["snapshot"])

    def _load_entries(self, snapshot_id: str) -> dict[str, RefEntry] | None:
        with self._lock:
            entries = self._entries.get(snapshot_id)
        if entries is not None:
            return entries
        if self.root is None:
            return None
        path = self.root / "snapshots" / f"{snapshot_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        loaded = {ref: RefEntry.from_dict(entry) for ref, entry in data["refs"].items()}
        with self._lock:
            self._entries[snapshot_id] = loaded
        return loaded

    def _persist(self, snapshot: Snapshot, entries: dict[str, RefEntry]) -> None:
        if self.root is None:
            return
        path = self.root / "snapshots" / f"{snapshot.snapshot_id}.json"
        payload = {"snapshot": snapshot.to_dict(), "refs": {ref: entry.to_dict() for ref, entry in entries.items()}}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)


def match_candidates(entry: RefEntry, nodes: list[SceneNode]) -> list[SceneNode]:
    """Nodes in a fresh scene that share the entry's identity key."""
    key = entry.identity_key()
    return [node for node in nodes if node.identity_key() == key and node.bounds is not None]


def choose_by_position(entry: RefEntry, candidates: list[SceneNode], max_distance: float) -> SceneNode | None:
    """Among identical twins, the one closest to where the ref was captured, if it is close enough."""
    stored = entry.rect()
    if stored is None or not candidates:
        return None
    scored = sorted(candidates, key=lambda node: stored.moved_by(node.bounds))  # type: ignore[arg-type]
    best = scored[0]
    if stored.iou(best.bounds) > 0.0 or stored.moved_by(best.bounds) <= max_distance:  # type: ignore[arg-type]
        return best
    return None
