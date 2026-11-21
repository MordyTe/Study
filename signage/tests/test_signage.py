import io
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server import schedule as sched
from server import zmanim
from server.app import create_app
from server.templates_lib import Library, TemplateError

FIXED_NOW = datetime(2026, 11, 18, 10, 30, tzinfo=zmanim.TZ)  # a Wednesday


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path, now=lambda: FIXED_NOW))


@pytest.fixture
def admin(client):
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200
    return client


def png_bytes(size=(64, 48), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


# ---------- schedule ----------
def at(day, hhmm):  # day: 15=Sun … 21=Sat (Nov 2026)
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 11, day, h, m, tzinfo=zmanim.TZ)


def test_schedule_always():
    assert sched.is_active(None, at(18, "03:00"))


def test_schedule_window_and_days():
    s = sched.clean({"days": [0, 3], "start": "08:00", "end": "12:00"})  # Sunday, Wednesday
    assert sched.is_active(s, at(15, "08:00"))
    assert sched.is_active(s, at(18, "11:59"))
    assert not sched.is_active(s, at(18, "12:00"))
    assert not sched.is_active(s, at(16, "09:00"))  # Monday


def test_schedule_overnight_belongs_to_start_day():
    s = sched.clean({"days": [4], "start": "22:00", "end": "02:00"})  # Thursday night
    assert sched.is_active(s, at(19, "23:00"))
    assert sched.is_active(s, at(20, "01:30"))      # Friday, after midnight
    assert not sched.is_active(s, at(20, "23:00"))  # Friday night is not listed
    assert not sched.is_active(s, at(19, "01:00"))  # Thursday before the window


@pytest.mark.parametrize("bad", [{"days": [7]}, {"start": "25:00"}, {"start": "08:00", "end": "08:00"}, "x", {"days": [True]}])
def test_schedule_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        sched.clean(bad)


# ---------- zmanim ----------
def minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


@pytest.mark.parametrize("day,sunrise,sunset", [
    (date(2026, 6, 21), "5:34", "19:47"),    # summer time (UTC+3)
    (date(2026, 12, 21), "6:34", "16:40"),   # winter time (UTC+2)
])
def test_jerusalem_sunrise_sunset(day, sunrise, sunset):
    z = {row["name"]: row["time"] for row in zmanim.zmanim(day, "ירושלים")}
    assert abs(minutes(z["הנץ החמה"]) - minutes(sunrise)) <= 4
    assert abs(minutes(z["שקיעה"]) - minutes(sunset)) <= 4


def test_zmanim_are_in_order():
    times = [minutes(r["time"]) for r in zmanim.zmanim(date(2026, 3, 10), "חיפה")]
    assert times == sorted(times) and len(times) == 8


def test_shabbat_picks_friday_and_saturday():
    wed = zmanim.shabbat(date(2026, 11, 18), "תל אביב")
    sat = zmanim.shabbat(date(2026, 11, 21), "תל אביב")
    assert wed == sat and wed["date"] == "21.11" and wed["parsha"] == "ויצא"
    assert minutes(wed["candles"]) < minutes(wed["havdalah"])
    sunset_fri = {r["name"]: r["time"] for r in zmanim.zmanim(date(2026, 11, 20), "תל אביב")}["שקיעה"]
    assert minutes(sunset_fri) - minutes(wed["candles"]) in (19, 20, 21)


def test_hebrew_date():
    assert zmanim.hebrew_date(date(2026, 11, 21)) == "י״א כסלו תשפ״ז"
    assert zmanim.day_name(date(2026, 11, 21)) == "שבת"
    assert zmanim.day_name(date(2026, 11, 22)) == "יום ראשון"


# ---------- templates ----------
def test_every_template_renders_with_defaults(admin):
    lib = admin.app.state.lib
    assert len(lib.templates) == 13
    for template_id in lib.templates:
        r = admin.post("/api/preview", json={"template": template_id, "data": {}})
        assert r.status_code == 200, template_id
        assert "<html" in r.text and 'dir="rtl"' in r.text


