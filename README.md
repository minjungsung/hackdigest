# hackdigest

🔥 Automated daily digest of the top 5 Hacker News stories, translated to Korean and delivered via email or Teams.

## Features

- Fetches top 5 HN stories by score via official API
- Extracts and summarizes each article in 3 sentences
- Translates summaries to Korean (Google Translate → Argos offline fallback)
- Sends to multiple recipients via email or Teams Webhook
- Runs daily at KST 09:00 via GitHub Actions
- Built-in security scan to catch hardcoded credentials
- Test mode for safe manual triggers

## GitHub Secrets

| Secret | Description |
|--------|-------------|
| `EMAIL_TO` | Production recipients (comma-separated) |
| `EMAIL_TEST_TO` | Test recipient (single email) |
| `EMAIL_FROM` | Sender Gmail address |
| `EMAIL_APP_PASSWORD` | Gmail app password |
| `TEAMS_WEBHOOK_URL` | (Optional) Teams Incoming Webhook URL |

## Usage

### Daily (automatic)
Runs every day at KST 10:15 via cron schedule.

### Manual test
GitHub Actions → HackDigest Daily → Run workflow → check "Test mode" → Run

Test mode sends only to `EMAIL_TEST_TO` (your email).
Unchecking test mode sends to all `EMAIL_TO` recipients.
