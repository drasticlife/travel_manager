# travel manager 수집→DB 코어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 유튜브·웹·텍스트·자연어로 수집한 여행 자료를 검증된 SQLite DB로 쌓고, 구글지도 확인 링크와 Todoist 체크리스트로 내보내는 CLI를 만든다.

**Architecture:** LLM(Claude CLI)은 추출·분류만 하고 정규화 JSON을 stdout으로 뱉는다. `trip.py`가 그 JSON을 화이트리스트 검증한 뒤 트랜잭션으로 SQLite에 쓴다. 좌표·place_id 같은 사실(fact)은 LLM이 아니라 Places API만 채운다. 수집(무과금)과 검증(과금)을 분리해 실패 지점을 격리한다.

**Tech Stack:** Python 3.13, stdlib (`sqlite3`, `argparse`, `json`, `csv`, `urllib`), 외부 패키지 `youtube-transcript-api` 1개.

## Global Constraints

- 스펙 원본: `docs/superpowers/specs/2026-09-06-travel-manager-design.md`. 충돌 시 스펙이 우선.
- 외부 패키지는 `youtube-transcript-api` **하나만**. `requests`·ORM·pydantic·pytest 금지.
- 테스트는 `test_trip.py` 단일 파일, `assert` 기반, `python test_trip.py`로 실행. 프레임워크 금지.
- 테스트는 네트워크를 타지 않는다. 외부 호출은 함수 인자로 주입(`fetch=...`).
- DB 파일 기본 경로 `data/trip.db`. 테스트는 `sqlite3.connect(":memory:")`.
- enum 값은 스펙과 **정확히 일치**해야 한다:
  - `source.kind`: `youtube` `web` `text` `chat` `takeout`
  - `place.category`: `맛집` `쇼핑` `관광` `숙소` `이동` `기타`
  - `place.verify_status`: `pending` `matched` `ambiguous` `not_found`
  - `itinerary.slot`: `오전` `점심` `오후` `저녁` `밤`
  - `packing.category`: `의류` `전자` `서류` `약` `세면` `기타`
  - `packing.owner`: `나` `아내` `공용`
- LLM 금지 필드: `place_id` `lat` `lng` `address` `verify_status` `maps_url` `id` `created_at`
- 종료코드: 검증 실패 `2`, 설정/외부 실패 `1`, 정상·부분성공 `0`
- 모든 파일은 UTF-8. Windows 환경이므로 파일 쓰기 시 `encoding="utf-8"` 명시.
- 커밋은 자기가 만든 파일 경로만 명시해서 한다. `git add .` 금지.

## File Structure

| 파일 | 책임 | 의존 |
| :--- | :--- | :--- |
| `schema.sql` | DDL 4테이블 + 인덱스 | — |
| `trip.py` | DB 연결, JSON 검증, 쓰기, 조회 CLI | `schema.sql`, `places.py`, `youtube.py` |
| `youtube.py` | video id 추출, 자막 3단 폴백, 30초 병합 | `youtube-transcript-api` |
| `places.py` | Places API 조회, 이름 대조, maps_url 생성 | stdlib only |
| `export.py` | 지도링크 출력, Todoist 푸시 | `trip.py` |
| `test_trip.py` | 전체 테스트 | 위 전부 |
| `.claude/commands/trip.md` | LLM 추출 계약 | — |
| `CLAUDE.md` | 프로젝트 규약 | — |

---

### Task 1: 스키마와 DB 부트스트랩

**Files:**
- Create: `schema.sql`
- Create: `trip.py`
- Create: `test_trip.py`

**Interfaces:**
- Consumes: 없음
- Produces: `connect(db_path=":memory:") -> sqlite3.Connection` (스키마 적용된 연결 반환), `SCHEMA_PATH`

- [ ] **Step 1: `schema.sql` 작성**

스펙 §2.2~2.5의 DDL을 그대로 옮긴다. 4테이블 + 인덱스 3개. 전부 `IF NOT EXISTS`.

- [ ] **Step 2: 실패하는 테스트 작성** (`test_trip.py`)

```python
import sqlite3, trip

def test_schema_creates_four_tables():
    conn = trip.connect(":memory:")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"source", "place", "itinerary", "packing"}, names

def test_category_check_constraint():
    conn = trip.connect(":memory:")
    try:
        conn.execute("INSERT INTO place (name, category) VALUES ('x', '밥집')")
        assert False, "DB가 잘못된 category를 받아들였다"
    except sqlite3.IntegrityError:
        pass
```

- [ ] **Step 3: 실패 확인**

Run: `python test_trip.py`
Expected: FAIL — `ModuleNotFoundError` 또는 `AttributeError: module 'trip' has no attribute 'connect'`

- [ ] **Step 4: `trip.py`에 최소 구현**

```python
import sqlite3, os
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "trip.db")

def connect(db_path=DEFAULT_DB):
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn
```

테스트 러너도 같이 넣는다 (`test_trip.py` 하단):

```python
if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  PASS {name}")
            except Exception as e:
                fails += 1; print(f"  FAIL {name}: {e}")
    print(f"\n{'FAILED' if fails else 'OK'} — {fails} failure(s)")
    raise SystemExit(1 if fails else 0)
```

- [ ] **Step 5: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 2건

- [ ] **Step 6: 커밋**

```bash
git add schema.sql trip.py test_trip.py
git commit -m "feat: SQLite 스키마 4테이블 + DB 부트스트랩"
```

---

### Task 2: LLM JSON 검증 (E1~E4)

**Files:**
- Modify: `trip.py`
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: 없음
- Produces: `ValidationError(Exception)` — `.code` 속성에 `"E1"`~`"E4"` 보유. `validate_payload(payload: dict) -> dict` — 검증 통과한 payload를 그대로 반환, 실패 시 `ValidationError`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
FORBIDDEN_SAMPLE = {
    "source": {"kind": "youtube", "raw_text": "자막"},
    "places": [{"name": "이치란", "category": "맛집", "lat": 33.59}],
}

def test_reject_forbidden_fields():
    try:
        trip.validate_payload(FORBIDDEN_SAMPLE)
        assert False, "금지 필드 lat이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E3", e.code
        assert "lat" in str(e)

