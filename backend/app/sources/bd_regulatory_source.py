"""
Bangladesh regulatory, exchange, and chamber-of-commerce sources.

None of dsebd.org (DSE), cse.com.bd (CSE), or roc.gov.bd (RJSC) are
directly fetchable -- all three fail with SSL cert errors confirmed via
direct httpx requests (missing intermediate cert for the two exchanges,
self-signed cert for RJSC). BSEC (sec.gov.bd), Bangladesh Bank
(bb.org.bd), and MCCI (mccibd.org) ARE directly reachable but have no
per-company search of their own -- they're regulatory/directory hubs,
not databases (confirmed by reading their actual navigation structure).

Every fetcher here therefore goes through Serper's indexed search
(serper_site_search, same mechanism as bdjobs_source.py/reddit_source.py)
scoped to the relevant domain, rather than fetching the site directly.
This sidesteps both problems at once: Google's crawler doesn't share
this app's TLS trust chain, and its index acts as the missing
"search by company name" feature these sites don't provide themselves.

Verified live before writing this: dsebd.org and cse.com.bd both
returned real per-company results (a DSE filing page, a CSE audit PDF)
this way. roc.gov.bd returned zero results -- RJSC content doesn't
appear to be indexed at all, a different problem than the TLS one, so
it stays a documented "not fetched" stub rather than pretending the
search path fixes it too.

BSEC/Bangladesh Bank/MCCI additionally enrich their top search results
with full content (content_fetch_utils.enrich_with_full_content) --
verified live that BSEC's PDF filings (e.g. an IPO prospectus) download
and parse correctly, turning a 250-char snippet into thousands of chars
of real filing text. DSE/CSE/RJSC don't get this treatment since their
domains are already known unreachable/unindexed -- there's nothing a
follow-up fetch would find that the search step didn't already fail on.
"""
from app.sources.base import BaseFetcher
from app.schemas.source_document import SourceDocument, SourceType
from app.sources.serper_utils import serper_site_search, organic_results_to_text, site_search_url
from app.sources.content_fetch_utils import enrich_with_full_content


class _SerperSiteFetcher(BaseFetcher):
    """Shared shape for 'search this domain via Serper, or explain why
    not' -- subclasses just set domain/display_name/not_found_hint."""
    domain: str
    display_name: str
    not_found_hint: str = ""
    # Only set True for domains confirmed directly reachable (BSEC/BB/MCCI)
    # -- DSE/CSE/RJSC are known TLS-broken or unindexed, so attempting a
    # full-content fetch there would just be a guaranteed-failed extra
    # request per result for zero benefit.
    fetch_full_content_enabled: bool = False

    async def _fetch_impl(self, company_name: str, **kwargs) -> SourceDocument:
        api_key = kwargs.get("serper_api_key")
        if not api_key:
            return SourceDocument(
                source_type=self.source_type,
                source_name=self.display_name,
                raw_text="",
                fetch_succeeded=False,
                fetch_error="SERPER_API_KEY not configured -- skipping",
            )

        results = await serper_site_search(self.domain, company_name, api_key)
        if self.fetch_full_content_enabled and results:
            results = await enrich_with_full_content(results)
        if not results:
            return SourceDocument(
                source_type=self.source_type,
                source_name=self.display_name,
                raw_text="",
                fetch_succeeded=False,
                fetch_error=f"no indexed {self.domain} results for this company. {self.not_found_hint}".strip(),
            )

        return SourceDocument(
            source_type=self.source_type,
            source_name=self.display_name,
            origin_url=site_search_url(self.domain, company_name),
            title=f"{self.display_name} results for {company_name}",
            raw_text=organic_results_to_text(results),
            fetch_succeeded=True,
        )


class DSEFetcher(_SerperSiteFetcher):
    source_type = SourceType.DSE_FILING
    domain = "dsebd.org"
    display_name = "Dhaka Stock Exchange (DSE)"
    not_found_hint = "Direct access also blocked by a TLS cert error on their end (missing intermediate cert)."


class CSEFetcher(_SerperSiteFetcher):
    source_type = SourceType.CSE_FILING
    domain = "cse.com.bd"
    display_name = "Chittagong Stock Exchange (CSE)"
    not_found_hint = "Direct access also blocked by a TLS cert error on their end (missing intermediate cert)."


class RJSCFetcher(_SerperSiteFetcher):
    source_type = SourceType.RJSC_RECORD
    domain = "roc.gov.bd"
    display_name = "RJSC (Registrar of Joint Stock Companies)"
    not_found_hint = "RJSC content doesn't appear to be Google-indexed at all; direct access is also blocked by a self-signed TLS cert."


class BSECFetcher(_SerperSiteFetcher):
    source_type = SourceType.BSEC_FILING
    domain = "sec.gov.bd"
    display_name = "Bangladesh Securities and Exchange Commission (BSEC)"
    fetch_full_content_enabled = True


class BangladeshBankFetcher(_SerperSiteFetcher):
    source_type = SourceType.BANGLADESH_BANK
    domain = "bb.org.bd"
    display_name = "Bangladesh Bank"
    fetch_full_content_enabled = True


class MCCIFetcher(_SerperSiteFetcher):
    source_type = SourceType.CHAMBER_DIRECTORY
    domain = "mccibd.org"
    display_name = "Metropolitan Chamber of Commerce and Industry (MCCI)"
    fetch_full_content_enabled = True
