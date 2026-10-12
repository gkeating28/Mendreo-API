import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from api.consent.access import has_current_consent
from api.consent.models import ConsumerConsent, ConsumerMarketingOptIn
from api.consent.services import save_consent, validate_consent_payload
from api.consent.views import Consent
from api.consumer.serializers import ConsumerListSerializer
from api.consumer.views import Detail as ConsumerDetail
from api.exercise.views import ListCreate as ExerciseListCreate
from api.message.views import ListCreate as MessageListCreate
from api.progress.views import Mood as ProgressMood
from api.session.views import Today as SessionToday
from api.user.views import Info, Login, Logout, Settings, VerifyEmail
from api.utils.Constants import (
    CONSENT_ERROR_AGE,
    CONSENT_ERROR_LIMITATIONS,
    CONSENT_ERROR_VERSION,
    CONSENT_VERSION,
    USER_TYPE_ADMIN,
    USER_TYPE_CONSUMER,
)


def _json_request(factory_request):
    return Request(factory_request, parsers=[JSONParser()])


def _rendered(response):
    if hasattr(response, "render"):
        response.render()
    return response


def _user(user_type=USER_TYPE_CONSUMER):
    user = Mock()
    user.is_anonymous = False
    user.is_authenticated = True
    user.type = user_type
    user.consumer = Mock(name="consumer")
    return user


def _call(view_cls, path, user, consented, method="get", view_kwargs=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, {}, format="json")

    def _auth(view_self, req):
        req.user = user

    with patch.object(APIView, "perform_authentication", _auth), \
            patch("api.consent.access.has_current_consent", return_value=consented), \
            patch.object(view_cls, method, return_value=_ok()):
        return _rendered(view_cls.as_view()(request, **(view_kwargs or {})))


def _ok():
    from rest_framework.response import Response
    return Response({"ok": True}, status=200)


class ConsentPayloadTests(SimpleTestCase):

    def test_each_missing_rule_and_a_stale_version_are_all_returned(self):
        errors = validate_consent_payload({
            "version": "0",
            "age_confirmed": False,
            "limitations_acknowledged": False,
            "marketing_opt_in": True,
        })

        self.assertEqual(errors, [
            CONSENT_ERROR_AGE,
            CONSENT_ERROR_LIMITATIONS,
            CONSENT_ERROR_VERSION,
        ])

    def test_rejected_payload_writes_nothing_and_sends_no_mail(self):
        factory = APIRequestFactory()
        django_request = factory.post("/user/consent", {
            "version": CONSENT_VERSION,
            "age_confirmed": True,
            "limitations_acknowledged": False,
        }, format="json")
        request = _json_request(django_request)
        request.user = _user()
        view = Consent()

        with patch("api.consent.views.save_consent") as save, \
                patch("api.tasks.send_mail") as mail:
            response = view.post(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], [CONSENT_ERROR_LIMITATIONS])
        save.assert_not_called()
        mail.delay.assert_not_called()
        mail.delay_on_commit.assert_not_called()

    def test_unticked_marketing_is_stored_separately_and_does_not_grant_access(self):
        consumer = Mock(name="consumer")
        with patch.object(ConsumerConsent.objects, "update_or_create") as consent_save, \
                patch.object(ConsumerMarketingOptIn.objects, "update_or_create") as marketing_save, \
                patch("api.tasks.send_mail") as mail:
            opted_in = save_consent(consumer, {
                "version": CONSENT_VERSION,
                "age_confirmed": True,
                "limitations_acknowledged": True,
                "marketing_opt_in": False,
            })

        self.assertFalse(opted_in)
        consent_save.assert_called_once()
        self.assertEqual(consent_save.call_args.kwargs["consumer"], consumer)
        self.assertEqual(consent_save.call_args.kwargs["version"], CONSENT_VERSION)
        self.assertTrue(consent_save.call_args.kwargs["defaults"]["age_confirmed"])
        self.assertIsNotNone(consent_save.call_args.kwargs["defaults"]["age_confirmed_at"])
        marketing_save.assert_called_once()
        self.assertFalse(marketing_save.call_args.kwargs["defaults"]["opted_in"])
        self.assertIsNone(marketing_save.call_args.kwargs["defaults"]["opted_in_at"])
        mail.delay.assert_not_called()

    def test_ticked_marketing_stores_a_timestamp_and_is_not_the_access_check(self):
        consumer = Mock(name="consumer")
        with patch.object(ConsumerConsent.objects, "update_or_create"), \
                patch.object(ConsumerMarketingOptIn.objects, "update_or_create") as marketing_save:
            opted_in = save_consent(consumer, {
                "version": CONSENT_VERSION,
                "age_confirmed": True,
                "limitations_acknowledged": True,
                "marketing_opt_in": True,
            })

        self.assertTrue(opted_in)
        self.assertTrue(marketing_save.call_args.kwargs["defaults"]["opted_in"])
        self.assertIsNotNone(marketing_save.call_args.kwargs["defaults"]["opted_in_at"])

        queryset = Mock()
        queryset.exists.return_value = True
        with patch.object(ConsumerConsent.objects, "filter", return_value=queryset) as consent_filter, \
                patch.object(ConsumerMarketingOptIn.objects, "filter") as marketing_filter:
            self.assertTrue(has_current_consent(consumer))
        consent_filter.assert_called_once()
        marketing_filter.assert_not_called()

    def test_current_consent_requires_the_api_version(self):
        consumer = Mock(name="consumer")
        queryset = Mock()
        queryset.exists.return_value = False
        with patch.object(ConsumerConsent.objects, "filter", return_value=queryset) as consent_filter:
            self.assertFalse(has_current_consent(consumer))
        self.assertEqual(consent_filter.call_args.kwargs["version"], CONSENT_VERSION)

        queryset.exists.return_value = True
        with patch("api.consent.access.CONSENT_VERSION", "2"), \
                patch.object(ConsumerConsent.objects, "filter", return_value=queryset) as consent_filter:
            self.assertTrue(has_current_consent(consumer))
        self.assertEqual(consent_filter.call_args.kwargs["version"], "2")


