# 동선 지도 · 아이템 카테고리 · 가족 참고사항 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일정 동선을 SVG 지도로 보여주고, 살거·먹을거·놀거 아이템을 장소와 연결하고, 3인 가족 맥락의 참고사항을 근거 URL 과 함께 DB 에 넣는다.

**Architecture:** 기존 `trip.py`(쓰기·검증) / `export.py`(읽기 전용 출력) / `maps_page.py`(HTML 생성) 3분할을 그대로 유지한다. 테이블 3개(`item`·`item_place`·`tip`)를 더하고, 지도는 외부 의존 없이 좌표를 선형 투영해 인라인 SVG 로 그린다.

**Tech Stack:** Python stdlib 만 (sqlite3, json, argparse, re, urllib). 프런트는 순수 HTML/CSS/JS, 라이브러리 없음.

**Spec:** `docs/superpowers/specs/2026-09-09-map-items-tips-design.md`

## Global Constraints

CLAUDE.md 에서 온 프로젝트 전역 규칙이다. 모든 Task 에 암묵적으로 적용된다.

- **외부 패키지 추가 금지.** `youtube-transcript-api` 하나뿐이고 나머지는 stdlib. requests·ORM·pydantic·pytest 금지.
- **테스트는 `test_trip.py` 한 파일.** 프레임워크 없이 `def test_*` + `assert`. 실행은 `python test_trip.py`.
- **`git add .` 금지.** 자기가 고친 파일 경로만 명시해서 커밋한다.
- **LLM 은 좌표·`place_id`·`address`·`verify_status` 를 쓸 수 없다.** `trip.FORBIDDEN` 가드를 풀지 마라.
- **`verify` 는 과금 단계다. 자동 실행 금지.** 사람이 실행한다.
- **Places field mask 에 `rating`·`opening_hours` 를 넣지 마라.** Pro 가 Enterprise 로 승격되어 과금이 뛴다.
- **`places.SEARCH_AREA`(후쿠오카 사각형)를 지우지 마라.** 지우면 체인점이 전국에서 잡힌다.
- **`export.py` 는 `todoist_task_id` 외 어떤 컬럼에도 쓰지 않는다.**
- **Todoist 푸시는 미리보기가 기본.** `--push` 없이 쓰지 않는다. 이 기본값을 뒤집지 마라.
- **`main()` 의 `sys.stdin.reconfigure(encoding="utf-8")` 를 지우지 마라.** Windows cp949 때문에 한국어가 깨진다.
- **stdout 도 cp949 다.** 테스트·CLI 출력에 이모지를 쓰지 마라.

---

## Task 0: 테스트 러너를 파일 끝으로 옮긴다

**왜 먼저 하는가:** `if __name__ == "__main__":` 블록이 `test_trip.py` 639번째 줄에 있다. 파이썬은 모듈을 위에서 아래로 실행하므로, 러너가 도는 시점에 그 아래 정의된 함수 4개는 아직 `globals()` 에 없다. 그래서 **조용히 건너뛰고도 "OK — 0 failure(s)" 를 출력한다.** 정의 59개, 실행 55개다.

건너뛰던 4개 중 둘은 실제 사고의 회귀 테스트다 — `test_search_restricts_to_fukuoka`(체인점 오염), `test_todoist_existing_contents_follows_cursor`(커서 페이징 누락). 이걸 안 고치면 이 계획에서 새로 쓸 테스트도 위치에 따라 조용히 안 돈다.

**Files:**
- Modify: `test_trip.py:639-651` (러너 블록을 잘라 파일 맨 끝으로)

**Interfaces:**
- Consumes: 없음
- Produces: 없음 (구조 수정)

- [ ] **Step 1: 현재 실행 수를 기록한다**

Run: `python test_trip.py 2>&1 | grep -c PASS`
Expected: `55`

Run: `grep -c '^def test_' test_trip.py`
Expected: `59`

두 숫자가 다르다는 것이 이 Task 의 근거다.

- [ ] **Step 2: 러너 블록을 파일 끝으로 옮긴다**

`test_trip.py` 639번째 줄부터 시작하는 아래 블록을 **잘라내서** 파일 맨 끝(마지막 `def test_...` 함수 뒤)에 붙인다. 내용은 한 글자도 바꾸지 않는다.

```python
if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as e:
                fails += 1
                print(f"  FAIL {name}: {e}")
    print(f"\n{'FAILED' if fails else 'OK'} — {fails} failure(s)")
    raise SystemExit(1 if fails else 0)
```

- [ ] **Step 3: 러너 바로 앞에 이유를 적는다**

옮긴 블록 바로 위에 주석을 넣는다. 다음 사람이 다시 중간으로 옮기지 않도록.

```python
# 러너는 반드시 파일 맨 끝에 있어야 한다. 중간에 두면 그 아래 정의된
# test_ 함수가 globals() 에 없는 채로 수집되어 조용히 건너뛴다.
# 실제로 그래서 4개(체인점 오염·커서 페이징 회귀 테스트 포함)가 안 돌았다.
```

- [ ] **Step 4: 실행 수가 정의 수와 같아졌는지 확인한다**

Run: `python test_trip.py 2>&1 | grep -c PASS`
Expected: `59`

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`

숨어 있던 4개가 실패하면 그건 진짜 회귀다. 고치고 나서 다음으로 간다.

- [ ] **Step 5: 커밋**

```bash
git add test_trip.py
git commit -m "fix: 테스트 러너를 파일 끝으로 이동 — 4개가 조용히 안 돌고 있었다"
```

---

## Task 1: 테이블 3개 추가

**Files:**
- Modify: `schema.sql` (파일 끝에 추가)
- Modify: `test_trip.py` (기존 `test_schema_creates_four_tables` 갱신 + 새 테스트)

**Interfaces:**
- Consumes: `trip.connect(db_path)` — 스키마가 적용된 연결을 준다
- Produces: 테이블 `item`, `item_place`, `tip`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`test_trip.py` 의 기존 `test_schema_creates_four_tables` 를 **찾아서 아래로 교체**한다. 테이블이 7개가 되므로 이름과 집합을 함께 바꾼다.

```python
def test_schema_creates_all_tables():
    conn = trip.connect(":memory:")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"source", "place", "itinerary", "packing",
                     "item", "item_place", "tip"}, names


def test_item_category_check_constraint():
    conn = trip.connect(":memory:")
    try:
        conn.execute("INSERT INTO item (name, category) VALUES ('명란', '기념품')")
        assert False, "DB가 잘못된 item.category를 받아들였다"
    except sqlite3.IntegrityError:
        pass


def test_tip_scope_check_constraint():
    conn = trip.connect(":memory:")
    try:
        conn.execute(
            "INSERT INTO tip (scope, category, text, evidence_urls) "
            "VALUES ('hour', '날씨', 'x', 'http://a')")
        assert False, "DB가 잘못된 tip.scope를 받아들였다"
    except sqlite3.IntegrityError:
        pass


def test_item_place_links_one_item_to_many_places():
    conn = trip.connect(":memory:")
    conn.execute("INSERT INTO place (name, category) VALUES ('야마야', '쇼핑')")
    conn.execute("INSERT INTO place (name, category) VALUES ('로피아', '쇼핑')")
    conn.execute("INSERT INTO item (name, category) VALUES ('명란', '살거')")
    conn.execute("INSERT INTO item_place (item_id, place_id) VALUES (1, 1), (1, 2)")
    got = [r[0] for r in conn.execute(
        "SELECT p.name FROM item_place ip JOIN place p ON p.id = ip.place_id "
        "WHERE ip.item_id = 1 ORDER BY p.name")]
    assert got == ["로피아", "야마야"], got
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -E 'FAIL (test_schema|test_item|test_tip)'`
Expected: 4개 모두 FAIL. `test_schema_creates_all_tables` 는 집합 불일치, 나머지는 `no such table`.

- [ ] **Step 3: `schema.sql` 끝에 테이블을 추가한다**

```sql
-- 살거/먹을거/놀거. 장소와는 item_place 로 N:M 으로 붙는다.
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

