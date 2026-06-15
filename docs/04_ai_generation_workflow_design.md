# 04. AI 생성 워크플로우 설계

## 목적

LLM을 서비스 전면에 노출하는 대신, 사용자가 통제 가능한 학습 자료 생성 도구로 구성한다.

## 기본 흐름

```text
Source Resolver
→ Template Registry
→ Prompt Builder
→ LLM Client
→ Draft Parser
→ StudyMaterial + StudyMaterialGeneration 저장
→ 사용자 편집
```

## 현재 구현

`study/services.py`는 source resolver와 deterministic draft builder를 이미 제공한다.

```text
resolve_study_source()
build_material_title()
build_initial_material_content()
append_generation_history()
```

이 구조를 유지하면서 LLM 호출은 별도 서비스로 추가한다.

## Template Registry

초기에는 DB 모델보다 코드 상수/데이터 클래스로 시작한다.

```text
TemplateDefinition
├── key
├── title
├── material_type
├── default_purpose
├── supported_sources
├── output_sections
└── prompt_builder
```

예시:

```text
shadowing_script
expressions
learning_note
listening_quiz
grammar_focus
```

## Prompt 입력 원칙

```text
source_snapshot
  title, source_type, source_url, source text excerpt, clip timing

user_controls
  material_type, purpose, difficulty, preferred language, notes

output_contract
  sections, bullet style, JSON/plain markdown policy
```

## 출력 저장 원칙

- `generated_content`에는 사용자가 바로 편집할 수 있는 본문을 저장한다.
- `editable_notes`에는 사용자 메모와 다음 액션을 저장한다.
- `StudyMaterialGeneration.output_snapshot`에는 원본 LLM 출력, 파싱 결과, fallback 여부를 저장한다.
- 실패해도 빈 화면으로 끝내지 않고 deterministic draft를 fallback으로 제공한다.

## 비동기 처리

LLM 호출이 느려질 수 있으므로 장기적으로는 `BackgroundJob`과 Celery로 연결한다.

```text
StudyMaterial.generation_status = queued
BackgroundJob(job_type=study_material_generate)
Celery task calls LLM
StudyMaterial.generation_status = ready/failed
```

초기 단계에서는 동기 생성 + 명확한 실패 메시지로 시작할 수 있다.

## 실패 처리

```text
LLM timeout
  fallback deterministic draft 저장
  generation_history에 fallback=true 기록

Source text missing
  metadata 기반 초안 저장
  사용자에게 자막/본문 보강 필요 표시

Parsing failed
  raw markdown 저장
  output_snapshot에 parse_error 기록
```

