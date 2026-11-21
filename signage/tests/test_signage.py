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
    assert len(lib.templates) == 12
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
    assert client.get("/").status_code == 200 and client.get("/admin").status_code == 200
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
