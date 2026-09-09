# 동선 지도 · 아이템 카테고리 · 가족 참고사항 — 설계

작성 2026-09-09 · 여행 2026-09-21~24 (12일 남음)

## 왜 하는가

현재 DB 는 **장소만** 담는다. 실제 여행에서 필요한 세 가지가 빠져 있다.

1. **동선이 안 보인다.** 일정은 목록이라 하루에 어디를 어떤 순서로 도는지 지도로 확인할 수 없다.
2. **살 것·먹을 것·놀 것을 담을 자리가 없다.** "명란을 야마야에서 산다" 같은
   아이템↔장소 관계를 표현할 테이블이 없다. Todoist 에 흩어져 있다.
3. **3인 가족(3살 다정이·배우자·본인) 맥락이 없다.** 3세 요금, 유모차 동선,
   수유실, 우천 대안, 9/21~23 실버위크 혼잡 — 전부 사람 머릿속에만 있다.

## 조사로 확인한 사실

설계의 전제다. 추측이 아니라 DB·코드·API 설정을 실제로 확인한 값이다.

| 사실 | 값 | 확인 방법 |
| --- | --- | --- |
| 좌표 보유 | 52건 중 **22건** | `SELECT count(*) FROM place WHERE lat IS NOT NULL` |
| `claude_search` 경로 좌표 | **27건 중 0건** | `verify_method` 별 집계 |
| Places API 경로 좌표 | 22건 중 22건 | 같음 |
| 일정에 걸린 장소 중 좌표 없음 | **6곳** (id 6·10·12·14·15·52) | itinerary JOIN place |
| 그중 `verify` 가 잡는 것 | **1곳**(52 라라포트, pending) | `verify_places()` 는 `verify_status='pending'` 만 선택 |
| Places field mask | `places.id,displayName,formattedAddress,location` | `places.py:15` |

즉 **웹 검색으로는 좌표가 안 나온다**는 CLAUDE.md 의 함정이 그대로 데이터에 찍혀 있다.
field mask 에 `rating`·`opening_hours` 가 없으므로 Pro 등급이고, Enterprise 승격
함정은 피해 있다. 6건 요청은 무료 한도(월 5,000) 안이다.

## 결정 사항

브레인스토밍에서 사용자가 고른 것이다.

- 네 갈래를 **하나의 스펙**으로 묶는다.
- 좌표는 **일정에 걸린 것만** 채운다. 나머지 24곳은 좌표 없이 둔다.
- 지도는 **자체 SVG**. 구글지도·Leaflet 을 쓰지 않는다.
- 아이템은 **DB 가 원본**, CLI 로 넣고, 페이지는 표시만, Todoist 로 푸시한다.
- 리서치는 **폭넓게** 한다.

### 지도를 자체 SVG 로 그리는 이유

두 가지 제약이 겹친다.

1. **Artifact 의 CSP 가 외부 호스트를 전부 막는다.** 구글지도든 OSM 타일이든
   배경 지도는 Artifact 에서 원천적으로 뜨지 않는다.
2. **리포가 public 이다.** `index.html` 에 API 키를 넣으면 그대로 공개된다.
   referrer 제한을 사람이 직접 걸어야 하고, 안 걸면 키 도용 위험이 있다.

자체 SVG 는 키가 필요 없고 외부 의존이 0 이라 Artifact·Pages 양쪽에서 똑같이 돈다.
대가는 배경 지도 타일이 없다는 것이다. 각 점에 구글지도 링크를 걸어 보완한다.

## 1. 스키마

`schema.sql` 에 테이블 3개를 더한다. enum 은 기존 방식대로 CHECK 로 DB 가 강제한다 —
LLM 이 카테고리를 지어내면 INSERT 가 거부되어야 한다.

