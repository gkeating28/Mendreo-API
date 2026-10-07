"""Embedding and chunking locks.

``gemini-embedding-001`` truncated to 768 dimensions matches the stored
vector column. ``text-embedding-004`` was shut down on 14 January 2026.
Changing the dimension needs a new migration. Retrieval stays behind
``AI_RETRIEVAL_ENABLED``, which defaults off.
"""

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768
# Each text in a batch counts as one Gemini request. Stay under the free-tier
# per-minute cap so indexing a long guide does not exhaust the quota at once.
EMBED_TEXTS_PER_MINUTE = 60

CHUNK_TARGET_TOKENS = 500
CHUNK_HARD_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 60

CANDIDATE_LIMIT = 20
BELOW_THRESHOLD_LIMIT = 5
RRF_K = 60