def test_clean_drops_unknown_and_limits():
    lib = Library()
    out = lib.clean("promo", {"title": "  שלום  ", "evil": "x", "theme": "nope"})
    assert out["title"] == "שלום" and "evil" not in out and out["theme"] == "night"
    with pytest.raises(TemplateError):
        lib.clean("promo", {"title": "א" * 51})
    with pytest.raises(TemplateError):
        lib.clean("promo", {"image": "../../etc/passwd"})
    with pytest.raises(TemplateError):
        lib.clean("nope", {})
    rows = lib.clean("menu", {"items": [{"name": "קפה", "price": "9", "x": "y"}, {"name": "", "price": ""}]})["items"]
    assert rows == [{"name": "קפה", "note": "", "price": "9"}]
    assert lib.clean("slideshow", {"seconds": 999})["seconds"] == 60


def test_user_text_is_escaped(admin):
    r = admin.post("/api/preview", json={"template": "text", "data": {"title": "<script>alert(1)</script>", "body": "a\n<b>"}})
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text and "a<br>&lt;b&gt;" in r.text


# ---------- auth ----------
def test_admin_api_needs_login(client):
    for method, url in [("get", "/api/slides"), ("get", "/api/templates"), ("get", "/api/images"), ("get", "/api/settings")]:
        assert getattr(client, method)(url).status_code == 401
    assert client.post("/api/slides", json={"template": "text"}).status_code == 401
    assert client.post("/api/images", files={"file": ("a.png", png_bytes(), "image/png")}).status_code == 401
    assert client.get("/api/playlist").status_code == 200  # the display itself is public


def test_pin_setup_login_and_lockout(client):
    assert client.post("/api/auth/setup", json={"pin": "12"}).status_code == 400
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200
    assert client.post("/api/auth/setup", json={"pin": "9999"}).status_code == 409  # cannot be reset by a stranger
    client.cookies.clear()
    assert client.get("/api/slides").status_code == 401
    assert client.post("/api/auth/login", json={"pin": "1234"}).status_code == 200
    assert client.get("/api/slides").status_code == 200
    client.cookies.clear()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"pin": "0000"}).status_code == 401
    assert client.post("/api/auth/login", json={"pin": "1234"}).status_code == 429


def test_change_pin(admin):
    assert admin.post("/api/auth/pin", json={"old": "0000", "new": "5678"}).status_code == 401
    assert admin.post("/api/auth/pin", json={"old": "1234", "new": "5678"}).status_code == 200
    admin.cookies.clear()
    assert admin.post("/api/auth/login", json={"pin": "1234"}).status_code == 401
    assert admin.post("/api/auth/login", json={"pin": "5678"}).status_code == 200


# ---------- slides, playlist ----------
def test_slide_lifecycle_and_playlist(admin):
    assert admin.get("/api/playlist").json()["slides"] == []
    v0 = admin.get("/api/playlist").json()["version"]
    a = admin.post("/api/slides", json={"template": "text", "data": {"title": "אחת"}, "duration": 2}).json()
    b = admin.post("/api/slides", json={"template": "promo", "data": {"title": "שתיים"}}).json()
    assert a["duration"] == 5 and a["template_name"] == "טקסט חופשי"  # duration clamped
    pl = admin.get("/api/playlist").json()
    assert [s["id"] for s in pl["slides"]] == [a["id"], b["id"]] and pl["version"] > v0

    assert admin.post("/api/slides/order", json={"ids": [b["id"], a["id"]]}).status_code == 200
    assert [s["id"] for s in admin.get("/api/playlist").json()["slides"]] == [b["id"], a["id"]]
    assert admin.post("/api/slides/order", json={"ids": [a["id"]]}).status_code == 400

    r = admin.put(f"/api/slides/{a['id']}", json={"data": {"title": "חדש"}, "duration": 20, "enabled": False})
    assert r.json()["data"]["title"] == "חדש" and r.json()["enabled"] is False
    assert [s["id"] for s in admin.get("/api/playlist").json()["slides"]] == [b["id"]]
    assert "חדש" in admin.get(f"/render/{a['id']}").text

    assert admin.delete(f"/api/slides/{b['id']}").status_code == 200
    assert admin.get(f"/render/{b['id']}").status_code == 404
    assert admin.get("/api/playlist").json()["slides"] == []


def test_playlist_respects_schedule(admin):
    morning = {"days": [3], "start": "08:00", "end": "12:00"}   # FIXED_NOW is Wednesday 10:30
    evening = {"days": [3], "start": "18:00", "end": "22:00"}
    a = admin.post("/api/slides", json={"template": "text", "schedule": morning}).json()
    b = admin.post("/api/slides", json={"template": "text", "schedule": evening}).json()
    assert a["active_now"] and not b["active_now"]
    assert [s["id"] for s in admin.get("/api/playlist").json()["slides"]] == [a["id"]]
    assert admin.post("/api/slides", json={"template": "text", "schedule": {"start": "9"}}).status_code == 400


