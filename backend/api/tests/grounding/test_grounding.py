from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

from ...agent.models import Agent
from ...ai_provider.models import AiProvider
from ...eval.models import EvalCase
from ...eval.runner import run_eval
from ...exercise.models import Exercise
from ...file.models import File
from ...grounding.constants import EMBEDDING_DIMENSIONS
from ...grounding.embeddings import clear_embedder, set_embedder
from ...grounding.indexing import index_source
from ...grounding.models import KnowledgeChunk, KnowledgeSource
from ...grounding.posts import sync_post_source
from ...grounding.retrieval import augment_user_prompt, stamp_retrieval_enabled
from ...grounding.search import search_chunks
from ...image.models import Image
from ...message.models import Message
from ...message.serializers import MessageListSerializer
from ...participant.models import Participant
from ...post.models import Post
from ...post.serializers import PostEditSerializer
from ...session.models import Session
from ...step.models import Step
from ...session.serializers import SessionDetailSerializer
from ...setting.models import Setting
from ...utils import Constants
from ...utils.Agent import GeneralResponse, _prepare_prompt
from ...utils.history import build_history
from ..TestCase import TestCase
from ..utils.manager import Auth


def _vector(axis: int) -> list[float]:
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[axis] = 1.0
    return values


def _embed(texts):
    vectors = []
    for text in texts:
        if "avoidance" in (text or "").lower():
            vectors.append(_vector(0))
        else:
            vectors.append(_vector(1))
    return vectors


class EmbeddingModelTests(SimpleTestCase):
    @patch("api.grounding.embeddings._embed_client")
    def test_embeddings_request_768_dimensions_from_gemini(self, client_factory):
        from ...grounding.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
        from ...grounding.embeddings import clear_embedder, embed_texts

        clear_embedder()
        embedding = Mock(values=[0.2] * EMBEDDING_DIMENSIONS)
        client = Mock()
        client.models.embed_content.return_value = Mock(embeddings=[embedding])
        client_factory.return_value = client

        vectors = embed_texts(["Avoidance keeps the cycle going."])

        kwargs = client.models.embed_content.call_args.kwargs
        self.assertEqual(kwargs["model"], EMBEDDING_MODEL)
        self.assertEqual(kwargs["model"], "gemini-embedding-001")
        self.assertEqual(kwargs["config"].output_dimensionality, 768)
        self.assertEqual(len(vectors[0]), 768)
        clear_embedder()


class GroundingTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        set_embedder(_embed)
        self.admin = Auth.create_admin(email="owner@example.com")
        self.other = Auth.create_admin(email="reviewer@example.com")
        self.token = Auth.get_access_token(self.admin.user)
        self.other_token = Auth.get_access_token(self.other.user)

    def tearDown(self):
        clear_embedder()
        cache.clear()
        super().tearDown()

    def _setting(self, key, value):
        Setting.objects.update_or_create(key=key, defaults={"value": str(value)})
        cache.clear()

    def _exercise(self, reference="UNIQUE_NOTE_ALPHA"):
        exercise = Exercise.objects.create(
            title="Avoidance",
            subtitle="Cycle",
            description="Notice the loop.",
            steps_no=1,
            icon="circle",
            icon_background_color="#ffffff",
            reference_material=reference,
            status=Constants.EXERCISE_STATUS_PUBLISHED,
        )
        Step.objects.create(
            exercise=exercise,
            title="Notice",
            description="Notice it.",
            instructions="Name the loop.",
            completion_label="Done",
            order=0,
            reference_material="Step note stays in the prompt.",
        )
        return exercise

    def _source(self, **kwargs):
        payload = {
            "title": "Avoidance",
            "kind": Constants.KNOWLEDGE_SOURCE_KIND_GUIDANCE,
            "status": Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED,
            "body": "# Module 3\n\n## Avoidance\n\nAvoidance keeps the cycle going.",
            "clinical_owner": self.admin,
        }
        payload.update(kwargs)
        return KnowledgeSource.objects.create(**payload)

    def test_reindex_swaps_version_and_failed_embed_keeps_the_previous(self):
        source = self._source()
        self.assertEqual(index_source(source.id), 1)
        source.refresh_from_db()
        self.assertEqual(source.version, 1)
        self.assertEqual(KnowledgeChunk.objects.filter(source=source, active=True).count(), 1)

        self.assertEqual(index_source(source.id), 1)
        source.refresh_from_db()
        self.assertEqual(source.version, 2)
        self.assertEqual(KnowledgeChunk.objects.filter(source=source, active=True).count(), 1)
        self.assertEqual(KnowledgeChunk.objects.filter(source=source, active=False).count(), 1)

        def _boom(_texts):
            raise RuntimeError("embed down")

        set_embedder(_boom)
        with self.assertRaises(RuntimeError):
            index_source(source.id)
        source.refresh_from_db()
        self.assertEqual(source.version, 2)
        self.assertEqual(
            list(
                KnowledgeChunk.objects.filter(source=source, active=True).values_list(
                    "source_version", flat=True
                )
            ),
            [2],
        )

    def test_up_source_without_licence_and_copied_notes_are_not_indexed(self):
        source = self._source(
            kind=Constants.KNOWLEDGE_SOURCE_KIND_UP_SOURCE,
            licence_note="",
        )
        self.assertEqual(index_source(source.id), 0)
        self.assertFalse(KnowledgeChunk.objects.filter(source=source).exists())

        exercise = self._exercise(reference="Keep this note in the prompt.")
        copied = self._source(
            kind=Constants.KNOWLEDGE_SOURCE_KIND_EXERCISE_REFERENCE,
            body="Keep this note in the prompt.",
            exercise_ids=[exercise.id],
        )
        self.assertEqual(index_source(copied.id), 0)

    def test_search_scope_threshold_and_exercise_list(self):
        exercise = self._exercise()
        guidance = self._source(title="Guidance")
        linked = self._source(
            title="Linked article",
            kind=Constants.KNOWLEDGE_SOURCE_KIND_POST,
            exercise_ids=[exercise.id],
        )
        other = self._source(
            title="Other article",
            kind=Constants.KNOWLEDGE_SOURCE_KIND_POST,
            exercise_ids=["exrcs_other"],
        )
        up_source = self._source(
            title="Workbook",
            kind=Constants.KNOWLEDGE_SOURCE_KIND_UP_SOURCE,
            licence_note="Internal sample, licence check pending.",
        )
        noise = self._source(title="Noise", body="A note about zephyr only.")
        for source in (guidance, linked, other, up_source, noise):
            index_source(source.id)

        selected, below = search_chunks(
            "how does avoidance keep anxiety going when someone mentions zephyr",
            exercise.id,
        )
        titles = [item["title"] for item in selected]
        self.assertIn("Guidance", titles)
        self.assertIn("Linked article", titles)
        self.assertIn("Workbook", titles)
        self.assertNotIn("Other article", titles)
        self.assertNotIn("Noise", titles)
        self.assertEqual(selected[0]["title"], "Linked article")
        self.assertEqual(selected[0]["rank"], 1)
        self.assertTrue(any(item["title"] == "Noise" for item in below))

        general, _ = search_chunks(
            "how does avoidance keep anxiety going in general chat today",
            None,
        )
        self.assertIn("Other article", [item["title"] for item in general])

        other.status = Constants.KNOWLEDGE_SOURCE_STATUS_RETIRED
        other.save(update_fields=["status", "updated_at"])
        again, _ = search_chunks("how does avoidance keep anxiety going in general chat today")
        self.assertNotIn("Other article", [item["title"] for item in again])

    def test_flag_off_keeps_notes_and_omits_the_instruction(self):
        consumer = Auth.create_consumer()
        exercise = self._exercise()
        session = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            current_step_no=1,
            completed=False,
            total_steps_no=exercise.steps_no,
        )
        prompt = _prepare_prompt(session)
        self.assertIn("UNIQUE_NOTE_ALPHA", prompt)
        self.assertNotIn("do not name the source document", prompt)

        self._setting(Constants.SETTING_KEY_AI_RETRIEVAL_ENABLED, "true")
        session.refresh_from_db()
        cached = _prepare_prompt(session)
        self.assertIn("UNIQUE_NOTE_ALPHA", cached)
        self.assertNotIn("do not name the source document", cached)

        stamped = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            current_step_no=1,
            completed=False,
            total_steps_no=exercise.steps_no,
        )
        stamp_retrieval_enabled(stamped)
        enabled = _prepare_prompt(stamped)
        self.assertIn("UNIQUE_NOTE_ALPHA", enabled)
        self.assertIn("do not name the source document", enabled)
        self.assertIn("<REFERENCE>", enabled)

    def test_short_query_is_prefixed_and_high_risk_skips_search(self):
        consumer = Auth.create_consumer()
        self._setting(Constants.SETTING_KEY_AI_RETRIEVAL_ENABLED, "true")
        session = Session.objects.create(consumer=consumer)
        stamp_retrieval_enabled(session)
        Participant.create_participants(session)
        agent_participant = Participant.objects.get(session=session, agent__isnull=False)
        Message.objects.create(
            session=session,
            sender=agent_participant,
            text="Avoidance keeps the cycle going for a long time.",
        )
        seen = []

        def _watch(texts):
            seen.extend(texts)
            return _embed(texts)

        set_embedder(_watch)
        user = SimpleNamespace(text="why though")
        augment_user_prompt(session, user, "why though")
        self.assertTrue(seen)
        self.assertIn("Avoidance keeps the cycle", seen[0])
        self.assertIn("why though", seen[0])

        seen.clear()

        def _forbid(_texts):
            raise AssertionError("search should not run")

        set_embedder(_forbid)
        skipped = augment_user_prompt(session, SimpleNamespace(text="I want to die"), "I want to die")
        self.assertEqual(skipped, "I want to die")
        self.assertIsNone(session._pending_retrieval)
        chip = augment_user_prompt(
            session,
            SimpleNamespace(text=Constants.CHIP_READY_YES),
            Constants.CHIP_READY_YES,
        )
        self.assertNotIn("<RETRIEVED>", chip)

    def test_retrieval_turn_fails_over_without_putting_the_block_in_history(self):
        consumer = Auth.create_consumer()
        self._setting(Constants.SETTING_KEY_AI_RETRIEVAL_ENABLED, "true")
        source = self._source()
        index_source(source.id)
        session = Session.create_general(consumer)
        user_participant = Participant.objects.get(session=session, consumer__isnull=False)
        user_message = Message.objects.create(
            session=session,
            sender=user_participant,
            text="How does avoidance keep anxiety going over time?",
        )
        AiProvider.objects.all().delete()
        google = AiProvider(
            name="Google",
            provider=Constants.AI_PROVIDER_GOOGLE,
            default_model="gemini-3.1-flash-lite",
            is_default=True,
            enabled=True,
        )
        google.set_api_key("google-secret")
        google.save()
        anthropic = AiProvider(
            name="Anthropic",
            provider=Constants.AI_PROVIDER_ANTHROPIC,
            default_model="claude-sonnet-4-5",
            is_default=False,
            enabled=True,
        )
        anthropic.set_api_key("anthropic-secret")
        anthropic.save()
        calls = {"n": 0, "prompts": [], "histories": []}

        class _FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def tool(self, func=None, **kwargs):
                if func is None:
                    return lambda fn: fn
                return func

            def run_sync(self, user_prompt="", message_history=None, **kwargs):
                calls["n"] += 1
                calls["prompts"].append(user_prompt)
                calls["histories"].append(message_history or [])
                if calls["n"] == 1:
                    raise RuntimeError("google down")
                output = GeneralResponse(
                    text="Avoidance can keep the alarm switched on.",
                    suggested_responses=[],
                    reasoning="ok",
                )
                return SimpleNamespace(
                    output=output,
                    usage=lambda: SimpleNamespace(input_tokens=1, output_tokens=1),
                )

        with (
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", _FakeAgent),
        ):
            agent_message = Agent.get_response(session, user_message)

        self.assertEqual(calls["n"], 2)
        self.assertIn("<RETRIEVED>", calls["prompts"][0])
        self.assertNotIn("similarity", calls["prompts"][0])
        history_text = _history_text(calls["histories"][1])
        self.assertNotIn("<RETRIEVED>", history_text)
        user_message.refresh_from_db()
        self.assertNotIn("<RETRIEVED>", user_message.text)
        self.assertEqual(agent_message.retrieval[0]["source_id"], source.id)
        self.assertEqual(agent_message.retrieval[0]["rank"], 1)
        rebuilt = _history_text(build_history(session))
        self.assertNotIn("<RETRIEVED>", rebuilt)

        admin_data = SessionDetailSerializer(
            session,
            context={"request": SimpleNamespace(user=self.admin.user)},
        ).data
        self.assertEqual(admin_data["retrieval"][0]["sources"], ["Avoidance"])
        consumer_data = SessionDetailSerializer(
            session,
            context={"request": SimpleNamespace(user=consumer.user)},
        ).data
        self.assertNotIn("retrieval", consumer_data)
        self.assertNotIn("retrieval", MessageListSerializer.Meta.fields)

    def test_submitter_can_approve_when_licence_is_present(self):
        created = self._post(
            "/knowledge/sources",
            {
                "title": "Workbook chapter",
                "kind": "up_source",
                "body": "# Module 3\n\nAvoidance keeps the cycle going.",
                "licence_note": "",
            },
            access_token=self.token,
        )
        self.assertEqual(created.status_code, 201, created.json)
        source_id = created.json["id"]
        submitted = self._post(
            f"/knowledge/sources/{source_id}/submit",
            {},
            access_token=self.token,
        )
        self.assertEqual(submitted.status_code, 200, submitted.json)
        missing_licence = self._post(
            f"/knowledge/sources/{source_id}/approve",
            {},
            access_token=self.token,
        )
        self.assertEqual(missing_licence.status_code, 400)
        self._patch(
            f"/knowledge/sources/{source_id}",
            {"licence_note": "Internal sample for the spike."},
            access_token=self.token,
        )
        approved = self._post(
            f"/knowledge/sources/{source_id}/approve",
            {},
            access_token=self.token,
        )
        self.assertEqual(approved.status_code, 200, approved.json)
        self.assertEqual(approved.json["status"], "published")
        self.assertEqual(approved.json["approved_by"], approved.json["submitted_by"])
        self.assertEqual(approved.json["indexed_chunks"], 1)
        self.assertEqual(
            KnowledgeChunk.objects.filter(source_id=source_id, active=True).count(),
            1,
        )

    def test_approve_reports_when_the_source_has_no_text(self):
        created = self._post(
            "/knowledge/sources",
            {"title": "Empty", "kind": "guidance", "body": " "},
            access_token=self.token,
        )
        self.assertEqual(created.status_code, 201, created.json)
        source_id = created.json["id"]
        submitted = self._post(
            f"/knowledge/sources/{source_id}/submit",
            {},
            access_token=self.token,
        )
        self.assertEqual(submitted.status_code, 200, submitted.json)
        approved = self._post(
            f"/knowledge/sources/{source_id}/approve",
            {},
            access_token=self.token,
        )
        self.assertEqual(approved.status_code, 400, approved.json)
        self.assertIn("no text", approved.json["detail"])
        self.assertFalse(KnowledgeChunk.objects.filter(source_id=source_id).exists())

    def test_public_admin_upload_can_be_attached_to_a_source(self):
        uploaded = File.objects.create(
            name="UP Therapist Guide - main.md",
            extension="md",
            url=f"/admins/{self.admin.user_id}/files/abc.md",
            uploaded=True,
            created_by=self.admin.user,
        )
        with (
            patch("api.utils.File._download_bytes", return_value=b"# Guide\n") as download,
            patch("api.utils.File.upload", return_value=None) as upload,
            patch("api.utils.File.delete") as delete,
        ):
            created = self._post(
                "/knowledge/sources",
                {
                    "title": "UP Therapist Guide",
                    "kind": "up_source",
                    "file": uploaded.id,
                    "licence_note": "Internal sample for the spike.",
                },
                access_token=self.token,
            )

        self.assertEqual(created.status_code, 201, created.json)
        uploaded.refresh_from_db()
        self.assertEqual(
            uploaded.url,
            f"/knowledge/{self.admin.user_id}/abc.md",
        )
        download.assert_called_once()
        upload.assert_called_once()
        delete.assert_called_once_with(f"/admins/{self.admin.user_id}/files/abc.md")
        self.assertEqual(created.json["file"], uploaded.id)

    def test_article_publish_creates_a_source_and_unpublish_retires_it(self):
        image = Image.objects.create(
            created_by=self.admin.user,
            original="images/test.png",
            name="test",
            width=8,
            height=8,
            uploaded=True,
        )
        post = Post.objects.create(
            created_by=self.admin.user,
            thumbnail=image,
            banner=image,
            status=Constants.POST_STATUS_DRAFT,
            type=Constants.POST_TYPE_ARTICLE,
            title="Sleep",
            subtitle="Nights",
            body="Draft body",
        )
        self.assertFalse(KnowledgeSource.objects.filter(post=post).exists())
        post.status = Constants.POST_STATUS_PUBLISHED
        post.published_at = timezone.now()
        post.body = "# Sleep\n\nShort nights make the next day harder."
        post.save()
        PostEditSerializer().post_update(post, {})
        source = KnowledgeSource.objects.get(post=post)
        self.assertEqual(source.status, Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED)
        self.assertEqual(source.kind, Constants.KNOWLEDGE_SOURCE_KIND_POST)
        post.status = Constants.POST_STATUS_ARCHIVED
        post.save(update_fields=["status", "updated_at"])
        sync_post_source(post)
        source.refresh_from_db()
        self.assertEqual(source.status, Constants.KNOWLEDGE_SOURCE_STATUS_RETIRED)

    def test_grounding_cases_do_not_fail_the_default_harness(self):
        EvalCase.objects.create(
            name="grounding sample",
            kind=Constants.EVAL_CASE_KIND_GROUNDING,
            transcript=[{"role": "user", "text": "Why does avoidance stick?"}],
            expected={"key_points": ["cycle"], "must_not": []},
            active=True,
        )
        result = run_eval()
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 0)


def _history_text(history) -> str:
    parts = []
    for message in history:
        for part in getattr(message, "parts", []) or []:
            parts.append(getattr(part, "content", "") or "")
    return "\n".join(parts)
