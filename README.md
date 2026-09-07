# travel manager

여행 자료를 검증된 SQLite DB로 쌓고, 구글지도 확인 링크와 Todoist 체크리스트로 꺼내 쓰는 CLI.

수집한 유튜브·블로그 자료에서 장소를 뽑되, **좌표와 구글 링크는 LLM이 아니라 Places API가 채운다.**
덕분에 "AI가 알려준 주소로 갔더니 다른 가게" 가 구조적으로 불가능하다.

## 설치

```bash
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 키를 채운다.

| 키 | 발급처 | 필요 시점 |
| --- | --- | --- |
| `TODOIST_TOKEN` | Todoist → 설정 → 연동 → 개발자 → API 토큰 | `export.py todoist` |
| `TODOIST_PROJECT_ID` | **`python export.py todoist-projects` 로 조회** | 위와 동일 |
| `GOOGLE_MAPS_API_KEY` | 선택 — 아래 참조 | `trip.py verify` (안 써도 됨) |

**`TODOIST_PROJECT_ID`는 브라우저 URL에서 못 가져온다.** REST v2가 쓰는 ID는
`2203306141` 같은 숫자인데, URL의 `2026-6hR986mmJqCrxHc4`는 슬러그라 API가 받지 않는다.
토큰만 넣고 아래를 실행하면 숫자 ID가 나온다.

```bash
python export.py todoist-projects
```

### Google Places API는 선택이다

Places API Text Search는 월 5,000콜 무료지만, **무료 한도만 쓸 거라도 구글 클라우드에
결제 수단 등록이 필수다.** 2025년 3월에 $200 공용 크레딧이 SKU별 무료 한도로 바뀌면서
카드 없이는 키 발급 자체가 안 된다.

카드를 등록하지 않아도 **`/trip lookup`(Claude 웹 검색)으로 주소를 채울 수 있다.**
기본 경로는 이쪽이다. 차이는 이렇다.

| | Claude 검색 (기본) | Places API (선택) |
| --- | --- | --- |
| 결제 등록 | 불필요 | **필수** |
| 주소 | ✅ | ✅ |
| 좌표·`place_id` | ❌ NULL로 남음 | ✅ |
| 링크 | 주소 검색 링크 | `place_id` 정확 링크 |
| 신뢰 근거 | 근거 URL 2개 이상 교차확인 | 구글 응답 |

좌표는 다음 사이클(동선 최적화)에서나 필요하다. 지금은 NULL이어도 무해하다.

## 첫 실행 — 이미 쌓아둔 구글지도 목록 가져오기

구글지도 저장 목록은 API로 읽을 수 없다(JS 렌더링). Takeout으로 내보낸다.

1. [takeout.google.com](https://takeout.google.com) → **전체 선택 해제**
2. **Saved**(저장 목록) + **Maps (내 장소)** 체크 → zip 다운로드
3. 압축을 풀면 `Takeout/Saved/<목록명>.csv`

```bash
python trip.py import-takeout "Takeout/Saved/'26 후쿠오카.csv"
```

CSV에는 좌표가 없다. 다음 단계가 채운다.

## 일상 사용

```bash
# 1. 수집 — Claude Code 안에서
/trip add https://youtu.be/xxxxx
/trip add 이치란 라멘 나카스점을 3일차 점심에 넣어줘

# 2. 주소 채우기 — Claude가 검색해서 근거 URL과 함께 저장
/trip lookup

# 3. 확인 — 내 지도에 저장할 링크
python export.py maps-links
```

`maps-links` 출력에서 `[확인]` 표시가 붙은 것은 **눈으로 봐야 한다.**
근거가 한 군데서만 나왔거나 주소를 못 찾은 경우다.

Places API 키를 넣었다면 2번 대신 `python trip.py verify`를 쓸 수 있다. 둘은 배타적이지 않다 —
`verify`로 처리하고 남은 것을 `/trip lookup`으로 메워도 된다.

링크를 열어 맞는 가게면 구글지도에서 "저장" → `'26 후쿠오카` 목록에 넣고,
돌아와서 처리 완료를 기록한다.

```bash
python trip.py mark-saved 12 15 17
```

## 조회

```bash
python trip.py list                      # 전체
python trip.py list --category 맛집
python trip.py list --status ambiguous   # 확인 필요한 것만
python trip.py plan --day 3
python trip.py pending                   # 아직 주소 없는 것 (JSON)
```

주소를 어디서 가져왔는지는 `evidence_urls`에 남아 있다. 나중에 "이 주소 어디서 봤지?"가 되면
추적할 수 있다.

```bash
python -c "import sqlite3,sys; sys.stdout.reconfigure(encoding='utf-8'); [print(r[0],'|',r[1]) for r in sqlite3.connect('data/trip.db').execute('SELECT name, evidence_urls FROM place WHERE evidence_urls IS NOT NULL')]"
```

## Todoist 푸시

```bash
python export.py todoist --dry-run   # 먼저 이걸로 확인
python export.py todoist             # 실제 푸시
```

아내와 공유 중인 프로젝트에 들어가므로 `--dry-run`을 먼저 보는 습관을 들인다.
이미 푸시된 항목은 `todoist_task_id`로 걸러져 **중복 생성되지 않는다.**

## 테스트

```bash
python test_trip.py
```

프레임워크 없음. `assert` 기반 단일 파일. 네트워크를 타지 않는다.

## 지금 안 되는 것

| | 이유 |
| --- | --- |
| 구글지도 목록에 자동 저장 | 공식 API가 없다 ([기능 요청](https://issuetracker.google.com/issues/453378725) 미구현). 링크를 만들어주면 사람이 클릭한다 |
| 좌표 확보 | 웹 검색으로는 안 나온다. Places API 키를 넣거나 다음 사이클에서 해결 |
| 폰에서 수집 | PC의 Claude Code에서만. 텔레그램 봇은 다음 사이클 |
| 최적 동선·맛집 추천 | 다음 사이클. 이 DB가 입력이 된다 |
| GitHub Pages 배포 | 다음 사이클 |
| 사진/스크린샷 입력 | 범위 밖 |

## 문서

- 설계: `docs/superpowers/specs/2026-09-06-travel-manager-design.md`
- 계획: `docs/superpowers/plans/2026-09-06-collect-to-db-core.md`
