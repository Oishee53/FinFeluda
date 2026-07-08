"""
Reranking -- the article's "fast rough retriever, then slow precise
reranker" two-stage pattern.

Hybrid search (search_hybrid in qdrant_service.py) is the fast, rough
first pass: it's good at narrowing millions of chunks down to a
double-digit candidate set quickly, using RRF-fused dense+sparse
scores. But RRF rank fusion is itself approximate -- it never actually
reads the query against each candidate's full text together.

A cross-encoder reranker does: it takes the (query, candidate_text)
PAIR and scores how relevant that specific candidate actually is to
that specific query, which is far more precise than comparing
independently-computed embeddings, but too slow to run over a whole
collection. The division of labor: hybrid search narrows millions of
chunks to ~20-30 candidates cheaply, the reranker does a careful
pass over just those ~20-30 to pick the best ~5-8 for the prompt.

Uses fastembed's bundled cross-encoder (same ONNX/no-torch story as
the rest of this app's embedding stack -- no new dependency class).
"""
import asyncio
import logging
import psutil
from fastembed.rerank.cross_encoder import TextCrossEncoder
from typing import List

logger = logging.getLogger(__name__)

_reranker: TextCrossEncoder | None = None

RERANKER_MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"  # small, fast, good default cross-encoder

# The reranker is already lazy-loaded (only instantiated on first chat
# use, not at startup) -- confirmed in practice that lazy loading alone
# isn't enough on a 512MB free-tier deploy: the FIRST chat request still
# crashed the whole process with an OOM kill, because loading the
# cross-encoder on top of the already-resident dense+sparse embedding
# models plus that request's own working set (retrieved chunk text,
# prompt strings) pushed total RSS over the container's memory cap.
# This checks current process memory before attempting to load/run the
# reranker and skips it entirely if already tight, falling back to the
# hybrid search's own RRF-fused ordering (a real ranking, just less
# precise) instead of crashing the whole request.
MEMORY_PRESSURE_THRESHOLD_BYTES = 350 * 1024 * 1024


def _memory_pressure_high() -> bool:
    try:
        rss = psutil.Process().memory_info().rss
    except Exception:
        # If we can't even check, don't let that itself break reranking --
        # only psutil failing is the risk here, not a real OOM.
        return False
    if rss > MEMORY_PRESSURE_THRESHOLD_BYTES:
        logger.warning(
            "Memory pressure high (%.0fMB > %.0fMB threshold) -- skipping reranking",
            rss / 1024 / 1024, MEMORY_PRESSURE_THRESHOLD_BYTES / 1024 / 1024,
        )
        return True
    return False


def get_reranker() -> TextCrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = TextCrossEncoder(model_name=RERANKER_MODEL_NAME)
    return _reranker


def rerank_chunks(query: str, candidates: List[dict], top_n: int = 6) -> List[dict]:
    """
    Sync implementation. Call rerank_chunks_async() from async code.

    candidates: list of chunk payload dicts (as returned by
    qdrant_service.search_hybrid()), each must have a "text" key.
    Already ordered by hybrid search's fused RRF score -- a real
    (if less precise) ranking, so falling back to candidates[:top_n]
    under memory pressure is a genuine degradation, not arbitrary order.

    Returns the top_n candidates re-sorted by the cross-encoder's
    relevance score, with payload["_rerank_score"] attached. This
    score is NOT comparable to "_score" (RRF) or "_dense_score" /
    "_sparse_score" -- it's a separate, more precise judgment and
    should be the one actually trusted for final ordering.

    If candidates is empty, returns empty -- doesn't fabricate results.
    """
    if not candidates:
        return []

    if _memory_pressure_high():
        return candidates[:top_n]

    model = get_reranker()
    texts = [c.get("text", "") for c in candidates]

    scores = list(model.rerank(query, texts))

    scored = list(zip(candidates, scores))
    scored.sort(key=lambda pair: pair[1], reverse=True)

    results = []
    for candidate, score in scored[:top_n]:
        enriched = dict(candidate)
        enriched["_rerank_score"] = float(score)
        results.append(enriched)

    return results


async def rerank_chunks_async(query: str, candidates: List[dict], top_n: int = 6) -> List[dict]:
    return await asyncio.to_thread(rerank_chunks, query, candidates, top_n)
