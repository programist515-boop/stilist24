"use client";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { formatKibbeFamily } from "@/lib/i18n/analysis";
import {
  formatCategory,
  formatOccasion,
  formatSlot,
} from "@/lib/i18n/wardrobe";
import type { IdentityLookMatch } from "@/lib/schemas/preferenceQuiz";

interface IdentityMatchStepProps {
  looks: IdentityLookMatch[];
  onComplete: () => void;
  completing: boolean;
  error: unknown;
}

/**
 * Final step of the identity quiz. For every look the user liked,
 * shows: original photo, what's already in the wardrobe, what's missing
 * (with shopping hints), and a completeness bar. The «Готово» button
 * triggers ``completeIdentityQuiz`` which writes the preference profile.
 */
export function IdentityMatchStep({
  looks,
  onComplete,
  completing,
  error,
}: IdentityMatchStepProps) {
  return (
    <div className="space-y-6">
      <SectionHeader
        title="Шаг 2 — собираем образы из вашего гардероба"
        description="Для каждого лайкнутого образа — что у вас уже есть и чего не хватает, чтобы повторить его из своего шкафа."
      />

      {looks.length === 0 ? (
        <Card className="border-amber-100 bg-amber-50">
          <p className="text-sm text-amber-900">
            Не удалось собрать ни одного образа. Похоже, в YAML нет лайкнутых
            луков — попробуйте начать квиз заново.
          </p>
        </Card>
      ) : (
        <div className="space-y-5">
          {looks.map((look) => (
            <LookMatchCard key={`${look.subtype}:${look.look_id}`} look={look} />
          ))}
        </div>
      )}

      {error ? (
        <ErrorState
          title="Не удалось зафиксировать типаж"
          error={error}
          onRetry={onComplete}
        />
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Button
          onClick={onComplete}
          loading={completing}
          loadingText="Фиксируем…"
          size="lg"
        >
          Готово, закрепить типаж
        </Button>
      </div>
    </div>
  );
}

function LookMatchCard({ look }: { look: IdentityLookMatch }) {
  const requiredCount = look.slot_order.length;
  const matchedCount = look.matched_items.length;
  const completenessPct = Math.round(look.completeness * 100);

  return (
    <Card padding="md" className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row">
        {look.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={look.image_url}
            alt={look.title}
            loading="lazy"
            className="h-48 w-full flex-shrink-0 rounded-xl bg-canvas-soft object-cover sm:h-40 sm:w-32"
          />
        ) : null}
        <div className="flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{look.title}</CardTitle>
            <Badge tone="neutral">{formatKibbeFamily(look.subtype)}</Badge>
            {look.occasion ? (
              <Badge tone="neutral">{formatOccasion(look.occasion)}</Badge>
            ) : null}
          </div>
          <CardSubtitle>
            Закрыто {matchedCount} из {requiredCount || matchedCount} слотов
          </CardSubtitle>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft">
            <div
              className="h-full bg-emerald-500 transition-[width]"
              style={{ width: `${completenessPct}%` }}
            />
          </div>
        </div>
      </div>

      {look.matched_items.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.12em] text-emerald-700">
            У вас уже есть
          </p>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {look.matched_items.map((m) => (
              <li
                key={`${m.slot}:${m.item_id}`}
                className="flex flex-col gap-1.5 rounded-xl border border-emerald-100 bg-emerald-50/40 p-2"
              >
                {m.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={m.image_url}
                    alt={formatCategory(m.category) || formatSlot(m.slot)}
                    loading="lazy"
                    className="h-24 w-full rounded-lg bg-canvas-soft object-cover"
                  />
                ) : (
                  <div className="flex h-24 w-full items-center justify-center rounded-lg bg-canvas-soft text-xs text-ink-muted">
                    {formatCategory(m.category) || formatSlot(m.slot)}
                  </div>
                )}
                <div className="text-xs">
                  <p className="font-medium text-ink">{formatSlot(m.slot)}</p>
                  {m.category ? (
                    <p className="text-ink-muted">{formatCategory(m.category)}</p>
                  ) : null}
                  {m.match_quality < 0.7 ? (
                    <p className="text-amber-700">подойдёт, но можно лучше</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {look.missing_slots.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.12em] text-red-700">
            Не хватает
          </p>
          <ul className="space-y-2 text-sm">
            {look.missing_slots.map((s) => (
              <li
                key={s.slot}
                className="flex flex-col gap-1 rounded-xl border border-red-100 bg-red-50/40 p-3"
              >
                <p className="text-xs font-medium uppercase tracking-[0.12em] text-red-700">
                  {formatSlot(s.slot)}
                </p>
                <p className="text-ink">{s.shopping_hint}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}
