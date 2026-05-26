from django.db import models

from ..utils.Models import SmartModel
from ..user.models import User
from ..role.models import Role


class Admin(SmartModel):

    user = models.OneToOneField(User, primary_key=True, related_name='admin', on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, related_name='admins')

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Admin: {}".format(self.user)
