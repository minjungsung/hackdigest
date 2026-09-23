# hackdigest

🔥 토픽별 뉴스를 자동 요약해서 매일 이메일로 보내주는 다이제스트 서비스.

## Features

- **토픽별 뉴스 수집**
  - 📱 Tech — Hacker News 상위 기사
  - 📈 Stocks — Yahoo Finance (EN) / Google News 한국 주식 (KO)
  - 🏠 Real Estate — Zillow·HousingWire·CNBC (EN) / Google News 한국 부동산 (KO)
- **언어별 소스 분기** — `ko` 구독자는 한국 주식/부동산, `en` 구독자는 미국 주식/부동산 소스
- **Groq LLM 요약** — Qwen 모델로 기사 3줄 요약, Google Translate fallback
- **구독자별 설정** — language/topic 조합으로 개인화된 다이제스트
- **GitHub Pages 구독 페이지** — 브라우저 언어 자동 감지, 토픽 선택 UI
- **Cloudflare Worker 프록시** — 구독 요청을 GitHub Actions `repository_dispatch`로 중계
- **배포 시 자동화** — main push 시 캐시 삭제 + 테스트 이메일 발송
- Security scan으로 하드코딩된 credential 검출
- Test mode로 안전한 수동 트리거

## Architecture

```
구독 페이지 (GitHub Pages)
  → Cloudflare Worker (프록시)
    → GitHub Actions repository_dispatch
      → subscribers.json 업데이트

cronjob.io (KST 10:15 트리거)
  → GitHub Actions workflow_dispatch
    → Fetchers (HN / Yahoo Finance / Google News / Zillow / HousingWire / CNBC)
      → Groq LLM 요약
        → 구독자별 이메일 발송
```

## GitHub Secrets

| Secret | Description |
|--------|-------------|
| `EMAIL_TO` | Production recipients (comma-separated) |
| `EMAIL_TEST_TO` | Test recipient (single email) |
| `EMAIL_FROM` | Sender Gmail address |
| `EMAIL_APP_PASSWORD` | Gmail app password |
| `GROQ_API_KEY` | Groq API key (LLM 요약용) |

## Usage

### Daily (자동)
[cronjob.io](https://cronjob.io)에서 매일 KST 10:15에 GitHub Actions `workflow_dispatch`를 트리거합니다.

### Manual test
GitHub Actions → HackDigest Daily → Run workflow → "Test mode" 체크 → Run

Test mode는 `EMAIL_TEST_TO`에만 발송됩니다.
체크 해제 시 `subscribers.json`의 전체 구독자에게 발송됩니다.

## Project Structure

```
src/
  main.py           # 진입점
  models.py          # Article, Subscriber, Topic, Language 모델
  subscribers.py     # 구독자 관리
  summarizer.py      # Groq LLM 요약 + Google Translate fallback
  notifier.py        # 이메일 발송
  cache.py           # 기사 캐시
  fetchers/
    tech.py          # Hacker News fetcher
    stocks.py        # 주식 뉴스 fetcher (EN/KO)
    realestate.py    # 부동산 뉴스 fetcher (EN/KO)
docs/
  index.html         # GitHub Pages 구독 페이지
worker/
  src/index.js       # Cloudflare Worker 프록시
```
