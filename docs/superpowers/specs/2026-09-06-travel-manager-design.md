# travel manager — 수집→DB 코어 설계

- **작성일**: 2026-09-06
- **상태**: 설계 확정 (구현 계획 대기)
- **작업장**: `C:\GIT\travel manager` / `github.com/drasticlife/travel_manager` (private)
- **마감**: 2026-10-06 이내 (한 달)
- **적용 정책**: `AI_Project_Operations_Policy`, `AI_Project_Runbook_Framework`, `클로드-코드-실전-마스터가이드`, `실밸개발자`

---

## 0. 스코프

전체 프로젝트 목표 5개 중 **첫 번째 조각(수집→DB 코어)만** 이번 사이클 대상.

| # | 목표 | 이번 사이클 |
| :-- | :--- | :--- |
| 1 | 여행 일정·준비물·동선·자료 관리 | ✅ DB 스키마로 |
| 2 | 수집 자료를 SQL식 DB로 정리 | ✅ **핵심** |
| 3 | DB 기반 LLM 정보 제공 (최적동선·맛집·쇼핑주의) | ❌ 다음 사이클 |
| 4 | GitHub Pages 배포 | ❌ 다음 사이클 |
| 5 | Claude CLI 입력 → 구글지도·Todoist 반영 | ⚠️ **부분** — Todoist 푸시 ✅ / 구글지도는 링크 생성까지만 |

나머지 4개 서브프로젝트는 각각 별도 spec → plan → 구현 사이클을 가진다.

### 확정된 전제

| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 입력 형태 | URL / 텍스트 붙여넣기 / 자연어 대화 | 사용자 확정. 사진 OCR 제외 |
| 공동 편집 | **없음** — 사용자 단독 입력, 아내는 결과만 조회 | 사용자 확정 |
| DB 위치 | 로컬 SQLite + git 커밋 | 서버·인증·동시성 전부 제거 |
| 저장 엔티티 | place / itinerary / packing / source | 사용자 확정 |
| Todoist | 준비물·일정을 체크리스트로 | 사용자 확정 |
| 구글지도 | 시스템이 **검증된 링크 생성** → 사용자가 클릭해 "내 장소"에 수동 저장 | 사용자 확정 |

---

## 1. 아키텍처

### 1.1 핵심 원칙

> **LLM은 추출·분류만. 쓰기는 전부 결정론적 파이썬이.**

Claude가 스키마를 어기면 `trip.py`가 거부한다. 환각이 DB에 들어갈 경로가 없다.
`AI_Project_Operations_Policy` §2.4(조언 80% vs 강제 100%)를 스키마·CLI 층에서 실현한 것.

### 1.2 디렉토리

```
C:\GIT\travel manager\
├─ CLAUDE.md                  # 프로젝트 규약 (200줄 이하, 안티패턴 중심)
├─ .claude/commands/
│   └─ trip.md                # /trip 슬래시 커맨드 — 추출 규칙 + 출력 스키마
├─ schema.sql                 # DDL 단일 파일
├─ trip.py                    # CLI 엔트리 — 검증 + DB 쓰기
├─ youtube.py                 # scrap_agent.py에서 이식한 자막 추출 3함수
├─ places.py                  # Places API 조회 + place_id 검증
├─ export.py                  # Todoist / 지도링크 / JSON (읽기 전용)
├─ test_trip.py               # 단일 테스트 파일
├─ requirements.txt           # youtube-transcript-api 1줄
├─ .env.example               # GOOGLE_MAPS_API_KEY, TODOIST_TOKEN
├─ data/trip.db               # SQLite — git 커밋 대상
└─ docs/superpowers/specs/    # 이 문서
```

**코드·스키마 파일 7개** (`trip.md`, `schema.sql`, `trip.py`, `youtube.py`, `places.py`, `export.py`, `test_trip.py`).
나머지 3개(`CLAUDE.md`, `requirements.txt`, `.env.example`)는 설정·문서. 프레임워크·서버·봇 없음.

### 1.3 의존성

**외부 패키지 1개**: `youtube-transcript-api`

나머지는 전부 stdlib.

| 필요 | 모듈 |
| :--- | :--- |
| DB | `sqlite3` |
| CLI 파싱 | `argparse` |
| JSON | `json` |
| HTTP (Places / Todoist) | `urllib.request` |
| URL 인코딩 | `urllib.parse` |
| CSV (Takeout) | `csv` |
| 테스트 | `assert` |

