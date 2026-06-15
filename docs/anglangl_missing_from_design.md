# anglangl Codex 작업 이력 중 설계서 미반영 항목 추출 보고서

## 0. 기준

- 비교 대상 설계서: `anglangl-docs.zip`의 `docs/` 문서 패키지
- 비교 대상 작업 이력: `anglangl-codex-history.zip`의 `codex-history/*.md` 177개 문서
- 판단 기준: 설계서의 큰 방향에는 일부 포함되어 있더라도, 작업 이력에 구현·운영·장애 대응·세부 UX·외부 연동으로 기록되어 있으나 설계서에 명시적 설계 항목으로 정리되지 않은 내용을 별도 추출했다.

## 1. 요약 결론

현재 설계서는 `StudyMaterial` 중심의 학습 자료 생성·저장·공유·복제 플랫폼 관점으로 잘 정리되어 있다. 그러나 Codex 작업 이력에는 설계서보다 훨씬 많은 실제 구현 세부사항이 남아 있다.

가장 크게 누락된 영역은 다음이다.

1. YouTube/clipmaster 기반 영상 추가·저장·클립 생성 UX
2. YouTube/드라마 공통 클립 추출 백엔드
3. 자막 추출, Whisper fallback, 0.1초 단위 클립 타임코드
4. Player의 영화/드라마 검색, PiP, fullscreen, 자막 제어
5. IMDb 드라마 저장·재생·정렬·삭제·드래그앤드롭 카드 UX
6. 별도 Movies 앱과 KOBIS/YTS 기반 영화 검색·재생 기능
7. 인증 모달, ThePeach/peach 연동, auth middleware DB write 최적화
8. 운영 배포, Gunicorn/Celery/PostgreSQL/SQLite 장애 대응 이력
9. 썸네일 저장 경로 통합, 썸네일 복사/추출/앨범 기능
10. live 서버에서 발생한 500/404/CSRF/마이그레이션 불일치 장애 대응

즉, 설계서는 `StudyMaterial 중심의 미래 구조`를 잘 설명하지만, 실제 서비스에 이미 축적된 `미디어 플레이어·YouTube 편집기·IMDb/Movies·운영 인프라` 세부 설계는 별도 문서로 보강해야 한다.

---

## 2. 설계서에 없는 주요 기능/구현 항목

### 2.1 YouTube / clipmaster 기반 영상 관리 기능

작업 이력에는 기존 anglangl YouTube 구현을 제거하고, 별도 `yt-clipmaster`의 기능을 anglangl로 이식한 내용이 많다. 그러나 설계서에는 이를 독립된 하위 시스템으로 충분히 설명하지 않는다.

미반영 항목:

- 기존 anglangl YouTube 화면/메뉴/데이터/파일 제거 계획과 실제 제거 이력
- `Youtube` 메인 메뉴 신설
- `영상 추가`, `저장된 영상`, `클립 생성`, `클립 업로드`, `업로드 배치`, `이미지 등록`, `블로그편집` 메뉴 구조
- `/videos/create/youtube/` YouTube 추가 화면
- `/videos/linked/` 저장된 영상 화면
- `/videos/api/fetch-info/` preview loading API
- YouTube metadata fetch 실패 시 oEmbed fallback title/author/thumbnail 사용
- YouTube 저장 영상 설명(description) 저장/표시/자동 보강
- 저장된 영상 화면을 카드형 UI로 변경
- `LINKED VIDEOS` → `저장된 영상` 명칭 변경
- 저장된 영상 카드에서 Failed/Open/Reload 버튼 제거 또는 재배치
- 저장된 영상 상단 toolbar의 source dropdown, Apply, Add Video 정렬
- `블로그편집` 화면의 역할: 영상 metadata 편집, URL/description 관리, 썸네일 추출

설계서 반영 권고:

- `YouTube Source Management Design` 문서 추가
- `yt-clipmaster` 이식 근거와 anglangl 내 역할 정리
- YouTube 영상은 단순 source asset이 아니라 `저장된 영상 관리 + 클립 제작 + 블로그 편집 + 썸네일 추출`까지 포함하는 별도 서브시스템으로 정리

---

### 2.2 클립 생성 UI와 0.1초 타임코드 UX

설계서에는 Clip이 source asset으로 등장하지만, 작업 이력에 있는 매우 구체적인 clip extraction UX가 빠져 있다.

미반영 항목:

