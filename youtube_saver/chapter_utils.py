import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


class ChapterExtractionError(Exception):
    """Raised when yt-dlp metadata fetch fails."""


class ChapterDownloadError(Exception):
    """Raised when a chapter download fails."""


@dataclass
class ChapterMeta:
    idx: int
    start: float
    end: float
    title: str

    @property
    def start_hms(self) -> str:
        return sec_to_hms(self.start)

    @property
    def end_hms(self) -> str:
        return sec_to_hms(self.end)


def _run(cmd: List[str]) -> Tuple[int, str, str]:
    process = subprocess.run(cmd, text=True, capture_output=True)
    return process.returncode, process.stdout, process.stderr


def ensure_yt_dlp() -> None:
    code, _, err = _run(["yt-dlp", "--version"])
    if code != 0:
        raise ChapterExtractionError("yt-dlp 실행에 실패했습니다. PATH를 확인하세요.\n" + err.strip())


def fetch_info_json(url: str) -> dict:
    cmd = ["yt-dlp", "--dump-single-json", url]
    code, out, err = _run(cmd)
    if code != 0:
        raise ChapterExtractionError(
            "yt-dlp로 메타데이터를 가져오지 못했습니다.\n" + (err.strip() or "알 수 없는 오류")
        )
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:  # noqa: PERF203
        raise ChapterExtractionError("yt-dlp 출력이 JSON 형식이 아닙니다.") from exc


def parse_chapters(info: dict) -> List[ChapterMeta]:
    raw = info.get("chapters") or []
    chapters: List[ChapterMeta] = []
    for i, ch in enumerate(raw, start=1):
        start = float(ch.get("start_time", 0.0))
        end = ch.get("end_time")
        if end is None:
            continue
        end = float(end)
        title = str(ch.get("title") or "").strip() or f"Chapter {i}"
        chapters.append(ChapterMeta(idx=i, start=start, end=end, title=title))
    return chapters


def sec_to_hms(sec: float) -> str:
    seconds = int(round(sec))
    hh = seconds // 3600
    mm = (seconds % 3600) // 60
    ss = seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def sanitize_filename(text: str) -> str:
    safe = re.sub(r"[\\/:\*\?\"<>\|]+", "_", text)
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe[:120] if len(safe) > 120 else safe


def fetch_chapters(url: str) -> Tuple[List[ChapterMeta], dict]:
    ensure_yt_dlp()
    info = fetch_info_json(url)
    return parse_chapters(info), info


def download_chapter_section(
    url: str,
    chapter: ChapterMeta,
    outdir: Path,
    extra_args: Optional[List[str]] = None,
) -> Optional[Path]:
    outdir.mkdir(parents=True, exist_ok=True)

    start_hms = chapter.start_hms
    end_hms = chapter.end_hms
    safe_title = sanitize_filename(chapter.title)
    section_label = f"{start_hms.replace(':', '_')}-{end_hms.replace(':', '_')}"

    outtmpl = str(
        outdir / f"%(title)s - {safe_title} - {section_label}.%(ext)s"
    )

    cmd = [
        "yt-dlp",
        "--download-sections",
        f"*{start_hms}-{end_hms}",
        "-o",
        outtmpl,
        url,
    ]
    if extra_args:
        cmd[1:1] = extra_args

    process = subprocess.run(cmd, text=True, capture_output=True)
    if process.returncode != 0:
        raise ChapterDownloadError(
            f"챕터 다운로드 실패 (index={chapter.idx}): {process.stderr.strip() or '알 수 없는 오류'}"
        )

    pattern = f"* - {safe_title} - {section_label}.*"
    matches = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None
