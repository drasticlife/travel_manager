"""여행 가이드 HTML 한 장.

사용자가 만든 가이드 인포그래픽(2026-09-09 판)의 구성을 따라 그린다:
라벤더 바탕, 일차별 카드, 왼쪽에 DAY/날짜/공휴일 + 마스코트, 오른쪽에
[주요 일정 | 영업시간 | 이동 동선·교통편] 3열. 환승은 아이콘 체인으로,
구간은 분홍 알약 라벨로 보여준다.

일러스트는 전부 인라인 SVG 로 직접 그린다. 원본의 산리오 캐릭터는 저작물이라
쓰지 않고, 같은 자리에 자체 도안 마스코트를 넣었다. 외부 이미지·웹폰트는
쓰지 않는다 — Artifact 의 CSP 가 외부 호스트를 전부 막는다.

그림을 누르면 팝업이 열려 DB 의 주소·노트·근거 URL·구글지도 링크를 보여준다.
팝업 안에서 '내 지도에 저장함' 을 체크하면 하단 바가
`python trip.py mark-saved <id...>` 명령을 만들어 준다.

읽기 전용이다. 이 파일은 DB 에 아무것도 쓰지 않는다 — 되먹임은 사람이
터미널에서 mark-saved 를 실행하는 것으로 끝난다.
"""
import html
import json
import math
import os
import re
import sqlite3

import trip

SLOT_ORDER = {"오전": 0, "점심": 1, "오후": 2, "저녁": 3, "밤": 4}

STATUS_ORDER = ["ambiguous", "not_found", "pending", "matched"]
STATUS_LABEL = {"ambiguous": "모호 — 후보가 여럿이다",
                "not_found": "못 찾음 — 검색으로 안 나왔다",
                "pending": "미조사 — 주소가 아직 없다",
                "matched": "확인됨"}

# 날짜·공휴일·감성 문구·마스코트는 DB 에 없다. 가이드 원본을 그대로 옮겼다.
DAY_META = {
    1: {"date": "9/21 (월)", "holiday": True, "tone": "v", "mascot": "dog",
        "mood": "여행의 시작\n설레는 후쿠오카!"},
    2: {"date": "9/22 (화)", "holiday": True, "tone": "v", "mascot": "bunny",
        "mood": "바다와 자연이\n가득한 하루"},
    3: {"date": "9/23 (수)", "holiday": True, "tone": "v", "mascot": "cat",
        "mood": "바다 생물을 만나고\n텐진에서 즐기는 하루"},
    4: {"date": "9/24 (목)", "holiday": False, "tone": "y", "mascot": "bear",
        "mood": "아쉬운 잠시,\n다음에 또 :)"},
}

ICON_BY_NAME = [
    ("공원", "🌳"), ("동물의숲", "🌳"), ("마린월드", "🐬"), ("수족관", "🐬"),
    ("라라포트", "🤖"), ("Moff", "🐹"), ("animal", "🐹"),
    ("호빵맨", "🍞"), ("공항", "✈️"), ("귀국", "✈️"),
    ("캐널시티", "🏬"), ("호텔", "🏨"), ("지하상가", "🛍️"),
    ("마잉구", "🎁"), ("한큐", "🎁"), ("저녁", "🍽️"),
]
ICON_BY_CAT = {"맛집": "🍜", "쇼핑": "🛍️", "관광": "🎡",
               "숙소": "🏨", "이동": "🚃", "기타": "📍"}

MOVE_WORDS = ("도보", "JR", "지하철", "택시", "환승", "→", "정거장", "km", "전철")
TIME_RE = re.compile(r"\d{1,2}:\d{2}")

# 이동 칸 파싱 ------------------------------------------------------------
# "호텔→캐널시티 도보 약 18분…" 처럼 문장 맨 앞에 오는 구간 표시
LEG_RE = re.compile(r"^([^\s→]{1,20})→([^\s:：,]{1,24})[:：]?[\s,]*")
# "경로:" / "복귀:" 뒤가 환승 체인이다
CHAIN_LABEL_RE = re.compile(r"(?:^|\.\s*)(경로|복귀)\s*[:：]\s*")
# 노선 이름이 역명 앞에 붙는 경우가 있다. 그때만 두 토큰까지 역명으로 본다.
LINE_PREFIX = ("JR", "지하철", "니시테츠", "사철", "신칸센")
STEP_ICON = [("도보", "🚶"), ("택시", "🚕"), ("버스", "🚌"),
             ("JR", "🚃"), ("지하철", "🚇"), ("전철", "🚃"), ("니시테츠", "🚃")]
STAR_WORDS = ("체크인", "체크아웃", "출발")


def icon_for(name, category):
    for key, emoji in ICON_BY_NAME:
        if key.lower() in (name or "").lower():
            return emoji
    return ICON_BY_CAT.get(category, "📍")


def _head(text, n=6):
    """공백을 뺀 앞 n 글자. 제목과 부제가 같은 말인지 보는 데만 쓴다."""
    return re.sub(r"\s+", "", text or "")[:n]


def split_memo(memo):
    """memo 를 (영업시간, 부제, 이동 동선) 으로 쪼갠다."""
    parts = [s.strip() for s in (memo or "").split(". ") if s.strip()]
    hours = ""
    if parts and TIME_RE.search(parts[0]) and len(parts[0]) <= 40:
        hours = parts.pop(0)
    subtitle = parts.pop(0) if parts else ""
    move = ". ".join(parts)
    if subtitle and any(w in subtitle for w in MOVE_WORDS):
        move = f"{subtitle}. {move}".strip(". ") if move else subtitle
        subtitle = ""
    return hours, subtitle, move


def split_step(text):
    """'하카타역 JR 가고시마본선 약 11분' → ('하카타역', 'JR 가고시마본선 약 11분').

    첫 토큰이 노선 이름이면 두 토큰까지 역명으로 본다 ('JR 하카타역').
    """
    tokens = text.split()
    if not tokens:
        return "", ""
    take = 2 if tokens[0] in LINE_PREFIX and len(tokens) > 1 else 1
    return " ".join(tokens[:take]), " ".join(tokens[take:])


def step_icon(name, detail):
    """수단은 detail 이 정한다. 안 적혀 있으면 역이면 열차, 아니면 도보로 본다."""
    for key, emoji in STEP_ICON:
        if key in detail:
            return emoji
    return "🚃" if name.endswith("역") else "🚶"


def parse_move(move):
    """이동 문장을 (구간 라벨, 환승 체인, 남은 설명) 으로 나눈다."""
    text = (move or "").strip()
    leg = None
    m = LEG_RE.match(text)
    if m:
        leg = f"{m.group(1)} → {m.group(2)}"
        text = text[m.end():]

    chain, note = [], text
    m = CHAIN_LABEL_RE.search(text)
    body = text[m.end():] if m else text
    if " → " in body:
        steps = [split_step(s.strip()) for s in body.split(" → ") if s.strip()]
        # '→' 는 환승이 아니라 '그래서' 로도 쓰인다 ("… 3시간 전 도착 권장 → 15:00 …").
        # 노드 절반 이상이 역 이름일 때만 이동 체인으로 본다.
        stations = sum(1 for n, _ in steps if n.endswith("역"))
        if len(steps) >= 2 and stations * 2 >= len(steps):
            chain = [{"name": n, "detail": d, "icon": step_icon(n, d)}
                     for n, d in steps]
            note = text[:m.start()].strip() if m else ""

    return {"leg": leg, "chain": chain, "note": note.strip(" .")}


def collect(conn):
    """페이지에 뿌릴 장소 전체. 확인이 급한 것부터."""
    conn.row_factory = sqlite3.Row
    days = {}
    for r in conn.execute(
            "SELECT place_id, day_no, slot, seq, memo FROM itinerary "
            "WHERE place_id IS NOT NULL"):
        days.setdefault(r["place_id"], []).append(dict(r))
    for v in days.values():
        v.sort(key=lambda d: (d["day_no"], SLOT_ORDER.get(d["slot"], 9), d["seq"]))

    out = []
    for r in conn.execute(
            "SELECT id, name, name_verified, category, address, maps_url, "
            "verify_status, saved_to_mymaps, note, evidence_urls FROM place "
            "ORDER BY id"):
        p = dict(r)
        p["evidence"] = [u.strip() for u in
                         (p.pop("evidence_urls") or "").split("\n") if u.strip()]
        p["days"] = days.get(r["id"], [])
        p["icon"] = icon_for(p["name"], p["category"])
        out.append(p)
    out.sort(key=lambda p: (STATUS_ORDER.index(p["verify_status"])
                            if p["verify_status"] in STATUS_ORDER else 9, p["id"]))
    return out


