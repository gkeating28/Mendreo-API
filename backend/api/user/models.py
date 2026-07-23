from django.db import models
from django.contrib.auth.models import AbstractBaseUser

from ..user.managers import UserManager

from ..utils import Constants
from ..utils.Fields import EnumField, CharIDField


class User(AbstractBaseUser):
    """This class represents the user model"""

    REQUIRED_FIELDS = ('type', 'first_name', 'last_name')
    USERNAME_FIELD = 'email'

    is_anonymous = False
    is_authenticated = True

    objects = UserManager()

    id = CharIDField(primary_key=True, prefix="usr_")
    type = EnumField(options=Constants.USER_TYPES)

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    full_name = models.CharField(max_length=255, null=True, db_index=True)

    email = models.EmailField(max_length=255, unique=True)

    password = models.CharField(max_length=255)

    verification_code = models.CharField(max_length=5, null=True)

    verification_code_sent_at = models.DateTimeField(null=True)

    status = EnumField(options=Constants.USER_STATUSES, default=Constants.USER_STATUS_DEFAULT)

    phone_country_code = models.CharField(max_length=255, null=True)
    phone_number = models.CharField(max_length=255, null=True)

    email_verified = models.BooleanField(default=False)

    last_seen = models.DateTimeField(auto_now=True)

    deleted_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "User: {}".format(self.id)

    def get_permission_key(self):
        """Return the permission key for role-based access control"""
        return "users"

    def save(self, *args, **kwargs):
        if self.first_name and self.last_name:
            self.full_name = f"{self.first_name} {self.last_name}"
        else:
            self.full_name = None
        super(User, self).save(*args, **kwargs)


