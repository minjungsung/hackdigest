# Private daily study email

The `JHU Morning Study Brief` workflow runs independently from the public news digest and subscriber list. It uses the existing Gmail SMTP secrets. The default schedule requests execution at 09:00 Asia/Seoul; GitHub scheduled workflows can be delayed. The existing external cron service can instead dispatch `course-brief.yml` at that time.

The sender stays disabled until repository variable `COURSE_BRIEF_ENABLED=true` is set. Add secrets `COURSE_EMAIL_TO` and `COURSE_BRIEF_DATA` (a JSON object with `checked_at`, `tasks`, `readings`, and optional `completed`). Never commit a personal Canvas snapshot or publish it to Pages/artifacts.

Set secret `CANVAS_CALENDAR_FEED` to the private JHU calendar feed URL. It refreshes assignment dates from the cloud without browser login. Canvas feed events often contain dates only: known assignment times are preserved; new items explicitly label an assumed 23:59 ET time for verification. Discussion dates are kept separately from the reviewed instructions.

The implementation always displays the last full Canvas check time and warns after 24 hours that readings, peer replies, and recent submissions may not be current. Calendar refresh cannot verify submission status or fetch module reading pages. JHU disables personal access token creation; an administrator-issued token or approved integration is needed for those live updates.

Discussion peer replies are separate from initial posts. AML replies happen in Teams, so a Canvas submission never proves reply completion. Reading completion must be recorded explicitly. Email content guides the student's work and does not post or submit coursework.

Local preview: `python -m src.course_brief --preview --snapshot /path/to/private.json`. Verification: `python -m unittest discover -s tests -p 'test_course_brief.py'`.
