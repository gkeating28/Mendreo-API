"""Publishing an article creates its source. Leaving published retires it.

Video and podcast wait until a transcript exists. This path is a system
publish: it does not go through the self-approval endpoint.
"""

from __future__ import annotations

from ..utils import Constants
from .models import KnowledgeChunk, KnowledgeSource


def sync_post_source(post) -> KnowledgeSource | None:
    if post is None or post.type != Constants.POST_TYPE_ARTICLE:
        return None
    source = KnowledgeSource.objects.filter(post=post).first()
    if post.status == Constants.POST_STATUS_PUBLISHED and (post.body or "").strip():
        owner = _owner(post)
        if source is None:
            source = KnowledgeSource.objects.create(
                title=post.title,
                kind=Constants.KNOWLEDGE_SOURCE_KIND_POST,
                status=Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED,
                post=post,
                body=post.body,
                version=1,
                clinical_owner=owner,
            )
        else:
            source.title = post.title
            source.body = post.body
            source.status = Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED
            source.deleted_at = None
            if owner is not None and source.clinical_owner_id is None:
                source.clinical_owner = owner
            source.save()
        _enqueue(source.id)
        return source
    if source is not None and source.status == Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED:
        source.status = Constants.KNOWLEDGE_SOURCE_STATUS_RETIRED
        source.save(update_fields=["status", "updated_at"])
        KnowledgeChunk.objects.filter(source=source, active=True).update(active=False)
    return source


def _owner(post):
    from django.core.exceptions import ObjectDoesNotExist

    user = getattr(post, "created_by", None)
    if user is None:
        return None
    try:
        return user.admin
    except ObjectDoesNotExist:
        return None


def _enqueue(source_id: str) -> None:
    """Index the article in this request. A failure here must not block publish."""
    import logging

    from .indexing import index_now

    try:
        index_now(source_id)
    except Exception:
        logging.getLogger(__name__).exception(
            "article source %s was not indexed", source_id
        )
