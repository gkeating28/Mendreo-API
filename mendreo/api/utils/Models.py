from django.db import models
from django.db.models import QuerySet
from django.utils import timezone

from django.core.exceptions import MultipleObjectsReturned
from django.db.utils import IntegrityError

import logging, os


class SoftDeletionManager(models.Manager):
    def __init__(self, *args, **kwargs):
        self.alive_only = kwargs.pop('alive_only', True)
        super(SoftDeletionManager, self).__init__(*args, **kwargs)

    def get_queryset(self):
        if self.alive_only:
            return SoftDeletionQuerySet(self.model).filter(deleted_at=None)
        return SoftDeletionQuerySet(self.model)

    def hard_delete(self):
        return self.get_queryset().hard_delete()

    # if get_or_create fails due to an existing object, first try to get
    # https://groups.google.com/g/django-developers/c/lzD0AFvwi2c/m/iB6FKObfl8wJ
    def get_or_create(self, **kwargs):
        try:
            return super(SoftDeletionManager, self).get_or_create(**kwargs)
        except IntegrityError:
            try:
                return self.get(**kwargs)
            except MultipleObjectsReturned:
                kwargs.pop("defaults", None)
                return super(SoftDeletionManager, self).filter(**kwargs).first(), False
        except MultipleObjectsReturned as e:
            kwargs.pop("defaults", None)
            first = super(SoftDeletionManager, self).filter(**kwargs).first()

            if not os.environ["GENERAL_DEBUG"] == "True":
                warning = f"Warning: {self} get_or_create returned multiple objects matching: {kwargs}, " \
                          f"with error: {e}, will fallback to first match: {first}"

                print(f"\033[93m{warning}\x1b[0m")
                logging.warning(warning)

            return first, False


class SoftDeletionQuerySet(QuerySet):
    def delete(self):
        return super(SoftDeletionQuerySet, self).update(deleted_at=timezone.now())

    def hard_delete(self):
        return super(SoftDeletionQuerySet, self).delete()

    def alive(self):
        return self.filter(deleted_at=None)

    def dead(self):
        return self.exclude(deleted_at=None)


class SmartModel(models.Model):
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = SoftDeletionManager()
    all_objects = SoftDeletionManager(alive_only=False)

    class Meta:
        abstract = True

    def delete(self):
        self.deleted_at = timezone.now()
        self.save()

    def hard_delete(self):
        super(SmartModel, self).delete()

    def id_prefix(self):
        return ""

    def get_create_serializer(self):
        pass

    def get_edit_serializer(self):
        pass

    def get_validate_serializer(self):
        pass