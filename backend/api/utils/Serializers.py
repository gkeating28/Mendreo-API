from abc import ABC

from rest_framework import serializers
from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from typing import Callable

from ..utils import Message, Exception, Constants
from ..utils.Models import SmartModel


class BaseModelSerializer(serializers.ModelSerializer):

    nested_relations = []
    nested_relation = False

    related_name = None
    foreign_key = None
    create_serializer = None
    edit_serializer = None
    model_name_in_related_object = None
    ordered = False
    create_before_model = False
    related_object_primary_key = "id"

    allow_null = False

    def __init__(self, *args, nested_relation=False, related_name: str = None, foreign_key: str = None,
                 create_serializer: type(serializers.ModelSerializer) = None,
                 edit_serializer: type(serializers.ModelSerializer) = None,
                 model_name_in_related_object: str = None, ordered: bool = True, create_before_model=False,
                 related_object_primary_key: str = "id", **kwargs):
        self.related_name = related_name
        self.foreign_key = foreign_key
        self.create_serializer = create_serializer
        self.edit_serializer = edit_serializer
        self.nested_relations = []
        self.nested_relation = nested_relation
        self.model_name_in_related_object = model_name_in_related_object
        self.ordered = ordered
        self.create_before_model = create_before_model
        self.related_object_primary_key = related_object_primary_key

        self.allow_null = kwargs.get("allow_null", False)

        super().__init__(*args, **kwargs)

        try:
            field_def = str(self).split(":\n")[0]
        except:
            field_def = "ModelSerializer"

        if nested_relation:
            error = f"keyword must be specified if 'nested_relation' is true in {field_def}"
            if not create_serializer:
                self.raise_validation_error("create_serializer", error)

            if not edit_serializer:
                self.raise_validation_error("edit_serializer", error)

            if not related_name:
                self.raise_validation_error("field_name", error)

        nested_relations = []
        for _nested_field in self.get_fields():
            many = False

            _nested_serializer_field = self.fields[_nested_field]
            if not hasattr(_nested_serializer_field, "related_name") or not _nested_serializer_field.related_name:
                # if many=True data will be in child serializer
                _nested_serializer_field = getattr(_nested_serializer_field, "child", None)
                if not hasattr(_nested_serializer_field, "related_name") or not _nested_serializer_field.related_name:
                    continue
                else:
                    many = True

            if _nested_serializer_field.nested_relation:
                nested_relations.append({
                    "foreign_key": _nested_serializer_field.foreign_key,
                    "related_name": _nested_serializer_field.related_name or _nested_serializer_field.field_name,
                    "create_serializer": _nested_serializer_field.create_serializer,
                    "edit_serializer": _nested_serializer_field.edit_serializer,
                    "many": many,
                    "allow_null": _nested_serializer_field.allow_null,
                    "model_name_in_related_object": _nested_serializer_field.model_name_in_related_object,
                    "ordered": _nested_serializer_field.ordered,
                    "create_before_model": _nested_serializer_field.create_before_model,
                    "related_object_primary_key": _nested_serializer_field.related_object_primary_key
                })

        self.nested_relations = nested_relations

    def to_internal_value(self, data):
        validated_data = super(BaseModelSerializer, self).to_internal_value(data)
        if "id" in data and self.edit_serializer:
            instance = self.Meta.model.objects.get(id=data["id"])

            # use original data to avoid double validation
            serializer = self.edit_serializer(data=data, instance=instance, partial=True)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            # inject back in the id in case edit does not include it
            if not "id" in validated_data:
                validated_data["id"] = data["id"]

            return serializer.validated_data

        return validated_data


    @classmethod
    def optimise(cls, queryset):
        return queryset.select_related(*cls.get_select_related_fields())\
                       .prefetch_related(*cls.get_prefetch_related_fields())

    def raise_validation_error(self, key=None, error=None):
        data = error

        if not error:
            raise Exception.raise_error("error is required")

        if key:
            data = dict()
            data[key] = error
        raise serializers.ValidationError(data)

    @classmethod
    def get_select_related_fields(cls):
        return []

    @classmethod
    def get_prefetch_related_fields(cls):
        return []

    def attrs_validation_methods(self) -> [Callable]:
        return []

    def nested_objects_with_foreign_key_relations(self) -> []:
        return []

    def validate_enum_field(self, key, value, options):
        if not value:
            return value

        if value not in options:
            return self.raise_validation_error(key, f"{key} needs to be one of {options}")

        return value

    def validate(self, attrs):
        for validation_method in self.attrs_validation_methods():
            attrs = validation_method(self, attrs)
        return super().validate(attrs)

    def create(self, validated_data):
        updatable_nested_relations = []
        for nested_relation in self.nested_relations:
            nested_relation["data"] = validated_data.pop(nested_relation["related_name"], None)

            if nested_relation["data"] is None and nested_relation["allow_null"] is False:
                self.raise_validation_error(nested_relation["related_name"], "was not resolvable 'create'")

            if nested_relation["create_before_model"]:
                if nested_relation["many"]:
                    self.raise_validation_error(nested_relation["related_name"], "many not supported when 'create_before_model' is True")

                serializer = nested_relation["create_serializer"](data=nested_relation["data"])
                nested_relation["data"].pop("id", None)
                related_model = serializer.create(nested_relation["data"])
                validated_data[nested_relation["related_name"]] = related_model
            else:
                updatable_nested_relations.append(nested_relation)

        model = self.handle_create(validated_data)
        self.nested_relations = updatable_nested_relations

        nested_relations = self.update_nested_relations(model)

        self.post_create(model, nested_relations)

        return model

    def update(self, model, validated_data):
        updatable_nested_relations = []
        for nested_relation in self.nested_relations:
            nested_relation["data"] = validated_data.pop(nested_relation["related_name"], None)

            if nested_relation["create_before_model"]:
                self.raise_validation_error(nested_relation["related_name"], "'create_before_model' not supported on Edit")

            if nested_relation["data"] is not None or nested_relation["allow_null"]:
                updatable_nested_relations.append(nested_relation)

        self.nested_relations = updatable_nested_relations

        model = self.handle_update(model, validated_data)

        nested_relations = self.update_nested_relations(model)

        self.post_update(model, nested_relations)

        return model

    def update_nested_relations(self, model: SmartModel) -> dict:

        nested_relations = {}
        for nested_relation in self.nested_relations:

            nested_relation_data = nested_relation["data"]
            create_serializer = nested_relation["create_serializer"]
            edit_serializer = nested_relation["edit_serializer"]
            related_name = nested_relation["related_name"]
            foreign_key = nested_relation["foreign_key"]

            if nested_relation["many"] is True:
                nested_relation = update_foreign_key_relation(
                    model=model,
                    related_objects_data=nested_relation_data,
                    model_name_in_related_object=nested_relation["model_name_in_related_object"],
                    foreign_key=foreign_key,
                    related_name=related_name,
                    related_object_create_serializer=create_serializer,
                    related_object_edit_serializer=edit_serializer,
                    ordered=nested_relation["ordered"],
                    related_object_primary_key=nested_relation.get("related_object_primary_key", "id")
                )
            else:
                nested_relation = update_one_to_one_relation(
                    model=model,
                    related_model_data=nested_relation_data,
                    related_name=related_name,
                    model_name_in_related_object=nested_relation['model_name_in_related_object'],
                    related_model_create_serializer=create_serializer,
                    related_model_edit_serializer=edit_serializer
                )

            nested_relations[related_name] = nested_relation

        return nested_relations

    def handle_create(self, validated_data):
        return super().create(validated_data)


    def post_create(self, model: SmartModel, nested_relations: dict):
        pass

    def handle_update(self, model, validated_data):
        return super().update(model, validated_data)

    def post_update(self, model: SmartModel, nested_relations: dict):
        pass

    def get_attr_value(self, attrs, key):

        value = attrs.get(key, None)
        if not value and self.instance and hasattr(self.instance, key):
            value = getattr(self.instance, key)

        return value


