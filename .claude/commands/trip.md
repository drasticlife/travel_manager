---
description: 여행 자료(URL/텍스트/자연어)를 정규화 JSON으로 추출해 trip.py에 저장합니다.
---

# /trip add

사용자가 던진 자료에서 **장소·일정·준비물**을 추출해 정규화 JSON을 만들고
`python trip.py add`에 파이프한다.

## 절대 규칙

> **너는 추출과 분류만 한다. 사실(fact)은 Places API가 채운다.**

아래 필드를 JSON에 넣으면 `trip.py`가 거부한다. 절대 만들어내지 마라.

| 금지 필드 | 이유 |
| --- | --- |
| `place_id` | 구글만 발급한다 |
| `lat` / `lng` | **환각 좌표가 들어가면 동선 최적화가 통째로 망가진다** |
| `address` | Places API가 채운다 |
| `verify_status` | 검증받을 대상이 검증 결과를 쓸 수 없다 |
| `maps_url` | place_id에서 파생된다 |
| `id` / `created_at` | DB 소관 |

주소를 "대충 아는 것 같아도" 쓰지 마라. `verify` 단계가 정확한 값을 가져온다.

## 절차

### 1. 입력 종류 판별

| 입력 | `source.kind` | 처리 |
| --- | --- | --- |
| 유튜브 URL | `youtube` | 아래 2번으로 자막 확보 |
| 일반 웹 URL | `web` | WebFetch로 본문 읽기 |
| 붙여넣은 텍스트 | `text` | 그대로 `raw_text` |
| 자연어 지시 | `chat` | 사용자 발언 그대로 `raw_text` |

### 2. 유튜브면 자막 먼저 확보

```bash
python -c "import youtube,sys; sys.stdout.reconfigure(encoding='utf-8'); print(youtube.get_transcript(youtube.extract_youtube_id('<URL>')) or '')"
```

출력이 비어 있으면 자막이 없는 영상이다(E5). 이때는:
- `raw_text`에 영상 제목·설명만 넣고 `places`는 `[]`로 저장하거나
- 사용자에게 **"자막이 없는 영상입니다. 내용을 텍스트로 붙여넣어 주세요"** 라고 요청한다

없는 장소를 지어내지 마라.

### 3. 정규화 JSON 작성

```json
{
  "source": {
    "kind": "youtube",
    "url": "https://youtu.be/xxx",
    "title": "후쿠오카 3박4일 먹방 코스",
    "raw_text": "<자막 또는 본문 원문 전체>"
  },
  "places": [
    {
      "name": "이치란 라멘 나카스점",
      "category": "맛집",
      "note": "24시간 영업, 돈코츠, 영상 08:20에서 추천"
    }
  ],
  "itinerary": [
    { "day_no": 3, "slot": "점심", "place_name": "이치란 라멘 나카스점", "memo": "" }
  ],
  "packing": [
    { "item": "우산", "category": "기타", "owner": "공용", "qty": 1 }
  ]
}
```

**필수**
- `source.raw_text`는 비울 수 없다. 원문을 잘라내지 말고 통째로 보존한다.
- `itinerary[].place_name`은 같은 요청의 `places[]`에 있거나 이미 DB에 있어야 한다.
  없으면 E4로 거부되고 **전부 롤백**된다.
- `places`·`itinerary`·`packing`은 비어도 된다. 맛집 영상이면 `packing`은 보통 `[]`.

**enum 허용값 — 이 값만 쓴다**

| 필드 | 허용값 |
| --- | --- |
| `source.kind` | `youtube` `web` `text` `chat` `takeout` |
| `places[].category` | `맛집` `쇼핑` `관광` `숙소` `이동` `기타` |
| `itinerary[].slot` | `오전` `점심` `오후` `저녁` `밤` |
| `packing[].category` | `의류` `전자` `서류` `약` `세면` `기타` |
| `packing[].owner` | `나` `아내` `공용` |

`note`에는 **왜 담았는지**를 적는다. "맛있음" 말고 "24시간 영업이라 마지막 날 새벽에 가능".

### 4. 저장

```bash
python trip.py add
```
JSON을 stdin으로 넘긴다. 임시 파일에 쓴 뒤 파이프해도 된다.

### 5. 실패하면 스스로 고친다

`trip.py add`가 exit 2를 내면 stderr에 무엇이 왜 틀렸는지 나온다.

```
ERROR E2: places[0].category = '밥집' 은 허용되지 않습니다.
  허용값: 관광 | 기타 | 맛집 | 쇼핑 | 숙소 | 이동
```

