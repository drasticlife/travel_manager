"""여행 자료 수집·검증 CLI.

핵심 원칙: LLM 은 추출·분류만 한다. 좌표·place_id 같은 사실은 Places API 만 채운다.
스펙: docs/superpowers/specs/2026-09-06-travel-manager-design.md
"""
import argparse
import csv
import json
import os
import sqlite3
import sys

import places as places_mod

_HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(_HERE, "schema.sql")
DEFAULT_DB = os.path.join(_HERE, "data", "trip.db")


def connect(db_path=DEFAULT_DB):
    """스키마가 적용된 연결을 반환한다. 없으면 만든다."""
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


# --------------------------------------------------------------------------
# LLM 출력 검증 — 환각 차단선
# --------------------------------------------------------------------------

# LLM 이 절대 채울 수 없는 필드. 사실(fact)은 Places API 만 쓴다.
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
            f"{where} = {value!r} 은 허용되지 않습니다. "
            f"허용값: {' | '.join(sorted(allowed))}")


def validate_payload(payload):
    """통과하면 payload 를 그대로 반환. 실패하면 ValidationError."""
    if not isinstance(payload, dict):
        raise ValidationError("E2", "최상위는 객체여야 합니다.")

    src = payload.get("source")
    if not isinstance(src, dict):
        raise ValidationError("E2", "source 객체가 필요합니다.")
    if not src.get("raw_text"):
        raise ValidationError("E2",
            "source.raw_text 는 비어 있을 수 없습니다. 원문을 보존해야 합니다.")
    _enum("source.kind", src.get("kind"), KIND)

    for i, p in enumerate(payload.get("places") or []):
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


# --------------------------------------------------------------------------
# 쓰기 — all-or-nothing
# --------------------------------------------------------------------------

def insert_payload(conn, payload, force=False):
    """검증 후 트랜잭션으로 쓴다. 어디서든 실패하면 전부 롤백한다."""
    validate_payload(payload)
    warnings = []
    result = {"source_id": None, "places_new": 0, "places_merged": 0,
              "itinerary": 0, "packing": 0, "warnings": warnings}
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
                    "INSERT INTO place (name, category, note, source_id) "
                    "VALUES (?,?,?,?)",
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
                        f"itinerary 의 place_name {pname!r} 을 places 에서도 "
                        "DB 에서도 찾을 수 없습니다.")
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


def import_takeout(conn, csv_path):
    """Google Takeout 의 저장 목록 CSV 를 place 시드로 넣는다.

    CSV 에는 좌표도 카테고리도 없다. 전부 '기타' 로 넣고 verify 가 사실을 채운다.
    """
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
                "source": {"kind": "takeout",
                           "url": (row.get("URL") or "").strip() or None,
                           "title": title, "raw_text": raw},
                "places": [{"name": title, "category": "기타",
                            "note": note or None}],
            })
            total["places_new"] += r["places_new"]
            total["places_merged"] += r["places_merged"]
            total["warnings"].extend(r["warnings"])
    return total


# --------------------------------------------------------------------------
# 검증 — 네트워크·과금 단계. 수집과 분리되어 있어 실패해도 원문은 안전하다.
# --------------------------------------------------------------------------

def verify_places(conn, api_key, limit=50, search=None):
    """pending 장소를 Places API 로 조회해 사실을 채운다.

    조회 실패(E7)는 장애가 아니다. pending 을 유지하면 다음 실행이 재시도한다.
    """
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
        try:
            if chosen:
                conn.execute(
                    "UPDATE place SET verify_status=?, place_id=?, name_verified=?, "
                    "address=?, lat=?, lng=?, maps_url=? WHERE id=?",
                    (status, chosen.get("place_id"), chosen.get("name"),
                     chosen.get("address"), chosen.get("lat"), chosen.get("lng"),
                     places_mod.maps_url(chosen.get("place_id")), pid))
            else:
                conn.execute(
                    "UPDATE place SET verify_status=? WHERE id=?", (status, pid))
            conn.commit()
        except sqlite3.IntegrityError as e:
            # 같은 place_id 를 다른 이름으로 이미 확정한 경우. pending 유지가 안전하다.
            conn.rollback()
            print(f"[verify] place_id 중복으로 건너뜀 (pending 유지): {name} — {e}")
            stats["failed"] += 1
            continue
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
        sql += " AND category = ?"
        args.append(category)
    if status:
        sql += " AND verify_status = ?"
        args.append(status)
    return conn.execute(sql + " ORDER BY category, name", args).fetchall()


def list_plan(conn, day=None):
    conn.row_factory = sqlite3.Row
    sql = ("SELECT i.day_no, i.slot, i.seq, i.memo, p.name AS place_name, p.maps_url "
           "FROM itinerary i LEFT JOIN place p ON p.id = i.place_id WHERE 1=1")
    args = []
    if day:
        sql += " AND i.day_no = ?"
        args.append(day)
    return conn.execute(sql + " ORDER BY i.day_no, i.seq", args).fetchall()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_env(path=None):
    """.env 를 읽고 실제 환경변수가 있으면 그쪽을 우선한다."""
    path = path or os.path.join(_HERE, ".env")
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
    """stdin 의 정규화 JSON 을 저장한다. 실패하면 Claude 가 읽고 고칠 수 있게 말한다."""
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
    # Windows 기본 cp949 로는 파이프로 들어온 UTF-8 한국어 JSON 이 깨진다.
    # stdin 을 안 고치면 '맛집' 이 '留쏆쭛' 으로 읽혀 전 입력 경로가 죽는다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

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
    p_list.add_argument("--category")
    p_list.add_argument("--status")

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
            r = verify_places(conn, env.get("GOOGLE_MAPS_API_KEY", ""),
                              limit=args.limit)
        except places_mod.MissingApiKey as e:
            print(f"ERROR E6: {e}", file=sys.stderr)
            return 1
        print(f"OK matched {r['matched']} / ambiguous {r['ambiguous']} / "
              f"not_found {r['not_found']} / failed {r['failed']}")
        return 0

    if args.cmd == "list":
        for r in list_places(conn, args.category, args.status):
            flag = "*" if r["saved_to_mymaps"] else " "
            print(f"{flag} [{r['id']:>3}] {r['verify_status']:<10} "
                  f"{r['category']:<4} {r['name']}")
        return 0

    if args.cmd == "plan":
        for r in list_plan(conn, args.day):
            print(f"{r['day_no']}일차 [{r['slot']}] "
                  f"{r['place_name'] or '(미정)'} {r['memo'] or ''}".rstrip())
        return 0

    if args.cmd == "mark-saved":
        print(f"OK {mark_saved(conn, args.ids)} 건 저장 완료 표시")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