class BaseSerializer(serializers.Serializer):

    def optimise(self, queryset):
        return queryset.select_related(self.get_select_related_fields()) \
            .prefetch_related(self.get_prefetch_related_fields())

    def raise_validation_error(self, key=None, error=None):
        data = error

        if not error:
            raise Exception.raise_error("error is required")

        if key:
            data = dict()
            data[key] = error
        raise serializers.ValidationError(data)

    def validate_enum_field(self, key, value, options):
        if not value:
            return value

        if value not in options:
            return self.raise_validation_error(key, f"{key} needs to be one of {options}")

        return value

    @classmethod
    def get_select_related_fields(cls):
        return []

    @classmethod
    def get_prefetch_related_fields(cls):
        return []


class CreateModelSerializer(BaseModelSerializer):
    class Meta:
        pass

    def update(self, instance, validated_data):
        raise Exception.raise_error(Message.create("Create Model Serializer does not support 'update'"))


class CreateSerializer(BaseSerializer):

    def create(self, validated_data):
        pass

    def update(self, instance, validated_data):
        raise Exception.raise_error(Message.create("Create Serializer does not support 'update'"))


class EditModelSerializer(BaseModelSerializer):
    class Meta:
        pass

    def create(self, validated_data):
        raise Exception.raise_error(Message.create(f"{self.__class__} does not support 'create'"))