class ConsentFlagTests(SimpleTestCase):

    def test_missing_record_requires_consent_even_when_already_onboarded(self):
        consumer = Mock()
        consumer.onboarded = True
        consumer.date_of_birth = "1990-01-01"
        consumer.user.email_verified = True
        with patch("api.consent.access.has_current_consent", return_value=False):
            self.assertTrue(ConsumerListSerializer().get_consent_required(consumer))
        self.assertTrue(consumer.onboarded)

    def test_social_shaped_account_without_a_record_still_requires_consent(self):
        """The gate does not look at email verification or date of birth."""
        consumer = Mock()
        consumer.onboarded = False
        consumer.date_of_birth = None
        consumer.user.email_verified = True
        with patch("api.consent.access.has_current_consent", return_value=False):
            self.assertTrue(ConsumerListSerializer().get_consent_required(consumer))

    def test_accepted_current_version_clears_the_flag(self):
        consumer = Mock()
        consumer.onboarded = False
        with patch("api.consent.access.has_current_consent", return_value=True):
            self.assertFalse(ConsumerListSerializer().get_consent_required(consumer))


class ConsentEndpointTests(SimpleTestCase):

    def test_get_returns_the_current_text_and_an_unticked_marketing_default(self):
        user = _user()
        factory = APIRequestFactory()
        django_request = factory.get("/user/consent")
        request = _json_request(django_request)
        request.user = user
        view = Consent()
        view.request = request

        with patch("api.consent.views.has_current_consent", return_value=False):
            response = view.get(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], CONSENT_VERSION)
        self.assertFalse(response.data["marketing_opt_in_default"])
        self.assertTrue(response.data["consent_required"])
        self.assertIn("18 or over", response.data["statements"]["age_confirmed"])
        self.assertIn("limitations", response.data["statements"]["limitations_acknowledged"])
        self.assertIn("emails from Mendreo", response.data["statements"]["marketing_opt_in"])

    def test_post_of_the_current_version_clears_consent_required(self):
        user = _user()
        factory = APIRequestFactory()
        django_request = factory.post("/user/consent", {
            "version": CONSENT_VERSION,
            "age_confirmed": True,
            "limitations_acknowledged": True,
            "marketing_opt_in": False,
        }, format="json")
        request = _json_request(django_request)
        request.user = user
        view = Consent()
        view.request = request

        with patch("api.consent.views.save_consent", return_value=False) as save, \
                patch("api.tasks.send_mail") as mail:
            response = view.post(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["consent_required"])
        self.assertFalse(response.data["marketing_opt_in"])
        save.assert_called_once()
        mail.delay.assert_not_called()


class ConsentGateTests(SimpleTestCase):

    def setUp(self):
        self.user = _user()

    def test_product_endpoints_reject_a_consumer_with_no_current_consent(self):
        cases = [
            (SessionToday, "/sessions/today", "get", None),
            (MessageListCreate, "/messages", "get", None),
            (ExerciseListCreate, "/exercises", "get", None),
            (ProgressMood, "/progress/mood", "get", None),
            (ConsumerDetail, "/consumers/usr_test", "patch", {"id": "usr_test"}),
            (Settings, "/user/settings", "get", None),
        ]
        for view_cls, path, method, view_kwargs in cases:
            response = _call(
                view_cls,
                path,
                self.user,
                consented=False,
                method=method,
                view_kwargs=view_kwargs,
            )
            body = json.loads(response.content)
            self.assertEqual(response.status_code, 403, view_cls)
            self.assertEqual(body, {"detail": "consent_required"}, view_cls)

    def test_a_consumer_who_has_accepted_is_not_blocked(self):
        response = _call(SessionToday, "/sessions/today", self.user, consented=True)
        self.assertEqual(response.status_code, 200)

    def test_login_verify_email_info_and_consent_stay_open(self):
        for view_cls, path, method in (
            (Login, "/user/login", "post"),
            (VerifyEmail, "/user/verify-email", "post"),
            (Logout, "/user/logout", "post"),
            (Consent, "/user/consent", "get"),
            (Info, "/user/info", "get"),
        ):
            response = _call(view_cls, path, self.user, consented=False, method=method)
            self.assertEqual(response.status_code, 200, view_cls)

    def test_admins_are_not_asked_for_consumer_consent(self):
        response = _call(
            MessageListCreate,
            "/messages",
            _user(USER_TYPE_ADMIN),
            consented=False,
        )
        self.assertEqual(response.status_code, 200)
