from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests

from dramaNlearn import extractor
from dramaNlearn.models import Video


class DramaStreamAccessError(Exception):
    pass


@dataclass(frozen=True)
class PreparedDramaStream:
    source_path: Path
    resolved_master_url: str
    selected_variant_url: str


def _stream_headers(player_url: str) -> dict[str, str]:
    headers = dict(extractor.HEADERS)
    if player_url:
        headers["Referer"] = player_url
    return headers


def _fetch_text(url: str, *, player_url: str) -> str:
    try:
        response = requests.get(url, headers=_stream_headers(player_url), timeout=20)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise DramaStreamAccessError("드라마 스트림 응답 시간이 너무 길어 클립 추출을 준비하지 못했습니다.") from exc
    except requests.RequestException as exc:
        raise DramaStreamAccessError(f"드라마 스트림에 접근하지 못했습니다: {exc}") from exc

    text = response.text
    if not text.strip():
        raise DramaStreamAccessError("드라마 스트림 플레이리스트가 비어 있습니다.")
    return text


def _resolve_url(base_url: str, raw_url: str) -> str:
    return urljoin(base_url, (raw_url or "").strip())


def _rewrite_attribute_uris(line: str, *, base_url: str) -> str:
    return re.sub(
        r'URI="([^"]+)"',
        lambda match: f'URI="{_resolve_url(base_url, match.group(1))}"',
        line,
    )


def _pick_variant_playlist(master_manifest: str, *, master_url: str) -> str:
    lines = [line.strip() for line in master_manifest.splitlines()]
    best_url = ""
    best_bandwidth = -1

    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue

        bandwidth_match = re.search(r"BANDWIDTH=(\d+)", line)
        bandwidth = int(bandwidth_match.group(1)) if bandwidth_match else 0

        next_index = index + 1
        while next_index < len(lines):
            candidate = lines[next_index].strip()
            next_index += 1
            if not candidate or candidate.startswith("#"):
                continue
            candidate_url = _resolve_url(master_url, candidate)
            if bandwidth > best_bandwidth:
                best_bandwidth = bandwidth
                best_url = candidate_url
            break

    return best_url


def _rewrite_media_playlist(playlist_text: str, *, playlist_url: str) -> str:
    rewritten_lines: list[str] = []
    for raw_line in playlist_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            rewritten_lines.append("")
            continue
        if stripped.startswith("#"):
            rewritten_lines.append(_rewrite_attribute_uris(stripped, base_url=playlist_url))
            continue
        rewritten_lines.append(_resolve_url(playlist_url, stripped))
    return "\n".join(rewritten_lines) + "\n"


def _sync_video_stream_metadata(video: Video, info: dict, *, resolved_master_url: str) -> None:
    update_fields: list[str] = []

    if video.m3u8_url != resolved_master_url:
        video.m3u8_url = resolved_master_url
        update_fields.append("m3u8_url")

    thumbnail = info.get("thumbnail") or ""
    if thumbnail and video.thumbnail != thumbnail:
        video.thumbnail = thumbnail
        update_fields.append("thumbnail")

    duration = info.get("duration") or 0
    if duration and video.duration != duration:
        video.duration = duration
        update_fields.append("duration")

    subtitles = info.get("subtitles")
    if subtitles is not None:
        subtitle_json = json.dumps(subtitles, ensure_ascii=False)
        if video.subtitle_tracks != subtitle_json:
            video.subtitle_tracks = subtitle_json
            update_fields.append("subtitle_tracks")

    if update_fields:
        update_fields.append("updated_at")
        video.save(update_fields=update_fields)


def prepare_drama_extract_source(video: Video, output_dir: Path) -> PreparedDramaStream:
    if not video.player_url:
        raise DramaStreamAccessError("드라마 player URL이 없어 최신 스트림을 갱신할 수 없습니다.")

    try:
        info = extractor.get_m3u8_from_player(video.player_url)
    except requests.Timeout as exc:
        raise DramaStreamAccessError("드라마 플레이어 응답 시간이 너무 길어 최신 스트림을 갱신하지 못했습니다.") from exc
    except requests.RequestException as exc:
        raise DramaStreamAccessError(f"드라마 플레이어에 접근하지 못했습니다: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise DramaStreamAccessError(str(exc).strip() or "드라마 스트림 정보를 갱신하지 못했습니다.") from exc

    resolved_master_url = (info.get("m3u8_url") or video.m3u8_url or "").strip()
    if not resolved_master_url:
        raise DramaStreamAccessError("최신 드라마 m3u8 URL을 찾지 못했습니다.")

    _sync_video_stream_metadata(video, info, resolved_master_url=resolved_master_url)

    master_manifest = _fetch_text(resolved_master_url, player_url=video.player_url)
    selected_variant_url = _pick_variant_playlist(master_manifest, master_url=resolved_master_url) or resolved_master_url
    variant_manifest = _fetch_text(selected_variant_url, player_url=video.player_url)

    output_dir.mkdir(parents=True, exist_ok=True)
    local_playlist_path = output_dir / "drama-source.m3u8"
    local_playlist_path.write_text(
        _rewrite_media_playlist(variant_manifest, playlist_url=selected_variant_url),
        encoding="utf-8",
    )

    return PreparedDramaStream(
        source_path=local_playlist_path,
        resolved_master_url=resolved_master_url,
        selected_variant_url=selected_variant_url,
    )
