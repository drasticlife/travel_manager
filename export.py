"""DB 읽기 전용 출력 어댑터.

쓰기는 todoist_task_id 하나뿐이다 — 이걸 안 쓰면 재푸시가 태스크를 중복 생성한다.
그 외 어떤 컬럼에도 UPDATE/INSERT/DELETE 하지 않는다.
"""
import json
import sqlite3
import sys
import urllib.parse
import urllib.request

import trip

# REST v2 는 2026 초에 폐기되어 410 Gone 을 낸다. 통합 API v1 을 쓴다.
TODOIST_API = "https://api.todoist.com/api/v1"
TODOIST_URL = f"{TODOIST_API}/tasks"
TODOIST_PROJECTS_URL = f"{TODOIST_API}/projects"
TIMEOUT_SEC = 10


def unwrap(data):
    """v1 은 목록을 {results, next_cursor} 로 감싼다. v2 는 맨 배열이었다."""
    if isinstance(data, dict) and "results" in data:
        return data["results"] or []
    return data or []


def get_all(url, token, get=None):
    """목록을 next_cursor 끝까지 따라간다.

    v1 은 한 페이지 기본 50건에서 자른다. 이걸 안 따라가면 중복 검사가 앞의
    50건만 보고, 공유 프로젝트에 이미 있는 태스크를 또 만든다. 실제로 밟았다 —
    프로젝트에 115건이 있는데 50건만 읽혔다.
    """
    get = get or _real_get
    out, cursor = [], None
    while True:
        sep = "&" if "?" in url else "?"
        page = get(f"{url}{sep}limit=200" +
                   (f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""), token)
        out += unwrap(page)
        cursor = page.get("next_cursor") if isinstance(page, dict) else None
        if not cursor:
            return out


def maps_links(conn):
    """내 지도에 아직 저장 안 한 장소만. 확인이 급한 것부터."""
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT id, name, name_verified, verify_status, maps_url, note "
        "FROM place WHERE saved_to_mymaps = 0 "
        "ORDER BY CASE verify_status WHEN 'ambiguous' THEN 0 WHEN 'not_found' "
        "THEN 1 WHEN 'pending' THEN 2 ELSE 3 END, name").fetchall()


def build_todoist_tasks(conn):
    """아직 푸시 안 된 행만 태스크로 만든다."""
    conn.row_factory = sqlite3.Row
    tasks = []
    for r in conn.execute(
            "SELECT id, item, qty, owner FROM packing WHERE todoist_task_id IS NULL"):
        tasks.append({"table": "packing", "row_id": r["id"],
                      "content": f"{r['item']} x{r['qty']}", "labels": [r["owner"]]})
    for r in conn.execute(
            "SELECT i.id, i.day_no, i.slot, p.name AS place_name FROM itinerary i "
            "LEFT JOIN place p ON p.id = i.place_id WHERE i.todoist_task_id IS NULL"):
        label = r["place_name"] or "(장소 미정)"
        tasks.append({"table": "itinerary", "row_id": r["id"],
                      "content": f"{r['day_no']}일차 [{r['slot']}] {label}",
                      "labels": [f"{r['day_no']}일차"]})
    for r in conn.execute(
            "SELECT i.id, i.name, i.category, i.note, i.tag, "
            "(SELECT GROUP_CONCAT(x.name, ', ') FROM ("
            "   SELECT p.name FROM item_place ip "
            "   JOIN place p ON p.id = ip.place_id "
            "   WHERE ip.item_id = i.id ORDER BY p.name) x) AS places "
            "FROM item i WHERE i.todoist_task_id IS NULL"):
        # '@' 를 쓰면 Todoist 가 라벨 문법으로 파싱해 제목을 잘라먹는다.
        # 실제로 33건 중 29건이 '바오바오 백 @한큐 하카타' -> '바오바오 백 하카타'
        # 로 깨지고 '한큐' 라벨이 멋대로 생겼다. 구분자는 중점을 쓴다.
        where = f" · {r['places']}" if r["places"] else ""
        # note 에 층수·쿠폰·오픈런 같은 실전 정보가 들어 있다. 제목만 보내면
        # 폰에서 그걸 못 본다 — description 으로 함께 실어 보낸다.
        # 태그가 있으면 제목에 넣는다 — 폰에서 '아침밥' 만 모아 보려면 필요하다.
        tg = f"#{r['tag']} " if r["tag"] else ""
        tasks.append({"table": "item", "row_id": r["id"],
                      "content": f"[{r['category']}] {tg}{r['name']}{where}",
                      "labels": [r["category"]],
                      "description": r["note"] or ""})
    return tasks


