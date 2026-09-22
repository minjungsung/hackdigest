# hackdigest

🔥 Hacker News 일일 Top 5 뉴스 다이제스트를 이메일/Teams로 자동 발송합니다.

## 기능

- HN API에서 점수 높은 순으로 Top 5 가져오기
- 각 글의 원문에서 5-10줄 요약 자동 추출
- 이메일 또는 Teams Webhook으로 발송
- GitHub Actions로 매일 KST 09:00 자동 실행

## 설정

GitHub Secrets에 다음 값을 등록하세요:

| Secret | 설명 |
|--------|------|
| `EMAIL_TO` | 수신 이메일 주소 |
| `EMAIL_FROM` | 발신 Gmail 주소 |
| `EMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 |
| `TEAMS_WEBHOOK_URL` | (선택) Teams Incoming Webhook URL |

## 수동 실행

GitHub Actions → HackDigest Daily → Run workflow
