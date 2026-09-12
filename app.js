const { PLACES, DAYS, ROUTE, ITEMS, TIMETABLE, STATIONS, TIPS, LABELS } = window.APP_DATA;

// Animation Toggle
let reduceMotion = false;
function toggleAnimation() {
    reduceMotion = !reduceMotion;
    document.body.classList.toggle('reduce-motion', reduceMotion);
}

// Theme Toggle
function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    let newTheme;
    if (currentTheme === 'dark') {
        newTheme = 'light';
    } else if (currentTheme === 'light') {
        newTheme = 'dark';
    } else {
        newTheme = systemPrefersDark ? 'light' : 'dark';
    }
    
    html.setAttribute('data-theme', newTheme);
    try {
        localStorage.setItem('theme', newTheme);
    } catch(e) {}
}

try {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
    }
} catch(e) {}
const LABEL = LABELS;



const PLACE_STATION = STATIONS;
/* 여행 4일의 다이어. 9/21~23 은 공휴일이라 평일 다이어가 꺼지고 휴일 다이어가
   돌아간다 — GTFS calendar_dates 예외에 그렇게 들어 있다. */
const TRIP_KIND = {"2026-09-21":"휴일","2026-09-22":"휴일",
                   "2026-09-23":"휴일","2026-09-24":"평일"};

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
const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); }
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
    let parts = txt.split(/은\s+/);
    if (parts.length > 1) {
      desc = parts[1].split(".")[0].trim();
    }
    return `${emoji} ${desc}`;
  }
  if (cat === "공휴일") {
    let name = "공휴일";
    let parts = txt.split(/은\s+/);
    if (parts.length > 1) {
      let m = parts[1].match(/\(([^)]+)\)/);
      if (m) name = m[1];
      else name = parts[1].split(/[.,\s]/)[0];
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

/* ---------- 장소 목록 & 아이템 카테고리 태그 헬퍼 ---------- */
const FOOD_TAG_ICONS = {
  "라멘·츠케멘": "🍜",
  "우동": "🥢",
  "튀김·텐동": "🍤",
  "스시·해산물": "🍣",
  "모츠나베": "🍲",
  "장어덮밥": "🍱",
  "야키니쿠·스키야키": "🥩",
  "일본가정식": "🍚",
  "교자·만두": "🥟",
  "베이커리·빵": "🥖",
  "카페·커피": "☕",
  "디저트·간식": "🍰",
  "아침밥": "🍳",
  "함바그·스테이크": "🥩",
  "위스키": "🥃",
  "특산물/식품": "🛍️",
  "패션/잡화": "👜",
  "기념품/과자": "🎁",
  "아기용품": "🧸",
  "자연/동물": "🐬",
  "키즈/테마파크": "🎡",
  "구경/전시": "🤖",
};

/* ---------- 장소 목록 ---------- */
const TABS = [["all", "전체"], ["planned", "일정에 있는 곳"], ["쇼핑", "쇼핑"],
              ["맛집", "맛집"], ["관광", "관광"], ["unsaved", "아직 저장 안 함"],
              ["ambiguous", "확인 필요"]];
let placeSubFilter = "all";

function matches(p) {
  if (filter === "all") return true;
  if (filter === "planned") return p.days.length > 0;
  if (filter === "unsaved") return !p.saved_to_mymaps && !checked.has(p.id);
  if (filter === "ambiguous") return p.verify_status !== "matched";
  return p.category === filter;
}

function renderPlaceSubtabs(places) {
  const subtabsEl = document.getElementById("place-subtabs");
  if (!subtabsEl) return;
  
  if (filter !== "맛집") {
    subtabsEl.style.display = "none";
    return;
  }
  
  const tagsWithCount = {};
  places.forEach(p => {
    if (p.tag) {
      tagsWithCount[p.tag] = (tagsWithCount[p.tag] || 0) + 1;
    }
  });
  
  const tags = Object.keys(tagsWithCount);
  if (!tags.length) {
    subtabsEl.style.display = "none";
    return;
  }
  
  subtabsEl.style.display = "flex";
  let html = `<button class="sub-chip${placeSubFilter === 'all' ? ' on' : ''}" data-sub="all">전체 (${places.length})</button>`;
  
  const sortedTags = Object.entries(tagsWithCount).sort((a, b) => b[1] - a[1]);
  html += sortedTags.map(([tag, count]) => {
    const icon = FOOD_TAG_ICONS[tag] || "🏷️";
    return `<button class="sub-chip${placeSubFilter === tag ? ' on' : ''}" data-sub="${esc(tag)}">${icon} ${esc(tag)} (${count})</button>`;
  }).join("");
  
  subtabsEl.innerHTML = html;
}

function renderPlaceTile(p) {
  const on = p.saved_to_mymaps || checked.has(p.id);
  const icon = (p.tag && FOOD_TAG_ICONS[p.tag]) || p.icon;
  const tagBadge = p.tag ? `<span class="tg">${esc(p.tag)}</span>` : "";
  const daysText = p.days.length ? " · " + p.days.map(d => d.day_no + "일차").join(",") : "";
  
  return `<button class="tile${on ? " done" : ""}" data-place="${p.id}">
    <span class="e">${icon}</span>
    <span style="display:flex; flex-direction:column; align-items:flex-start; width:100%; min-width:0;">
      <b>${tagBadge}${esc(p.name)}</b>
      <small>${esc(p.category)}${daysText}</small>
      ${p.note ? `<div class="item-note">${esc(p.note.length > 70 ? p.note.slice(0, 70) + '…' : p.note)}</div>` : ""}
    </span>
    <span class="dot d-${p.verify_status}"
      title="${esc(LABEL[p.verify_status] || "")}"></span></button>`;
}

function renderGrid() {
  const basePlaces = PLACES.filter(matches);
  renderPlaceSubtabs(basePlaces);
  
  const shown = basePlaces.filter(
    p => placeSubFilter === "all" || p.tag === placeSubFilter);
  
  const container = document.getElementById("grid");
  if (!shown.length) {
    container.innerHTML = "<p>해당하는 장소가 없습니다.</p>";
    return;
  }
  
  if (filter === "맛집" && placeSubFilter === "all") {
    const groups = {};
    shown.forEach(p => {
      const t = p.tag || "기타 맛집";
      if (!groups[t]) groups[t] = [];
      groups[t].push(p);
    });
    
    container.innerHTML = Object.entries(groups).map(([tag, list]) => {
      const icon = FOOD_TAG_ICONS[tag] || "🍜";
      return `<div class="category-group">
        <div class="group-header">
          <span class="group-icon">${icon}</span>
          <span class="group-name">${esc(tag)}</span>
          <span class="group-badge">${list.length}</span>
        </div>
        <div class="group-grid">
          ${list.map(renderPlaceTile).join("")}
        </div>
      </div>`;
    }).join("");
  } else {
    container.innerHTML = shown.map(renderPlaceTile).join("");
  }
}

/* ---------- 아이템 ---------- */
const ITEM_TABS = ["전체", "살거", "먹을거", "놀거"];
let itemFilter = "전체";
let itemSubFilter = "all";

function renderItemSubtabs(items) {
  const subtabsEl = document.getElementById("item-subtabs");
  if (!subtabsEl) return;
  
  const tagsWithCount = {};
  items.forEach(i => {
    if (i.tag) {
      tagsWithCount[i.tag] = (tagsWithCount[i.tag] || 0) + 1;
    }
  });
  
  const tags = Object.keys(tagsWithCount);
  if (!tags.length) {
    subtabsEl.style.display = "none";
    return;
  }
  
  subtabsEl.style.display = "flex";
  let html = `<button class="sub-chip${itemSubFilter === 'all' ? ' on' : ''}" data-sub="all">전체 (${items.length})</button>`;
  
  const sortedTags = Object.entries(tagsWithCount).sort((a, b) => b[1] - a[1]);
  html += sortedTags.map(([tag, count]) => {
    const icon = FOOD_TAG_ICONS[tag] || "🏷️";
    return `<button class="sub-chip${itemSubFilter === tag ? ' on' : ''}" data-sub="${esc(tag)}">${icon} ${esc(tag)} (${count})</button>`;
  }).join("");
  
  subtabsEl.innerHTML = html;
}

function renderItemTile(i) {
  let placeHtml = "";
  if (i.places) {
    const names = i.places.split(", ");
    placeHtml = names.map(name => {
      const p = PLACES.find(x => x.name === name);
      if (p) return `<button class="item-place-link" onclick="openPlace(${p.id}); return false;">📍 ${esc(name)}</button>`;
      return `<small style="margin-right:8px; color:var(--muted);">${esc(name)}</small>`;
    }).join("");
    placeHtml = `<div class="item-actions">${placeHtml}</div>`;
  }
  
  const icon = (i.tag && FOOD_TAG_ICONS[i.tag]) 
    || (i.category === "살거" ? "🛍️" : i.category === "먹을거" ? "🍜" : "🎡");

  return `<div class="tile${i.done ? " done" : ""}">
    <span class="e">${icon}</span>
    <span style="display:flex; flex-direction:column; align-items:flex-start; width:100%;">
      <b>${i.tag ? `<span class="tg">${esc(i.tag)}</span>` : ""}${esc(i.name)}</b>
      ${placeHtml}
      ${i.note ? `<div class="item-note">${esc(i.note)}</div>` : ""}
    </span></div>`;
}

function renderItems() {
  const baseItems = ITEMS.filter(
    i => itemFilter === "전체" || i.category === itemFilter);
  
  renderItemSubtabs(baseItems);
  
  const shown = baseItems.filter(
    i => itemSubFilter === "all" || i.tag === itemSubFilter);
  
  const container = document.getElementById("itemgrid");
  if (!shown.length) {
    container.innerHTML = "<p>해당 카테고리에 등록된 항목이 없습니다.</p>";
    return;
  }
  
  if (itemFilter === "먹을거" && itemSubFilter === "all") {
    const groups = {};
    shown.forEach(i => {
      const t = i.tag || "기타 먹을거리";
      if (!groups[t]) groups[t] = [];
      groups[t].push(i);
    });
    
    container.innerHTML = Object.entries(groups).map(([tag, list]) => {
      const icon = FOOD_TAG_ICONS[tag] || "🍽️";
      return `<div class="category-group">
        <div class="group-header">
          <span class="group-icon">${icon}</span>
          <span class="group-name">${esc(tag)}</span>
          <span class="group-badge">${list.length}</span>
        </div>
        <div class="group-grid">
          ${list.map(renderItemTile).join("")}
        </div>
      </div>`;
    }).join("");
  } else {
    container.innerHTML = shown.map(renderItemTile).join("");
  }
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
  itemSubFilter = "all";
  renderItems();
});

