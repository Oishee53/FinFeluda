"""
Review extraction prompt -- pulls verbatim user/investor opinion quotes
out of already-gathered personal-opinion sources (Reddit, YouTube,
bdjobs.com, Glassdoor). Callers filter chunks to those source types
before this ever sees them -- this prompt doesn't do that filtering
itself, since institutional sources (BSEC, DSE/CSE, News, company
website) essentially never contain a real individual's opinion and
would just invite the model to manufacture one.
"""
from app.prompts.extraction import CONFIDENCE_TIER_LEGEND


def build_review_extraction_prompt(company_name: str, tagged_chunks: list[dict]) -> str:
    chunks_block = "\n\n".join(
        f"[SOURCE: {c['source_name']} | TIER {c['confidence_tier']}]\n{c['text']}"
        for c in sorted(tagged_chunks, key=lambda c: c["confidence_tier"])
    )

    return f"""
Extract user/investor reviews and opinions about: {company_name}

{CONFIDENCE_TIER_LEGEND}

--- SOURCE MATERIAL (Reddit, YouTube, bdjobs.com, Glassdoor only) ---
{chunks_block}
--- END SOURCE MATERIAL ---

Your task:
1. Find passages that read as an individual person's real opinion or experience --
   a complaint, praise, a described experience (as a customer, employee, or investor),
   not a general fact, advertisement, or job-posting boilerplate.
2. For each one, copy the actual quoted text into `quote` -- do NOT paraphrase or
   summarize it. If the source material doesn't contain an actual quotable line,
   don't include it.
3. Tag `sentiment` honestly based on what the quote actually expresses (positive,
   negative, neutral, or mixed) -- don't force everything into positive/negative.
4. Set `reviewer_context` to who/where this came from, in plain language (e.g.
   "Reddit user in r/bangladesh", "bdjobs.com job listing mentioning compensation").
5. If nothing in the source material actually reads as a personal opinion or
   experience, return an empty `reviews` list and say so in `extraction_notes`
   rather than inventing one.
"""
