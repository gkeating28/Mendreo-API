from __future__ import annotations

from django.db import models

from ..file.models import File
from ..image.models import Image

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField, EnumField

from ..utils import Constants
from ..user.models import User


class Post(SmartModel):
    id = CharIDField(primary_key=True, prefix="pst_")

    created_by = models.ForeignKey("api.User", related_name="posts", on_delete=models.CASCADE)

    thumbnail = models.ForeignKey(Image, related_name="posts_as_thumbnail", on_delete=models.DO_NOTHING)

    banner = models.ForeignKey(Image, related_name="posts_as_banner", on_delete=models.DO_NOTHING)

    file = models.ForeignKey(File, related_name="posts", null=True, on_delete=models.SET_NULL)

    status = EnumField(options=Constants.POST_STATUSES)

    type = EnumField(options=Constants.POST_TYPES)

    published_at = models.DateTimeField(null=True)

    title = models.CharField(max_length=255)

    subtitle = models.CharField(max_length=255)

    body = models.TextField(null=True)

    views_no = models.PositiveIntegerField(default=0)
    impressions_no = models.PositiveIntegerField(default=0)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Post: {}".format(self.id)

    @staticmethod
    def generate(post, prompt: str = ""):
        if post.type == Constants.POST_TYPE_ARTICLE:
            return Post._generate_article(post, prompt)

        raise ValueError(f"Invalid post type: {post.type}")

    @staticmethod
    def _generate_article(post, optional_extra: str = ""):
        from ..utils.AI import AI

        article_data = AI.generate_article(optional_extra)

        article_image = Image.generate(
            prompt=article_data.image_prompt,
            user=post.created_by
        )

        post.title = article_data.title
        post.subtitle = article_data.subtitle
        post.body = article_data.body
        post.status = Constants.POST_STATUS_DRAFT
        post.banner = article_image
        post.thumbnail = article_image
        post.save()

        return post