-- '명란' 은 야마야에서도 로피아에서도 산다. 그래서 N:M 이다.
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

- [ ] **Step 4: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 62

- [ ] **Step 5: 기존 DB 에도 테이블을 만든다**

`connect()` 가 `executescript` 로 `CREATE TABLE IF NOT EXISTS` 를 매번 돌리므로 기존 `data/trip.db` 도 열기만 하면 적용된다.

Run: `python -c "import trip; c=trip.connect('data/trip.db'); print(sorted(r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"`
Expected: `['item', 'item_place', 'itinerary', 'packing', 'place', 'source', 'tip']`

- [ ] **Step 6: 커밋**

```bash
git add schema.sql test_trip.py data/trip.db
git commit -m "feat: item·item_place·tip 테이블 추가"
```

---

## Task 2: `validate_payload` 가 items·tips 를 검증한다

**Files:**
- Modify: `trip.py:66-98` (`validate_payload`), `trip.py:36-40` (enum 상수)
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: `trip.ValidationError(code, msg)`, `trip._enum(where, value, allowed)`, `trip._check_forbidden(where, obj)`
- Produces: `trip.ITEM_CATEGORY`, `trip.TIP_SCOPE`, `trip.TIP_CATEGORY` (집합 상수)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_reject_bad_item_category():
    try:
        trip.validate_payload({
            "source": {"kind": "text", "raw_text": "x"},
            "items": [{"name": "명란", "category": "기념품"}]})
        assert False, "잘못된 item category가 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E2", e.code
        assert "기념품" in str(e)


def test_reject_item_without_name():
    try:
        trip.validate_payload({
            "source": {"kind": "text", "raw_text": "x"},
            "items": [{"category": "살거"}]})
        assert False, "name 없는 item이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E2", e.code


def test_reject_tip_without_evidence():
    """근거 없는 팁은 저장하지 않는다. 공백뿐인 값도 막는다."""
    for bad in (None, "", "   ", "\n"):
        try:
            trip.validate_payload({
                "source": {"kind": "text", "raw_text": "x"},
                "tips": [{"scope": "trip", "category": "날씨",
                          "text": "덥다", "evidence_urls": bad}]})
            assert False, f"근거 없는 팁이 통과했다: {bad!r}"
        except trip.ValidationError as e:
            assert e.code == "E2", e.code


def test_reject_day_tip_without_day_no():
    try:
        trip.validate_payload({
            "source": {"kind": "text", "raw_text": "x"},
            "tips": [{"scope": "day", "category": "날씨", "text": "비",
                      "evidence_urls": "http://a"}]})
        assert False, "day_no 없는 day 팁이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E2", e.code
        assert "day_no" in str(e)


def test_reject_place_tip_without_place_name():
    try:
        trip.validate_payload({
            "source": {"kind": "text", "raw_text": "x"},
            "tips": [{"scope": "place", "category": "유모차", "text": "엘리베이터",
                      "evidence_urls": "http://a"}]})
        assert False, "place_name 없는 place 팁이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E2", e.code
        assert "place_name" in str(e)


def test_accept_valid_items_and_tips():
    payload = {
        "source": {"kind": "text", "raw_text": "원문"},
        "items": [{"name": "명란", "category": "살거", "note": "위탁수화물만",
                   "place_names": ["야마야 다이묘점"]}],
        "tips": [{"scope": "trip", "category": "공휴일", "text": "9/21~23 연휴",
                  "evidence_urls": "http://a\nhttp://b"}],
    }
    assert trip.validate_payload(payload) is payload


def test_reject_forbidden_fields_in_tip():
    """팁에도 좌표 금지 가드가 걸려야 한다."""
    try:
        trip.validate_payload({
            "source": {"kind": "text", "raw_text": "x"},
            "tips": [{"scope": "trip", "category": "날씨", "text": "x",
                      "evidence_urls": "http://a", "lat": 33.5}]})
        assert False, "팁의 lat이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E3", e.code
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -c FAIL`
Expected: `7`

- [ ] **Step 3: enum 상수를 더한다**

`trip.py` 의 `OWNER = {"나", "아내", "공용"}` 바로 아래에 붙인다.

```python
ITEM_CATEGORY = {"살거", "먹을거", "놀거"}
TIP_SCOPE = {"trip", "day", "place"}
TIP_CATEGORY = {"날씨", "공휴일", "아기", "유모차", "요금",
                "식사", "혼잡", "우천", "의료", "기타"}
```

- [ ] **Step 4: `validate_payload` 에 검증을 더한다**

`packing` 루프 바로 뒤, `return payload` 바로 앞에 넣는다.

```python
    for i, it in enumerate(payload.get("items") or []):
        _check_forbidden(f"items[{i}]", it)
        if not it.get("name"):
            raise ValidationError("E2", f"items[{i}].name 이 필요합니다.")
        _enum(f"items[{i}].category", it.get("category"), ITEM_CATEGORY)

    for i, t in enumerate(payload.get("tips") or []):
        _check_forbidden(f"tips[{i}]", t)
        if not t.get("text"):
            raise ValidationError("E2", f"tips[{i}].text 가 필요합니다.")
        _enum(f"tips[{i}].scope", t.get("scope"), TIP_SCOPE)
        _enum(f"tips[{i}].category", t.get("category"), TIP_CATEGORY)
        # 근거 없는 팁은 저장하지 않는다. NOT NULL 로는 '' 가 통과한다.
        if not (t.get("evidence_urls") or "").strip():
            raise ValidationError("E2",
                f"tips[{i}].evidence_urls 가 비었습니다. "
                "근거 URL 없는 팁은 저장하지 않습니다.")
        if t.get("scope") == "day" and not isinstance(t.get("day_no"), int):
            raise ValidationError("E2",
                f"tips[{i}].scope 가 'day' 이면 day_no 가 필요합니다.")
        if t.get("scope") == "place" and not t.get("place_name"):
            raise ValidationError("E2",
                f"tips[{i}].scope 가 'place' 이면 place_name 이 필요합니다.")
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 69

- [ ] **Step 6: 커밋**

```bash
git add trip.py test_trip.py
git commit -m "feat: items·tips 페이로드 검증 — 근거 URL 없는 팁 거부"
```

---

## Task 3: `insert_payload` 가 items·tips 를 쓴다

**Files:**
- Modify: `trip.py:105-172` (`insert_payload`)
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: Task 2 의 검증. `insert_payload` 안의 지역변수 `name_to_id`(장소명 → id), `source_id`
- Produces: 반환 dict 에 `"items"`, `"item_places"`, `"tips"` 카운트 추가

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_insert_items_and_links_to_places():
    conn = trip.connect(":memory:")
    r = trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "원문"},
        "places": [{"name": "야마야 다이묘점", "category": "쇼핑"},
                   {"name": "로피아", "category": "쇼핑"}],
        "items": [{"name": "명란", "category": "살거",
                   "place_names": ["야마야 다이묘점", "로피아"]}],
    })
    assert r["items"] == 1, r
    assert r["item_places"] == 2, r
    linked = [x[0] for x in conn.execute(
        "SELECT p.name FROM item_place ip JOIN place p ON p.id = ip.place_id "
        "ORDER BY p.name")]
    assert linked == ["로피아", "야마야 다이묘점"], linked


def test_insert_tip_resolves_place_name():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "원문"},
        "places": [{"name": "마린월드", "category": "관광"}],
        "tips": [{"scope": "place", "category": "요금", "text": "3세 무료",
                  "place_name": "마린월드", "evidence_urls": "http://a"}],
    })
    row = conn.execute("SELECT scope, place_id, text FROM tip").fetchone()
    assert row[0] == "place" and row[1] == 1, row
    assert row[2] == "3세 무료", row


