"""Slide templates: each is templates/<id>/template.json (fields) + template.html (Jinja).

Adding a template = adding a folder; no Python changes needed.
Field types: text, textarea, number, select, image, images, video, rows.
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

# Built-in backgrounds. All of them are plain CSS written for this project (gradients and
# patterns), so there are no image files and no third-party rights involved.
# Each one is a complete look: it brings its own text, accent and card colours.
BACKGROUNDS = {
    "dusk": {"name": "שקיעה", "css": "linear-gradient(160deg,#1e1b4b 0%,#7c2d92 55%,#f97316 125%)",
             "fg": "#ffffff", "accent": "#fde68a", "card": "rgba(0,0,0,.28)"},
    "deep-sea": {"name": "מעמקים", "css": "radial-gradient(120% 90% at 80% 10%,#0ea5e9 0%,#0c4a6e 45%,#082f49 100%)",
                 "fg": "#f0f9ff", "accent": "#fde047", "card": "rgba(0,0,0,.25)"},
    "emerald": {"name": "אזמרגד", "css": "linear-gradient(150deg,#064e3b,#047857 60%,#34d399 135%)",
                "fg": "#f0fdf4", "accent": "#fef08a", "card": "rgba(0,0,0,.25)"},
    "ember": {"name": "גחלים", "css": "radial-gradient(110% 100% at 15% 90%,#f59e0b 0%,#b91c1c 45%,#450a0a 100%)",
              "fg": "#fff7ed", "accent": "#fde68a", "card": "rgba(0,0,0,.3)"},
    "royal": {"name": "מלכותי", "css": "linear-gradient(135deg,#1e3a8a,#312e81 60%,#581c87)",
              "fg": "#ffffff", "accent": "#fcd34d", "card": "rgba(0,0,0,.28)"},
    "bokeh": {"name": "אורות", "css": "radial-gradient(22vh 22vh at 18% 28%,rgba(244,114,182,.45),transparent 70%),"
              "radial-gradient(30vh 30vh at 78% 22%,rgba(96,165,250,.4),transparent 70%),"
              "radial-gradient(26vh 26vh at 62% 80%,rgba(250,204,21,.3),transparent 70%),"
              "radial-gradient(20vh 20vh at 30% 78%,rgba(52,211,153,.3),transparent 70%),#1a1033",
              "fg": "#ffffff", "accent": "#fde68a", "card": "rgba(255,255,255,.1)"},
    "grid": {"name": "רשת", "css": "linear-gradient(rgba(255,255,255,.07) 1px,transparent 1px) 0 0/6vh 6vh,"
             "linear-gradient(90deg,rgba(255,255,255,.07) 1px,transparent 1px) 0 0/6vh 6vh,#0f172a",
             "fg": "#f8fafc", "accent": "#38bdf8", "card": "rgba(255,255,255,.08)"},
    "carbon": {"name": "פחם", "css": "repeating-linear-gradient(45deg,#18181b 0 2vh,#202024 2vh 4vh)",
               "fg": "#fafafa", "accent": "#fb923c", "card": "rgba(255,255,255,.08)"},
    "paper": {"name": "נייר", "css": "radial-gradient(#d9cba6 .18vh,transparent .2vh) 0 0/3vh 3vh,#faf3e0",
              "fg": "#3b2f1e", "accent": "#b45309", "card": "rgba(120,90,40,.12)"},
    "sky": {"name": "שמיים", "css": "linear-gradient(180deg,#bae6fd,#f0f9ff 75%)",
            "fg": "#0c4a6e", "accent": "#c2410c", "card": "rgba(255,255,255,.6)"},
    "blush": {"name": "סומק", "css": "linear-gradient(140deg,#fce7f3,#fde68a)",
              "fg": "#4a1d34", "accent": "#be185d", "card": "rgba(255,255,255,.55)"},
    "mint": {"name": "מנטה", "css": "linear-gradient(140deg,#d1fae5,#e0f2fe)",
             "fg": "#064e3b", "accent": "#0f766e", "card": "rgba(255,255,255,.6)"},
}
BG_PREFIX = "bg:"

IMAGE_NAME = re.compile(r"^[0-9a-f]{16}\.(jpg|png)$")
VIDEO_NAME = re.compile(r"^[0-9a-f]{16}\.(mp4|webm)$")
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
        out["background"] = self._clean_background(data.get("background"))
        return out

    @staticmethod
    def _clean_background(raw) -> str:
        """'' = plain theme colour, 'bg:<id>' = built-in background, or an uploaded image name."""
        if not raw:
            return ""
        if isinstance(raw, str) and (
            (raw.startswith(BG_PREFIX) and raw[len(BG_PREFIX):] in BACKGROUNDS) or IMAGE_NAME.match(raw)
        ):
            return raw
        raise TemplateError("רקע לא תקין")

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
        if kind == "video":
            if not raw:
                return ""
            if not isinstance(raw, str) or not VIDEO_NAME.match(raw):
                raise TemplateError(f"{label}: סרטון לא תקין")
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
        theme = dict(THEMES.get(data.get("theme"), THEMES[DEFAULT_THEME]))
        background = data.get("background") or ""
        theme["paint"] = theme["bg"]
        if background.startswith(BG_PREFIX):
            look = BACKGROUNDS[background[len(BG_PREFIX):]]
            theme.update(fg=look["fg"], accent=look["accent"], card=look["card"], paint=Markup(look["css"]))
        elif background:  # an uploaded photo, darkened so text stays readable (name is validated)
            theme.update(fg="#ffffff", accent="#fde68a", card="rgba(0,0,0,.42)", paint=Markup(
                f"linear-gradient(rgba(0,0,0,.55),rgba(0,0,0,.55)),url(/uploads/{background}) center/cover no-repeat"))
        return self.env.get_template(f"{template_id}/template.html").render(d=data, t=theme, **context)
