import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class WhisperError(Exception):
    pass


@dataclass(frozen=True)
class WhisperTranscript:
    text: str
    timing_json: str


class WhisperService:
    def __init__(
        self,
        binary: str = "whisper",
        model: str = "base",
        language: str | None = "en",
        task: str = "transcribe",
    ):
        self.binary = binary
        self.model = model
        self.language = language
        self.task = task

    def _ensure_binary(self) -> None:
        if shutil.which(self.binary) is None:
            raise WhisperError(f"{self.binary} is not installed or not found in PATH.")

    def transcribe(self, source_path: Path) -> WhisperTranscript:
        self._ensure_binary()
        if not source_path.exists():
            raise WhisperError("Clip file does not exist.")

        with tempfile.TemporaryDirectory(prefix="clip-whisper-") as temp_dir:
            output_dir = Path(temp_dir)
            cmd = [
                self.binary,
                str(source_path),
                "--model",
                self.model,
                "--task",
                self.task,
                "--word_timestamps",
                "True",
                "--output_format",
                "json",
                "--output_dir",
                str(output_dir),
            ]
            if self.language:
                cmd.extend(["--language", self.language])
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=3600,
                )
            except subprocess.TimeoutExpired as exc:
                raise WhisperError("Whisper command timed out.") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "Whisper command failed.").strip()
                raise WhisperError(detail) from exc

            transcript_path = output_dir / f"{source_path.stem}.json"
            if not transcript_path.exists():
                raise WhisperError("Whisper finished but transcript file was not created.")

            try:
                payload = json.loads(transcript_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise WhisperError("Whisper JSON output could not be parsed.") from exc

            text = str(payload.get("text") or "").strip()
            segments = []
            for segment in payload.get("segments") or []:
                words = []
                for word in segment.get("words") or []:
                    start = word.get("start")
                    end = word.get("end")
                    token = str(word.get("word") or "").strip()
                    if start is None or end is None or not token:
                        continue
                    words.append(
                        {
                            "start": float(start),
                            "end": float(end),
                            "word": token,
                        }
                    )
                if not words:
                    words = self._build_segment_word_timings(
                        str(segment.get("text") or "").strip(),
                        float(segment.get("start") or 0.0),
                        float(segment.get("end") or 0.0),
                    )
                if not words:
                    continue
                segments.append(
                    {
                        "start": float(segment.get("start") or words[0]["start"]),
                        "end": float(segment.get("end") or words[-1]["end"]),
                        "text": str(segment.get("text") or "").strip(),
                        "words": words,
                    }
                )

            return WhisperTranscript(
                text=text,
                timing_json=json.dumps(segments, ensure_ascii=False),
            )

    def _build_segment_word_timings(self, text: str, start: float, end: float) -> list[dict]:
        tokens = re.findall(r"\S+", text or "")
        if not tokens:
            return []
        duration = max(end - start, 0.01)
        step = duration / len(tokens)
        words = []
        current = start
        for token in tokens:
            next_time = current + step
            words.append(
                {
                    "start": round(current, 3),
                    "end": round(next_time, 3),
                    "word": token,
                }
            )
            current = next_time
        if words:
            words[-1]["end"] = round(end if end > start else words[-1]["end"], 3)
        return words
