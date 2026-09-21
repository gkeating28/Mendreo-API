from django.test import SimpleTestCase
from freezegun import freeze_time

from api.utils import DateUtils


class DayBoundsTests(SimpleTestCase):
    def test_day_bounds_are_half_open(self):
        import datetime
        day = datetime.date(2026, 7, 28)
        start, end = DateUtils.day_bounds(day)
        self.assertEqual((end - start).total_seconds(), 24 * 3600)
        self.assertEqual(start.date(), day)
        self.assertEqual(end.date(), datetime.date(2026, 7, 29))

    def test_local_now_is_ireland_not_utc(self):
        with freeze_time("2026-09-21 08:30:00+00:00"):
            local = DateUtils.local_now()
        self.assertEqual(str(local.tzinfo), "Europe/Dublin")
        self.assertEqual(local.hour, 9)
        self.assertEqual(local.minute, 30)
