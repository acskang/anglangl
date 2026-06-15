# Step 05 - Library and Explore IA

너는 `anglangl`의 학습 자료 라이브러리와 공개 탐색 화면을 정리하는 Django 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

`/study/`와 `/study/explore/`를 생성/보관/탐색/재사용 정보구조에 맞춰 개선한다.

## 주요 작업

- `docs/03_information_architecture_design.md`와 `docs/06_share_reuse_design.md`를 읽는다.
- `StudyMaterialListView`, `StudyMaterialExploreListView`, `templates/study/material_list.html`을 확인한다.
- 필터와 정렬을 정리한다.
  - ownership
  - material_type
  - purpose
  - difficulty
  - source_type
  - visibility
- 공개 탐색에서는 작성자, source 요약, quality badge, clone action을 명확히 보여준다.
- 내 라이브러리에서는 내가 만든 자료와 가져온 자료가 구분되어야 한다.
- pagination과 기존 query parameter를 보존한다.
- 관련 테스트를 추가한다.

## 금지 사항

```text
자료 상세/복제 권한 변경 금지
검색 엔진 또는 외부 dependency 도입 금지
대규모 CSS 리뉴얼 금지
```

## 검증

```bash
python manage.py check
python manage.py test study.tests
```

## 완료 보고 형식

```text
[Step 05 - Library and Explore IA 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. 필터/정렬 변경 내용
4. 실행한 명령어
5. 검증 결과
6. 남은 이슈
```