class EditSerializer(BaseSerializer):

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        raise Exception.raise_error(Message.create("Edit Serializer does not support 'create'"))


class ValidateSerializer(BaseSerializer):

    def create(self, validated_data):
        raise Exception.raise_error(Message.create("Validate Serializer does not support 'create'"))

    def update(self, instance, validated_data):
        raise Exception.raise_error(Message.create("Validate Serializer does not support 'update'"))


class ListSerializer(BaseSerializer):

    def create(self, validated_data):
        raise Exception.raise_error(Message.create("Validate Serializer does not support 'create'"))

    def update(self, instance, validated_data):
        raise Exception.raise_error(Message.create("Validate Serializer does not support 'update'"))


class OrderedListSerializer(serializers.ListSerializer, ABC):

    def to_representation(self, data):
        order_by = getattr(self.child, "order_by", None)

        if order_by:
            data = data.all().order_by(order_by) if isinstance(data, models.Manager) else data

        return super(OrderedListSerializer, self).to_representation(data)


class ListModelSerializer(BaseModelSerializer):

    order_by = None

    class Meta:
        list_serializer_class = OrderedListSerializer

    def __init__(self, *args, order_by=None, **kwargs):
        self.order_by = order_by
        super().__init__(*args, **kwargs)

        if self.order_by:
            self.context["order_By"] = self.order_by

        self.Meta.list_serializer_class = OrderedListSerializer

    def create(self, validated_data):
        raise Exception.raiseError(Message.create("List Model Serializer does not support 'create'"))

    def update(self, instance, validated_data):
        raise Exception.raiseError(Message.create("List Model Serializer does not support 'update'"))


class ValidateModelSerializer(BaseModelSerializer):
    class Meta:
        pass

    def create(self, validated_data):
        raise Exception.raiseError(Message.create("Validate Model Serializer does not support 'create'"))

    def update(self, instance, validated_data):
        raise Exception.raiseError(Message.create("Validate Model Serializer does not support 'update'"))


# https://github.com/encode/django-rest-framework/issues/6599
# returns the original pk instead of the object
class PrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):

    def to_internal_value(self, data):
        if self.pk_field is not None:
            data = self.pk_field.to_internal_value(data)
        try:
            self.get_queryset().get(pk=data)
        except ObjectDoesNotExist:
            self.fail('does_not_exist', pk_value=data)
        except (TypeError, ValueError):
            self.fail('incorrect_type', data_type=type(data).__name__)
        else:
            return data


