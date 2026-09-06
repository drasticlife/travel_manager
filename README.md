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
| `GOOGLE_MAPS_API_KEY` | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → Places API (New) 활성화 | `verify` 실행 시 |
| `TODOIST_TOKEN` | Todoist → 설정 → 연동 → API 토큰 | `export.py todoist` 실행 시 |
| `TODOIST_PROJECT_ID` | 프로젝트 URL 끝 문자열 | 위와 동일 |

Places API Text Search는 **월 5,000콜 무료**다. 여행 1건에 장소 100~300개면 무료 범위 안이다.

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

# 2. 검증 — 과금 단계라 몰아서 한 번
python trip.py verify

# 3. 확인 — 내 지도에 저장할 링크
python export.py maps-links
```

`maps-links` 출력에서 `[확인]` 표시가 붙은 것은 **눈으로 봐야 한다.**
장소가 여러 개 검색되었거나 이름이 안 맞은 경우다.

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
| 폰에서 수집 | PC의 Claude Code에서만. 텔레그램 봇은 다음 사이클 |
| 최적 동선·맛집 추천 | 다음 사이클. 이 DB가 입력이 된다 |
| GitHub Pages 배포 | 다음 사이클 |
| 사진/스크린샷 입력 | 범위 밖 |

## 문서

- 설계: `docs/superpowers/specs/2026-09-06-travel-manager-design.md`
- 계획: `docs/superpowers/plans/2026-09-06-collect-to-db-core.md`
