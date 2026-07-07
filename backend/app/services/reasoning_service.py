"""
REASON stage. Consumes NormalizedChunks (already provenance-tagged),
runs validated structured extraction, then risk analysis that
explicitly cross-references tier 1/2 claims against tier 3/4 public
signal.
"""
import logging
from app.schemas.source_document import NormalizedChunk
from app.schemas.llm_outputs import (
    FinancialExtractionResult,
    RiskAnalysisResult,
    ExecutiveSummaryResult,
    RecommendationsResult,
    ReviewExtractionResult,
)
from app.prompts.extraction import build_extraction_prompt
from app.prompts.analysis import build_risk_analysis_prompt
from app.prompts.summary import build_executive_summary_prompt
from app.prompts.recommendations import build_recommendations_prompt
from app.prompts.reviews import build_review_extraction_prompt
from app.services.groq_service import call_groq_structured

logger = logging.getLogger(__name__)

# Source types where an individual's real opinion/experience shows up --
# institutional sources (BSEC, DSE/CSE, News, company website, etc.)
# essentially never contain a personal review, so they're excluded rather
# than left for the model to sift through (confirmed scope decision).
REVIEW_SOURCE_TYPES = {"reddit", "youtube", "job_listing", "glassdoor"}

# Cap how much raw text goes into a single prompt; prioritize
# highest-confidence-tier chunks first if we have to truncate.
MAX_CHUNKS_PER_PROMPT = 60

# Groq's free tier enforces a 12k tokens-per-minute cap that counts
# prompt AND max_tokens of a single request together -- a request over
# the cap is rejected outright with a 413, it doesn't just throttle.
# ~16k chars ≈ 4k tokens of chunk text keeps the largest prompt (risk
# analysis: chunks + extraction dump + schema) comfortably under it.
MAX_PROMPT_CHARS = 16000

# extract_reviews() gets a larger budget than the default -- its prompt
# skips the extracted-financials dump the risk/extraction prompts carry,
# and uses a smaller max_tokens (3000 vs 4000), so there's real headroom
# left under the 12k-token cap. Without this, widening the Reddit fetch
# (multi-query search, see reddit_source.py) just meant more chunks
# competing for the same ceiling -- confirmed 4 of 20 review-relevant
# chunks were being silently dropped at the old 16000-char budget.
REVIEW_MAX_PROMPT_CHARS = 22000


def _field(chunk, name: str):
    """Chunks can arrive as NormalizedChunk objects (fresh from /upload's
    in-memory pipeline) or as plain dict payloads (fetched back from
    Qdrant by /analyze's standalone re-run path) -- accept either."""
    return chunk[name] if isinstance(chunk, dict) else getattr(chunk, name)


def _chunks_to_tagged_dicts(chunks: list, max_chars: int = MAX_PROMPT_CHARS) -> list[dict]:
    """max_chars is overridable per caller -- extract_reviews() uses a
    higher budget than the default, since its prompt skips the extracted-
    financials dump analyze_risk()/extract_financials() carry and uses a
    smaller max_tokens (3000 vs 4000), leaving real headroom under Groq's
    12k-tokens-per-request cap that the default 16000 is tuned for."""
    sorted_chunks = sorted(chunks, key=lambda c: _field(c, "confidence_tier"))

    selected: list[dict] = []
    total_chars = 0
    for c in sorted_chunks[:MAX_CHUNKS_PER_PROMPT]:
        text = _field(c, "text")
        if selected and total_chars + len(text) > max_chars:
            break
        selected.append(
            {
                "source_name": _field(c, "source_name"),
                "confidence_tier": int(_field(c, "confidence_tier")),
                "text": text,
            }
        )
        total_chars += len(text)

    if len(selected) < len(chunks):
        logger.info(
            "Prompt budget: using %d of %d chunks (%d chars)",
            len(selected), len(chunks), total_chars,
        )
    return selected


def extract_financials(company_name: str, chunks: list[NormalizedChunk]) -> FinancialExtractionResult:
    """Step 7: structured extraction, validated against schema with retry."""
    if not chunks:
        logger.warning("No chunks available for %s -- returning empty extraction", company_name)
        return FinancialExtractionResult(
            company_name=company_name,
            extraction_notes="No usable source material was gathered for this investigation.",
        )

    tagged = _chunks_to_tagged_dicts(chunks)
    prompt = build_extraction_prompt(company_name, tagged)

    return call_groq_structured(
        prompt=prompt,
        schema=FinancialExtractionResult,
        system="You are a meticulous financial analyst who never reports unverified "
               "figures as fact and always flags data quality issues.",
    )


