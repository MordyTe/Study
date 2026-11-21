"""Slide templates: each is templates/<id>/template.json (fields) + template.html (Jinja).

Adding a template = adding a folder; no Python changes needed.
Field types: text, textarea, number, select, image, images, rows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

CATEGORIES = [
    {"id": "business", "name": "עסק", "hint": "מסעדה, חנות, מספרה, קליניקה"},
    {"id": "lobby", "name": "לובי בניין", "hint": "הודעות ועד, זמני שבת, שעון"},
    {"id": "synagogue", "name": "בית כנסת", "hint": "זמני תפילות, זמני היום, הודעות"},
    {"id": "general", "name": "כל דבר אחר", "hint": "תמונות, טקסט חופשי"},
]

THEMES = {
    "night": {"name": "לילה", "bg": "#0f172a", "fg": "#f8fafc", "accent": "#fbbf24", "card": "#1e293b"},
    "light": {"name": "בהיר", "bg": "#f8fafc", "fg": "#0f172a", "accent": "#2563eb", "card": "#e2e8f0"},
    "wine": {"name": "יין", "bg": "#3b0a1e", "fg": "#fff7ed", "accent": "#fdba74", "card": "#5b1630"},
    "forest": {"name": "יער", "bg": "#0b2e24", "fg": "#f0fdf4", "accent": "#86efac", "card": "#14463a"},
    "ocean": {"name": "ים", "bg": "#0c2d48", "fg": "#f0f9ff", "accent": "#7dd3fc", "card": "#14446b"},
    "cream": {"name": "קרם", "bg": "#fdf6e3", "fg": "#3b2f1e", "accent": "#b45309", "card": "#f3e6c4"},
}
DEFAULT_THEME = "night"

IMAGE_NAME = re.compile(r"^[0-9a-f]{16}\.(jpg|png)$")
MAX_ROWS = 40
MAX_IMAGES = 30
_LIMITS = {"text": 120, "textarea": 1500}


class TemplateError(ValueError):
    pass


def _nl2br(value) -> Markup:
    return Markup("<br>").join(escape(str(value or "")).splitlines())


class Library:
    def __init__(self, directory: Path = TEMPLATES_DIR):
        self.directory = Path(directory)
        self.env = Environment(
            loader=FileSystemLoader(str(self.directory)),
            autoescape=select_autoescape(default=True, default_for_string=True),
        )
        self.env.filters["nl2br"] = _nl2br
        self.templates: dict[str, dict] = {}
        for meta_path in sorted(self.directory.glob("*/template.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["id"] = meta_path.parent.name
            self.templates[meta["id"]] = meta

    def listing(self) -> list[dict]:
        return sorted(self.templates.values(), key=lambda t: t.get("order", 100))

    def get(self, template_id: str) -> dict:
        try:
            return self.templates[template_id]
        except KeyError:
            raise TemplateError("תבנית לא קיימת") from None

    # --- validation ------------------------------------------------------
    def clean(self, template_id: str, data) -> dict:
        """Coerce user input to exactly the template's fields. Raises TemplateError."""
        meta = self.get(template_id)
        if not isinstance(data, dict):
            raise TemplateError("נתונים לא תקינים")
        out: dict = {}
        for field in meta["fields"]:
            key, kind = field["key"], field["type"]
            raw = data.get(key, field.get("default"))
            out[key] = self._clean_field(field, kind, raw)
        theme = data.get("theme", DEFAULT_THEME)
        out["theme"] = theme if theme in THEMES else DEFAULT_THEME
        return out

    def _clean_field(self, field: dict, kind: str, raw):
        label = field.get("label", field["key"])
        if kind in ("text", "textarea"):
            text = "" if raw is None else str(raw).strip()
            limit = field.get("max", _LIMITS[kind])
            if len(text) > limit:
                raise TemplateError(f"{label}: ארוך מדי (עד {limit} תווים)")
            return text
        if kind == "number":
            try:
                num = int(raw)
            except (TypeError, ValueError):
                raise TemplateError(f"{label}: צריך מספר") from None
            return max(field.get("min", 0), min(field.get("max", 9999), num))
        if kind == "select":
            options = [o["value"] for o in field["options"]]
            return raw if raw in options else field.get("default", options[0])
        if kind == "image":
            if not raw:
                return ""
            if not isinstance(raw, str) or not IMAGE_NAME.match(raw):
                raise TemplateError(f"{label}: תמונה לא תקינה")
            return raw
        if kind == "images":
            items = raw or []
            if not isinstance(items, list) or any(not isinstance(i, str) or not IMAGE_NAME.match(i) for i in items):
                raise TemplateError(f"{label}: תמונות לא תקינות")
            return items[:MAX_IMAGES]
        if kind == "rows":
            rows = raw or []
            if not isinstance(rows, list):
                raise TemplateError(f"{label}: רשימה לא תקינה")
            cleaned = []
            for row in rows[:MAX_ROWS]:
                if not isinstance(row, dict):
                    raise TemplateError(f"{label}: שורה לא תקינה")
                item = {c["key"]: str(row.get(c["key"]) or "").strip()[:120] for c in field["columns"]}
                if any(item.values()):
                    cleaned.append(item)
            return cleaned
        raise TemplateError(f"סוג שדה לא מוכר: {kind}")

    def defaults(self, template_id: str) -> dict:
        return self.clean(template_id, {})

    # --- rendering -------------------------------------------------------
    def render(self, template_id: str, data: dict, context: dict) -> str:
        self.get(template_id)
        theme = THEMES.get(data.get("theme"), THEMES[DEFAULT_THEME])
        return self.env.get_template(f"{template_id}/template.html").render(d=data, t=theme, **context)