def test_reject_bad_category():
    try:
        trip.validate_payload({
            "source": {"kind": "text", "raw_text": "x"},
            "places": [{"name": "이치란", "category": "밥집"}]})
        assert False, "잘못된 category가 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E2", e.code
        assert "밥집" in str(e)

def test_reject_missing_raw_text():
    try:
        trip.validate_payload({"source": {"kind": "text"}, "places": []})
        assert False, "raw_text 없이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E2", e.code

def test_accepts_minimal_valid():
    ok = trip.validate_payload({
        "source": {"kind": "text", "raw_text": "메모"},
        "places": [{"name": "이치란", "category": "맛집"}]})
    assert ok["places"][0]["name"] == "이치란"
```

- [ ] **Step 2: 실패 확인**

Run: `python test_trip.py`
Expected: 4건 FAIL — `AttributeError: module 'trip' has no attribute 'validate_payload'`

- [ ] **Step 3: 구현**

```python
FORBIDDEN = {"place_id", "lat", "lng", "address", "verify_status",
             "maps_url", "id", "created_at"}
KIND = {"youtube", "web", "text", "chat", "takeout"}
CATEGORY = {"맛집", "쇼핑", "관광", "숙소", "이동", "기타"}
SLOT = {"오전", "점심", "오후", "저녁", "밤"}
PACK_CATEGORY = {"의류", "전자", "서류", "약", "세면", "기타"}
OWNER = {"나", "아내", "공용"}

class ValidationError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code = code

def _check_forbidden(where, obj):
    hit = FORBIDDEN & set(obj)
    if hit:
        raise ValidationError("E3",
            f"{where} 에 금지 필드 {sorted(hit)} 가 있습니다. "
            "place_id·lat·lng·address·verify_status·maps_url 은 Places API만 채웁니다.")

def _enum(where, value, allowed):
    if value not in allowed:
        raise ValidationError("E2",
            f"{where} = {value!r} 은 허용되지 않습니다. 허용값: {' | '.join(sorted(allowed))}")

def validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValidationError("E2", "최상위는 객체여야 합니다.")
    src = payload.get("source")
    if not isinstance(src, dict):
        raise ValidationError("E2", "source 객체가 필요합니다.")
    if not src.get("raw_text"):
        raise ValidationError("E2", "source.raw_text 는 비어 있을 수 없습니다. 원문을 보존해야 합니다.")
    _enum("source.kind", src.get("kind"), KIND)

    places = payload.get("places") or []
    for i, p in enumerate(places):
        _check_forbidden(f"places[{i}]", p)
        if not p.get("name"):
            raise ValidationError("E2", f"places[{i}].name 이 필요합니다.")
        _enum(f"places[{i}].category", p.get("category"), CATEGORY)

    for i, it in enumerate(payload.get("itinerary") or []):
        _check_forbidden(f"itinerary[{i}]", it)
        if not isinstance(it.get("day_no"), int):
            raise ValidationError("E2", f"itinerary[{i}].day_no 는 정수여야 합니다.")
        _enum(f"itinerary[{i}].slot", it.get("slot"), SLOT)

    for i, pk in enumerate(payload.get("packing") or []):
        _check_forbidden(f"packing[{i}]", pk)
        if not pk.get("item"):
            raise ValidationError("E2", f"packing[{i}].item 이 필요합니다.")
        _enum(f"packing[{i}].category", pk.get("category", "기타"), PACK_CATEGORY)
        _enum(f"packing[{i}].owner", pk.get("owner", "공용"), OWNER)
    return payload
```

- [ ] **Step 4: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 6건

- [ ] **Step 5: 커밋**

```bash
git add trip.py test_trip.py
git commit -m "feat: LLM JSON 화이트리스트 검증 (E2·E3 환각 차단)"
```

---

### Task 3: 트랜잭션 쓰기와 이름 충돌 처리

**Files:**
- Modify: `trip.py`
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: `connect()`, `validate_payload()`, `ValidationError`
- Produces: `insert_payload(conn, payload, force=False) -> dict` — `{"source_id": int, "places_new": int, "places_merged": int, "itinerary": int, "packing": int, "warnings": list[str]}`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
BASE = {
    "source": {"kind": "youtube", "url": "https://youtu.be/a", "title": "후쿠오카",
               "raw_text": "[00:00] 이치란 라멘 추천"},
    "places": [{"name": "이치란 라멘 나카스점", "category": "맛집", "note": "돈코츠"}],
    "itinerary": [{"day_no": 3, "slot": "점심", "place_name": "이치란 라멘 나카스점"}],
    "packing": [{"item": "우산", "category": "기타", "owner": "공용", "qty": 1}],
}

def test_insert_payload_writes_all_tables():
    conn = trip.connect(":memory:")
    r = trip.insert_payload(conn, BASE)
    assert r["places_new"] == 1, r
    assert conn.execute("SELECT COUNT(*) FROM itinerary").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM packing").fetchone()[0] == 1
    assert conn.execute(
        "SELECT verify_status FROM place").fetchone()[0] == "pending"

def test_duplicate_name_appends_note():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, BASE)
    second = {"source": {"kind": "web", "url": "https://b.com", "raw_text": "또 추천"},
              "places": [{"name": "이치란 라멘 나카스점", "category": "맛집",
                          "note": "두번째 영상에서도 추천"}]}
    r = trip.insert_payload(conn, second)
    assert r["places_new"] == 0 and r["places_merged"] == 1, r
    assert conn.execute("SELECT COUNT(*) FROM place").fetchone()[0] == 1
    note = conn.execute("SELECT note FROM place").fetchone()[0]
    assert "돈코츠" in note and "두번째" in note, note

def test_force_creates_separate_row():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, BASE)
    trip.insert_payload(conn, BASE, force=True)
    assert conn.execute("SELECT COUNT(*) FROM place").fetchone()[0] == 2

def test_reject_unknown_place_name():
    conn = trip.connect(":memory:")
    bad = {"source": {"kind": "text", "raw_text": "x"}, "places": [],
           "itinerary": [{"day_no": 1, "slot": "오전", "place_name": "없는집"}]}
    try:
        trip.insert_payload(conn, bad)
        assert False, "미해석 place_name이 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E4", e.code
        assert "없는집" in str(e)

def test_rollback_on_partial_failure():
    conn = trip.connect(":memory:")
    bad = {"source": {"kind": "text", "raw_text": "원문"},
           "places": [{"name": "좋은집", "category": "맛집"}],
           "itinerary": [{"day_no": 1, "slot": "오전", "place_name": "없는집"}]}
    try:
        trip.insert_payload(conn, bad)
    except trip.ValidationError:
        pass
    assert conn.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM place").fetchone()[0] == 0
```