`requests`·ORM·pydantic·pytest 미사용. 한 달 마감에 `pip install` 디버깅 시간을 쓰지 않는다.

### 1.4 컴포넌트 경계

| 컴포넌트 | 하는 일 | 안 하는 일 |
| :--- | :--- | :--- |
| `.claude/commands/trip.md` | URL/텍스트/자연어 → 정규화 JSON 1건 출력 | DB 접근 금지. 파일 쓰기 금지 |
| `trip.py` | stdin JSON 검증 → SQLite 쓰기. 조회 커맨드 | LLM 호출 안 함 |
| `youtube.py` | video id 추출, 자막 3단 폴백, 30초 병합 | DB 접근 안 함 |
| `places.py` | Places API 조회, 이름 대조, maps_url 생성 | DB 쓰기 안 함 (결과 반환만) |
| `export.py` | DB 읽기 → Todoist / 지도링크 / JSON | **`todoist_task_id` 외 어떤 컬럼도 쓰지 않는다** |

`export.py`의 유일한 쓰기는 푸시 성공 후 `todoist_task_id` 기록이다. 이것을 쓰지 않으면 재푸시가 태스크를 중복 생성하므로 읽기 전용을 유지할 수 없다. 그 외 컬럼에 대한 UPDATE/INSERT/DELETE는 금지한다.

경계 판정: `export.py`를 지워도 수집은 돌아간다. `trip.md`를 지워도 `trip.py`는 손으로 JSON을 넣어 쓸 수 있다.

### 1.5 외부 자산 재사용 — 유튜브 자막

`C:\GIT\Moons_Company\agents\scrap_agent.py`에 실전 검증된 3단 폴백이 있다.

```
1차: 수동 등록된 ko/en 자막
2차: 자막 목록 조회 → find_transcript(['ko','en'])
3차: en 자막 → ko 자동번역
+ merge_transcripts(): 30초 단위 병합으로 토큰 밀도 최적화
```

**이식 방식**: `extract_youtube_id` / `merge_transcripts` / `get_youtube_transcript` 3함수를 `youtube.py`로 **복사**(약 60줄). `async` 껍데기는 제거(내부가 동기).

**import하지 않는 이유**: 볼트 밖 다른 리포에 경로 의존이 생기고, 그쪽 변경이 여행 준비 중 이 도구를 깨뜨린다. 60줄 복사가 더 싸다.

---

## 2. 데이터 모델

### 2.1 설계 판단

1. **CHECK 제약으로 enum을 DB가 강제한다.** LLM이 카테고리를 `'밥집'`으로 지어내면 SQLite가 INSERT를 거부한다.
2. **`source`에 원문을 통째로 보존한다.** LLM 추출이 틀렸을 때 재처리 가능해야 한다. 볼트 원문 보존 원칙과 동일.
3. **장소–소스는 N:1로 단순화.** "여러 영상이 같은 집을 추천 = 진짜 맛집" 신호는 매력적이나 조인 테이블은 지금 불필요. 재등장 시 `note`에 덧붙인다.

### 2.2 `source`

