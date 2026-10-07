import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from src.course_brief import render, update_calendar


class CourseBriefTests(unittest.TestCase):
    def test_stale_data_and_completed_tasks(self):
        snapshot = {'checked_at':'2026-10-07T09:00:00+09:00', 'completed':['done'],
                    'readings':[], 'tasks':[
                        {'id':'done','due':'2026-10-12T03:59:00+00:00','title':'Finished task','note':'','url':''},
                        {'id':'reply','due':'2026-10-17T03:59:00+00:00','title':'Peer replies','note':'Two peers','url':'https://jhu.instructure.com/'}]}
        body, markup = render(snapshot, datetime(2026,10,9,9,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertIn('실시간 연결 전',body)
        self.assertNotIn('Finished task',body)
        self.assertIn('10/17 12:59 한국 시간',body)
        self.assertIn('Peer replies',markup)

    def test_html_escaping_and_dst(self):
        snapshot = {'checked_at':'2026-12-06T08:00:00+09:00','readings':[], 'tasks':[
            {'id':'x','due':'2026-12-07T04:59:00+00:00','title':'<script>bad</script>','note':'','url':'https://jhu.instructure.com/'}]}
        body, markup = render(snapshot, datetime(2026,12,6,9,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertIn('12/07 13:59 한국 시간',body)
        self.assertNotIn('<script>',markup)

    def test_date_only_calendar_preserves_known_time_and_skips_submitted(self):
        snapshot = {'tasks': [], 'known_assignments': {
            '1': {'due':'2026-10-12T03:59:00Z','submitted':False},
            '2': {'due':'2026-10-12T03:59:00Z','submitted':True}}}
        feed = '''BEGIN:VCALENDAR
BEGIN:VEVENT
UID:event-assignment-1
DTSTART;VALUE=DATE:20261018
SUMMARY:Module 7 Assignment
URL:https://jhu.instructure.com/courses/1/assignments/1
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-2
DTSTART;VALUE=DATE:20261018
SUMMARY:Already submitted
END:VEVENT
END:VCALENDAR'''
        updated = update_calendar(snapshot, feed, datetime(2026,10,7,9,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertEqual(len(updated['tasks']),1)
        due = datetime.fromisoformat(updated['tasks'][0]['due']).astimezone(ZoneInfo('Asia/Seoul'))
        self.assertEqual(due.strftime('%m/%d %H:%M'),'10/19 12:59')


if __name__ == '__main__':
    unittest.main()