- [ ] **Step 2: 실패 확인**

Run: `python test_trip.py`
Expected: 5건 FAIL — `insert_payload` 없음

- [ ] **Step 3: 구현**

```python
def insert_payload(conn, payload, force=False):
    validate_payload(payload)
    warnings = []
    result = {"places_new": 0, "places_merged": 0, "itinerary": 0,
              "packing": 0, "warnings": warnings}
    try:
        conn.execute("BEGIN")
        src = payload["source"]
        cur = conn.execute(
            "INSERT INTO source (kind, url, title, raw_text) VALUES (?,?,?,?)",
            (src["kind"], src.get("url"), src.get("title"), src["raw_text"]))
        source_id = cur.lastrowid
        result["source_id"] = source_id

        name_to_id = {}
        for p in payload.get("places") or []:
            existing = None if force else conn.execute(
                "SELECT id, note FROM place WHERE name = ?", (p["name"],)).fetchone()
            if existing:
                pid, old_note = existing
                new_note = p.get("note")
                if new_note and new_note not in (old_note or ""):
                    merged = f"{old_note}\n{new_note}" if old_note else new_note
                    conn.execute("UPDATE place SET note = ? WHERE id = ?", (merged, pid))
                warnings.append(f"이미 존재: {p['name']} (id={pid}) — note 추가함")
                result["places_merged"] += 1
            else:
                cur = conn.execute(
                    "INSERT INTO place (name, category, note, source_id) VALUES (?,?,?,?)",
                    (p["name"], p["category"], p.get("note"), source_id))
                pid = cur.lastrowid
                result["places_new"] += 1
            name_to_id[p["name"]] = pid

        for it in payload.get("itinerary") or []:
            pname = it.get("place_name")
            pid = None
            if pname:
                pid = name_to_id.get(pname)
                if pid is None:
                    row = conn.execute(
                        "SELECT id FROM place WHERE name = ?", (pname,)).fetchone()
                    pid = row[0] if row else None
                if pid is None:
                    raise ValidationError("E4",
                        f"itinerary 의 place_name {pname!r} 을 places 에서도 DB 에서도 찾을 수 없습니다.")
            conn.execute(
                "INSERT INTO itinerary (day_no, date, slot, seq, place_id, memo) "
                "VALUES (?,?,?,?,?,?)",
                (it["day_no"], it.get("date"), it["slot"], it.get("seq", 0),
                 pid, it.get("memo")))
            result["itinerary"] += 1

        for pk in payload.get("packing") or []:
            conn.execute(
                "INSERT INTO packing (item, category, qty, owner) VALUES (?,?,?,?)",
                (pk["item"], pk.get("category", "기타"),
                 pk.get("qty", 1), pk.get("owner", "공용")))
            result["packing"] += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result
```

- [ ] **Step 4: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 11건

- [ ] **Step 5: 커밋**

```bash
git add trip.py test_trip.py
git commit -m "feat: 트랜잭션 쓰기 + 이름 충돌 note 병합 (E4·E11)"
```

---

### Task 4: Takeout CSV 임포트

**Files:**
- Modify: `trip.py`
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: `connect()`, `insert_payload()`
- Produces: `import_takeout(conn, csv_path) -> dict` — `insert_payload` 와 동일한 결과 dict

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import tempfile, os as _os

TAKEOUT_CSV = (
    "Title,Note,URL,Comment\n"
    "이치란 라멘 나카스점,줄 서더라도 가볼 것,https://maps.app.goo.gl/aaa,\n"
    "캐널시티 하카타,쇼핑몰,https://maps.app.goo.gl/bbb,분수쇼 시간 확인\n")

def test_takeout_csv_parse():
    conn = trip.connect(":memory:")
    fd, path = tempfile.mkstemp(suffix=".csv")
    _os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(TAKEOUT_CSV)
    try:
        r = trip.import_takeout(conn, path)
    finally:
        _os.unlink(path)
    assert r["places_new"] == 2, r
    rows = dict(conn.execute("SELECT name, note FROM place").fetchall())
    assert rows["이치란 라멘 나카스점"] == "줄 서더라도 가볼 것", rows
    kinds = [r[0] for r in conn.execute("SELECT kind FROM source").fetchall()]
    assert kinds == ["takeout", "takeout"], kinds
    assert conn.execute(
        "SELECT verify_status FROM place WHERE name='캐널시티 하카타'"
    ).fetchone()[0] == "pending"
```

- [ ] **Step 2: 실패 확인**

Run: `python test_trip.py`
Expected: FAIL — `import_takeout` 없음

- [ ] **Step 3: 구현**

Takeout CSV는 좌표가 없고 카테고리도 없다. 전부 `기타`로 넣고 `verify` 단계가 사실을 채운다.

```python
import csv

def import_takeout(conn, csv_path):
    total = {"places_new": 0, "places_merged": 0, "itinerary": 0,
             "packing": 0, "warnings": []}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = (row.get("Title") or "").strip()
            if not title:
                continue
            note = (row.get("Note") or "").strip()
            comment = (row.get("Comment") or "").strip()
            raw = "\n".join(x for x in (title, note, comment) if x)
            r = insert_payload(conn, {
                "source": {"kind": "takeout", "url": (row.get("URL") or "").strip() or None,
                           "title": title, "raw_text": raw},
                "places": [{"name": title, "category": "기타", "note": note or None}],
            })
            for k in ("places_new", "places_merged"):
                total[k] += r[k]
            total["warnings"].extend(r["warnings"])
    return total
