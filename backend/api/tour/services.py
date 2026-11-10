"""App tour copy in the app_tour Setting row, and generated voice clips.

The row stores title, body, audio_key and audio_hash per step id. Step ids
and platforms always come from code. A blank title or body falls back to
the default. audio_hash is a short hash of the body and the voice the clip
was generated with. The clip is current only when that hash still matches
the step's current body for one of the library voices.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.db import transaction

from ..user.models import UserSettings
from ..utils import Api, Constants, File
from ..voice.elevenlabs_client import (
    ElevenLabsConfigError,
    ElevenLabsRequestError,
    resolve_elevenlabs_voice,
    synthesize_speech,
)
from ..voice.services import TTS_MAX_CHARS
from .defaults import DEFAULT_TOUR_STEPS, STEPS_BY_ID

logger = logging.getLogger(__name__)

_STORED_FIELDS = ("title", "body", "audio_key", "audio_hash")
_HASH_CHARS = 16


class TourSpeechError(Exception):
    def __init__(self, detail: str, status_code: int):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def clip_hash(body: str, voice_id: str) -> str:
    """Short hash of the spoken body and the voice id used to speak it."""
    payload = f"{voice_id}\n{(body or '').strip()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:_HASH_CHARS]


def clip_is_current(stored_hash: str, body: str) -> bool:
    if not stored_hash:
        return False
    return any(
        clip_hash(body, voice_id) == stored_hash
        for voice_id in UserSettings.VoiceId.values
    )


def get_or_create_app_tour():
    from ..setting.models import Setting

    setting, _created = Setting.objects.get_or_create(
        key=Constants.SETTING_KEY_APP_TOUR,
        defaults={"value": "{}"},
    )
    return setting


def _parse_stored(raw) -> dict:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    cleaned = {}
    for step_id, value in parsed.items():
        if step_id not in STEPS_BY_ID or not isinstance(value, dict):
            continue
        step = {}
        for field in _STORED_FIELDS:
            item = value.get(field)
            if isinstance(item, str):
                step[field] = item
        cleaned[step_id] = step
    return cleaned


def _load_stored() -> dict:
    from ..setting.models import Setting

    raw = Setting._cached_value(
        Constants.SETTING_KEY_APP_TOUR,
        get_or_create_app_tour,
    )
    return _parse_stored(raw)


def _text(saved: dict, field: str, default: str) -> str:
    value = saved.get(field)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _public_audio_url(audio_key: str) -> str | None:
    base = (Api.SUPABASE_STORAGE_URL or "").rstrip("/")
    bucket = Api.SUPABASE_STORAGE_BUCKET or ""
    if not audio_key or not base or not bucket:
        return None
    key = audio_key if audio_key.startswith("/") else f"/{audio_key}"
    return f"{base}/storage/v1/object/public/{bucket}{key}"


def tour_steps() -> list[dict]:
    """Merged steps, including the fields the admin response adds."""
    stored = _load_stored()
    steps = []
    for default in DEFAULT_TOUR_STEPS:
        saved = stored.get(default["id"]) or {}
        body = _text(saved, "body", default["body"])
        audio_key = (saved.get("audio_key") or "").strip()
        audio_hash = (saved.get("audio_hash") or "").strip()
        current = bool(audio_key) and clip_is_current(audio_hash, body)
        steps.append({
            "id": default["id"],
            "title": _text(saved, "title", default["title"]),
            "body": body,
            "platforms": list(default["platforms"]),
            "audio_url": _public_audio_url(audio_key) if current else None,
            "audio_exists": bool(audio_key),
            "audio_stale": bool(audio_key) and not current,
        })
    return steps


def consumer_steps() -> list[dict]:
    return [
        {
            "id": step["id"],
            "title": step["title"],
            "body": step["body"],
            "platforms": step["platforms"],
            "audio_url": step["audio_url"],
        }
        for step in tour_steps()
    ]


def admin_steps() -> list[dict]:
    return [
        {
            "id": step["id"],
            "title": step["title"],
            "body": step["body"],
            "platforms": step["platforms"],
            "audio_url": step["audio_url"],
            "audio_exists": step["audio_exists"],
            "audio_stale": step["audio_stale"],
        }
        for step in tour_steps()
    ]


def save_step_text(steps: list[dict]) -> None:
    """Update title and body for the given steps. Audio fields stay as they are."""
    from ..setting.models import Setting

    with transaction.atomic():
        get_or_create_app_tour()
        setting = Setting.objects.select_for_update().get(
            key=Constants.SETTING_KEY_APP_TOUR,
        )
        stored = _parse_stored(setting.value)
        for item in steps:
            step_id = item["id"]
            current = dict(stored.get(step_id) or {})
            if "title" in item:
                current["title"] = (item["title"] or "").strip()
            if "body" in item:
                current["body"] = (item["body"] or "").strip()
            stored[step_id] = {
                field: current[field]
                for field in _STORED_FIELDS
                if isinstance(current.get(field), str)
            }
        setting.value = json.dumps(stored)
        setting.save()


def generate_step_audio(step_id: str, voice_id: str) -> dict:
    """Synthesize the current body, store the clip, then drop the previous file."""
    step = next((item for item in tour_steps() if item["id"] == step_id), None)
    if step is None:
        raise TourSpeechError("Step not found.", 404)

    text = (step["body"] or "").strip()
    if not text:
        raise TourSpeechError("This step has no text to read.", 400)
    if len(text) > TTS_MAX_CHARS:
        raise TourSpeechError(
            f"Text must be {TTS_MAX_CHARS} characters or fewer.",
            400,
        )

    _voice_key, elevenlabs_voice_id = resolve_elevenlabs_voice(voice_id)
    try:
        audio, content_type = synthesize_speech(text, elevenlabs_voice_id)
    except ElevenLabsConfigError:
        logger.warning("tour audio is not configured step=%s", step_id)
        raise TourSpeechError("ElevenLabs is not configured.", 503)
    except ElevenLabsRequestError as exc:
        logger.warning(
            "tour audio request failed step=%s status=%s",
            step_id,
            exc.status_code,
        )
        status_code = exc.status_code if isinstance(exc.status_code, int) else 502
        if status_code < 400 or status_code > 599:
            status_code = 502
        raise TourSpeechError("Could not generate speech.", status_code)

    new_hash = clip_hash(text, voice_id)
    new_key = f"/tour/{step_id}-{new_hash[:8]}.mp3"
    try:
        result = File.upload(
            audio,
            new_key,
            content_type=content_type or "audio/mpeg",
            public=True,
        )
    except Exception:
        logger.warning("tour audio upload failed step=%s", step_id)
        raise TourSpeechError("Could not store the audio clip.", 502)
    if isinstance(result, str):
        logger.warning("tour audio upload failed step=%s", step_id)
        raise TourSpeechError("Could not store the audio clip.", 502)

    from ..setting.models import Setting

    with transaction.atomic():
        get_or_create_app_tour()
        setting = Setting.objects.select_for_update().get(
            key=Constants.SETTING_KEY_APP_TOUR,
        )
        stored = _parse_stored(setting.value)
        current = dict(stored.get(step_id) or {})
        old_key = (current.get("audio_key") or "").strip()
        current["audio_key"] = new_key
        current["audio_hash"] = new_hash
        stored[step_id] = {
            field: current[field]
            for field in _STORED_FIELDS
            if isinstance(current.get(field), str)
        }
        setting.value = json.dumps(stored)
        setting.save()

    if old_key and old_key != new_key:
        try:
            File.delete(old_key)
        except Exception:
            logger.warning("tour audio delete failed step=%s", step_id)

    updated = next(item for item in admin_steps() if item["id"] == step_id)
    return updated
