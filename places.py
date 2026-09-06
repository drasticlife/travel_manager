"""Google Places API (New) Text Search 조회와 이름 대조.

스펙 §3.3~3.4.1. 핵심: 결과가 2건 이상이면 무조건 ambiguous —
1순위를 자동 채택하면 '이치란 나카스점'을 찾다가 '이치란 텐진점'이 확정된다.
"""
import json
import re
import urllib.request

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# 과금 등급 주의: rating·opening_hours·reviews·photos 를 넣으면 Enterprise 로 올라간다.
# 구글은 field mask 에 포함된 가장 높은 등급으로 요청 전체를 과금한다.
FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.location"

TIMEOUT_SEC = 10


class MissingApiKey(Exception):
    pass


def normalize(name):
    """공백·구두점·괄호를 걷어내고 소문자화. 일본 장소는 표기가 제각각이라 필요하다."""
    return re.sub(r"[\s()（）・·,，.\-–—]", "", (name or "")).lower()


def maps_url(place_id):
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def judge(query, candidates):
    """(status, chosen) 반환. 스펙 §3.4.1 판정 규칙."""
    if not candidates:
        return "not_found", None
    if len(candidates) > 1:
        # 1순위 자동 채택 금지. 사람이 확인해야 한다.
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
    """Text Search 결과를 정규화된 dict 리스트로 반환한다."""
    if not api_key:
        raise MissingApiKey(
            "GOOGLE_MAPS_API_KEY 가 없습니다. "
            "https://console.cloud.google.com/apis/credentials 에서 발급 후 "
            ".env 에 넣으세요.")
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