def test_insert_tip_unknown_place_raises_e4():
    conn = trip.connect(":memory:")
    try:
        trip.insert_payload(conn, {
            "source": {"kind": "text", "raw_text": "원문"},
            "tips": [{"scope": "place", "category": "요금", "text": "x",
                      "place_name": "없는곳", "evidence_urls": "http://a"}],
        })
        assert False, "없는 장소를 가리키는 팁이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E4", e.code


def test_item_link_rollback_on_failure():
    """어디서든 실패하면 전부 롤백된다. 아이템만 남으면 안 된다."""
    conn = trip.connect(":memory:")
    try:
        trip.insert_payload(conn, {
            "source": {"kind": "text", "raw_text": "원문"},
            "items": [{"name": "명란", "category": "살거",
                       "place_names": ["없는가게"]}],
        })
        assert False, "없는 장소 연결이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E4", e.code
    assert conn.execute("SELECT count(*) FROM item").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM source").fetchone()[0] == 0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -c FAIL`
Expected: `4`

- [ ] **Step 3: `insert_payload` 를 고친다**

먼저 `result` 초기화에 카운터를 더한다.

```python
    result = {"source_id": None, "places_new": 0, "places_merged": 0,
              "itinerary": 0, "packing": 0, "items": 0, "item_places": 0,
              "tips": 0, "warnings": warnings}
```

그리고 `packing` 루프 바로 뒤, `conn.execute("COMMIT")` 바로 앞에 넣는다. 장소 이름 해석은 itinerary 와 같은 방식이다 — 이번 payload 의 `name_to_id` 를 먼저 보고, 없으면 DB 를 본다.

```python
        def resolve_place(where, pname):
            pid = name_to_id.get(pname)
            if pid is None:
                row = conn.execute(
                    "SELECT id FROM place WHERE name = ?", (pname,)).fetchone()
                pid = row[0] if row else None
            if pid is None:
                raise ValidationError("E4",
                    f"{where} 의 place_name {pname!r} 을 places 에서도 "
                    "DB 에서도 찾을 수 없습니다.")
            return pid

        for i, it in enumerate(payload.get("items") or []):
            cur = conn.execute(
                "INSERT INTO item (name, category, note, source_id) "
                "VALUES (?,?,?,?)",
                (it["name"], it["category"], it.get("note"), source_id))
            item_id = cur.lastrowid
            result["items"] += 1
            for pname in it.get("place_names") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO item_place (item_id, place_id) "
                    "VALUES (?,?)", (item_id, resolve_place(f"items[{i}]", pname)))
                result["item_places"] += 1

        for i, t in enumerate(payload.get("tips") or []):
            pid = (resolve_place(f"tips[{i}]", t["place_name"])
                   if t.get("place_name") else None)
            conn.execute(
                "INSERT INTO tip (scope, day_no, place_id, category, text, "
                "evidence_urls, source_id) VALUES (?,?,?,?,?,?,?)",
                (t["scope"], t.get("day_no"), pid, t["category"], t["text"],
                 t["evidence_urls"], source_id))
            result["tips"] += 1
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 73

- [ ] **Step 5: 커밋**

```bash
git add trip.py test_trip.py
git commit -m "feat: items·tips 저장 + 장소 연결 (all-or-nothing 유지)"
```

---

## Task 4: 조회 명령 `items` · `tips`

**Files:**
- Modify: `trip.py` (`list_plan` 뒤에 함수 2개, `main()` 에 서브명령 2개)
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: `trip.connect`
- Produces: `trip.list_items(conn, category=None)` → `sqlite3.Row` 리스트 (컬럼: `id, name, category, note, done, places`), `trip.list_tips(conn, day=None, scope=None)` → `sqlite3.Row` 리스트 (컬럼: `id, scope, day_no, category, text, evidence_urls, place_name`)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_list_items_joins_place_names():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "x"},
        "places": [{"name": "야마야", "category": "쇼핑"},
                   {"name": "로피아", "category": "쇼핑"}],
        "items": [{"name": "명란", "category": "살거",
                   "place_names": ["야마야", "로피아"]},
                  {"name": "모츠나베", "category": "먹을거"}],
    })
    rows = trip.list_items(conn)
    assert len(rows) == 2, rows
    by = {r["name"]: r for r in rows}
    assert by["명란"]["places"] == "로피아, 야마야", by["명란"]["places"]
    assert by["모츠나베"]["places"] is None, by["모츠나베"]["places"]

    only = trip.list_items(conn, category="먹을거")
    assert [r["name"] for r in only] == ["모츠나베"], only


def test_list_tips_filters_by_day():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "x"},
        "tips": [{"scope": "day", "day_no": 2, "category": "날씨",
                  "text": "비 예보", "evidence_urls": "http://a"},
                 {"scope": "trip", "category": "공휴일",
                  "text": "실버위크", "evidence_urls": "http://b"}],
    })
    assert [r["text"] for r in trip.list_tips(conn, day=2)] == ["비 예보"]
    assert len(trip.list_tips(conn)) == 2
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -c FAIL`
Expected: `2`

- [ ] **Step 3: 조회 함수를 쓴다**

`trip.py` 의 `list_plan` 함수 바로 뒤에 넣는다.

```python
def list_items(conn, category=None):
    """아이템 목록. 연결된 장소 이름을 쉼표로 이어 붙여 함께 준다."""
    conn.row_factory = sqlite3.Row
    sql = ("SELECT i.id, i.name, i.category, i.note, i.done, "
           "GROUP_CONCAT(p.name, ', ') AS places "
           "FROM item i "
           "LEFT JOIN item_place ip ON ip.item_id = i.id "
           "LEFT JOIN place p ON p.id = ip.place_id WHERE 1=1")
    args = []
    if category:
        sql += " AND i.category = ?"
        args.append(category)
    return conn.execute(
        sql + " GROUP BY i.id ORDER BY i.category, i.name", args).fetchall()


def list_tips(conn, day=None, scope=None):
    """참고사항 목록. 장소 팁이면 장소 이름을 함께 준다."""
    conn.row_factory = sqlite3.Row
    sql = ("SELECT t.id, t.scope, t.day_no, t.category, t.text, "
           "t.evidence_urls, p.name AS place_name "
           "FROM tip t LEFT JOIN place p ON p.id = t.place_id WHERE 1=1")
    args = []
    if day:
        sql += " AND t.day_no = ?"
        args.append(day)
    if scope:
        sql += " AND t.scope = ?"
        args.append(scope)
    return conn.execute(
        sql + " ORDER BY t.day_no IS NULL DESC, t.day_no, t.category, t.id",
        args).fetchall()
```

`GROUP_CONCAT` 의 정렬은 SQLite 가 보장하지 않지만, `LEFT JOIN place` 결과가 `place.id` 순으로 오므로 실무상 안정적이다. 테스트가 기대하는 `"로피아, 야마야"` 는 삽입 순서(야마야=1, 로피아=2)가 아니라 이름 순이므로, 안정성을 위해 서브쿼리로 정렬을 고정한다.

```python
           "(SELECT GROUP_CONCAT(p2.name, ', ') FROM ("
           "  SELECT p3.name FROM item_place ip2 "
           "  JOIN place p3 ON p3.id = ip2.place_id "
           "  WHERE ip2.item_id = i.id ORDER BY p3.name) p2) AS places "
```

위 서브쿼리로 `GROUP_CONCAT(p.name, ', ') AS places` 를 대체하고, `LEFT JOIN item_place` / `LEFT JOIN place` / `GROUP BY i.id` 는 지운다. 최종 `list_items` 는 다음과 같다.

```python
def list_items(conn, category=None):
    """아이템 목록. 연결된 장소 이름을 이름순으로 이어 붙여 함께 준다.

    GROUP_CONCAT 은 정렬을 보장하지 않는다. 서브쿼리에서 ORDER BY 로 고정한다.
    """
    conn.row_factory = sqlite3.Row
    sql = ("SELECT i.id, i.name, i.category, i.note, i.done, "
           "(SELECT GROUP_CONCAT(x.name, ', ') FROM ("
           "   SELECT p.name FROM item_place ip "
           "   JOIN place p ON p.id = ip.place_id "
           "   WHERE ip.item_id = i.id ORDER BY p.name) x) AS places "
           "FROM item i WHERE 1=1")
    args = []
    if category:
        sql += " AND i.category = ?"
        args.append(category)
    return conn.execute(sql + " ORDER BY i.category, i.name", args).fetchall()
```

