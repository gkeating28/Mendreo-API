from __future__ import annotations

from typing import Type

from django.db.models import F
from django.db import models

from ..post.models import Post

from ..consumer.models import Consumer

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField, EnumField

from ..utils import Constants


class Event(SmartModel):
    id = CharIDField(primary_key=True, prefix="evt_")

    consumer = models.ForeignKey(Consumer, related_name="events", on_delete=models.CASCADE)

    post = models.ForeignKey(Post, related_name="events", on_delete=models.CASCADE)

    type = EnumField(options=Constants.EVENT_TYPES)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Event: {}".format(self.id)

    @staticmethod
    def create_impressions(consumer: Consumer, posts_data: dict):

        Event._create_impressions(
            consumer=consumer,
            id_key="post_id",
            data=posts_data,
            model=Post
        )

    @staticmethod
    def create_view(consumer: Consumer, post: Post):

        Event._create_view(
            consumer=consumer,
            id_key="post_id",
            id_=post.id,
            model=Post
        )

    @staticmethod
    def _create_impressions(consumer: Consumer, id_key: str, data: [dict], model: Type[Post]):

        ids_ = []
        events = []

        for result in data:
            id_ = result["id"]
            ids_.append(id_)
            data = {
                id_key: id_,
                "consumer": consumer,
                "type": Constants.EVENT_TYPE_IMPRESSION
            }
            events.append(Event(**data))

        if len(events) > 0:
            Event.objects.bulk_create(events)

        model.objects.filter(id__in=ids_).update(impressions_no=F('impressions_no') + 1)

    @staticmethod
    def _create_view(consumer: Consumer, id_key: str, id_: str, model: Type[Post]):

        data = {
            id_key: id_,
            "consumer": consumer,
            "type": Constants.EVENT_TYPE_VIEW
        }

        Event.objects.create(**data)

        model.objects.filter(id=id_).update(views_no=F('views_no') + 1)
