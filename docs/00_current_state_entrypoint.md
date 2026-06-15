# 00. 현재 상태 진입점

## 목적

새 Codex 세션이나 개발자가 `anglangl` 후속 작업을 시작할 때 현재 코드 상태와 문서 기준을 빠르게 파악하기 위한 진입 문서다.

## 현재 코드베이스 요약

```text
config        Django settings, urls, Celery app
core          landing/player, 공통 상태 enum, 외부 콘텐츠 캐시
platform_auth ThePeach SSO 연동
videos        MasterVideo 등록, YouTube/import/upload, 썸네일, HLS
clips         Clip 생성/업로드/추출/자막/이미지/앨범
study         StudyMaterial 라이브러리, 공개 탐색, 복제, 생성 이력
dashboard     사용자 작업 현황과 최근 자료/클립/영상 요약
workers       BackgroundJob 상태 추적
internal_api  MCP용 내부 JSON API
mcp_server    FastMCP 기반 clip/video/study recent 도구
dramaNlearn   레거시 영상 URL 추출/플레이어/썸네일 관리
movies        영화 검색/시청 보조 흐름
interactions  clip like/comment
```

## 이미 구현된 핵심 자산

```text
StudyMaterial
├── owner
├── material_type
├── purpose
├── difficulty
├── visibility
├── source_type
├── source_* references
├── copied_from
├── generated_content
├── editable_notes
└── generation_history

StudyMaterialGeneration
├── material
├── created_by
├── template_key
├── prompt_intent
├── input_snapshot
└── output_snapshot
```

현재 `study` 앱은 이미 학습 자료의 생성, 편집, 라이브러리, 공개 탐색, 복제 흐름을 갖고 있다. 다만 실제 LLM 호출, 템플릿 레지스트리, 구조화된 생성 결과, 내부 API 확장, UI 정보구조 정리는 후속 작업으로 남아 있다.

## 현재 사용자 흐름

```text
소스 선택
→ /study/create/?source_type=...
→ 서비스 레이어가 소스 메타데이터/자막을 읽어 초안 생성
→ 사용자가 generated_content/editable_notes 편집
→ StudyMaterial 저장
→ /study/ 라이브러리에서 재열람
→ 공개 전환
→ /study/explore/에서 다른 사용자가 탐색
→ clone으로 내 라이브러리에 가져오기
```

## 중요한 기존 검증 문서

- `docs/manual-qa-checklist.md`
- `docs/manual-qa-execution-log.md`

## 작업 시작 전 확인

- `AGENTS.md`를 읽고 제품 정체성을 확인한다.
- `codex-history/`에 새 작업 기록을 생성한다.
- `git status --short`로 기존 변경을 확인한다.
- 코드 변경 여부와 문서 변경 여부를 구분한다.
- schema 변경이 필요한 단계인지 먼저 판단한다.

## 현재 우선순위

1. `StudyMaterial`을 영어 학습 자료의 중심 엔티티로 확정한다.
2. 영상/클립/드라마/영화 기능을 source asset으로 정리한다.
3. 생성 템플릿과 LLM 호출 경계를 명확히 한다.
4. 라이브러리와 탐색 화면을 생성/보관/공개/복제 흐름에 맞춰 다듬는다.
5. 내부 API와 MCP에 학습 자료 도구를 추가한다.

## 주의 사항

- 기존 미디어 처리 흐름은 깨지기 쉽다. ffmpeg/yt-dlp/Celery 관련 변경은 작은 단위로 해야 한다.
- `dramaNlearn`은 레거시 성격이 있으나 학습 자료 source로 쓰이고 있으므로 성급히 제거하지 않는다.
- 공개 자료 복제는 개인정보, 저작권, 원본 소스 노출 범위를 함께 고려해야 한다.
- AI 생성 결과는 모델 응답 원문이 아니라 사용자 편집 가능한 학습 자산으로 저장되어야 한다.