def _real_post(token, project_id, task):
    body = {"content": task["content"], "project_id": project_id,
            "labels": task["labels"]}
    if task.get("description"):
        body["description"] = task["description"]
    req = urllib.request.Request(
        TODOIST_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _real_get(url, token):
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def todoist_projects(token, get=None):
    """프로젝트 목록 + ID.

    v1 의 project_id 는 `6hR986mmJqCrxHc4` 같은 문자열이고, 브라우저 URL
    (.../project/2026-6hR986mmJqCrxHc4)의 대시 뒤 부분과 같다.
    """
    return [{"id": str(p.get("id")), "name": p.get("name")}
            for p in get_all(TODOIST_PROJECTS_URL, token, get)]


def todoist_existing_contents(token, project_id, get=None):
    """프로젝트에 이미 있는 태스크 제목 집합.

    이 프로젝트는 아내와 공유 중이고 이미 수십 건이 들어 있다.
    같은 제목을 또 만들지 않기 위해 푸시 전에 대조한다.
    """
    url = f"{TODOIST_URL}?project_id={urllib.parse.quote(str(project_id))}"
    return {(t.get("content") or "").strip() for t in get_all(url, token, get)}


def push_todoist(conn, token, project_id, dry_run=True, post=None, existing=None):
    """멱등 2중: 로컬 todoist_task_id + 원격 제목 대조.

    로컬 DB 만 보면 다른 기기에서 이미 만든 것, 아내가 손으로 적은 것을 또 만든다.
    """
    post = post or _real_post
    tasks = build_todoist_tasks(conn)
    total = conn.execute(
        "SELECT (SELECT COUNT(*) FROM packing) + (SELECT COUNT(*) FROM itinerary)"
        " + (SELECT COUNT(*) FROM item)"
    ).fetchone()[0]

    # 여기서 네트워크를 타지 않는다. 원격 제목은 호출자가 넘긴다(main 이 조회).
    existing = existing or set()

    fresh = [t for t in tasks if t["content"].strip() not in existing]
    dupes = [t for t in tasks if t["content"].strip() in existing]

    if dry_run:
        for t in fresh:
            print(f"  [dry-run] + {t['content']}  @{','.join(t['labels'])}")
        for t in dupes:
            print(f"  [dry-run] - {t['content']}  (원격에 이미 있음)")
        return {"would_create": len(fresh), "already_remote": len(dupes),
                "skipped": total - len(tasks)}

    created = 0
    for t in fresh:
        resp = post(token, project_id, t)
        # t['table'] 은 이 파일 안에서 리터럴로만 만들어진다. 외부 입력이 닿지 않는다.
        conn.execute(f"UPDATE {t['table']} SET todoist_task_id = ? WHERE id = ?",
                     (str(resp["id"]), t["row_id"]))
        conn.commit()
        created += 1
    return {"created": created, "already_remote": len(dupes),
            "skipped": total - len(tasks)}


def main(argv=None):
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(prog="export", description="여행 DB 출력 어댑터")
    ap.add_argument("--db", default=trip.DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("maps-links", help="내 지도에 저장할 링크 목록")
    p_page = sub.add_parser("maps-page", help="여행 가이드 HTML 한 장 생성")
    p_page.add_argument("--out", default="maps.html")
    # Artifact 는 <html>/<head>/<body> 를 자기가 씌운다. 껍데기 없는 조각을 낸다.
    p_page.add_argument("--fragment", action="store_true", default=False,
                        help="Artifact 게시용 조각(<title>+<style>+본문)만 출력")
    sub.add_parser("todoist-projects", help="프로젝트 목록 + 숫자 ID 조회")
    p_td = sub.add_parser(
        "todoist", help="준비물·일정 체크리스트 푸시 (기본 미리보기)")
    # 공유 프로젝트라 기본을 미리보기로 둔다. 실제 쓰기는 명시적으로 요구한다.
    p_td.add_argument("--push", action="store_true", default=False,
                      help="실제로 푸시한다. 없으면 미리보기만.")
    args = ap.parse_args(argv)

    if args.cmd == "todoist-projects":
        token = trip.load_env().get("TODOIST_TOKEN")
        if not token:
            print("ERROR E6: TODOIST_TOKEN 이 .env 에 없습니다. "
                  "Todoist 설정 > 연동 > 개발자에서 API 토큰을 복사하세요.",
                  file=sys.stderr)
            return 1
        for p in todoist_projects(token):
            print(f"  {p['id']:<24} {p['name']}")
        print("\n위 ID 를 .env 의 TODOIST_PROJECT_ID 에 넣으세요.")
        return 0

    conn = trip.connect(args.db)

    if args.cmd == "maps-links":
        for r in maps_links(conn):
            verified = r["name_verified"] or ""
            mark = "[확인] " if r["verify_status"] != "matched" else "       "
            print(f"{mark}[{r['id']:>3}] {r['verify_status']:<10} {r['name']}")
            if verified and verified != r["name"]:
                print(f"        구글 표기: {verified}")
            print(f"        {r['maps_url'] or '(링크 없음 — verify 필요)'}")
        return 0

    if args.cmd == "maps-page":
        import datetime
        import maps_page
        page = maps_page.build_page(
            conn, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            fragment=args.fragment)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(page)
        print(f"OK {args.out} ({len(page):,} bytes) — 브라우저로 열어라")
        return 0

    env = trip.load_env()
    token, project = env.get("TODOIST_TOKEN"), env.get("TODOIST_PROJECT_ID")
    if not (token and project):
        print("ERROR E6: TODOIST_TOKEN / TODOIST_PROJECT_ID 가 .env 에 없습니다. "
              "`export.py todoist-projects` 로 ID 를 확인하세요.", file=sys.stderr)
        return 1

    # 미리보기에서도 원격 제목을 읽어와야 중복 예상을 정확히 보여줄 수 있다.
    try:
        existing = todoist_existing_contents(token, project)
    except Exception as e:
        print(f"ERROR E10: Todoist 조회 실패 — {e}", file=sys.stderr)
        return 1

    r = push_todoist(conn, token, project, dry_run=not args.push,
                     existing=existing)
    print(f"OK {r}")
    if not args.push:
        print("\n미리보기입니다. 실제로 푸시하려면 --push 를 붙이세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