- [ ] **Step 4: CLI 서브명령을 더한다**

`main()` 의 `p_mark` 정의 바로 뒤에 파서를 더한다.

```python
    p_items = sub.add_parser("items", help="아이템 조회 (살거/먹을거/놀거)")
    p_items.add_argument("--category")

    p_tips = sub.add_parser("tips", help="참고사항 조회")
    p_tips.add_argument("--day", type=int)
    p_tips.add_argument("--scope")
```

그리고 `if args.cmd == "mark-saved":` 처리 뒤에 출력을 더한다. **stdout 이 cp949 이므로 이모지를 쓰지 않는다.**

```python
    if args.cmd == "items":
        for r in list_items(conn, category=args.category):
            mark = "[v]" if r["done"] else "[ ]"
            print(f"{mark} [{r['id']:>3}] {r['category']:<4} {r['name']}")
            if r["places"]:
                print(f"        장소: {r['places']}")
            if r["note"]:
                print(f"        {r['note']}")
        return 0

    if args.cmd == "tips":
        for r in list_tips(conn, day=args.day, scope=args.scope):
            where = (f"{r['day_no']}일차" if r["day_no"]
                     else r["place_name"] or "여행 전체")
            print(f"[{r['id']:>3}] {r['category']:<4} ({where}) {r['text']}")
            for u in (r["evidence_urls"] or "").split("\n"):
                if u.strip():
                    print(f"        근거 {u.strip()}")
        return 0
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 75

Run: `python trip.py items`
Expected: 아무것도 안 나오고 종료 코드 0 (아직 데이터 없음)

- [ ] **Step 6: 커밋**

```bash
git add trip.py test_trip.py
git commit -m "feat: trip.py items·tips 조회 명령"
```

---

## Task 5: `verify --ids` 와 주소 우선 검색

**Files:**
- Modify: `trip.py:207-245` (`verify_places`), `main()` 의 `p_ver`
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: `places_mod.search(query, api_key)`, `places_mod.judge(name, candidates)`
- Produces: `trip.verify_places(conn, api_key, limit=50, search=None, ids=None)` — `ids` 가 주어지면 `verify_status` 와 무관하게 그 id 만 처리한다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_verify_ids_targets_matched_rows():
    """이미 matched 인 행도 --ids 로 지정하면 다시 조회한다.

    웹검색 경로로 matched 가 된 장소는 좌표가 없다. pending 만 보는
    선택 조건으로는 영영 안 잡힌다.
    """
    conn = trip.connect(":memory:")
    conn.execute("INSERT INTO place (name, category, verify_status) "
                 "VALUES ('마린월드', '관광', 'matched')")
    conn.commit()
    seen = []

    def fake_search(query, api_key):
        seen.append(query)
        return [{"place_id": "P1", "name": "마린월드", "address": "후쿠오카",
                 "lat": 33.66, "lng": 130.36}]

    trip.verify_places(conn, "KEY", search=fake_search, ids=[1])
    assert seen == ["마린월드"], seen
    row = conn.execute("SELECT lat, lng FROM place WHERE id=1").fetchone()
    assert row[0] == 33.66 and row[1] == 130.36, row


def test_verify_prefers_address_over_name():
    """주소가 있으면 주소로 검색한다. 일본 주소는 그 자체가 식별자다."""
    conn = trip.connect(":memory:")
    conn.execute("INSERT INTO place (name, category, address, verify_status) "
                 "VALUES ('동물의숲 우미노나카미치카이힌 공원', '관광', "
                 "'후쿠오카 히가시구 사이토자키 18-25', 'matched')")
    conn.commit()
    seen = []

    def fake_search(query, api_key):
        seen.append(query)
        return []

    trip.verify_places(conn, "KEY", search=fake_search, ids=[1])
    assert seen == ["후쿠오카 히가시구 사이토자키 18-25"], seen


def test_verify_without_ids_still_only_pending():
    """--ids 를 안 주면 기존 동작 그대로여야 한다."""
    conn = trip.connect(":memory:")
    conn.execute("INSERT INTO place (name, category, verify_status) "
                 "VALUES ('이미확인', '관광', 'matched')")
    conn.execute("INSERT INTO place (name, category) VALUES ('미조사', '관광')")
    conn.commit()
    seen = []

    def fake_search(query, api_key):
        seen.append(query)
        return []

    trip.verify_places(conn, "KEY", search=fake_search)
    assert seen == ["미조사"], seen
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -c FAIL`
Expected: `3` (앞의 둘은 `ids` 인자가 없어 TypeError, 셋째는 통과할 수도 있으나 시그니처 변경 전이므로 함께 확인)

- [ ] **Step 3: `verify_places` 를 고친다**

함수 시그니처와 행 선택, 검색어 결정 세 곳을 바꾼다.

```python
def verify_places(conn, api_key, limit=50, search=None, ids=None):
    """장소를 Places API 로 조회해 사실을 채운다.

    ids 를 주면 verify_status 와 무관하게 그 id 만 처리한다. 웹검색 경로로
    이미 matched 가 된 장소는 좌표가 없는데, pending 만 보는 조건으로는
    영영 안 잡히기 때문이다.

    조회 실패(E7)는 장애가 아니다. pending 을 유지하면 다음 실행이 재시도한다.
    """
    search = search or places_mod.search
    stats = {"matched": 0, "ambiguous": 0, "not_found": 0, "failed": 0}
    if ids:
        holes = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, name, address FROM place WHERE id IN ({holes}) "
            "ORDER BY id", tuple(ids)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, address FROM place WHERE verify_status = 'pending' "
            "ORDER BY id LIMIT ?", (limit,)).fetchall()
    for pid, name, address in rows:
        # 정확한 일본 주소는 그 자체가 식별자다. 한국어 표기명보다 잘 잡힌다.
        query = (address or "").strip() or name
        try:
            candidates = search(query, api_key)
```

이하 루프 본문에서 `search(name, api_key)` 를 위의 `search(query, api_key)` 로 바꾼 것 외에는 그대로 둔다. `places_mod.judge(name, candidates)` 의 첫 인자는 **`name` 그대로** 유지한다 — 이름 대조는 원래 이름으로 해야 한다.

- [ ] **Step 4: CLI 에 `--ids` 를 더한다**

`main()` 의 `p_ver` 정의를 고친다.

```python
    p_ver = sub.add_parser("verify", help="Places API 로 검증 (키 필요, 과금)")
    p_ver.add_argument("--limit", type=int, default=50)
    p_ver.add_argument("--ids", nargs="+", type=int,
                       help="이 id 만 검증한다. verify_status 를 무시한다.")
```

그리고 호출부에 넘긴다.

