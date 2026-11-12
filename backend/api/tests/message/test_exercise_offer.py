from contextlib import contextmanager
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from pydantic_ai.exceptions import ModelRetry
from rest_framework import status

from ...exercise.models import Exercise
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session
from ...tests.TestCase import TestCase
from ...utils import Constants
from ...agent.models import Agent as PersistAgent
from ...utils.Agent import (
    Dependencies,
    GeneralResponse,
    _BLANK_REPLY_FALLBACK,
    _BLANK_REPLY_HINT,
    _OFFER_RETRY_HINT,
    _prepare_prompt,
    _register_get_exercise,
    _register_tools,
)
from ...utils.ExerciseOffer import (
    _resolve_offer,
    declined_offer_text,
    format_agent_offer,
    note_unresolved_typed_decline,
    offer_decline_hint,
)
from ..utils import Data
from ..utils.manager import Auth, General


class ExerciseOfferTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)
        self.exercise = General.create_exercise()
        self.exercise.status = Constants.EXERCISE_STATUS_PUBLISHED
        self.exercise.save(update_fields=["status"])
        self.session = General.create_session(consumer=self.consumer)

    def _agent_participant(self):
        return Participant.objects.filter(
            session=self.session,
            agent=self.consumer.agent,
        ).first()

    def _consumer_participant(self):
        return Participant.objects.filter(
            session=self.session,
            consumer=self.consumer,
        ).first()

    def _create_offer(self, suggested_responses=None):
        if suggested_responses is None:
            suggested_responses = list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES)
        return Message.objects.create(
            session=self.session,
            sender=self._agent_participant(),
            text=f"Would you like to start {self.exercise.title}?",
            exercise=self.exercise,
            suggested_responses=suggested_responses,
            suggested_responses_kind=Constants.SUGGESTED_RESPONSES_KIND_OFFER,
            reasoning="triage",
        )

    def _post_message(self, text, from_suggested_response=None, session=None):
        data = Data.valid_message_data(text=text, session=session or self.session)
        if from_suggested_response is not None:
            data["from_suggested_response"] = from_suggested_response
        return self._post("/messages", data, access_token=self.access_token)

    def _get_exercise_tool(self):
        captured = {}

        class _Recorder:
            def tool(self, func=None, **kwargs):
                def register(fn):
                    captured[fn.__name__] = fn
                    return fn

                if func is None:
                    return register
                return register(func)

        _register_get_exercise(_Recorder())
        return captured["get_exercise"]

    def _tool_names(self, session):
        names = []

        class _Recorder:
            def tool(self, func=None, **kwargs):
                def register(fn):
                    names.append(fn.__name__)
                    return fn

                if func is None:
                    return register
                return register(func)

        _register_tools(_Recorder(), session)
        return names

    def _linked_chat(self):
        run = Session.objects.create(
            consumer=self.consumer,
            exercise=self.exercise,
            completed=True,
            completed_at=timezone.now(),
            current_step_no=1,
            total_steps_no=self.exercise.steps_no or 1,
            run_summary={"line": "You stayed with it", "bullets": ["The worry shrank"]},
        )
        chat = General.create_session(consumer=self.consumer)
        chat.source_run = run
        chat.save(update_fields=["source_run", "updated_at"])
        return chat

    def test_unknown_exercise_id_raises_model_retry(self):
        draft = Exercise.objects.create(
            title="Draft only",
            subtitle="Draft",
            description="Not published.",
            steps_no=1,
            icon="leaf",
            icon_background_color="tan",
            status=Constants.EXERCISE_STATUS_DRAFT,
        )
        snapshot = Exercise.objects.create(
            title="Snapshot",
            subtitle="Snapshot",
            description="Hidden copy.",
            steps_no=1,
            icon="leaf",
            icon_background_color="tan",
            status=Constants.EXERCISE_STATUS_PUBLISHED,
            authoring_snapshot=True,
        )
        deps = Dependencies(session=self.session, consumer=self.consumer, exercise=None)
        ctx = mock.Mock()
        ctx.deps = deps

        with self.assertRaises(ModelRetry) as raised:
            self._get_exercise_tool()(ctx, "exrcs_missing")

        self.assertIsNone(deps.matched_exercise)
        message = str(raised.exception)
        self.assertIn(self.exercise.id, message)
        self.assertIn(self.exercise.title, message)
        self.assertNotIn(draft.id, message)
        self.assertNotIn(snapshot.id, message)

    def test_published_exercise_id_returns_ok(self):
        deps = Dependencies(session=self.session, consumer=self.consumer, exercise=None)
        ctx = mock.Mock()
        ctx.deps = deps

        result = self._get_exercise_tool()(ctx, self.exercise.id)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["exercise_id"], self.exercise.id)
        self.assertEqual(deps.matched_exercise, self.exercise)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_offer_message_includes_yes_no_chips(self):
        mocked = GeneralResponse(
            text="There's an exercise that fits.",
            reasoning="Unified Protocol",
            suggested_responses=["Tell me more"],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, self.exercise
            response = self._post_message("I've been stuck in the same thought loop")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json["suggested_responses"],
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )
        self.assertIn("Would you like to start an exercise? Yes or no.", response.json["text"])
        self.assertIn(self.exercise.title, response.json["text"])
        self.assertEqual(response.json["exercise"]["id"], self.exercise.id)
        self.assertIsNone(response.json["exercise_session"])
        self.session.refresh_from_db()
        self.assertIsNone(self.session.exercise_id)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_ordinary_general_chat_still_gets_the_tool_and_the_appended_offer(self):
        self.assertIn("get_exercise", self._tool_names(self.session))
        mocked = GeneralResponse(
            text="There's an exercise that fits.",
            reasoning="Unified Protocol",
            suggested_responses=["Tell me more"],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, self.exercise
            response = self._post_message("I've been stuck in the same thought loop")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("Would you like to start an exercise? Yes or no.", response.json["text"])
        self.assertEqual(
            response.json["suggested_responses"],
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_linked_finished_run_does_not_get_the_tool_or_the_appended_offer(self):
        chat = self._linked_chat()
        self.assertNotIn("get_exercise", self._tool_names(chat))
        mocked = GeneralResponse(
            text="There's an exercise that fits.",
            reasoning="Unified Protocol",
            suggested_responses=["Tell me more"],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, self.exercise
            response = self._post_message(
                "I've been stuck in the same thought loop",
                session=chat,
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json["text"], "There's an exercise that fits.")
        self.assertNotIn("Would you like to start an exercise?", response.json["text"])
        self.assertNotEqual(
            response.json["suggested_responses"],
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_offer_keeps_lets_work_through_copy_and_only_adds_chips(self):
        mocked = GeneralResponse(
            text=f"Let's work through '{self.exercise.title}'. Tap below to start when you're ready.",
            reasoning="Unified Protocol",
            suggested_responses=["Tell me more"],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, self.exercise
            response = self._post_message(f"Try '{self.exercise.title}'")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json["suggested_responses"],
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )
        self.assertIn("Let's work through", response.json["text"])
        self.assertNotIn(
            "There's an exercise that fits what you're describing",
            response.json["text"],
        )
        self.assertEqual(response.json["exercise"]["id"], self.exercise.id)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_offer_keeps_begin_this_exercise_copy_and_only_adds_chips(self):
        mocked = GeneralResponse(
            text=(
                f"{self.exercise.title} is designed to help break the cycle of anxiety. "
                "Would you like to begin this exercise now?"
            ),
            reasoning="Unified Protocol",
            suggested_responses=["Tell me more"],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, self.exercise
            response = self._post_message("I've been worrying a lot")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json["suggested_responses"],
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )
        self.assertIn("Would you like to begin this exercise now?", response.json["text"])
        self.assertNotIn(
            "There's an exercise that fits what you're describing",
            response.json["text"],
        )
        self.assertEqual(response.json["exercise"]["id"], self.exercise.id)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_yes_chip_saves_message_only_and_does_not_start_session(self):
        offer = self._create_offer()

        with mock.patch("api.message.views.request_agent_response") as ai:
            response = self._post_message("Yes", from_suggested_response=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ai.assert_not_called()
        self.assertEqual(response.json["text"], "Yes")
        self.assertIsNotNone(response.json["sender"]["consumer"])
        self.assertIsNone(response.json["sender"]["agent"])

        offer.refresh_from_db()
        self.assertEqual(offer.suggested_responses, [])

        self.assertFalse(
            Session.objects.filter(
                consumer=self.consumer,
                exercise=self.exercise,
            ).exists()
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.last_message_id, response.json["id"])

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_typed_yes_is_normal_chat(self):
        offer = self._create_offer()
        mocked = GeneralResponse(
            text="I'm here — take your time.",
            reasoning="continue",
            suggested_responses=[],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            response = self._post_message("Yes")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json["text"], "I'm here — take your time.")
        self.assertIsNotNone(response.json["sender"]["agent"])

        offer.refresh_from_db()
        self.assertEqual(
            offer.suggested_responses,
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )
        self.assertFalse(
            Session.objects.filter(
                consumer=self.consumer,
                exercise=self.exercise,
            ).exists()
        )

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_no_chip_clears_pills_and_keeps_saved_offer(self):
        offer = self._create_offer()

        with self._scripted_posts(["We'll leave that there."]):
            response = self._post_message("No", from_suggested_response=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json["text"], "We'll leave that there.")
        self.assertNotIn("Tap the card", response.json["text"])
        self.assertIsNotNone(response.json["sender"]["agent"])

        offer.refresh_from_db()
        self.assertEqual(offer.suggested_responses, [])
        self.assertEqual(offer.exercise_id, self.exercise.id)
        self.assertFalse(
            Session.objects.filter(
                consumer=self.consumer,
                exercise=self.exercise,
            ).exists()
        )

        listed = self._get(
            f"/messages?session_id={self.session.id}&order_by=created_at",
            access_token=self.access_token,
        )
        offer_payload = next(
            row for row in listed.json["results"] if row["id"] == offer.id
        )
        self.assertEqual(offer_payload["exercise"]["id"], self.exercise.id)
        self.assertEqual(offer_payload["suggested_responses"], [])
        self.assertIsNone(offer_payload["exercise_session"])

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_sheet_decline_after_yes_does_not_start_session(self):
        offer = self._create_offer()
        self._post_message("Yes", from_suggested_response=True)

        with self._scripted_posts(["We'll leave that there."]):
            response = self._post_message("No", from_suggested_response=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json["text"], "We'll leave that there.")
        offer.refresh_from_db()
        self.assertEqual(offer.exercise_id, self.exercise.id)
        self.assertFalse(
            Session.objects.filter(
                consumer=self.consumer,
                exercise=self.exercise,
            ).exists()
        )

    def test_exercise_session_payload_reuses_paused_and_completed(self):
        offer = self._create_offer(suggested_responses=[])

        exercise_session = Session.objects.create(
            consumer=self.consumer,
            exercise=self.exercise,
            completed=False,
            current_step_no=2,
            total_steps_no=self.exercise.steps_no,
        )

        listed = self._get(
            f"/messages?session_id={self.session.id}&order_by=created_at",
            access_token=self.access_token,
        )
        offer_payload = next(
            row for row in listed.json["results"] if row["id"] == offer.id
        )
        self.assertEqual(offer_payload["exercise_session"]["id"], exercise_session.id)
        self.assertFalse(offer_payload["exercise_session"]["completed"])

        exercise_session.completed = True
        exercise_session.save(update_fields=["completed"])

        listed = self._get(
            f"/messages?session_id={self.session.id}&order_by=created_at",
            access_token=self.access_token,
        )
        offer_payload = next(
            row for row in listed.json["results"] if row["id"] == offer.id
        )
        self.assertTrue(offer_payload["exercise_session"]["completed"])
        self.assertEqual(offer_payload["exercise_session"]["id"], exercise_session.id)

    def test_offer_wording_keeps_the_real_title_only(self):
        named = GeneralResponse(
            text=f"Arr, {self.exercise.title} might help. Shall we?",
            reasoning="offer",
            suggested_responses=["Tell me more"],
        )
        chips, text = format_agent_offer(named, self.exercise, self.session)
        self.assertEqual(chips, list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES))
        self.assertEqual(text, named.text)

        wrong = GeneralResponse(
            text="Let's try the Pirate Breathing Drill.",
            reasoning="offer",
            suggested_responses=["Tell me more"],
        )
        chips, text = format_agent_offer(wrong, self.exercise, self.session)
        self.assertEqual(chips, list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES))
        self.assertEqual(
            text,
            (
                f"There's an exercise that fits what you're describing: {self.exercise.title}. "
                "Would you like to start an exercise? Yes or no."
            ),
        )
        self.assertNotIn("Pirate Breathing Drill", text)

        finished = self._linked_chat()
        chips, text = format_agent_offer(wrong, self.exercise, finished)
        self.assertEqual(text, wrong.text)
        self.assertNotIn("Would you like to start an exercise?", text)
        self.assertNotEqual(chips, list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES))

    def test_decline_stays_in_the_prompt_for_six_user_turns(self):
        offer = self._create_offer()
        self.session.consumer_messages_no = 3
        self.session.save(update_fields=["consumer_messages_no", "updated_at"])
        user_message = Message.objects.create(
            session=self.session,
            sender=self._consumer_participant(),
            text="No",
        )
        _resolve_offer(user_message, offer, Constants.EXERCISE_OFFER_NO)

        self.session.refresh_from_db()
        stored = self.session.cached_prompt_meta["exercise_offers"][-1]
        self.assertEqual(stored["outcome"], "declined")
        self.assertEqual(stored["exercise_id"], self.exercise.id)
        self.assertEqual(stored["title"], self.exercise.title)
        self.assertEqual(stored["at_consumer_messages_no"], 4)

        self.session.consumer_messages_no = 9
        self.session.save(update_fields=["consumer_messages_no", "updated_at"])
        prompt_at_9 = _prepare_prompt(self.session)
        self.assertIn(
            (
                f"Already in this chat: {self.exercise.title}, declined, 5 user turns ago. "
                "Do not offer it again yet. Stay in this chat in the same voice. "
                "Do not run an exercise here."
            ),
            prompt_at_9,
        )

        self.session.consumer_messages_no = 10
        self.session.save(update_fields=["consumer_messages_no", "updated_at"])
        self.assertNotIn("Already in this chat:", _prepare_prompt(self.session))

        fresh = General.create_session(consumer=self.consumer)
        self.assertNotIn("Already in this chat:", _prepare_prompt(fresh))

        typed = General.create_session(consumer=self.consumer)
        typed.consumer_messages_no = 4
        typed.save(update_fields=["consumer_messages_no", "updated_at"])
        Message.objects.create(
            session=typed,
            sender=Participant.objects.filter(
                session=typed, agent=self.consumer.agent
            ).first(),
            text=f"Would you like to start {self.exercise.title}?",
            exercise=self.exercise,
            suggested_responses=list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES),
        )
        note_unresolved_typed_decline(typed, "no")
        typed.refresh_from_db()
        typed_offer = typed.cached_prompt_meta["exercise_offers"][-1]
        self.assertEqual(typed_offer["outcome"], "declined")
        self.assertEqual(typed_offer["at_consumer_messages_no"], 4)
        self.assertIn("Already in this chat:", _prepare_prompt(typed))

    def _user_message(self, text, session=None):
        chat = session or self.session
        sender = Participant.objects.filter(session=chat, consumer=self.consumer).first()
        return Message.objects.create(session=chat, sender=sender, text=text)

    @contextmanager
    def _scripted_posts(self, texts, *, fail=False):
        prompts = []
        pending = list(texts)

        class _Usage:
            pass

        class _Result:
            def __init__(self, text):
                self.output = GeneralResponse(
                    text=text,
                    suggested_responses=[],
                    reasoning="test",
                )

            def usage(self):
                return _Usage()

        def run_sync(*args, **kwargs):
            prompts.append(kwargs.get("user_prompt") or "")
            if fail:
                raise RuntimeError("model down")
            text = pending.pop(0) if pending else ""
            return _Result(text)

        def tool(func=None, **kwargs):
            def register(fn):
                return fn

            if func is None:
                return register
            return register(func)

        fake = mock.Mock()
        fake.tool.side_effect = tool
        fake.run_sync.side_effect = run_sync
        with (
            mock.patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            mock.patch("api.utils.Agent.Agent", return_value=fake),
        ):
            yield prompts

    def _save_scripted(self, texts, user_text, *, session=None, match=False):
        """Run one turn with scripted model replies. Returns (saved message, user prompts)."""
        prompts = []
        systems = []
        pending = list(texts)

        class _Usage:
            pass

        class _Result:
            def __init__(self, text):
                self.output = GeneralResponse(
                    text=text,
                    suggested_responses=[],
                    reasoning="test",
                )

            def usage(self):
                return _Usage()

        def run_sync(*args, **kwargs):
            deps = kwargs.get("deps")
            if match and not prompts and deps is not None:
                deps.matched_exercise = self.exercise
            prompts.append(kwargs.get("user_prompt") or "")
            text = pending.pop(0) if pending else "Still here."
            return _Result(text)

        def tool(func=None, **kwargs):
            def register(fn):
                return fn

            if func is None:
                return register
            return register(func)

        fake = mock.Mock()
        fake.tool.side_effect = tool
        fake.run_sync.side_effect = run_sync

        def build_agent(*args, **kwargs):
            systems.append(kwargs.get("system_prompt"))
            return fake

        user_message = self._user_message(user_text, session=session)
        with (
            mock.patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            mock.patch("api.utils.Agent.Agent", side_effect=build_agent),
        ):
            saved = PersistAgent.get_response(session or self.session, user_message)
        if len(systems) > 1:
            self.assertEqual(systems[0], systems[1])
        return saved, prompts

    def test_empty_reply_retries_once_and_saves_the_reply(self):
        saved, prompts = self._save_scripted(
            ["", "I'm here with you today."],
            "I keep thinking about work.",
        )
        self.assertEqual(len(prompts), 2)
        self.assertNotIn(_BLANK_REPLY_HINT, prompts[0])
        self.assertTrue(prompts[1].endswith(_BLANK_REPLY_HINT))
        self.assertEqual(saved.text, "I'm here with you today.")
        self.assertTrue(saved.text.strip())
        saved.refresh_from_db()
        self.assertEqual(saved.text, "I'm here with you today.")

    def test_empty_reply_twice_saves_the_fixed_fallback(self):
        saved, prompts = self._save_scripted(
            ["", "   "],
            "I keep thinking about work.",
        )
        self.assertEqual(len(prompts), 2)
        self.assertEqual(saved.text, _BLANK_REPLY_FALLBACK)
        self.assertTrue(saved.text.strip())
        self.assertNotIn("exercise", saved.text.lower())

    def test_published_title_without_a_match_retries_once(self):
        saved, prompts = self._save_scripted(
            [
                f"Want to try {self.exercise.title}?",
                "Let's stay with what you said.",
            ],
            "I keep thinking about work.",
        )
        self.assertEqual(len(prompts), 2)
        self.assertTrue(prompts[1].endswith(_OFFER_RETRY_HINT))
        self.assertNotIn(_OFFER_RETRY_HINT, prompts[0])
        self.assertEqual(saved.text, "Let's stay with what you said.")
        self.assertNotEqual(
            saved.suggested_responses,
            list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES),
        )

    def test_published_title_with_a_match_does_not_retry(self):
        first = f"{self.exercise.title} might help. Shall we?"
        saved, prompts = self._save_scripted(
            [first, "This second reply must not be used."],
            "I keep thinking about work.",
            match=True,
        )
        self.assertEqual(len(prompts), 1)
        self.assertIn(self.exercise.title, saved.text)
        self.assertEqual(
            saved.suggested_responses,
            list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES),
        )

    def test_exercise_session_does_not_check_for_an_offer(self):
        chat = Session.objects.create(
            consumer=self.consumer,
            exercise=self.exercise,
            current_step_no=1,
            completed=False,
            total_steps_no=self.exercise.steps_no or 1,
        )
        Participant.create_participants(chat)
        saved, prompts = self._save_scripted(
            [f"Let's talk about {self.exercise.title}.", "Unused retry."],
            "I keep thinking about work.",
            session=chat,
        )
        self.assertEqual(len(prompts), 1)
        self.assertIn(self.exercise.title, saved.text)

    def test_plain_reply_does_not_retry(self):
        saved, prompts = self._save_scripted(
            ["You had a long day.", "Unused retry."],
            "I keep thinking about work.",
        )
        self.assertEqual(len(prompts), 1)
        self.assertEqual(saved.text, "You had a long day.")

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_tapped_no_calls_the_model_once_with_the_decline_hint(self):
        offer = self._create_offer()
        hint = offer_decline_hint(self.exercise.title)
        with self._scripted_posts(["We'll leave that there."]) as prompts:
            response = self._post_message("No", from_suggested_response=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(prompts), 1)
        self.assertIn(hint, prompts[0])
        self.assertEqual(prompts[0].count("<TURN_HINT>"), 1)
        self.assertTrue(prompts[0].rstrip().endswith("</TURN_HINT>"))
        self.assertEqual(response.json["text"], "We'll leave that there.")
        self.assertNotIn(
            Constants.EXERCISE_OFFER_YES,
            response.json["suggested_responses"] or [],
        )
        self.assertIsNone(response.json["exercise"])
        self.session.refresh_from_db()
        stored = self.session.cached_prompt_meta["exercise_offers"][-1]
        self.assertEqual(stored["outcome"], "declined")
        self.assertEqual(stored["exercise_id"], self.exercise.id)
        self.assertEqual(stored["title"], self.exercise.title)
        offer.refresh_from_db()
        self.assertEqual(offer.suggested_responses, [])
        user_message = Message.objects.get(session=self.session, text="No")
        self.assertIsNotNone(user_message.sender.consumer_id)

        with self._scripted_posts(["How did the rest of the day go?"]) as later:
            follow = self._post_message("How was the rest of your day?")
        self.assertEqual(len(later), 1)
        self.assertNotIn("declined the offered exercise", later[0])
        self.assertEqual(follow.json["text"], "How did the rest of the day go?")

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_tapped_no_model_failure_saves_the_canned_line(self):
        self._create_offer()
        with self._scripted_posts([], fail=True):
            response = self._post_message("No", from_suggested_response=True)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json["text"], declined_offer_text(self.exercise.title))
        self.assertNotIn(
            Constants.EXERCISE_OFFER_YES,
            response.json["suggested_responses"] or [],
        )

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_tapped_no_blank_reply_saves_the_canned_line(self):
        self._create_offer()
        with self._scripted_posts([""]) as prompts:
            response = self._post_message("No", from_suggested_response=True)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json["text"], declined_offer_text(self.exercise.title))
        self.assertNotEqual(response.json["text"], "I'm here with you. Tell me a bit more.")

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_typed_no_does_not_use_the_tapped_decline_hint(self):
        self._create_offer()
        with self._scripted_posts(["We can stay with this."]) as prompts:
            response = self._post_message("no")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("declined the offered exercise", prompts[0])
        self.assertEqual(response.json["text"], "We can stay with this.")
