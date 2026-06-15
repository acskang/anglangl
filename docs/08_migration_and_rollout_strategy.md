# 08. Migration 및 Rollout 전략

## 목적

학습 자료 중심 확장을 운영 중인 Django 서비스에 안전하게 반영한다.

## 원칙

- schema 변경은 단계별로 작게 수행한다.
- 기존 데이터가 없어도, 있어도 migration이 통과해야 한다.
- 기존 URL과 템플릿 진입점은 가능한 한 유지한다.
- 새 기능은 feature flag나 fallback으로 기존 deterministic draft를 보존한다.

## 단계별 rollout

```text
Phase 1: Baseline inventory
  현재 모델, URL, 테스트, 수동 QA를 문서화한다.

Phase 2: StudyMaterial hardening
  필요한 필드만 추가하고 migration/test를 작성한다.

Phase 3: Template registry
  생성 템플릿을 서비스 레이어로 분리한다.

Phase 4: Create flow upgrade
  source resolver, template selector, draft result를 화면에서 명확히 보여준다.

Phase 5: Library/Explore IA
  필터, 정렬, 품질 badge, 공개/복제 UX를 정리한다.

Phase 6: Internal API/MCP
  학습 자료 검색/상세/초안 도구를 추가한다.

Phase 7: AI provider integration
  LLM client를 추가하되 fallback을 유지한다.
```

## 데이터 마이그레이션 주의

```text
StudyMaterial.source_snapshot
  기존 자료는 source_title/source_url/source_*에서 best-effort로 채운다.

published_at
  기존 public 자료는 updated_at 또는 created_at으로 backfill 가능하다.

generation_status
  기존 자료는 ready로 backfill한다.
```

## 배포 전 확인

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py test study.tests
python manage.py test internal_api.tests
scripts/test-postgres-min.sh --skip-migrate
```

실제 명령은 현재 환경과 변경 범위에 맞춰 조정한다.

## rollback 관점

- 템플릿/뷰 변경은 이전 URL을 유지하면 rollback이 쉽다.
- schema 변경은 nullable/default 필드로 시작한다.
- LLM 기능은 실패 시 기존 deterministic draft로 돌아갈 수 있어야 한다.
- 공개/복제 권한 변경은 테스트 없이는 배포하지 않는다.