```python
            r = verify_places(conn, env.get("GOOGLE_MAPS_API_KEY", ""),
                              limit=args.limit, ids=args.ids)
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 78

- [ ] **Step 6: 커밋**

```bash
git add trip.py test_trip.py
git commit -m "feat: verify --ids 와 주소 우선 검색"
```

- [ ] **Step 7: 사람이 좌표를 채운다 (에이전트는 실행하지 않는다)**

**이 단계는 과금이다. 에이전트가 실행하지 말고 사용자에게 요청한다.**

사용자가 실행할 명령:

```bash
python trip.py verify --ids 6 10 12 14 15 52
```

대상: 6(Moff animal cafe), 10(한큐 하카타), 12(호텔 포르자), 14(마린월드), 15(동물의숲 해변공원), 52(라라포트 후쿠오카).

실행 뒤 확인:

```bash
python -c "import trip;c=trip.connect('data/trip.db');[print(r) for r in c.execute('SELECT id,name,verify_status,lat FROM place WHERE id IN (6,10,12,14,15,52)')]"
```

`ambiguous` 로 떨어진 것은 좌표가 안 채워진다. 억지로 채우지 않는다 — 지도에서 빠지고 Task 7 이 그 사실을 페이지에 표시한다.

```bash
git add data/trip.db
git commit -m "data: 일정 장소 6곳 좌표 확보"
```

---

## Task 6: 좌표 투영 함수

**Files:**
- Modify: `maps_page.py` (`collect_days` 뒤에 함수 추가)
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: 없음 (순수 함수)
- Produces: `maps_page.project(points, width=720, height=460, pad=40)` — `points` 는 `{"lat": float, "lng": float, ...}` 리스트, 반환은 같은 dict 에 `"x"`, `"y"` 가 더해진 새 리스트. 점이 0개면 빈 리스트, 1개면 화면 중앙.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_project_keeps_relative_positions():
    """북쪽이 위, 동쪽이 오른쪽이어야 한다. SVG 의 y 는 아래로 증가한다."""
    pts = maps_page.project([
        {"lat": 33.59, "lng": 130.42, "id": "hakata"},   # 남동
        {"lat": 33.66, "lng": 130.36, "id": "uminaka"},  # 북서
    ])
    by = {p["id"]: p for p in pts}
    assert by["uminaka"]["y"] < by["hakata"]["y"], by   # 북쪽이 위
    assert by["uminaka"]["x"] < by["hakata"]["x"], by   # 서쪽이 왼쪽


def test_project_fits_inside_canvas():
    pts = maps_page.project([
        {"lat": 33.59, "lng": 130.42},
        {"lat": 33.66, "lng": 130.36},
        {"lat": 33.60, "lng": 130.39},
    ], width=720, height=460, pad=40)
    for p in pts:
        assert 40 <= p["x"] <= 680, p
        assert 40 <= p["y"] <= 420, p


def test_project_single_point_centers():
    pts = maps_page.project([{"lat": 33.59, "lng": 130.42}],
                            width=720, height=460)
    assert pts[0]["x"] == 360 and pts[0]["y"] == 230, pts


def test_project_empty_returns_empty():
    assert maps_page.project([]) == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -c FAIL`
Expected: `4`

- [ ] **Step 3: 투영 함수를 쓴다**

`maps_page.py` 의 `collect_days` 뒤에 넣는다. `import math` 를 파일 상단 import 에 더한다.

```python
def project(points, width=720, height=460, pad=40):
    """위경도를 SVG 좌표로 옮긴다.

    후쿠오카 시내 범위(위도 0.1도 미만)라 Mercator 가 필요 없다. 위도에 따라
    경도 1도의 실제 길이가 짧아지는 것만 cos(lat) 로 보정하면 모양이 안 찌그러진다.
    """
    if not points:
        return []
    lats = [p["lat"] for p in points]
    lngs = [p["lng"] for p in points]
    mid_lat = (min(lats) + max(lats)) / 2
    kx = math.cos(math.radians(mid_lat))          # 경도 축소 보정
    xs = [p["lng"] * kx for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(lats), max(lats)
    span_x, span_y = x1 - x0, y1 - y0
    inner_w, inner_h = width - pad * 2, height - pad * 2
    # 가로세로 같은 배율을 써야 실제 모양이 유지된다.
    scale = min(inner_w / span_x if span_x else float("inf"),
                inner_h / span_y if span_y else float("inf"))
    if scale == float("inf"):
        scale = 0                                  # 점이 하나뿐이면 중앙에 둔다
    off_x = pad + (inner_w - span_x * scale) / 2
    off_y = pad + (inner_h - span_y * scale) / 2
    out = []
    for p, x in zip(points, xs):
        out.append({**p,
                    "x": round(off_x + (x - x0) * scale, 1),
                    # SVG 의 y 는 아래로 증가한다. 북쪽이 위로 가도록 뒤집는다.
                    "y": round(off_y + (y1 - p["lat"]) * scale, 1)})
    return out
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 82

- [ ] **Step 5: 커밋**

```bash
git add maps_page.py test_trip.py
git commit -m "feat: 위경도 → SVG 좌표 선형 투영"
```

---

## Task 7: 동선 지도 SVG + 일차 필터

**Files:**
- Modify: `maps_page.py` (`collect_route`, `build_page` 의 `__ROUTE__` 치환, TEMPLATE 의 지도 섹션·CSS·JS)
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: `maps_page.project(points, ...)` (Task 6), `maps_page.SLOT_ORDER`, `maps_page.DAY_META`
- Produces: `maps_page.collect_route(conn)` → `{"points": [...], "missing": {day_no: [name, ...]}}`. 각 point 는 `{"itin_id","place_id","day_no","seq_in_day","name","lat","lng","x","y","icon"}`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_collect_route_skips_places_without_coords():
    """좌표 없는 장소는 지도에서 빠지고, 빠진 사실이 남아야 한다."""
    conn = trip.connect(":memory:")
    conn.execute("INSERT INTO place (name, category, lat, lng) "
                 "VALUES ('캐널시티', '쇼핑', 33.5896, 130.4108)")
    conn.execute("INSERT INTO place (name, category) VALUES ('호텔', '숙소')")
    conn.execute("INSERT INTO itinerary (day_no, slot, seq, place_id) "
                 "VALUES (1, '오후', 0, 2)")
    conn.execute("INSERT INTO itinerary (day_no, slot, seq, place_id) "
                 "VALUES (1, '오후', 1, 1)")
    conn.commit()
    route = maps_page.collect_route(conn)
    assert [p["name"] for p in route["points"]] == ["캐널시티"], route
    assert route["missing"] == {1: ["호텔"]}, route


def test_collect_route_numbers_within_day():
    conn = trip.connect(":memory:")
    for i, (name, lat) in enumerate(
            [("A", 33.59), ("B", 33.60), ("C", 33.61)], start=1):
        conn.execute("INSERT INTO place (name, category, lat, lng) "
                     "VALUES (?, '관광', ?, 130.4)", (name, lat))
    # 밤을 먼저 넣어도 슬롯 순서대로 번호가 매겨져야 한다
    conn.execute("INSERT INTO itinerary (day_no, slot, seq, place_id) "
                 "VALUES (1, '밤', 0, 3)")
    conn.execute("INSERT INTO itinerary (day_no, slot, seq, place_id) "
                 "VALUES (1, '오전', 0, 1)")
    conn.execute("INSERT INTO itinerary (day_no, slot, seq, place_id) "
                 "VALUES (2, '오전', 0, 2)")
    conn.commit()
    route = maps_page.collect_route(conn)
    got = [(p["day_no"], p["seq_in_day"], p["name"]) for p in route["points"]]
    assert got == [(1, 1, "A"), (1, 2, "C"), (2, 1, "B")], got


def test_page_reports_missing_coords():
    conn = trip.connect(":memory:")
    conn.execute("INSERT INTO place (name, category) VALUES ('호텔', '숙소')")
    conn.execute("INSERT INTO itinerary (day_no, slot, seq, place_id) "
                 "VALUES (1, '오후', 0, 1)")
    conn.commit()
    page = maps_page.build_page(conn, "2026-09-09 12:00")
    assert "__ROUTE__" not in page, "치환 안 된 자리표시자"
    assert "좌표" in page, "좌표 누락 안내가 없다"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -c FAIL`
Expected: `3`

- [ ] **Step 3: `collect_route` 를 쓴다**

`maps_page.py` 의 `project` 뒤에 넣는다.

