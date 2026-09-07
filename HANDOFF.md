# 작업 인계 (HANDOFF)

> 새 세션은 이 파일부터 읽는다. 그다음 `CLAUDE.md`.
> 마지막 갱신: 2026-09-07

## 지금 상태 한 줄

수집→DB 코어는 **동작한다.** 장소 51건·일정 18건이 들어 있고 테스트 55건이 통과한다.
남은 건 주소 미확보 28건과, 아직 손대지 않은 서브프로젝트 4개다.

## 여행 정보 (마감이 여기서 나온다)

| | |
| --- | --- |
| 일정 | **2026-09-21(월) ~ 09-24(목)**, 3박 4일 |
| 남은 시간 | 2026-09-07 기준 **약 2주** |
| 숙소 | 호텔 포르자 하카타역 치쿠시구치Ⅱ (1-13-3 Hakataekihigashi) |
| 주의 | 실버위크 5연휴(9/19~23) 한복판. 관광지 혼잡, 일부 시설 운영시간 연장 |

**2주밖에 없다.** 새 기능보다 "지금 여행에 실제로 쓰이는 것"을 먼저 끝낸다.

## 바로 다음에 할 일 (우선순위 순)

1. **주소 미확보 28건 채우기** — `/trip lookup` 반복
   ```bash
   python trip.py pending --limit 20   # 목록 받기
   # 장소마다 WebSearch 한국어 1회 + 영어 1회 → 근거 URL 수집
   python trip.py apply-lookup          # stdin JSON
   ```
   현재 `matched 21 / ambiguous 2 / not_found 4 / pending 24`

2. **지도 링크 확인용 HTML 만들기** (사용자가 요청했고 아직 안 만듦)
   터미널에서 URL 인코딩된 긴 링크 51개를 클릭하는 건 고통스럽다.
   장소명·구글 표기·근거 URL을 나란히 놓고 링크만 누르면 되는 정적 페이지 +
   확인 완료분을 `mark-saved`로 되먹이는 명령어 출력.

3. **Todoist 푸시** — 준비물·일정을 체크리스트로
   ```bash
   python export.py todoist          # 미리보기 (기본)
   python export.py todoist --push   # 실제 푸시
   ```
   ⚠️ 프로젝트는 배우자와 공유 중이고 **이미 태스크 50건**이 있다.
   중복 방지가 2중(로컬 id + 원격 제목)이지만 `--push` 전에 반드시 미리보기를 볼 것.

4. 노트의 남은 확인 사항 (사람이 해야 하는 것)
   - `7-Eleven`(place id 7) 상호 특정 — 평점 3.1(11), 목록에 왜 담았는지 사용자만 앎
   - 야마야 다이묘점 주소 미확인
   - Klook/Live Japan 러닝화 5% 쿠폰 바코드 캡처
   - DAY2 아침 마린월드 X(@marine_uminaka) 임시휴관 확인
   - 마린월드·해변공원 사전 예매 여부 결정

## 안 한 것 (서브프로젝트, 각각 별도 spec→plan 사이클)

| # | 내용 | 상태 |
| --- | --- | --- |
| 3 | DB 기반 LLM 정보 제공 (최적동선·맛집추천·쇼핑주의) | 미착수. **좌표가 없어 동선 최적화는 막혀 있다** |
| 4 | GitHub Pages 배포 | 미착수. 리포가 private이라 Pages는 Pro 필요 → public 전환 여부 결정 필요 |
| 5-a | 텔레그램 봇 수집 (폰에서 던지기) | 미착수. `trip.py` 위에 어댑터로 얹으면 됨 |
| — | 사진/스크린샷 OCR 입력 | 범위 밖 (사용자가 제외) |

## 반드시 알아야 할 함정 (전부 실제로 밟았다)

1. **Windows stdin/stdout 이 cp949다.** 파이프로 들어온 UTF-8 한국어가 깨진다
   (`맛집` → `留쏆쭛`). `main()` 의 `sys.stdin.reconfigure(encoding="utf-8")` 를 지우지 마라.
   `io.StringIO` 테스트로는 재현되지 않는다 — subprocess 테스트가 잡는다.
2. **Todoist REST v2 는 폐기됐다(410 Gone).** `/api/v1/` 을 쓰고 `{results, next_cursor}` 를
   `unwrap()` 으로 벗긴다. `project_id` 는 브라우저 URL 의 대시 뒤 문자열과 같다.
3. **웹 검색으로 place_id·좌표는 안 나온다. 주소만 나온다.** 그래서 주소 기반 검색 링크를 쓴다.
   Claude 가 좌표를 쓰면 `apply-lookup` 이 E3 으로 거부한다. 이 가드를 풀지 마라.
4. **Google Takeout 은 '저장됨' 목록을 안 내줬다.** '내 지도' 제품만 잡혀 빈 아카이브가 나왔다.
   목록은 브라우저로 직접 읽었다(가상 스크롤이라 스크롤하며 수집).
5. **Places API 는 무료 한도만 써도 결제 수단 등록이 필수다.** 그래서 선택 경로다.
6. **일정 정렬은 `day_no, 슬롯순서, seq`.** `seq` 만 쓰면 밤이 오전보다 먼저 나온다.

## 데이터 출처

| 파일 | 내용 |
| --- | --- |
| `data/fukuoka_list.json` | 구글지도 `'26 후쿠오카` 목록 27건 (브라우저로 읽음) |
| `data/lookup_batch1.json` | 위 27건의 주소 조사 결과 + 근거 URL |
| `data/journal_note_import.json` | 볼트 일일노트에서 가져온 장소 24건 + 일정 18건 |
| `data/trip.db` | SQLite 본체 (git 커밋 대상) |

원본 노트: `C:\Vault\Moon Life Planner\03. JOURNALS\2026\2026-M09\2026-W37\후쿠오카 3박 4일 여행 DB.md`

## 문서

- 설계 스펙: `docs/superpowers/specs/2026-09-06-travel-manager-design.md`
- 구현 계획: `docs/superpowers/plans/2026-09-06-collect-to-db-core.md`
- 프로젝트 규약: `CLAUDE.md`
- 사용법: `README.md`

스펙과 코드가 다르면 스펙이 맞다. 코드를 고치거나 스펙을 갱신하고 이유를 남긴다.