# 슬롯별 기본 출발 시각(분). 명시된 단서가 없을 때만 쓴다.
SLOT_DEFAULT_TIME = {
    "오전": 9 * 60, "점심": 12 * 60, "오후": 14 * 60,
    "저녁": 18 * 60, "밤": 20 * 60,
}

# 이 낱말 옆의 시각은 '우리가 움직이는 시각'이다.
DEPART_WORDS = ("출발", "체크아웃", "체크인", "탑승", "복귀", "집합")
# 이 낱말 옆의 시각은 '늦어도 그때까지'라는 기한이라 이동시간만큼 앞당긴다.
DEADLINE_WORDS = ("도착 권장", "도착권장", "까지", "마감")
# 영업시간은 우리 일정이 아니다. 이걸 출발 시각으로 쓰면 오후 일정에
# 오전 열차를 안내하게 된다.
HOURS_WORDS = ("영업", "쇼핑", "식당", "입장", "최종입장", "입장마감", "오픈")

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")


def _clock(text):
    """문장에서 첫 시각을 분으로. 없으면 None."""
    m = _HHMM.search(text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h * 60 + mi if 0 <= h < 24 and mi < 60 else None


def plan_time(slot, hours, memo, travel_min=30):
    """그 일정에 '우리가 움직일' 대략의 시각(분)을 추정한다.

    memo 는 사용자가 만든 일정표에서 왔다. 거기 적힌 시각을 쓰되,
    영업시간과 계획 시각을 구분한다 — '10:00~20:00' 은 가게가 여는
    시간이지 우리가 나서는 시간이 아니다.
    """
    # 순서가 중요하다. 영업시간을 먼저 걸러내지 않으면
    # '09:30~21:00(입장마감 20:00)' 이 '마감' 때문에 기한으로 잡혀
    # 오전 일정인 마린월드가 19:30 이 된다.
    sentences = [x for x in re.split(r"[.。]\s*", memo or "") if _HHMM.search(x)]
    plan = [x for x in sentences if not any(w in x for w in HOURS_WORDS)]

    # 기한이 출발 단서를 이긴다. 공항행 memo 는 '출발 18:00'(비행기)이 먼저
    # 나오지만 우리가 맞춰야 하는 건 뒤에 오는 '15:00 도착 권장' 이다.
    for sentence in plan:
        if any(w in sentence for w in DEADLINE_WORDS):
            t = None
            for m in _HHMM.finditer(sentence):      # 기한은 보통 마지막 시각
                t = int(m.group(1)) * 60 + int(m.group(2))
            if t is not None:
                return max(0, t - travel_min)
    for sentence in plan:
        if any(w in sentence for w in DEPART_WORDS):
            t = _clock(sentence)
            if t is not None:
                return t
    # hours 가 '체크아웃 11:00' 처럼 계획을 담고 있으면 그것도 본다
    if hours and hours != "–" and any(w in hours for w in DEPART_WORDS):
        t = _clock(hours)
        if t is not None:
            return t
    return SLOT_DEFAULT_TIME.get(slot)


def collect_days(conn):
    """일차별 일정. 정렬은 day_no → 슬롯순서 → seq 다. seq 만 쓰면 밤이 먼저 온다."""
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT i.id, i.day_no, i.date, i.slot, i.seq, i.place_id, i.memo, "
        "p.name AS place_name, p.category AS place_category "
        "FROM itinerary i LEFT JOIN place p ON p.id = i.place_id")]
    rows.sort(key=lambda r: (r["day_no"], SLOT_ORDER.get(r["slot"], 9), r["seq"]))

    days = []
    for day_no in sorted({r["day_no"] for r in rows} | set(DAY_META)):
        meta = DAY_META.get(day_no, {"date": "", "holiday": False, "tone": "v",
                                     "mascot": "dog", "mood": ""})
        items = []
        for r in rows:
            if r["day_no"] != day_no:
                continue
            hours, subtitle, move = split_memo(r["memo"])
            title = r["place_name"] or subtitle or hours or "(미정)"
            if not r["place_name"]:
                hours = "" if title == hours else hours
                subtitle = ""
            elif _head(subtitle) and _head(subtitle) == _head(title):
                # ponytail: 앞 6글자만 본다. 장소명이 부제로 되풀이되는 것만 잡으면 된다
                subtitle = ""
            items.append({
                "id": r["id"], "slot": r["slot"], "place_id": r["place_id"],
                # 날짜가 있어야 그날의 다이어(휴일/평일)를 고를 수 있다
                "date": r["date"],
                "title": title, "subtitle": subtitle, "hours": hours or "–",
                "star": any(w in hours for w in STAR_WORDS),
                "plan_time": plan_time(r["slot"], hours or "–", r["memo"] or ""),
                "memo": r["memo"] or "",
                "icon": icon_for(r["place_name"] or title, r["place_category"]),
                **parse_move(move),
            })
        days.append({"day_no": day_no, "items": items, **meta})
    return days


def project(points, width=720, height=460, pad=40):
    """위경도를 SVG 좌표로 옮긴다.

    후쿠오카 시내 범위(위도 0.1도 미만)라 Mercator 가 필요 없다. 위도에 따라
    경도 1도의 실제 길이가 짧아지는 것만 cos(lat) 로 보정하면 모양이 안 찌그러진다.
    """
    if not points:
        return []
    lats = [p["lat"] for p in points]
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


def collect_route(conn):
    """일차별 동선. 좌표 없는 장소는 못 그리므로 빼고, 뺀 사실을 남긴다."""
    conn.row_factory = sqlite3.Row
    # LEFT JOIN 이어야 한다. INNER 로 하면 place_id 가 없는 일정(귀국 비행편 등)이
    # points 에도 missing 에도 안 남아 통째로 사라진다.
    rows = [dict(r) for r in conn.execute(
        "SELECT i.id AS itin_id, i.day_no, i.slot, i.seq, i.place_id, i.memo, "
        "p.name, p.category, p.lat, p.lng "
        "FROM itinerary i LEFT JOIN place p ON p.id = i.place_id")]
    rows.sort(key=lambda r: (r["day_no"], SLOT_ORDER.get(r["slot"], 9), r["seq"]))

    missing, keep = {}, []
    for r in rows:
        if r["lat"] is None or r["lng"] is None:
            hours, subtitle, _ = split_memo(r["memo"])
            # collect_days 의 제목과 같은 순서로 고른다. 카드와 지도 주석이
            # 서로 다른 이름을 부르면 사람이 대조를 못 한다.
            label = r["name"] or subtitle or hours or "(장소 미지정)"
            missing.setdefault(r["day_no"], []).append(label)
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


# 일정 장소 -> 지하철 역. 여기 없는 장소는 지하철로 못 가는 곳이라
# 시각표 대신 구글지도 경로 링크만 보여준다(JR·버스·도보 구간).
PLACE_STATION = {
    "호텔 포르자 하카타역 치쿠시구치Ⅱ": "하카타",
    "마잉구 (하카타 1번가)": "하카타",
    "한큐 하카타": "하카타",
    "아뮤플라자 하카타 (AMU)": "하카타",
    "텐진 지하상가": "텐진",
    "캐널시티 하카타": "나카스카와바타",
    "후쿠오카 호빵맨 어린이 박물관 in 쇼핑몰": "나카스카와바타",
}

# 여행 4일에 실제로 쓰이는 다이어만 싣는다. 토요일이 없는 일정이다.
TRIP_SERVICE_KINDS = ("휴일", "평일")

# 숙소가 하카타역 옆이라 모든 이동의 기점이다. JS 쪽 HOME_STATION 과 같은 값.
HOME_STATION = "하카타"


