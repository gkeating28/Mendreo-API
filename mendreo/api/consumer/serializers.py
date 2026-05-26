import datetime

from rest_framework import serializers

from .models import Consumer, Agent

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)

from ..user.serializers import (
    UserMinSerializer,
    UserEditSerializer,
    UserListSerializer,
    UserAdminListSerializer,
    UserAdminEditSerializer,
    UserConsumerCreateSerializer,
    UserConsumerSocialCreateSerializer,
)

from ..summary.models import Summary
from ..subscription.serializers import Subscription, SubscriptionDetailSerializer, SubscriptionAdminDetailSerializer

from ..agent.serializers import AgentListSerializer

from ..utils import Constants

from ..tasks import send_mail


class ConsumerCreateSerializer(CreateModelSerializer):
    date_of_birth = serializers.DateField()

    user = UserConsumerCreateSerializer(
        nested_relation=True,
        related_name="user",
        create_before_model=True,
        model_name_in_related_object="user",
        edit_serializer=UserEditSerializer,
        create_serializer=UserConsumerCreateSerializer
    )

    class Meta:
        model = Consumer
        fields = [
            "user",
            "date_of_birth",
        ]

    def validate_date_of_birth(self, date_of_birth):
        return dob_validation(self, date_of_birth)

    def validate(self, attrs):

        attrs["agent"] = Agent.get_default()

        return attrs

    def post_create(self, consumer, nested_relations):

        Summary.get_or_create(consumer)
        Subscription.create(consumer)

        if not consumer.user.email_verified:
            send_mail.delay_on_commit("send_account_verification_code", consumer.user_id)

        return consumer


# remove date of birth requirement along with first / last name and email on user
class ConsumerSocialCreateSerializer(ConsumerCreateSerializer):

    user = UserConsumerSocialCreateSerializer(
        nested_relation=True,
        related_name="user",
        create_before_model=True,
        model_name_in_related_object="user",
        edit_serializer=UserEditSerializer,
        create_serializer=UserConsumerSocialCreateSerializer
    )

    class Meta(ConsumerCreateSerializer.Meta):
        # remove date of birth requirement
        fields = [
            "user",
        ]


class ConsumerEditSerializer(EditModelSerializer):
    user = UserEditSerializer(
        nested_relation=True,
        required=False,
        related_name="user",
        model_name_in_related_object="user",
        edit_serializer=UserEditSerializer,
        create_serializer=UserConsumerCreateSerializer
    )

    class Meta:
        model = Consumer
        fields = [
            "user",
            "date_of_birth"
        ]

    def validate_date_of_birth(self, date_of_birth):
        return dob_validation(self, date_of_birth)

    def post_update(self, consumer, nested_relations: dict):
        consumer.update_onboarding_status()
        consumer.update_surveyed_status()


class ConsumerAdminEditSerializer(ConsumerEditSerializer):
    user = UserAdminEditSerializer(
        required=False,
        related_name="user",
        model_name_in_related_object="user",
        edit_serializer=UserAdminEditSerializer
    )


class ConsumerListSerializer(ListModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = Consumer
        fields = [
            "user",
            "onboarded",
            "date_of_birth"
        ]

    def get_user(self, obj):
        serializer = UserListSerializer(obj.user, context=self.context)
        return serializer.data

    @classmethod
    def get_select_related_fields(cls):
        return ["user"]


class ConsumerDetailSerializer(ConsumerListSerializer):

    agent = AgentListSerializer()
    subscription = SubscriptionDetailSerializer()

    class Meta(ConsumerListSerializer.Meta):
        ConsumerListSerializer.Meta.fields += [
            "agent",
            "subscription"
        ]

    @classmethod
    def get_select_related_fields(cls):
        return ["user", "agent", "subscription__payment__price"]


class ConsumerAdminListSerializer(ConsumerDetailSerializer):
    user = UserAdminListSerializer()


class ConsumerAdminDetailSerializer(ConsumerAdminListSerializer):

    subscription = SubscriptionAdminDetailSerializer()


    @classmethod
    def get_select_related_fields(cls):
        return ["user", "agent", "subscription__payment__price__currency"]


def dob_validation(serializer, date_of_birth):
    if not date_of_birth:
        return date_of_birth

    today = datetime.datetime.today()
    threshold = datetime.date(today.year - Constants.CONSUMER_MINIMUM_AGE, date_of_birth.month, date_of_birth.day)

    if date_of_birth > threshold:
        raise serializer.raise_validation_error(
            "date_of_birth", f"must be at least {Constants.CONSUMER_MINIMUM_AGE}"
        )

    return date_of_birth


class ConsumerMinSerializer(ConsumerListSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = Consumer
        fields = ['user']

