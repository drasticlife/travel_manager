"""Google Places API (New) Text Search 조회와 이름 대조.

스펙 §3.3~3.4.1. 핵심: 결과가 2건 이상이면 무조건 ambiguous —
1순위를 자동 채택하면 '이치란 나카스점'을 찾다가 '이치란 텐진점'이 확정된다.
"""
import json
import re
import urllib.parse
import urllib.request

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# 과금 등급 주의: rating·opening_hours·reviews·photos 를 넣으면 Enterprise 로 올라간다.
# 구글은 field mask 에 포함된 가장 높은 등급으로 요청 전체를 과금한다.
FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.location"

# 후쿠오카 광역. 이름만 던지면 체인점이 전국에서 잡힌다 — '카페 베로체 치쿠시구치'
# 를 찾다가 도쿄 니시신주쿠점의 주소와 좌표가 DB 에 써졌다. 실제로 밟았다.
# locationRestriction 은 searchText 에서 rectangle 만 받는다(circle 불가).
SEARCH_AREA = {"rectangle": {"low": {"latitude": 33.40, "longitude": 130.10},
                             "high": {"latitude": 33.80, "longitude": 130.65}}}

TIMEOUT_SEC = 10


class MissingApiKey(Exception):
    pass


def normalize(name):
    """공백·구두점·괄호를 걷어내고 소문자화. 일본 장소는 표기가 제각각이라 필요하다."""
    return re.sub(r"[\s()（）・·,，.\-–—]", "", (name or "")).lower()


def maps_url(place_id):
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def maps_url_from_address(address, name=None):
    """주소 기반 검색 링크.

    이름으로 검색하면 '이치란 나카스점'을 찾다가 '이치란 텐진점'이 나오지만,
    정확한 일본 주소는 그 자체가 식별자라 한 곳으로 떨어진다.
    """
    q = f"{address} {name}".strip() if name else (address or "").strip()
    return ("https://www.google.com/maps/search/?api=1&query="
            + urllib.parse.quote(q))


def _domain(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def judge_by_evidence(address, evidence_urls):
    """근거 URL 의 고유 도메인 수로 판정한다.

    판정을 LLM 에게 맡기면 자기 결과에 후한 점수를 준다. 그래서 코드가 센다.
    같은 블로그의 페이지 2개는 교차확인이 아니므로 1개로 센다.
    """
    if not address or not str(address).strip():
        return "not_found"
    domains = {d for d in (_domain(u) for u in (evidence_urls or [])) if d}
    return "matched" if len(domains) >= 2 else "ambiguous"


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


def search(query, api_key, fetch=None, area=SEARCH_AREA):
    """Text Search 결과를 정규화된 dict 리스트로 반환한다.

    area 는 검색을 가둘 사각형이다. 이걸 빼면 체인점이 전국에서 잡힌다.
    """
    if not api_key:
        raise MissingApiKey(
            "GOOGLE_MAPS_API_KEY 가 없습니다. "
            "https://console.cloud.google.com/apis/credentials 에서 발급 후 "
            ".env 에 넣으세요.")
    fetch = fetch or _real_fetch
    body = {"textQuery": query, "languageCode": "ko", "maxResultCount": 5}
    if area:
        body["locationRestriction"] = area
    data = fetch(ENDPOINT, body,
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
