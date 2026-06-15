# Step 07 - Media to Material Pipeline

너는 `anglangl`의 미디어 소스에서 학습 자료 생성으로 이어지는 흐름을 개선하는 Django 개발자다.

이번 단계만 수행하고 완료 후 멈춘다.

## 목표

MasterVideo, Clip, DramaVideo, Movie 화면에서 `학습 자료 만들기` 진입을 일관되게 제공하고 source resolver 품질을 개선한다.

## 주요 작업

- `docs/05_media_source_pipeline_design.md`를 읽는다.
- `videos/views.py`, `clips/views.py`, `dramaNlearn/views.py`, `movies/views.py`와 관련 템플릿을 확인한다.
- 각 detail/player 화면에서 `/study/create/`로 이어지는 링크가 있는지 확인한다.
- 없는 곳에는 기존 UI 톤에 맞춰 추가한다.
- `resolve_study_source()`가 각 source type에서 title, URL, source_text_kind를 안정적으로 채우는지 보강한다.
- source text가 없을 때 사용자에게 후편집 필요 상태가 보이게 한다.
- 관련 테스트를 추가한다.

## 금지 사항

```text
ffmpeg/yt-dlp 처리 로직 변경 금지
미디어 파일 저장 경로 변경 금지
dramaNlearn 레거시 URL 대규모 변경 금지
```

## 검증

```bash
python manage.py check
python manage.py test study.tests clips.tests videos.tests
```

## 완료 보고 형식

```text
[Step 07 - Media to Material Pipeline 완료 보고]

1. 수행한 작업 요약
2. 생성/수정한 파일 목록
3. source별 생성 진입점
4. 실행한 명령어
5. 검증 결과
6. 남은 이슈
```