const itemSubtabsEl = document.getElementById("item-subtabs");
if (itemSubtabsEl) {
  itemSubtabsEl.addEventListener("click", e => {
    const b = e.target.closest(".sub-chip");
    if (!b) return;
    document.querySelectorAll("#item-subtabs .sub-chip").forEach(x => x.classList.remove("on"));
    b.classList.add("on");
    itemSubFilter = b.dataset.sub;
    renderItems();
  });
}

const placeSubtabsEl = document.getElementById("place-subtabs");
if (placeSubtabsEl) {
  placeSubtabsEl.addEventListener("click", e => {
    const b = e.target.closest(".sub-chip");
    if (!b) return;
    document.querySelectorAll("#place-subtabs .sub-chip").forEach(x => x.classList.remove("on"));
    b.classList.add("on");
    placeSubFilter = b.dataset.sub;
    renderGrid();
  });
}

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
    const catText = esc(p.category) + (p.tag ? ` · <span style="color:var(--v-ink); font-weight:700;">${esc(p.tag)}</span>` : "");
    rows.push(["카테고리", catText]);
    if (p.name_verified && p.name_verified !== p.name)
      rows.push(["구글 표기", esc(p.name_verified)]);
    rows.push(["주소", p.address ? esc(p.address)
      : '<span style="color:#9b9096">주소 미확보 — 링크에서 확인</span>']);
    if (ev) rows.push(["근거", ev]);
    if (!itin && p.days.length)
      rows.push(["일정", p.days.map(d => `${d.day_no}일차 ${esc(d.slot)}`).join(", ")]);
  }

  const reviewBoxHtml = (p && p.note) ? `
    <div class="review-box">
      <div class="review-header">💡 현지 가이드 리뷰 및 특징</div>
      <div class="review-content">${esc(p.note)}</div>
    </div>` : "";

  document.getElementById("popbody").innerHTML = `
    <div class="top">
      <div class="e">${(p && p.icon) || (itin && itin.icon) || "📍"}</div>
      <div>
        <h4>${esc(p ? p.name : itin.title)}</h4>
        <div class="badges">
          ${p ? `<span class="badge">#${p.id}</span>
                 ${p.tag ? `<span class="badge" style="background:var(--pink-soft); color:var(--pink); font-weight:700;">🏷️ ${esc(p.tag)}</span>` : ""}
                 <span class="badge">${esc(LABEL[p.verify_status] || p.verify_status)}</span>`
              : '<span class="badge">장소 미지정</span>'}
        </div>
      </div>
    </div>
    <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    ${reviewBoxHtml}
    ${nextTrains(p ? p.name : (itin ? itin.title : ""),
                 itin ? itin.date : null, itin ? itin.plan_time : null)}
    <div class="acts">
      ${p && p.maps_url
        ? `<a class="btn go" href="${esc(p.maps_url)}" target="_blank"
             rel="noopener">📍 구글 지도 열기</a>`
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

/* ---------- 전체 검색 ---------- */
/* 데이터는 이미 페이지에 다 실려 있다. 인덱스는 그걸 평탄하게 편 것뿐이라
   추가 전송이 없고 오프라인에서도 돈다. */
function searchIndex() {
  const idx = [];
  for (const p of PLACES) {
    idx.push({
      kind: p.category || "장소", title: p.name,
      body: [p.name_verified, p.address, p.note, (p.evidence || []).join(" ")]
        .filter(Boolean).join(" · "),
      open: () => openPlace(p.id, null),
    });
  }
  for (const d of DAYS) {
    for (const it of d.items) {
      idx.push({
        kind: `${d.day_no}일차 ${it.slot}`, title: it.title,
        body: [it.subtitle, it.hours === "–" ? "" : it.hours, it.memo]
          .filter(Boolean).join(" · "),
        open: () => openPlace(it.place_id, { ...it, day_no: d.day_no }),
      });
    }
  }
  for (const i of ITEMS) {
    idx.push({
      kind: i.category + (i.tag ? ` #${i.tag}` : ""), title: i.name,
      body: [i.places, i.note].filter(Boolean).join(" · "),
      open: null,
    });
  }
  for (const t of (typeof TIPS !== "undefined" ? TIPS : [])) {
    const where = t.day_no ? `${t.day_no}일차` : (t.place_name || "여행 전체");
    idx.push({
      kind: `팁 ${t.category}`, title: `${where} · ${t.category}`,
      body: [t.text, t.evidence_urls].filter(Boolean).join(" "),
      open: null,
    });
  }
  return idx;
}