```sql
CREATE TABLE IF NOT EXISTS source (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('youtube','web','text','chat','takeout')),
  url         TEXT,
  title       TEXT,
  raw_text    TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`raw_text`가 비면 INSERT 실패 — 원문 없는 수집을 막는다.

### 2.3 `place` (핵심)

```sql
CREATE TABLE IF NOT EXISTS place (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  name_verified   TEXT,
  category        TEXT NOT NULL CHECK (category IN
                    ('맛집','쇼핑','관광','숙소','이동','기타')),
  address         TEXT,
  lat             REAL,
  lng             REAL,
  place_id        TEXT UNIQUE,
  maps_url        TEXT,
  verify_status   TEXT NOT NULL DEFAULT 'pending'
                    CHECK (verify_status IN ('pending','matched','ambiguous','not_found')),
  verify_method   TEXT CHECK (verify_method IN ('claude_search','places_api','manual')),
  evidence_urls   TEXT,   -- 주소 근거 URL(줄바꿈 구분). 환각 사후 추적 수단
  saved_to_mymaps INTEGER NOT NULL DEFAULT 0 CHECK (saved_to_mymaps IN (0,1)),
  note            TEXT,
  source_id       INTEGER REFERENCES source(id),
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_place_verify   ON place(verify_status);
CREATE INDEX IF NOT EXISTS idx_place_category ON place(category);
```

`place_id UNIQUE`가 중복 방지를 담당한다. 여러 영상이 같은 집을 추천해도 Places API가 같은 `place_id`를 반환하므로 두 번 들어가지 않는다.

`verify_status`가 이번 설계의 핵심 컬럼. "링크 타고 들어가 확인" 대상이 여기서 나온다.

```sql
SELECT id, name, name_verified, maps_url FROM place
WHERE verify_status != 'matched' AND saved_to_mymaps = 0;
```

### 2.4 `itinerary`

```sql
CREATE TABLE IF NOT EXISTS itinerary (
  id              INTEGER PRIMARY KEY,
  day_no          INTEGER NOT NULL,
  date            TEXT,
  slot            TEXT NOT NULL CHECK (slot IN ('오전','점심','오후','저녁','밤')),
  seq             INTEGER NOT NULL DEFAULT 0,
  place_id        INTEGER REFERENCES place(id),
  memo            TEXT,
  todoist_task_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_itin_day ON itinerary(day_no, slot, seq);
```

`place_id` NULL 허용 — "3일차 오전: 이동만" 같은 항목이 존재한다.

### 2.5 `packing`

```sql
CREATE TABLE IF NOT EXISTS packing (
  id              INTEGER PRIMARY KEY,
  item            TEXT NOT NULL,
  category        TEXT NOT NULL DEFAULT '기타' CHECK (category IN
                    ('의류','전자','서류','약','세면','기타')),
  qty             INTEGER NOT NULL DEFAULT 1,
  owner           TEXT NOT NULL DEFAULT '공용' CHECK (owner IN ('나','아내','공용')),
  packed          INTEGER NOT NULL DEFAULT 0 CHECK (packed IN (0,1)),
  todoist_task_id TEXT
);
```

`owner`를 둔 이유: Todoist를 아내와 공유하므로 "누가 챙길 것"이 갈린다.

### 2.6 마이그레이션 없음

`schema.sql` 하나를 `CREATE TABLE IF NOT EXISTS`로 실행한다. 스키마 변경이 필요하면 DB를 지우고 Takeout + 원문에서 재구축한다. `source.raw_text`가 남아 있으므로 복구 가능하다.

---

## 3. 구글지도 연동

### 3.1 확인된 제약 (웹 검증 완료)

| 항목 | 가능 여부 | 근거 |
| :--- | :--- | :--- |
| 저장 목록에 API로 쓰기 | ❌ **불가** | 공식 API 없음. [Bulk Save 기능 요청](https://issuetracker.google.com/issues/453378725) 2025-10 등록, 미구현 |
| My Maps 쓰기 | ❌ 불가 | 공식 쓰기 API 없음 |
| 저장 목록 링크를 HTTP로 읽기 | ❌ 불가 | JS 렌더링. 실측 시 `"Google 지도"` 문자열만 반환 |
| **Takeout으로 목록 내보내기** | ✅ **가능** | `Takeout/Saved/<목록명>.csv` |
| place_id 조회 후 정확한 링크 생성 | ✅ 가능 | Places API Text Search |

실측: `https://maps.app.goo.gl/GdvdZnjrA7u2tLk86` → 302 → `...!11m2!2sJasp0p2q5O3Dy_wWQ6XR8w!3e3`.
이 ID는 프로젝트 노트의 `'26 후쿠오카` 저장 목록과 동일. 본문은 비어 있음(JS 벽).

### 3.2 Takeout 임포트 (부트스트랩)

```
takeout.google.com → 전체 선택 해제
→ "Saved"(저장 목록) + "Maps (내 장소)" 체크 → zip 다운로드
→ Takeout/Saved/'26 후쿠오카.csv
```

| CSV 컬럼 | 저장 위치 | 비고 |
| :--- | :--- | :--- |
| `Title` | `place.name` | Places API 조회 키 |
| `Note` | `place.note` | 내가 쓴 메모 — 원문 그대로 |
| `URL` | `source.url` (`kind='takeout'`) | 파싱하지 않고 보존만 |
| `Comment` | `source.raw_text`에 합류 | |

**좌표는 CSV에 없다.** `places.py`가 그 구멍을 메운다.
Takeout URL에서 좌표를 파싱할 수도 있으나 하지 않는다 — Places API 무료 한도가 충분한데 구글 URL 포맷 변경에 깨지는 파서를 유지할 이유가 없다.

**Takeout은 수동 1회 작업이므로 자동화하지 않는다.** 여행 준비 기간에 한두 번 실행하면 끝이라 자동화 코드가 회수되지 않는다.

### 3.3 검증 경로 — 2026-09-07 변경

> **변경 이유**: Places API는 무료 한도(월 5,000콜)만 쓰더라도 구글 클라우드에
> **결제 수단 등록이 필수**다. 2025년 3월에 $200 공용 크레딧이 SKU별 무료 한도로
> 바뀌면서 카드 없이는 키 발급 자체가 안 된다. 사용자가 카드 등록 대신
> Claude CLI 웹 검색으로 채우는 방식을 선택했다.

**실측 결과** — "이치란 라멘 나카스점"을 한국어·영어로 각각 검색:

| 항목 | 웹 검색으로 | 비고 |
| :--- | :--- | :--- |
| **주소** | ✅ 확보 | 두 독립 검색이 동일: `5-3-2 Nakasu, Hakata-ku, Fukuoka 810-0801` |
| `place_id` | ❌ 없음 | 검색 결과에 명시적으로 부재 |
| 좌표 | ❌ 없음 | 동일 |

**주소는 되고 place_id·좌표는 안 된다.** 원래 `place_id` 링크를 고집한 이유는
"이치란 나카스점"을 찾다가 "이치란 텐진점"이 확정되는 걸 막기 위해서였는데,
그 문제는 *이름으로* 검색해서 생긴 것이다. **정확한 일본 주소는 그 자체가 식별자**라
주소 기반 검색 링크는 한 곳으로 떨어진다.

원래 요구사항("내가 DB 확인 후 링크 타고 들어가서 다시 확인하고 내 지도에 저장")에서
**사람의 육안 확인이 최종 게이트**라는 점은 그대로다. API는 신뢰도를 올리는 장치였지
게이트가 아니었다.

#### 3.3.1 두 경로

| | Claude 검색 (기본) | Places API (선택) |
| :--- | :--- | :--- |
| 커맨드 | `trip.py pending` → `trip.py apply-lookup` | `trip.py verify` |
| 결제 등록 | 불필요 | **필수** |
| 주소 | ✅ | ✅ |
| 좌표·`place_id` | ❌ NULL 유지 | ✅ |
| 링크 | `maps_url_from_address()` | `maps_url(place_id)` |
| `verify_method` | `claude_search` | `places_api` |

두 경로는 배타적이지 않다. `verify`로 처리하고 남은 것을 `apply-lookup`으로 메울 수 있다.

#### 3.3.2 환각 차단선 — 기준은 바뀌었으나 원칙은 유지

> **Claude는 검색으로 retrieve 한 것만 쓴다. 기억으로 지어낸 것은 쓰지 않는다.**

`apply-lookup`의 검증 규칙:

| 규칙 | 코드 | 이유 |
| :--- | :--- | :--- |
| `lat`·`lng`·`place_id` 포함 시 거부 | E3 | 검색으로 안 나오는 값. 있으면 지어낸 것 |
| `evidence_urls` 없는 주소 거부 | E2 | 근거 없는 주소는 환각과 구분 불가 |
| 없는 `id` 거부 | E4 | — |
| **`verify_status`는 Claude가 쓰지 않음** | — | 판정을 LLM에 맡기면 자기 결과에 후한 점수를 준다 |

허용 필드는 `id` `address` `name_verified` `evidence_urls` **넷뿐**이다(화이트리스트).

좌표는 이 경로에서 **영구히 NULL**이다. 다음 사이클(동선 최적화) 시작 전에
Places API를 붙이거나 수동 입력이 필요하다. 지금은 무해하다.

#### 3.3.3 판정 규칙 — §3.4.1 대체

`places.judge_by_evidence(address, evidence_urls)`가 **고유 도메인 수**로 판정한다.

| 조건 | `verify_status` |
| :--- | :--- |
| 서로 다른 도메인 **2개 이상** | `matched` |
| 도메인 1개 (같은 사이트의 페이지 여러 개 포함) | `ambiguous` |
| 주소 없음 | `not_found` |

`www.` 접두사는 제거하고 비교하므로 `blog.com`과 `www.blog.com`은 같은 도메인이다.

`ambiguous`여도 `maps_url`은 만든다 — 사용자가 링크를 여는 것이 판정 절차의 일부다.

**Places API 경로의 판정은 §3.4.1이 그대로 유효하다.**

---

### 3.4 Places API 비용 통제 (선택 경로)

| 항목 | 값 |
| :--- | :--- |
| SKU | Text Search — Pro |
| 무료 한도 | **월 5,000 콜** |
| 여행 1건 예상 장소 수 | 100~300개 → 무료 범위 내 |
| 링크 형식 | `https://www.google.com/maps/place/?q=place_id:<PLACE_ID>` |
| **금지 필드** | field mask에 `rating`·`opening_hours`·`reviews`·`photos` **넣지 않는다** — Enterprise 등급으로 과금 상승 |

> 구글은 field mask에 포함된 **가장 높은 등급**으로 요청 전체를 과금한다. 필드 하나가 비용 등급을 올린다.

### 3.5 검증 상태와 사용자 행동

| `verify_status` | 의미 | 사용자 행동 |
| :--- | :--- | :--- |
| `pending` | 아직 조회 안 함 | `trip.py verify` 실행 |
| `matched` | 검색어와 반환 이름 일치 | 링크 타고 바로 내 장소 저장 |
| `ambiguous` | 결과는 있으나 이름 불일치 | **눈으로 확인 필요** |
| `not_found` | 결과 없음 | 수동 검색 |

`saved_to_mymaps`로 이미 저장한 곳을 다시 확인하지 않도록 추적한다.

#### 3.5.1 `matched` 판정 규칙 — Places API 경로 전용

> Claude 검색 경로의 판정은 **§3.3.3**을 따른다. 아래는 `trip.py verify`(Places API)에만 적용된다.

일본 장소는 한국어 표기·일본어 원표기·로마자가 섞이므로 **완전 일치를 요구하지 않는다.** 다음 순서로 판정한다.

```
1. 결과가 0건            → not_found
2. 결과가 2건 이상        → ambiguous  (1등만 취해 확정하지 않는다)
3. 결과가 1건일 때:
     정규화(공백·중점·괄호 제거, 소문자화) 후
     검색어와 반환 이름이 서로 부분문자열 관계이면  → matched
     아니면                                        → ambiguous
```

**결과가 여러 건이면 무조건 `ambiguous`다.** Places API의 1순위 결과를 자동 채택하면 "이치란 나카스점"을 찾다가 "이치란 텐진점"이 확정될 수 있다. 여행지에서 다른 지점 앞에 서 있는 것이 이 설계에서 막아야 할 최악의 실패다.

`ambiguous`여도 `maps_url`은 생성한다 — 사용자가 링크를 열어 확인하는 것이 판정 절차의 일부이기 때문이다.

---

## 4. 데이터 흐름과 LLM 계약

### 4.1 3단계 분리

```
1. 수집 (오프라인·무과금)
   /trip add <URL|텍스트|자연어>
   Claude: 읽기 → 추출 → JSON stdout
   trip.py: 검증 → 트랜잭션 INSERT → verify_status='pending'
        ↓
2. 검증 (네트워크·과금·배치)
   trip.py verify
   pending 장소만 Places API 조회
   → place_id·좌표·실제이름·maps_url 채움 → verify_status 갱신
        ↓
3. 출력 (읽기 전용)
   export.py maps-links   → 확인 대기 목록
   export.py todoist      → 체크리스트 푸시
   trip.py mark-saved <id> → 내 지도 저장 완료 표시
```

**1과 2를 나눈 이유**: `add`는 네트워크도 과금도 없어야 실패율이 낮다. 유튜브 10개를 던져놓고 나중에 `verify` 한 번으로 API를 몰아 쓴다. 검증이 실패해도 수집한 원문은 이미 DB에 안전하다.

### 4.2 LLM 출력 계약

`.claude/commands/trip.md`가 Claude에게 이 형식만 출력하도록 지시한다.

```json
{
  "source": {
    "kind": "youtube",
    "url": "https://youtu.be/xxx",
    "title": "후쿠오카 3박4일 먹방 코스",
    "raw_text": "<자막 또는 본문 원문 전체>"
  },
  "places": [
    {
      "name": "이치란 라멘 나카스점",
      "category": "맛집",
      "note": "24시간 영업, 돈코츠, 영상 08:20에서 추천"
    }
  ],
  "itinerary": [
    { "day_no": 3, "slot": "점심", "place_name": "이치란 라멘 나카스점", "memo": "" }
  ],
  "packing": [
    { "item": "우산", "category": "기타", "owner": "공용", "qty": 1 }
  ]
}
```

참조는 정수 id가 아니라 `place_name`으로 한다. Claude는 DB id를 알 수 없다. `trip.py`가 이름을 id로 해석한다.
`places` 외 배열은 비어도 된다.

### 4.3 LLM 금지 필드 — 환각 차단선

JSON에 포함되면 `trip.py`가 즉시 거부한다.

| 금지 필드 | 이유 |
| :--- | :--- |
| `place_id` | 구글만 발급. 지어내면 잘못된 장소가 확정됨 |
| `lat` / `lng` | **환각 좌표가 들어가면 동선 최적화가 통째로 망가짐** |
| `address` | Places API가 채움 |
| `verify_status` | 검증받을 대상이 스스로 검증 결과를 쓸 수 없음 |
| `maps_url` | place_id에서 파생 |
| `id` / `created_at` | DB 소관 |

LLM이 채우는 것은 **이름·분류·메모·원문**뿐이다. 사실(fact)은 API가, 판단(judgment)만 LLM이 한다.

### 4.4 CLI 커맨드

| 커맨드 | 입력 | 하는 일 | 네트워크 |
| :--- | :--- | :--- | :--- |
| `trip.py add` | stdin JSON | 검증 → 트랜잭션 INSERT | ❌ |
| `trip.py import-takeout <csv>` | CSV 경로 | Takeout 목록 → place 시드 | ❌ |
| `trip.py pending [--limit N]` | — | 주소 없는 장소 목록을 JSON 출력. 기본값 20 | ❌ |
| `trip.py apply-lookup` | stdin JSON | Claude 조사 결과 저장 (§3.3.2 검증) | ❌ |
| `trip.py verify [--limit N]` | — | pending 장소 Places API 조회. **`--limit` 기본값 50** | ✅ 과금 |
| `trip.py list [--category] [--status]` | — | 장소 조회 | ❌ |
| `trip.py plan [--day N]` | — | 일정 슬롯 조회 | ❌ |
| `trip.py mark-saved <id...>` | id 목록 | 내 지도 저장 완료 표시 | ❌ |
| `export.py maps-links` | — | 확인 대기 목록 출력 | ❌ |
| `export.py todoist-projects` | — | 숫자 `project_id` 조회 (URL 슬러그로는 불가) | ✅ |
| `export.py todoist [--dry-run]` | — | 준비물·일정 체크리스트 푸시 | ✅ |

### 4.5 이름 충돌 처리

```
add 시 name이 이미 DB에 존재하면:
  → 새 row 만들지 않음
  → 기존 place.note 에 새 메모를 줄바꿈으로 append
  → stderr: "이미 존재: <이름> (id=N) — note 추가함"
  → --force 지정 시 별도 row 생성 (스타벅스 지점 구분 등)
```

조용히 중복을 쌓지도, 조용히 버리지도 않는다. 무슨 일이 일어났는지 항상 출력한다.

### 4.6 트랜잭션 경계

`add` 한 번은 all-or-nothing. `places`는 들어갔는데 `itinerary`에서 실패하면 전부 롤백한다. 반쯤 들어간 상태로 남으면 Claude 재시도 시 중복이 생긴다.

```python
with conn:                 # sqlite3 컨텍스트매니저 = 자동 커밋/롤백
    insert_source(...)
    insert_places(...)
    insert_itinerary(...)  # 예외 발생 시 전부 롤백
```

### 4.7 Todoist 매핑

| DB | Todoist |
| :--- | :--- |
| `packing` 행 | 섹션 "준비물" 아래 태스크. `owner`를 라벨로 (`@나`/`@아내`/`@공용`) |
| `itinerary` 행 | 섹션 "N일차" 아래 태스크. 제목은 `[슬롯] 장소명` |
| `todoist_task_id` | 푸시 후 응답 id 저장 → 재푸시 시 중복 생성 방지 |

`--dry-run`을 기본 습관으로 한다. 아내와 공유 중인 프로젝트에 잘못 밀어넣으면 되돌리기 번거롭다.

---

## 5. 에러 처리와 실패 모드

원칙: **조용히 넘어가지 않는다.** 여행 준비 중 조용한 실패는 현장에서 발견된다.

| # | 실패 | 감지 | 처리 | 종료코드 |
| :-- | :--- | :--- | :--- | :--- |
| E1 | LLM JSON 파싱 불가 | `json.loads` 예외 | stderr에 원본 앞 200자 + 파싱 위치 | 2 |
| E2 | 필수 키 누락 / enum 위반 | 파이썬 검증 | 어떤 필드가 왜 틀렸는지 명시 | 2 |
| E3 | 금지 필드 포함 | 화이트리스트 대조 | 거부 + "이 필드는 Places API만 채웁니다" | 2 |
| E4 | `itinerary.place_name` 미해석 | id 해석 실패 | 롤백 + 이름 출력. NULL로 조용히 넣지 않음 | 2 |
| E5 | 유튜브 자막 없음 | 3단 폴백 전부 실패 | 제목·설명만 `source` 저장, `places=[]`. **stderr에 `WARN E5: 자막 없음 — 텍스트를 직접 붙여넣어 주세요` 출력** | 0 (경고) |
| E6 | `GOOGLE_MAPS_API_KEY` 없음 | 환경변수 확인 | 발급 링크 출력 후 중단. **검색 URL 폴백 안 함** | 1 |
| E7 | Places API 5xx / 타임아웃 | HTTP 상태 | 해당 장소 `pending` 유지 → 다음 `verify`가 재시도 | 0 (부분) |
| E8 | Places 결과 이름 불일치 | 검색어 vs 반환 이름 대조 | `ambiguous` + `maps_url` 생성 → 사용자 육안 확인 | 0 |
| E9 | Places 결과 없음 | 빈 응답 | `not_found` 저장 | 0 |
| E10 | Todoist API 실패 | HTTP 상태 | `todoist_task_id` 미기록 → 재푸시가 곧 재시도 (멱등) | 1 |
| E11 | 배열 중 일부만 성공 | 예외 발생 | 전체 롤백 | 2 |

### 5.1 검증 실패는 Claude가 고칠 수 있게 말한다

```
$ echo '{"places":[{"name":"이치란","category":"밥집"}]}' | python trip.py add
ERROR E2: places[0].category = '밥집' 은 허용되지 않습니다.
  허용값: 맛집 | 쇼핑 | 관광 | 숙소 | 이동 | 기타
```

Claude CLI가 이 문장을 읽고 스스로 재시도한다. 사람이 중간에 낄 필요가 없다.

### 5.2 E6에서 폴백하지 않는 이유

키가 없다고 검색 URL로 조용히 내려가면 검증 안 된 링크가 검증된 링크와 섞여 DB에 들어간다. "반드시 확인하고 DB로 구축"이라는 요구가 무너진다. 차라리 멈춘다.

### 5.3 런북 연결

`AI_Project_Runbook_Framework` 구조를 그대로 적용.

| 런북 원칙 | 이 프로젝트 적용 |
| :--- | :--- |
| 트리거는 숫자로 | Places API 재시도 1회, 타임아웃 10초 |
| 강등 운전 설계 | `verify` 실패는 장애가 아님. `pending` 상태가 곧 강등 모드 |
| 조언이 아니라 강제 | enum은 CHECK 제약으로 DB가 거부 |
| Kill 전에 덤프 | 트랜잭션 롤백 전 stderr에 실패 원인 전량 출력 |

---

## 6. 테스트

`test_trip.py` 한 파일, `assert` 기반, 프레임워크 없음.

```bash
python test_trip.py
```

pytest도 쓰지 않는다. 의존성 0개 원칙을 테스트에도 적용한다.

### 6.1 테스트 대상 — 깨지면 조용히 잘못된 데이터가 쌓이는 것만

| 테스트 | 검증 내용 |
| :--- | :--- |
| `test_reject_bad_category` | E2 — enum 위반 거부 |
| `test_reject_forbidden_fields` | E3 — LLM이 `lat` 넣으면 거부 (**가장 중요**) |
| `test_reject_unknown_place_name` | E4 — 미해석 참조 거부 |
| `test_rollback_on_partial_failure` | E11 — 부분 실패 시 `source`도 남지 않음 |
| `test_duplicate_name_appends_note` | 중복 시 note append, row 미증가 |
| `test_takeout_csv_parse` | Title/Note/URL 매핑 |
| `test_verify_status_transitions` | pending → matched/ambiguous/not_found |
| `test_todoist_idempotent` | `todoist_task_id` 있으면 재생성 안 함 |

### 6.2 네트워크는 타지 않는다

```python
def verify_places(conn, fetch=_real_fetch):   # 테스트는 가짜 fetch 주입
```

목 라이브러리 없이 함수 하나를 바꿔 끼운다. DB는 `sqlite3.connect(":memory:")`.

### 6.3 만들지 않는 것

CI 파이프라인, 커버리지 리포트, 픽스처 계층, 통합 테스트. 1인용 여행 도구에서 회수되지 않는다.

---

## 7. 명시적 비목표 (이번 사이클)

| 항목 | 이유 |
| :--- | :--- |
| 텔레그램 봇 수집 | PM2 24시간 가동 인프라가 수집 코어보다 커진다. 입력 로직이 동일하므로 나중에 `trip.py` 위에 어댑터로 얹는다 |
| 구글시트 DB | "SQL식 정리로 검색 용이하게"라는 목적과 충돌. 조인·필터가 필요한 동선 최적화에 부적합 |
| GitHub Pages 배포 | 다음 사이클. 단 리포가 private이므로 **Pages는 Pro 필요** — public 전환 여부를 그때 결정 |
| LLM 동선 최적화·맛집 추천 | 다음 사이클. 이 DB가 입력이 된다 |
| 브라우저 자동화로 지도 목록 스크래핑 | Takeout이 공식·안정적이고 5분이면 끝난다. 구글 UI 변경마다 깨지는 스크래퍼를 여행 준비 중에 고치게 된다 |
| Takeout URL 좌표 파싱 | Places API 무료 한도로 충분. 구글 URL 포맷 변경에 취약 |
| DB 마이그레이션 도구 | 여행 한 번 쓰는 DB. 재구축이 더 싸다 |
| 사진/스크린샷 OCR 입력 | 사용자가 입력 형태에서 제외 |
| 아내 동시 편집 | 사용자가 불필요하다고 확정. 서버·인증·동시성 전부 제거의 근거 |

## 8. 알려진 리스크

| 리스크 | 영향 | 대응 |
| :--- | :--- | :--- |
| 유튜브 자막 없는 영상 | 해당 영상 수집 실패 | E5 — 텍스트 붙여넣기 경로로 폴백 (추가 코드 불필요) |
| `youtube-transcript-api`가 유튜브 변경으로 깨짐 | 자막 수집 전면 중단 | 텍스트 붙여넣기로 우회. Moons_Company와 동일 라이브러리라 그쪽 수정을 이식 가능 |
| Places API 이름 대조가 일본어 표기 차이로 오판 | `ambiguous` 과다 발생 | 사용자 육안 확인이 이미 절차에 포함. 오판해도 데이터는 안전 |
| 무료 한도 5,000 초과 | 과금 발생 | `verify --limit N`으로 배치 제어. 장소 300개 예상이므로 여유 |
| private 리포에 `.env` 실수 커밋 | 키 유출 | `.gitignore`에 `.env` 등록. `.env.example`만 커밋 |
| `data/trip.db`를 git에 커밋 | 바이너리 diff 비대 | 여행 1건 규모(수백 행)라 수용. 문제가 되면 `.sql` 덤프로 전환 |

## 9. 완료 기준

이번 사이클은 아래가 전부 참일 때 완료다.

1. `python test_trip.py`가 전부 통과한다.
2. `'26 후쿠오카` Takeout CSV를 임포트해 `place` 행이 생성된다.
3. `trip.py apply-lookup`(또는 키가 있으면 `verify`) 실행 후 `verify_status`가
   `pending` 아닌 값으로 갱신되고, `evidence_urls`에 근거가 남는다.
4. `export.py maps-links`가 출력한 링크를 클릭하면 **의도한 장소가 열린다**.
5. 유튜브 URL 1건을 `/trip add`로 넣으면 `source.raw_text`에 자막이, `place`에 장소가 들어간다.
6. `export.py todoist --dry-run`이 실제 푸시 없이 생성될 태스크 목록을 출력한다.
7. LLM이 `lat`을 넣은 JSON은 거부된다 — `add`(§4.3)와 `apply-lookup`(§3.3.2) 양쪽에서.
8. 근거 URL 없는 주소는 `apply-lookup`이 거부한다 (E2 실증).

---

## 부록: 출처

- Google Maps 저장 목록 쓰기 API 부재 — [issuetracker #453378725](https://issuetracker.google.com/issues/453378725)
- Places API 가격·무료 한도 — [Google Places API Free Tier Limits 2026](https://www.mapsleads.co/blog/google-places-api-free-tier-limits-2026)
- Takeout CSV 포맷 — [Export Google Maps Saved Places to CSV](https://exportmymap.com/blog/export-google-maps-saved-places-to-csv/)
- 자막 추출 원본 — `C:\GIT\Moons_Company\agents\scrap_agent.py`
