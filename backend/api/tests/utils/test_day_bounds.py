from django.test import SimpleTestCase

from api.utils import DateUtils


class DayBoundsTests(SimpleTestCase):
    def test_day_bounds_are_half_open(self):
        import datetime
        day = datetime.date(2026, 7, 28)
        start, end = DateUtils.day_bounds(day)
        self.assertEqual((end - start).total_seconds(), 24 * 3600)
        self.assertEqual(start.date(), day)
        self.assertEqual(end.date(), datetime.date(2026, 7, 29))
