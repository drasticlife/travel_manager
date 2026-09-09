"""travel manager 전체 테스트. 프레임워크 없음. 실행: python test_trip.py"""
import sqlite3
import sys

# Windows 콘솔 기본 cp949 는 em dash·기호를 못 찍는다. utf-8 로 고정.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import trip


# ---------- Task 1: 스키마 ----------

def test_schema_creates_all_tables():
    conn = trip.connect(":memory:")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"source", "place", "itinerary", "packing",
                     "item", "item_place", "tip"}, names


def test_category_check_constraint():
    conn = trip.connect(":memory:")
    try:
        conn.execute("INSERT INTO place (name, category) VALUES ('x', '밥집')")
        assert False, "DB가 잘못된 category를 받아들였다"
    except sqlite3.IntegrityError:
        pass


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


def test_plan_orders_slots_chronologically():
    """회귀: seq 만으로 정렬하면 '밤 seq=0' 이 '오전 seq=0' 보다 먼저 나왔다."""
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, {
        "source": {"kind": "text", "raw_text": "x"},
        "places": [{"name": "아침집", "category": "맛집"},
                   {"name": "밤집", "category": "맛집"},
                   {"name": "낮집", "category": "맛집"}],
        "itinerary": [
            {"day_no": 1, "slot": "밤", "seq": 0, "place_name": "밤집"},
            {"day_no": 1, "slot": "오전", "seq": 0, "place_name": "아침집"},
            {"day_no": 1, "slot": "오후", "seq": 0, "place_name": "낮집"},
        ]})
    slots = [r["slot"] for r in trip.list_plan(conn)]
    assert slots == ["오전", "오후", "밤"], slots


def test_todoist_uses_v1_endpoints():
    """REST v2 는 2026 초에 폐기되어 410 Gone 을 낸다."""
    assert "/api/v1/" in export.TODOIST_URL, export.TODOIST_URL
    assert "/api/v1/" in export.TODOIST_PROJECTS_URL, export.TODOIST_PROJECTS_URL
    assert "rest/v2" not in export.TODOIST_URL


def test_unwrap_handles_v1_and_bare():
    assert export.unwrap({"results": [1, 2], "next_cursor": None}) == [1, 2]
    assert export.unwrap([1, 2]) == [1, 2]
    assert export.unwrap({"results": None, "next_cursor": None}) == []
    assert export.unwrap(None) == []


def test_todoist_projects_parses_v1_wrapper():
    """v1 은 목록을 {results, next_cursor} 로 감싼다."""
    def fake_get(url, token):
        assert url.startswith(export.TODOIST_PROJECTS_URL), url
        return {"results": [{"id": "6hR986mmJqCrxHc4", "name": "2026 후쿠오카"},
                            {"id": "6WJ8wCQ2pgPfW96V", "name": "Inbox"}],
                "next_cursor": None}
    out = export.todoist_projects("TOK", get=fake_get)
    assert out == [{"id": "6hR986mmJqCrxHc4", "name": "2026 후쿠오카"},
                   {"id": "6WJ8wCQ2pgPfW96V", "name": "Inbox"}], out


def test_push_skips_tasks_already_on_remote():
    """공유 프로젝트다. 아내가 손으로 적어둔 것을 또 만들면 안 된다."""
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, BASE)
    posted = []

    def fake_post(token, project_id, task):
        posted.append(task["content"])
        return {"id": f"t{len(posted)}"}
    r = export.push_todoist(conn, "TOK", "P1", dry_run=False, post=fake_post,
                            existing={"우산 x1"})
    assert r["created"] == 1 and r["already_remote"] == 1, r
    assert posted == ["3일차 [점심] 이치란 라멘 나카스점"], posted



def test_todoist_existing_contents_follows_cursor():
    """페이지 1건만 읽으면 중복 검사가 뚫린다. 실제로 115건 중 50건만 읽혔다."""
    pages = [{"results": [{"content": "여권"}], "next_cursor": "c1"},
             {"results": [{"content": "우산"}], "next_cursor": None}]
    seen = []

    def fake_get(url, token):
        seen.append(url)
        return pages[len(seen) - 1]
    got = export.todoist_existing_contents("TOK", "P1", get=fake_get)
    assert got == {"여권", "우산"}, got
    assert "cursor=c1" in seen[1], seen


# ---------- 장소 확인 HTML ----------

import maps_page


def test_maps_page_orders_urgent_first_and_embeds_places():
    """확인이 급한 것(모호 → 못 찾음 → 미조사)이 먼저 와야 한다."""
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, BASE)
    conn.execute("UPDATE place SET verify_status = 'matched' WHERE id = 1")
    conn.execute(
        "INSERT INTO place (name, category, verify_status, source_id) "
        "VALUES ('미조사', '쇼핑', 'pending', 1), ('모호', '맛집', 'ambiguous', 1)")
    conn.commit()

    got = [p["verify_status"] for p in maps_page.collect(conn)]
    assert got[0] == "ambiguous" and got[1] == "pending", got
    assert got[-1] == "matched", got

    page = maps_page.build_page(conn, "2026-09-07 23:00")
    assert "__PLACES__" not in page and "__LABELS__" not in page, "치환 안 된 자리표시자"
    assert "이치란 라멘 나카스점" in page, "장소명이 페이지에 없다"
    assert "mark-saved" in page


def test_maps_page_marks_already_saved():
    """이미 내 지도에 저장한 것은 체크박스가 잠겨야 한다 — 명령에 또 넣으면 안 된다."""
    conn = trip.connect(":memory:")
    trip.insert_payload(conn, BASE)
    trip.mark_saved(conn, [1])
    saved = {p["id"]: p["saved_to_mymaps"] for p in maps_page.collect(conn)}
    assert saved[1] == 1, saved


def test_search_restricts_to_fukuoka():
    """지역 제한을 빼면 체인점이 전국에서 잡힌다.

    실제로 '카페 베로체 치쿠시구치' 를 찾다가 도쿄 니시신주쿠점의
    주소·좌표가 DB 에 써졌다.
    """
    seen = {}

    def fake_fetch(url, body, headers):
        seen["body"] = body
        return {"places": []}
    places.search("카페 베로체 치쿠시구치", "KEY", fetch=fake_fetch)
    box = seen["body"]["locationRestriction"]["rectangle"]
    assert box["low"]["latitude"] < 33.6 < box["high"]["latitude"], box
    assert box["low"]["longitude"] < 130.4 < box["high"]["longitude"], box
    # 도쿄(35.69, 139.70)는 상자 밖이어야 한다
    assert not (box["low"]["latitude"] <= 35.69 <= box["high"]["latitude"]), box

    places.search("x", "KEY", fetch=fake_fetch, area=None)
    assert "locationRestriction" not in seen["body"], seen["body"]


# ---------- Task 2: items·tips 검증 ----------

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


# 러너는 반드시 파일 맨 끝에 있어야 한다. 중간에 두면 그 아래 정의된
# test_ 함수가 globals() 에 없는 채로 수집되어 조용히 건너뛴다.
# 실제로 그래서 4개(체인점 오염·커서 페이징 회귀 테스트 포함)가 안 돌았다.
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