let INDEX = null;

/* 검색어 앞뒤를 잘라 보여주고, 매칭 부분만 <mark> 로 감싼다.
   반드시 esc() 로 이스케이프한 뒤에 마크업을 넣는다 — 순서가 바뀌면 XSS 다. */
function snippet(text, q) {
  const t = String(text || "");
  const i = t.toLowerCase().indexOf(q);
  if (i < 0) return esc(t.slice(0, 90));
  const from = Math.max(0, i - 34);
  const cut = t.slice(from, i + q.length + 66);
  const rel = i - from;
  return (from > 0 ? "…" : "")
    + esc(cut.slice(0, rel))
    + "<mark>" + esc(cut.slice(rel, rel + q.length)) + "</mark>"
    + esc(cut.slice(rel + q.length))
    + (from + cut.length < t.length ? "…" : "");
}

function runSearch() {
  const raw = document.getElementById("q").value.trim();
  const box = document.getElementById("results");
  const cnt = document.getElementById("qcnt");
  if (!raw) {
    box.classList.remove("on");
    box.innerHTML = "";
    cnt.textContent = "";
    return;
  }
  if (!INDEX) INDEX = searchIndex();
  const q = raw.toLowerCase();
  const hits = INDEX.filter(
    r => (r.title + " " + r.body).toLowerCase().includes(q)).slice(0, 40);

  cnt.textContent = `${hits.length}건`;
  box.classList.add("on");
  if (!hits.length) {
    box.innerHTML = `<div class="nohit">'${esc(raw)}' 에 맞는 게 없다.
      장소·일정·살거·먹을거·놀거·팁을 모두 뒤졌다.</div>`;
    return;
  }
  box.innerHTML = hits.map((r, n) => {
    const inTitle = r.title.toLowerCase().includes(q);
    return `<button class="hit${r.open ? " can" : ""}" data-n="${n}">
      <span class="top"><span class="kind">${esc(r.kind)}</span>
        <b>${inTitle ? snippet(r.title, q) : esc(r.title)}</b></span>
      ${r.body ? `<span class="snip">${snippet(r.body, q)}</span>` : ""}
    </button>`;
  }).join("");
  box._hits = hits;
}