def update_one_to_one_relation(model: SmartModel, related_model_data: dict, related_name: str,
                               model_name_in_related_object: str,
                               related_model_create_serializer: type(serializers.ModelSerializer),
                               related_model_edit_serializer: type(serializers.ModelSerializer)) -> SmartModel:
    """

    :param model: The model whose relation needs to be updated
    :param related_model_data: The data of the related object
    :param related_name: The name of the relation
    :param model_name_in_related_object: The name of the relation from the related object
    :param related_model_create_serializer: The serializer used to create the related model
    :param related_model_edit_serializer: The serializer used to edit the related model
    :return: related model
    """

    if related_model_data is None:
        setattr(model, related_name, None)
        model.save()
        return None

    # todo undo this comment wit ha correct fix for where and object gets created and is attached
    # if hasattr(model, related_name) and "id" in related_model_data:
    #     related_model = getattr(model, related_name)
    #     if related_model and related_model.id != related_model_data["id"]:
    #         raise Exception.raise_error(
    #             {related_name: f"This {related_name} does not belong to this object"},
    #             status_code=400
    #         )

    related_model = None
    related_model_id = None
    if hasattr(model, related_name) and getattr(model, related_name):
        related_model = getattr(model, related_name)
        if hasattr(related_model, "id"):
            related_model_id = getattr(related_model, "id")

    if related_model and ("id" not in related_model_data or related_model_id == related_model_data["id"]):
        serializer = related_model_edit_serializer(instance=related_model, data=related_model_data)
        related_model = serializer.update(related_model, related_model_data)
    else:
        field_names = []
        for field in related_model_create_serializer.Meta.model._meta.fields:
            field_names.append(field.name)

        if model_name_in_related_object in field_names:
            related_model_data[model_name_in_related_object] = model
        else:
            related_model_data.pop(model_name_in_related_object, None)

        related_model = related_model_create_serializer(data=related_model_data).create(related_model_data)
        setattr(model, related_name, related_model)
        model.save()

    return related_model


def update_foreign_key_relation(model: SmartModel, foreign_key: str,
                                related_objects_data: [dict], model_name_in_related_object: str, related_name: str,
                                related_object_create_serializer: type(serializers.ModelSerializer),
                                related_object_edit_serializer: type(serializers.ModelSerializer),
                                related_object_primary_key: str = "id",
                                ordered: bool = True, order_name: str = "order",
                                return_on_null: bool = True):
    """
    This method is a util method that updates a model's related objects. It will delete any relations not provided

    :param model: The model whose relations need to be updated
    :param related_objects_data: The data of the related objects
    :param model_name_in_related_object: The name of the model in the related object
    :param related_name: The name of the relation
    :param related_object_create_serializer: The serializer used to create the related model
    :param related_object_primary_key: The name of the primary key field in the related model
    :param related_object_edit_serializer: The serializer used to edit the related model
    :param ordered: Whether the related models are to be ordered
    :param order_name: The name of the order field in the related model
    :param return_on_null: If the method should return without updating the relation if null data is passed
    :return: An array of the related models
    """
    related_objects = []
    related_object_ids = []

    if related_objects_data is None:
        if return_on_null:
            return related_objects

        related_objects_data = []

    for related_object_data in related_objects_data:
        if related_object_primary_key in related_object_data:
            related_object_ids.append(related_object_data[related_object_primary_key])

    related_field_name = foreign_key or related_name
    if hasattr(model, related_field_name):
        getattr(model, related_field_name).exclude(**{f"{related_object_primary_key}__in": related_object_ids}).delete()
        related_object_no = getattr(model, related_field_name).filter(**{f"{related_object_primary_key}__in": related_object_ids}).count()
        if related_object_no != len(related_object_ids):
            raise Exception.raise_error(
                {related_name: f"One or more {related_name} does not belong to this {model_name_in_related_object}"},
                status_code=400
            )

    for index, related_object_data in enumerate(related_objects_data, start=0):
        if ordered:
            related_object_data[order_name] = index

        related_object_data[model_name_in_related_object] = model
        related_object_data["deleted_at"] = None

        if related_object_primary_key in related_object_data:
            pk = related_object_data[related_object_primary_key]
            related_object_model = related_object_create_serializer.Meta.model
            related_object = related_object_model.objects.get(**{related_object_primary_key: pk})
            serializer = related_object_edit_serializer(data=related_object_data, instance=related_object)
            related_object = serializer.update(related_object, related_object_data)
        else:
            serializer = related_object_create_serializer(data=related_object_data)
            related_object = serializer.create(related_object_data)

        related_objects.append(related_object)

    return related_objects
