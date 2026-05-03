import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { ScoreBadge } from "./ScoreBadge";
import { formatCategory } from "@/lib/i18n/wardrobe";
import type { Outfit } from "@/lib/schemas";

const OVERALL_KEY = "overall";

const PRIORITY_SCORE_KEYS = [
  "color_harmony",
  "silhouette_balance",
  "line_consistency",
  "style_consistency",
  "occasion_fit",
] as const;

const SCORE_LABEL: Record<(typeof PRIORITY_SCORE_KEYS)[number], string> = {
  color_harmony: "цвет",
  silhouette_balance: "силуэт",
  line_consistency: "линии",
  style_consistency: "стиль",
  occasion_fit: "повод",
};

interface OutfitCardProps {
  outfit: Outfit;
  imageById: Map<string, string>;
}

export function OutfitCard({ outfit, imageById }: OutfitCardProps) {
  const reasons = Array.isArray(outfit.explanation)
    ? outfit.explanation
    : outfit.explanation
    ? [outfit.explanation]
    : outfit.scoring_reasons ?? [];

  const scores = outfit.scores ?? {};
  const overall = scores[OVERALL_KEY];
  const otherScores = PRIORITY_SCORE_KEYS.filter(
    (k) => typeof scores[k] === "number"
  );

  // Auto-open the rationale when the list is short — no need to hide one line.
  const reasonsOpen = reasons.length > 0 && reasons.length <= 2;

  return (
    <Card padding="md" className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-3">
        <div>
          <CardTitle>Образ</CardTitle>
          {outfit.generation?.template ? (
            <CardSubtitle className="mt-1 capitalize">
              {outfit.generation.template.replace(/_/g, " ")}
            </CardSubtitle>
          ) : null}
        </div>
        {typeof overall === "number" ? (
          <div className="text-right">
            <p className="font-display text-3xl leading-none text-ink">
              {Math.round(overall * 100)}
            </p>
            <p className="text-[10px] uppercase tracking-wide text-ink-muted">
              оценка
            </p>
          </div>
        ) : null}
      </div>

      <ul className="mt-4 grid grid-cols-3 gap-2">
        {outfit.items.map((item, idx) => {
          const image =
            item.image_url ?? (item.id ? imageById.get(item.id) : undefined);
          return (
            <li
              key={item.id ?? idx}
              className="overflow-hidden rounded-xl border border-canvas-border bg-accent-soft"
            >
              <div className="aspect-square w-full">
                {image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={image}
                    alt={item.name ?? formatCategory(item.category) ?? ""}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center px-1 text-center text-[10px] capitalize text-ink-muted">
                    {item.name ?? formatCategory(item.category) ?? "вещь"}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {otherScores.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {otherScores.map((k) => (
            <ScoreBadge
              key={k}
              label={SCORE_LABEL[k]}
              value={scores[k]!}
            />
          ))}
        </div>
      ) : null}

      {reasons.length > 0 ? (
        <details
          className="mt-4 group"
          open={reasonsOpen}
        >
          <summary className="flex cursor-pointer items-center gap-1 text-xs font-medium text-ink-muted transition-colors hover:text-ink">
            <span>Почему этот образ</span>
            <span className="transition-transform group-open:rotate-90">›</span>
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-ink-muted">
            {reasons.slice(0, 6).map((r, i) => (
              <li key={i}>· {r}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}

export function OutfitCardSkeleton() {
  return (
    <Card padding="md" className="animate-pulse">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <div className="h-4 w-20 rounded-full bg-canvas-border/70" />
          <div className="h-3 w-28 rounded-full bg-canvas-border/60" />
        </div>
        <div className="h-9 w-12 rounded-md bg-canvas-border/60" />
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <div className="aspect-square rounded-xl bg-canvas-border/60" />
        <div className="aspect-square rounded-xl bg-canvas-border/60" />
        <div className="aspect-square rounded-xl bg-canvas-border/60" />
      </div>
      <div className="mt-4 flex gap-1.5">
        <div className="h-6 w-16 rounded-full bg-canvas-border/60" />
        <div className="h-6 w-20 rounded-full bg-canvas-border/60" />
      </div>
    </Card>
  );
}
