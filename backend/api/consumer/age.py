"""Shared 18+ check used by registration and the welcome flow."""

import datetime

from ..utils import Constants


def meets_minimum_age(date_of_birth) -> bool:
    """Same threshold as registration: a birthday of today minus 18 years is old enough.

    29 February in a non-leap threshold year uses 28 February, so the check
    does not raise.
    """
    if not date_of_birth:
        return True

    today = datetime.datetime.today()
    year = today.year - Constants.CONSUMER_MINIMUM_AGE
    try:
        threshold = datetime.date(year, date_of_birth.month, date_of_birth.day)
    except ValueError:
        threshold = datetime.date(year, 2, 28)
    return date_of_birth <= threshold