- YouTube 클립 추출 화면에서 우클릭으로 현재 시간을 `클립 시작 시간` 또는 `클립 종료 시간`에 저장
- player overlay가 PiP/fullscreen/native scrubber를 방해했던 문제와 복구
- YouTube 상단 기본 버튼 공유/나중에 보기/More videos/브랜드 영역 mask 처리
- 시작/종료 시간 입력란 옆 원형 버튼 추가
- 시작/종료 시간 입력란을 `↓ [시간] ↑` 구조로 변경
- `↓`: 현재 player 시간을 입력란으로 가져오기
- `↑`: 입력된 시간으로 player 이동
- 시작/종료/선택 구간을 100ms, 최종적으로 0.1초 단위로 처리
- `hh:mm:ss:s` 형식 사용
- 좌우 화살표 1회당 0.1초 이동
- `clips.timecode` 유틸리티 도입/수정
- `Clip` 모델의 subsecond time 저장을 위한 migration
- 클립 편집 화면에서 `클립 추출 시간` 표시

설계서 반영 권고:

- `Clip Timecode and Editing UX Design` 문서 추가
- 타임코드 표준 형식, 저장 precision, 사용자 입력 규칙, JS 조작 규칙 명시
- 향후 StudyMaterial source snapshot에 clip start/end를 저장할 때 0.1초 precision을 유지하도록 정책화

---

### 2.3 YouTube/드라마 공통 클립 추출 백엔드

작업 이력에는 YouTube와 드라마 HLS의 clip extraction 경로가 공통화되어 있다. 설계서에는 media pipeline 수준에서만 언급되고, 실제 추출 전략은 없다.

미반영 항목:

- YouTube clip extraction을 `yt_dlp.download_ranges` 기반으로 변경
- 기존 `--js-runtimes` 옵션 호환 문제로 실패했던 이력
- YouTube와 드라마가 같은 공통 클립 생성 UI를 사용
- 드라마 HLS source를 `MasterVideo` bridge record로 연결
- 드라마 bridge record는 일반 비디오 라이브러리에서 제외
- 드라마 HLS 원격 스트림은 ffmpeg 기반으로 구간 추출
- HLS manifest/variant playlist 403 대응
- prepared manifest에 절대 segment URL이 들어간 경우 ffmpeg protocol whitelist 필요
- `-protocol_whitelist file,crypto,data,http,https,tcp,tls` 적용
- YouTube clip extraction 회귀 없이 drama path만 수정하는 원칙

설계서 반영 권고:

- `Clip Extraction Backend Design` 문서 추가
- source별 추출 엔진 분리:
  - YouTube: yt-dlp download_ranges
  - local/upload: ffmpeg local file
  - drama/HLS: ffmpeg remote stream + protocol whitelist
- BackgroundJob 상태와 실패 원인 표준화

---

### 2.4 자막 추출 / Whisper fallback

설계서에는 subtitle/transcript를 source quality로 다루지만, 실제 자막 추출 구현 방식이 빠져 있다.

미반영 항목:

- 클립 편집 화면에서 자막 추출 버튼 제공
- `Whisper -> YouTube captions fallback` 순서
- AJAX로 subtitle extraction 결과를 같은 편집 화면 textarea에 반영
- `clips/services/whisper.py` 도입
- YouTube captions fallback
- subtitle body가 StudyMaterial draft 생성에 사용됨
- dramaNlearn subtitle track URL fetch 실패 시 metadata fallback 사용

설계서 반영 권고:

- `Subtitle Extraction Design` 문서 추가
- source별 subtitle provider 순서:
  - existing subtitle body
  - Whisper transcription
  - YouTube captions
  - remote subtitle track
  - metadata-only fallback
- 자막 추출 실패 시 UI와 BackgroundJob 기록 정책 명시

---

### 2.5 Player 기능: 영화/드라마 검색, PiP, 자막, fullscreen

설계서는 player를 source entry 정도로 다루지만, 작업 이력에는 player 자체가 중요한 기능으로 구현되어 있다.

미반영 항목:

