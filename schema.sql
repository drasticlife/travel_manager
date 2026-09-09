-- travel manager 수집→DB 코어 스키마
-- 스펙: docs/superpowers/specs/2026-09-06-travel-manager-design.md §2
-- enum 은 CHECK 제약으로 DB 가 강제한다. LLM 이 카테고리를 지어내면 INSERT 가 거부된다.

CREATE TABLE IF NOT EXISTS source (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('youtube','web','text','chat','takeout')),
  url         TEXT,
  title       TEXT,
  raw_text    TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS place (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  name_verified   TEXT,
  category        TEXT NOT NULL CHECK (category IN
                    ('맛집','쇼핑','관광','숙소','이동','기타')),
  address         TEXT,
  lat             REAL,
  lng             REAL,
  place_id        TEXT UNIQUE,
  maps_url        TEXT,
  verify_status   TEXT NOT NULL DEFAULT 'pending'
                    CHECK (verify_status IN ('pending','matched','ambiguous','not_found')),
  verify_method   TEXT CHECK (verify_method IN ('claude_search','places_api','manual')),
  -- 주소 근거 URL(줄바꿈 구분). 환각 여부를 사후 추적하는 유일한 수단이다.
  evidence_urls   TEXT,
  saved_to_mymaps INTEGER NOT NULL DEFAULT 0 CHECK (saved_to_mymaps IN (0,1)),
  note            TEXT,
  source_id       INTEGER REFERENCES source(id),
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_place_verify   ON place(verify_status);
CREATE INDEX IF NOT EXISTS idx_place_category ON place(category);

CREATE TABLE IF NOT EXISTS itinerary (
  id              INTEGER PRIMARY KEY,
  day_no          INTEGER NOT NULL,
  date            TEXT,
  slot            TEXT NOT NULL CHECK (slot IN ('오전','점심','오후','저녁','밤')),
  seq             INTEGER NOT NULL DEFAULT 0,
  place_id        INTEGER REFERENCES place(id),
  memo            TEXT,
  todoist_task_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_itin_day ON itinerary(day_no, slot, seq);

CREATE TABLE IF NOT EXISTS packing (
  id              INTEGER PRIMARY KEY,
  item            TEXT NOT NULL,
  category        TEXT NOT NULL DEFAULT '기타' CHECK (category IN
                    ('의류','전자','서류','약','세면','기타')),
  qty             INTEGER NOT NULL DEFAULT 1,
  owner           TEXT NOT NULL DEFAULT '공용' CHECK (owner IN ('나','아내','공용')),
  packed          INTEGER NOT NULL DEFAULT 0 CHECK (packed IN (0,1)),
  todoist_task_id TEXT
);

-- 살거/먹을거/놀거. 장소와는 item_place 로 N:M 으로 붙는다.
CREATE TABLE IF NOT EXISTS item (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  category        TEXT NOT NULL CHECK (category IN ('살거','먹을거','놀거')),
  note            TEXT,
  done            INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0,1)),
  source_id       INTEGER REFERENCES source(id),
  todoist_task_id TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- '명란' 은 야마야에서도 로피아에서도 산다. 그래서 N:M 이다.
CREATE TABLE IF NOT EXISTS item_place (
  item_id   INTEGER NOT NULL REFERENCES item(id),
  place_id  INTEGER NOT NULL REFERENCES place(id),
  PRIMARY KEY (item_id, place_id)
);

-- 참고사항. 날씨·공휴일은 장소가 아니라 날짜에 붙으므로 place.note 로는 못 담는다.
CREATE TABLE IF NOT EXISTS tip (
  id            INTEGER PRIMARY KEY,
  scope         TEXT NOT NULL CHECK (scope IN ('trip','day','place')),
  day_no        INTEGER,
  place_id      INTEGER REFERENCES place(id),
  category      TEXT NOT NULL CHECK (category IN
                  ('날씨','공휴일','아기','유모차','요금','식사','혼잡','우천','의료','기타')),
  text          TEXT NOT NULL,
  -- 근거 URL(줄바꿈 구분). NOT NULL 은 빈 문자열을 막지 못하므로
  -- validate_payload 가 공백뿐인 값도 E2 로 거부한다.
  evidence_urls TEXT NOT NULL,
  source_id     INTEGER REFERENCES source(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_item_category ON item(category);
CREATE INDEX IF NOT EXISTS idx_tip_scope     ON tip(scope, day_no);
