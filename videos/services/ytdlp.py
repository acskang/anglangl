import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


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
    channel_name: str
    output_path: Path


class YtDlpService:
    def __init__(self, binary: str = "yt-dlp"):
        self.binary = binary

    def _yt_dlp_module(self) -> ModuleType:
        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise YtDlpTransientError("yt_dlp Python package is not installed.") from exc
        return yt_dlp

    def _ensure_binary(self) -> None:
        if shutil.which(self.binary) is None:
            raise YtDlpTransientError("yt-dlp is not installed or not found in PATH.")

    def _runtime_args(self) -> list[str]:
        node_path = shutil.which("node")
        if node_path:
            return ["--js-runtimes", f"node:{node_path}"]
        return []

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
            detail = (exc.stderr or exc.stdout or "yt-dlp command failed").strip()
            self._raise_mapped_error(detail, exc)

    def fetch_metadata(self, youtube_url: str) -> dict:
        cmd = [self.binary, *self._runtime_args(), "--dump-single-json", "--no-playlist", youtube_url]
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
            *self._runtime_args(),
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

    def download_clip_section(
        self,
        youtube_url: str,
        output_dir: Path,
        *,
        start_seconds: float,
        end_seconds: float,
    ) -> Path:
        if end_seconds <= start_seconds:
            raise YtDlpPermanentError("End time must be greater than start time.")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / "clip.%(ext)s")
        yt_dlp = self._yt_dlp_module()

        for stale_file in output_dir.glob("clip*"):
            if stale_file.is_file():
                stale_file.unlink(missing_ok=True)

        options = {
            "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]",
            "outtmpl": output_template,
            "download_ranges": yt_dlp.utils.download_range_func(None, [(float(start_seconds), float(end_seconds))]),
            "force_keyframes_at_cuts": True,
            "merge_output_format": "mp4",
            "overwrites": True,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([youtube_url])
        except Exception as exc:  # noqa: BLE001
            download_error = getattr(yt_dlp.utils, "DownloadError", None)
            if download_error and isinstance(exc, download_error):
                detail = str(exc).strip() or "yt-dlp download failed"
                self._raise_mapped_error(detail, exc)
            raise YtDlpTransientError(str(exc).strip() or "yt-dlp section download failed.") from exc

        files = sorted(
            (
                path
                for path in output_dir.glob("clip.*")
                if path.is_file() and path.suffix.lower() not in {".part", ".ytdl", ".tmp"}
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            raise YtDlpTransientError("yt-dlp finished but no clipped output file was found.")
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
            channel_name=metadata.get("uploader") or metadata.get("channel") or "",
            output_path=output_path,
        )

    def _format_seconds(self, value: float) -> str:
        total_ms = int(round(max(0.0, float(value)) * 1000))
        total_seconds, milliseconds = divmod(total_ms, 1000)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def _raise_mapped_error(self, detail: str, exc: Exception) -> None:
        normalized = detail.strip().lower()
        if (
            "unsupported url" in normalized
            or "video unavailable" in normalized
            or "private video" in normalized
            or "members-only" in normalized
            or "login required" in normalized
        ):
            raise YtDlpPermanentError(detail) from exc
        raise YtDlpTransientError(detail) from exc
