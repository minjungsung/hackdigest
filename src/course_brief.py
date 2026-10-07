"""Private Korean study email, independent of the public news subscribers."""

import argparse
import html
import json
import os
import re
import smtplib
import ssl
import urllib.request
from datetime import datetime, timedelta, time
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
ET = ZoneInfo('America/New_York')


def calendar_events(text):
    unfolded = re.sub(r'\r?\n[ \t]', '', text)
    events = []
    for block in unfolded.split('BEGIN:VEVENT')[1:]:
        event = {}
        for line in block.split('END:VEVENT')[0].splitlines():
            if ':' not in line:
                continue
            key, value = line.split(':', 1)
            event[key.split(';')[0]] = value.replace('\\n', '\n').replace('\\,', ',').replace('\\;', ';')
        if event.get('DTSTART'):
            events.append(event)
    return events


def update_calendar(snapshot, text, now):
    tasks = {t['id']: dict(t) for t in snapshot['tasks']}
    known = snapshot.get('known_assignments', {})
    for event in calendar_events(text):
        match = re.search(r'assignment-(\d+)', event.get('UID', ''))
        if not match:
            continue
        aid = match[1]
        value = event['DTSTART']
        if len(value) == 8:
            day = datetime.strptime(value, '%Y%m%d').date()
            original = known.get(aid, {}).get('due')
            clock = datetime.fromisoformat(original.replace('Z', '+00:00')).astimezone(ET).time() if original else time(23, 59)
            due = datetime.combine(day, clock, ET)
            note = 'Canvas 피드는 날짜만 제공. 시각은 기존 Canvas 확인값' if original else '피드에 마감 시각 없음. 표시 시각은 ET 23:59 가정이므로 Canvas에서 확인.'
        else:
            due = datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=ZoneInfo('UTC'))
            note = 'Canvas 캘린더에서 최신 마감 확인. 제출 완료 여부는 별도 확인.'
        if known.get(aid, {}).get('submitted'):
            continue
        if 'Discussion' in event.get('SUMMARY', ''):
            # Initial posts and replies are already split from their instructions.
            continue
        ident = 'a-' + aid
        task = tasks.get(ident, {'id': ident, 'title': event.get('SUMMARY', 'Canvas 과제'),
                                'url': event.get('URL', 'https://jhu.instructure.com/'), 'note': note})
        task['due'] = due.isoformat()
        task['note'] = note + ' · ' + task.get('note', '')
        tasks[ident] = task
    return {**snapshot, 'tasks': list(tasks.values()), 'calendar_checked_at': now.isoformat()}


def fetch_calendar(url):
    if not url.startswith('https://jhu.instructure.com/feeds/calendars/'):
        raise ValueError('Only the JHU Canvas calendar feed is supported')
    with urllib.request.urlopen(url, timeout=30) as response:  # nosec B310: HTTPS JHU prefix validated above
        text = response.read(5_000_000).decode('utf-8')
    if not text.startswith('BEGIN:VCALENDAR'):
        raise ValueError('Canvas did not return a calendar')
    return text


