# Step 04 - Material Create Flow Upgrade

너는 `anglangl`의 학습 자료 생성 화면을 개선하는 Django 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

`/study/create/`에서 source, template, purpose, difficulty, draft quality가 사용자에게 명확히 보이도록 개선한다.

## 주요 작업

- `docs/03_information_architecture_design.md`와 `docs/04_ai_generation_workflow_design.md`를 읽는다.
- `study/views.py`, `study/forms.py`, `templates/study/material_form.html`을 확인한다.
- source payload 정보를 화면에 요약 표시한다.
- source text 품질(`rich`, `medium`, `light`) 또는 `quality_badge`를 생성 전/후에 보여준다.
- material type 선택이 초안 생성에 어떤 영향을 주는지 명확히 한다.
- 저장 후 상세로 이동하는 기존 흐름을 유지한다.
- 관련 view/form 테스트를 추가한다.

## 금지 사항

```text
새 프론트엔드 프레임워크 도입 금지
대규모 디자인 리뉴얼 금지
기존 source query parameter 깨기 금지
```

## 검증

```bash
python manage.py check
python manage.py test study.tests
```

가능하면 수동 확인:

```text
/study/create/?source_type=manual&title=Test
/study/create/?source_type=clip&clip_id=<owned_clip_id>
```

## 완료 보고 형식

```text
[Step 04 - Material Create Flow Upgrade 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. 화면 변경 내용
4. 실행한 명령어
5. 검증 결과
6. 수동 확인 여부
7. 남은 이슈
```

