import json
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone
from rest_framework import status

from ...message.models import Message
from ...progress.models import UserInsight
from ...session.models import Session
from ...setting.models import Setting
from ...utils import Constants
from ..TestCase import TestCase
from ..utils.manager import Auth, General


class ChatOpenerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.consumer = Auth.create_consumer()
        self.token = Auth.get_access_token(self.consumer.user)
        self.admin_token = Auth.get_platform_admin_access_token()

    def _openers(self, lines):
        row = Setting.get_or_create_chat_openers()
        row.value = json.dumps(lines)
        row.save()

    def _first_opener(self, text):
        row = Setting.get_or_create_first_chat_opener()
        row.value = text
        row.save()

    def _name(self, first_name):
        self.consumer.user.first_name = first_name
        self.consumer.user.save(update_fields=["first_name", "full_name", "updated_at"])

    def test_settings_accept_and_return_the_list(self):
        listed = self._get("/settings", access_token=self.admin_token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        self.assertEqual(listed.json["chat_openers"], Constants.DEFAULT_CHAT_OPENERS)
        self.assertEqual(listed.json["first_chat_opener"], Constants.DEFAULT_FIRST_CHAT_OPENER)

        saved = [
            "Hi {name}, one.",
            "Hi {name}, two.",
        ]
        response = self._post(
            "/settings",
            {"survey_enabled": True, "chat_openers": saved},
            access_token=self.admin_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["chat_openers"], saved)
        again = self._get("/settings", access_token=self.admin_token)
        self.assertEqual(again.json["chat_openers"], saved)

        denied = self._post(
            "/settings",
            {"survey_enabled": True, "chat_openers": []},
            access_token=self.token,
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

    def test_validation_limits(self):
        too_many = [f"Line {index}" for index in range(21)]
        too_long = "x" * 121
        cases = (
            too_many,
            [too_long],
            [""],
            ["  "],
            ["Hi {name}.", "Hi {name}."],
            [" Hi {name}. ", "Hi {name}."],
        )
        for lines in cases:
            response = self._post(
                "/settings",
                {"survey_enabled": True, "chat_openers": lines},
                access_token=self.admin_token,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, lines)
            self.assertIn("chat_openers", response.json)

        empty = self._post(
            "/settings",
            {"survey_enabled": True, "chat_openers": []},
            access_token=self.admin_token,
        )
        self.assertEqual(empty.status_code, status.HTTP_200_OK, empty.json)
        self.assertEqual(empty.json["chat_openers"], [])

    def test_a_new_general_chat_picks_from_the_list_and_does_not_repeat(self):
        self._first_opener("")
        self._name("Ada")
        self._openers(
            [
                "Hi {name}, what's on your mind right now?",
                "Good to see you, {name}. What would you like to talk about?",
            ]
        )
        rendered = [
            "Hi Ada, what's on your mind right now?",
            "Good to see you, Ada. What would you like to talk about?",
        ]
        first = self._post("/sessions", {}, access_token=self.token)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.json)
        self.assertIn(first.json["opener"], rendered)
        session = Session.objects.get(id=first.json["id"])
        self.assertEqual(session.opener, first.json["opener"])
        self.assertFalse(Message.objects.filter(session=session).exists())

        second = self._post("/sessions", {}, access_token=self.token)
        self.assertIn(second.json["opener"], rendered)
        self.assertNotEqual(second.json["opener"], first.json["opener"])

        fetched = self._get(f"/sessions/{first.json['id']}", access_token=self.token)
        self.assertEqual(fetched.status_code, status.HTTP_200_OK, fetched.json)
        self.assertEqual(fetched.json["opener"], first.json["opener"])

    def test_a_single_opener_is_reused(self):
        self._first_opener("")
        self._name("Ada")
        self._openers(["Hi {name}, what's on your mind right now?"])
        first = Session.create_general(self.consumer)
        second = Session.create_general(self.consumer)
        self.assertEqual(first.opener, "Hi Ada, what's on your mind right now?")
        self.assertEqual(second.opener, first.opener)

    def test_an_empty_list_leaves_the_opener_null(self):
        self._first_opener("")
        self._openers([])
        created = self._post("/sessions", {}, access_token=self.token)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.json)
        self.assertIsNone(created.json["opener"])
        self.assertIsNone(Session.objects.get(id=created.json["id"]).opener)

    def test_name_is_substituted_and_omitted_cleanly(self):
        self._first_opener("")
        self._name("Ada")
        self._openers(["Hi {name}, what's on your mind right now?"])
        named = Session.create_general(self.consumer)
        self.assertEqual(named.opener, "Hi Ada, what's on your mind right now?")

        self._name("")
        self._openers(["Hi {name}, what's on your mind right now?"])
        greeting = Session.create_general(self.consumer)
        self.assertEqual(greeting.opener, "Hi, what's on your mind right now?")

        self._openers(["Good to see you, {name}. What would you like to talk about?"])
        farewell = Session.create_general(self.consumer)
        self.assertEqual(
            farewell.opener,
            "Good to see you. What would you like to talk about?",
        )

    def test_exercise_reflection_and_insight_chats_get_no_opener(self):
        self._openers(["Hi {name}, what's on your mind right now?"])
        exercise = General.create_exercise()
        with patch("api.utils.AIWorkerClient.request_session_greeting"):
            exercise_session = Session.get_or_create(
                consumer=self.consumer,
                exercise=exercise,
            )
        self.assertIsNone(exercise_session.opener)

        run = Session.objects.create(
            consumer=self.consumer,
            exercise=exercise,
            completed=True,
            completed_at=timezone.now(),
            current_step_no=1,
            total_steps_no=exercise.steps_no or 1,
            run_summary={"line": "You stayed with it", "bullets": []},
        )
        reflection = self._post(
            "/sessions",
            {"runId": run.id},
            access_token=self.token,
        )
        self.assertEqual(reflection.status_code, status.HTTP_201_CREATED, reflection.json)
        self.assertIsNone(reflection.json["opener"])
        self.assertEqual(reflection.json["source_run"], run.id)

        insight = UserInsight.objects.create(
            consumer=self.consumer,
            text="You mentioned the walk. How has that been going?",
            topic_key="walk",
            generated_at=timezone.now(),
        )
        started = self._post(
            f"/progress/insights/{insight.id}/start",
            {},
            access_token=self.token,
        )
        self.assertEqual(started.status_code, status.HTTP_201_CREATED, started.json)
        self.assertIsNone(started.json["opener"])
        self.assertEqual(started.json["last_message"]["text"], insight.text)
        self.assertIsNone(Session.objects.get(id=started.json["id"]).opener)

    def test_another_users_session_does_not_leak_the_opener(self):
        self._first_opener("")
        self._name("Ada")
        self._openers(["Hi {name}, what's on your mind right now?"])
        created = self._post("/sessions", {}, access_token=self.token)
        opener = created.json["opener"]
        self.assertEqual(opener, "Hi Ada, what's on your mind right now?")

        other = Auth.create_consumer()
        other_token = Auth.get_access_token(other.user)
        hidden = self._get(f"/sessions/{created.json['id']}", access_token=other_token)
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn(opener, hidden.content.decode())

        listed = self._get("/sessions", access_token=other_token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertNotIn(created.json["id"], listed.content.decode())
        self.assertNotIn(opener, listed.content.decode())

    def test_the_first_general_chat_uses_the_special_opener(self):
        self._name("Ada")
        self._openers(
            [
                "Hi {name}, random one.",
                "Hi {name}, random two.",
            ]
        )
        first = self._post("/sessions", {}, access_token=self.token)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.json)
        self.assertEqual(
            first.json["opener"],
            "Hi Ada, what's on your mind today? Is there anything you'd like to "
            "talk about, or anything that's been worrying you?",
        )

    def test_the_second_general_chat_uses_the_random_list(self):
        self._name("Ada")
        self._openers(
            [
                "Hi {name}, random one.",
                "Hi {name}, random two.",
            ]
        )
        rendered = ["Hi Ada, random one.", "Hi Ada, random two."]
        first = Session.create_general(self.consumer)
        self.assertEqual(
            first.opener,
            "Hi Ada, what's on your mind today? Is there anything you'd like to "
            "talk about, or anything that's been worrying you?",
        )
        second = Session.create_general(self.consumer)
        self.assertIn(second.opener, rendered)

    def test_a_blank_first_opener_falls_back_to_the_random_list(self):
        self._name("Ada")
        self._openers(["Hi {name}, random one."])
        self._first_opener("   ")
        created = Session.create_general(self.consumer)
        self.assertEqual(created.opener, "Hi Ada, random one.")

        saved = self._post(
            "/settings",
            {"survey_enabled": True, "first_chat_opener": ""},
            access_token=self.admin_token,
        )
        self.assertEqual(saved.status_code, status.HTTP_200_OK, saved.json)
        self.assertEqual(saved.json["first_chat_opener"], "")
        again = self._get("/settings", access_token=self.admin_token)
        self.assertEqual(again.json["first_chat_opener"], "")

    def test_consumers_cannot_write_the_first_opener(self):
        self._first_opener("Hi {name}, keep me.")
        denied = self._post(
            "/settings",
            {"survey_enabled": True, "first_chat_opener": "Hi {name}, nope."},
            access_token=self.token,
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Setting.get_first_chat_opener(), "Hi {name}, keep me.")

        too_long = self._post(
            "/settings",
            {"survey_enabled": True, "first_chat_opener": "x" * 241},
            access_token=self.admin_token,
        )
        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("first_chat_opener", too_long.json)
