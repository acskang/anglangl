# Step 02 - StudyMaterial Schema Hardening

너는 `anglangl`의 학습 자료 자산 모델을 안정화하는 Django 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

`StudyMaterial`을 생성/공유/복제 가능한 학습 자료 자산으로 더 명확히 만들기 위해 필요한 최소 schema와 테스트를 추가한다.

## 주요 작업

- `docs/02_domain_model_design.md`를 읽는다.
- 현재 `study/models.py`, `study/views.py`, `study/tests.py`를 확인한다.
- 필요한 필드만 추가한다. 후보:
  - `summary`
  - `source_snapshot`
  - `published_at`
  - `generation_status`
  - `generation_error_message`
  - `clone_count_cache`
- 기존 데이터 migration이 안전한지 확인한다.
- 공개 전환 시 `published_at`이 채워지도록 한다.
- clone 시 `clone_count_cache`를 갱신할지, 후속 단계로 미룰지 결정하고 기록한다.
- 관련 regression test를 추가한다.

## 금지 사항

```text
불필요한 새 앱 생성 금지
한 번에 collection/tag/moderation까지 구현 금지
기존 StudyMaterial 생성/편집/복제 흐름 회귀 금지
```

## 검증

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py test study.tests
```

## 완료 보고 형식

```text
[Step 02 - StudyMaterial Schema Hardening 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. migration 내용
4. 주요 테스트
5. 실행한 명령어
6. 검증 결과
7. 남은 이슈
```

