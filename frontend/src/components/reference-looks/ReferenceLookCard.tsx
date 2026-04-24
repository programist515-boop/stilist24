"use client";

import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import type { ReferenceLook } from "@/lib/schemas/referenceLooks";

interface Props {
  look: ReferenceLook;
}

/**
 * Карточка одного референсного лука подтипа.
 *
 * Сверху — название + картинка, под ней три колонки:
 *   1. Закрытые слоты (matched_items) — item_id + score.
 *   2. Пустые слоты (missing_slots) — shopping_hint в компактном виде.
 *   3. Completeness-метрика.
 */
export function ReferenceLookCard({ look }: Props) {
  const completenessPct = Math.round(look.completeness * 100);

  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle className="truncate">{look.title}</CardTitle>
          {look.occasion ? (
            <CardSubtitle className="mt-1">{look.occasion}</CardSubtitle>
          ) : null}
        </div>
        <Badge tone={completenessPct === 100 ? "success" : "default"}>
          {completenessPct}%
        </Badge>
      </div>

      {look.image_url ? (
        <img
          src={look.image_url}
          alt={look.title}
          className="h-48 w-full rounded-lg object-cover"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
      ) : null}

      {look.description ? (
        <p className="text-sm text-ink-muted">{look.description}</p>
      ) : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
            Из твоего гардероба ({look.matched_items.length})
          </h4>
          {look.matched_items.length === 0 ? (
            <p className="text-sm text-ink-muted">Пока ничего не подошло.</p>
          ) : (
            <ul className="space-y-1.5">
              {look.matched_items.map((mi) => (
                <li key={`${mi.slot}-${mi.item_id}`} className="text-sm">
                  <span className="font-medium">{mi.slot}:</span>{" "}
                  <span className="text-ink-muted">
                    #{mi.item_id.slice(0, 8)} (
                    {Math.round(mi.match_quality * 100)}%)
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
            Докупить ({look.missing_slots.length})
          </h4>
          {look.missing_slots.length === 0 ? (
            <p className="text-sm text-ink-muted">Всё есть!</p>
          ) : (
            <ul className="space-y-1.5">
              {look.missing_slots.map((ms) => (
                <li key={ms.slot} className="text-sm">
                  <span className="font-medium">{ms.slot}:</span>{" "}
                  <span className="text-ink-muted">{ms.shopping_hint}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Card>
  );
}