def test_bad_slide_input(admin):
    assert admin.post("/api/slides", json={"template": "nope"}).status_code == 400
    assert admin.post("/api/slides", json={"template": "text", "data": {"title": "x" * 200}}).status_code == 400
    assert admin.put("/api/slides/999", json={}).status_code == 404


# ---------- images ----------
def test_image_upload_use_and_delete(admin):
    big = png_bytes(size=(4000, 3000))
    name = admin.post("/api/images", files={"file": ("photo.png", big, "image/png")}).json()["name"]
    assert name.endswith(".jpg") and admin.get("/api/images").json() == [name]
    saved = Image.open(admin.app.state.uploads / name)
    assert max(saved.size) == 2560

    slide = admin.post("/api/slides", json={"template": "image", "data": {"image": name}}).json()
    assert f"/uploads/{name}" in admin.get(f"/render/{slide['id']}").text
    assert admin.get(f"/uploads/{name}").status_code == 200

    assert admin.delete(f"/api/images/{name}").status_code == 200
    html = admin.get(f"/render/{slide['id']}").text          # slide survives a deleted image
    assert f"/uploads/{name}" not in html and "עוד לא נבחרה תמונה" in html
    assert admin.delete("/api/images/..%2Fsignage.db").status_code == 404


def test_upload_rejects_non_images(admin):
    r = admin.post("/api/images", files={"file": ("x.png", b"<script>not an image</script>", "image/png")})
    assert r.status_code == 400 and admin.get("/api/images").json() == []


def test_settings_and_context(admin):
    assert admin.put("/api/settings", json={"place": "קפה השכונה", "city": "לונדון"}).status_code == 400
    assert admin.put("/api/settings", json={"place": "קפה השכונה", "city": "ירושלים"}).status_code == 200
    html = admin.post("/api/preview", json={"template": "shabbat", "data": {}}).text
    assert "ירושלים" in html and "ויצא" in html and "קפה השכונה" in html
    html = admin.post("/api/preview", json={"template": "zmanim", "data": {}}).text
    assert "הנץ החמה" in html and "יום רביעי" in html


def test_pages_and_qr(client):
    assert client.get("/?display=1").status_code == 200 and client.get("/admin").status_code == 200
    r = client.get("/api/qr.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg")


# ---------- backgrounds ----------
def test_builtin_background_changes_the_look(admin):
    plain = admin.post("/api/preview", json={"template": "text", "data": {}}).text
    styled = admin.post("/api/preview", json={"template": "text", "data": {"background": "bg:dusk"}}).text
    assert "body{background:#0f172a" in plain
    assert "body{background:linear-gradient(160deg,#1e1b4b" in styled and "--accent:#fde68a" in styled


def test_every_builtin_background_renders_unescaped(admin):
    lib = admin.get("/api/templates").json()
    assert len(lib["backgrounds"]) == 12
    for bg in lib["backgrounds"]:
        html = admin.post("/api/preview", json={"template": "menu", "data": {"background": bg["id"]}}).text
        assert "body{background:" + bg["css"] in html, bg["id"]


def test_photo_background_and_fallback_when_deleted(admin):
    name = admin.post("/api/images", files={"file": ("p.png", png_bytes(), "image/png")}).json()["name"]
    slide = admin.post("/api/slides", json={"template": "text", "data": {"background": name}}).json()
    assert f"url(/uploads/{name}) center/cover" in admin.get(f"/render/{slide['id']}").text
    admin.delete(f"/api/images/{name}")
    html = admin.get(f"/render/{slide['id']}").text
    assert "/uploads/" not in html and "body{background:#0f172a" in html


@pytest.mark.parametrize("bad", ["bg:nope", "x.jpg", "url(http://evil)", "bg:dusk);}body{x", 5])
def test_bad_background_rejected(admin, bad):
    assert admin.post("/api/preview", json={"template": "text", "data": {"background": bad}}).status_code == 400


# ---------- Canva (against a fake Canva; the real service has not been exercised) ----------
import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx


