"""GTFS-JP 에서 일정에 쓰는 지하철 구간만 뽑아 timetable 에 넣는다.

왜 전체를 안 넣나
  원본 stop_times.txt 는 2MB, 37,892행이다. 페이지에 통째로 실을 수 없다.
  일정이 실제로 지나는 구간만 남기면 수백 행으로 줄어든다.

실시간이 아니다
  GTFS-RT(열차위치·지연) 는 후쿠오카 노선에 공개된 게 없다. 조사 결과
  ODPT 가 실시간을 주는 건 JR동일본뿐이고, JR규슈·니시테츠·후쿠오카시
  지하철은 정적 시각표만 있다. 그래서 이건 '조회'이지 '알림'이 아니다.

출처
  https://github.com/kuwayamamasayuki/GTFS-FukuokaCitySubway (도구는 MIT)
  원자료는 후쿠오카시 교통국 공개 시각표 Excel.
"""
import csv
import io
import json
import os
import sqlite3
import sys
import zipfile

import trip

GTFS_ZIP = os.path.join("data", "gtfs", "FukuokaCitySubway.zip")
GTFS_URL = ("https://raw.githubusercontent.com/kuwayamamasayuki/"
            "GTFS-FukuokaCitySubway/master/dist/FukuokaCitySubway.zip")

# GTFS service_id 접미사 -> 우리 enum
KIND = {"平日": "평일", "土曜": "토요", "休日": "휴일"}

# 일정이 지나는 역만. 이 밖은 넣지 않는다.
# stop_id 는 '11', '11_1' 처럼 승강장별로 갈라지므로 앞자리로 묶는다.
STATIONS = {
    "11": "하카타",          # 博多 (공항선) — 호텔·마잉구·한큐 기점
    "37": "하카타",          # 博多 (나나쿠마선)
    "8": "텐진",             # 天神 — 텐진 지하상가
    "35": "텐진미나미",       # 天神南 (나나쿠마선)
    "9": "나카스카와바타",     # 中洲川端 — 호빵맨 박물관·캐널시티
    "10": "기온",            # 祇園 — 캐널시티 도보권
    "13": "후쿠오카공항",     # 福岡空港 — 귀국일
}


def _rd(z, name):
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))


def _kind_of(service_id):
    """'空港箱崎_休日' -> '휴일'. 모르는 값이면 None 을 돌려 건너뛴다."""
    tail = service_id.rsplit("_", 1)[-1]
    return KIND.get(tail)


def extract(zip_path=GTFS_ZIP):
    """(legs, feed_version) 를 돌려준다. legs 는 DB 에 넣을 dict 리스트."""
    with zipfile.ZipFile(zip_path) as z:
        feed = _rd(z, "feed_info.txt")[0]
        trips = {t["trip_id"]: t for t in _rd(z, "trips.txt")}
        times = _rd(z, "stop_times.txt")

    # trip 별로 우리가 아는 역만 순서대로 모은다
    by_trip = {}
    for r in times:
        base = r["stop_id"].split("_")[0]
        name = STATIONS.get(base)
        if not name:
            continue
        by_trip.setdefault(r["trip_id"], []).append(
            (int(r["stop_sequence"]), name, r["departure_time"], r["arrival_time"]))

    legs = []
    for trip_id, stops in by_trip.items():
        t = trips.get(trip_id)
        if not t:
            continue
        kind = _kind_of(t["service_id"])
        if not kind:
            continue
        stops.sort()
        # 같은 열차 안에서 앞역 -> 뒷역 조합을 전부 만든다.
        # 환승 없이 한 번에 가는 구간만 나온다 — 그게 우리가 보여줄 것이다.
        for i in range(len(stops)):
            for j in range(i + 1, len(stops)):
                _, a, dep, _ = stops[i]
                _, b, _, arr = stops[j]
                if a == b:
                    continue
                legs.append({
                    "line": t.get("route_id", ""),
                    "from_stop": a, "to_stop": b, "service_kind": kind,
                    "dep_time": dep[:5], "arr_time": arr[:5],
                    "headsign": t.get("trip_headsign", ""),
                })
    return legs, feed


def load(conn, zip_path=GTFS_ZIP):
    """timetable 을 통째로 갈아끼운다. 시각표는 누적할 값이 아니다."""
    legs, feed = extract(zip_path)
    raw = json.dumps({
        "gtfs_url": GTFS_URL,
        "feed_version": feed.get("feed_version"),
        "feed_publisher": feed.get("feed_publisher_name"),
        "feed_start": feed.get("feed_start_date"),
        "feed_end": feed.get("feed_end_date"),
        "note": ("후쿠오카시 교통국 공개 시각표에서 생성된 GTFS-JP. 도구는 MIT. "
                 "정적 시각표이며 실시간 지연 정보가 아니다."),
        "stations": STATIONS,
    }, ensure_ascii=False, indent=2)

    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            "INSERT INTO source (kind, url, title, raw_text) VALUES (?,?,?,?)",
            ("web", GTFS_URL,
             f"후쿠오카 시영 지하철 시각표 GTFS-JP ({feed.get('feed_version')})", raw))
        sid = cur.lastrowid
        conn.execute("DELETE FROM timetable")
        conn.executemany(
            "INSERT INTO timetable (line, from_stop, to_stop, service_kind, "
            "dep_time, arr_time, headsign, source_id) VALUES (?,?,?,?,?,?,?,?)",
            [(l["line"], l["from_stop"], l["to_stop"], l["service_kind"],
              l["dep_time"], l["arr_time"], l["headsign"], sid) for l in legs])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"legs": len(legs), "source_id": sid,
            "feed_version": feed.get("feed_version")}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    db = argv[0] if argv else trip.DEFAULT_DB
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    conn = trip.connect(db)
    r = load(conn)
    print(f"OK 시각표 {r['legs']:,}건 (feed {r['feed_version']}, source={r['source_id']})")
    for row in conn.execute(
            "SELECT from_stop, to_stop, service_kind, count(*) FROM timetable "
            "GROUP BY 1,2,3 ORDER BY 1,2,3"):
        print(f"  {row[0]} -> {row[1]:8} {row[2]}  {row[3]:>4}편")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
