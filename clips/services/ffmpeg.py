import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


class FfmpegError(Exception):
    pass


class FfmpegTransientError(FfmpegError):
    pass


class FfmpegPermanentError(FfmpegError):
    pass


@dataclass(frozen=True)
class ClipExtractionResult:
    clip_output_path: Path
    thumbnail_output_path: Path


@dataclass(frozen=True)
class MediaProfile:
    container: str
    video_codec: str
    audio_codec: str


@dataclass(frozen=True)
class HlsResult:
    manifest_path: Path


ProgressCallback = Callable[[int], None]


class FfmpegService:
    def __init__(self, ffmpeg_binary: str = "ffmpeg", ffprobe_binary: str = "ffprobe"):
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary

    def _ensure_binary(self, binary: str) -> None:
        if shutil.which(binary) is None:
            raise FfmpegTransientError(f"{binary} is not installed or not found in PATH.")

    def _run(self, args: list[str], timeout: int = 1200) -> subprocess.CompletedProcess[str]:
        self._ensure_binary(args[0])
        try:
            return subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise FfmpegTransientError("ffmpeg/ffprobe command timed out.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").lower()
            detail = (exc.stderr or exc.stdout or "ffmpeg/ffprobe command failed").strip()
            if "invalid argument" in stderr or "no such file" in stderr or "invalid data found" in stderr:
                raise FfmpegPermanentError(detail) from exc
            raise FfmpegTransientError(detail) from exc

    def _classify_process_error(self, detail: str) -> FfmpegError:
        lowered = detail.lower()
        if "invalid argument" in lowered or "no such file" in lowered or "invalid data found" in lowered:
            return FfmpegPermanentError(detail)
        return FfmpegTransientError(detail)

    def _run_ffmpeg_with_progress(
        self,
        args: list[str],
        timeout: int,
        progress_callback: ProgressCallback | None = None,
        expected_duration_seconds: float | None = None,
    ) -> None:
        self._ensure_binary(args[0])
        command = [args[0], "-nostdin", "-progress", "pipe:2", "-nostats", *args[1:]]
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        started_at = time.monotonic()
        stderr_lines: list[str] = []
        progress_state: dict[str, str] = {}
        last_reported = -1

        try:
            assert process.stderr is not None
            while True:
                if timeout and (time.monotonic() - started_at) > timeout:
                    raise subprocess.TimeoutExpired(command, timeout)

                line = process.stderr.readline()
                if line == "" and process.poll() is not None:
                    break
                if not line:
                    continue

                stripped = line.strip()
                if not stripped:
                    continue

                stderr_lines.append(stripped)
                if len(stderr_lines) > 200:
                    stderr_lines.pop(0)

                if "=" not in stripped:
                    continue

                key, value = stripped.split("=", 1)
                progress_state[key] = value
                if key == "out_time_ms" and progress_callback and expected_duration_seconds and expected_duration_seconds > 0:
                    current_seconds = max(0.0, int(value) / 1_000_000)
                    percent = min(99, max(0, int((current_seconds / expected_duration_seconds) * 100)))
                    if percent > last_reported:
                        last_reported = percent
                        progress_callback(percent)
                elif key == "progress" and value == "end" and progress_callback:
                    progress_callback(100)
        except subprocess.TimeoutExpired as exc:
            self._terminate_process(process)
            raise FfmpegTransientError("ffmpeg command timed out.") from exc
        except BaseException:
            self._terminate_process(process)
            raise

        return_code = process.wait()
        if return_code != 0:
            detail = "\n".join(stderr_lines).strip() or "ffmpeg command failed"
            raise self._classify_process_error(detail)

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def probe_duration_seconds(self, source_path: Path) -> int:
        if not source_path.exists():
            raise FfmpegPermanentError("Source video file does not exist.")

        cmd = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(source_path),
        ]
        result = self._run(cmd)

        try:
            parsed = json.loads(result.stdout)
            duration_raw = parsed.get("format", {}).get("duration")
            duration = int(float(duration_raw)) if duration_raw is not None else 0
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise FfmpegTransientError("Failed to parse ffprobe duration output.") from exc

        if duration <= 0:
            raise FfmpegPermanentError("Could not detect valid clip duration.")

        return duration

    def probe_media_profile(self, source_path: Path) -> MediaProfile:
        if not source_path.exists():
            raise FfmpegPermanentError("Source video file does not exist.")

        cmd = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=format_name",
            "-show_streams",
            "-of",
            "json",
            str(source_path),
        ]
        result = self._run(cmd)

        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FfmpegTransientError("Failed to parse ffprobe media profile output.") from exc

        format_name = str(parsed.get("format", {}).get("format_name") or "").split(",")[0].strip().lower()
        streams = parsed.get("streams") or []
        video_codec = ""
        audio_codec = ""
        for stream in streams:
            codec_type = str(stream.get("codec_type") or "").lower()
            codec_name = str(stream.get("codec_name") or "").lower()
            if codec_type == "video" and not video_codec:
                video_codec = codec_name
            elif codec_type == "audio" and not audio_codec:
                audio_codec = codec_name

        return MediaProfile(
            container=format_name,
            video_codec=video_codec,
            audio_codec=audio_codec,
        )

    def generate_thumbnail(
        self,
        source_path: Path,
        thumbnail_path: Path,
        seek_seconds: float,
        timeout: int = 1200,
    ) -> Path:
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg_binary,
            "-y",
            "-ss",
            str(max(0.1, seek_seconds)),
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            str(thumbnail_path),
        ]
        self._run_ffmpeg_with_progress(cmd, timeout=timeout)
        if not thumbnail_path.exists():
            raise FfmpegTransientError("Thumbnail generation finished but output file is missing.")
        return thumbnail_path

    def generate_hls(
        self,
        source_path: Path,
        output_dir: Path,
        playlist_name: str = "index.m3u8",
        timeout: int = 3600,
        progress_callback: ProgressCallback | None = None,
        expected_duration_seconds: float | None = None,
    ) -> HlsResult:
        if not source_path.exists():
            raise FfmpegPermanentError("Source video file does not exist.")

        output_dir.mkdir(parents=True, exist_ok=True)
        for existing in output_dir.iterdir():
            if existing.is_file():
                existing.unlink()
            else:
                shutil.rmtree(existing, ignore_errors=True)

        manifest_path = output_dir / playlist_name
        segment_pattern = output_dir / "segment_%05d.ts"
        cmd = [
            self.ffmpeg_binary,
            "-y",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-sn",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-g",
            "48",
            "-keyint_min",
            "48",
            "-sc_threshold",
            "0",
            "-force_key_frames",
            "expr:gte(t,n_forced*2)",
            "-f",
            "hls",
            "-hls_time",
            "2",
            "-hls_playlist_type",
            "vod",
            "-hls_flags",
            "independent_segments",
            "-hls_segment_filename",
            str(segment_pattern),
            str(manifest_path),
        ]
        self._run_ffmpeg_with_progress(
            cmd,
            timeout=timeout,
            progress_callback=progress_callback,
            expected_duration_seconds=expected_duration_seconds,
        )

        if not manifest_path.exists():
            raise FfmpegTransientError("HLS generation finished but manifest file is missing.")

        return HlsResult(manifest_path=manifest_path)

    def _normalize_source_arg(self, source_path: Path | str) -> str:
        if isinstance(source_path, Path):
            if not source_path.exists():
                raise FfmpegPermanentError("Source video file does not exist.")
            return str(source_path)

        source_text = str(source_path or "").strip()
        if not source_text:
            raise FfmpegPermanentError("Source video path is empty.")

        parsed = urlparse(source_text)
        if parsed.scheme in {"http", "https"}:
            return source_text

        file_path = Path(source_text)
        if not file_path.exists():
            raise FfmpegPermanentError("Source video file does not exist.")
        return str(file_path)

    def extract_clip(
        self,
        source_path: Path | str,
        output_path: Path,
        thumbnail_path: Path,
        start_seconds: int,
        end_seconds: int,
        timeout: int = 1200,
        progress_callback: ProgressCallback | None = None,
        input_options: list[str] | None = None,
    ) -> ClipExtractionResult:
        source_arg = self._normalize_source_arg(source_path)
        duration = end_seconds - start_seconds
        if duration <= 0:
            raise FfmpegPermanentError("Invalid clip duration.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_input_options = list(input_options or [])

        extract_cmd = [
            self.ffmpeg_binary,
            "-y",
            "-ss",
            str(start_seconds),
            *resolved_input_options,
            "-i",
            source_arg,
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(output_path),
        ]
        self._run_ffmpeg_with_progress(
            extract_cmd,
            timeout=timeout,
            progress_callback=progress_callback,
            expected_duration_seconds=duration,
        )

        # Prefer the near-first visible frame so the thumbnail matches clip review.
        thumb_seek = 0.1
        self.generate_thumbnail(output_path, thumbnail_path, thumb_seek, timeout=timeout)

        if not output_path.exists():
            raise FfmpegTransientError("Clip extraction finished but output file is missing.")

        return ClipExtractionResult(clip_output_path=output_path, thumbnail_output_path=thumbnail_path)
