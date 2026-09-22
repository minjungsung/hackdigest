# hackdigest — Design Spec

Hacker News 일일 Top 5 뉴스를 Teams로 발송하는 자동화 서비스.

## 개요

매일 아침 KST 09:00에 Hacker News에서 점수가 가장 높은 글 5개를 가져와, 각 글의 원문에서 본문을 추출·요약한 뒤 Microsoft Teams 채널로 전송한다. GitHub Actions 스케줄로 실행되며, LLM 없이 규칙 기반으로 요약한다.

## 프로젝트 구조

```
hackdigest/
├── src/
│   ├── __init__.py
│   ├── main.py            # 오케스트레이션: fetch → summarize → notify
│   ├── fetcher.py         # HN API에서 Top Stories 점수순 Top 5 반환
│   ├── summarizer.py      # 원문 URL 본문 추출 → 5-10줄 요약
│   ├── notifier.py        # Teams Incoming Webhook으로 메시지 전송
│   └── models.py          # Article dataclass 정의
├── tests/
│   ├── test_fetcher.py
│   ├── test_summarizer.py
│   └── test_notifier.py
├── .github/
│   └── workflows/
│       └── daily-digest.yml
├── requirements.txt
└── README.md
```

## 데이터 모델

```python
from dataclasses import dataclass

@dataclass
class Article:
    title: str          # 글 제목
    url: str            # 원문 링크 (없으면 hn_url과 동일)
    hn_url: str         # HN 토론 페이지 링크
    score: int          # upvote 점수
    comment_count: int  # 댓글 수
    summary: str = ""   # summarizer가 채움 (5-10줄)
```

모듈 간 데이터 전달은 `list[Article]`로 통일한다.

## 모듈 상세

### fetcher.py

HN 공식 Firebase API를 사용한다.

- **API 엔드포인트:** `https://hacker-news.firebaseio.com/v0/`
- **동작:**
  1. `topstories.json`으로 Top Story ID 목록 조회 (약 500개, 이미 랭킹순)
  2. 상위 30개 ID에 대해 각각 `item/{id}.json`으로 상세 조회
  3. 점수(`score`) 기준 내림차순 정렬
  4. 상위 5개를 `Article` 객체로 변환하여 반환
- **성능:** 500개 전부 조회하지 않고 상위 30개만 조회하여 API 호출 최소화. Top Stories는 이미 HN 알고리즘으로 정렬되어 있으므로 30개면 점수 상위 5개를 충분히 포함한다.
- **타임아웃:** 요청당 10초
- **에러 처리:** 개별 항목 조회 실패 시 해당 항목 스킵, 전체 목록 조회 실패 시 3회 재시도 후 에러 발생

### summarizer.py

각 Article의 원문 URL에서 본문을 추출하고 요약한다.

- **본문 추출:** `trafilatura` 라이브러리 사용
  - `trafilatura.fetch_url()`로 페이지 다운로드
  - `trafilatura.extract()`로 본문 텍스트 추출
- **요약 로직 (규칙 기반):**
  1. 추출된 본문을 문장 단위로 분리 (`.`, `!`, `?` 기준)
  2. 앞에서부터 문장을 선택하되, 5문장 이상 10문장 이하
  3. 총 글자수가 1000자를 넘으면 해당 문장에서 자름
  4. 문장이 5개 미만이면 있는 만큼만 사용
- **특수 케이스:**
  - Ask HN, Show HN 등 외부 URL 없는 글 → HN API의 `text` 필드에서 본문 추출. `text` 필드는 HTML이므로 태그를 제거한 후 동일한 문장 분리 로직 적용.
  - 본문 추출 실패 → `"본문을 가져올 수 없습니다."` 폴백 메시지
- **타임아웃:** 페이지당 15초

### notifier.py

Teams Incoming Webhook으로 Adaptive Card를 전송한다.

- **Webhook URL:** 환경 변수 `TEAMS_WEBHOOK_URL`에서 읽음
- **메시지 포맷:** Adaptive Card v1.4
  - 헤더: "🔥 Hacker News Daily Top 5 — {날짜}"
  - 각 글 블록:
    - `#{순위} {제목}` (원문 링크)
    - `⬆ {점수} | 💬 {댓글수}` + HN 토론 링크
    - 요약 텍스트 (5-10줄)
  - 글 사이 구분선
- **에러 처리:** 전송 실패 시 최대 3회 재시도 (1초 간격), 최종 실패 시 예외 발생

### main.py

모듈을 순서대로 호출하는 오케스트레이터.

```
1. fetcher.fetch_top_articles(count=5) → list[Article]
2. for article in articles: summarizer.summarize(article) → summary 필드 채움
3. notifier.send_to_teams(articles) → Teams 전송
```

- 가져온 글이 0개면 발송하지 않고 정상 종료
- 로깅: `logging` 모듈 사용, INFO 레벨로 진행 상황 출력

## GitHub Actions 워크플로우

```yaml
name: HackDigest Daily
on:
  schedule:
    - cron: '0 0 * * *'    # UTC 00:00 = KST 09:00
  workflow_dispatch:         # 수동 실행 지원

jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python -m src.main
        env:
          TEAMS_WEBHOOK_URL: ${{ secrets.TEAMS_WEBHOOK_URL }}
```

## 의존성

```
requests==2.32.3
trafilatura==1.12.2
```

테스트용 추가 의존성:
```
pytest==8.3.3
responses==0.25.3    # requests 모킹
```

## 에러 처리 요약

| 상황 | 동작 |
|------|------|
| HN API 전체 실패 | 3회 재시도 → 실패 시 exit 1 |
| 개별 글 조회 실패 | 해당 글 스킵, 나머지 진행 |
| 본문 추출 실패 | 폴백 메시지로 대체, 나머지 진행 |
| Teams Webhook 실패 | 3회 재시도 → 실패 시 exit 1 |
| 유효한 글 0개 | 발송하지 않고 정상 종료 |

## 향후 확장 가능성 (현재 구현 범위 밖)

- Slack/Discord 알림 추가 (notifier 모듈만 추가)
- LLM 기반 요약으로 전환 (summarizer 교체)
- 카테고리 필터링 (AI, DevOps 등 관심 분야만)
- 한국어 요약
