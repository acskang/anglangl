"""
send2video.com URL 에서 m3u8 스트리밍 URL 을 추출하는 모듈.

흐름:
  1. send2video 페이지 -> iframe URL (xzxcdn.com/e/...)
  2. iframe 페이지 -> PackerJS eval() 난독화 코드
  3. PackerJS 디코딩 -> jwplayer setup -> m3u8 URL / subtitle track
"""

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

LANGUAGE_CODE_MAP = {
    "eng": "en",
    "english": "en",
    "ara": "ar",
    "arabic": "ar",
    "cat": "ca",
    "cze": "cs",
    "czech": "cs",
    "dan": "da",
    "danish": "da",
    "ger": "de",
    "german": "de",
    "gre": "el",
    "spa": "es",
    "spanish": "es",
    "baq": "eu",
    "fin": "fi",
    "fil": "fil",
    "fre": "fr",
    "french": "fr",
    "glg": "gl",
    "heb": "he",
    "hrv": "hr",
    "croatian": "hr",
    "hun": "hu",
    "ind": "id",
    "indonesian": "id",
    "ita": "it",
    "italian": "it",
    "jpn": "ja",
    "japanese": "ja",
    "kor": "ko",
    "korean": "ko",
    "may": "ms",
    "malay": "ms",
    "nob": "no",
    "dut": "nl",
    "pol": "pl",
    "polish": "pl",
    "por": "pt",
    "portuguese": "pt",
    "rum": "ro",
    "romanian": "ro",
    "rus": "ru",
    "russian": "ru",
    "swe": "sv",
    "sweden": "sv",
    "tha": "th",
    "thai": "th",
    "tur": "tr",
    "turkish": "tr",
    "ukr": "uk",
    "ukrainian": "uk",
    "vie": "vi",
    "vietnamese": "vi",
    "chi": "zh",
    "chinese": "zh",
}


# ── PackerJS 디코더 ──────────────────────────────────────────
def decode_packer(packed: str) -> str | None:
    m = re.search(
        r"}\('([\s\S]+?)',\s*(\d+),\s*(\d+),\s*'([\s\S]+?)'\.split",
        packed
    )
    if not m:
        return None

    p_str = m.group(1)
    a_val = int(m.group(2))
    c_val = int(m.group(3))
    k_vals = m.group(4).split("|")

    def to_base(num, base):
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        if num == 0:
            return "0"
        s = ""
        while num:
            s = chars[num % base] + s
            num //= base
        return s

    result = p_str
    for i in range(c_val - 1, -1, -1):
        key = to_base(i, a_val)
        val = k_vals[i] if i < len(k_vals) and k_vals[i].strip() else key
        result = re.sub(r'\b' + re.escape(key) + r'\b', val, result)

    return result


