import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class YtDlpError(Exception):
    pass


class YtDlpPermanentError(YtDlpError):
    pass


class YtDlpTransientError(YtDlpError):
    pass


@dataclass(frozen=True)
class DownloadResult:
    title: str
    description: str
    thumbnail_url: str
    duration_seconds: int | None
    file_size_bytes: int | None
    output_path: Path


class YtDlpService:
    def __init__(self, binary: str = "yt-dlp"):
        self.binary = binary

    def _ensure_binary(self) -> None:
        if shutil.which(self.binary) is None:
            raise YtDlpTransientError("yt-dlp is not installed or not found in PATH.")

    def _run(self, args: list[str], timeout: int = 1200) -> subprocess.CompletedProcess[str]:
        self._ensure_binary()
        try:
            return subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise YtDlpTransientError("yt-dlp timed out.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip().lower()
            detail = (exc.stderr or exc.stdout or "yt-dlp command failed").strip()
            if "unsupported url" in stderr or "video unavailable" in stderr or "private video" in stderr:
                raise YtDlpPermanentError(detail) from exc
            raise YtDlpTransientError(detail) from exc

    def fetch_metadata(self, youtube_url: str) -> dict:
        cmd = [self.binary, "--dump-single-json", "--no-playlist", youtube_url]
        result = self._run(cmd)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise YtDlpTransientError("Failed to parse yt-dlp metadata output.") from exc

    def download_video(self, youtube_url: str, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(destination_dir / "source.%(ext)s")
        cmd = [
            self.binary,
            "--no-playlist",
            "--output",
            output_template,
            youtube_url,
        ]
        self._run(cmd)

        files = sorted(destination_dir.glob("source.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise YtDlpTransientError("yt-dlp finished but no output file was found.")
        return files[0]

    def download_with_metadata(self, youtube_url: str, destination_dir: Path) -> DownloadResult:
        metadata = self.fetch_metadata(youtube_url)
        output_path = self.download_video(youtube_url, destination_dir)

        file_size = metadata.get("filesize") or metadata.get("filesize_approx")
        duration = metadata.get("duration")
        if isinstance(duration, float):
            duration = int(duration)

        return DownloadResult(
            title=metadata.get("title") or "",
            description=metadata.get("description") or "",
            thumbnail_url=metadata.get("thumbnail") or "",
            duration_seconds=duration if isinstance(duration, int) else None,
            file_size_bytes=file_size if isinstance(file_size, int) else None,
            output_path=output_path,
        )