class FakeCanva:
    def __init__(self):
        self.access, self.refresh, self.challenge, self.calls, self.polls = "at1", "rt1", None, [], 0
        self.fail_export = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if request.url.host == "export.canva.test":
            return httpx.Response(200, content=png_bytes(size=(1920, 1080)))
        if path == "/rest/v1/oauth/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if request.headers.get("authorization") != "Basic " + base64.b64encode(b"cid:shh").decode():
                return httpx.Response(401, json={"code": "invalid_client"})
            if form["grant_type"] == "authorization_code":
                digest = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if form["code"] != "good-code" or digest != self.challenge or "redirect_uri" not in form:
                    return httpx.Response(400, json={"code": "invalid_grant"})
            elif form.get("refresh_token") != self.refresh:
                return httpx.Response(400, json={"code": "invalid_grant"})
            n = int(self.access[2:]) + 1
            self.access, self.refresh = f"at{n}", f"rt{n}"       # refresh tokens rotate
            return httpx.Response(200, json={"access_token": self.access, "refresh_token": self.refresh,
                                             "token_type": "Bearer", "expires_in": 14400})
        if request.headers.get("authorization") != "Bearer " + self.access:
            return httpx.Response(401, json={"code": "invalid_access_token"})
        if path == "/rest/v1/designs":
            if request.url.params.get("continuation") == "page2":
                return httpx.Response(200, json={"items": [{"id": "D3", "title": "שלישי"}]})
            return httpx.Response(200, json={"continuation": "page2", "items": [
                {"id": "D1", "title": "תפריט חורף", "thumbnail": {"url": "https://thumb.canva.test/1.png"}}, {"id": "D2"}]})
        if path == "/rest/v1/exports" and request.method == "POST":
            return httpx.Response(200, json={"job": {"id": "J1", "status": "in_progress"}})
        if path == "/rest/v1/exports/J1":
            self.polls += 1
            if self.polls < 2:
                return httpx.Response(200, json={"job": {"id": "J1", "status": "in_progress"}})
            if self.fail_export:
                return httpx.Response(200, json={"job": {"id": "J1", "status": "failed", "error": {"code": "internal_failure"}}})
            return httpx.Response(200, json={"job": {"id": "J1", "status": "success", "urls": [
                "https://export.canva.test/p1.png", "https://export.canva.test/p2.png"]}})
        return httpx.Response(404)


@pytest.fixture
def canva(tmp_path):
    fake = FakeCanva()
    client = TestClient(create_app(tmp_path, now=lambda: FIXED_NOW, canva_transport=httpx.MockTransport(fake)), follow_redirects=False)
    client.post("/api/auth/setup", json={"pin": "1234"})
    return client, fake


def connect(client, fake):
    assert client.put("/api/canva/config", json={"client_id": "cid", "client_secret": "shh"}).status_code == 200
    r = client.get("/api/canva/login")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert r.headers["location"].startswith("https://www.canva.com/api/oauth/authorize?")
    assert q["code_challenge_method"] == ["s256"] and q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8080/api/canva/callback"]
    assert q["scope"] == ["design:meta:read design:content:read"]
    fake.challenge = q["code_challenge"][0]
    return q["state"][0]


def test_canva_needs_login_and_config(client, canva):
    for url in ("/api/canva/status", "/api/canva/designs", "/api/canva/login"):
        assert client.get(url).status_code == 401
    c, _ = canva
    assert c.get("/api/canva/status").json()["configured"] is False
    assert c.get("/api/canva/login").status_code == 502
    assert c.get("/api/canva/designs").status_code == 502
    assert c.put("/api/canva/config", json={"client_id": "cid"}).status_code == 400


def test_canva_connect_list_and_import(canva):
    c, fake = canva
    state = connect(c, fake)
    assert c.get("/api/canva/callback?code=good-code&state=wrong").headers["location"] == "/admin#canva=failed"
    assert c.get("/api/canva/status").json()["connected"] is False
    state = connect(c, fake)                      # a failed attempt burns the state; start over
    assert c.get(f"/api/canva/callback?code=good-code&state={state}").headers["location"] == "/admin#canva=ok"
    assert c.get(f"/api/canva/callback?code=good-code&state={state}").headers["location"] == "/admin#canva=failed"  # no replay
    st = c.get("/api/canva/status").json()
    assert st["connected"] and "client_secret" not in st

    first = c.get("/api/canva/designs").json()
    assert first["items"][0] == {"id": "D1", "title": "תפריט חורף", "thumbnail": "https://thumb.canva.test/1.png"}
    assert first["items"][1] == {"id": "D2", "title": "ללא שם", "thumbnail": ""} and first["continuation"] == "page2"
    assert c.get("/api/canva/designs?continuation=page2").json() == {"items": [{"id": "D3", "title": "שלישי", "thumbnail": ""}], "continuation": ""}

    names = c.post("/api/canva/import", json={"design_id": "D1"}).json()["names"]
    assert len(names) == 2 and sorted(c.get("/api/images").json()) == sorted(names)
    assert Image.open(c.app.state.uploads / names[0]).size == (1920, 1080)
    slide = c.post("/api/slides", json={"template": "image", "data": {"image": names[0]}}).json()
    assert f"/uploads/{names[0]}" in c.get(f"/render/{slide['id']}").text


