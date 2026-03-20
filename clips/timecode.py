import re

_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")


def parse_hhmmss(value: str) -> int:
    text = (value or "").strip()
    match = _TIME_RE.match(text)
    if not match:
        raise ValueError("Use hh:mm:ss format (e.g. 00:01:30).")

    hours, minutes, seconds = (int(part) for part in match.groups())
    if minutes >= 60 or seconds >= 60:
        raise ValueError("Minutes and seconds must be between 00 and 59.")

    return hours * 3600 + minutes * 60 + seconds


def format_hhmmss(total_seconds: int | None) -> str:
    if total_seconds is None:
        return "-"
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remain = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remain:02d}"