- Player 화면의 `영화보기` 탭
- 영화 검색 시 YTS 검색 로직
- 한국어 영화 제목을 영어 후보로 변환한 뒤 YTS 검색
- 후보 title list, thumbnail, click-to-play UX
- movie player 클릭 시 외부 page/tab이 열리지 않도록 차단
- 영화/드라마 통합 검색 모달을 `영상찾기`로 변경
- `영화버튼` / `드라마버튼` 라디오 전환
- 드라마 검색: `ytstv.hair` 검색/상세 기반
- 외부 페이지로 이동하지 않고 modal 안에 썸네일/URL 리스트 표시
- 드라마 썸네일 클릭 시 바로 재생하지 않고 series/episode 선택 리스트 표시
- Player PiP 기능
- 드라마 player PiP 지원
- PiP 화면에도 자막 표시
- fullscreen 시 자막 유지
- player 시작 시 자막 버튼 label 초기 상태 보정
- PiP player에서 space key로 재생/정지
- Player에서 현재 화면 이미지 저장 버튼

설계서 반영 권고:

- `Player UX and Playback Design` 문서 추가
- 영화/드라마/player는 StudyMaterial source 진입점 이전에 독립적인 media consumption layer로 정의
- PiP/fullscreen/subtitle 상태 관리 정책 명시

---

### 2.6 IMDb 드라마 관리 기능

설계서에는 DramaVideo/IMDb가 source asset으로만 간단히 언급되어 있지만, 작업 이력에는 IMDb 드라마 저장·캐시·재생·정렬 기능이 매우 크게 구현되어 있다.

미반영 항목:

- `Drama > IMDB` 메뉴 추가
- IMDb ID/제목 기반 드라마 검색 화면
- 최초 검색 시 외부 metadata 조회, 이후 DB cache 우선 사용
- 선택한 드라마 정보 저장:
  - thumbnail
  - title
  - season
  - episode
  - episode title
  - playback URL
- `ImdbDramaSeriesCache` / `ImdbDramaEpisodeCache` 저장 구조
- Player 화면에서 저장된 IMDb 드라마 선택 후 바로 재생
- 저장된 URL이 있는 IMDb 드라마만 Player에서 선택 가능하도록 제한
- IMDb 저장 시리즈를 `/dramaNlearn/` 홈에 노출
- 기존 drama card 목록에 IMDb 카드 통합
- 필터: 전체 / 재생가능 / 오류
- 정렬: 최신순 / 오래된순 / 조회순 / 최근 재생
- `last_played_at` 필드 추가
- IMDb browser에서 저장된 드라마 카드 표시
- 4열 grid UI
- 삭제 버튼
- 표시하지 말아야 할 내부 데이터: IMDb ID, DB badge 등
- drag-and-drop 수동 순서 변경
- `manual_order` 저장
- `열기` 버튼 클릭 시 Player IMDb tab의 episode selection modal 자동 open
- home card와 IMDb card의 delete 권한/동작 분리

설계서 반영 권고:

- `IMDb Drama Cache and Library Design` 문서 추가
- IMDb cache와 dramaNlearn.Video의 차이 명확화
- IMDb 저장 항목을 StudyMaterial source asset으로 사용할 때 필요한 resolver 규칙 추가

---

### 2.7 Movies 앱 / KOBIS / YTS 기반 영화 기능

설계서는 `Movie`를 source asset으로만 다룬다. 하지만 작업 이력에는 별도의 `movies` 앱 구현이 있다.

미반영 항목:

- `Movies` main menu 추가
- 기존 `/home/cskang/ganzskang/_deploy/movies`와 `https://movies.thesysm.com` 기능 분석 및 이식
- `/movies/search/`
- `/movies/api/search/`
- `/movies/watch/<tmdb_id>/`
- KOBIS API key를 production env에 설정
- `/movies/api/translate-title/?title=기생충` → `PARASITE` 변환 확인
- `movies/services/title_ko2en.py`
- TMDB/YTS/embedded movie player 계열 연동 추정

설계서 반영 권고:

- `Movies App Design` 문서 추가
- 기존 Player 내부 movie search와 새 Movies 앱의 관계 정리
- KOBIS/TMDB/YTS provider 계층 분리
- API key는 문서에 값 없이 변수명과 배포 방식만 기록

---

### 2.8 인증 / ThePeach / 모달 로그인 UX

설계서에는 인증 원칙은 있으나, 실제 구현된 인증 UX와 외부 인증 연동 세부사항은 빠져 있다.

미반영 항목:

