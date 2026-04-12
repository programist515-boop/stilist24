"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { QueryState } from "@/components/ui/QueryState";
import { EmptyState } from "@/components/ui/EmptyState";
import { InsightCard } from "@/components/insights/InsightCard";
import { getWeeklyInsights } from "@/lib/api/insights";

function formatDate(value?: string): string | null {
  if (!value) return null;
  try {
    return new Date(value).toLocaleDateString("ru-RU", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return value;
  }
}

export default function InsightsPage() {
  const query = useQuery({
    queryKey: ["insights", "weekly"],
    queryFn: getWeeklyInsights,
  });

  const data = query.data;
  const window = data?.window;
  const behavior = data?.behavior;
  const patterns = data?.preference_patterns;
  const underused = data?.underused_items ?? [];
  const underusedCategories = data?.underused_categories ?? [];
  const styleShift = data?.style_shift;
  const notes = data?.notes ?? [];

  const noActivity =
    !!behavior && behavior.total_events === 0 && underused.length === 0;

  return (
    <>
      <PageHeader
        eyebrow="Аналитика"
        title="Что мы заметили"
        subtitle={
          window?.start && window?.end
            ? `${formatDate(window.start)} → ${formatDate(window.end)}`
            : "Закономерности за последние семь дней."
        }
      />

      <QueryState
        isLoading={query.isLoading}
        isError={query.isError}
        error={query.error}
        onRetry={() => query.refetch()}
      >
        {noActivity ? (
          <EmptyState
            title="Пока нечего показать"
            hint="Поработайте с разделами «Сегодня», «Образы» и «Примерка» несколько дней — и мы начнём замечать закономерности."
          />
        ) : (
          <>
            {behavior ? (
              <section>
                <SectionHeader title="Активность" />
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <InsightCard
                    title="Всего событий"
                    value={behavior.total_events}
                  />
                  <InsightCard
                    title="Лайков на образы"
                    value={behavior.outfits_liked}
                  />
                  <InsightCard
                    title="Образов надето"
                    value={behavior.outfits_worn}
                  />
                  <InsightCard
                    title="Вещей надето"
                    value={behavior.items_worn}
                  />
                  <InsightCard
                    title="Лайков на вещи"
                    value={behavior.items_liked}
                  />
                  <InsightCard
                    title="Дизлайков на вещи"
                    value={behavior.items_disliked}
                  />
                  <InsightCard
                    title="Пропущенных вещей"
                    value={behavior.items_ignored}
                  />
                  <InsightCard
                    title="Примерок"
                    value={behavior.tryons_opened}
                  />
                </div>
              </section>
            ) : null}

            {patterns && patterns.patterns.length > 0 ? (
              <section>
                <SectionHeader title="Предпочтения" />
                <Card>
                  <ul className="space-y-2 text-sm text-ink">
                    {patterns.patterns.map((line, i) => (
                      <li key={i}>· {line}</li>
                    ))}
                  </ul>
                </Card>
              </section>
            ) : null}

            {styleShift && styleShift.lines.length > 0 ? (
              <section>
                <SectionHeader title="Сдвиг стиля" />
                <Card>
                  <ul className="space-y-2 text-sm text-ink">
                    {styleShift.lines.map((line, i) => (
                      <li key={i}>· {line}</li>
                    ))}
                  </ul>
                </Card>
              </section>
            ) : null}

            {underused.length > 0 || underusedCategories.length > 0 ? (
              <section>
                <SectionHeader
                  title="Редко используете"
                  description="Вещи и категории, к которым вы давно не возвращались."
                />
                <Card>
                  {underusedCategories.length > 0 ? (
                    <div className="mb-4 flex flex-wrap gap-2">
                      {underusedCategories.map((c) => (
                        <Badge key={c} tone="warning">
                          {c}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                  {underused.length > 0 ? (
                    <ul className="space-y-2 text-sm">
                      {underused.slice(0, 8).map((item) => (
                        <li
                          key={item.id}
                          className="flex items-center justify-between gap-3"
                        >
                          <span className="capitalize text-ink">
                            {item.category}
                          </span>
                          <span className="text-xs text-ink-muted">
                            {item.reason}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </Card>
              </section>
            ) : null}

            {notes.length > 0 ? (
              <section>
                <SectionHeader title="Заметки" />
                <Card>
                  <ul className="space-y-1.5 text-sm text-ink-muted">
                    {notes.map((n, i) => (
                      <li key={i}>· {n}</li>
                    ))}
                  </ul>
                </Card>
              </section>
            ) : null}
          </>
        )}
      </QueryState>
    </>
  );
}
