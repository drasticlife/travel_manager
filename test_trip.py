"""travel manager 전체 테스트. 프레임워크 없음. 실행: python test_trip.py"""
import sqlite3
import trip


# ---------- Task 1: 스키마 ----------

def test_schema_creates_four_tables():
    conn = trip.connect(":memory:")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"source", "place", "itinerary", "packing"}, names


def test_category_check_constraint():
    conn = trip.connect(":memory:")
    try:
        conn.execute("INSERT INTO place (name, category) VALUES ('x', '밥집')")
        assert False, "DB가 잘못된 category를 받아들였다"
    except sqlite3.IntegrityError:
        pass


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as e:
                fails += 1
                print(f"  FAIL {name}: {e}")
    print(f"\n{'FAILED' if fails else 'OK'} — {fails} failure(s)")
    raise SystemExit(1 if fails else 0)