def test_canva_token_refresh_on_401(canva):
    c, fake = canva
    c.get(f"/api/canva/callback?code=good-code&state={connect(c, fake)}")
    c.app.state.store.set("canva_access_token", "stale")     # our copy is stale; refresh token still valid
    assert c.get("/api/canva/designs").status_code == 200
    assert "POST /rest/v1/oauth/token" in fake.calls[-2:]
    assert c.app.state.store.get("canva_refresh_token") == fake.refresh

    fake.refresh = "rotated-away"                             # refresh token no longer valid -> disconnected
    c.app.state.store.set("canva_access_token", "stale")
    r = c.get("/api/canva/designs")
    assert r.status_code == 502 and "מחדש" in r.json()["detail"]
    assert c.get("/api/canva/status").json()["connected"] is False


def test_canva_export_failure_and_denied_consent(canva):
    c, fake = canva
    assert c.get("/api/canva/callback?error=access_denied").headers["location"] == "/admin#canva=denied"
    c.get(f"/api/canva/callback?code=good-code&state={connect(c, fake)}")
    fake.fail_export = True
    r = c.post("/api/canva/import", json={"design_id": "D1"})
    assert r.status_code == 502 and c.get("/api/images").json() == []
    assert c.post("/api/canva/import", json={}).status_code == 400
    assert c.post("/api/canva/disconnect").status_code == 200
    assert c.get("/api/canva/status").json()["connected"] is False


# ---------- video, display ----------
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


def test_video_upload_slide_and_delete(admin):
    assert admin.post("/api/videos", files={"file": ("a.mp4", b"MZ not a video at all", "video/mp4")}).status_code == 400
    assert admin.post("/api/videos", files={"file": ("a.mp4", png_bytes(), "video/mp4")}).status_code == 400
    mp4 = admin.post("/api/videos", files={"file": ("clip.mov", MP4, "video/quicktime")}).json()["name"]
    webm = admin.post("/api/videos", files={"file": ("clip", WEBM, "video/webm")}).json()["name"]
    assert mp4.endswith(".mp4") and webm.endswith(".webm")
    assert sorted(admin.get("/api/videos").json()) == sorted([mp4, webm])
    assert admin.get("/api/images").json() == []                      # videos are not listed as images
    assert (admin.app.state.uploads / mp4).read_bytes() == MP4
    assert not list(admin.app.state.uploads.glob("*.part"))

    slide = admin.post("/api/slides", json={"template": "video", "data": {"video": mp4, "sound": "on"}}).json()
    html = admin.get(f"/render/{slide['id']}").text
    assert f'src="/uploads/{mp4}"' in html and " muted" not in html.split("<video")[1].split(">")[0]
    assert admin.get("/api/playlist").json()["slides"] == [{"id": slide["id"], "duration": 12, "wait_end": True, "has_sound": True}]
    assert admin.post("/api/slides", json={"template": "video", "data": {"video": "../x.mp4"}}).status_code == 400
    assert admin.post("/api/slides", json={"template": "image", "data": {"image": mp4}}).status_code == 400

    assert admin.delete(f"/api/videos/{mp4}").status_code == 200
    assert "עוד לא נבחר סרטון" in admin.get(f"/render/{slide['id']}").text
    assert admin.delete(f"/api/videos/{mp4}").status_code == 404


def test_video_needs_login_and_size_limit(client, admin, monkeypatch):
    client.cookies.clear()
    assert client.post("/api/videos", files={"file": ("a.mp4", MP4, "video/mp4")}).status_code == 401
    client.post("/api/auth/login", json={"pin": "1234"})
    import server.app as app_module
    monkeypatch.setattr(app_module, "MAX_VIDEO", 1024)
    big = MP4 + b"\x00" * 4096
    assert client.post("/api/videos", files={"file": ("a.mp4", big, "video/mp4")}).status_code == 413
    assert client.get("/api/videos").json() == [] and not list(client.app.state.uploads.iterdir())


