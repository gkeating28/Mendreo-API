from unittest.mock import patch

from django.core.cache import cache

from ...session.models import Session
from ...setting.models import Setting
from ...utils import Constants
from ...utils.Agent import _prepare_prompt
from ..TestCase import TestCase
from ..utils.manager import Auth


class ReturningUserInstructionTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.consumer = Auth.create_consumer()
        self.consumer.user.first_name = "Ada"
        self.consumer.user.save(update_fields=["first_name"])

    def _session(self):
        return Session.objects.create(consumer=self.consumer)

    def test_default_text_renders_with_user_name_filled(self):
        prompt = _prepare_prompt(self._session())
        filled = Constants.DEFAULT_RETURNING_USER_INSTRUCTION.replace("{user_name}", "Ada")

        self.assertNotIn("{user_name}", filled)
        self.assertIn(filled, prompt)
        self.assertNotIn("{returning_user_instruction}", prompt)
        self.assertNotIn(
            "If there are no notes, you have never spoken to Ada and you must say so.",
            prompt,
        )

    def test_second_prepare_with_unchanged_setting_does_not_rebuild(self):
        session = self._session()
        first = _prepare_prompt(session)
        session.refresh_from_db()
        updated_at = session.updated_at

        with patch.object(Session, "save", wraps=Session.save) as save:
            second = _prepare_prompt(session)

        self.assertEqual(second, first)
        self.assertEqual(save.call_count, 0)
        session.refresh_from_db()
        self.assertEqual(session.updated_at, updated_at)
        self.assertEqual(session.cached_prompt, first)

    def test_multiline_setting_still_matches_the_cache_check(self):
        row = Setting.get_or_create_returning_user_instruction()
        row.value = "Line one for {user_name}.\nLine two is still about them."
        row.save()
        cache.clear()
        session = self._session()
        first = _prepare_prompt(session)
        filled = "Line one for Ada.\nLine two is still about them."
        self.assertIn(filled, first)
        session.refresh_from_db()

        with patch.object(Session, "save", wraps=Session.save) as save:
            second = _prepare_prompt(session)

        self.assertEqual(save.call_count, 0)
        self.assertEqual(second, first)
        self.assertIn(filled, second)

    def test_blank_save_returns_the_default(self):
        row = Setting.get_or_create_returning_user_instruction()
        row.value = ""
        row.save()
        cache.clear()

        self.assertEqual(
            Setting.get_returning_user_instruction(),
            Constants.DEFAULT_RETURNING_USER_INSTRUCTION,
        )
