import { Badge } from "@/components/ui/Badge";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import type { UserAnalysis } from "@/lib/schemas";
import {
  formatColorAxisLabel,
  formatColorAxisValue,
  formatKibbeFamily,
  formatPhotoSlot,
  formatSeason,
} from "@/lib/i18n/analysis";

function formatPercent(value: number | undefined): string {
  if (typeof value !== "number") return "—";
  return `${Math.round(value * 100)}%`;
}

function topEntries(
  scores: Record<string, number> | undefined,
  limit = 4
): Array<[string, number]> {
  if (!scores) return [];
  return Object.entries(scores)
    .sort(([, a], [, b]) => b - a)
    .slice(0, limit);
}

export function AnalysisResultCard({ result }: { result: UserAnalysis }) {
  const kibbe = result.kibbe;
  const color = result.color;
  const styleVector = result.style_vector;
  const photos = result.photos ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <div className="flex items-center justify-between">
          <CardTitle>Тип внешности</CardTitle>
          {kibbe?.confidence !== undefined ? (
            <Badge>Уверенность {formatPercent(kibbe.confidence)}</Badge>
          ) : null}
        </div>
        <CardSubtitle className="mt-1">
          Kibbe-семейство, считанное с ваших фото
        </CardSubtitle>
        <p className="mt-4 font-display text-3xl tracking-tight">
          {kibbe?.main_type ? formatKibbeFamily(kibbe.main_type) : "—"}
        </p>
        {topEntries(kibbe?.family_scores).length > 0 ? (
          <ul className="mt-4 space-y-2">
            {topEntries(kibbe?.family_scores).map(([name, value]) => (
              <li key={name} className="text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-ink">{formatKibbeFamily(name)}</span>
                  <span className="text-ink-muted">{formatPercent(value)}</span>
                </div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-accent-soft">
                  <div
                    className="h-full bg-ink"
                    style={{ width: `${Math.round(value * 100)}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>

      <Card>
        <div className="flex items-center justify-between">
          <CardTitle>Цвет</CardTitle>
          {color?.confidence !== undefined ? (
            <Badge>Уверенность {formatPercent(color.confidence)}</Badge>
          ) : null}
        </div>
        <CardSubtitle className="mt-1">Сезонная палитра</CardSubtitle>
        <p className="mt-4 font-display text-3xl tracking-tight">
          {formatSeason(color?.season_top_1)}
        </p>
        {color?.axes ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(color.axes).map(([k, v]) => (
              <Badge key={k}>
                <span className="text-ink-muted">
                  {formatColorAxisLabel(k)}
                </span>
                <span className="ml-1 font-semibold text-ink">
                  {formatColorAxisValue(v)}
                </span>
              </Badge>
            ))}
          </div>
        ) : null}
      </Card>

      <Card className="lg:col-span-2">
        <CardTitle>Стилевой вектор</CardTitle>
        <CardSubtitle className="mt-1">
          Где находится ваша отправная точка по основным осям
        </CardSubtitle>
        {styleVector && Object.keys(styleVector).length > 0 ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {Object.entries(styleVector).map(([name, value]) => (
              <div
                key={name}
                className="rounded-xl border border-canvas-border p-4"
              >
                <p className="text-xs font-medium tracking-wide text-ink-muted">
                  {formatKibbeFamily(name)}
                </p>
                <p className="mt-1 font-display text-2xl">
                  {formatPercent(value)}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-ink-muted">Стилевой вектор пока не рассчитан.</p>
        )}
      </Card>

      {photos.length > 0 ? (
        <Card className="lg:col-span-2">
          <CardTitle>Сохранённые фото</CardTitle>
          <CardSubtitle className="mt-1">
            Привязаны к вашему аккаунту — используются примеркой.
          </CardSubtitle>
          <div className="mt-4 grid grid-cols-3 gap-3">
            {photos.map((photo) => {
              const slotLabel = formatPhotoSlot(photo.slot);
              return (
                <div
                  key={photo.id}
                  className="overflow-hidden rounded-xl border border-canvas-border bg-accent-soft"
                >
                  <div className="aspect-[3/4] w-full">
                    {photo.image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={photo.image_url}
                        alt={slotLabel}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-xs text-ink-muted">
                        {slotLabel}
                      </div>
                    )}
                  </div>
                  <div className="px-3 py-2 text-xs text-ink-muted">
                    <span className="text-ink">{slotLabel}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
