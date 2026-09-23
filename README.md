# 🔥 HackDigest

**AI-summarized daily news digest — delivered to your inbox every morning.**

Subscribe at **[minjungsung.github.io/hackdigest](https://minjungsung.github.io/hackdigest/)**

## What is HackDigest?

HackDigest curates and summarizes the top stories across Tech, Stocks, and Real Estate, then delivers a personalized daily digest straight to your email. Each article is condensed into a 3-sentence summary using AI — so you stay informed without the noise.

**100% serverless. $0/month to run.**

## Features

- **Multi-topic news curation**
  - 💻 **Tech** — Top Hacker News stories ranked by score
  - 📈 **Stocks** — Yahoo Finance (EN) / Korean market via Google News (KO)
  - 🏠 **Real Estate** — Zillow · HousingWire · CNBC (EN) / Korean market via Google News (KO)
- **Region-aware sources** — Korean subscribers get Korean stock & real estate news, English subscribers get US sources
- **AI-powered summaries** — Groq Qwen model generates 3-sentence casual summaries, with Google Translate fallback
- **Per-subscriber personalization** — Choose your language + topics for a tailored digest
- **Auto-detecting subscription page** — Detects browser language, responsive UI
- **Zero infrastructure cost** — Runs entirely on GitHub Actions + Cloudflare Workers + GitHub Pages
- **Security hardened** — Automated security scanning on every deploy (injection detection, Bandit, secrets scan)
- **Deploy automation** — Every push clears cache + sends a test email automatically

## Architecture

```
Subscription Page (GitHub Pages)
  → Cloudflare Worker (proxy)
    → GitHub Actions repository_dispatch
      → updates subscribers.json + sends welcome email

cronjob.io (daily trigger at KST 10:15)
  → GitHub Actions workflow_dispatch
    → Fetchers (HN API / Yahoo Finance / Google News / Zillow / HousingWire / CNBC)
      → Groq LLM summarization
        → Per-subscriber email delivery via Gmail SMTP
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Summarization | Groq API (`qwen/qwen3.8-27b`) |
| Translation fallback | Google Translate (free API) |
| Article extraction | trafilatura |
| RSS parsing | feedparser |
| Email delivery | Gmail SMTP (SSL) |
| Subscription proxy | Cloudflare Worker |
| CI/CD & runtime | GitHub Actions |
| Caching | GitHub Actions Cache (daily JSON) |
| Frontend | GitHub Pages (vanilla HTML/JS) |
| Scheduling | cronjob.io → workflow_dispatch |
| Security scanning | Bandit + custom injection/secrets checks |
| Dependency management | Dependabot (daily, auto-merge) |

## How It Works

1. **Fetch** — Pulls top articles from multiple sources per topic
2. **Rank** — Scores articles by impact keywords + multi-source appearance
3. **Summarize** — Groq LLM generates a 3-sentence summary in the subscriber's language
4. **Cache** — Stores articles + summaries as daily JSON (avoids redundant API calls)
5. **Deliver** — Sends personalized HTML emails per subscriber per topic

## Subscribe

Visit **[minjungsung.github.io/hackdigest](https://minjungsung.github.io/hackdigest/)** and enter your email. The page auto-detects your language — or toggle manually.

## Usage

### Daily (automated)
[cronjob.io](https://cronjob.io) triggers a GitHub Actions `workflow_dispatch` at KST 10:15 every day.

### Manual test
GitHub Actions → HackDigest Daily → Run workflow → Check "Test mode" → Run

Test mode sends only to `EMAIL_TEST_TO`. Uncheck to send to all subscribers.

## Project Structure

```
src/
  main.py            # Entry point — orchestrates fetch → summarize → send
  models.py           # Article, Subscriber, Topic, Language models
  subscribers.py      # Subscriber CRUD (JSON-based)
  summarizer.py       # Groq LLM summarization + Google Translate fallback
  notifier.py         # HTML email builder + Gmail SMTP delivery
  cache.py            # Daily article/summary cache (JSON files)
  fetchers/
    __init__.py       # Topic dispatcher with language-aware routing
    tech.py           # Hacker News API fetcher (score-ranked)
    stocks.py         # Stock news fetcher (Yahoo Finance EN / Google News KO)
    realestate.py     # Real estate fetcher (Zillow·HousingWire·CNBC EN / Google News KO)
docs/
  index.html          # Subscription page (GitHub Pages, i18n, auto-detect language)
worker/
  src/index.js        # Cloudflare Worker proxy (rate-limited, CORS, input validation)
scripts/
  check_injection.py  # CI security check for workflow injection vulnerabilities
```

## Security

- All external input is sanitized via environment variables (no `${{ }}` in shell)
- HTML email output is escaped to prevent XSS
- URL scheme whitelist blocks `javascript:` injection
- Cloudflare Worker validates and whitelists all input fields
- Automated security scan on every push: injection detection, Bandit, secrets scan, frontend XSS check
- Dependabot monitors dependencies daily with auto-merge

## GitHub Secrets

| Secret | Description |
|--------|-------------|
| `EMAIL_TEST_TO` | Test recipient email |
| `EMAIL_FROM` | Sender Gmail address |
| `EMAIL_APP_PASSWORD` | Gmail app password |
| `GROQ_API_KEY` | Groq API key for LLM summarization |

## Contributing

Feedback and feature requests welcome! Check out the [Discussions](https://github.com/minjungsung/hackdigest/discussions) tab.

## License

MIT