def analyze_risk(
    company_name: str,
    extraction: FinancialExtractionResult,
    chunks: list[NormalizedChunk],
) -> RiskAnalysisResult:
    """Step 10/11: risk analysis with explicit cross-referencing instruction."""
    tagged = _chunks_to_tagged_dicts(chunks)
    prompt = build_risk_analysis_prompt(
        company_name=company_name,
        extracted_financials=extraction.model_dump(),
        tagged_chunks=tagged,
    )

    return call_groq_structured(
        prompt=prompt,
        schema=RiskAnalysisResult,
        system="You are a skeptical due diligence analyst. Your job is to find what "
               "doesn't add up between what a company claims and what independent "
               "evidence shows. Never fabricate risks; ground every finding in the data.",
        max_tokens=4000,
    )


def generate_executive_summary(
    company_name: str,
    extraction: FinancialExtractionResult,
    risk: RiskAnalysisResult,
) -> ExecutiveSummaryResult:
    prompt = build_executive_summary_prompt(
        company_name=company_name,
        extracted_financials=extraction.model_dump(),
        risk_analysis=risk.model_dump(),
    )
    return call_groq_structured(
        prompt=prompt,
        schema=ExecutiveSummaryResult,
        system="You are writing for sophisticated investors. Be precise and specific.",
    )


def extract_reviews(company_name: str, chunks: list) -> ReviewExtractionResult:
    """Scans only personal-opinion sources (Reddit, YouTube, bdjobs.com,
    Glassdoor) for verbatim user/investor review quotes. Returns an empty
    result rather than calling Groq at all if none of those source types
    were gathered -- no point spending a call on guaranteed-empty input."""
    review_chunks = [c for c in chunks if _field(c, "source_type") in REVIEW_SOURCE_TYPES]

    if not review_chunks:
        return ReviewExtractionResult(
            reviews=[],
            extraction_notes="No personal-opinion sources (Reddit, YouTube, bdjobs.com, "
                              "Glassdoor) were gathered for this investigation.",
        )

    tagged = _chunks_to_tagged_dicts(review_chunks, max_chars=REVIEW_MAX_PROMPT_CHARS)
    prompt = build_review_extraction_prompt(company_name=company_name, tagged_chunks=tagged)

    result = call_groq_structured(
        prompt=prompt,
        schema=ReviewExtractionResult,
        system="You extract real, verbatim user opinions from source material. Never "
               "invent or paraphrase a quote, and never fabricate a review when none exists.",
        max_tokens=3000,
    )

    # Ground every review's source_name/source_type/confidence_tier/
    # origin_url in the actual chunk it came from, rather than trusting
    # the model to reproduce them -- it's asked to copy the quote
    # verbatim, so matching on "which chunk's text contains this quote"
    # is reliable; matching on source_name is NOT (observed the model
    # normalize "Reddit (via search)" down to "Reddit", which silently
    # broke a source_name-keyed lookup and let an invented source_type
    # like "Social Media" slip through instead of the real "reddit").
    grounded_reviews = []
    for review in result.reviews:
        match = next(
            (c for c in review_chunks if review.quote and review.quote in _field(c, "text")),
            None,
        )
        if match is None:
            logger.warning(
                "Review quote didn't match any source chunk verbatim -- dropping: %r",
                review.quote[:100],
            )
            continue
        review.source_name = _field(match, "source_name")
        review.source_type = _field(match, "source_type")
        review.confidence_tier = int(_field(match, "confidence_tier"))
        review.origin_url = _field(match, "origin_url")
        grounded_reviews.append(review)

    result.reviews = grounded_reviews
    return result


def generate_recommendations(
    company_name: str,
    extraction: FinancialExtractionResult,
    risk: RiskAnalysisResult,
) -> RecommendationsResult:
    prompt = build_recommendations_prompt(
        company_name=company_name,
        extracted_financials=extraction.model_dump(),
        risk_analysis=risk.model_dump(),
    )
    return call_groq_structured(
        prompt=prompt,
        schema=RecommendationsResult,
        system="Every recommendation must include a concrete rationale tied to the data. "
               "Never output a recommendation without explaining why.",
    )