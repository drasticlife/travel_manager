"""travel manager 전체 테스트. 프레임워크 없음. 실행: python test_trip.py"""
import sqlite3
import sys

# Windows 콘솔 기본 cp949 는 em dash·기호를 못 찍는다. utf-8 로 고정.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import trip


# ---------- Task 1: 스키마 ----------

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


# ---------- Task 2: LLM JSON 검증 ----------

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


# ---------- Task 3: 트랜잭션 쓰기 ----------

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
    assert conn.execute("SELECT verify_status FROM place").fetchone()[0] == "pending"


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


# ---------- Task 4: Takeout CSV ----------

import os as _os
import tempfile

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
    kinds = [x[0] for x in conn.execute("SELECT kind FROM source").fetchall()]
    assert kinds == ["takeout", "takeout"], kinds
    assert conn.execute(
        "SELECT verify_status FROM place WHERE name='캐널시티 하카타'"
    ).fetchone()[0] == "pending"


# ---------- Task 5: 유튜브 자막 ----------

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


# ---------- Task 6: Places API ----------

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
        assert billing_trap not in mask, \
            f"과금 등급을 올리는 필드 {billing_trap} 포함됨: {mask}"
    assert out[0]["place_id"] == "ChIJx" and out[0]["lat"] == 33.5, out


def test_search_without_key_raises():
    try:
        places.search("x", "", fetch=lambda *a: {})
        assert False, "키 없이 통과했다"
    except places.MissingApiKey:
        pass


# ---------- Task 7: verify 배치 ----------

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
    assert row[0] == "matched" and row[1] == "ChIJ1" and row[2] == 33.5, tuple(row)
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
        calls.append(query)
        return []
    trip.verify_places(conn, "KEY", limit=2, search=counting_search)
    assert len(calls) == 2, calls


def test_mark_saved():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["가게"])
    pid = conn.execute("SELECT id FROM place").fetchone()[0]
    assert trip.mark_saved(conn, [pid]) == 1
    assert conn.execute("SELECT saved_to_mymaps FROM place").fetchone()[0] == 1


# ---------- Task 8: export ----------

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
        posted.append(task["content"])
        return {"id": f"t{len(posted)}"}
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


# ---------- Task 9: CLI ----------

import io
import json as _json


def test_load_env_reads_dotenv():
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
    conn = trip.connect(":memory:")
    code = trip.cmd_add(conn, io.StringIO(_json.dumps(BASE)), force=False)
    assert code == 0, code
    assert conn.execute("SELECT COUNT(*) FROM place").fetchone()[0] == 1


def test_cmd_add_returns_2_on_bad_json():
    conn = trip.connect(":memory:")
    assert trip.cmd_add(conn, io.StringIO("{not json"), force=False) == 2


def test_cmd_add_returns_2_on_forbidden_field():
    conn = trip.connect(":memory:")
    assert trip.cmd_add(conn, io.StringIO(_json.dumps(FORBIDDEN_SAMPLE)),
                        force=False) == 2


def test_cli_stdin_accepts_utf8_korean():
    """회귀: Windows cp949 stdin 이 '맛집'을 '留쏆쭛'으로 깨뜨렸다.

    io.StringIO 로는 잡히지 않는다. 실제 서브프로세스 파이프여야 재현된다.
    """
    import subprocess
    fd, dbpath = tempfile.mkstemp(suffix=".db")
    _os.close(fd)
    _os.unlink(dbpath)
    payload = _json.dumps({
        "source": {"kind": "text", "raw_text": "메모"},
        "places": [{"name": "이치란 라멘", "category": "맛집"}]})
    try:
        p = subprocess.run(
            [sys.executable, "trip.py", "--db", dbpath, "add"],
            input=payload.encode("utf-8"),
            cwd=_os.path.dirname(_os.path.abspath(__file__)),
            capture_output=True)
        assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
        conn = sqlite3.connect(dbpath)
        row = conn.execute("SELECT name, category FROM place").fetchone()
        conn.close()
        assert row == ("이치란 라멘", "맛집"), row
    finally:
        if _os.path.exists(dbpath):
            _os.unlink(dbpath)


# ---------- Claude 검색 경로 (lookup) ----------

def test_maps_url_from_address_encodes():
    u = places.maps_url_from_address("5-3-2 Nakasu, Hakata-ku, Fukuoka")
    assert u.startswith("https://www.google.com/maps/search/?api=1&query="), u
    assert " " not in u, u
    assert "Nakasu" in u


def test_judge_by_evidence_two_domains_matched():
    assert places.judge_by_evidence(
        "5-3-2 Nakasu", ["https://triple.guide/a", "https://kyushurent.com/b"]
    ) == "matched"


def test_judge_by_evidence_same_domain_is_ambiguous():
    # 같은 블로그의 페이지 2개는 교차확인이 아니다.
    assert places.judge_by_evidence(
        "5-3-2 Nakasu", ["https://blog.com/a", "https://www.blog.com/b"]
    ) == "ambiguous"


def test_judge_by_evidence_single_is_ambiguous():
    assert places.judge_by_evidence("5-3-2 Nakasu", ["https://a.com/x"]) == "ambiguous"