```python
def collect_route(conn):
    """일차별 동선. 좌표 없는 장소는 못 그리므로 빼고, 뺀 사실을 남긴다."""
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT i.id AS itin_id, i.day_no, i.slot, i.seq, i.place_id, "
        "p.name, p.category, p.lat, p.lng "
        "FROM itinerary i JOIN place p ON p.id = i.place_id")]
    rows.sort(key=lambda r: (r["day_no"], SLOT_ORDER.get(r["slot"], 9), r["seq"]))

    missing, keep = {}, []
    for r in rows:
        if r["lat"] is None or r["lng"] is None:
            missing.setdefault(r["day_no"], []).append(r["name"])
        else:
            keep.append(r)

    seen_per_day = {}
    points = []
    for r in keep:
        n = seen_per_day.get(r["day_no"], 0) + 1
        seen_per_day[r["day_no"]] = n
        points.append({
            "itin_id": r["itin_id"], "place_id": r["place_id"],
            "day_no": r["day_no"], "seq_in_day": n, "name": r["name"],
            "lat": r["lat"], "lng": r["lng"],
            "icon": icon_for(r["name"], r["category"]),
        })
    return {"points": project(points), "missing": missing}
```

- [ ] **Step 4: `build_page` 에 치환을 더한다**

```python
    page = (TEMPLATE
            .replace("__PLACES__", json.dumps(places, ensure_ascii=False))
            .replace("__DAYS__", json.dumps(collect_days(conn), ensure_ascii=False))
            .replace("__ROUTE__", json.dumps(collect_route(conn), ensure_ascii=False))
            .replace("__LABELS__", json.dumps(STATUS_LABEL, ensure_ascii=False))
            .replace("__TOTAL__", str(len(places)))
            .replace("__GENERATED__", html.escape(generated)))
```

- [ ] **Step 5: TEMPLATE 에 지도 섹션을 넣는다**

`<div id="days"></div>` **바로 위**에 넣는다.

```html
<section class="mapwrap">
  <div class="maphead">
    <h3 class="sec">동선</h3>
    <div class="tabs" id="daytabs"></div>
  </div>
  <svg id="routemap" viewBox="0 0 720 460" role="img"
       aria-label="일차별 이동 동선"></svg>
  <p class="mapnote" id="mapnote"></p>
</section>
```

CSS 는 `h3.sec` 규칙 바로 앞에 넣는다.

```css
.mapwrap{background:var(--card);border:1px solid var(--line);border-radius:20px;
  padding:14px;margin:16px 0}
.maphead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.maphead .sec{margin:0}
#routemap{width:100%;height:auto;display:block;background:var(--bg);
  border-radius:14px}
.mapnote{margin:8px 0 0;font-size:12px;color:var(--muted)}
.rt-line{fill:none;stroke-width:2.5;stroke-linecap:round}
.rt-dot{cursor:pointer}
.rt-dot circle{stroke:#fff;stroke-width:2}
.rt-dot text{font-size:11px;font-weight:700;fill:#fff;text-anchor:middle;
  dominant-baseline:central;pointer-events:none}
.rt-label{font-size:10.5px;fill:var(--ink);text-anchor:middle;pointer-events:none}
.rt-grid{stroke:var(--line);stroke-width:1}
.rt-scale{stroke:var(--muted);stroke-width:1.5}
.rt-scale-text{font-size:10px;fill:var(--muted)}
```

- [ ] **Step 6: TEMPLATE 의 JS 에 지도 렌더를 더한다**

`const LABEL = __LABELS__;` 아래에 `const ROUTE = __ROUTE__;` 를 더하고, `renderDays();` 호출 앞에 아래 코드를 넣는다.

```javascript
/* ---------- 동선 지도 ---------- */
const DAY_COLOR = {1: "#7b5ea7", 2: "#4a7fb5", 3: "#5aa469", 4: "#c9962f"};
let mapFilter = "all";

function renderMap() {
  const svg = document.getElementById("routemap");
  const pts = ROUTE.points.filter(
    p => mapFilter === "all" || p.day_no === Number(mapFilter));
  const days = [...new Set(pts.map(p => p.day_no))].sort((a, b) => a - b);

  let out = "";
  for (let g = 80; g < 720; g += 160)
    out += `<line class="rt-grid" x1="${g}" y1="0" x2="${g}" y2="460"/>`;
  for (let g = 80; g < 460; g += 120)
    out += `<line class="rt-grid" x1="0" y1="${g}" x2="720" y2="${g}"/>`;

  for (const d of days) {
    const seq = pts.filter(p => p.day_no === d)
                   .sort((a, b) => a.seq_in_day - b.seq_in_day);
    const color = DAY_COLOR[d] || "#7b5ea7";
    for (let i = 1; i < seq.length; i++) {
      const a = seq[i - 1], b = seq[i];
      out += `<line class="rt-line" stroke="${color}" x1="${a.x}" y1="${a.y}"
                x2="${b.x}" y2="${b.y}" marker-end="url(#arrow${d})"/>`;
    }
    for (const p of seq) {
      out += `<g class="rt-dot" data-itin="${p.itin_id}">
        <circle cx="${p.x}" cy="${p.y}" r="13" fill="${color}"/>
        <text x="${p.x}" y="${p.y}">${p.seq_in_day}</text></g>
        <text class="rt-label" x="${p.x}" y="${p.y + 26}">${esc(p.name).slice(0, 12)}</text>`;
    }
  }

  const defs = days.map(d => `<marker id="arrow${d}" viewBox="0 0 10 10"
      refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="${DAY_COLOR[d] || "#7b5ea7"}"/></marker>`).join("");
  svg.innerHTML = `<defs>${defs}</defs>${out}` ||
    `<text x="360" y="230" text-anchor="middle" fill="#9b9096">표시할 좌표가 없다</text>`;

  const miss = Object.entries(ROUTE.missing)
    .filter(([d]) => mapFilter === "all" || Number(d) === Number(mapFilter));
  const total = miss.reduce((n, [, names]) => n + names.length, 0);
  document.getElementById("mapnote").textContent = total
    ? `좌표가 없어 지도에 없는 곳 ${total}곳: ` +
      miss.map(([d, names]) => `${d}일차 ${names.join(", ")}`).join(" / ")
    : "";
}

document.getElementById("daytabs").innerHTML =
  [["all", "전체"], ...[1, 2, 3, 4].map(d => [String(d), `DAY ${d}`])]
    .map(([f, label], i) =>
      `<button class="chip${i === 0 ? " on" : ""}" data-day="${f}">${label}</button>`)
    .join("");
document.getElementById("daytabs").addEventListener("click", e => {
  const b = e.target.closest(".chip");
  if (!b) return;
  document.querySelectorAll("#daytabs .chip").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  mapFilter = b.dataset.day;
  renderMap();
});
```

지도의 점을 눌렀을 때 기존 팝업이 뜨도록, 전역 클릭 핸들러의 `.pic` 분기 **바로 앞**에 넣는다.

```javascript
  const dot = e.target.closest(".rt-dot");
  if (dot) {
    const iid = Number(dot.dataset.itin);
    for (const d of DAYS) {
      const it = d.items.find(x => x.id === iid);
      if (it) return openPlace(it.place_id, { ...it, day_no: d.day_no });
    }
    return;
  }
```

마지막으로 초기화 호출에 더한다.

```javascript
renderMap();
renderDays();
renderGrid();
renderCmd();
```

- [ ] **Step 7: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 85

Run: `python export.py maps-page && python export.py maps-page --out index.html`
Expected: 두 파일 모두 생성

- [ ] **Step 8: 브라우저로 눈으로 확인한다**

```bash
python -m http.server 8791 --bind 127.0.0.1
```

`http://127.0.0.1:8791/maps.html` 을 열고 확인한다.

- 동선 지도에 번호 붙은 점과 화살표가 보인다
- `전체 / DAY 1~4` 버튼을 누르면 해당 일차만 남는다
- 점을 누르면 기존 팝업이 뜬다
- 좌표 없는 곳이 있으면 지도 아래에 그 목록이 나온다

확인이 끝나면 서버를 끈다.

- [ ] **Step 9: 커밋**

```bash
git add maps_page.py test_trip.py maps.html index.html
git commit -m "feat: 일차별 동선 SVG 지도 + 필터"
```

`maps.html` 은 `.gitignore` 에 있으므로 실제로는 `index.html` 만 커밋된다. 경고가 나오면 `maps.html` 을 빼고 다시 실행한다.

---

## Task 8: 3인 가족 참고사항 리서치