def test_display_report(admin):
    assert admin.get("/api/settings").json()["display"] is None
    assert admin.post("/api/display", json={"width": 3840, "height": 2160}).status_code == 200
    d = admin.get("/api/settings").json()["display"]
    assert (d["width"], d["height"], d["live"]) == (3840, 2160, True)
    admin.post("/api/display", json={"width": 5, "height": 5})        # nonsense is ignored
    assert admin.get("/api/settings").json()["display"]["width"] == 3840
    assert admin.post("/api/display", json={"width": "x"}).status_code == 400


# ---------- music, expiry, copy ----------
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x0a" + b"\x00" * 64
OGG = b"OggS" + b"\x00" * 64


def test_music_playlist(admin):
    assert admin.get("/api/playlist").json()["music"] == {"mode": "off"}
    assert admin.put("/api/music", json={"mode": "playlist"}).status_code == 400          # nothing to play yet
    assert admin.post("/api/music/tracks", files={"file": ("x.mp3", png_bytes(), "audio/mpeg")}).status_code == 400
    a = admin.post("/api/music/tracks", files={"file": ("שיר ראשון.mp3", MP3, "audio/mpeg")}).json()
    b = admin.post("/api/music/tracks", files={"file": ("../../second.ogg", OGG, "audio/ogg")}).json()
    assert a["title"] == "שיר ראשון" and a["name"].endswith(".mp3") and b["title"] == "second" and b["name"].endswith(".ogg")
    assert admin.get("/api/images").json() == [] and admin.get("/api/videos").json() == []

    m = admin.put("/api/music", json={"mode": "playlist", "volume": 250, "shuffle": False}).json()
    assert m["volume"] == 100 and [t["title"] for t in m["tracks"]] == ["שיר ראשון", "second"]
    assert admin.get("/api/playlist").json()["music"] == {"mode": "playlist", "volume": 100, "shuffle": False, "tracks": [a["name"], b["name"]]}
    assert admin.get(f"/uploads/{a['name']}").status_code == 200

    assert admin.delete(f"/api/music/tracks/{a['name']}").status_code == 200
    assert admin.get("/api/playlist").json()["music"]["tracks"] == [b["name"]]
    assert admin.delete(f"/api/music/tracks/{b['name']}").status_code == 200
    assert admin.get("/api/playlist").json()["music"] == {"mode": "off"}                # last song gone -> silence, not an error
    assert admin.delete(f"/api/music/tracks/{b['name']}").status_code == 404
    assert not list(admin.app.state.uploads.iterdir())


def test_music_radio_and_validation(admin):
    assert admin.put("/api/music", json={"mode": "radio"}).status_code == 400
    for bad in ("javascript:alert(1)", "file:///etc/passwd", "http://a b", "ftp://x"):
        assert admin.put("/api/music", json={"mode": "radio", "radio_url": bad}).status_code == 400, bad
    assert admin.put("/api/music", json={"mode": "disco"}).status_code == 400
    r = admin.put("/api/music", json={"mode": "radio", "radio_url": "https://stream.example.org/live.mp3", "radio_name": "תחנה", "volume": 30})
    assert r.status_code == 200
    assert admin.get("/api/playlist").json()["music"] == {"mode": "radio", "volume": 30, "url": "https://stream.example.org/live.mp3"}
    admin.cookies.clear()
    assert admin.get("/api/music").status_code == 401 and admin.put("/api/music", json={"mode": "off"}).status_code == 401
    assert admin.post("/api/music/tracks", files={"file": ("a.mp3", MP3, "audio/mpeg")}).status_code == 401


def test_slide_expiry_and_copy(admin):
    # FIXED_NOW is 2026-11-18
    live = admin.post("/api/slides", json={"template": "promo", "data": {"title": "עד היום"}, "expires": "2026-11-18"}).json()
    gone = admin.post("/api/slides", json={"template": "promo", "data": {"title": "אתמול"}, "expires": "2026-11-17"}).json()
    assert live["active_now"] and not live["expired"] and gone["expired"] and not gone["active_now"]
    assert [s["id"] for s in admin.get("/api/playlist").json()["slides"]] == [live["id"]]
    assert admin.post("/api/slides", json={"template": "promo", "expires": "18/11/2026"}).status_code == 400
    back = admin.put(f"/api/slides/{gone['id']}", json={"data": gone["data"], "expires": None}).json()
    assert back["expires"] is None and back["active_now"]

    copy = admin.post(f"/api/slides/{live['id']}/copy").json()
    assert copy["id"] != live["id"] and copy["data"] == live["data"] and copy["expires"] == "2026-11-18"
    assert [s["id"] for s in admin.get("/api/slides").json()][-1] == copy["id"]
    assert admin.post("/api/slides/999/copy").status_code == 404


