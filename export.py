"""DB 읽기 전용 출력 어댑터.

쓰기는 todoist_task_id 하나뿐이다 — 이걸 안 쓰면 재푸시가 태스크를 중복 생성한다.
그 외 어떤 컬럼에도 UPDATE/INSERT/DELETE 하지 않는다.
"""
import json
import sqlite3
import sys
import urllib.request

import trip

TODOIST_URL = "https://api.todoist.com/rest/v2/tasks"
TIMEOUT_SEC = 10


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
    return tasks


def _real_post(token, project_id, task):
    body = {"content": task["content"], "project_id": project_id,
            "labels": task["labels"]}
    req = urllib.request.Request(
        TODOIST_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def push_todoist(conn, token, project_id, dry_run=True, post=None):
    """멱등: todoist_task_id 가 있는 행은 건너뛴다."""
    post = post or _real_post
    tasks = build_todoist_tasks(conn)
    total = conn.execute(
        "SELECT (SELECT COUNT(*) FROM packing) + (SELECT COUNT(*) FROM itinerary)"
    ).fetchone()[0]
    if dry_run:
        for t in tasks:
            print(f"  [dry-run] {t['content']}  @{','.join(t['labels'])}")
        return {"would_create": len(tasks), "skipped": total - len(tasks)}
    created = 0
    for t in tasks:
        resp = post(token, project_id, t)
        # t['table'] 은 이 파일 안에서 리터럴로만 만들어진다. 외부 입력이 닿지 않는다.
        conn.execute(f"UPDATE {t['table']} SET todoist_task_id = ? WHERE id = ?",
                     (str(resp["id"]), t["row_id"]))
        conn.commit()
        created += 1
    return {"created": created, "skipped": total - created}


def main(argv=None):
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(prog="export", description="여행 DB 출력 어댑터")
    ap.add_argument("--db", default=trip.DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("maps-links", help="내 지도에 저장할 링크 목록")
    p_td = sub.add_parser("todoist", help="준비물·일정 체크리스트 푸시")
    p_td.add_argument("--dry-run", action="store_true", default=False)
    args = ap.parse_args(argv)
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

    env = trip.load_env()
    token, project = env.get("TODOIST_TOKEN"), env.get("TODOIST_PROJECT_ID")
    if not args.dry_run and not (token and project):
        print("ERROR E6: TODOIST_TOKEN / TODOIST_PROJECT_ID 가 .env 에 없습니다.",
              file=sys.stderr)
        return 1
    r = push_todoist(conn, token, project, dry_run=args.dry_run)
    print(f"OK {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