document.getElementById("q").addEventListener("input", runSearch);
document.getElementById("q").addEventListener("keydown", e => {
  if (e.key === "Escape") { e.target.value = ""; runSearch(); }
});
document.getElementById("qclear").addEventListener("click", () => {
  const q = document.getElementById("q");
  q.value = ""; runSearch(); q.focus();
});
document.getElementById("results").addEventListener("click", e => {
  const b = e.target.closest(".hit");
  if (!b) return;
  const hits = document.getElementById("results")._hits || [];
  const r = hits[Number(b.dataset.n)];
  if (r && r.open) r.open();
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
  placeSubFilter = "all";
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
  const markers = [];
  pts.forEach(p => {
    const pos = {lat: p.lat, lng: p.lng};
    bounds.extend(pos);
    const marker = new google.maps.Marker({
      position: pos,
      label: {
        text: String(p.seq_in_day),
        color: "white",
        fontWeight: "bold"
      },
      title: p.name
    });
    markers.push(marker);
  });
  
  if (typeof markerClusterer !== "undefined") {
    new markerClusterer.MarkerClusterer({ map, markers });
  } else {
    markers.forEach(m => m.setMap(map));
  }
  
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
if (document.getElementById("total-places")) {
  document.getElementById("total-places").textContent = window.APP_DATA?.TOTAL || PLACES.length;
}
