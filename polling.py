"""School-day polling in Home Assistant's configured local time."""
from datetime import datetime, time, timedelta

from .const import (
    DEFAULT_AM_WINDOW, DEFAULT_PM_WINDOW, SCAN_INTERVAL_ACTIVE,
    SCAN_INTERVAL_IDLE, SCAN_INTERVAL_OFF, SCHOOL_DAYS,
)


def polling_interval(now: datetime, options: dict | None = None) -> int:
    """Poll promptly at window boundaries, including after an overnight pause."""
    options = options or {}
    windows = []
    for label, default in (("am", DEFAULT_AM_WINDOW), ("pm", DEFAULT_PM_WINDOW)):
        start = options.get(f"{label}_start", f"{default[0]:02}:{default[1]:02}")
        end = options.get(f"{label}_end", f"{default[2]:02}:{default[3]:02}")
        windows.append((time.fromisoformat(start), time.fromisoformat(end)))
    current = now.time().replace(tzinfo=None)
    school_day = now.weekday() in SCHOOL_DAYS
    if school_day and any(start <= current < end for start, end in windows):
        interval = SCAN_INTERVAL_ACTIVE
    elif school_day and time(6) <= current < time(19):
        interval = SCAN_INTERVAL_IDLE
    else:
        interval = SCAN_INTERVAL_OFF
    # A slow poll must never sleep through the beginning of an active window.
    for day_offset in (0, 1):
        date = now.date() + timedelta(days=day_offset)
        if date.weekday() not in SCHOOL_DAYS:
            continue
        for boundary in [time(6), time(19), *(v for window in windows for v in window)]:
            seconds = (datetime.combine(date, boundary, now.tzinfo) - now).total_seconds()
            if seconds > 0:
                interval = min(interval, max(1, int(seconds)))
    return interval
