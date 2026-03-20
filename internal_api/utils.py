from typing import Optional

from django.http import HttpRequest


def parse_int_param(request: HttpRequest, key: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = request.GET.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, value))


def parse_bool_param(request: HttpRequest, key: str, default: bool = False) -> bool:
    raw = request.GET.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def safe_text(value: Optional[str]) -> str:
    return (value or "").strip()