- `thepeach.thesysm.com` 계열 URL을 `peach.thesysm.com`으로 변경
- 로그인되지 않은 상태에서 보호 화면 접근 시 page형 로그인 대신 modal login 사용
- 로그인/로그아웃/회원가입을 모두 modal로 제공
- 사용자 노출 UI에서 `ThePeach`, `peach` 등 외부 인증 시스템 식별자 제거
- 다크 테마에 맞춘 auth modal UI
- `/auth/login/`, `/auth/signup/` 직접 접근 시에도 modal이 열린 상태로 공통 layout 표시
- navbar의 Login / Sign up / Logout이 modal trigger/confirm 흐름으로 변경
- 표시 이름이 없으면 이메일 전체 대신 `@` 앞부분 표시
- `thumbnail-proxy` 요청마다 auth middleware가 DB write를 유발하던 구조 분석
- 동일 사용자/동일 profile이면 `auth_user` update와 `django_session` 재기록 생략

설계서 반영 권고:

- `Authentication and Session UX Design` 문서 추가
- 외부 인증 provider 이름을 사용자 화면에서 숨기는 정책 명시
- thumbnail/static/proxy류 요청에서 session DB write를 피하는 성능 정책 명시

---

### 2.9 썸네일 관리 / 복사 / 추출 / 앨범

설계서에는 thumbnail이 source payload 수준으로 언급되지만, 실제 구현된 썸네일 기능이 빠져 있다.

미반영 항목:

- 새 비디오/클립 thumbnail 파일 저장 경로를 `media/thumbnails/...` 아래로 통일
- 기존 `video_thumbs`, `clip_thumbs`, `clips/thumbnails` 경로를 새 경로로 옮기는 management command
- 저장된 영상 thumbnail card UX
- `영상추가` 화면 preview card에서 `썸네일 복사` 버튼
- URL 복사가 아니라 `fetch -> blob -> canvas -> ClipboardItem(image/png)` 방식으로 이미지 자체 복사
- `블로그편집` 화면의 `썸네일 이미지 추출` 섹션
- YouTube player를 보며 특정 시점으로 이동 후 현재 장면을 thumbnail로 저장
- 저장 전 확인 modal
- modal에 영상 제목, thumbnail preview, canvas size, filename 수정, description 입력 제공
- 썸네일 이미지 앨범 화면

설계서 반영 권고:

- `Thumbnail Asset Design` 문서 추가
- thumbnail storage path, migration, proxy, copy, extraction, album을 하나의 asset pipeline으로 정리

---

### 2.10 운영/배포/장애 대응 이력

설계서에는 rollout strategy가 있지만, 실제 작업 이력에 있는 운영 장애와 해결 방식이 충분히 정리되어 있지 않다.

미반영 항목:

- GitHub backup branch 생성 후 구현 시작
- `backup-20260321-pre-study-material` 브랜치, pre-implementation snapshot commit 생성
- local helper scripts와 PostgreSQL regression script
- 실제 local PostgreSQL DB 이름이 `listening_clips`였던 점
- PostgreSQL service/cluster 확인, port 5432 listener 확인
- SQLite와 PostgreSQL을 함께 쓰는 검증 경로
- production Gunicorn restart/reload 필요 사례
- 배포된 Gunicorn runtime과 disk Django file 불일치로 인한 문제 설명
- live SQLite DB에 migration이 적용되지 않아 500 발생한 사례
- Celery worker 자동 기동 및 systemd 서비스 구성
- Celery import error `_create_chord_error_with_cause`와 버전 정렬
- `QUEUED 0%` job이 worker 미기동 때문에 처리되지 않던 사례
- URL extraction add/refresh/retry/cancel/job history UX
- health endpoint 확인 패턴
- 다른 서비스 `erp`, `address`, `build`의 500 오류 원인 분석 이력
- CSRF 403 수정 이력

설계서 반영 권고:

- `Operations Runbook` 문서 추가
- DB/migration/gunicorn/celery/healthcheck/troubleshooting 절차 문서화
- 운영 secret 값은 절대 문서에 기록하지 말고 변수명과 설정 위치만 기록

---

### 2.11 메뉴/정보구조 실제 변경 이력

설계서의 목표 IA보다 작업 이력의 실제 메뉴 변화가 더 복잡하다.

미반영 항목:

- `Materials` main menu 추가, Library/Explore 하위 배치
- `dramaNlearn` main menu를 `Drama`로 rename
- `Drama` 하위 `드라마보기`, `드라마URL생성`, `IMDB`
- `Youtube` main menu와 다수 submenu
- `Movies` main menu
- `/videos/` 전체 `VIDEOS` 집계 화면 제거, dashboard redirect
- `/clips/`, image album 등 일부 화면 삭제 또는 숨김 처리
- `Admin > 자막클립생성`으로 clip create 이동
- global alert/log banner 제거

