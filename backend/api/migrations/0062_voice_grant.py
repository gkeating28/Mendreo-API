# ElevenLabs Conversational AI — VoiceGrant + message turn keys

import charidfield.fields
import cuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0061_user_settings_chat_prefs"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="voice_conversation_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="voice_turn_index",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["session", "voice_conversation_id", "voice_turn_index"],
                name="message_voice_turn_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="message",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    voice_conversation_id__isnull=False,
                    voice_turn_index__isnull=False,
                ),
                fields=("session", "voice_conversation_id", "voice_turn_index"),
                name="uniq_message_voice_turn",
            ),
        ),
        migrations.CreateModel(
            name="VoiceGrant",
            fields=[
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "id",
                    charidfield.fields.CharIDField(
                        default=cuid.cuid,
                        help_text="cuid-format identifier for this entity.",
                        max_length=40,
                        prefix="vgr_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                (
                    "elevenlabs_conversation_id",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "consumer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="voice_grants",
                        to="api.consumer",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="voice_grants",
                        to="api.session",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="voicegrant",
            index=models.Index(
                fields=["consumer", "-created_at"],
                name="api_vgr_consumer_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="voicegrant",
            index=models.Index(
                fields=["elevenlabs_conversation_id"],
                name="api_vgr_elevenlabs_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="voicegrant",
            index=models.Index(fields=["expires_at"], name="api_vgr_expires_idx"),
        ),
    ]