**성격이 다르다.** 코드가 아니라 데이터 수집이다. 각 항목은 WebSearch 로 근거를 찾고, 근거 URL 이 없으면 저장하지 않는다.

**Files:**
- Create: `data/tips_research.json` (수집 결과, `trip.py add` 입력)
- Modify: `data/trip.db`

**Interfaces:**
- Consumes: Task 2·3 의 `tips` 페이로드 형식
- Produces: `tip` 행

- [ ] **Step 1: 항목별로 검색한다**

각 항목마다 한국어 1회 + 일본어/영어 1회 검색한다. 검색 결과에 없는 값은 쓰지 않는다.

| scope | category | 조사 내용 |
| --- | --- | --- |
| trip | 공휴일 | 2026-09-21~23 일본 공휴일 여부, 실버위크 해당 여부 |
| day (1~4) | 날씨 | 9/21~24 후쿠오카 예보와 9월 하순 평년 기온·강수 |
| place (14) | 요금 | 마린월드 우미노나카미치 3세 요금 |
| place (15) | 요금 | 우미노나카미치 해변공원 3세 요금 |
| place (52) | 아기 | 라라포트 후쿠오카 수유실·기저귀 교환대 |
| trip | 요금 | JR·후쿠오카 지하철 유아 운임 규정 |
| trip | 유모차 | 하카타역·텐진역 엘리베이터, 유모차 동선 |
| trip | 혼잡 | 연휴 관광지 혼잡 시간대와 회피 요령 |
| trip | 우천 | 비 올 때 실내 대안 |
| trip | 의료 | 하카타역 주변 약국·소아과 |

- [ ] **Step 2: 페이로드를 만든다**

`data/tips_research.json` 형식. `raw_text` 에는 검색으로 읽은 원문을 요약하지 말고 넣는다.

```json
{
  "source": {
    "kind": "web",
    "title": "3인 가족 여행 참고사항 조사 (2026-09-09)",
    "raw_text": "여기에 검색으로 읽은 원문을 그대로 넣는다. 요약하지 않는다."
  },
  "tips": [
    {
      "scope": "trip",
      "category": "공휴일",
      "text": "여기에 조사 결과를 쓴다",
      "evidence_urls": "https://...\nhttps://..."
    }
  ]
}
```

- [ ] **Step 3: 저장한다**

```bash
python trip.py add < data/tips_research.json
```

Expected: `OK ... tips N` 형태의 출력. 검증에 걸리면 그 팁은 근거가 없거나 scope 조건을 안 지킨 것이다.

- [ ] **Step 4: 확인한다**

```bash
python trip.py tips
python trip.py tips --day 2
```

Expected: 저장한 팁이 근거 URL 과 함께 나온다.

- [ ] **Step 5: 커밋**

```bash
git add data/tips_research.json data/trip.db
git commit -m "data: 3인 가족 여행 참고사항 (근거 URL 포함)"
```

---

## Task 9: 아이템 입력과 페이지 표시

**Files:**
- Create: `data/items.json`
- Modify: `maps_page.py` (TEMPLATE 에 아이템 탭 + `__ITEMS__` 치환), `test_trip.py`
- Modify: `data/trip.db`

**Interfaces:**
- Consumes: `trip.list_items(conn)` (Task 4)
- Produces: `maps_page.collect_items(conn)` → `[{"id","name","category","note","done","places"}]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_collect_items_groups_by_category():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "x"},
        "places": [{"name": "야마야", "category": "쇼핑"}],
        "items": [{"name": "명란", "category": "살거", "place_names": ["야마야"]},
                  {"name": "모츠나베", "category": "먹을거"}],
    })
    got = maps_page.collect_items(conn)
    assert {i["category"] for i in got} == {"살거", "먹을거"}, got
    myeong = [i for i in got if i["name"] == "명란"][0]
    assert myeong["places"] == "야마야", myeong


def test_page_embeds_items():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "x"},
        "items": [{"name": "모츠나베", "category": "먹을거"}],
    })
    page = maps_page.build_page(conn, "2026-09-09 12:00")
    assert "__ITEMS__" not in page, "치환 안 된 자리표시자"
    assert "모츠나베" in page, "아이템이 페이지에 없다"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -c FAIL`
Expected: `2`

- [ ] **Step 3: `collect_items` 를 쓴다**

`maps_page.py` 의 `collect_route` 뒤에 넣는다. `import trip` 를 파일 상단에 더한다.

```python
def collect_items(conn):
    """아이템 목록. 조회 로직은 trip.list_items 를 그대로 쓴다."""
    return [dict(r) for r in trip.list_items(conn)]
```

- [ ] **Step 4: `build_page` 에 치환을 더한다**

```python
            .replace("__ITEMS__", json.dumps(collect_items(conn), ensure_ascii=False))
```

- [ ] **Step 5: TEMPLATE 에 아이템 섹션을 넣는다**

`<h3 class="sec">장소 목록</h3>` **바로 위**에 넣는다.

```html
<h3 class="sec">살거 · 먹을거 · 놀거</h3>
<p class="sec-sub">장소와 연결된 것은 장소 이름이 같이 나온다.
  누르면 그 장소의 상세가 열린다.</p>
<div class="tabs" id="itemtabs"></div>
<div id="itemgrid"></div>
```

JS 는 `renderGrid` 정의 뒤에 넣고, 초기화 호출에 `renderItems();` 를 더한다.

```javascript
/* ---------- 아이템 ---------- */
const ITEM_TABS = ["전체", "살거", "먹을거", "놀거"];
let itemFilter = "전체";

function renderItems() {
  const shown = ITEMS.filter(
    i => itemFilter === "전체" || i.category === itemFilter);
  document.getElementById("itemgrid").innerHTML = shown.map(i => {
    const place = i.places
      ? `<small>${esc(i.places)}</small>` : `<small>장소 미정</small>`;
    return `<div class="tile${i.done ? " done" : ""}">
      <span class="e">${i.category === "살거" ? "🛍️"
        : i.category === "먹을거" ? "🍜" : "🎡"}</span>
      <span><b>${esc(i.name)}</b>${place}
        ${i.note ? `<small>${esc(i.note)}</small>` : ""}</span></div>`;
  }).join("") || "<p>아직 없다. python trip.py add 로 넣는다.</p>";
}

document.getElementById("itemtabs").innerHTML = ITEM_TABS.map((label, i) =>
  `<button class="chip${i === 0 ? " on" : ""}" data-i="${label}">${label}</button>`)
  .join("");
document.getElementById("itemtabs").addEventListener("click", e => {
  const b = e.target.closest(".chip");
  if (!b) return;
  document.querySelectorAll("#itemtabs .chip").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  itemFilter = b.dataset.i;
  renderItems();
});
```

`const ROUTE = __ROUTE__;` 아래에 `const ITEMS = __ITEMS__;` 를 더한다.

- [ ] **Step 6: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 87

- [ ] **Step 7: 실제 아이템을 넣는다**

`data/items.json` 을 만든다. Todoist 의 `01. 쇼핑 LIST`(바오바오 백, 플리츠)를 옮기고, 후쿠오카에서 살 것·먹을 것·놀 것을 더한다. 장소 이름은 **DB 에 있는 이름과 정확히 같아야 한다** — 다르면 E4 로 거부된다.

```bash
python -c "import trip;c=trip.connect('data/trip.db');[print(r[0]) for r in c.execute('SELECT name FROM place ORDER BY name')]"
```

로 이름을 먼저 확인하고 쓴다.

```json
{
  "source": {"kind": "text", "title": "살거·먹을거·놀거 목록",
             "raw_text": "원문을 그대로 넣는다"},
  "items": [
    {"name": "명란", "category": "살거", "note": "위탁수화물로만 가능",
     "place_names": ["야마야 다이묘점", "로피아 하카타 요도바시"]}
  ]
}
```

```bash
python trip.py add < data/items.json
python trip.py items
```

- [ ] **Step 8: 페이지를 다시 만들고 눈으로 확인한다**