설계서 반영 권고:

- `03_information_architecture_design.md` 보강
- 현재 실제 navbar 구조와 제거/숨김 화면을 표로 정리
- 사용자가 접근 가능한 URL과 내부/legacy URL을 분리

---

## 3. 설계서에는 일부 언급되지만 세부가 부족한 항목

### 3.1 DramaNlearn 비동기 상태 UX

설계서에는 BackgroundJob과 Celery 흐름이 있지만, 실제 구현 세부가 부족하다.

추가할 세부:

- URL add/refresh/retry/cancel 공통 enqueue helper
- job history page
- clear operator-facing error messages
- failed row retry
- queued job cancel
- player에서 job history direct link
- URL 관리 화면 auto refresh/polling

### 3.2 StudyMaterial 생성 품질 개선

설계서의 Template Registry 방향은 좋지만, 작업 이력상 이미 구현된 deterministic draft 품질 개선 세부가 빠져 있다.

추가할 세부:

- source text 기반 shadowing script
- expression summary
- learning note
- source text가 없으면 metadata-only draft
- create UI에서 source text backed 여부 표시
- library title sorting
- visibility/ownership/quality/reuse badge

### 3.3 Dashboard

설계서에는 dashboard가 언급되지만 실제 구현 항목이 더 구체적이다.

추가할 세부:

- study-material count KPI
- recent saved materials
- clips/videos/jobs와 함께 표시
- BackgroundJob 상태 통합

---

## 4. 설계서 보강 문서 제안

현재 `docs/00~10` 구조를 유지한다면, 아래 문서를 추가하는 것이 좋다.

```text
11_youtube_clipmaster_design.md
12_clip_timecode_and_extraction_design.md
13_subtitle_extraction_design.md
14_player_playback_design.md
15_imdb_drama_cache_design.md
16_movies_app_design.md
17_thumbnail_asset_design.md
18_auth_session_design.md
19_operations_runbook.md
20_current_nav_and_legacy_url_inventory.md
```

또는 기존 문서를 보강한다면 다음처럼 배치한다.

| 보강 대상 | 추가할 내용 |
|---|---|
| `03_information_architecture_design.md` | 실제 navbar, Youtube/Drama/Movies/Admin 메뉴, 제거된 화면 |
| `05_media_source_pipeline_design.md` | YouTube/Drama clip extraction, yt-dlp, ffmpeg, HLS, subtitle |
| `07_internal_api_mcp_design.md` | Movies/IMDb/thumbnail 관련 내부 API가 있다면 추가 |
| `08_migration_and_rollout_strategy.md` | Gunicorn/Celery/DB/migration/healthcheck runbook |
| `09_risk_and_test_plan.md` | clip extraction 회귀, auth DB write, thumbnail proxy, IMDb cache 테스트 |

---

## 5. 우선 반영 순서

설계서에 지금 바로 반영할 우선순위는 다음이다.

1. `YouTube/clipmaster` 설계
2. `Clip extraction + timecode` 설계
3. `IMDb drama cache/player` 설계
4. `Movies app` 설계
5. `Thumbnail asset pipeline` 설계
6. `Auth/session modal` 설계
7. `Operations runbook`

이 순서가 좋은 이유는, 현재 StudyMaterial 설계는 이미 어느 정도 정리되어 있지만 실제 사용자가 많이 만지는 화면과 운영 리스크는 위 영역에 더 많이 몰려 있기 때문이다.

---

## 6. 최종 판단

현재 설계서는 `anglangl의 미래 중심축`인 StudyMaterial 플랫폼을 잘 정리했다. 그러나 Codex 작업 이력 기준 실제 서비스는 다음 4개의 큰 하위 시스템을 이미 가지고 있다.

```text
1. StudyMaterial 학습 자료 시스템
2. YouTube/clipmaster 영상·클립 편집 시스템
3. Drama/IMDb/Player 재생 시스템
4. Movies/KOBIS/YTS 영화 검색·재생 시스템
```

현재 설계서에는 1번은 잘 정리되어 있으나, 2~4번은 source asset 수준으로 축약되어 있다. 따라서 다음 문서화 작업은 `StudyMaterial`을 더 파는 것이 아니라, 실제 구현된 미디어 하위 시스템을 설계서 수준으로 끌어올리는 것이어야 한다.