```sql
CREATE TABLE IF NOT EXISTS item (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  category        TEXT NOT NULL CHECK (category IN ('살거','먹을거','놀거')),
  note            TEXT,
  done            INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0,1)),
  source_id       INTEGER REFERENCES source(id),
  todoist_task_id TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 아이템 ↔ 장소 N:M. '명란' 은 야마야에서도 로피아에서도 산다.
CREATE TABLE IF NOT EXISTS item_place (
  item_id   INTEGER NOT NULL REFERENCES item(id),
  place_id  INTEGER NOT NULL REFERENCES place(id),
  PRIMARY KEY (item_id, place_id)
);

-- 참고사항. 날씨·공휴일은 장소가 아니라 날짜에 붙으므로 place.note 로는 못 담는다.
CREATE TABLE IF NOT EXISTS tip (
  id            INTEGER PRIMARY KEY,
  scope         TEXT NOT NULL CHECK (scope IN ('trip','day','place')),
  day_no        INTEGER,
  place_id      INTEGER REFERENCES place(id),
  category      TEXT NOT NULL CHECK (category IN
                  ('날씨','공휴일','아기','유모차','요금','식사','혼잡','우천','의료','기타')),
  text          TEXT NOT NULL,
  -- 근거 URL(줄바꿈 구분). NOT NULL 은 빈 문자열을 막지 못하므로
  -- validate_payload 가 공백뿐인 값도 E2 로 거부한다.
  evidence_urls TEXT NOT NULL,
  source_id     INTEGER REFERENCES source(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_item_category ON item(category);
CREATE INDEX IF NOT EXISTS idx_tip_scope     ON tip(scope, day_no);
```

`scope` 와 `day_no`/`place_id` 의 정합성은 코드가 검증한다: `scope='day'` 면
`day_no` 필수, `scope='place'` 면 `place_id` 필수, `scope='trip'` 이면 둘 다 NULL.
SQLite CHECK 로도 표현 가능하지만 오류 메시지가 불친절하므로 `validate_payload`
에서 잡고 E2 로 돌려준다.

## 2. 좌표 확보

`trip.py verify` 를 두 가지로 고친다.

1. **`--ids` 옵션 추가.** 없으면 지금처럼 `pending` 전체, 있으면 그 id 만.
   `verify_status` 와 무관하게 처리한다 — 대상 5곳이 이미 `matched` 라서
   현재 선택 조건으로는 영영 안 잡힌다.
2. **주소가 있으면 이름 대신 주소로 검색한다.** CLAUDE.md 가 적어둔 대로
   정확한 일본 주소는 그 자체가 식별자다. "동물의숲 우미노나카미치카이힌 공원"
   같은 한국어 이름은 구글에서 안 잡힐 가능성이 높다.

실행은 사람이 한다 — **`verify` 는 과금 단계이므로 자동 실행하지 않는다**(CLAUDE.md 규칙 3).

```bash
python trip.py verify --ids 6 10 12 14 15 52
```

`SEARCH_AREA`(후쿠오카 사각형)는 그대로 둔다. 이걸 풀면 체인점이 전국에서
잡힌다 — 실제로 카페 베로체가 야쿠인점으로 오염된 적이 있다.

**결과가 2건 이상이면 `ambiguous`** 규칙도 그대로다. ambiguous 로 떨어지면
좌표는 안 써지고, 그 장소는 지도에서 빠진다. 억지로 1순위를 채택하지 않는다.

## 3. 동선 지도 (자체 SVG)

`maps_page.py` 에 함수를 더한다. 새 파일로 분리하지 않는다 — 기존 페이지
생성기와 데이터·색 토큰을 공유한다.

- **투영**: 좌표 범위가 위도 0.08°·경도 0.05° 정도로 좁아 Mercator 가 필요 없다.
  선형 변환으로 충분하고, 위도에 따른 경도 축소만 `cos(lat)` 로 보정한다.
- **표시**: 방문 순서 번호 배지가 붙은 점, 순서대로 잇는 선, 화살표 마커.
  일차별 색은 기존 토큰(보라 계열, DAY4 노랑)을 쓴다.
- **필터**: `전체 / DAY 1 / DAY 2 / DAY 3 / DAY 4` 버튼. 누르면 해당 일차 동선만 남는다.
- **상호작용**: 점을 누르면 **기존 팝업을 그대로 재사용**한다. 새 팝업을 만들지 않는다.
- **배경**: 지도 타일 없음. 격자, 축척 바, 주요 지명 라벨만.
- **누락 표시**: 좌표 없는 장소는 지도에 못 그린다. 조용히 빠뜨리지 않고
  "이 일차의 N곳은 좌표가 없어 지도에 없다" 를 명시한다.

## 4. 페이지 구조

