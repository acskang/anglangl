from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


class InvalidYouTubeInput(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedYouTubeInput:
    youtube_video_id: str
    youtube_url: str


def _is_valid_video_id(value: str) -> bool:
    if len(value) != 11:
        return False
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    return all(ch in allowed for ch in value)


def _extract_from_url(value: str) -> str | None:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path

    if "youtube.com" in host:
        if path == "/watch":
            query = parse_qs(parsed.query)
            return (query.get("v") or [None])[0]
        if path.startswith("/shorts/"):
            return path.split("/shorts/", 1)[1].split("/")[0]
        if path.startswith("/embed/"):
            return path.split("/embed/", 1)[1].split("/")[0]
    if "youtu.be" in host:
        return path.lstrip("/").split("/")[0]
    return None


def normalize_youtube_input(value: str) -> NormalizedYouTubeInput:
    candidate = value.strip()

    if _is_valid_video_id(candidate):
        video_id = candidate
    else:
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        video_id = _extract_from_url(candidate)

    if not video_id or not _is_valid_video_id(video_id):
        raise InvalidYouTubeInput("Invalid YouTube URL or video ID.")

    return NormalizedYouTubeInput(
        youtube_video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
    )
