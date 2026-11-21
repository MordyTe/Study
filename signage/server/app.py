"""Digital signage server: display page (/), admin (/admin), JSON API."""
from __future__ import annotations

import hashlib
import hmac
import io
import os
import secrets
import socket
import time
from datetime import datetime
from pathlib import Path

import segno
from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from . import schedule as sched
from . import zmanim
from .canva import Canva, CanvaError
from .store import Store
from .templates_lib import BACKGROUNDS, BG_PREFIX, CATEGORIES, IMAGE_NAME, THEMES, VIDEO_NAME, Library, TemplateError

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "sg_session"
SESSION_SECONDS = 30 * 24 * 3600
MAX_UPLOAD = 25 * 1024 * 1024
MAX_VIDEO = 300 * 1024 * 1024
MAX_SIDE = 2560
MAX_FAILS, LOCK_SECONDS = 5, 60


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def create_app(data_dir: str | Path | None = None, now=lambda: datetime.now(zmanim.TZ), canva_transport=None) -> FastAPI:
    data = Path(data_dir or os.environ.get("SIGNAGE_DATA") or Path(__file__).resolve().parent.parent / "data")
    uploads = data / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    store = Store(data / "signage.db")
    lib = Library()
    port = int(os.environ.get("SIGNAGE_PORT", "8080"))
    fails = {"count": 0, "locked_until": 0.0}
    display: dict = {}
    # Canva only accepts redirect URLs registered in advance; a LAN address cannot be one.
    canva = Canva(store, os.environ.get("SIGNAGE_CANVA_REDIRECT") or f"http://127.0.0.1:{port}/api/canva/callback",
                  transport=canva_transport, sleep=(lambda s: None) if canva_transport else time.sleep)

    app = FastAPI(title="Signage", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.lib, app.state.uploads = store, lib, uploads
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.mount("/uploads", StaticFiles(directory=uploads), name="uploads")

    # --- auth -------------------------------------------------------------
    def pin_is_set() -> bool:
        return bool(store.get("pin_hash"))

    def logged_in(request: Request) -> bool:
        token = request.cookies.get(COOKIE)
        return bool(token) and store.has_session(token, time.time() - SESSION_SECONDS)

    def admin(request: Request) -> None:
        if not logged_in(request):
            raise HTTPException(401, "נדרשת כניסה")

    def _start_session(response: Response) -> None:
        token = secrets.token_urlsafe(32)
        store.add_session(token, time.time())
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax")

    def _valid_pin(pin) -> str:
        if not isinstance(pin, str) or not pin.isdigit() or not 4 <= len(pin) <= 8:
            raise HTTPException(400, "הקוד צריך להיות 4 עד 8 ספרות")
        return pin

    def _save_pin(pin: str) -> None:
        salt = secrets.token_hex(16)
        store.set("pin_salt", salt)
        store.set("pin_hash", _hash_pin(pin, salt))

    def _check_pin(pin) -> bool:
        if time.time() < fails["locked_until"]:
            raise HTTPException(429, "יותר מדי ניסיונות. נסו שוב בעוד דקה")
        ok = isinstance(pin, str) and hmac.compare_digest(
            _hash_pin(pin, store.get("pin_salt")), store.get("pin_hash")
        )
        if ok:
            fails["count"] = 0
        else:
            fails["count"] += 1
            if fails["count"] >= MAX_FAILS:
                fails.update(count=0, locked_until=time.time() + LOCK_SECONDS)
        return ok

    @app.get("/api/auth/state")
    def auth_state(request: Request):
        return {"pin_set": pin_is_set(), "logged_in": logged_in(request)}

    @app.post("/api/auth/setup")
    def auth_setup(response: Response, body: dict = Body(...)):
        if pin_is_set():
            raise HTTPException(409, "כבר הוגדר קוד")
        _save_pin(_valid_pin(body.get("pin")))
        _start_session(response)
        return {"ok": True}

    @app.post("/api/auth/login")
    def auth_login(response: Response, body: dict = Body(...)):
        if not pin_is_set():
            raise HTTPException(409, "עוד לא הוגדר קוד")
        if not _check_pin(body.get("pin")):
            raise HTTPException(401, "קוד שגוי")
        _start_session(response)
        return {"ok": True}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, response: Response):
        store.drop_sessions(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.post("/api/auth/pin", dependencies=[Depends(admin)])
    def auth_change(response: Response, body: dict = Body(...)):
        if not _check_pin(body.get("old")):
            raise HTTPException(401, "הקוד הנוכחי שגוי")
        _save_pin(_valid_pin(body.get("new")))
        store.drop_sessions()
        _start_session(response)
        return {"ok": True}

    # --- settings ---------------------------------------------------------
    def settings() -> dict:
        city = store.get("city", zmanim.DEFAULT_CITY)
        return {"place": store.get("place", ""), "city": city if city in zmanim.CITIES else zmanim.DEFAULT_CITY}

    @app.get("/api/settings", dependencies=[Depends(admin)])
    def get_settings():
        shown = {**display, "live": time.time() - display["seen"] < 30} if display else None
        return {**settings(), "cities": list(zmanim.CITIES), "admin_url": admin_url(), "display": shown}

    @app.put("/api/settings", dependencies=[Depends(admin)])
    def put_settings(body: dict = Body(...)):
        place = str(body.get("place") or "").strip()
        if len(place) > 60:
            raise HTTPException(400, "שם המקום ארוך מדי")
        if body.get("city") not in zmanim.CITIES:
            raise HTTPException(400, "עיר לא מוכרת")
        store.set("place", place)
        store.set("city", body["city"])
        store.bump()
        return settings()

    # --- rendering --------------------------------------------------------
    def context() -> dict:
        s, moment = settings(), now()
        today = moment.date()
        return {
            "place": s["place"],
            "city": s["city"],
            "zmanim": zmanim.zmanim(today, s["city"]),
            "shabbat": zmanim.shabbat(today, s["city"]),
            "hebrew_date": zmanim.hebrew_date(today),
            "day_name": zmanim.day_name(today),
        }

    def render(template_id: str, data: dict) -> str:
        data = dict(data)
        for field in lib.get(template_id)["fields"]:  # drop images that were deleted since
            key = field["key"]
            if field["type"] in ("image", "video") and data.get(key) and not (uploads / data[key]).is_file():
                data[key] = ""
            if field["type"] == "images":
                data[key] = [i for i in data.get(key, []) if (uploads / i).is_file()]
        background = data.get("background") or ""
        if background and not background.startswith(BG_PREFIX) and not (uploads / background).is_file():
            data["background"] = ""
        return lib.render(template_id, data, context())

    @app.get("/render/{slide_id}", response_class=HTMLResponse)
    def render_slide(slide_id: int):
        slide = store.slide(slide_id)
        if not slide:
            raise HTTPException(404, "אין שקופית כזאת")
        return HTMLResponse(render(slide["template"], slide["data"]), headers={"Cache-Control": "no-store"})

    @app.post("/api/preview", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def preview(body: dict = Body(...)):
        try:
            template_id = str(body.get("template"))
            return render(template_id, lib.clean(template_id, body.get("data") or {}))
        except TemplateError as exc:
            raise HTTPException(400, str(exc)) from None

    # --- templates & slides -----------------------------------------------
    @app.get("/api/templates", dependencies=[Depends(admin)])
    def templates():
        items = [{**t, "defaults": lib.defaults(t["id"])} for t in lib.listing()]
        themes = [{"id": k, **v} for k, v in THEMES.items()]
        backgrounds = [{"id": BG_PREFIX + k, "name": v["name"], "css": v["css"]} for k, v in BACKGROUNDS.items()]
        return {"categories": CATEGORIES, "templates": items, "themes": themes, "backgrounds": backgrounds}

    def _slide_input(template_id: str, body: dict) -> tuple[dict, int, bool, dict | None]:
        try:
            clean = lib.clean(template_id, body.get("data") or {})
            schedule = sched.clean(body.get("schedule"))
        except (TemplateError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None
        try:
            duration = max(5, min(600, int(body.get("duration", 12))))
        except (TypeError, ValueError):
            raise HTTPException(400, "משך הצגה לא תקין") from None
        return clean, duration, bool(body.get("enabled", True)), schedule

    def _with_name(slide: dict) -> dict:
        meta = lib.templates.get(slide["template"], {})
        return {**slide, "template_name": meta.get("name", slide["template"]),
                "active_now": slide["enabled"] and sched.is_active(slide["schedule"], now())}

    @app.get("/api/slides", dependencies=[Depends(admin)])
    def list_slides():
        return [_with_name(s) for s in store.slides()]

    @app.post("/api/slides", dependencies=[Depends(admin)])
    def create_slide(body: dict = Body(...)):
        template_id = str(body.get("template"))
        if template_id not in lib.templates:
            raise HTTPException(400, "תבנית לא קיימת")
        new_id = store.add_slide(template_id, *_slide_input(template_id, body))
        return _with_name(store.slide(new_id))

    @app.put("/api/slides/{slide_id}", dependencies=[Depends(admin)])
    def update_slide(slide_id: int, body: dict = Body(...)):
        slide = store.slide(slide_id)
        if not slide:
            raise HTTPException(404, "אין שקופית כזאת")
        store.update_slide(slide_id, *_slide_input(slide["template"], body))
        return _with_name(store.slide(slide_id))

    @app.delete("/api/slides/{slide_id}", dependencies=[Depends(admin)])
    def delete_slide(slide_id: int):
        if not store.slide(slide_id):
            raise HTTPException(404, "אין שקופית כזאת")
        store.delete_slide(slide_id)
        return {"ok": True}

    @app.post("/api/slides/order", dependencies=[Depends(admin)])
    def order_slides(body: dict = Body(...)):
        ids = body.get("ids")
        existing = {s["id"] for s in store.slides()}
        if not isinstance(ids, list) or set(ids) != existing or len(ids) != len(existing):
            raise HTTPException(400, "רשימת סדר לא תקינה")
        store.reorder(ids)
        return {"ok": True}

    # --- images -----------------------------------------------------------
    @app.get("/api/images", dependencies=[Depends(admin)])
    def list_images():
        files = sorted(uploads.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.name for p in files if IMAGE_NAME.match(p.name)]

    @app.post("/api/images", dependencies=[Depends(admin)])
    async def upload_image(file: UploadFile = File(...)):
        raw = await file.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "התמונה גדולה מדי (עד 25MB)")
        return {"name": save_image(raw)}

    def save_image(raw: bytes) -> str:
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
            img = ImageOps.exif_transpose(img)  # phone photos: apply rotation
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise HTTPException(400, "הקובץ אינו תמונה שאפשר לקרוא") from None
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        # re-encode: drops metadata (location) and anything that is not pixel data
        if img.mode in ("RGBA", "LA", "P"):
            name, img = secrets.token_hex(8) + ".png", img.convert("RGBA")
            img.save(uploads / name, "PNG", optimize=True)
        else:
            name = secrets.token_hex(8) + ".jpg"
            img.convert("RGB").save(uploads / name, "JPEG", quality=88)
        return name

    @app.delete("/api/images/{name}", dependencies=[Depends(admin)])
    def delete_image(name: str):
        if not IMAGE_NAME.match(name) or not (uploads / name).is_file():
            raise HTTPException(404, "אין תמונה כזאת")
        (uploads / name).unlink()
        store.bump()
        return {"ok": True}

    # --- videos -----------------------------------------------------------
    @app.get("/api/videos", dependencies=[Depends(admin)])
    def list_videos():
        files = sorted(uploads.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.name for p in files if VIDEO_NAME.match(p.name)]

    @app.post("/api/videos", dependencies=[Depends(admin)])
    async def upload_video(file: UploadFile = File(...)):
        head = await file.read(16)
        if head[4:8] == b"ftyp":
            ext = ".mp4"
        elif head[:4] == b"\x1a\x45\xdf\xa3":
            ext = ".webm"
        else:
            raise HTTPException(400, "אפשר להעלות רק סרטוני MP4 או WebM")
        name = secrets.token_hex(8) + ext
        partial, size = uploads / (name + ".part"), len(head)
        try:
            with partial.open("wb") as out:   # streamed to disk: videos do not fit in memory on a Pi
                out.write(head)
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_VIDEO:
                        raise HTTPException(413, "הסרטון גדול מדי (עד 300MB)")
                    out.write(chunk)
            partial.rename(uploads / name)
        finally:
            partial.unlink(missing_ok=True)
        return {"name": name}

    @app.delete("/api/videos/{name}", dependencies=[Depends(admin)])
    def delete_video(name: str):
        if not VIDEO_NAME.match(name) or not (uploads / name).is_file():
            raise HTTPException(404, "אין סרטון כזה")
        (uploads / name).unlink()
        store.bump()
        return {"ok": True}

    # --- Canva ------------------------------------------------------------
    def canva_call(fn, *args):
        try:
            return fn(*args)
        except CanvaError as exc:
            raise HTTPException(502, str(exc)) from None

    @app.get("/api/canva/status", dependencies=[Depends(admin)])
    def canva_status():
        return {"configured": canva.configured(), "connected": canva.connected(),
                "client_id": store.get("canva_client_id"), "redirect_uri": canva.redirect_uri}

    @app.put("/api/canva/config", dependencies=[Depends(admin)])
    def canva_config(body: dict = Body(...)):
        client_id, secret = str(body.get("client_id") or "").strip(), str(body.get("client_secret") or "").strip()
        if not client_id or not secret or len(client_id) > 200 or len(secret) > 400:
            raise HTTPException(400, "צריך למלא גם מזהה וגם סוד")
        canva.configure(client_id, secret)
        return {"ok": True}

    @app.get("/api/canva/login", dependencies=[Depends(admin)])
    def canva_login():
        return RedirectResponse(canva_call(canva.login_url), status_code=302)

    @app.get("/api/canva/callback")
    def canva_callback(code: str = "", state: str = "", error: str = ""):
        # no session needed: the unguessable `state` proves this answers a login the admin started
        if error or not code:
            return RedirectResponse("/admin#canva=denied", status_code=302)
        try:
            canva.finish_login(code, state)
        except CanvaError:
            return RedirectResponse("/admin#canva=failed", status_code=302)
        return RedirectResponse("/admin#canva=ok", status_code=302)

    @app.post("/api/canva/disconnect", dependencies=[Depends(admin)])
    def canva_disconnect():
        canva.disconnect()
        return {"ok": True}

    @app.get("/api/canva/designs", dependencies=[Depends(admin)])
    def canva_designs(continuation: str = "", query: str = ""):
        return canva_call(canva.designs, continuation[:2000], query[:100])

    @app.post("/api/canva/import", dependencies=[Depends(admin)])
    def canva_import(body: dict = Body(...)):
        design_id = str(body.get("design_id") or "")
        if not design_id or len(design_id) > 100:
            raise HTTPException(400, "עיצוב לא תקין")
        return {"names": [save_image(page) for page in canva_call(canva.export_png, design_id)]}

    # --- display ------------------------------------------------------------
    def admin_url() -> str:
        return f"http://{lan_ip()}:{port}/admin"

    @app.get("/api/playlist")
    def playlist():
        moment = now()
        active = [
            {"id": s["id"], "duration": s["duration"], "wait_end": bool(lib.templates.get(s["template"], {}).get("wait_end"))}
            for s in store.slides()
            if s["enabled"] and sched.is_active(s["schedule"], moment) and s["template"] in lib.templates
        ]
        return {"version": store.version(), "slides": active, "admin_url": admin_url()}

    @app.post("/api/display")
    def report_display(body: dict = Body(...)):
        """The display page reports the resolution the browser actually got from the screen."""
        try:
            w, h = int(body.get("width")), int(body.get("height"))
        except (TypeError, ValueError):
            raise HTTPException(400, "bad size") from None
        if 100 <= w <= 20000 and 100 <= h <= 20000:
            display.update(width=w, height=h, seen=time.time())
        return {"ok": True}

    @app.get("/api/qr.svg")
    def qr():
        buf = io.BytesIO()
        segno.make(admin_url(), error="m").save(buf, kind="svg", scale=10, border=2, dark="#0f172a", light="#ffffff")
        return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    @app.get("/", include_in_schema=False)
    def player_page():
        return FileResponse(STATIC / "player.html", headers={"Cache-Control": "no-store"})

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-store"})

    return app

