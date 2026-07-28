import calendar
import datetime

from django.utils import timezone
import dateutil.parser


def greater_than(date, days_ago):
    delta = timezone.now() - date
    return delta.days > days_ago


def format_string(date_string, current_format="%Y-%m-%d", new_format="%A, %B %e, %Y"):
    return datetime.datetime.strptime(date_string,  current_format).strftime(new_format)


def format(date, new_format="%d/%m/%Y, %H:%M %Z"):
    return date.strftime(new_format).replace('{S}', str(date.day) + suffix(date.day))


def suffix(d):
    return 'th' if 11 <= d <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')


def validate(datetime_str):
    try:
        dateutil.parser.parse(datetime_str)
        return True
    except ValueError:
        raise Exception("Please enter a valid datetime in format 'YYYY-MM-DDTHH:mm'")


def parse(datetime_str):
    return dateutil.parser.parse(datetime_str)


def parse_date(date_str):
    return dateutil.parser.parse(date_str).date()


def today():
    return now().today()


def local_date(value=None):
    """Return a calendar date in the active Django timezone."""
    if value is None:
        return timezone.localdate()
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    return value


def day_bounds(day=None):
    """Return timezone-aware [start, end) datetimes for a calendar day.

    Prefer these over ``created_at__date=…`` so btree indexes on ``created_at``
    remain usable.
    """
    day = local_date(day)
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    end = start + datetime.timedelta(days=1)
    return start, end


def tomorrow():
    return days_later(day_count=1)


def yesterday():
    return days_ago(1)


def day_before_yesterday():
    return days_ago(2)


def now():
    return timezone.now()


def next_day(date):
    return days_later(date, 1)


def days_ago(days, date=None):
    from datetime import timedelta
    if not date:
        date = timezone.now()
    return date - timedelta(days=days)


def days_later(date=None, day_count=1):
    if not date:
        date = today()

    return date + datetime.timedelta(days=day_count)


def months_ago(months, date=None):
    from dateutil.relativedelta import relativedelta
    if not date:
        date = timezone.now()
    return date - relativedelta(months=months)


def months_later(months):
    from dateutil.relativedelta import relativedelta
    return timezone.now() + relativedelta(months=months)


def last_week():
    return timezone.now()-datetime.timedelta(days=7)


def create_date(day, month, year):
    return datetime.date(year=year, month=month, day=day)


def convert_to_date(datetime_to_compare):
    if isinstance(datetime_to_compare, datetime.datetime):
        return datetime.date()


def from_timestamp(timestamp):
    return datetime.datetime.fromtimestamp(timestamp)


def start_of_current_month():
    _start_of_current_month = start_of_month(today().date())
    return _start_of_current_month


def end_of_current_month():
    _end_of_current_month = end_of_month(today().date())
    return _end_of_current_month


def start_of_month(date):
    return date.replace(day=1)


def end_of_month(date):
    last_day_of_month = calendar.monthrange(date.year, date.month)[1]
    return create_date(last_day_of_month, date.month, date.year)


def is_start_of_the_month():
    _start_of_current_month = start_of_current_month()
    return today().date() == _start_of_current_month


# todo fix the logic
def workday_before(date_):
    return date_


def date_in_past(date):
    return date < today().date()