```

- [ ] **Step 4: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 12건

- [ ] **Step 5: 커밋**

```bash
git add trip.py test_trip.py
git commit -m "feat: Google Takeout CSV 임포트 (저장 목록 부트스트랩)"
```

---

### Task 5: 유튜브 자막 추출 이식

**Files:**
- Create: `youtube.py`
- Create: `requirements.txt`
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: 없음
- Produces: `extract_youtube_id(url) -> str|None`, `format_time(seconds) -> str`, `merge_transcripts(srt, interval_sec=30) -> str`, `get_transcript(video_id, api=None) -> str|None`

원본: `C:\GIT\Moons_Company\agents\scrap_agent.py`. `async` 제거하고 API 객체를 주입 가능하게 바꾼다(테스트가 네트워크를 안 타도록).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import youtube

def test_extract_youtube_id():
    assert youtube.extract_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube.extract_youtube_id(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3s") == "dQw4w9WgXcQ"
    assert youtube.extract_youtube_id("https://naver.com") is None

def test_merge_transcripts_groups_by_30s():
    srt = [{"start": 0.0, "text": "가"}, {"start": 10.0, "text": "나"},
           {"start": 35.0, "text": "다"}]
    out = youtube.merge_transcripts(srt)
    assert out == "[00:00] 가 나\n[00:35] 다", repr(out)

def test_merge_transcripts_empty():
    assert youtube.merge_transcripts([]) == ""

def test_get_transcript_uses_injected_api():
    class FakeApi:
        def fetch(self, vid, languages=None):
            return [{"start": 0.0, "text": "안녕"}]
    assert youtube.get_transcript("x", api=FakeApi()) == "[00:00] 안녕"

def test_get_transcript_returns_none_on_total_failure():
    class DeadApi:
        def fetch(self, vid, languages=None):
            raise RuntimeError("no captions")
        def list(self, vid):
            raise RuntimeError("no list")
    assert youtube.get_transcript("x", api=DeadApi()) is None
```

- [ ] **Step 2: 실패 확인**

Run: `python test_trip.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'youtube'`

- [ ] **Step 3: `youtube.py` 구현**

```python
"""유튜브 자막 추출. 원본: Moons_Company/agents/scrap_agent.py (async 제거·API 주입화)."""
import re

def format_time(seconds):
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"

def extract_youtube_id(url):
    m = re.search(
        r'(https?://)?(www\.)?'
        r'(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|shorts/|live/|.+\?v=)?([^&=%\?/]{11})', url or "")
    return m.group(6) if m else None

def _attr(item, name):
    if hasattr(item, name):
        return getattr(item, name)
    if isinstance(item, dict):
        return item.get(name)
    return None

def merge_transcripts(srt, interval_sec=30):
    """30초 단위로 병합해 텍스트 밀도를 높이고 토큰을 아낀다."""
    if not srt:
        return ""
    merged, chunk = [], []
    current_start = _attr(srt[0], "start") or 0.0
    for item in srt:
        start = _attr(item, "start") or 0.0
        text = _attr(item, "text") or ""
        if not chunk:
            current_start, chunk = start, [text]
        elif start - current_start >= interval_sec:
            merged.append(f"[{format_time(current_start)}] {' '.join(chunk)}")
            current_start, chunk = start, [text]
        else:
            chunk.append(text)
    if chunk:
        merged.append(f"[{format_time(current_start)}] {' '.join(chunk)}")
    return "\n".join(merged)

def get_transcript(video_id, api=None):
    """3단 폴백: 수동 ko/en → 목록 조회 → en을 ko로 번역. 전부 실패하면 None."""
    if api is None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
        except Exception as e:
            print(f"[youtube] 라이브러리 연동 실패: {e}")
            return None
    try:
        return merge_transcripts(api.fetch(video_id, languages=['ko', 'en']))
    except Exception as e1:
        print(f"[youtube] 자막 1차 실패: {e1}")
    try:
        listing = api.list(video_id)
    except Exception as e:
        print(f"[youtube] 자막 목록 조회 실패: {e}")
        return None
    try:
        return merge_transcripts(listing.find_transcript(['ko', 'en']).fetch())
    except Exception as e2:
        print(f"[youtube] 자막 2차 실패: {e2}")
    try:
        return merge_transcripts(listing.find_transcript(['en']).translate('ko').fetch())
    except Exception as e3:
        print(f"[youtube] 자막 3차 실패: {e3}")
        return None
```

`requirements.txt`:

```
youtube-transcript-api>=1.2.4
```

- [ ] **Step 4: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 17건

- [ ] **Step 5: 커밋**

```bash
git add youtube.py requirements.txt test_trip.py
git commit -m "feat: 유튜브 자막 3단 폴백 이식 (scrap_agent.py 출처)"
```

---

### Task 6: Places API 조회와 matched 판정

**Files:**
- Create: `places.py`
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: 없음
- Produces: `normalize(name) -> str`, `judge(query, candidates) -> tuple[str, dict|None]` (status, chosen), `maps_url(place_id) -> str`, `search(query, api_key, fetch=None) -> list[dict]`, `MissingApiKey(Exception)`

스펙 §3.4.1 판정 규칙을 그대로 구현한다. **결과 2건 이상이면 무조건 `ambiguous`.**

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import places

def test_normalize_strips_noise():
    assert places.normalize("이치란 라멘 (나카스점)") == "이치란라멘나카스점"
    assert places.normalize("Ichiran・Nakasu") == "ichirannakasu"

def test_judge_not_found():
    assert places.judge("이치란", [])[0] == "not_found"

def test_judge_multiple_is_always_ambiguous():
    cands = [{"name": "이치란 나카스점"}, {"name": "이치란 텐진점"}]
    status, chosen = places.judge("이치란 나카스점", cands)
    assert status == "ambiguous", status
    assert chosen == cands[0]

def test_judge_single_substring_is_matched():
    status, chosen = places.judge("이치란 라멘 나카스점",
                                  [{"name": "이치란 라멘 (나카스점)"}])
    assert status == "matched", status

def test_judge_single_mismatch_is_ambiguous():
    status, _ = places.judge("이치란 라멘", [{"name": "스타벅스 하카타점"}])
    assert status == "ambiguous", status

def test_maps_url_format():
    assert places.maps_url("ChIJabc") == \
        "https://www.google.com/maps/place/?q=place_id:ChIJabc"

