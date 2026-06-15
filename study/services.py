from dataclasses import dataclass
from pathlib import Path

import requests
from clips.models import Clip
from clips.services.subtitles import parse_srt, parse_subtitle_file, parse_vtt
from dramaNlearn.models import Video as DramaVideo
from videos.models import MasterVideo

from .models import (
    StudyMaterial,
    StudyMaterialDifficulty,
    StudyMaterialPurpose,
    StudyMaterialSourceType,
    StudyMaterialType,
)


@dataclass
class StudySourcePayload:
    source_type: str
    title: str
    source_url: str
    imdb_code: str
    source_text: str = ""
    source_text_kind: str = ""
    source_master_video: MasterVideo | None = None
    source_clip: Clip | None = None
    source_drama_video: DramaVideo | None = None


def _normalize_source_text(text: str, *, limit: int = 2000) -> str:
    compact = "\n".join(line.strip() for line in str(text).splitlines() if line.strip())
    return compact[:limit].strip()


def _source_text_lines(text: str, *, limit: int = 8) -> list[str]:
    return [line.strip() for line in str(text).splitlines() if line.strip()][:limit]


def _pick_focus_sentences(text: str, *, limit: int = 3) -> list[str]:
    lines = _source_text_lines(text, limit=12)
    if not lines:
        return []
    sorted_lines = sorted(lines, key=lambda item: (-len(item), item))
    selected = []
    for line in sorted_lines:
        if line not in selected:
            selected.append(line)
        if len(selected) >= limit:
            break
    return selected


def _pick_focus_words(text: str, *, limit: int = 5) -> list[str]:
    tokens = []
    for raw_line in _source_text_lines(text, limit=12):
        for token in raw_line.replace(",", " ").replace(".", " ").replace("!", " ").replace("?", " ").split():
            cleaned = "".join(ch for ch in token if ch.isalpha() or ch in {"'", "-"}).strip("-'")
            if len(cleaned) >= 4:
                tokens.append(cleaned.lower())
    unique = []
    for token in tokens:
        if token not in unique:
            unique.append(token)
        if len(unique) >= limit:
            break
    return unique


def _expression_outline_lines(focus_sentences: list[str]) -> list[str]:
    if not focus_sentences:
        return [
            "1. 표현:",
            "   - 뜻:",
            "   - 쓰이는 상황:",
            "   - 바꿔 말하기:",
            "",
            "2. 표현:",
            "   - 뜻:",
            "   - 쓰이는 상황:",
            "   - 바꿔 말하기:",
        ]

    lines: list[str] = []
    for index, sentence in enumerate(focus_sentences, start=1):
        lines.extend(
            [
                f"{index}. 표현: {sentence}",
                "   - 뜻:",
                "   - 쓰이는 상황:",
                "   - 바꿔 말하기:",
                "",
            ]
        )
    return lines


def _learning_note_sentence_lines(focus_sentences: list[str]) -> list[str]:
    if not focus_sentences:
        return [
            "- 문장 1:",
            "- 해석:",
            "- 포인트:",
        ]

    lines: list[str] = []
    for index, sentence in enumerate(focus_sentences[:2], start=1):
        lines.extend(
            [
                f"- 문장 {index}: {sentence}",
                "  - 해석:",
                "  - 포인트:",
                "",
            ]
        )
    return lines


def _learning_note_word_lines(focus_words: list[str]) -> list[str]:
    if not focus_words:
        return [
            "- 단어:",
            "- 뜻:",
            "- 예문:",
        ]

    lines: list[str] = []
    for word in focus_words[:4]:
        lines.extend(
            [
                f"- 단어: {word}",
                "  - 뜻:",
                "  - 예문:",
                "",
            ]
        )
    return lines


