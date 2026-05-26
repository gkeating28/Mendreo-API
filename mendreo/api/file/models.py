from django.db import models

from ..utils import Api

from ..utils.Models import SmartModel

from ..utils.Fields import CharIDField


class File(SmartModel):
    """
    Model instance for storing a reference to a file uploaded to the platform.
    The file itself is stored on AWS S3 bucket
    """

    id = CharIDField(primary_key=True, prefix="file_")

    name = models.CharField(max_length=255)

    extension = models.CharField(max_length=50, null=True)

    content_type = models.CharField(max_length=255, null=True)

    url = models.CharField(max_length=255)

    size = models.CharField(max_length=255, null=True)

    duration = models.PositiveIntegerField(null=True)

    token = models.TextField(null=True)

    uploaded = models.BooleanField(default=False)

    created_by = models.ForeignKey("api.User", related_name="files", on_delete=models.DO_NOTHING)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "File: {}".format(self.id)

    def get_url(self):
        if self.url.startswith("http"):
            return self.url

        return "https://" + Api.AWS_CLOUD_FRONT_DOMAIN + self.url