# ── Step 1: send2video 페이지 -> player iframe URL ──────────
def get_player_iframe_url(send2video_url: str) -> str:
    resp = requests.get(send2video_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 알려진 플레이어 도메인 우선
    PLAYER_DOMAINS = ["xzxcdn.com", "streamtape.com", "mixdrop.co", "upstream.to"]

    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        for domain in PLAYER_DOMAINS:
            if domain in src:
                return src

    # 첫 번째 외부 iframe fallback
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if src.startswith("http") and "send2video.com" not in src:
            return src

    raise ValueError("플레이어 iframe을 찾을 수 없습니다.")


# ── Step 2: player 페이지 -> PackerJS 디코딩 -> m3u8 URL ────
def get_m3u8_from_player(player_url: str) -> dict:
    headers = {**HEADERS, "Referer": "https://send2video.com/"}
    resp = requests.get(player_url, headers=headers, timeout=15)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    result = {
        "m3u8_url": "",
        "thumbnail": "",
        "duration": 0.0,
        "decoded": "",
        "subtitles": [],
    }

    # PackerJS 찾기
    packed_code = None
    for script in soup.find_all("script"):
        content = script.string or ""
        if content.strip().startswith("eval(function(p,a,c,k,e,d)"):
            packed_code = content.strip()
            break

    if packed_code:
        decoded = decode_packer(packed_code)
        result["decoded"] = decoded or ""
        source = decoded or html
    else:
        source = html

    # m3u8 패턴 추출
    m3u8_patterns = [
        r"(https?://[^\s'\"\\<>]+\.m3u8[^\s'\"\\<>]*)",
        r"\"hls\d*\"\s*:\s*\"(https?://[^'\"]+)\"",
        r"'hls\d*'\s*:\s*'(https?://[^'\"]+)'",
        r"\"file\"\s*:\s*\"(https?://[^'\"]+\.m3u8[^'\"]*)\"",
        r"'file'\s*:\s*'(https?://[^'\"]+\.m3u8[^'\"]*)'",
        # 상대 경로 /stream/...
        r"\"file\"\s*:\s*\"(/stream/[^'\"]+)\"",
    ]

    found_urls = []
    for pattern in m3u8_patterns:
        for m in re.findall(pattern, source):
            if m not in found_urls:
                found_urls.append(m)

    # 상대경로 -> 절대경로
    abs_urls = []
    for u in found_urls:
        if u.startswith("/"):
            abs_urls.append(urljoin(player_url, u))
        else:
            abs_urls.append(u)

    # hls2 > hls3 > hls4 순서 우선순위 (hls2가 토큰 포함 직접 URL)
    if abs_urls:
        result["m3u8_url"] = abs_urls[0]

    result["subtitles"] = extract_subtitle_tracks(source, player_url)

    # 썸네일
    thumb_m = re.search(r"image\s*:\s*['\"](https?://[^'\"]+)['\"]", source)
    if thumb_m:
        result["thumbnail"] = thumb_m.group(1)

    # 재생시간
    dur_m = re.search(r"duration\s*:\s*['\"]([\d.]+)['\"]", source)
    if dur_m:
        try:
            result["duration"] = float(dur_m.group(1))
        except ValueError:
            pass

    if not result["m3u8_url"]:
        raise ValueError("m3u8 URL을 찾을 수 없습니다. 사이트 구조가 변경되었을 수 있습니다.")

    return result


def normalize_subtitle_url(url: str, player_url: str) -> str:
    url = (url or "").strip().strip('"').strip("'")
    if not url:
        return ""
    return urljoin(player_url, url)


def clean_subtitle_label(label: str, fallback_index: int) -> str:
    label = (label or "").strip().strip('"').strip("'")
    return label or "Subtitle %d" % fallback_index


def infer_srclang(label: str, src: str) -> str:
    label_key = (label or "").strip().lower()
    if label_key in LANGUAGE_CODE_MAP:
        return LANGUAGE_CODE_MAP[label_key]

    src_match = re.search(r"_([a-z]{3})(?:\.[a-z0-9]+|\?)", src.lower())
    if src_match:
        return LANGUAGE_CODE_MAP.get(src_match.group(1), src_match.group(1)[:2])

    return ""


def extract_subtitle_tracks(source: str, player_url: str) -> list[dict]:
    tracks = []
    seen = set()

    object_pattern = re.compile(r"\{[^{}]{0,600}?(?:file|src)\s*:\s*['\"]([^'\"]+\.(?:vtt|srt)(?:\?[^'\"]*)?)['\"][^{}]{0,600}?\}")
    label_pattern = re.compile(r"label\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
    srclang_pattern = re.compile(r"srclang\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
    kind_pattern = re.compile(r"kind\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
    default_pattern = re.compile(r"default\s*:\s*(?:['\"])?(true|false)(?:['\"])?", re.IGNORECASE)

    for match in object_pattern.finditer(source):
        chunk = match.group(0)
        src = normalize_subtitle_url(match.group(1), player_url)
        if not src or src in seen:
            continue
        label_match = label_pattern.search(chunk)
        lang_match = srclang_pattern.search(chunk)
        kind_match = kind_pattern.search(chunk)
        default_match = default_pattern.search(chunk)
        tracks.append({
            "src": src,
            "label": clean_subtitle_label(label_match.group(1) if label_match else lang_match.group(1) if lang_match else "", len(tracks) + 1),
            "srclang": infer_srclang((lang_match.group(1) if lang_match else label_match.group(1) if label_match else ""), src),
            "kind": "subtitles" if (kind_match.group(1) if kind_match else "").strip().lower() in {"captions", "subtitles", ""} else (kind_match.group(1) if kind_match else "subtitles").strip(),
            "default": bool(default_match and default_match.group(1).lower() == "true"),
        })
        seen.add(src)

    json_like_patterns = [
        re.compile(r'"tracks"\s*:\s*(\[[\s\S]{0,4000}?\])', re.IGNORECASE),
        re.compile(r'"captions"\s*:\s*(\[[\s\S]{0,4000}?\])', re.IGNORECASE),
        re.compile(r'"subtitles"\s*:\s*(\[[\s\S]{0,4000}?\])', re.IGNORECASE),
    ]
    for pattern in json_like_patterns:
        match = pattern.search(source)
        if not match:
            continue
        raw = match.group(1)
        normalized = re.sub(r"(\w+)\s*:", r'"\1":', raw)
        normalized = normalized.replace("'", '"')
        try:
            items = json.loads(normalized)
        except Exception:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            src = normalize_subtitle_url(item.get("file") or item.get("src") or item.get("url") or "", player_url)
            if not src or src in seen or not re.search(r"\.(vtt|srt)(?:\?|$)", src, re.IGNORECASE):
                continue
            tracks.append({
                "src": src,
                "label": clean_subtitle_label(item.get("label") or item.get("lang") or item.get("srclang") or "", len(tracks) + 1),
                "srclang": infer_srclang(item.get("srclang") or item.get("lang") or item.get("label") or "", src),
                "kind": "subtitles" if str(item.get("kind") or "subtitles").strip().lower() in {"captions", "subtitles", ""} else str(item.get("kind")).strip(),
                "default": bool(item.get("default")),
            })
            seen.add(src)

    for match in re.finditer(r"(https?://[^'\"\s<>]+\.(?:vtt|srt)(?:\?[^'\"\s<>]*)?)", source, re.IGNORECASE):
        src = normalize_subtitle_url(match.group(1), player_url)
        if src and src not in seen:
            tracks.append({
                "src": src,
                "label": clean_subtitle_label("", len(tracks) + 1),
                "srclang": infer_srclang("", src),
                "kind": "subtitles",
                "default": False,
            })
            seen.add(src)

    return tracks


# ── 메인 진입점 ──────────────────────────────────────────────
def extract(send2video_url: str) -> dict:
    """
    send2video URL 을 받아 모든 정보를 추출해서 반환.

    Returns:
        {
            "player_url": str,
            "m3u8_url":   str,
            "thumbnail":  str,
            "duration":   float,
        }
    """
    player_url = get_player_iframe_url(send2video_url)
    info = get_m3u8_from_player(player_url)
    info["player_url"] = player_url
    return info
