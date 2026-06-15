# 06. 공유와 재사용 설계

## 목적

공개 기능을 단순 노출이 아니라 재사용 가능한 학습 자료 생태계로 설계한다.

## 현재 구현

```text
StudyMaterial.visibility
  private / public

StudyMaterial.copied_from
  복제 원본 추적

StudyMaterialExploreListView
  공개 자료 목록

StudyMaterialCloneView
  공개 자료를 내 라이브러리로 복제
```

## 공유 정책

```text
Private
  owner만 접근
  explore 노출 없음
  다른 사용자의 direct access 차단

Public
  explore 노출
  public detail 접근 가능
  로그인 사용자는 clone 가능

Clone
  새 owner로 복사
  visibility는 private
  copied_from으로 원본 추적
  복제 후 편집은 원본에 영향 없음
```

## 원본 정보 노출 정책

공개 자료에는 학습 맥락은 보여주되 민감한 내부 경로나 private 파일 정보는 노출하지 않는다.

```text
노출 가능
  source_title
  source_type
  public URL
  material purpose/difficulty/type
  작성자 display name

주의 필요
  원본 source_url
  private clip/video id
  내부 playback link
  local file path
```

## 탐색 품질 신호

초기에는 cache 필드 없이 계산 가능한 신호로 시작한다.

```text
quality_badge
source_type
difficulty
purpose
updated_at
clone count (future cache)
```

## 신고/저작권 후속 설계

공개 자료가 늘어나면 다음 모델 또는 상태가 필요하다.

```text
report_count
moderation_status: visible / hidden / review_required
license_note
source_attribution
```

초기 단계에서는 운영자 admin 확인과 공개 전환 문구 보강으로 시작한다.

