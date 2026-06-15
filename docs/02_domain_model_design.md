# 02. 도메인 모델 설계

## 목적

현재 모델을 유지하면서 `학습 자료` 중심 도메인으로 정리한다. 불필요한 대형 schema 변경보다 기존 `StudyMaterial`을 확장 가능한 중심 엔티티로 안정화하는 것이 우선이다.

## 현재 주요 모델

```text
MasterVideo
├── owner
├── source_type
├── youtube_url / remote_playback_url / video_file / subtitle_file / hls_manifest_file
├── source_drama_video
├── title / description / category / channel_name
├── duration_seconds
├── download_status / download_error_message
└── is_active

Clip
├── owner
├── source_type
├── master_video / upload_batch
├── title / description / subtitle / subtitle_timing
├── start_time_seconds / end_time_seconds / duration_seconds
├── clip_file / hls_manifest_file / thumbnail_file
├── is_public
├── file_status / file_error_message
└── cache fields

StudyMaterial
├── owner
├── title
├── material_type
├── purpose
├── difficulty
├── visibility
├── source_type
├── source_title / source_url / imdb_code
├── source_master_video / source_clip / source_drama_video
├── copied_from
├── generated_content
├── editable_notes
└── generation_history
```

## StudyMaterial의 역할

`StudyMaterial`은 서비스의 최종 산출물이다. 생성된 텍스트를 단순 저장하는 필드가 아니라, 학습자가 다시 열고 편집하고 공유할 수 있는 자산 단위다.

```text
StudyMaterial = source context + generated draft + user edits + sharing state + lineage
```

## 권장 보강 필드

필드는 한 번에 모두 추가하지 않는다. 실제 구현 단계에서 필요한 항목만 migration으로 추가한다.

```text
StudyMaterial
├── summary                  목록/탐색용 짧은 설명
├── language_level           CEFR 또는 내부 난이도 확장
├── tags                     단순 문자열 JSON 또는 별도 Tag 모델
├── source_snapshot          생성 당시 소스 메타데이터 JSON
├── generation_status        pending/processing/ready/failed
├── generation_error_message 실패 메시지
├── published_at             공개 시각
└── clone_count_cache        복제 활용 신호
```

## Generation 모델 보강 방향

현재 `StudyMaterialGeneration`은 생성 이력을 저장한다. LLM 도입 시 아래 값이 중요해진다.

```text
StudyMaterialGeneration
├── template_key
├── prompt_intent
├── input_snapshot
├── output_snapshot
├── model_name           future
├── provider             future
├── prompt_snapshot      future
├── status               future
├── error_message        future
└── latency_ms           future
```

## Source 참조 정책

원본 객체가 삭제되거나 비공개가 되어도 이미 생성된 학습 자료는 최소한의 source snapshot으로 열람 가능해야 한다.

```text
source_* FK      현재 연결 가능한 원본
source_snapshot 생성 당시 제목, URL, 시간 구간, 자막 일부, 썸네일 등의 복구 정보
source_title    목록/검색용 denormalized label
```

## 공개/복제 정책

```text
Private material
  owner만 열람/편집/복제 가능

Public material
  탐색 화면에 노출
  로그인 사용자는 clone 가능
  clone 결과는 기본 private
  원본 generated_content는 복사하지만 owner, visibility, editable_notes는 새 사용자 자산으로 분리
```

## 장기 확장 모델

```text
MaterialCollection
├── owner
├── title
├── description
├── visibility
└── materials

StudyMaterialTag
├── name
├── slug
└── usage_count

MaterialReviewSignal
├── user
├── material
├── action_type: clone/bookmark/complete/report
└── created_at
```

초기 단계에서는 별도 모델보다 `StudyMaterial`과 `StudyMaterialGeneration`을 안정화하는 것이 우선이다.