def test_judge_by_evidence_no_address_is_not_found():
    assert places.judge_by_evidence("", ["https://a.com", "https://b.com"]) == "not_found"


def test_apply_lookup_rejects_coordinates():
    """가장 중요: 검색으로 안 나오는 좌표를 Claude 가 지어내면 거부한다."""
    conn = trip.connect(":memory:")
    _seed_places(conn, ["이치란"])
    pid = conn.execute("SELECT id FROM place").fetchone()[0]
    try:
        trip.apply_lookup(conn, [{"id": pid, "address": "어딘가", "lat": 33.5,
                                  "evidence_urls": ["https://a.com", "https://b.com"]}])
        assert False, "환각 좌표가 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E3", e.code
        assert "lat" in str(e)


def test_apply_lookup_rejects_place_id():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["이치란"])
    pid = conn.execute("SELECT id FROM place").fetchone()[0]
    try:
        trip.apply_lookup(conn, [{"id": pid, "address": "어딘가",
                                  "place_id": "ChIJfake",
                                  "evidence_urls": ["https://a.com", "https://b.com"]}])
        assert False, "지어낸 place_id 가 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E3", e.code


def test_apply_lookup_rejects_empty_evidence():
    """근거 URL 없는 주소는 환각과 구분이 안 된다."""
    conn = trip.connect(":memory:")
    _seed_places(conn, ["이치란"])
    pid = conn.execute("SELECT id FROM place").fetchone()[0]
    try:
        trip.apply_lookup(conn, [{"id": pid, "address": "어딘가", "evidence_urls": []}])
        assert False, "근거 없는 주소가 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E2", e.code
        assert "evidence_urls" in str(e)


def test_apply_lookup_rejects_unknown_id():
    conn = trip.connect(":memory:")
    try:
        trip.apply_lookup(conn, [{"id": 999, "address": "어딘가",
                                  "evidence_urls": ["https://a.com", "https://b.com"]}])
        assert False, "없는 id 가 통과했다"
    except trip.ValidationError as e:
        assert e.code == "E4", e.code


def test_apply_lookup_writes_and_code_judges():
    """Claude 는 status 를 쓰지 않는다. 코드가 도메인 수를 세서 판정한다."""
    conn = trip.connect(":memory:")
    _seed_places(conn, ["이치란", "애매한집", "못찾은집"])
    ids = {n: i for i, n in conn.execute("SELECT id, name FROM place").fetchall()}
    r = trip.apply_lookup(conn, [
        {"id": ids["이치란"], "address": "5-3-2 Nakasu, Hakata-ku, Fukuoka",
         "name_verified": "이치란 본사 총본점",
         "evidence_urls": ["https://triple.guide/a", "https://kyushurent.com/b"]},
        {"id": ids["애매한집"], "address": "어딘가 1-2-3",
         "evidence_urls": ["https://oneblog.com/a"]},
        {"id": ids["못찾은집"], "address": "", "evidence_urls": []},
    ])
    assert r == {"matched": 1, "ambiguous": 1, "not_found": 1}, r
    row = conn.execute(
        "SELECT verify_status, verify_method, address, name_verified, maps_url, "
        "evidence_urls, lat FROM place WHERE id=?", (ids["이치란"],)).fetchone()
    assert row[0] == "matched", row[0]
    assert row[1] == "claude_search", row[1]
    assert row[2] == "5-3-2 Nakasu, Hakata-ku, Fukuoka"
    assert row[3] == "이치란 본사 총본점"
    assert row[4].startswith("https://www.google.com/maps/search/?api=1&query=")
    assert "triple.guide" in row[5] and "kyushurent.com" in row[5], row[5]
    assert row[6] is None, "좌표는 절대 채워지면 안 된다"
    # ambiguous 여도 링크는 만든다 — 사용자가 열어보는 게 판정 절차의 일부다.
    assert conn.execute("SELECT maps_url FROM place WHERE id=?",
                        (ids["애매한집"],)).fetchone()[0]


def test_pending_outputs_json():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["가게1", "가게2"])
    out = trip.pending_places(conn)
    assert len(out) == 2, out
    assert set(out[0]) == {"id", "name", "category", "note"}, out[0]
    _json.dumps(out)  # 직렬화 가능해야 Claude 가 읽는다


def test_pending_excludes_resolved():
    conn = trip.connect(":memory:")
    _seed_places(conn, ["미확인", "확인됨"])
    ids = {n: i for i, n in conn.execute("SELECT id, name FROM place").fetchall()}
    trip.apply_lookup(conn, [{"id": ids["확인됨"], "address": "a 1-2",
                              "evidence_urls": ["https://a.com", "https://b.com"]}])
    assert [p["name"] for p in trip.pending_places(conn)] == ["미확인"]


def test_todoist_projects_parses():
    """project_id 는 URL 슬러그가 아니라 숫자다. API 로만 얻을 수 있다."""
    def fake_get(url, token):
        assert url.endswith("/projects"), url
        return [{"id": 2203306141, "name": "2026 후쿠오카"},
                {"id": 2203306999, "name": "인박스"}]
    out = export.todoist_projects("TOK", get=fake_get)
    assert out == [{"id": "2203306141", "name": "2026 후쿠오카"},
                   {"id": "2203306999", "name": "인박스"}], out


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