def collect_timetable(conn):
    """시각표를 페이지에 실을 만큼 압축한다.

    원본은 37,892행짜리 GTFS 다. 그대로 실으면 페이지가 수 MB 가 된다.
    방면 문자열은 사전으로 빼고, 시각은 자정 기준 분으로, 도착은 소요분으로
    줄이면 76KB 로 떨어진다.
    """
    conn.row_factory = sqlite3.Row
    holes = ",".join("?" * len(TRIP_SERVICE_KINDS))
    rows = conn.execute(
        f"SELECT from_stop, to_stop, service_kind, dep_time, arr_time, headsign "
        f"FROM timetable WHERE service_kind IN ({holes}) "
        f"ORDER BY from_stop, to_stop, service_kind, dep_time",
        TRIP_SERVICE_KINDS).fetchall()
    if not rows:
        return {"h": [], "legs": {}}

    heads = sorted({r["headsign"] or "" for r in rows})
    hidx = {h: i for i, h in enumerate(heads)}

    def mins(t):
        hh, mm = t.split(":")[:2]
        return int(hh) * 60 + int(mm)

    # 44개 구간을 다 실으면 78KB 다. 일정이 실제로 지나는 구간만 남기면 7KB.
    wanted = _wanted_legs(conn)
    legs = {}
    for r in rows:
        leg = f"{r['from_stop']}>{r['to_stop']}"
        if leg not in wanted:
            continue
        d = mins(r["dep_time"])
        legs.setdefault(f"{leg}|{r['service_kind']}", []).append(
            [d, mins(r["arr_time"]) - d, hidx[r["headsign"] or ""]])
    # 실린 구간에 쓰인 방면만 남겨 사전도 줄인다
    used = {h for v in legs.values() for _, _, h in v}
    return {"h": [h if i in used else "" for i, h in enumerate(heads)], "legs": legs}


def _wanted_legs(conn):
    """일정에 등장하는 목적지 + 귀국일 공항. 그 밖은 페이지에 실을 이유가 없다."""
    wanted = {f"{HOME_STATION}>후쿠오카공항"}   # 택시 예정이어도 대안으로 남긴다
    for r in conn.execute(
            "SELECT p.name FROM itinerary i JOIN place p ON p.id = i.place_id"):
        st = PLACE_STATION.get(r["name"])
        if st and st != HOME_STATION:
            wanted.add(f"{HOME_STATION}>{st}")
    return wanted


def collect_items(conn):
    """아이템 목록. 조회 로직은 trip.list_items 를 그대로 쓴다."""
    return [dict(r) for r in trip.list_items(conn)]


def collect_tips(conn):
    """참고사항. 조회는 trip.list_tips 를 그대로 쓰고, 근거만 리스트로 편다."""
    out = []
    for r in trip.list_tips(conn):
        t = dict(r)
        t["evidence_urls"] = [u.strip() for u in
                              (t.get("evidence_urls") or "").split("\n") if u.strip()]
        out.append(t)
    return out


TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>후쿠오카 3박 4일 · 하카타역 거점 여행 가이드</title>
<style>
:root{
  --bg:#f7f3fd; --card:#ffffff; --ink:#4a4550; --muted:#756b71;
  --line:#ece3f7;
  --v:#7b5ea7; --v-ink:#6b4c9a; --v-soft:#f0e9fb; --v-pill:#ded0f5;
  --y:#c9962f; --y-soft:#fdf6e3; --y-pill:#f7e6c8;
  --pink:#d1568a; --pink-soft:#fce4ee; --heart:#f48fb1;
  --star:#e8763a; --sky:#dff0fb;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Apple SD Gothic Neo","Malgun Gothic","Nanum Gothic",sans-serif;
  font-size:15px;line-height:1.6;-webkit-text-size-adjust:100%}
.wrap{max-width:1000px;margin:0 auto;padding:0 14px 110px}
a{color:var(--v-ink);text-decoration:underline;text-underline-offset:3px}

/* ---- 표지 ---- */
.hero{position:relative;margin-top:16px;border-radius:22px;overflow:hidden;
  background:var(--card);border:1px solid var(--line)}
.hero .art{display:block;width:100%;height:auto}
.hero .title{position:absolute;left:26px;top:22px}
.hero h1{margin:0;font-size:33px;font-weight:800;letter-spacing:-.035em;
  color:var(--v-ink);text-wrap:balance}
.hero h1 .hh{color:var(--heart);font-size:22px;vertical-align:5px}
.hero h2{margin:2px 0 0;font-size:17px;font-weight:700;color:var(--v)}
.hero p{margin:4px 0 0;font-size:13px;color:var(--muted)}
.script{position:absolute;right:26px;top:26px;font-size:27px;color:var(--v-ink);
  font-family:"Segoe Script","Brush Script MT",cursive;transform:rotate(-6deg)}

