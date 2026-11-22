from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
import mirea_schedule as schedule


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261116
DTEND;VALUE=DATE:20261123
SUMMARY:12 неделя
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Moscow:20261116T090000
DTEND;TZID=Europe/Moscow:20261116T103000
CATEGORIES:ЛК
SUMMARY:ЛК Математический
  анализ
DESCRIPTION:Преподаватель: Иванов Иван Иванович\n
LOCATION:А-123
EXDATE;TZID=Europe/Moscow:20261130T090000,
 20261214T090000
RRULE:FREQ=WEEKLY;INTERVAL=2;UNTIL=20261228T060000Z
END:VEVENT
BEGIN:VEVENT
DTSTART:20261116T062000Z
DTEND:20261116T075000Z
SUMMARY:Физика
CATEGORIES:ЛК
END:VEVENT
END:VCALENDAR
"""


class TestMireaSchedule(unittest.TestCase):
    def test_repeated_dates_and_folded_fields(self):
        entries = schedule.parse_ical(ICS, 'ИКБО-01-26')['entries']
        self.assertEqual([row['date'] for row in entries], ['2026-11-16', '2026-11-16', '2026-12-28'])
        self.assertEqual(entries[0]['subject'], 'Математический анализ')
        self.assertEqual(entries[0]['variants'][0]['room'], 'А-123')
        self.assertEqual(entries[1]['start'], '09:20')
        self.assertEqual(entries[0]['folder'], '2026-11-16 09-00 — Математический анализ — ЛК')
        self.assertNotIn('12 неделя', [row['subject'] for row in entries])
        self.assertEqual(schedule.suggest(entries[:2], datetime(2026, 11, 16, 8, 58, tzinfo=schedule.TZ), 480), 0)
        self.assertIsNone(schedule.suggest(entries[:2], datetime(2026, 11, 16, 9, 25, tzinfo=schedule.TZ), 480))
        self.assertIsNone(schedule.suggest(entries[:2], datetime(2026, 11, 16, 8, 58, tzinfo=schedule.TZ), 25))

    def test_cache_is_group_specific_and_profile_is_optional(self):
        legacy = {'group': 'ЛЕГАСИ-01-24', 'entries': [], 'timezone': schedule.TZ.key}
        with tempfile.TemporaryDirectory() as target:
            root = Path(target)
            with patch.object(schedule, 'PROFILE', root/'profile.json'), patch.object(schedule, 'CACHE', root/'cache.json'), patch.object(schedule, 'last_error', ('',0)):
                self.assertFalse(schedule.profile()['configured'])
                self.assertEqual(schedule.set_profile({'skip': True}), {'configured': True, 'group': '', 'course': None})
                self.assertIs(schedule.load_calendar(legacy), legacy)
                with self.assertRaises(ValueError):
                    schedule.set_profile({'group': 'ИКБО-01-26', 'course': True})
                self.assertEqual(schedule.set_profile({'group': ' икбо‑01–26 ', 'course': 1})['group'], 'ИКБО-01-26')
                expected = schedule.parse_ical(ICS, 'ИКБО-01-26')
                with patch.object(schedule, '_schedule', return_value=expected):
                    self.assertEqual(schedule.load_calendar(legacy)['entries'], expected['entries'])
                with patch.object(schedule, '_schedule', side_effect=OSError), patch.object(schedule, 'REFRESH_SECONDS', 0):
                    self.assertEqual(schedule.load_calendar(legacy)['entries'], expected['entries'])
                    schedule.set_profile({'group': 'ИКБО-02-26', 'course': 1})
                    self.assertEqual(schedule.load_calendar(legacy)['entries'], [])


if __name__ == '__main__':
    unittest.main()