```bash
python export.py maps-page
python export.py maps-page --out index.html
python -m http.server 8791 --bind 127.0.0.1
```

아이템 탭이 뜨고 필터가 도는지 확인한 뒤 서버를 끈다.

- [ ] **Step 9: 커밋**

```bash
git add maps_page.py test_trip.py data/items.json data/trip.db index.html
git commit -m "feat: 살거·먹을거·놀거 아이템 탭"
```

---

## Task 10: Todoist 로 아이템 푸시

**Files:**
- Modify: `export.py` (`build_todoist_tasks`)
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: `export.build_todoist_tasks(conn)` — 현재 `packing` 과 `itinerary` 를 태스크로 만든다
- Produces: 같은 함수가 `item` 도 낸다. 태스크 dict 는 `{"table","row_id","content","labels"}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_todoist_tasks_include_items():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "x"},
        "places": [{"name": "야마야", "category": "쇼핑"}],
        "items": [{"name": "명란", "category": "살거", "place_names": ["야마야"]}],
    })
    tasks = export.build_todoist_tasks(conn)
    item_tasks = [t for t in tasks if t["table"] == "item"]
    assert len(item_tasks) == 1, tasks
    assert item_tasks[0]["content"] == "[살거] 명란 @야마야", item_tasks[0]
    assert item_tasks[0]["labels"] == ["살거"], item_tasks[0]


def test_todoist_skips_pushed_items():
    """이미 푸시한 아이템은 다시 만들지 않는다."""
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "x"},
        "items": [{"name": "명란", "category": "살거"}],
    })
    conn.execute("UPDATE item SET todoist_task_id = 'T1' WHERE id = 1")
    conn.commit()
    assert [t for t in export.build_todoist_tasks(conn)
            if t["table"] == "item"] == []


def test_todoist_skipped_count_includes_items():
    """skipped 집계가 item 을 빼먹으면 숫자가 틀어진다."""
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "x"},
        "items": [{"name": "명란", "category": "살거"}],
    })
    conn.execute("UPDATE item SET todoist_task_id = 'T1' WHERE id = 1")
    conn.commit()
    r = export.push_todoist(conn, "TOK", "P1", dry_run=True)
    assert r["skipped"] == 1, r
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_trip.py 2>&1 | grep -c FAIL`
Expected: `3`

- [ ] **Step 3: `build_todoist_tasks` 에 아이템을 더한다**

`itinerary` 루프 뒤, `return tasks` 앞에 넣는다.

```python
    for r in conn.execute(
            "SELECT i.id, i.name, i.category, "
            "(SELECT GROUP_CONCAT(x.name, ', ') FROM ("
            "   SELECT p.name FROM item_place ip "
            "   JOIN place p ON p.id = ip.place_id "
            "   WHERE ip.item_id = i.id ORDER BY p.name) x) AS places "
            "FROM item i WHERE i.todoist_task_id IS NULL"):
        where = f" @{r['places']}" if r["places"] else ""
        tasks.append({"table": "item", "row_id": r["id"],
                      "content": f"[{r['category']}] {r['name']}{where}",
                      "labels": [r["category"]]})
```

`push_todoist` 는 `UPDATE {t['table']} SET todoist_task_id = ...` 로 테이블명을 동적으로 쓰므로 `item` 도 손대지 않고 그대로 동작한다(`export.py:141-143`). 고칠 곳은 한 군데, `skipped` 집계다. 지금은 `packing + itinerary` 만 세서 아이템이 빠진다.

`push_todoist` 안의 `total` 계산을 아래로 바꾼다.

```python
    total = conn.execute(
        "SELECT (SELECT COUNT(*) FROM packing) + (SELECT COUNT(*) FROM itinerary)"
        " + (SELECT COUNT(*) FROM item)"
    ).fetchone()[0]
```

**`todoist_task_id` 외의 컬럼은 여전히 건드리지 않는다.**

- [ ] **Step 4: 통과를 확인한다**

Run: `python test_trip.py 2>&1 | tail -2`
Expected: `OK — 0 failure(s)`, PASS 개수 90

- [ ] **Step 5: 미리보기로 확인한다 (푸시하지 않는다)**

```bash
python export.py todoist
```

Expected: 만들려는 아이템 태스크 목록이 나오고 `would_create` 가 아이템 수만큼. **`--push` 는 사용자가 결정한다.**

- [ ] **Step 6: 커밋**

```bash
git add export.py test_trip.py
git commit -m "feat: 아이템을 Todoist 태스크로 푸시 (미리보기 기본 유지)"
```

---

## Task 11: HANDOFF.md 갱신

**Files:**
- Modify: `HANDOFF.md`

- [ ] **Step 1: 현재 상태를 다시 쓴다**

다음을 반영한다.

- 테이블이 7개가 됐다 (`item`·`item_place`·`tip` 추가)
- 테스트 러너가 파일 끝으로 갔다. **중간에 두면 그 아래 테스트가 조용히 안 돈다** — 이 함정을 함정 목록에 추가한다
- `verify --ids` 로 `matched` 행도 재검증할 수 있다. 주소가 있으면 주소로 검색한다
- 페이지에 동선 지도·아이템 탭이 생겼다
- 좌표 현황을 실제 수치로 갱신한다

- [ ] **Step 2: 명령어 목록을 갱신한다**

```bash
python trip.py items --category 살거
python trip.py tips --day 2
python trip.py verify --ids 6 10 12 14 15 52   # 과금. 사람이 실행한다
python export.py maps-page --out index.html    # Pages 배포물
```

- [ ] **Step 3: 커밋**

```bash
git add HANDOFF.md
git commit -m "docs: HANDOFF 갱신 — 테이블 7개, 동선 지도, 아이템·팁"
```

---

## Task 12: 배포

**Files:**
- Modify: `index.html`

- [ ] **Step 1: 배포물을 다시 만든다**

```bash
python export.py maps-page --out index.html
python test_trip.py
```

Expected: `OK — 0 failure(s)`

- [ ] **Step 2: 푸시한다**

```bash
git add index.html
git commit -m "chore: 가이드 페이지 갱신 — 동선 지도·아이템"
git push origin main
```

- [ ] **Step 3: Pages 배포를 확인한다**

```bash
gh api repos/drasticlife/travel_manager/pages/builds/latest --jq '.status'
curl -s -o /dev/null -w "%{http_code}\n" https://drasticlife.github.io/travel_manager/
```

Expected: `built`, `200`

- [ ] **Step 4: Artifact 를 갱신한다**

```bash
python export.py maps-page --fragment --out <scratchpad>/fukuoka-guide.html
```

같은 파일 경로로 재게시하면 URL 이 유지된다.

**Artifact 에서는 지도가 그대로 뜬다** — 인라인 SVG 라 외부 호스트를 쓰지 않기 때문이다. 이것이 자체 SVG 를 고른 이유다.

---

## 자체 검토 결과

**스펙 대응:** 스펙의 8개 절이 Task 로 모두 덮인다 — 스키마(1), 좌표(5), 지도(6·7), 페이지 구조(7·9), CLI(4·5), 리서치(8), 테스트(각 Task), 구현 순서(Task 배열). 스펙에 없던 Task 0 은 조사 중 발견한 결함이라 추가했다.

**타입 일관성:** `project()` 가 반환하는 `x`/`y` 를 `collect_route()` 가 그대로 실어 보내고 JS 가 `p.x`/`p.y` 로 읽는다. `collect_route()` 의 `itin_id` 는 JS 의 `dot.dataset.itin` → `DAYS[].items[].id` 와 맞물린다. `list_items()` 의 `places` 컬럼명이 `collect_items()` → JS `i.places` 까지 이어진다.

**남은 위험:** Task 5 Step 7 의 좌표 확보 결과에 따라 Task 7 의 지도에 점이 몇 개 찍힐지가 달라진다. `ambiguous` 가 많이 나오면 지도가 빈약해지지만, 누락 안내가 그 사실을 드러내므로 조용한 실패는 아니다.
