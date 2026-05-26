from django.db import models

from ..consumer.models import Consumer
from ..payment.models import Payment
from ..package.models import Package

from ..utils import DateUtils

from ..utils.Models import SmartModel


class Subscription(SmartModel):
    consumer = models.OneToOneField(Consumer, primary_key=True, related_name='subscription',  on_delete=models.CASCADE)

    payment = models.OneToOneField(Payment, related_name="subscription", null=True, on_delete=models.CASCADE)

    package = models.ForeignKey(Package, related_name="subscriptions", on_delete=models.CASCADE)

    title = models.CharField(max_length=255)

    active = models.BooleanField()

    unsubscribed_at = models.DateTimeField(null=True)

    subscribed_at = models.DateTimeField(null=True)

    last_checked_at = models.DateTimeField(null=True)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Subscription: {}".format(self.consumer)

    def save(self, *args, **kwargs):
        super(Subscription, self).save()

    @staticmethod
    def create(consumer):
        package = Package.get_default()

        data = {
            "consumer": consumer,
            "package": package,
            "title": package.title,
            "subscribed_at": DateUtils.now(),
            "active": False
        }

        return Subscription.objects.create(**data)
