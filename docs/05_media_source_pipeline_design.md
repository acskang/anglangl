# 05. 미디어 소스 파이프라인 설계

## 목적

기존 영상/클립 기능을 학습 자료 생성의 입력 자산으로 정리한다.

## 현재 소스 유형

```text
MasterVideo
  YouTube, upload, drama bridge, subtitle file, HLS manifest

Clip
  extracted, uploaded, subtitle, subtitle_timing, thumbnail, HLS manifest

DramaVideo
  external source_url, player_url, m3u8_url, subtitle_tracks, status

Movie
  title, imdb/tmdb metadata, player_url

URL / Manual
  lightweight source metadata
```

## 목표 Source Payload

`study.services.StudySourcePayload`를 확장 가능한 공통 입력 구조로 유지한다.

```text
StudySourcePayload
├── source_type
├── title
├── source_url
├── imdb_code
├── source_text
├── source_text_kind
├── source_master_video
├── source_clip
├── source_drama_video
└── future: source_snapshot, thumbnail_url, timing_range
```

## 소스 품질 단계

```text
rich
  자막/대사 본문이 있고 문장 단위 자료 생성 가능

medium
  자막 track metadata는 있지만 본문 fetch가 제한적

light
  제목/URL 등 metadata만 있고 사용자의 후편집이 필요
```

현재 `StudyMaterial.quality_badge`와 `quality_tone`은 이 개념을 이미 부분적으로 구현한다.

## Clip 기반 생성

```text
Clip detail
→ subtitle 또는 Whisper/Youtube subtitle preview 확보
→ study/create/?source_type=clip&clip_id=...
→ source_text_kind=clip_subtitle
→ 쉐도잉/표현/노트 초안 생성
```

## MasterVideo 기반 생성

```text
MasterVideo detail
→ subtitle_file이 있으면 parse
→ 없으면 metadata 기반 초안
→ 필요 시 clip extraction으로 세분화
```

## DramaVideo 기반 생성

```text
dramaNlearn Video
→ subtitle_tracks_list()
→ 영어 track 우선 fetch
→ 실패 시 track metadata 기반 초안
```

## 권장 후속 작업

1. 모든 source detail 화면에 `학습 자료 만들기` 진입을 일관되게 배치한다.
2. source resolver 결과를 `source_snapshot`으로 저장한다.
3. 자막 본문이 없는 경우 사용자에게 품질 상태와 다음 행동을 보여준다.
4. HLS playback과 자료 생성 링크가 같은 source detail에서 만난다.

