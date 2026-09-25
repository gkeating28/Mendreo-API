from rest_framework import status

from ...question.models import Question
from ...session.models import Session, SessionMetric
from ...tests.TestCase import TestCase
from ...utils import Constants
from ..utils.manager import Auth


class FormAnswersTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)
        self.session = Session.objects.create(consumer=self.consumer)
        Question.objects.create(
            session=self.session,
            type=Constants.QUESTION_TYPE_TEXT,
            title="Which worries showed up?",
            key="worries",
            order=1,
        )
        Question.objects.create(
            session=self.session,
            type=Constants.QUESTION_TYPE_NUMBER,
            title="How disruptive?",
            key="disruptiveness",
            order=2,
        )

    def test_stores_text_without_a_metric_and_returns_form_answers(self):
        response = self._post(
            f"/sessions/{self.session.id}/form-answers",
            {"key": "worries", "value": "Health, Work"},
            access_token=self.access_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["form_answers"]["worries"], "Health, Work")
        self.session.refresh_from_db()
        self.assertEqual(self.session.form_answers["worries"], "Health, Work")
        self.assertFalse(SessionMetric.objects.filter(session=self.session).exists())

        fetched = self._get(f"/sessions/{self.session.id}", access_token=self.access_token)
        self.assertEqual(fetched.json["form_answers"]["worries"], "Health, Work")

    def test_numeric_value_inserts_a_metric_row(self):
        response = self._post(
            f"/sessions/{self.session.id}/form-answers",
            {"key": "disruptiveness", "value": "4"},
            access_token=self.access_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        metric = SessionMetric.objects.get(session=self.session, key="disruptiveness")
        self.assertEqual(float(metric.value), 4.0)
        self.assertEqual(metric.source, Constants.SESSION_METRIC_SOURCE_FORM)

    def test_unknown_key_is_rejected(self):
        response = self._post(
            f"/sessions/{self.session.id}/form-answers",
            {"key": "not-a-question", "value": "4"},
            access_token=self.access_token,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.session.refresh_from_db()
        self.assertEqual(self.session.form_answers, {})