def test_old_database_gains_expiry_column(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "signage.db")
    db.execute("CREATE TABLE slides (id INTEGER PRIMARY KEY AUTOINCREMENT, template TEXT NOT NULL, data TEXT NOT NULL, "
               "duration INTEGER NOT NULL DEFAULT 12, enabled INTEGER NOT NULL DEFAULT 1, schedule TEXT, position INTEGER NOT NULL DEFAULT 0)")
    db.execute("INSERT INTO slides(template,data) VALUES('text','{\"title\":\"ישן\"}')")
    db.commit(); db.close()
    c = TestClient(create_app(tmp_path, now=lambda: FIXED_NOW))
    c.post("/api/auth/setup", json={"pin": "1234"})
    old = c.get("/api/slides").json()
    assert old[0]["data"]["title"] == "ישן" and old[0]["expires"] is None and old[0]["active_now"]


# ---------- out of the box: network, address on screen, first-run wizard ----------
def test_screen_waits_for_network_then_shows_address(client):
    client.app.state.lan_ip = lambda: None                       # cable not plugged in yet
    p = client.get("/api/playlist").json()
    assert p["network"] is False and p["admin_url"] == "" and p["setup_done"] is False
    assert client.get("/api/qr.svg").status_code == 404
    client.app.state.lan_ip = lambda: "192.168.1.57"             # router handed out an address
    p = client.get("/api/playlist").json()
    assert p["network"] is True and p["admin_url"] == "http://192.168.1.57:8080"
    assert client.get("/api/qr.svg").status_code == 200


