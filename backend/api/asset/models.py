from django.db import models

from ..post.models import Post
from ..file.models import File
from ..image.models import Image

from ..tag.models import Tag

from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class Asset(SmartModel):

    id = CharIDField(primary_key=True, prefix="ast_")

    post = models.ForeignKey(Post, related_name="assets", null=True, on_delete=models.CASCADE)
    file = models.ForeignKey(File, related_name="assets", null=True, on_delete=models.CASCADE)
    image = models.ForeignKey(Image, related_name="assets", null=True, on_delete=models.CASCADE)

    context = models.TextField()

    tags = models.ManyToManyField(Tag, related_name="assets", blank=True)

    def __str__(self):
        return f"Asset: ({self.id})"

    def get_permission_key(self):
        """Return the permission key for role-based access control"""
        return "assets"