def test_search_uses_injected_fetch_and_no_billing_fields():
    seen = {}
    def fake_fetch(url, body, headers):
        seen["headers"] = headers
        return {"places": [{"id": "ChIJx", "displayName": {"text": "이치란"},
                            "formattedAddress": "후쿠오카",
                            "location": {"latitude": 33.5, "longitude": 130.4}}]}
    out = places.search("이치란", "KEY", fetch=fake_fetch)
    mask = seen["headers"]["X-Goog-FieldMask"]
    for billing_trap in ("rating", "opening", "review", "photo"):
        assert billing_trap not in mask, f"과금 등급을 올리는 필드 {billing_trap} 포함됨: {mask}"
    assert out[0]["place_id"] == "ChIJx" and out[0]["lat"] == 33.5, out

def test_search_without_key_raises():
    try:
        places.search("x", "", fetch=lambda *a: {})
        assert False, "키 없이 통과했다"
    except places.MissingApiKey:
        pass
```

- [ ] **Step 2: 실패 확인**

Run: `python test_trip.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'places'`

- [ ] **Step 3: 구현**

```python
"""Google Places API (New) Text Search 조회와 이름 대조."""
import json, re, urllib.request

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
# 과금 등급 주의: rating·opening_hours·reviews·photos 를 넣으면 Enterprise 로 올라간다.
FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.location"
TIMEOUT_SEC = 10

class MissingApiKey(Exception):
    pass

def normalize(name):
    return re.sub(r"[\s()（）・·,，.\-–—]", "", (name or "")).lower()

def maps_url(place_id):
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"

def judge(query, candidates):
    """스펙 §3.4.1. 2건 이상이면 무조건 ambiguous — 1순위 자동 채택 금지."""
    if not candidates:
        return "not_found", None
    if len(candidates) > 1:
        return "ambiguous", candidates[0]
    got = candidates[0]
    a, b = normalize(query), normalize(got.get("name"))
    if a and b and (a in b or b in a):
        return "matched", got
    return "ambiguous", got

def _real_fetch(url, body, headers):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))

def search(query, api_key, fetch=None):
    if not api_key:
        raise MissingApiKey(
            "GOOGLE_MAPS_API_KEY 가 없습니다. "
            "https://console.cloud.google.com/apis/credentials 에서 발급 후 .env 에 넣으세요.")
    fetch = fetch or _real_fetch
    data = fetch(ENDPOINT,
                 {"textQuery": query, "languageCode": "ko", "maxResultCount": 5},
                 {"Content-Type": "application/json",
                  "X-Goog-Api-Key": api_key,
                  "X-Goog-FieldMask": FIELD_MASK})
    out = []
    for p in (data or {}).get("places", []):
        loc = p.get("location") or {}
        out.append({
            "place_id": p.get("id"),
            "name": (p.get("displayName") or {}).get("text"),
            "address": p.get("formattedAddress"),
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
        })
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 25건

- [ ] **Step 5: 커밋**

```bash
git add places.py test_trip.py
git commit -m "feat: Places API 조회 + matched 판정 (다중 결과는 무조건 ambiguous)"
```

---

### Task 7: verify 배치와 조회 커맨드

**Files:**
- Modify: `trip.py`
- Modify: `test_trip.py`
- Create: `.env.example`

**Interfaces:**
- Consumes: `places.search`, `places.judge`, `places.maps_url`, `connect()`
- Produces: `verify_places(conn, api_key, limit=50, search=None) -> dict` — `{"matched": int, "ambiguous": int, "not_found": int, "failed": int}`. `mark_saved(conn, ids) -> int`. `list_places(conn, category=None, status=None) -> list[sqlite3.Row]`. `list_plan(conn, day=None) -> list[sqlite3.Row]`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def _seed_places(conn, names):
    for n in names:
        trip.insert_payload(conn, {
            "source": {"kind": "text", "raw_text": n},
            "places": [{"name": n, "category": "맛집"}]})

def test_verify_status_transitions():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["이치란 라멘 나카스점", "애매한집", "없는집"])
    def fake_search(query, api_key, fetch=None):
        if query == "이치란 라멘 나카스점":
            return [{"place_id": "ChIJ1", "name": "이치란 라멘 (나카스점)",
                     "address": "후쿠오카", "lat": 33.5, "lng": 130.4}]
        if query == "애매한집":
            return [{"place_id": "ChIJ2", "name": "애매한집 A", "address": "a",
                     "lat": 1.0, "lng": 2.0},
                    {"place_id": "ChIJ3", "name": "애매한집 B", "address": "b",
                     "lat": 3.0, "lng": 4.0}]
        return []
    r = trip.verify_places(conn, "KEY", search=fake_search)
    assert r == {"matched": 1, "ambiguous": 1, "not_found": 1, "failed": 0}, r
    row = conn.execute("SELECT verify_status, place_id, lat, maps_url FROM place "
                       "WHERE name='이치란 라멘 나카스점'").fetchone()
    assert row[0] == "matched" and row[1] == "ChIJ1" and row[2] == 33.5
    assert row[3] == "https://www.google.com/maps/place/?q=place_id:ChIJ1"
    amb = conn.execute("SELECT maps_url FROM place WHERE name='애매한집'").fetchone()[0]
    assert amb, "ambiguous 여도 maps_url 은 생성되어야 한다"

def test_verify_keeps_pending_on_api_failure():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["실패집"])
    def dead_search(query, api_key, fetch=None):
        raise RuntimeError("503")
    r = trip.verify_places(conn, "KEY", search=dead_search)
    assert r["failed"] == 1, r
    assert conn.execute("SELECT verify_status FROM place").fetchone()[0] == "pending"

def test_verify_respects_limit():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["a집", "b집", "c집"])
    calls = []
    def counting_search(query, api_key, fetch=None):
        calls.append(query); return []
    trip.verify_places(conn, "KEY", limit=2, search=counting_search)
    assert len(calls) == 2, calls

def test_mark_saved():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["가게"])
    pid = conn.execute("SELECT id FROM place").fetchone()[0]
    assert trip.mark_saved(conn, [pid]) == 1
    assert conn.execute("SELECT saved_to_mymaps FROM place").fetchone()[0] == 1
```

- [ ] **Step 2: 실패 확인**

Run: `python test_trip.py`
Expected: 4건 FAIL — `verify_places` 없음

- [ ] **Step 3: 구현** (`trip.py`에 추가)

```python
import places as places_mod

