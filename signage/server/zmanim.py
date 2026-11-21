"""Sun-based times (zmanim, Shabbat) computed locally — no network needed.

Uses the classic "Almanac for Computers" sunrise equation. Accuracy is about
1–2 minutes at sea level; times are a convenience and should be checked against
a printed luach before relying on them for halachic purposes.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pyluach import dates, parshios

TZ = ZoneInfo("Asia/Jerusalem")

# name -> (lat, lon, candle-lighting minutes before sunset)
CITIES: dict[str, tuple[float, float, int]] = {
    "ירושלים": (31.778, 35.235, 40),
    "תל אביב": (32.085, 34.782, 20),
    "חיפה": (32.794, 34.990, 30),
    "באר שבע": (31.252, 34.791, 20),
    "אילת": (29.558, 34.952, 20),
    "נתניה": (32.332, 34.860, 20),
    "אשדוד": (31.804, 34.655, 20),
    "אשקלון": (31.669, 34.571, 20),
    "פתח תקווה": (32.087, 34.887, 40),
    "ראשון לציון": (31.973, 34.789, 20),
    "רחובות": (31.894, 34.811, 20),
    "בני ברק": (32.084, 34.834, 20),
    "מודיעין": (31.898, 35.010, 20),
    "בית שמש": (31.747, 34.988, 20),
    "טבריה": (32.796, 35.530, 20),
    "צפת": (32.965, 35.496, 20),
    "קריית שמונה": (33.208, 35.570, 20),
    "עפולה": (32.607, 35.289, 20),
    "כפר סבא": (32.175, 34.907, 20),
    "הרצליה": (32.166, 34.844, 20),
}
DEFAULT_CITY = "תל אביב"

SUN_ZENITH = 90.833   # sunrise / sunset (refraction + solar radius)
TZEIT_ZENITH = 98.5   # sun 8.5 degrees below the horizon


def _sun_utc_hours(day: date, lat: float, lon: float, zenith: float, rising: bool) -> float:
    n = day.timetuple().tm_yday
    lng_hour = lon / 15.0
    t = n + ((6 if rising else 18) - lng_hour) / 24.0
    m = 0.9856 * t - 3.289
    l = (m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360
    ra += (math.floor(l / 90) - math.floor(ra / 90)) * 90
    ra /= 15.0
    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(lat))) / (
        cos_dec * math.cos(math.radians(lat))
    )
    cos_h = max(-1.0, min(1.0, cos_h))
    h = math.degrees(math.acos(cos_h))
    h = (360 - h if rising else h) / 15.0
    return (h + ra - 0.06571 * t - 6.622 - lng_hour) % 24


def sun_time(day: date, city: str, zenith: float, rising: bool) -> datetime:
    lat, lon, _ = CITIES.get(city, CITIES[DEFAULT_CITY])
    hours = _sun_utc_hours(day, lat, lon, zenith, rising)
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return (base + timedelta(hours=hours)).astimezone(TZ)


def _fmt(dt: datetime) -> str:
    dt = dt + timedelta(seconds=30)  # round to the nearest minute
    return f"{dt.hour}:{dt.minute:02d}"


def zmanim(day: date, city: str) -> list[dict[str, str]]:
    """Daily times, GRA method (day = sunrise to sunset, divided in 12)."""
    sunrise = sun_time(day, city, SUN_ZENITH, True)
    sunset = sun_time(day, city, SUN_ZENITH, False)
    hour = (sunset - sunrise) / 12
    rows = [
        ("הנץ החמה", sunrise),
        ("סוף זמן קריאת שמע", sunrise + 3 * hour),
        ("סוף זמן תפילה", sunrise + 4 * hour),
        ("חצות היום", sunrise + 6 * hour),
        ("מנחה גדולה", sunrise + 6.5 * hour),
        ("פלג המנחה", sunrise + 10.75 * hour),
        ("שקיעה", sunset),
        ("צאת הכוכבים", sun_time(day, city, TZEIT_ZENITH, False)),
    ]
    return [{"name": name, "time": _fmt(dt)} for name, dt in rows]


def shabbat(day: date, city: str) -> dict[str, str]:
    """Times for the current/upcoming Shabbat (on Saturday: the one in progress)."""
    wd = day.weekday()  # Mon=0 … Fri=4, Sat=5, Sun=6
    friday = day - timedelta(days=1) if wd == 5 else day + timedelta(days=(4 - wd) % 7)
    saturday = friday + timedelta(days=1)
    minutes = CITIES.get(city, CITIES[DEFAULT_CITY])[2]
    candles = sun_time(friday, city, SUN_ZENITH, False) - timedelta(minutes=minutes)
    havdalah = sun_time(saturday, city, TZEIT_ZENITH, False)
    parsha = parshios.getparsha_string(dates.HebrewDate.from_pydate(saturday), israel=True, hebrew=True)
    return {
        "candles": _fmt(candles),
        "havdalah": _fmt(havdalah),
        "parsha": parsha or "",
        "date": f"{saturday.day}.{saturday.month}",
    }


def hebrew_date(day: date) -> str:
    return dates.HebrewDate.from_pydate(day).hebrew_date_string()


HEB_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def day_name(day: date) -> str:
    name = HEB_DAYS[day.weekday()]
    return name if name == "שבת" else f"יום {name}"
