"""Embedding and chunking locks.

``text-embedding-004`` at 768 dimensions is provisional until the grounding
spike records the model that separated relevant from irrelevant chunks.
Changing the dimension needs a new migration. Retrieval stays behind
``AI_RETRIEVAL_ENABLED``, which defaults off.
"""

EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIMENSIONS = 768

CHUNK_TARGET_TOKENS = 500
CHUNK_HARD_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 60

CANDIDATE_LIMIT = 20
BELOW_THRESHOLD_LIMIT = 5
RRF_K = 60