def verify_places(conn, api_key, limit=50, search=None):
    search = search or places_mod.search
    stats = {"matched": 0, "ambiguous": 0, "not_found": 0, "failed": 0}
    rows = conn.execute(
        "SELECT id, name FROM place WHERE verify_status = 'pending' "
        "ORDER BY id LIMIT ?", (limit,)).fetchall()
    for pid, name in rows:
        try:
            candidates = search(name, api_key)
        except places_mod.MissingApiKey:
            raise
        except Exception as e:
            print(f"[verify] E7 조회 실패 (pending 유지): {name} — {e}")
            stats["failed"] += 1
            continue
        status, chosen = places_mod.judge(name, candidates)
        if chosen:
            conn.execute(
                "UPDATE place SET verify_status=?, place_id=?, name_verified=?, "
                "address=?, lat=?, lng=?, maps_url=? WHERE id=?",
                (status, chosen.get("place_id"), chosen.get("name"),
                 chosen.get("address"), chosen.get("lat"), chosen.get("lng"),
                 places_mod.maps_url(chosen.get("place_id")), pid))
        else:
            conn.execute("UPDATE place SET verify_status=? WHERE id=?", (status, pid))
        conn.commit()
        stats[status] += 1
    return stats

def mark_saved(conn, ids):
    cur = conn.executemany(
        "UPDATE place SET saved_to_mymaps = 1 WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    return cur.rowcount

def list_places(conn, category=None, status=None):
    conn.row_factory = sqlite3.Row
    sql = ("SELECT id, name, name_verified, category, verify_status, "
           "saved_to_mymaps, maps_url, note FROM place WHERE 1=1")
    args = []
    if category:
        sql += " AND category = ?"; args.append(category)
    if status:
        sql += " AND verify_status = ?"; args.append(status)
    return conn.execute(sql + " ORDER BY category, name", args).fetchall()

def list_plan(conn, day=None):
    conn.row_factory = sqlite3.Row
    sql = ("SELECT i.day_no, i.slot, i.seq, i.memo, p.name AS place_name, p.maps_url "
           "FROM itinerary i LEFT JOIN place p ON p.id = i.place_id WHERE 1=1")
    args = []
    if day:
        sql += " AND i.day_no = ?"; args.append(day)
    return conn.execute(sql + " ORDER BY i.day_no, i.seq", args).fetchall()
```

**주의:** `verify_places` 는 `place_id UNIQUE` 충돌 가능성이 있다(같은 장소가 다른 이름으로 두 번 들어온 경우). `sqlite3.IntegrityError` 는 `except Exception` 에 걸려 `failed` 로 집계되고 `pending` 이 유지된다 — 데이터가 깨지지 않으므로 이번 사이클에서는 이 동작을 수용한다.

`.env.example`:

```
GOOGLE_MAPS_API_KEY=
TODOIST_TOKEN=
TODOIST_PROJECT_ID=
```

- [ ] **Step 4: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 29건

- [ ] **Step 5: 커밋**

```bash
git add trip.py test_trip.py .env.example
git commit -m "feat: verify 배치 + 조회 커맨드 (E7 실패 시 pending 유지)"
```

---

### Task 8: export.py — 지도 링크와 Todoist

**Files:**
- Create: `export.py`
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: `trip.connect`, `trip.list_places`
- Produces: `maps_links(conn) -> list[sqlite3.Row]` (확인 대기분만), `build_todoist_tasks(conn) -> list[dict]` — `{"table": str, "row_id": int, "content": str, "labels": list[str]}`, `push_todoist(conn, token, project_id, dry_run=True, post=None) -> dict`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import export

def test_maps_links_only_unconfirmed():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["확인필요집", "이미저장집"])
    conn.execute("UPDATE place SET verify_status='matched' WHERE name='확인필요집'")
    conn.execute("UPDATE place SET verify_status='matched', saved_to_mymaps=1 "
                 "WHERE name='이미저장집'")
    conn.commit()
    names = [r["name"] for r in export.maps_links(conn)]
    assert names == ["확인필요집"], names

def test_build_todoist_tasks():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, BASE)
    tasks = export.build_todoist_tasks(conn)
    contents = sorted(t["content"] for t in tasks)
    assert contents == ["3일차 [점심] 이치란 라멘 나카스점", "우산 x1"], contents
    pack = [t for t in tasks if t["table"] == "packing"][0]
    assert pack["labels"] == ["공용"], pack

def test_todoist_idempotent():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, BASE)
    posted = []
    def fake_post(token, project_id, task):
        posted.append(task["content"]); return {"id": f"t{len(posted)}"}
    r1 = export.push_todoist(conn, "TOK", "P1", dry_run=False, post=fake_post)
    assert r1["created"] == 2, r1
    r2 = export.push_todoist(conn, "TOK", "P1", dry_run=False, post=fake_post)
    assert r2["created"] == 0 and r2["skipped"] == 2, r2
    assert len(posted) == 2, posted

def test_todoist_dry_run_posts_nothing():
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, BASE)
    def boom(*a, **k):
        raise AssertionError("dry-run 인데 실제 푸시가 일어났다")
    r = export.push_todoist(conn, "TOK", "P1", dry_run=True, post=boom)
    assert r["would_create"] == 2, r
    assert conn.execute(
        "SELECT COUNT(*) FROM packing WHERE todoist_task_id IS NOT NULL"
    ).fetchone()[0] == 0
```

- [ ] **Step 2: 실패 확인**

Run: `python test_trip.py`
Expected: 4건 FAIL — `ModuleNotFoundError: No module named 'export'`

- [ ] **Step 3: 구현**

```python
"""DB 읽기 전용 출력 어댑터. todoist_task_id 외 어떤 컬럼도 쓰지 않는다."""
import json, sqlite3, urllib.request
import trip

TODOIST_URL = "https://api.todoist.com/rest/v2/tasks"
TIMEOUT_SEC = 10

def maps_links(conn):
    """내 지도에 아직 저장 안 한 장소만. 확인 순서는 ambiguous 가 먼저."""
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT id, name, name_verified, verify_status, maps_url, note "
        "FROM place WHERE saved_to_mymaps = 0 "
        "ORDER BY CASE verify_status WHEN 'ambiguous' THEN 0 WHEN 'not_found' "
        "THEN 1 WHEN 'pending' THEN 2 ELSE 3 END, name").fetchall()

def build_todoist_tasks(conn):
    conn.row_factory = sqlite3.Row
    tasks = []
    for r in conn.execute(
            "SELECT id, item, qty, owner FROM packing WHERE todoist_task_id IS NULL"):
        tasks.append({"table": "packing", "row_id": r["id"],
                      "content": f"{r['item']} x{r['qty']}", "labels": [r["owner"]]})
    for r in conn.execute(
            "SELECT i.id, i.day_no, i.slot, p.name AS place_name FROM itinerary i "
            "LEFT JOIN place p ON p.id = i.place_id WHERE i.todoist_task_id IS NULL"):
        label = r["place_name"] or "(장소 미정)"
        tasks.append({"table": "itinerary", "row_id": r["id"],
                      "content": f"{r['day_no']}일차 [{r['slot']}] {label}",
                      "labels": [f"{r['day_no']}일차"]})
    return tasks

def _real_post(token, project_id, task):
    body = {"content": task["content"], "project_id": project_id,
            "labels": task["labels"]}
    req = urllib.request.Request(
        TODOIST_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))

def push_todoist(conn, token, project_id, dry_run=True, post=None):
    post = post or _real_post
    tasks = build_todoist_tasks(conn)
    total = conn.execute(
        "SELECT (SELECT COUNT(*) FROM packing) + (SELECT COUNT(*) FROM itinerary)"
    ).fetchone()[0]
    if dry_run:
        for t in tasks:
            print(f"  [dry-run] {t['content']}  @{','.join(t['labels'])}")
        return {"would_create": len(tasks), "skipped": total - len(tasks)}
    created = 0
    for t in tasks:
        resp = post(token, project_id, t)
        conn.execute(f"UPDATE {t['table']} SET todoist_task_id = ? WHERE id = ?",
                     (str(resp["id"]), t["row_id"]))
        conn.commit()
        created += 1
    return {"created": created, "skipped": total - created}
```

`build_todoist_tasks` 의 `f"UPDATE {t['table']}"` 는 SQL 인젝션처럼 보이지만 `table` 값은 이 파일 안에서 리터럴 `"packing"`/`"itinerary"` 로만 생성된다. 외부 입력이 닿지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 33건

- [ ] **Step 5: 커밋**

```bash
git add export.py test_trip.py
git commit -m "feat: 지도 확인 링크 + Todoist 멱등 푸시 (E10)"
```

---

### Task 9: CLI 엔트리포인트

**Files:**
- Modify: `trip.py`
- Modify: `export.py`
- Modify: `test_trip.py`

**Interfaces:**
- Consumes: 위 전부
- Produces: `python trip.py <add|import-takeout|verify|list|plan|mark-saved>`, `python export.py <maps-links|todoist>`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_load_env_reads_dotenv():
    import tempfile, os as _os
    fd, path = tempfile.mkstemp()
    _os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 주석\nGOOGLE_MAPS_API_KEY=abc123\nTODOIST_TOKEN=\n")
    try:
        env = trip.load_env(path)
    finally:
        _os.unlink(path)
    assert env["GOOGLE_MAPS_API_KEY"] == "abc123", env
    assert env.get("TODOIST_TOKEN") == "", env

def test_cmd_add_reads_stdin_json():
    import io, json as _json
    conn = trip.connect(":memory:")
    stream = io.StringIO(_json.dumps(BASE))
    code = trip.cmd_add(conn, stream, force=False)
    assert code == 0, code
    assert conn.execute("SELECT COUNT(*) FROM place").fetchone()[0] == 1

def test_cmd_add_returns_2_on_bad_json():
    import io
    conn = trip.connect(":memory:")
    assert trip.cmd_add(conn, io.StringIO("{not json"), force=False) == 2

def test_cmd_add_returns_2_on_forbidden_field():
    import io, json as _json
    conn = trip.connect(":memory:")
    assert trip.cmd_add(conn, io.StringIO(_json.dumps(FORBIDDEN_SAMPLE)),
                        force=False) == 2
```

- [ ] **Step 2: 실패 확인**

Run: `python test_trip.py`
Expected: 4건 FAIL — `load_env` 없음

- [ ] **Step 3: 구현** (`trip.py` 하단)

```python
def load_env(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in ("GOOGLE_MAPS_API_KEY", "TODOIST_TOKEN", "TODOIST_PROJECT_ID"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env

def cmd_add(conn, stream, force=False):
    raw = stream.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR E1: JSON 파싱 실패 — {e}\n  받은 내용 앞부분: {raw[:200]!r}",
              file=sys.stderr)
        return 2
    try:
        r = insert_payload(conn, payload, force=force)
    except ValidationError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 2
    for w in r["warnings"]:
        print(f"WARN {w}", file=sys.stderr)
    print(f"OK source={r['source_id']} 장소 신규 {r['places_new']} / 병합 "
          f"{r['places_merged']}, 일정 {r['itinerary']}, 준비물 {r['packing']}")
    return 0

def main(argv=None):
    ap = argparse.ArgumentParser(prog="trip", description="여행 자료 수집·검증 CLI")
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="stdin 으로 정규화 JSON 을 받아 저장")
    p_add.add_argument("--force", action="store_true", help="동명 장소도 새 행으로")
    p_imp = sub.add_parser("import-takeout", help="Google Takeout CSV 임포트")
    p_imp.add_argument("csv_path")
    p_ver = sub.add_parser("verify", help="pending 장소를 Places API 로 검증")
    p_ver.add_argument("--limit", type=int, default=50)
    p_list = sub.add_parser("list", help="장소 조회")
    p_list.add_argument("--category"); p_list.add_argument("--status")
    p_plan = sub.add_parser("plan", help="일정 조회")
    p_plan.add_argument("--day", type=int)
    p_mark = sub.add_parser("mark-saved", help="내 지도 저장 완료 표시")
    p_mark.add_argument("ids", nargs="+", type=int)
    args = ap.parse_args(argv)

    conn = connect(args.db)
    if args.cmd == "add":
        return cmd_add(conn, sys.stdin, force=args.force)
    if args.cmd == "import-takeout":
        r = import_takeout(conn, args.csv_path)
        for w in r["warnings"]:
            print(f"WARN {w}", file=sys.stderr)
        print(f"OK 장소 신규 {r['places_new']} / 병합 {r['places_merged']}")
        return 0
    if args.cmd == "verify":
        env = load_env()
        try:
            r = verify_places(conn, env.get("GOOGLE_MAPS_API_KEY", ""), limit=args.limit)
        except places_mod.MissingApiKey as e:
            print(f"ERROR E6: {e}", file=sys.stderr)
            return 1
        print(f"OK matched {r['matched']} / ambiguous {r['ambiguous']} / "
              f"not_found {r['not_found']} / failed {r['failed']}")
        return 0
    if args.cmd == "list":
        for r in list_places(conn, args.category, args.status):
            flag = "✓" if r["saved_to_mymaps"] else " "
            print(f"{flag} [{r['id']:>3}] {r['verify_status']:<10} {r['category']:<4} "
                  f"{r['name']}")
        return 0
    if args.cmd == "plan":
        for r in list_plan(conn, args.day):
            print(f"{r['day_no']}일차 [{r['slot']}] {r['place_name'] or '(미정)'} "
                  f"{r['memo'] or ''}".rstrip())
        return 0
    if args.cmd == "mark-saved":
        print(f"OK {mark_saved(conn, args.ids)} 건 저장 완료 표시")
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
```

`trip.py` 상단 import에 `json, sys, argparse` 를 추가한다.

`export.py` 하단:

```python
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="export", description="여행 DB 출력 어댑터")
    ap.add_argument("--db", default=trip.DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("maps-links", help="내 지도에 저장할 링크 목록")
    p_td = sub.add_parser("todoist", help="준비물·일정 체크리스트 푸시")
    p_td.add_argument("--dry-run", action="store_true", default=False)
    args = ap.parse_args(argv)
    conn = trip.connect(args.db)

    if args.cmd == "maps-links":
        for r in maps_links(conn):
            verified = r["name_verified"] or ""
            mark = "⚠️ " if r["verify_status"] != "matched" else "   "
            print(f"{mark}[{r['id']:>3}] {r['verify_status']:<10} {r['name']}")
            if verified and verified != r["name"]:
                print(f"        구글 표기: {verified}")
            print(f"        {r['maps_url'] or '(링크 없음 — verify 필요)'}")
        return 0

    env = trip.load_env()
    token, project = env.get("TODOIST_TOKEN"), env.get("TODOIST_PROJECT_ID")
    if not args.dry_run and not (token and project):
        print("ERROR E6: TODOIST_TOKEN / TODOIST_PROJECT_ID 가 .env 에 없습니다.",
              file=__import__("sys").stderr)
        return 1
    r = push_todoist(conn, token, project, dry_run=args.dry_run)
    print(f"OK {r}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `python test_trip.py`
Expected: PASS 37건

- [ ] **Step 5: 스모크 테스트**

```bash
python trip.py --db data/smoke.db list
python export.py --db data/smoke.db maps-links
rm -f data/smoke.db
```
Expected: 빈 결과, 예외 없음, 종료코드 0

- [ ] **Step 6: 커밋**

```bash
git add trip.py export.py test_trip.py
git commit -m "feat: CLI 엔트리포인트 (trip add/verify/list/plan, export maps-links/todoist)"
```

---

### Task 10: LLM 계약 문서와 프로젝트 규약

**Files:**
- Create: `.claude/commands/trip.md`
- Create: `CLAUDE.md`
- Create: `README.md`

**Interfaces:**
- Consumes: 없음 (문서)
- Produces: `/trip` 슬래시 커맨드

- [ ] **Step 1: `.claude/commands/trip.md` 작성**

Claude가 URL/텍스트/자연어를 받아 정규화 JSON을 만들고 `python trip.py add` 에 파이프하는 절차를 기술한다. 반드시 포함할 것:
- 유튜브 URL이면 `python -c "import youtube; print(youtube.get_transcript(youtube.extract_youtube_id('<URL>')))"` 로 자막을 먼저 확보
- 자막이 `None` 이면 WARN E5 를 사용자에게 알리고 텍스트 붙여넣기를 요청
- 출력 JSON 스키마 (스펙 §4.2 전문)
- 금지 필드 목록과 이유 (스펙 §4.3)
- enum 허용값 전체
- `trip.py add` 가 exit 2 를 내면 stderr 메시지를 읽고 **스스로 고쳐서 재시도**

- [ ] **Step 2: `CLAUDE.md` 작성 (200줄 이하)**

안티패턴 중심. 포함할 것:
- 절대규칙: LLM은 추출·분류만, 사실(좌표·place_id)은 API만 채운다
- 빌드/테스트 명령: `python test_trip.py`
- 외부 패키지 추가 금지 (`youtube-transcript-api` 하나만)
- `git add .` 금지, 자기 파일만 커밋
- `.env` 커밋 금지
- 스펙·계획 경로 안내

- [ ] **Step 3: `README.md` 작성**

설치 → 키 발급 → Takeout 임포트 → `/trip add` → `verify` → `maps-links` → `mark-saved` 순서의 실사용 절차.

- [ ] **Step 4: 테스트 재확인**

Run: `python test_trip.py`
Expected: PASS 37건 (문서 추가는 테스트에 영향 없음)

- [ ] **Step 5: 커밋**

```bash
git add .claude/commands/trip.md CLAUDE.md README.md
git commit -m "docs: /trip LLM 계약 + 프로젝트 규약 + 사용 절차"
```

---

## 완료 검증

스펙 §9의 완료 기준 7개를 순서대로 확인한다.

- [ ] `python test_trip.py` 전부 통과 (37건)
- [ ] Takeout CSV 임포트로 `place` 행 생성 — Task 4 테스트가 커버
- [ ] `verify` 후 `verify_status` 갱신 — Task 7 테스트가 커버
- [ ] `maps-links` 링크가 의도한 장소를 연다 — **실키 필요, 사용자 수동 확인**
- [ ] 유튜브 URL 1건 실제 수집 — **네트워크 필요, 사용자 수동 확인**
- [ ] `export.py todoist --dry-run` 출력 — Task 8 테스트가 커버
- [ ] `lat` 포함 JSON 거부 — Task 2 테스트가 커버

4·5번은 실제 API 키와 네트워크가 필요하므로 구현 완료 후 사용자가 키를 넣고 확인한다.
