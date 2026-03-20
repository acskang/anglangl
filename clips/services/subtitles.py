import re
from dataclasses import dataclass
from pathlib import Path

from clips.timecode import format_hhmmss


_SRT_TIME_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)
_VTT_TIME_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})"
)


class SubtitleParseError(ValueError):
    pass


@dataclass(frozen=True)
class SubtitleSegment:
    start_seconds: int
    end_seconds: int
    text: str


def _parse_srt_time(value: str) -> int:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    whole_seconds = float(seconds)
    return int((int(hours) * 3600) + (int(minutes) * 60) + whole_seconds)


def _parse_vtt_time(value: str) -> int:
    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int((int(minutes) * 60) + float(seconds))
    hours, minutes, seconds = parts
    return int((int(hours) * 3600) + (int(minutes) * 60) + float(seconds))


def _normalize_text(lines: list[str]) -> str:
    return " ".join(part.strip() for part in lines if part.strip()).strip()


def parse_srt(content: str) -> list[SubtitleSegment]:
    segments: list[SubtitleSegment] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [line.strip("\ufeff ") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if _SRT_TIME_RE.match(lines[0]):
            time_line = lines[0]
            text_lines = lines[1:]
        elif len(lines) >= 2 and _SRT_TIME_RE.match(lines[1]):
            time_line = lines[1]
            text_lines = lines[2:]
        else:
            continue
        match = _SRT_TIME_RE.match(time_line)
        if not match:
            continue
        text = _normalize_text(text_lines)
        if not text:
            continue
        start_seconds = _parse_srt_time(match.group("start"))
        end_seconds = _parse_srt_time(match.group("end"))
        if end_seconds <= start_seconds:
            continue
        segments.append(SubtitleSegment(start_seconds=start_seconds, end_seconds=end_seconds, text=text))
    if not segments:
        raise SubtitleParseError("No valid subtitle rows were found in the subtitle file.")
    return segments


def parse_vtt(content: str) -> list[SubtitleSegment]:
    segments: list[SubtitleSegment] = []
    blocks = [block for block in re.split(r"\n\s*\n", content.strip()) if block.strip()]
    for block in blocks:
        lines = [line.strip("\ufeff ") for line in block.splitlines() if line.strip()]
        if not lines or lines[0].upper() == "WEBVTT":
            continue
        if _VTT_TIME_RE.match(lines[0]):
            time_line = lines[0]
            text_lines = lines[1:]
        elif len(lines) >= 2 and _VTT_TIME_RE.match(lines[1]):
            time_line = lines[1]
            text_lines = lines[2:]
        else:
            continue
        match = _VTT_TIME_RE.match(time_line)
        if not match:
            continue
        text = _normalize_text(text_lines)
        if not text:
            continue
        start_seconds = _parse_vtt_time(match.group("start"))
        end_seconds = _parse_vtt_time(match.group("end"))
        if end_seconds <= start_seconds:
            continue
        segments.append(SubtitleSegment(start_seconds=start_seconds, end_seconds=end_seconds, text=text))
    if not segments:
        raise SubtitleParseError("No valid subtitle rows were found in the subtitle file.")
    return segments


def parse_subtitle_file(subtitle_path: Path) -> list[SubtitleSegment]:
    if not subtitle_path.exists():
        raise SubtitleParseError("Subtitle file does not exist.")

    content = subtitle_path.read_text(encoding="utf-8-sig", errors="replace")
    suffix = subtitle_path.suffix.lower()
    if suffix == ".srt":
        return parse_srt(content)
    if suffix == ".vtt":
        return parse_vtt(content)
    raise SubtitleParseError("Unsupported subtitle format. Use .srt or .vtt.")


def build_extraction_plan(segments: list[SubtitleSegment], range_start: int, range_end: int) -> list[dict]:
    plan_rows: list[dict] = []
    for index, segment in enumerate(segments):
        if segment.end_seconds <= range_start or segment.start_seconds >= range_end:
            continue
        clip_start = max(range_start, segment.start_seconds)
        clip_end = min(range_end, segment.end_seconds)
        if clip_end <= clip_start:
            continue
        plan_rows.append(
            {
                "row_id": index,
                "clip_start_time": clip_start,
                "clip_start_label": format_hhmmss(clip_start),
                "clip_end_time": clip_end,
                "clip_end_label": format_hhmmss(clip_end),
                "subtitle_text": segment.text,
                "status_note": "자막 구간 기준 자동 계획",
                "selected": True,
            }
        )
    return plan_rows
