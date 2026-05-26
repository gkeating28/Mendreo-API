"""
Utility function for cloning model instances with their related fields.
"""
from django.db.models import ManyToOneRel, OneToOneRel
from django.db.models.fields import PositiveIntegerField, BooleanField
from copy import deepcopy


def instance(original_instance, exclude_fields=None):
    """
    Clone a Django model instance, including related OneToOne, ForeignKey, and ManyToMany relationships.

    Args:
        original_instance: The model instance to clone
        exclude_fields: List of field names to exclude from cloning

    Returns:
        A new cloned instance with all related objects
    """
    if exclude_fields is None:
        exclude_fields = []

    instance_copy = deepcopy(original_instance)
    instance_copy.id = None

    instance_copy.save()

    for field in original_instance._meta.get_fields():

        if field.name in exclude_fields:
            if not getattr(field, "field", None):

                if isinstance(field, PositiveIntegerField):
                    setattr(instance_copy, field.name, 0)

                elif isinstance(field, BooleanField):
                    setattr(instance_copy, field.name, False)

                else:
                    setattr(instance_copy, field.name, None)

            continue

        related_instance = getattr(original_instance, field.name, None)

        if not related_instance:
            continue

        related_instance_copy = deepcopy(related_instance)

        if isinstance(field, OneToOneRel):

            related_instance_copy.id = None

            setattr(related_instance_copy,
                    field.remote_field.name, instance_copy)

            related_instance_copy.save()

            copy_many_to_many_fields(related_instance, related_instance_copy)

        elif isinstance(field, ManyToOneRel):

            for related_object in related_instance.all():

                related_object_copy = deepcopy(related_object)

                related_object_copy.id = None

                setattr(related_object_copy,
                        field.remote_field.name, instance_copy)

                related_object_copy.save()

                copy_many_to_many_fields(related_object, related_object_copy)

    copy_many_to_many_fields(original_instance, instance_copy)

    return instance_copy


def copy_many_to_many_fields(original_instance, copied_instance):
    """
    Copy all many-to-many field values from original instance to copied instance.

    Args:
        original_instance: The original model instance
        copied_instance: The copied model instance

    Returns:
        The copied instance with many-to-many fields set
    """
    for field in original_instance._meta.many_to_many:

        related_manager = getattr(original_instance, field.name)

        related_manager_copy = getattr(copied_instance, field.name)

        old_values = related_manager.all()

        related_manager_copy.set(old_values)

    return copied_instance
