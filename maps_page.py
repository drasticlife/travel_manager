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
import re
import sqlite3

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
                "title": title, "subtitle": subtitle, "hours": hours or "–",
                "star": any(w in hours for w in STAR_WORDS),
                "memo": r["memo"] or "",
                "icon": icon_for(r["place_name"] or title, r["place_category"]),
                **parse_move(move),
            })
        days.append({"day_no": day_no, "items": items, **meta})
    return days


TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>후쿠오카 3박 4일 · 하카타역 거점 여행 가이드</title>
<style>
:root{
  --bg:#f7f3fd; --card:#ffffff; --ink:#4a4550; --muted:#9b9096;
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
a{color:var(--v-ink)}

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

/* ---- 장소 목록 ---- */
h3.sec{margin:32px 0 3px;font-size:19px;font-weight:800;color:var(--v-ink)}
.sec-sub{margin:0 0 11px;color:var(--muted);font-size:12.5px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:11px}
.chip{border:1px solid var(--line);background:var(--card);border-radius:999px;
  padding:5px 13px;font-size:12.5px;cursor:pointer;font-family:inherit;
  color:var(--ink)}
.chip.on{background:var(--v-ink);color:#fff;border-color:var(--v-ink)}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(224px,1fr));gap:9px}
.tile{display:flex;gap:9px;align-items:center;background:var(--card);
  border:1px solid var(--line);border-radius:14px;padding:9px;cursor:pointer;
  text-align:left;font-family:inherit;font-size:13.5px;color:var(--ink);width:100%}
.tile:hover{box-shadow:0 5px 14px rgba(123,94,167,.16)}
.tile .e{font-size:22px;flex:none}
.tile b{display:block;font-weight:700;line-height:1.3}
.tile small{color:var(--muted)}
.tile.done{background:var(--v-soft)}
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
@media(prefers-reduced-motion:reduce){.petal{animation:none}}

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

<div id="days"></div>

<h3 class="sec">장소 목록</h3>
<p class="sec-sub">그림을 누르면 주소·근거·지도 링크가 팝업으로 열린다.
  내 지도에 저장한 것은 팝업에서 체크하면 아래 명령이 만들어진다.</p>
<div class="tabs" id="tabs"></div>
<div id="grid"></div>

<footer>생성 __GENERATED__ · 장소 __TOTAL__건 · 이 페이지는 DB 에 아무것도 쓰지 않는다</footer>
</div>

<dialog id="pop"><div class="pop" id="popbody"></div></dialog>

<div class="bar">
  <b id="picked">0건</b>
  <code id="cmd">체크한 장소가 없다</code>
  <button class="btn" id="copy">명령 복사</button>
</div>

<script>
const PLACES = __PLACES__;
const DAYS = __DAYS__;
const LABEL = __LABELS__;
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
  <section class="day ${d.tone === "y" ? "y" : ""}">
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
  return `<div class="chain">` + steps.map((s, i) => `
    ${i ? '<span class="arrow">→</span>' : ""}
    <div class="step"><span class="e">${s.icon}</span>
      <b>${esc(s.name)}</b>
      ${s.detail ? `<span>${esc(s.detail)}</span>` : ""}</div>`).join("") + `</div>`;
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
  const picBtn = e.target.closest(".pic");
  if (picBtn) {
    const iid = Number(picBtn.dataset.itin);
    for (const d of DAYS) {
      const it = d.items.find(x => x.id === iid);
      if (it) return openPlace(it.place_id, { ...it, day_no: d.day_no });
    }
    return;
  }
  const tile = e.target.closest(".tile");
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

renderDays();
renderGrid();
renderCmd();
</script>
</body>
</html>
"""


def build_page(conn, generated="", fragment=False):
    """fragment=True 면 <title>+<style>+본문만 준다.

    Artifact 는 <!doctype>/<html>/<head>/<body> 껍데기를 자기가 씌운다.
    같은 껍데기를 또 주면 중첩 문서가 된다.
    """
    places = collect(conn)
    page = (TEMPLATE
            .replace("__PLACES__", json.dumps(places, ensure_ascii=False))
            .replace("__DAYS__", json.dumps(collect_days(conn), ensure_ascii=False))
            .replace("__LABELS__", json.dumps(STATUS_LABEL, ensure_ascii=False))
            .replace("__TOTAL__", str(len(places)))
            .replace("__GENERATED__", html.escape(generated)))
    if not fragment:
        return page
    head = page[page.index("<title>"):page.index("</head>")]
    body = page[page.index("<body>") + len("<body>"):page.index("</body>")]
    return head + body
