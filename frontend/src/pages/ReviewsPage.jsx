import { useParams } from "react-router-dom";
import { PageWrapper } from "../components/layout/PageWrapper";
import { Sidebar } from "../components/layout/Sidebar";
import { Card } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { useInvestigation, useInvestigationReviews } from "../hooks/useInvestigation";
import { CONFIDENCE_TIER_META, SENTIMENT_META, formatSourceType } from "../lib/utils";

const SENTIMENT_ORDER = ["negative", "mixed", "neutral", "positive"];

export function ReviewsPage() {
  const { id } = useParams();
  const { data: investigation } = useInvestigation(id);
  const { data: reviews, isLoading, isError, error } = useInvestigationReviews(id);

  const bySentiment = {};
  for (const review of reviews ?? []) {
    (bySentiment[review.sentiment] ??= []).push(review);
  }
  const sentiments = SENTIMENT_ORDER.filter((s) => bySentiment[s]?.length);

  return (
    <PageWrapper>
      <div className="mb-8">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand">Reviews</p>
        <h1 className="mt-1 font-display text-3xl font-semibold text-ink">
          {investigation?.company_name || "This investigation"}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          Verbatim user and investor opinions found in gathered sources (Reddit, YouTube,
          bdjobs.com) — real quotes, not a summary, each tagged with where it came from.
        </p>
      </div>

      <div className="flex gap-8">
        <Sidebar investigationId={id} companyName={investigation?.company_name} />

        <div className="flex min-w-0 flex-1 flex-col gap-6">
          {isLoading && (
            <div className="flex flex-col gap-4">
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          )}

          {isError && (
            <Card tier="risk-critical">
              <p className="font-medium text-ink">Couldn't load reviews.</p>
              <p className="mt-1 text-sm text-ink-muted">{error?.message}</p>
            </Card>
          )}

          {!isLoading && !isError && (reviews?.length ?? 0) === 0 && (
            <Card>
              <EmptyState>
                No reviews found in gathered sources yet. This fills in once analysis has
                run and finds real opinions in Reddit, YouTube, or bdjobs.com content.
              </EmptyState>
            </Card>
          )}

          {sentiments.map((sentiment) => {
            const meta = SENTIMENT_META[sentiment] ?? SENTIMENT_META.neutral;
            return (
              <Card key={sentiment} tier={meta.color}>
                <div className="mb-4 flex items-center gap-2">
                  <Badge color={meta.color}>{meta.label}</Badge>
                </div>

                <ul className="flex flex-col divide-y divide-line">
                  {bySentiment[sentiment].map((review, index) => {
                    const tierMeta = CONFIDENCE_TIER_META[review.confidence_tier] ?? CONFIDENCE_TIER_META[4];
                    return (
                      <li key={index} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
                        <p className="text-sm italic text-ink">“{review.quote}”</p>
                        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                          <Badge color={tierMeta.color}>{formatSourceType(review.source_type)}</Badge>
                          <span>{review.source_name}</span>
                          {review.reviewer_context && (
                            <>
                              <span>·</span>
                              <span>{review.reviewer_context}</span>
                            </>
                          )}
                          {review.origin_url && (
                            <>
                              <span>·</span>
                              <a
                                href={review.origin_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="font-medium text-brand hover:text-brand-deep"
                              >
                                Visit source →
                              </a>
                            </>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </Card>
            );
          })}
        </div>
      </div>
    </PageWrapper>
  );
}
