"""Fusion of several perceivers into one scene with provenance.

Rules: sources are merged in priority order (a11y, sim, template, ocr, vision). An overlapping node
from a lower-priority source corroborates the higher one and may fill a missing name or text, but never
overwrites a name the higher source supplied. Confidence is the maximum seen.
"""

from __future__ import annotations

from agent_play.scene.node import SOURCE_PRIORITY, SceneNode

GENERIC_ROLES = {"unknown", "image", "region", "group", "text", "tile"}


def _compatible(a: str, b: str) -> bool:
    return a == b or a in GENERIC_ROLES or b in GENERIC_ROLES


def _priority(source: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def fuse(per_source: list[tuple[str, list[SceneNode]]], iou_threshold: float = 0.5) -> list[SceneNode]:
    ordered = sorted(per_source, key=lambda item: _priority(item[0]))
    roots: list[SceneNode] = []
    index: list[SceneNode] = []
    for _, nodes in ordered:
        for node in nodes:
            if node.children:
                roots.append(node)
                index.extend(n for n, _ in node.walk() if n.bounds is not None)
                continue
            match = _best_overlap(node, index, iou_threshold)
            if match is None:
                roots.append(node)
                if node.bounds is not None:
                    index.append(node)
            else:
                _merge(match, node)
    return roots


def _best_overlap(node: SceneNode, index: list[SceneNode], threshold: float) -> SceneNode | None:
    if node.bounds is None:
        return None
    best, best_iou = None, threshold
    for candidate in index:
        if candidate.bounds is None or not _compatible(candidate.role, node.role):
            continue
        iou = candidate.bounds.iou(node.bounds)
        if iou >= best_iou:
            best, best_iou = candidate, iou
    return best


def _merge(target: SceneNode, extra: SceneNode) -> None:
    if target.role in GENERIC_ROLES and extra.role not in GENERIC_ROLES:
        target.role = extra.role
        target.interactive = target.interactive or extra.interactive
    if not target.name and extra.name:
        target.name = extra.name
    if not target.value and extra.value:
        target.value = extra.value
    if not target.description and extra.description:
        target.description = extra.description
    for state in extra.states:
        if state not in target.states:
            target.states.append(state)
    if extra.interactive and not target.interactive:
        target.interactive = True
    target.confidence = max(target.confidence, extra.confidence)
    if extra.source not in target.corroborated_by and extra.source != target.source:
        target.corroborated_by.append(extra.source)
