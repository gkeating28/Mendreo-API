import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class NumberValidator:
    def validate(self, password, user=None):
        if not re.findall(r'\d', password):
            raise ValidationError("This password must contain at least 1 digit, 0-9.")

    def get_help_text(self):
        return _(
            "This password must contain at least 1 digit, 0-9."
        )


class UppercaseValidator:
    def validate(self, password, user=None):
        if not re.findall('[A-Z]', password):

            raise ValidationError("This password must contain at least 1 uppercase letter, A-Z.")

    def get_help_text(self):
        return _(
            "This password must contain at least 1 uppercase letter, A-Z."
        )


class LowercaseValidator:
    def validate(self, password, user=None):
        if not re.findall('[a-z]', password):
            raise ValidationError("This password must contain at least 1 lowercase letter, a-z.")

    def get_help_text(self):
        return _(
            "This password must contain at least 1 lowercase letter, a-z."
        )


class SpecialCharacterValidator:
    def validate(self, password, user=None):
        if not re.findall(r'[()[\]{}|\\`~!@#$%^&*_\-+=;:\'",<>./?]', password):
            raise ValidationError(f"The password must contain at least 1 special character: ()[]|~!@#${'^{}'}&*_-+=;:,<>./?")

    def get_help_text(self):
        return _(
            f"This password must contain at least 1 special character: ()[]|~!@#${'^{}'}&*_-+=;:,<>./?"
        )