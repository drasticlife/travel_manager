# CLAUDE.md — travel manager

여행 자료를 검증된 SQLite DB로 쌓는 CLI. 안티패턴 중심 가드레일.

## 절대 규칙

1. **LLM은 추출·분류만 한다.** 좌표·`place_id`·주소는 Places API만 채운다.
   추측한 좌표를 넣으면 동선 최적화가 통째로 망가진다. `trip.py`가 거부한다.
2. **원문을 요약해서 저장하지 않는다.** `source.raw_text`는 자막/본문 전문이다.
   추출이 틀렸을 때 재처리할 유일한 근거다.
3. **`verify`는 과금 단계다.** 자동 실행 금지. 사용자가 결정한다.
4. **외부 패키지를 추가하지 않는다.** `youtube-transcript-api` 하나뿐이고
   나머지는 전부 stdlib다. `requests`·ORM·pydantic·pytest 금지.
5. **`git add .` 금지.** 자기가 고친 파일 경로만 명시해서 커밋한다.
6. **`.env`를 커밋하지 않는다.** `.gitignore`에 있다. `.env.example`만 커밋한다.

## 명령어

```bash
python test_trip.py                          # 테스트 (이게 전부)
python trip.py add                           # stdin JSON 저장
python trip.py import-takeout <csv>          # Takeout CSV 임포트
python trip.py verify --limit 50             # Places API 검증 (과금)
python trip.py list --status ambiguous       # 조회
python trip.py plan --day 3
python trip.py mark-saved 12 15              # 내 지도 저장 완료 표시
python export.py maps-links                  # 확인할 링크 목록
python export.py todoist --dry-run           # 푸시 미리보기
```

## 구조

| 파일 | 책임 |
| --- | --- |
| `schema.sql` | DDL. enum은 CHECK 제약으로 DB가 강제한다 |
| `trip.py` | 검증 + DB 쓰기 + 조회 CLI |
| `youtube.py` | 자막 3단 폴백 (출처: `C:\GIT\Moons_Company\agents\scrap_agent.py`) |
| `places.py` | Places API 조회 + 이름 대조 |
| `export.py` | 읽기 전용 출력. `todoist_task_id` 외 쓰기 금지 |
| `.claude/commands/trip.md` | LLM 추출 계약 |

## 함정 (실제로 밟은 것)

- **Windows stdin이 cp949다.** 파이프로 들어온 UTF-8 한국어가 깨진다
  (`맛집` → `留쏆쭛`). `main()`의 `sys.stdin.reconfigure(encoding="utf-8")`를
  지우지 마라. `io.StringIO` 테스트로는 재현되지 않는다 —
  `test_cli_stdin_accepts_utf8_korean`이 subprocess로 잡는다.
- **stdout도 cp949다.** `—`·`✓`·이모지를 출력하면 `UnicodeEncodeError`로 죽는다.
- **Places field mask에 `rating`·`opening_hours`를 넣지 마라.** 구글은 field mask의
  가장 높은 등급으로 요청 전체를 과금한다. Pro(월 5,000 무료)가 Enterprise가 된다.
- **결과가 2건 이상이면 무조건 `ambiguous`.** 1순위를 자동 채택하면
  "이치란 나카스점"을 찾다가 "이치란 텐진점"이 확정된다.
- **구글지도 저장 목록에 쓰는 API는 없다.** 링크를 만들어주고 사람이 클릭해서 저장한다.

## 문서

- 설계 스펙: `docs/superpowers/specs/2026-09-06-travel-manager-design.md`
- 구현 계획: `docs/superpowers/plans/2026-09-06-collect-to-db-core.md`

스펙과 코드가 다르면 스펙이 맞다. 코드를 고치거나 스펙을 갱신하고 이유를 남긴다.
