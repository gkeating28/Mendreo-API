import charidfield.fields
import cuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import api.utils.Fields


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0047_perf_session_message_participant_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='AiProvider',
            fields=[
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('id', charidfield.fields.CharIDField(default=cuid.cuid, help_text='cuid-format identifier for this entity.', max_length=40, prefix='aip_', primary_key=True, serialize=False, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('provider', api.utils.Fields.EnumField(choices=[('google', 'google'), ('openai', 'openai'), ('anthropic', 'anthropic')], default='google')),
                ('default_model', models.CharField(max_length=255)),
                ('is_default', models.BooleanField(db_index=True, default=False)),
                ('enabled', models.BooleanField(db_index=True, default=True)),
                ('api_key_encrypted', models.TextField()),
                ('extra_config', models.JSONField(blank=True, default=dict)),
            ],
        ),
        migrations.CreateModel(
            name='AiProviderAuditLog',
            fields=[
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('id', charidfield.fields.CharIDField(default=cuid.cuid, help_text='cuid-format identifier for this entity.', max_length=40, prefix='apal_', primary_key=True, serialize=False, unique=True)),
                ('provider_id_snapshot', models.CharField(db_index=True, max_length=40)),
                ('provider_name_snapshot', models.CharField(blank=True, default='', max_length=255)),
                ('provider_type_snapshot', models.CharField(blank=True, default='', max_length=64)),
                ('action', api.utils.Fields.EnumField(choices=[('created', 'created'), ('updated', 'updated'), ('key_rotated', 'key_rotated'), ('set_default', 'set_default'), ('enabled', 'enabled'), ('disabled', 'disabled'), ('deleted', 'deleted'), ('failover', 'failover'), ('seeded', 'seeded')], default='created')),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ai_provider_audit_logs', to=settings.AUTH_USER_MODEL)),
                ('provider', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_logs', to='api.aiprovider')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='aiprovider',
            index=models.Index(fields=['provider', 'enabled'], name='api_aiprovi_provide_c9377f_idx'),
        ),
    ]
