from functools import partial

from django.db import models

from cuid import cuid
from charidfield import CharIDField as _CUIDCharIdField


class EnumField(models.Field):
    """
    A field class that maps to MySQL's ENUM type.

    Usage:

    class Card(models.Model):
        suit = EnumField(options=('Clubs', 'Diamonds', 'Spades', 'Hearts'))

    c = Card()
    c.suit = 'Clubs'
    c.save()
    """
    def __init__(self, *args, **kwargs):
        if "options" in kwargs:
            self.values = kwargs.pop('options')
            kwargs['choices'] = [(v, v) for v in self.values]

        if "default" not in kwargs:
            kwargs['default'] = self.values[0]

        super(EnumField, self).__init__(*args, **kwargs)

    def db_type(self, connection):
        if connection.vendor == 'sqlite' or connection.vendor == 'postgresql' or connection.vendor == 'mysql':
            return "varchar(255)"

        return "enum({0})".format( ','.join("'%s'" % v for v in self.values) )


CharIDField = partial(
    _CUIDCharIdField,
    default=cuid,
    max_length=40,
    help_text="cuid-format identifier for this entity."
)