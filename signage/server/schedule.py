"""When is a slide on screen?  schedule = None (always) or
{"days": [0..6] (0 = Sunday), "start": "HH:MM", "end": "HH:MM"}."""
from __future__ import annotations

import re
from datetime import datetime

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def clean(schedule) -> dict | None:
    """Validate user input; raises ValueError on bad shape."""
    if not schedule:
        return None
    if not isinstance(schedule, dict):
        raise ValueError("תזמון לא תקין")
    days = schedule.get("days") or list(range(7))
    if not isinstance(days, list) or any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days):
        raise ValueError("ימים לא תקינים")
    start = schedule.get("start") or "00:00"
    end = schedule.get("end") or "23:59"
    if not (isinstance(start, str) and isinstance(end, str) and _HHMM.match(start) and _HHMM.match(end)):
        raise ValueError("שעה לא תקינה")
    if start == end:
        raise ValueError("שעת התחלה וסיום זהות")
    return {"days": sorted(set(days)), "start": start, "end": end}


def is_active(schedule: dict | None, now: datetime) -> bool:
    if not schedule:
        return True
    day = (now.weekday() + 1) % 7  # Python Mon=0 -> ours Sun=0
    hhmm = f"{now.hour:02d}:{now.minute:02d}"
    start, end, days = schedule["start"], schedule["end"], schedule["days"]
    if start < end:
        return day in days and start <= hhmm < end
    # overnight window (e.g. 22:00–02:00): belongs to the day it started on
    return (day in days and hhmm >= start) or ((day - 1) % 7 in days and hhmm < end)