```
헤더
 → 동선 지도 + 일차 필터        ← 신규
 → DAY 카드 4장 (팁 배지 추가)   ← tip 표시 추가
 → 아이템 탭 (살거/먹을거/놀거)  ← 신규
 → 장소 목록
```

DAY 카드에는 해당 일차의 `tip` 중 `날씨`·`공휴일`·`혼잡` 을 배지로 얹는다.
나머지 팁은 팝업에서 본다.

## 5. CLI

- `trip.py add` 페이로드에 `items` / `tips` 를 받는다. 기존 검증 방식 그대로이고
  **좌표 금지 가드(E3)는 유지**한다.
- `trip.py items --category 살거` — 아이템 조회
- `trip.py tips --day 2` — 참고사항 조회
- `export.py todoist` 에 아이템 푸시를 더한다. **미리보기가 기본이고 `--push` 를
  요구하는 현재 동작을 뒤집지 않는다** — 공유 프로젝트라 중복 생성이 위험하다.
  중복 방지는 기존대로 로컬 `todoist_task_id` + 원격 제목 대조 2중으로 한다.

## 6. 리서치

WebSearch 로 조사해 `tip` 행으로 저장한다. 원문은 `source.raw_text` 에 보존한다.

**근거 URL 없는 팁은 저장하지 않는다.** 빈 문자열·공백뿐인 값도 거부한다 —
`NOT NULL` 만으로는 `''` 가 통과하므로 `validate_payload` 에서 막는다.
기억으로 지어낸 값을 쓰지 않는다는 CLAUDE.md 규칙 1 이 여기에도 적용된다.

조사 항목:

| 범주 | 내용 |
| --- | --- |
| 날씨 | 9/21~24 후쿠오카 예보·평년값, 강수 확률, 체감 온도 |
| 공휴일 | 9/21~23 일본 공휴일 확인, 실버위크 혼잡 영향 |
| 요금 | 마린월드·해변공원·라라포트·JR·지하철의 3세 요금 |
| 유모차 | 역 엘리베이터 위치, 시설 유모차 대여·통행 |
| 아기 | 수유실·기저귀 교환대 위치 |
| 식사 | 아기 의자·유아 메뉴 있는 식당 |
| 혼잡 | 연휴 관광지 혼잡 시간대와 회피 시간 |
| 우천 | 비 올 때 실내 대안 |
| 의료 | 근처 약국·소아과 |

## 7. 테스트

`test_trip.py` 에 더한다. 프레임워크는 쓰지 않는다(pytest 금지).

- `item.category` 가 enum 밖이면 INSERT 거부
- `tip.scope='day'` 인데 `day_no` 없으면 E2
- `tip.evidence_urls` 가 비면 저장 거부
- `item_place` N:M — 한 아이템이 여러 장소에 붙는다
- 좌표 투영 함수: 알려진 두 점의 상대 위치가 유지되는지
- 지도 SVG 에 좌표 없는 장소가 안 들어가는지
- `verify --ids` 가 `matched` 상태도 대상으로 잡는지 (가짜 search 로)

## 8. 구현 순서

셋으로 나눈다. 각 단계 끝에서 테스트가 통과해야 다음으로 간다.

1. **스키마 + CLI** — 테이블 3개, `add` 페이로드 확장, 조회 명령, 테스트.
   데이터는 아직 없다.
2. **좌표 + 지도** — `verify --ids`, 주소 우선 검색, 투영 함수, SVG 동선도, 필터.
   좌표 채우기는 사용자가 실행한다.
3. **리서치 + 아이템 데이터** — WebSearch 로 팁 수집, 아이템 입력, Todoist 푸시.

## 위험과 한계

- **좌표 6곳이 다 채워진다는 보장이 없다.** `ambiguous` 로 떨어지면 그 장소는
  지도에서 빠진다. 억지로 채우지 않고 누락을 페이지에 표시한다.
- **배경 지도가 없다.** 점과 선만으로는 실제 거리감이 약하다. 축척 바로 보완하지만
  구글지도만큼 직관적이지 않다.
- **날씨 예보는 12일 전이라 정확도가 낮다.** 평년값과 함께 저장하고 조회 시점을
  같이 적는다. 출발 직전에 다시 갱신해야 한다.
- **리포가 public 이라 tip 내용도 공개된다.** 숙소·일정은 이미 공개 상태다.
  개인 의료 정보 같은 건 넣지 않는다.
