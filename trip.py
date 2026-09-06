"""여행 자료 수집·검증 CLI.

핵심 원칙: LLM 은 추출·분류만 한다. 좌표·place_id 같은 사실은 Places API 만 채운다.
스펙: docs/superpowers/specs/2026-09-06-travel-manager-design.md
"""
import csv
import os
import sqlite3

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
