import re

_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})(?::(\d{1,3}))?$")


def quantize_tenths(value: float | int | None) -> float:
    return round(max(0.0, float(value or 0.0)) + 1e-9, 1)


def parse_hhmmss(value: str) -> float:
    text = (value or "").strip()
    match = _TIME_RE.match(text)
    if not match:
        raise ValueError("Use hh:mm:ss:s format with 0.1-second steps (e.g. 00:01:30:5).")

    hours, minutes, seconds = (int(part) for part in match.groups()[:3])
    fraction_raw = match.group(4) or "0"
    if minutes >= 60 or seconds >= 60:
        raise ValueError("Minutes and seconds must be between 00 and 59.")
    if len(fraction_raw) == 1:
        tenths = int(fraction_raw)
    elif len(fraction_raw) == 3:
        milliseconds = int(fraction_raw)
        if milliseconds >= 1000:
            raise ValueError("Tenths must be between 0 and 9.")
        if milliseconds % 100 != 0:
            raise ValueError("Tenths must use 0.1-second steps (0 to 9).")
        tenths = milliseconds // 100
    else:
        raise ValueError("Use hh:mm:ss:s format with a single tenth digit.")

    total_seconds = hours * 3600 + minutes * 60 + seconds + (tenths / 10)
    return quantize_tenths(total_seconds)


def format_hhmmss(total_seconds: float | int | None) -> str:
    if total_seconds is None:
        return "-"
    total_tenths = int(round(max(0.0, float(total_seconds)) * 10))
    total_whole_seconds, tenths = divmod(total_tenths, 10)
    hours = total_whole_seconds // 3600
    minutes = (total_whole_seconds % 3600) // 60
    remain = total_whole_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remain:02d}:{tenths}"


def format_hhmmss_tenths(total_seconds: float | int | None) -> str:
    if total_seconds is None:
        return "-"
    total_tenths = int(round(max(0.0, float(total_seconds)) * 10))
    total_whole_seconds, tenths = divmod(total_tenths, 10)
    hours = total_whole_seconds // 3600
    minutes = (total_whole_seconds % 3600) // 60
    remain = total_whole_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remain:02d}.{tenths}s"
