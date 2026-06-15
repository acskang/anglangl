# anglangl 설계 문서 패키지

`anglangl`은 AI · LLM 기반 영어 학습 자료 생성 및 공유 플랫폼이다. 이 문서 패키지는 현재 Django 코드베이스를 분석한 결과를 기준으로, 기존 영상/클립/학습 이력 기능을 학습 자료 생성 생태계로 정렬하기 위한 설계서와 단계별 Codex 구현 프롬프트를 제공한다.

## 현재 프로젝트

```text
Name: anglangl
Root: /home/cskang/ganzskang/anglangl
Django settings: config.settings.base
Display name: 앙글앙글 / anglangl
Core direction: AI · LLM 기반 영어 학습 자료 생성 및 공유 플랫폼
DB default: PostgreSQL listening_clips
Local optional DB: USE_SQLITE=1 python manage.py ...
Async stack: Celery + Redis
Media stack: yt-dlp + ffmpeg/ffprobe + HLS long-term playback
```

## 추천 문서 읽기 순서

1. `docs/00_current_state_entrypoint.md`
2. `docs/01_overview.md`
3. `docs/02_domain_model_design.md`
4. `docs/03_information_architecture_design.md`
5. `docs/04_ai_generation_workflow_design.md`
6. `docs/05_media_source_pipeline_design.md`
7. `docs/06_share_reuse_design.md`
8. `docs/07_internal_api_mcp_design.md`
9. `docs/08_migration_and_rollout_strategy.md`
10. `docs/09_risk_and_test_plan.md`
11. `docs/10_codex_master_prompt.md`

## 단계별 Codex 프롬프트

아래 프롬프트는 한 번에 모두 실행하지 않는다. 각 단계는 해당 목표만 수행하고 검증 후 멈추는 방식으로 작성되어 있다.

- `docs/codex_prompts/01_source_inventory_and_baseline.md`
- `docs/codex_prompts/02_study_material_schema_hardening.md`
- `docs/codex_prompts/03_generation_template_registry.md`
- `docs/codex_prompts/04_material_create_flow_upgrade.md`
- `docs/codex_prompts/05_library_and_explore_ia.md`
- `docs/codex_prompts/06_share_clone_permissions.md`
- `docs/codex_prompts/07_media_to_material_pipeline.md`
- `docs/codex_prompts/08_internal_api_mcp_materials.md`
- `docs/codex_prompts/09_dashboard_and_job_status_unification.md`
- `docs/codex_prompts/10_integration_manual_qa.md`

## 핵심 원칙

- `anglangl`을 단순 영상 사이트나 AI 챗봇으로 만들지 않는다.
- 최종 산출물은 채팅 답변이 아니라 저장, 편집, 공유, 복제 가능한 `StudyMaterial`이어야 한다.
- 기존 `videos`, `clips`, `dramaNlearn`, `movies`는 학습 자료 생성을 위한 source asset으로 재해석한다.
- 새 기능은 `입력 -> 생성 -> 편집 -> 저장 -> 공유 -> 재사용` 흐름 중 어디에 기여하는지 분명해야 한다.
- 대규모 리팩터링보다 현재 모델과 화면을 이용한 단계적 개선을 우선한다.
- 코드 변경이 있으면 최소한 `python manage.py check`와 관련 앱 테스트를 수행한다.
- 문서만 수정한 경우에는 파일 목록, 링크 검증, 키워드 grep 검증을 보고한다.

