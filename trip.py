"""여행 자료 수집·검증 CLI.

핵심 원칙: LLM 은 추출·분류만 한다. 좌표·place_id 같은 사실은 Places API 만 채운다.
스펙: docs/superpowers/specs/2026-09-06-travel-manager-design.md
"""
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