def _read_master_video_subtitle_text(video: MasterVideo) -> str:
    if not video.subtitle_file:
        return ""

    subtitle_path = Path(video.subtitle_file.path)
    if not subtitle_path.exists():
        return ""

    try:
        segments = parse_subtitle_file(subtitle_path)
    except Exception:
        try:
            return _normalize_source_text(subtitle_path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return ""

    joined = "\n".join(segment.text for segment in segments if getattr(segment, "text", "").strip())
    return _normalize_source_text(joined)


def _build_drama_source_note(drama_video: DramaVideo) -> tuple[str, str]:
    tracks = drama_video.subtitle_tracks_list()
    if not tracks:
        return "", ""

    lines = []
    for track in tracks[:5]:
        if not isinstance(track, dict):
            continue
        label = str(track.get("label") or track.get("srclang") or "subtitle").strip()
        url = str(track.get("src") or track.get("url") or "").strip()
        if url:
            lines.append(f"- {label}: {url}")
        elif label:
            lines.append(f"- {label}")

    if not lines:
        return "", ""
    return "subtitle_tracks", "\n".join(lines)


def _parse_remote_subtitle_content(content: str, source_url: str) -> str:
    lower_url = source_url.lower()
    try:
        if ".srt" in lower_url:
            return _normalize_source_text("\n".join(segment.text for segment in parse_srt(content)))
        if ".vtt" in lower_url:
            return _normalize_source_text("\n".join(segment.text for segment in parse_vtt(content)))
    except Exception:
        return _normalize_source_text(content)

    try:
        return _normalize_source_text("\n".join(segment.text for segment in parse_vtt(content)))
    except Exception:
        try:
            return _normalize_source_text("\n".join(segment.text for segment in parse_srt(content)))
        except Exception:
            return _normalize_source_text(content)


def _fetch_drama_subtitle_text(drama_video: DramaVideo) -> tuple[str, str]:
    tracks = drama_video.subtitle_tracks_list()
    if not tracks:
        return "", ""

    prioritized_tracks = []
    english_tracks = []
    fallback_tracks = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        src = str(track.get("src") or track.get("url") or "").strip()
        if not src:
            continue
        lang = str(track.get("srclang") or "").strip().lower()
        label = str(track.get("label") or "").strip().lower()
        track_ref = (src, lang, label)
        if lang in {"en", "eng"} or "english" in label:
            english_tracks.append(track_ref)
        else:
            fallback_tracks.append(track_ref)
    prioritized_tracks.extend(english_tracks)
    prioritized_tracks.extend(fallback_tracks)

    for src, lang, label in prioritized_tracks[:5]:
        try:
            response = requests.get(src, timeout=5)
            response.raise_for_status()
        except requests.RequestException:
            continue
        text = _parse_remote_subtitle_content(response.text, src)
        if text:
            return "drama_subtitle_body", text

    note_kind, note_text = _build_drama_source_note(drama_video)
    return note_kind, note_text


def resolve_study_source(*, user, params) -> StudySourcePayload:
    source_type = (params.get("source_type") or StudyMaterialSourceType.MANUAL).strip()

    if source_type == StudyMaterialSourceType.CLIP:
        clip = Clip.objects.filter(pk=params.get("clip_id"), owner=user, is_active=True).select_related("master_video").first()
        if clip:
            source_url = clip.master_video.source_url if clip.master_video else ""
            return StudySourcePayload(
                source_type=StudyMaterialSourceType.CLIP,
                title=clip.title,
                source_url=source_url,
                imdb_code="",
                source_text=_normalize_source_text(clip.subtitle or ""),
                source_text_kind="clip_subtitle" if clip.subtitle else "",
                source_clip=clip,
            )

    if source_type == StudyMaterialSourceType.MASTER_VIDEO:
        video = MasterVideo.objects.filter(pk=params.get("master_video_id"), owner=user, is_active=True).first()
        if video:
            return StudySourcePayload(
                source_type=StudyMaterialSourceType.MASTER_VIDEO,
                title=video.title,
                source_url=video.source_url,
                imdb_code="",
                source_text=_read_master_video_subtitle_text(video),
                source_text_kind="master_video_subtitle" if video.subtitle_file else "",
                source_master_video=video,
            )

    if source_type == StudyMaterialSourceType.DRAMA_VIDEO:
        drama_video = DramaVideo.objects.filter(pk=params.get("drama_video_id"), owner=user).first()
        if drama_video:
            source_text_kind, source_text = _fetch_drama_subtitle_text(drama_video)
            return StudySourcePayload(
                source_type=StudyMaterialSourceType.DRAMA_VIDEO,
                title=drama_video.title,
                source_url=drama_video.source_url,
                imdb_code="",
                source_text=source_text,
                source_text_kind=source_text_kind,
                source_drama_video=drama_video,
            )

    if source_type == StudyMaterialSourceType.MOVIE:
        title = (params.get("title") or "영화 학습 자료").strip()
        imdb_code = (params.get("imdb") or "").strip()
        return StudySourcePayload(
            source_type=StudyMaterialSourceType.MOVIE,
            title=title,
            source_url="",
            imdb_code=imdb_code,
        )

    if source_type == StudyMaterialSourceType.URL:
        title = (params.get("title") or "URL 기반 학습 자료").strip()
        source_url = (params.get("source_url") or "").strip()
        return StudySourcePayload(
            source_type=StudyMaterialSourceType.URL,
            title=title,
            source_url=source_url,
            imdb_code="",
        )

    return StudySourcePayload(
        source_type=StudyMaterialSourceType.MANUAL,
        title=(params.get("title") or "새 학습 자료").strip() or "새 학습 자료",
        source_url="",
        imdb_code="",
    )


def suggest_purpose(material_type: str) -> str:
    if material_type == StudyMaterialType.SHADOWING_SCRIPT:
        return StudyMaterialPurpose.SHADOWING
    if material_type == StudyMaterialType.EXPRESSIONS:
        return StudyMaterialPurpose.SPEAKING
    if material_type == StudyMaterialType.LEARNING_NOTE:
        return StudyMaterialPurpose.VOCABULARY
    return StudyMaterialPurpose.GENERAL


def suggest_difficulty(source: StudySourcePayload) -> str:
    if source.source_type == StudyMaterialSourceType.MOVIE:
        return StudyMaterialDifficulty.INTERMEDIATE
    if source.source_text:
        return StudyMaterialDifficulty.INTERMEDIATE
    return StudyMaterialDifficulty.MIXED


def build_material_title(source: StudySourcePayload, material_type: str) -> str:
    label = dict(StudyMaterialType.choices).get(material_type, "학습 자료")
    return f"{source.title} · {label}"


def build_initial_material_content(*, source: StudySourcePayload, material_type: str, purpose: str) -> str:
    source_lines = [
        f"- 소스 유형: {dict(StudyMaterialSourceType.choices).get(source.source_type, source.source_type)}",
        f"- 소스 제목: {source.title or '-'}",
    ]
    if source.source_url:
        source_lines.append(f"- 원본 URL: {source.source_url}")
    if source.imdb_code:
        source_lines.append(f"- IMDb: {source.imdb_code}")
    if source.source_text_kind == "clip_subtitle":
        source_lines.append("- 자막 본문: clip subtitle 사용")
    elif source.source_text_kind == "master_video_subtitle":
        source_lines.append("- 자막 본문: master video subtitle file 사용")
    elif source.source_text_kind == "drama_subtitle_body":
        source_lines.append("- 자막 본문: dramaNlearn subtitle track fetch 사용")
    elif source.source_text_kind == "subtitle_tracks":
        source_lines.append("- 자막 트랙: dramaNlearn subtitle track 메타데이터 사용")
    subtitle_text = source.source_text.strip()
    focus_sentences = _pick_focus_sentences(subtitle_text)
    focus_words = _pick_focus_words(subtitle_text)

    if material_type == StudyMaterialType.SHADOWING_SCRIPT:
        script_lines = [
            "# 쉐도잉 스크립트 초안",
            "",
            "## 소스 정보",
            *source_lines,
            "",
            "## 학습 목표",
            f"- 목적: {dict(StudyMaterialPurpose.choices).get(purpose, purpose)}",
            "- 한 문장씩 듣고 따라 읽기",
            "- 발음, 억양, 리듬 포인트 표시하기",
            "- 어려운 문장은 짧은 단위로 끊어서 반복하기",
            "",
            "## 추천 반복 구간",
        ]
        if subtitle_text:
            script_lines.extend(
                [
                    *(f"- {line}" for line in (focus_sentences or _source_text_lines(subtitle_text, limit=3))),
                    "",
                    "## 쉐도잉 스크립트",
                    *(f"{index}. {line}" for index, line in enumerate(_source_text_lines(subtitle_text), start=1)),
                    "",
                    "## 체크 포인트",
                    "- 호흡이 끊기는 위치에 `/` 표시를 넣어 보세요.",
                    "- 강세가 들어가는 단어는 대문자 또는 별표로 표시해 보세요.",
                    "- 어려운 구간은 0.75x로 3회 이상 반복해 보세요.",
                    "",
                    "## 후편집 메모",
                    "- 발음이 어려운 문장에 한국어 힌트를 붙이세요.",
                    "- 바로 따라 말할 문장 2개를 남기세요.",
                ]
            )
        else:
            script_lines.extend(
                [
                    "- 아직 대사/자막 본문이 연결되지 않았습니다.",
                    "- 이 자료는 소스 메타데이터 기반 초안입니다.",
                    "- 다음 단계에서 자막 추출 또는 수동 편집으로 본문을 보강하세요.",
                ]
            )
        return "\n".join(script_lines)

    if material_type == StudyMaterialType.EXPRESSIONS:
        return "\n".join(
            [
                "# 핵심 표현 정리 초안",
                "",
                "## 소스 정보",
                *source_lines,
                "",
                "## 표현 정리",
                *_expression_outline_lines(focus_sentences),
                "",
                "## 소스 발화/자막 참고",
                subtitle_text or "- 아직 연결된 자막 본문이 없습니다.",
                "",
                "## 장면 맥락 메모",
                "- 누가 말했는지:",
                "- 어떤 상황에서 나왔는지:",
                "- 그대로 써볼 수 있는 회화 장면:",
                "",
                "## 직접 채워 넣을 포인트",
                "- 실제 발화 상황",
                "- 말투와 뉘앙스",
                "- 따라 말해볼 예문",
            ]
        )

    return "\n".join(
        [
            "# 단어/문장 학습 노트 초안",
            "",
            "## 소스 정보",
            *source_lines,
            "",
            "## 핵심 문장",
            *_learning_note_sentence_lines(focus_sentences),
            "",
            "## 핵심 단어",
            *_learning_note_word_lines(focus_words),
            "",
            "## 복습 메모",
            "- 오늘 어려웠던 표현:",
            "- 다시 볼 문장:",
            "- 다음에 확장할 주제:",
            "",
            "## 소스 발화/자막 참고",
            subtitle_text or "- 아직 연결된 자막 본문이 없습니다.",
        ]
    )


def append_generation_history(material: StudyMaterial, *, source: StudySourcePayload, template_key: str) -> list[dict]:
    history = list(material.generation_history or [])
    history.append(
        {
            "template_key": template_key,
            "source_type": source.source_type,
            "source_title": source.title,
            "source_url": source.source_url,
            "imdb_code": source.imdb_code,
            "source_text_kind": source.source_text_kind,
        }
    )
    return history