def render(snapshot, now):
    checked = datetime.fromisoformat(snapshot['checked_at'])
    age = now - checked
    completed = set(snapshot.get('completed', []))
    tasks = [t for t in snapshot['tasks'] if t['id'] not in completed and
             -7 <= (datetime.fromisoformat(t['due']) - now).days <= 21]
    tasks.sort(key=lambda t: t['due'])
    lines = [f'{now.astimezone(KST):%m월 %d일} 오늘의 공부', '',
             'Canvas 마지막 확인: ' + checked.astimezone(KST).strftime('%m/%d %H:%M')]
    if snapshot.get('calendar_checked_at'):
        lines += ['과제 캘린더는 오늘 갱신했습니다. 읽기 목록·답글 규칙·제출 상태는 마지막 수업 확인 기준입니다.']
    if snapshot.get('calendar_error'):
        lines += ['⚠️ 오늘 캘린더 조회 실패. 이전 확인 자료를 사용합니다.']
    if age > timedelta(hours=24):
        lines += ['⚠️ Canvas 실시간 연결 전입니다. 아래 내용은 마지막 확인 자료이며, 새 과제·마감 변경·최근 제출은 반영되지 않을 수 있습니다.']
    readings = [r for r in snapshot['readings'] if r['id'] not in completed and
                r['start'] <= now.astimezone(KST).date().isoformat() <= r['end']]
    lines += ['', '오늘 먼저 할 일']
    # Rotate unfinished readings so each morning gives a concrete, manageable start.
    if readings:
        r = readings[now.astimezone(KST).weekday() % len(readings)]
        lines += ['읽기 · ' + r['title'], r['today_focus'], r['url']]
    for t in tasks[:3]:
        due = datetime.fromisoformat(t['due'])
        lines += [t['title'], t['note'],
                  '마감 ' + due.astimezone(KST).strftime('%m/%d %H:%M 한국 시간'), t['url']]
    if not tasks and not readings:
        lines += ['확인 자료에 예정된 일이 없습니다. Canvas를 확인해 새로 공개된 일을 점검하세요.',
                  'https://jhu.instructure.com/']
    lines += ['', '이번 주 필수 읽기와 위치']
    for r in readings:
        lines += [r['title'], r['requirement'], r['url']]
    lines += ['', '다가오는 마감']
    for t in tasks:
        due = datetime.fromisoformat(t['due'])
        lines += [due.astimezone(KST).strftime('%m/%d %H:%M') + ' · ' + t['title'], t['url']]
    lines += ['', '답글은 첫 글과 따로 관리합니다. Teams 답글·읽기 완료는 직접 확인해야 합니다.',
              '실시간 Canvas 연결이 없으면 오래된 항목은 완료 여부 확인이 필요합니다.']
    body = '\n'.join(lines)
    cards = ''.join('<p style="margin:8px 0;line-height:1.7">' +
                    (f'<a href="{html.escape(line, quote=True)}">자료 열기 →</a>'
                     if line.startswith('https://') else html.escape(line)) + '</p>'
                    for line in lines)
    markup = ('<!doctype html><html lang="ko"><meta charset="utf-8">'
              '<body style="background:#f4f6fa;font-family:Arial,sans-serif;color:#182236">'
              '<main style="max-width:640px;margin:auto;padding:24px;background:white">'
              '<h1 style="font-size:24px">오늘 읽을 것과 할 일</h1>' + cards + '</main></body></html>')
    return body, markup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--test', action='store_true', help='Send a clearly labeled test email to the configured private recipient')
    args = parser.parse_args()
    raw = args.snapshot.read_text() if args.snapshot else os.environ.get('COURSE_BRIEF_DATA', '')
    if not raw:
        raise RuntimeError('COURSE_BRIEF_DATA 연결이 필요합니다.')
    snapshot = json.loads(raw)
    now = datetime.now(KST)
    feed_url = os.environ.get('CANVAS_CALENDAR_FEED', '')
    if feed_url:
        try:
            snapshot = update_calendar(snapshot, fetch_calendar(feed_url), now)
        except Exception:
            snapshot['calendar_error'] = True
    body, markup = render(snapshot, now)
    if args.preview:
        Path('course-preview.txt').write_text(body)
        Path('course-preview.html').write_text(markup)
        print('Preview generated locally; no email sent.')
        return
    sender = os.environ['EMAIL_FROM']
    recipient = os.environ['COURSE_EMAIL_TO']
    message = EmailMessage()
    message['Subject'] = ('[테스트] ' if args.test else '') + f'[JHU 공부] {now:%m/%d} 오늘 읽을 것과 할 일'
    message['From'] = sender
    message['To'] = recipient
    message.set_content(body)
    message.add_alternative(markup, subtype='html')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(sender, os.environ['EMAIL_APP_PASSWORD'])
        smtp.send_message(message)
    print('Course briefing accepted by SMTP server.')


if __name__ == '__main__':
    main()
