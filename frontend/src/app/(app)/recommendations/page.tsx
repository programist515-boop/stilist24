"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/Card";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { QueryState } from "@/components/ui/QueryState";
import { getRecommendationGuide } from "@/lib/api/recommendations";
import type { RecommendationSection } from "@/lib/schemas";

/**
 * Recommendations page — curated stylist guide keyed to the user's
 * Kibbe family, color profile and top style-vector tags.
 *
 * The content is served whole by `GET /recommendations/style-guide`
 * and cached for 5 minutes client-side (the backend projection is
 * deterministic, so a short cache is safe and keeps re-navigations
 * instant).
 *
 * Three page states:
 *
 * 1. **loading** — skeleton cards matching the section layout.
 * 2. **empty** — user has no resolvable Kibbe family yet. The backend
 *    sends an empty `sections` list plus a note; we render an
 *    `EmptyState` pointing to `/analyze`.
 * 3. **loaded** — identity card + ordered section cards + closing rule.
 */
export default function RecommendationsPage() {
  const guide = useQuery({
    queryKey: ["recommendations", "style-guide"],
    queryFn: getRecommendationGuide,
    staleTime: 5 * 60_000,
  });

  const data = guide.data;
  const sections = data?.sections ?? [];
  const identity = data?.identity;
  const hasIdentity = Boolean(identity?.kibbe_family);

  return (
    <>
      <PageHeader
        eyebrow="Рекомендации"
        title="Ваш персональный стилист-гид"
        subtitle="Краткий editorial на основе вашей типологии Kibbe, цветового профиля и ваших предпочтений — что носить, как подчёркивать, чего избегать."
      />

      <QueryState
        isLoading={guide.isLoading}
        isError={guide.isError}
        error={guide.error}
        onRetry={() => guide.refetch()}
        isEmpty={!guide.isLoading && !hasIdentity}
        emptyTitle="Пока нет данных для гида"
        emptyHint={
          data?.notes?.[0] ??
          "Чтобы получить персональные рекомендации, сначала пройдите анализ — нам нужно определить вашу типологию."
        }
        emptyAction={
          <Link href="/analyze">
            <Button variant="primary" size="md">
              Пройти анализ
            </Button>
          </Link>
        }
        loadingFallback={<RecommendationsSkeleton />}
      >
        {data ? (
          <div className="space-y-6">
            <IdentityCard
              kibbeType={identity?.kibbe_type ?? identity?.kibbe_family ?? null}
              styleKey={identity?.style_key ?? null}
              colorSummary={identity?.color_profile_summary ?? null}
              summary={data.summary}
              topTags={identity?.top_style_tags ?? []}
            />

            <div className="grid gap-5 lg:grid-cols-2">
              {sections.map((section) => (
                <SectionCard key={section.key} section={section} />
              ))}
            </div>

            {data.closing_note ? (
              <Card padding="md" className="bg-accent-soft/40">
                <SectionHeader
                  title="Правило образа"
                  description="Короткий ориентир на каждый день."
                  className="pb-3"
                />
                <p className="text-sm leading-relaxed text-ink">
                  {data.closing_note}
                </p>
              </Card>
            ) : null}

            {data.notes.length > 0 ? (
              <section>
                <SectionHeader
                  title="Заметки стилиста"
                  description="Контекст, на котором построен этот гид."
                />
                <Card padding="md">
                  <ul className="space-y-1.5 text-sm text-ink-muted">
                    {data.notes.map((n, i) => (
                      <li key={i}>· {n}</li>
                    ))}
                  </ul>
                </Card>
              </section>
            ) : null}
          </div>
        ) : null}
      </QueryState>
    </>
  );
}

/* ------------------------------------------------------ identity card */

function IdentityCard({
  kibbeType,
  styleKey,
  colorSummary,
  summary,
  topTags,
}: {
  kibbeType: string | null;
  styleKey: string | null;
  colorSummary: string | null;
  summary: string;
  topTags: string[];
}) {
  return (
    <Card padding="lg">
      <div className="flex flex-wrap items-start gap-2">
        {kibbeType ? (
          <Badge tone="default" className="uppercase tracking-[0.14em]">
            {kibbeType}
          </Badge>
        ) : null}
        {colorSummary ? (
          <Badge tone="neutral">{colorSummary}</Badge>
        ) : null}
      </div>

      {styleKey ? (
        <p className="mt-4 font-display text-2xl tracking-tight text-ink sm:text-3xl">
          {styleKey}
        </p>
      ) : null}

      {summary ? (
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-ink-muted">
          {summary}
        </p>
      ) : null}

      {topTags.length > 0 ? (
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-canvas-border pt-4">
          <span className="text-xs font-medium uppercase tracking-[0.14em] text-ink-muted">
            Ваши акценты
          </span>
          {topTags.map((tag) => (
            <Badge key={tag} tone="neutral">
              {tag}
            </Badge>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------- section card */

function SectionCard({ section }: { section: RecommendationSection }) {
  return (
    <Card padding="md" className="flex flex-col gap-4">
      <SectionHeader
        title={section.title}
        description={section.description || undefined}
        className="pb-0"
      />

      {section.recommended.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.12em] text-emerald-700">
            Выбирайте
          </p>
          <ul className="space-y-1.5 text-sm leading-relaxed text-ink">
            {section.recommended.map((line, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-[0.55rem] h-1 w-1 flex-shrink-0 rounded-full bg-emerald-600" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {section.avoid.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.12em] text-red-700">
            Избегайте
          </p>
          <ul className="space-y-1.5 text-sm leading-relaxed text-ink-muted">
            {section.avoid.map((line, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-[0.55rem] h-1 w-1 flex-shrink-0 rounded-full bg-red-600" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

/* ----------------------------------------------------------- skeleton */

function RecommendationsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="h-44 animate-pulse rounded-2xl border border-canvas-border bg-canvas-card" />
      <div className="grid gap-5 lg:grid-cols-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-52 animate-pulse rounded-2xl border border-canvas-border bg-canvas-card"
          />
        ))}
      </div>
    </div>
  );
}