def test_port_80_gives_a_bare_address(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNAGE_PORT", "80")
    c = TestClient(create_app(tmp_path))
    c.app.state.lan_ip = lambda: "192.168.1.57"
    assert c.get("/api/playlist").json()["admin_url"] == "http://192.168.1.57"


def test_typing_the_address_on_a_phone_leads_to_admin(client):
    r = client.get("/", follow_redirects=False)                  # not the device itself
    assert r.status_code == 302 and r.headers["location"] == "/admin"
    local = TestClient(client.app, client=("127.0.0.1", 5000))
    assert local.get("/", follow_redirects=False).status_code == 200   # the kiosk browser gets the display


@pytest.mark.parametrize("category,count", [("business", 4), ("lobby", 4), ("synagogue", 5), ("general", 2)])
def test_first_run_wizard_builds_a_working_screen(client, category, count):
    assert client.post("/api/setup", json={"place": "x", "city": "חיפה", "category": category}).status_code == 401
    client.post("/api/auth/setup", json={"pin": "1234"})
    state = client.get("/api/auth/state").json()
    assert state["setup_done"] is False and "חיפה" in state["cities"]
    assert client.post("/api/setup", json={"place": "בית הקפה", "city": "חיפה", "category": "nope"}).status_code == 400
    assert client.post("/api/setup", json={"place": "בית הקפה", "city": "פריז", "category": category}).status_code == 400
    r = client.post("/api/setup", json={"place": "בית הקפה", "city": "חיפה", "category": category})
    assert r.json() == {"ok": True, "slides": count}
    pl = client.get("/api/playlist").json()
    assert pl["setup_done"] is True and len(pl["slides"]) == count
    for s in pl["slides"]:
        assert client.get(f"/render/{s['id']}").status_code == 200
    first = client.get(f"/render/{pl['slides'][0]['id']}").text
    assert "ברוכים הבאים" in first and "בית הקפה" in first
    assert client.get("/api/settings").json()["city"] == "חיפה"
    # running it again must not pile up a second set
    assert client.post("/api/setup", json={"place": "בית הקפה", "city": "חיפה", "category": category}).json()["slides"] == count


def test_existing_screens_skip_the_wizard(admin):
    admin.post("/api/slides", json={"template": "text"})
    assert admin.get("/api/auth/state").json()["setup_done"] is True


# ---------- several screens ----------
def test_one_screen_by_default(admin):
    assert [s["name"] for s in admin.get("/api/screens").json()] == ["מסך ראשי"]
    pl = admin.get("/api/playlist").json()
    assert pl["screen"] == {"id": 1, "name": "מסך ראשי", "count": 1} and pl["identify"] is False
    assert admin.post("/api/slides", json={"template": "text", "screens": [2]}).status_code == 400   # no such screen


def test_slides_go_to_chosen_screens(admin):
    assert admin.put("/api/screens", json={"names": []}).status_code == 400
    assert admin.put("/api/screens", json={"names": ["x"] * 9}).status_code == 400
    names = [s["name"] for s in admin.put("/api/screens", json={"names": ["קופה", "", "חלון ראווה"]}).json()]
    assert names == ["קופה", "מסך 2", "חלון ראווה"]
    everywhere = admin.post("/api/slides", json={"template": "text"}).json()
    only2 = admin.post("/api/slides", json={"template": "text", "screens": [2]}).json()
    two = admin.post("/api/slides", json={"template": "text", "screens": [3, 1, 3]}).json()
    alls = admin.post("/api/slides", json={"template": "text", "screens": [1, 2, 3]}).json()
    assert everywhere["screens"] is None and only2["screens"] == [2] and two["screens"] == [1, 3] and alls["screens"] is None
    for bad in ([0], [4], ["1"], [True], "1"):
        assert admin.post("/api/slides", json={"template": "text", "screens": bad}).status_code == 400, bad

    def ids(screen):
        return [s["id"] for s in admin.get(f"/api/playlist?screen={screen}").json()["slides"]]
    assert ids(1) == [everywhere["id"], two["id"], alls["id"]]
    assert ids(2) == [everywhere["id"], only2["id"], alls["id"]]
    assert ids(3) == [everywhere["id"], two["id"], alls["id"]]
    assert ids("junk") == ids(1) and ids(99) == ids(1)                      # unknown screen behaves as the main one
    assert admin.get("/api/playlist?screen=2").json()["screen"] == {"id": 2, "name": "מסך 2", "count": 3}
    assert admin.post(f"/api/slides/{only2['id']}/copy").json()["screens"] == [2]

    # removing screens: slides that pointed only at a removed screen fall back to every screen
    admin.put("/api/screens", json={"names": ["קופה"]})
    by_id = {s["id"]: s["screens"] for s in admin.get("/api/slides").json()}
    assert by_id[only2["id"]] is None and by_id[two["id"]] == [1]


def test_music_only_on_main_screen_and_identify(admin):
    admin.put("/api/screens", json={"names": ["א", "ב"]})
    admin.put("/api/music", json={"mode": "radio", "radio_url": "https://stream.example.org/a.mp3"})
    assert admin.get("/api/playlist?screen=1").json()["music"]["mode"] == "radio"
    assert admin.get("/api/playlist?screen=2").json()["music"] == {"mode": "off"}
    assert admin.post("/api/screens/identify").json()["ok"]
    assert admin.get("/api/playlist?screen=2").json()["identify"] is True
    admin.cookies.clear()
    assert admin.post("/api/screens/identify").status_code == 401 and admin.put("/api/screens", json={"names": ["x"]}).status_code == 401


def test_each_screen_reports_its_own_size(admin):
    admin.put("/api/screens", json={"names": ["א", "ב"]})
    admin.post("/api/display", json={"screen": 1, "width": 1920, "height": 1080})
    admin.post("/api/display", json={"screen": 2, "width": 3840, "height": 2160})
    a, b = admin.get("/api/screens").json()
    assert (a["width"], a["live"], a["url"].endswith("/?display&screen=1")) == (1920, True, True)
    assert (b["width"], b["height"], b["live"]) == (3840, 2160, True)
    assert admin.get("/api/settings").json()["display"]["width"] == 1920


def test_template_preview_thumbnails_and_bundled_font(client, admin):
    assert "התפריט שלנו" in admin.get("/api/templates/menu/preview").text
    assert admin.get("/api/templates/nope/preview").status_code == 404
    assert admin.get("/static/fonts/heebo.css").status_code == 200
    assert admin.get("/static/fonts/heebo-hebrew-wght-normal.woff2").status_code == 200
    assert "/static/fonts/heebo.css" in admin.get("/api/templates/text/preview").text
    client.cookies.clear()
    assert client.get("/api/templates/menu/preview").status_code == 401