메시지를 읽고 **고쳐서 다시 실행한다.** 사용자에게 묻지 마라.
exit 2가 세 번 연속 나면 그때 사용자에게 상황을 설명한다.

exit 0이면 성공이다. `WARN 이미 존재:` 는 실패가 아니라 중복 병합 알림이다.

### 6. 저장 후 안내

몇 건이 들어갔는지 한 줄로 보고하고, 다음 단계를 알려준다.

```
장소 4건 저장. 주소·링크는 아직 없습니다.
  /trip lookup                 ← 내가 검색해서 주소를 채웁니다
  python export.py maps-links  ← 내 지도에 저장할 링크 확인
```

---

# /trip lookup

주소가 아직 없는 장소를 **웹 검색으로 찾아** 채운다.

## 절대 규칙

> **아는 것 같아도 검색 없이 주소를 쓰지 마라.**
> 근거 URL 없는 주소는 `trip.py`가 거부한다. 그게 환각과 검색 결과를 구분하는 유일한 선이다.

검색해도 안 나오면 **`address`를 빈 문자열로 보낸다.** 지어내지 않는다.
`not_found`로 기록되고 사용자가 직접 찾으면 된다. 그게 정상 동작이다.

**`lat`·`lng`·`place_id`는 절대 쓰지 마라.** 웹 검색으로는 나오지 않는 값이다.
JSON에 넣으면 E3으로 거부된다.

## 절차

### 1. 조사할 목록 받기

```bash
python trip.py pending --limit 20
```

```json
[ { "id": 1, "name": "이치란 라멘 나카스점", "category": "기타", "note": "줄 서더라도" } ]
```

한 번에 20건씩 처리한다. 더 있으면 저장 후 다시 실행한다.

### 2. 장소마다 검색 2회

**한국어 1회 + 영어 1회**를 각각 돌린다. 언어를 바꾸면 다른 도메인이 걸려서
교차확인이 된다.

```
WebSearch: "이치란 라멘 나카스점 후쿠오카 주소"
WebSearch: "Ichiran Nakasu Fukuoka address"
```

주소가 나온 결과의 **URL을 그대로 수집**한다. 이게 `evidence_urls`가 된다.

### 3. 판정은 하지 마라

`verify_status`를 JSON에 쓰지 않는다. 코드가 `evidence_urls`의
**고유 도메인 수**를 세서 정한다.

| 코드가 세는 것 | 결과 |
| --- | --- |
| 서로 다른 도메인 2개 이상이 같은 주소 | `matched` |
| 1개 도메인만 / 같은 사이트의 페이지 여러 개 | `ambiguous` |
| 주소 없음 | `not_found` |

`ambiguous`는 실패가 아니다. 사용자가 링크를 열어 확인하면 된다.
**억지로 `matched`를 만들려고 관련 없는 URL을 끼워넣지 마라.**

### 4. 저장

```bash
python trip.py apply-lookup
```

stdin으로 배열을 넘긴다.

```json
[
  {
    "id": 1,
    "address": "5-3-2 Nakasu, Hakata-ku, Fukuoka 810-0801, Japan",
    "name_verified": "이치란 본사 총본점",
    "evidence_urls": [
      "https://triple.guide/restaurants/3814dfe4-...",
      "https://www.kyushurent.com/restaurants/Ichiran-ramen"
    ]
  },
  { "id": 2, "address": "", "evidence_urls": [] }
]
```

허용 필드는 `id` `address` `name_verified` `evidence_urls` **넷뿐이다.**
다른 키가 있으면 전부 거부된다.

`name_verified`에는 검색에서 확인된 **현지/공식 표기**를 넣는다
(예: 사용자는 "이치란 라멘 나카스점"이라 불렀지만 실제 상호는 "이치란 본사 총본점").

### 5. 보고

```
20건 조사 — matched 14 / ambiguous 5 / not_found 1
  python trip.py list --status ambiguous   ← 확인 필요한 5건
  python export.py maps-links              ← 링크 열어서 확인
```

## 하지 말 것

- 여러 URL을 한 번에 처리하려고 JSON을 합치지 마라. **URL 하나당 add 한 번.** 원문 추적이 끊긴다.
- `verify`를 자동으로 실행하지 마라. 과금 단계는 사용자가 결정한다.
- 자막이 길다고 `raw_text`를 요약해서 넣지 마라. 요약은 `note`에 하고 원문은 원문대로 둔다.