/* ---- 글로벌 네비게이션 ---- */
.global-nav{margin:16px 0;background:var(--card);border:1px solid var(--line);border-radius:20px;padding:12px;display:flex;gap:6px;overflow-x:auto;box-shadow:0 2px 10px rgba(123,94,167,.04);align-items:center}
.global-nav .chip{flex:none;font-size:14px;padding:6px 16px;border-radius:12px;border:none;background:var(--v-soft);color:var(--v-ink);font-weight:700;transition:all .2s;cursor:pointer}
.global-nav .chip.on{background:var(--v-ink);color:#fff}
.global-nav .chip:hover:not(.on){background:var(--v-pill)}
.global-nav .divider{width:1px;height:24px;background:var(--line);margin:0 4px;flex:none}
.global-nav .chip.extra{background:var(--y-soft);color:var(--y)}
.global-nav .chip.extra.on{background:var(--star);color:#fff}
.global-nav .chip.extra:hover:not(.on){background:var(--y-pill)}
.day-hidden { display: none !important; }
.section-hidden { display: none !important; }

/* ---- 일차 카드 ---- */
.day{margin:16px 0;border-radius:20px;border:1px solid var(--line);
  background:var(--card);display:grid;grid-template-columns:132px 1fr;
  overflow:hidden}
.side{padding:16px 12px;background:var(--v-soft);position:relative;
  display:flex;flex-direction:column;align-items:center;text-align:center}
.day.y .side{background:var(--y-soft)}
.side .n{font-size:25px;font-weight:800;color:var(--v-ink);letter-spacing:-.02em}
.day.y .side .n{color:var(--y)}
.side .n .hh{color:var(--heart);font-size:15px;vertical-align:4px}
.side .d{font-size:16px;font-weight:700;color:var(--v);margin-top:1px}
.day.y .side .d{color:var(--y)}
.holi{margin-top:7px;font-size:11.5px;background:var(--card);border-radius:999px;
  padding:2px 10px;border:1px solid var(--line);white-space:nowrap}
.holi i{color:#e2536a;font-style:normal}
.mascot{width:74px;height:74px;margin-top:14px}
.side .mood{margin-top:8px;font-size:11.5px;color:var(--muted);white-space:pre-line;
  line-height:1.45}

.panel{padding:10px 12px 12px;min-width:0}
.hdrow{display:grid;grid-template-columns:1fr 112px 1.6fr;gap:7px;
  font-size:12px;font-weight:700;text-align:center;color:var(--v-ink)}
.hdrow span{background:var(--v-pill);border-radius:8px;padding:4px 6px}
.day.y .hdrow span{background:var(--y-pill);color:var(--y)}
.row{display:grid;grid-template-columns:1fr 112px 1.6fr;gap:7px;
  padding:11px 0;border-bottom:1px dashed var(--line);align-items:center}
.row:last-child{border-bottom:0}

.main{display:flex;align-items:center;gap:10px;min-width:0}
.slot{flex:none;width:34px;font-size:12.5px;font-weight:700;color:var(--v);
  text-align:center}
.day.y .slot{color:var(--y)}
.pic{flex:none;width:50px;height:50px;border:1px solid var(--line);
  background:var(--v-soft);border-radius:14px;font-size:24px;line-height:1;
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:transform .15s,box-shadow .15s}
.day.y .pic{background:var(--y-soft)}
.pic:hover{transform:translateY(-2px) scale(1.04);
  box-shadow:0 5px 14px rgba(123,94,167,.22)}
.pic:focus-visible{outline:2px solid var(--v);outline-offset:2px}
.t{min-width:0}
.t b{display:block;font-size:14.5px;font-weight:700;line-height:1.35}
.t span{display:block;font-size:12px;color:var(--muted)}

.hours{font-size:12px;text-align:center;color:var(--star);white-space:pre-line}
.hours .star{font-size:13px}
.row.none .hours{color:var(--muted)}

.move{font-size:12px;color:#6d6570;min-width:0}
.leg{display:inline-block;background:var(--pink-soft);color:var(--pink);
  border-radius:999px;padding:2px 11px;font-weight:700;font-size:12px;
  margin-bottom:5px}
.day.y .leg{background:var(--y-pill);color:var(--y)}
.chain{display:flex;align-items:flex-start;gap:2px;overflow-x:auto;padding-bottom:3px}
.step{flex:0 0 auto;max-width:88px;text-align:center}
.step .e{display:block;width:30px;height:30px;margin:0 auto 3px;
  background:var(--sky);border-radius:10px;font-size:15px;line-height:30px}
.step b{display:block;font-size:10.5px;font-weight:700;color:var(--v-ink);
  line-height:1.25}
.step span{display:block;font-size:9.5px;color:var(--muted);line-height:1.3}
.arrow{flex:0 0 auto;color:var(--heart);font-size:12px;padding-top:7px}
.mnote{margin-top:4px}

.mapwrap{background:var(--card);border:1px solid var(--line);border-radius:20px;
  padding:14px;margin:16px 0}
.maphead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.maphead .sec{margin:0}
#routemap{width:100%;height:460px;background:var(--bg);
  border-radius:14px;overflow:hidden;}
.mapnote{margin:8px 0 0;font-size:12px;color:var(--muted)}
.mapcap{margin:6px 0 0;font-size:11.5px;color:var(--muted)}

/* ---- 팁 ---- */
.tipbar{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.tipbadge{font-size:11.5px;border:1px solid var(--v-pill);background:var(--v-soft);
  color:var(--v-ink);border-radius:999px;padding:2px 10px;max-width:100%;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* 여행 전체 팁은 네 카드에 모두 뜬다. 하루치 경고로 안 읽히게 톤을 낮춘다. */
.tipbadge.trip{background:var(--card);border-color:var(--line);color:var(--muted)}
.tipgroup{background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:11px 14px;margin-bottom:9px}
.tipgroup h4{margin:0 0 5px;font-size:14px;font-weight:800;color:var(--v-ink)}
.tip{border-top:1px dashed var(--line);padding:8px 0;font-size:13px}
.tipgroup .tip:first-of-type{border-top:0}
.tipmeta{font-size:11.5px;font-weight:700;color:var(--v)}
.tipev{margin-top:3px;font-size:11.5px;word-break:break-all}

/* ---- 장소 목록 ---- */
h3.sec{margin:32px 0 3px;font-size:19px;font-weight:800;color:var(--v-ink)}
.sec-sub{margin:0 0 11px;color:var(--muted);font-size:12.5px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:11px}
.chip{border:1px solid var(--line);background:var(--card);border-radius:999px;
  padding:5px 13px;font-size:12.5px;cursor:pointer;font-family:inherit;
  color:var(--ink)}
.chip.on{background:var(--v-ink);color:#fff;border-color:var(--v-ink)}
#grid,#itemgrid{display:grid;
  grid-template-columns:repeat(auto-fill,minmax(224px,1fr));gap:9px}
.tile{display:flex;gap:9px;align-items:center;background:var(--card);
  border:1px solid var(--line);border-radius:14px;padding:9px;
  text-align:left;font-family:inherit;font-size:13.5px;color:var(--ink);width:100%}
/* 누를 수 있는 것만 누를 수 있게 보인다. 아이템 타일은 그냥 카드다. */
button.tile{cursor:pointer}
button.tile:hover{box-shadow:0 5px 14px rgba(123,94,167,.16)}
.tile .e{font-size:22px;flex:none}
.tile b{display:block;font-weight:700;line-height:1.3}
.tile small{color:var(--muted)}
.tile.done{background:var(--v-soft)}
.tile .tg{display:inline-block;font-size:10.5px;background:var(--pink-soft);
  color:var(--pink);border-radius:999px;padding:1px 7px;margin-right:5px}
.dot{width:7px;height:7px;border-radius:50%;flex:none}
.d-ambiguous{background:#e0a02a} .d-not_found{background:#d1594c}
.d-pending{background:#a8a0ad} .d-matched{background:#79b58a}

/* ---- 팝업 ---- */
dialog{border:0;border-radius:20px;padding:0;max-width:520px;
  width:calc(100% - 28px);background:var(--card);color:var(--ink)}
dialog::backdrop{background:rgba(74,69,80,.45)}
.pop{padding:20px 22px 18px}
.pop .top{display:flex;gap:12px;align-items:flex-start}
.pop .e{font-size:36px;line-height:1}
.pop h4{margin:0;font-size:19px;font-weight:800;color:var(--v-ink);
  text-wrap:balance}
.badges{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.badge{font-size:11.5px;border:1px solid var(--line);border-radius:999px;
  padding:2px 9px;color:var(--muted)}
.pop dl{margin:13px 0 0;display:grid;grid-template-columns:74px 1fr;
  gap:6px 12px;font-size:13px}
.pop dt{color:var(--muted)} .pop dd{margin:0;word-break:break-word}
.tt{margin-top:14px;border-top:1px dashed var(--line);padding-top:12px}
.tt h5{margin:0 0 3px;font-size:13.5px;font-weight:800;color:var(--v-ink)}
.tt .leg{font-size:12px;color:var(--muted);margin-bottom:7px}
.tt table{width:100%;border-collapse:collapse;font-size:13px;
  font-variant-numeric:tabular-nums}
.tt td{padding:3px 0}
.tt td.t{font-weight:700;color:var(--v-ink);white-space:nowrap}
.tt td.d{color:var(--muted);font-size:12px;padding-left:8px}
.tt .soon{color:var(--pink)}
.tt .warn{margin-top:7px;font-size:11.5px;color:var(--muted);line-height:1.45}
.tt .links{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.tt .links a{font-size:12px;border:1px solid var(--line);border-radius:8px;
  padding:5px 10px;text-decoration:none;color:var(--v-ink);background:var(--bg)}
.pop .acts{display:flex;gap:8px;align-items:center;margin-top:15px;flex-wrap:wrap}
.btn{border:1px solid var(--line);background:var(--card);border-radius:10px;
  padding:8px 14px;font-size:13px;cursor:pointer;font-family:inherit;
  color:var(--ink);text-decoration:none}
.btn.go{background:var(--v-ink);border-color:var(--v-ink);color:#fff}
.btn.off{color:var(--muted);cursor:not-allowed}
.savebox{display:flex;gap:7px;align-items:center;font-size:13px;margin-left:auto}

/* ---- 하단 명령 바 ---- */
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);
  border-top:1px solid var(--line);padding:8px 14px;display:flex;gap:10px;
  align-items:center;flex-wrap:wrap;font-size:12.5px;z-index:5}
.bar code{background:var(--bg);border:1px solid var(--line);border-radius:8px;
  padding:5px 9px;flex:1;min-width:180px;overflow:auto;white-space:nowrap}
footer{color:var(--muted);font-size:11.5px;padding:24px 0 6px;text-align:center}

@keyframes fall{to{transform:translateY(78px) rotate(150deg);opacity:0}}
.petal{animation:fall 9s linear infinite}
.petal:nth-of-type(2){animation-delay:2.4s} .petal:nth-of-type(3){animation-delay:4.9s}

/* 인터랙티브 애니메이션 */
@keyframes shake { 0%,100%{transform:translateY(0)} 25%{transform:translateY(-2px) rotate(-3deg)} 75%{transform:translateY(1px) rotate(3deg)} }
.anim-shake { animation: shake 0.6s infinite ease-in-out }
@keyframes walk { 0%,100%{transform:rotate(0deg)} 25%{transform:rotate(-8deg)} 75%{transform:rotate(8deg)} }
.anim-walk { animation: walk 0.8s infinite ease-in-out; transform-origin: bottom center }
@keyframes flow { 0%{transform:translateX(0);opacity:.5} 50%{transform:translateX(3px);opacity:1} 100%{transform:translateX(0);opacity:.5} }
.anim-flow { animation: flow 1.5s infinite ease-in-out; display:inline-block }
@keyframes cherryFall { 0%{transform:translateY(-10px) rotate(0deg) translateX(0);opacity:0} 10%{opacity:1} 90%{opacity:1} 100%{transform:translateY(100vh) rotate(360deg) translateX(50px);opacity:0} }
.cherry-blossom { position:fixed; top:-20px; color:#f48fb1; user-select:none; pointer-events:none; z-index:9999; animation:cherryFall linear forwards }

@media(prefers-reduced-motion:reduce){.petal,.anim-shake,.anim-walk,.anim-flow,.cherry-blossom{animation:none}}

@media(max-width:780px){
  .day{grid-template-columns:1fr}
  .side{flex-direction:row;gap:10px;justify-content:flex-start;text-align:left;
    padding:11px 14px}
  .side .mood{display:none} .mascot{width:42px;height:42px;margin:0}
  .hdrow{display:none}
  .row{grid-template-columns:1fr;gap:7px}
  .hours,.move{text-align:left}
  .hours::before{content:"영업시간 · "}
  .hero h1{font-size:25px} .script{display:none}
}
</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <svg class="art" viewBox="0 0 1000 150" role="img"
       aria-label="후쿠오카 하늘과 도시 일러스트">
    <defs>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#eaf5fd"/><stop offset="1" stop-color="#fdf4fa"/>
      </linearGradient>
    </defs>
    <rect width="1000" height="150" fill="url(#sky)"/>
    <g fill="#ffffff" opacity=".92">
      <ellipse cx="640" cy="44" rx="30" ry="17"/><ellipse cx="668" cy="48" rx="22" ry="13"/>
      <ellipse cx="860" cy="34" rx="26" ry="15"/><ellipse cx="884" cy="39" rx="19" ry="11"/>
    </g>
    <g fill="#cfe4f5">
      <rect x="700" y="86" width="34" height="64" rx="4"/>
      <rect x="742" y="70" width="26" height="80" rx="4"/>
      <rect x="776" y="96" width="38" height="54" rx="4"/>
      <rect x="900" y="80" width="30" height="70" rx="4"/>
      <rect x="938" y="100" width="34" height="50" rx="4"/>
    </g>
    <g stroke="#a8cfe8" stroke-width="2" fill="#e4f1fa">
      <path d="M836 150 L848 42 L860 150 Z"/>
      <path d="M848 42 L848 30"/>
    </g>
    <g fill="#f7c8dc">
      <circle class="petal" cx="120" cy="24" r="5"/>
      <circle class="petal" cx="300" cy="14" r="4"/>
      <circle class="petal" cx="470" cy="30" r="5"/>
    </g>
    <g fill="#fbdcea">
      <circle cx="52" cy="112" r="7"/><circle cx="70" cy="132" r="5"/>
      <circle cx="978" cy="126" r="6"/>
    </g>
  </svg>
  <div class="title">
    <h1>후쿠오카 3박 4일 <span class="hh">♥</span></h1>
    <h2>하카타역 거점 여행 가이드</h2>
    <p>맛있는 것도, 행복한 것도, 우리만의 속도로 :)</p>
  </div>
  <div class="script">Fukuoka</div>
</header>

<nav class="global-nav" id="globalnav"></nav>

<div id="section-days">
  <div id="days"></div>

  <section class="mapwrap">
    <div class="maphead">
      <h3 class="sec">동선</h3>
      <div class="tabs" id="daytabs"></div>
    </div>
    <div id="routemap"></div>
    <p class="mapnote" id="mapnote"></p>
    <p class="mapcap">실제 도로 및 교통편을 반영한 구글 지도 동선입니다.</p>
  </section>
</div>

<div id="section-tips" class="section-hidden">
  <h3 class="sec">참고사항</h3>
  <p class="sec-sub">조사해서 근거와 함께 저장한 것이다.
    날씨·공휴일·혼잡은 위 DAY 카드에도 배지로 얹혀 있다.</p>
  <div id="tips"></div>
</div>

<div id="section-items" class="section-hidden">
  <h3 class="sec">살거 · 먹을거 · 놀거</h3>
  <p class="sec-sub">장소와 연결된 것은 장소 이름이 같이 나온다.</p>
  <div class="tabs" id="itemtabs"></div>
  <div id="itemgrid"></div>
</div>

<div id="section-places" class="section-hidden">
  <h3 class="sec">장소 목록</h3>
  <p class="sec-sub">그림을 누르면 주소·근거·지도 링크가 팝업으로 열린다.
    내 지도에 저장한 것은 팝업에서 체크하면 아래 명령이 만들어진다.</p>
  <div class="tabs" id="tabs"></div>
  <div id="grid"></div>
</div>

<footer>생성 __GENERATED__ · 장소 __TOTAL__건 · 이 페이지는 DB 에 아무것도 쓰지 않는다</footer>
</div>

<dialog id="pop"><div class="pop" id="popbody"></div></dialog>

<div class="bar">
  <b id="picked">0건</b>
  <code id="cmd">체크한 장소가 없다</code>
  <button class="btn" id="copy">명령 복사</button>
</div>

<script src="https://maps.googleapis.com/maps/api/js?key=__API_KEY__"></script>
<script>
const PLACES = __PLACES__;
const DAYS = __DAYS__;
const LABEL = __LABELS__;
const ROUTE = __ROUTE__;
const ITEMS = __ITEMS__;
const TIMETABLE = __TIMETABLE__;
const PLACE_STATION = __STATIONS__;
/* 여행 4일의 다이어. 9/21~23 은 공휴일이라 평일 다이어가 꺼지고 휴일 다이어가
   돌아간다 — GTFS calendar_dates 예외에 그렇게 들어 있다. */
const TRIP_KIND = {"2026-09-21":"휴일","2026-09-22":"휴일",
                   "2026-09-23":"휴일","2026-09-24":"평일"};
const TIPS = __TIPS__;
const KEY = "trip.mymaps.checked";
const byId = Object.fromEntries(PLACES.map(p => [p.id, p]));
/* 샌드박스 iframe(Artifact 등)에서는 localStorage 접근 자체가 예외를 던진다.
   막아 두지 않으면 스크립트가 통째로 죽어 빈 화면이 된다. */
const store = {
  read() { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); }
           catch { return []; } },
  write(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch {} },
};
let checked = new Set(store.read());
let filter = "all";

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const host = u => { try { return new URL(u).hostname.replace(/^www\\./, ""); }
                    catch { return u; } };

/* ---------- 마스코트 (자체 도안) ---------- */
const MASCOT = {
  dog: `<circle cx="37" cy="40" r="24" fill="#fff" stroke="#e3d6f2" stroke-width="2"/>
    <ellipse cx="20" cy="32" rx="6.5" ry="10" fill="#d9b48f" transform="rotate(-22 20 32)"/>
    <ellipse cx="54" cy="32" rx="6.5" ry="10" fill="#d9b48f" transform="rotate(22 54 32)"/>
    <circle cx="29" cy="38" r="3" fill="#4a4550"/><circle cx="45" cy="38" r="3" fill="#4a4550"/>
    <ellipse cx="37" cy="46" rx="4" ry="3" fill="#c98fa6"/>
    <circle cx="22" cy="46" r="4" fill="#fbdcea"/><circle cx="52" cy="46" r="4" fill="#fbdcea"/>`,
  bunny: `<ellipse cx="21" cy="18" rx="6" ry="14" fill="#fff" stroke="#e3d6f2" stroke-width="2"/>
    <ellipse cx="53" cy="18" rx="6" ry="14" fill="#fff" stroke="#e3d6f2" stroke-width="2"/>
    <circle cx="37" cy="42" r="23" fill="#fff" stroke="#e3d6f2" stroke-width="2"/>
    <circle cx="29" cy="40" r="3" fill="#4a4550"/><circle cx="45" cy="40" r="3" fill="#4a4550"/>
    <path d="M33 48 q4 4 8 0" stroke="#c98fa6" stroke-width="2" fill="none"/>
    <circle cx="22" cy="47" r="4" fill="#dff0fb"/><circle cx="52" cy="47" r="4" fill="#dff0fb"/>`,
  cat: `<path d="M18 26 L22 10 L32 20 Z" fill="#5b5266"/>
    <path d="M56 26 L52 10 L42 20 Z" fill="#5b5266"/>
    <circle cx="37" cy="42" r="23" fill="#5b5266"/>
    <circle cx="29" cy="40" r="3.4" fill="#fff"/><circle cx="45" cy="40" r="3.4" fill="#fff"/>
    <path d="M32 49 q5 5 10 0" stroke="#f2b8cf" stroke-width="2" fill="none"/>
    <circle cx="52" cy="20" r="6" fill="#f2b8cf"/>`,
  bear: `<circle cx="20" cy="24" r="9" fill="#f2d69a"/><circle cx="54" cy="24" r="9" fill="#f2d69a"/>
    <circle cx="37" cy="42" r="24" fill="#fbe9bd" stroke="#efd79a" stroke-width="2"/>
    <circle cx="29" cy="39" r="3" fill="#4a4550"/><circle cx="45" cy="39" r="3" fill="#4a4550"/>
    <ellipse cx="37" cy="47" rx="9" ry="7" fill="#fff6e0"/>
    <ellipse cx="37" cy="45" rx="3.4" ry="2.6" fill="#8a6a3d"/>`,
};
const mascot = k => `<svg class="mascot" viewBox="0 0 74 74" aria-hidden="true">
  ${MASCOT[k] || MASCOT.dog}</svg>`;

/* ---------- 일차 카드 ---------- */
function renderDays() {
  document.getElementById("days").innerHTML = DAYS.map(d => `
  <section class="day ${d.tone === "y" ? "y" : ""}" data-dayno="${d.day_no}">
    <div class="side">
      <div>
        <div class="n">DAY ${d.day_no} <span class="hh">♥</span></div>
        <div class="d">${esc(d.date)}</div>
        ${d.holiday ? '<div class="holi"><i>●</i> 공휴일</div>' : ""}
      </div>
      ${mascot(d.mascot)}
      <div class="mood">${esc(d.mood)}</div>
    </div>
    <div class="panel">
      ${tipBadges(d.day_no)}
      <div class="hdrow"><span>주요 일정</span><span>영업시간</span>
        <span>이동 동선 / 교통편</span></div>
      ${d.items.length ? d.items.map(row).join("")
        : '<div class="row"><div class="main">일정 없음</div></div>'}
    </div>
  </section>`).join("");
}

function row(it) {
  return `
  <div class="row${it.hours === "–" ? " none" : ""}">
    <div class="main">
      <div class="slot">${esc(it.slot)}</div>
      <button class="pic" data-itin="${it.id}"
        aria-label="${esc(it.title)} 상세 보기">${it.icon}</button>
      <div class="t">
        <b>${esc(it.title)}</b>
        ${it.subtitle ? `<span>${esc(it.subtitle)}</span>` : ""}</div>
    </div>
    <div class="hours">${it.star ? '<span class="star">★</span> ' : ""}${esc(it.hours)}</div>
    <div class="move">
      ${it.leg ? `<div class="leg">${esc(it.leg)}</div>` : ""}
      ${it.chain.length ? chain(it.chain) : ""}
      ${it.note ? `<div class="mnote">${esc(it.note)}</div>` : ""}
    </div>
  </div>`;
}

function chain(steps) {
  return `<div class="chain">` + steps.map((s, i) => {
    let animClass = "";
    if (["🚇","🚃","🚌","🚕"].includes(s.icon)) animClass = " anim-shake";
    else if (s.icon.includes("🚶")) animClass = " anim-walk";
    return `
    ${i ? '<span class="arrow anim-flow">→</span>' : ""}
    <div class="step"><span class="e${animClass}">${s.icon}</span>
      <b>${esc(s.name)}</b>
      ${s.detail ? `<span>${esc(s.detail)}</span>` : ""}</div>`;
  }).join("") + `</div>`;
}

/* ---------- 참고사항 ---------- */
/* 날씨·공휴일·혼잡만 배지로 얹는다 (스펙 §4). 나머지는 아래 목록에서 본다.
   여행 전체(scope=trip) 팁은 네 카드에 다 뜨므로 흐린 톤으로 구분한다. */
const BADGE_CATS = ["날씨", "공휴일", "혼잡"];
const BADGE_LEN = 38;

function summarizeTip(cat, txt) {
  if (cat === "날씨") {
    let emoji = "⛅";
    if (txt.includes("비")) emoji = "☔";
    else if (txt.includes("맑")) emoji = "☀️";
    else if (txt.includes("흐")) emoji = "☁️";
    let desc = txt;
    let parts = txt.split(/은\\s+/);
    if (parts.length > 1) {
      desc = parts[1].split(".")[0].trim();
    }
    return `${emoji} ${desc}`;
  }
  if (cat === "공휴일") {
    let name = "공휴일";
    let parts = txt.split(/은\\s+/);
    if (parts.length > 1) {
      let m = parts[1].match(/\\(([^)]+)\\)/);
      if (m) name = m[1];
      else name = parts[1].split(/[.,\\s]/)[0];
    }
    return `🎌 ${name}`;
  }
  if (cat === "혼잡") return "⚠️ 혼잡주의";
  return `💡 ${cat}`;
}

function tipBadges(dayNo) {
  const rel = TIPS.filter(t => BADGE_CATS.includes(t.category)
    && (t.day_no === dayNo || t.scope === "trip"));
  if (!rel.length) return "";
  return `<div class="tipbar">` + rel.map(t => {
    const wide = t.scope === "trip";
    const text = String(t.text || "");
    const summary = summarizeTip(t.category, text);
    return `<span class="tipbadge${wide ? " trip" : ""}" title="${esc(text)}">${esc(summary)}</span>`;
  }).join("") + `</div>`;
}

function tipLinks(urls) {
  if (!urls || !urls.length) return "";
  return `<div class="tipev">근거 ` + urls.map(u =>
    `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))}</a>`)
    .join(" · ") + `</div>`;
}

function tipWho(t) {
  if (t.day_no) return `${t.day_no}일차`;
  if (t.scope === "place") return t.place_name || "장소";
  return "여행 전체";
}

function renderTips() {
  const cats = [...new Set(TIPS.map(t => t.category))];
  document.getElementById("tips").innerHTML = cats.map(c =>
    `<div class="tipgroup"><h4>${esc(c)}</h4>` +
    TIPS.filter(t => t.category === c).map(t => `<div class="tip">
      <div class="tipmeta">${esc(tipWho(t))}</div>
      <div>${esc(t.text)}</div>
      ${tipLinks(t.evidence_urls)}</div>`).join("") + `</div>`).join("")
    || "<p>아직 없다. python trip.py add 로 넣는다.</p>";
}

/* ---------- 장소 목록 ---------- */
const TABS = [["all", "전체"], ["planned", "일정에 있는 곳"], ["쇼핑", "쇼핑"],
              ["맛집", "맛집"], ["관광", "관광"], ["unsaved", "아직 저장 안 함"],
              ["ambiguous", "확인 필요"]];

function matches(p) {
  if (filter === "all") return true;
  if (filter === "planned") return p.days.length > 0;
  if (filter === "unsaved") return !p.saved_to_mymaps && !checked.has(p.id);
  if (filter === "ambiguous") return p.verify_status !== "matched";
  return p.category === filter;
}

function renderGrid() {
  const shown = PLACES.filter(matches);
  document.getElementById("grid").innerHTML = shown.map(p => {
    const on = p.saved_to_mymaps || checked.has(p.id);
    return `<button class="tile${on ? " done" : ""}" data-place="${p.id}">
      <span class="e">${p.icon}</span>
      <span><b>${esc(p.name)}</b>
        <small>${esc(p.category)}${p.days.length
          ? " · " + p.days.map(d => d.day_no + "일차").join(",") : ""}</small></span>
      <span class="dot d-${p.verify_status}"
        title="${esc(LABEL[p.verify_status] || "")}"></span></button>`;
  }).join("") || "<p>없음</p>";
}

/* ---------- 아이템 ---------- */
const ITEM_TABS = ["전체", "살거", "먹을거", "놀거"];
let itemFilter = "전체";

function renderItems() {
  const shown = ITEMS.filter(
    i => itemFilter === "전체" || i.category === itemFilter);
  document.getElementById("itemgrid").innerHTML = shown.map(i => {
    let placeHtml = `<small>장소 미정</small>`;
    if (i.places) {
      const names = i.places.split(", ");
      placeHtml = names.map(name => {
        const p = PLACES.find(x => x.name === name);
        if (p) return `<a href="#" onclick="openPlace(${p.id}); return false;" style="display:inline-block; margin-right:8px; text-decoration:underline;">📍 ${esc(name)}</a>`;
        return `<small style="margin-right:8px;">${esc(name)}</small>`;
      }).join("");
      placeHtml = `<div style="margin-top:4px; font-size:13px;">${placeHtml}</div>`;
    }
    
    return `<div class="tile${i.done ? " done" : ""}">
      <span class="e">${i.category === "살거" ? "🛍️"
        : i.category === "먹을거" ? "🍜" : "🎡"}</span>
      <span style="display:flex; flex-direction:column; align-items:flex-start;">
        <b>${i.tag ? `<span class="tg">${esc(i.tag)}</span>` : ""}${esc(i.name)}</b>
        ${placeHtml}
        ${i.note ? `<small style="margin-top:4px; color:var(--muted);">${esc(i.note)}</small>` : ""}
      </span></div>`;
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

/* ---------- 다음 열차 (시각표 조회) ---------- */
const HOME_STATION = "하카타";   // 숙소가 하카타역 옆이라 기본 출발지

function pad2(n) { return String(n).padStart(2, "0"); }
function hhmm(m) { return pad2(Math.floor(m / 60) % 24) + ":" + pad2(m % 60); }

function mapsDirUrl(from, to) {
  return "https://www.google.com/maps/dir/?api=1&travelmode=transit"
    + "&origin=" + encodeURIComponent(from + " 駅 福岡")
    + "&destination=" + encodeURIComponent(to + " 駅 福岡");
}

/* 일정 날짜의 다이어를 고른다. 여행일 밖이면 요일로 떨어뜨린다. */
function serviceKind(dateStr) {
  if (TRIP_KIND[dateStr]) return TRIP_KIND[dateStr];
  const d = dateStr ? new Date(dateStr + "T00:00:00") : new Date();
  const w = d.getDay();
  return w === 0 ? "휴일" : w === 6 ? "토요" : "평일";
}

function nextTrains(placeName, dateStr, planMin) {
  const to = PLACE_STATION[placeName];
  /* 지하철 역이 없는 곳(JR·버스·도보 구간)도 구글지도 경로는 보여준다.
     링크까지 빼면 사용자가 아무 안내도 못 받는다. */
  const dest = to || placeName;
  if (!placeName || to === HOME_STATION) return "";
  const kind = serviceKind(dateStr);
  const rows = to
    ? (TIMETABLE.legs || {})[HOME_STATION + ">" + to + "|" + kind] : null;

  const links = `<div class="links">
    <a href="${mapsDirUrl(HOME_STATION, dest)}" target="_blank" rel="noopener">구글지도 경로</a>
    <a href="https://www.jrkyushu.co.jp/trains/info/fukhok.html" target="_blank" rel="noopener">JR 운행정보</a>
    <a href="https://subway.city.fukuoka.lg.jp/" target="_blank" rel="noopener">지하철 공식</a>
  </div>`;

  if (!rows || !rows.length) {
    return `<div class="tt"><h5>가는 길</h5>
      <div class="leg">${esc(HOME_STATION)} → ${esc(dest)}</div>
      <div class="warn">지하철 직통 시각표가 없는 구간이다. JR·버스·도보가 섞여 있어
        구글지도에서 확인하는 게 정확하다.</div>${links}</div>`;
  }

  /* 기준 시각을 정한다.
     여행 당일이면 '지금', 아니면 일정에서 추정한 출발 시각을 쓴다.
     첫차부터 보여주면(예전 동작) 오후 일정인데 05:30 열차가 뜬다. */
  const now = new Date();
  const today = now.getFullYear() + "-" + pad2(now.getMonth() + 1) + "-" + pad2(now.getDate());
  const isToday = dateStr && dateStr === today;
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const base = isToday ? nowMin
    : (typeof planMin === "number" ? planMin : -1);

  let list = base >= 0 ? rows.filter(r => r[0] >= base).slice(0, 3) : [];
  const anchored = list.length > 0;
  if (!list.length) list = rows.slice(0, 3);

  const body = list.map((r, i) => {
    const wait = (isToday && anchored) ? r[0] - nowMin : null;
    const soon = i === 0 && wait !== null && wait <= 10;
    return `<tr>
      <td class="t${soon ? " soon" : ""}">${hhmm(r[0])} 발 → ${hhmm(r[0] + r[1])} 착</td>
      <td class="d">${esc(TIMETABLE.h[r[2]] || "")} 방면 · ${r[1]}분
        ${wait !== null ? `· ${wait}분 뒤` : ""}</td></tr>`;
  }).join("");

  return `<div class="tt"><h5>가는 길 — 다음 열차</h5>
    <div class="leg">${esc(HOME_STATION)} → ${esc(to)} (지하철)
      ${isToday ? "· 지금 시각 기준"
        : anchored ? `· ${hhmm(base)} 출발 예정 기준(추정)` : "· 첫차부터"}</div>
    <table>${body}</table>
    <div class="warn">시각표 기준이라 <b>지연은 반영되지 않는다</b>.
      실제 운행 상황은 아래 링크에서 확인할 것.</div>${links}</div>`;
}

/* ---------- 팝업 ---------- */
const pop = document.getElementById("pop");

function openPlace(id, itin) {
  const p = byId[id];
  if (!p && !itin) return;
  const on = p && (p.saved_to_mymaps || checked.has(p.id));
  const ev = (p?.evidence || []).map(u =>
    `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))}</a>`).join(" · ");
  const rows = [];
  if (itin) {
    rows.push(["일정", `${itin.day_no}일차 ${esc(itin.slot)}`]);
    if (itin.hours && itin.hours !== "–") rows.push(["영업시간", esc(itin.hours)]);
    if (itin.memo) rows.push(["메모", esc(itin.memo)]);
  }
  if (p) {
    rows.push(["카테고리", esc(p.category)]);
    if (p.name_verified && p.name_verified !== p.name)
      rows.push(["구글 표기", esc(p.name_verified)]);
    rows.push(["주소", p.address ? esc(p.address)
      : '<span style="color:#9b9096">주소 미확보 — trip.py pending 으로 조사 필요</span>']);
    if (p.note) rows.push(["노트", esc(p.note)]);
    if (ev) rows.push(["근거", ev]);
    if (!itin && p.days.length)
      rows.push(["일정", p.days.map(d => `${d.day_no}일차 ${esc(d.slot)}`).join(", ")]);
  }

  document.getElementById("popbody").innerHTML = `
    <div class="top">
      <div class="e">${(p && p.icon) || (itin && itin.icon) || "📍"}</div>
      <div>
        <h4>${esc(p ? p.name : itin.title)}</h4>
        <div class="badges">
          ${p ? `<span class="badge">#${p.id}</span>
                 <span class="badge">${esc(LABEL[p.verify_status] || p.verify_status)}</span>`
              : '<span class="badge">장소 미지정</span>'}
        </div>
      </div>
    </div>
    <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    ${nextTrains(p ? p.name : (itin ? itin.title : ""),
                 itin ? itin.date : null, itin ? itin.plan_time : null)}
    <div class="acts">
      ${p && p.maps_url
        ? `<a class="btn go" href="${esc(p.maps_url)}" target="_blank"
             rel="noopener">지도 열기</a>`
        : '<span class="btn off">지도 링크 없음</span>'}
      ${p ? `<label class="savebox">
        <input type="checkbox" data-id="${p.id}"${on ? " checked" : ""}
          ${p.saved_to_mymaps ? " disabled" : ""}> 내 지도에 저장함</label>` : ""}
      <button class="btn" id="close">닫기</button>
    </div>`;
  pop.showModal();
}

document.addEventListener("click", e => {
  if (e.target.id === "close") return pop.close();
  const dot = e.target.closest(".rt-dot");
  if (dot) {
    const iid = Number(dot.dataset.itin);
    for (const d of DAYS) {
      const it = d.items.find(x => x.id === iid);
      if (it) return openPlace(it.place_id, { ...it, day_no: d.day_no });
    }
    return;
  }
  const picBtn = e.target.closest(".pic");
  if (picBtn) {
    const iid = Number(picBtn.dataset.itin);
    for (const d of DAYS) {
      const it = d.items.find(x => x.id === iid);
      if (it) return openPlace(it.place_id, { ...it, day_no: d.day_no });
    }
    return;
  }
  const tile = e.target.closest("button.tile");
  if (tile) return openPlace(Number(tile.dataset.place), null);
  if (e.target === pop) pop.close();
});

pop.addEventListener("change", e => {
  const id = Number(e.target.dataset.id);
  if (!id) return;
  e.target.checked ? checked.add(id) : checked.delete(id);
  store.write([...checked]);
  renderGrid();
  renderCmd();
});

/* ---------- 하단 명령 ---------- */
function renderCmd() {
  const ids = [...checked].filter(i => !byId[i]?.saved_to_mymaps).sort((a, b) => a - b);
  document.getElementById("cmd").textContent = ids.length
    ? `python trip.py mark-saved ${ids.join(" ")}` : "체크한 장소가 없다";
  document.getElementById("picked").textContent = `${ids.length}건`;
}

document.getElementById("tabs").innerHTML = TABS.map(([f, label], i) =>
  `<button class="chip${i === 0 ? " on" : ""}" data-f="${f}">${label}</button>`).join("");
document.getElementById("tabs").addEventListener("click", e => {
  const b = e.target.closest(".chip");
  if (!b) return;
  document.querySelectorAll(".chip").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  filter = b.dataset.f;
  renderGrid();
});
document.getElementById("copy").addEventListener("click", () => {
  const t = document.getElementById("cmd").textContent;
  if (!t.startsWith("python")) return;
  const b = document.getElementById("copy");
  // 샌드박스 iframe 은 클립보드를 막는다. 실패해도 페이지는 살아 있어야 한다.
  Promise.resolve(navigator.clipboard?.writeText(t))
    .then(() => b.textContent = "복사됨")
    .catch(() => b.textContent = "복사 불가");
  setTimeout(() => b.textContent = "명령 복사", 1400);
});

/* ---------- 동선 지도 ---------- */
const DAY_COLOR = {1: "#7b5ea7", 2: "#4a7fb5", 3: "#5aa469", 4: "#c9962f"};
let mapFilter = "all";

function renderMap() {
  const container = document.getElementById("routemap");
  const pts = ROUTE.points.filter(
    p => mapFilter === "all" || p.day_no === Number(mapFilter));
  
  if (!pts.length) {
    container.innerHTML = "<div style='padding:20px;text-align:center;'>표시할 지점이 없습니다.</div>";
    return;
  }

  const map = new google.maps.Map(container, {
    zoom: 12,
    center: {lat: pts[0].lat, lng: pts[0].lng},
    mapTypeId: 'roadmap',
    disableDefaultUI: true,
    zoomControl: true,
  });

  const bounds = new google.maps.LatLngBounds();
  pts.forEach(p => {
    const pos = {lat: p.lat, lng: p.lng};
    bounds.extend(pos);
    new google.maps.Marker({
      position: pos,
      map: map,
      label: {
        text: String(p.seq_in_day),
        color: "white",
        fontWeight: "bold"
      },
      title: p.name
    });
  });
  
  if (pts.length > 1) {
    map.fitBounds(bounds, {top: 40, bottom: 40, left: 40, right: 40});
  }

  const days = [...new Set(pts.map(p => p.day_no))].sort((a, b) => a - b);
  const directionsService = new google.maps.DirectionsService();

  for (const d of days) {
    const seq = pts.filter(p => p.day_no === d).sort((a, b) => a.seq_in_day - b.seq_in_day);
    if (seq.length < 2) continue;
    const color = DAY_COLOR[d] || "#7b5ea7";
    
    for (let i = 0; i < seq.length - 1; i++) {
        directionsService.route({
            origin: {lat: seq[i].lat, lng: seq[i].lng},
            destination: {lat: seq[i+1].lat, lng: seq[i+1].lng},
            travelMode: google.maps.TravelMode.TRANSIT
        }, (response, status) => {
            if (status === 'OK') {
                new google.maps.DirectionsRenderer({
                    map: map,
                    directions: response,
                    suppressMarkers: true,
                    preserveViewport: true,
                    polylineOptions: {
                        strokeColor: color,
                        strokeOpacity: 0.8,
                        strokeWeight: 5
                    }
                });
            } else {
                new google.maps.Polyline({
                    path: [
                        {lat: seq[i].lat, lng: seq[i].lng},
                        {lat: seq[i+1].lat, lng: seq[i+1].lng}
                    ],
                    strokeColor: color,
                    strokeOpacity: 0.8,
                    strokeWeight: 4,
                    map: map
                });
            }
        });
    }
  }

  const miss = Object.entries(ROUTE.missing)
    .filter(([d]) => mapFilter === "all" || Number(d) === Number(mapFilter));
  const total = miss.reduce((n, [, names]) => n + names.length, 0);
  document.getElementById("mapnote").textContent = total
    ? `좌표가 없어 지도에 없는 곳 ${total}곳: ` +
      miss.map(([d, names]) => `${d}일차 ${names.join(", ")}`).join(" / ")
    : "";
}

/* ---------- 글로벌 네비게이션 & 벚꽃 애니메이션 ---------- */
const ALL_DAYS = [["all", "전체"], ...[1, 2, 3, 4].map(d => [String(d), `DAY ${d}`])];
const EXTRA_TABS = [["tips", "참고사항"], ["items", "살거·먹을거·놀거"], ["places", "장소 목록"]];

function initNav() {
  document.getElementById("globalnav").innerHTML = ALL_DAYS.map(([f, label], i) =>
    `<button class="chip${i === 0 ? " on" : ""}" data-nav="${f}">${label}</button>`
  ).join("") + `<div class="divider"></div>` + EXTRA_TABS.map(([f, label]) => 
    `<button class="chip extra" data-nav="${f}">${label}</button>`
  ).join("");
  
  const oldDayTabs = document.getElementById("daytabs");
  if (oldDayTabs) oldDayTabs.style.display = "none";
  
  document.getElementById("globalnav").addEventListener("click", e => {
    const b = e.target.closest(".chip");
    if (!b) return;
    document.querySelectorAll("#globalnav .chip").forEach(x => x.classList.remove("on"));
    b.classList.add("on");
    const nav = b.dataset.nav;
    
    // 섹션 토글
    document.getElementById("section-days").classList.toggle("section-hidden", !["all", "1", "2", "3", "4"].includes(nav));
    document.getElementById("section-tips").classList.toggle("section-hidden", nav !== "tips");
    document.getElementById("section-items").classList.toggle("section-hidden", nav !== "items");
    document.getElementById("section-places").classList.toggle("section-hidden", nav !== "places");
    
    // 일차(DAY) 필터링 (days 섹션일 때만)
    if (["all", "1", "2", "3", "4"].includes(nav)) {
      mapFilter = nav;
      document.querySelectorAll("#days section.day").forEach(el => {
        const dayNo = el.dataset.dayno;
        el.classList.toggle("day-hidden", nav !== "all" && nav !== dayNo);
      });
      renderMap();
    }
  });
}

function spawnBlossom() {
  const p = document.createElement("div");
  p.className = "cherry-blossom";
  p.innerHTML = "🌸";
  p.style.left = Math.random() * 100 + "vw";
  p.style.animationDuration = (Math.random() * 4 + 4) + "s";
  p.style.fontSize = (Math.random() * 10 + 10) + "px";
  document.body.appendChild(p);
  setTimeout(() => p.remove(), 9000);
}
setInterval(spawnBlossom, 800);

try {
  renderMap();
} catch (e) {
  console.error("Map rendering failed:", e);
  document.getElementById("routemap").innerHTML = "<div style='padding:20px;text-align:center;'>지도 로딩 실패. 콘솔을 확인하세요.</div>";
}
renderDays();
initNav();
renderTips();
renderGrid();
renderItems();
renderCmd();
</script>
</body>
</html>
"""


def get_google_maps_key():
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('GOOGLE_MAPS_API_KEY='):
                    return line.strip().split('=', 1)[1]
    except Exception:
        pass
    return ""


def build_page(conn, generated="", fragment=False):
    """fragment=True 면 <title>+<style>+본문만 준다.

    Artifact 는 <!doctype>/<html>/<head>/<body> 껍데기를 자기가 씌운다.
    같은 껍데기를 또 주면 중첩 문서가 된다.
    """
    places = collect(conn)
    page = (TEMPLATE
            .replace("__PLACES__", json.dumps(places, ensure_ascii=False))
            .replace("__DAYS__", json.dumps(collect_days(conn), ensure_ascii=False))
            .replace("__ROUTE__", json.dumps(collect_route(conn), ensure_ascii=False))
            .replace("__ITEMS__", json.dumps(collect_items(conn), ensure_ascii=False))
            .replace("__TIMETABLE__", json.dumps(collect_timetable(conn),
                                                 ensure_ascii=False,
                                                 separators=(",", ":")))
            .replace("__STATIONS__", json.dumps(PLACE_STATION, ensure_ascii=False))
            .replace("__TIPS__", json.dumps(collect_tips(conn), ensure_ascii=False))
            .replace("__LABELS__", json.dumps(STATUS_LABEL, ensure_ascii=False))
            .replace("__TOTAL__", str(len(places)))
            .replace("__API_KEY__", get_google_maps_key())
            .replace("__GENERATED__", html.escape(generated)))
    if not fragment:
        return page
    head = page[page.index("<title>"):page.index("</head>")]
    body = page[page.index("<body>") + len("<body>"):page.index("</body>")]
    return head + body
