"use client";

import { useMutation } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { sendColorTryOnFeedback } from "@/lib/api/colorTryOn";
import type { ColorTryOnVariant } from "@/lib/schemas/colorTryOn";

interface ColorTryOnGalleryProps {
  itemId: string;
  variants: ColorTryOnVariant[];
  quality: string;
}

/**
 * Галерея сгенерированных цветовых вариантов.
 * По клику на 👍/👎 отправляет feedback в `personalization_service`.
 */
export function ColorTryOnGallery({
  itemId,
  variants,
  quality,
}: ColorTryOnGalleryProps) {
  if (variants.length === 0) {
    return (
      <Card>
        <CardTitle>Нет палитры</CardTitle>
        <CardSubtitle className="mt-2">
          Чтобы примерить вещь в ваших цветах, сначала пройдите анализ цветотипа.
        </CardSubtitle>
      </Card>
    );
  }

  const qualityHint =
    quality === "low"
      ? "Палитра не определена, показываем общие цвета."
      : quality === "medium"
      ? "Часть вариантов — пробный рендер."
      : null;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink">
            Примерь в цветах твоей палитры
          </h2>
          {qualityHint ? (
            <p className="mt-1 text-xs text-ink-muted">{qualityHint}</p>
          ) : null}
        </div>
        <Badge tone="neutral">{variants.length} вариантов</Badge>
      </div>

      <div className="grid gap-4 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
        {variants.map((variant) => (
          <ColorTryOnCard
            key={variant.color_hex}
            itemId={itemId}
            variant={variant}
          />
        ))}
      </div>
    </section>
  );
}

function ColorTryOnCard({
  itemId,
  variant,
}: {
  itemId: string;
  variant: ColorTryOnVariant;
}) {
  const feedbackMutation = useMutation({
    mutationFn: (liked: boolean) =>
      sendColorTryOnFeedback(itemId, {
        variant_hex: variant.color_hex,
        liked,
      }),
  });

  const sent = feedbackMutation.isSuccess
    ? feedbackMutation.variables
    : undefined;

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-canvas-border bg-canvas-card shadow-card">
      <div className="relative aspect-square w-full bg-accent-soft">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={variant.image_url}
          alt={variant.color_name}
          className="h-full w-full object-cover"
        />
        <span
          className="absolute bottom-2 right-2 inline-block h-6 w-6 rounded-full border border-white/70 shadow"
          style={{ backgroundColor: variant.color_hex }}
          aria-label={variant.color_name}
          title={variant.color_hex}
        />
      </div>
      <div className="flex flex-col gap-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium text-ink">
            {variant.color_name}
          </span>
          <span className="font-mono text-[11px] uppercase text-ink-muted">
            {variant.color_hex}
          </span>
        </div>
        <div className="flex gap-2">
          <Button
            variant={sent === true ? "primary" : "secondary"}
            size="sm"
            className="flex-1"
            onClick={() => feedbackMutation.mutate(true)}
            disabled={feedbackMutation.isPending}
            aria-label={`Нравится ${variant.color_name}`}
          >
            Нравится
          </Button>
          <Button
            variant={sent === false ? "primary" : "secondary"}
            size="sm"
            className="flex-1"
            onClick={() => feedbackMutation.mutate(false)}
            disabled={feedbackMutation.isPending}
            aria-label={`Не нравится ${variant.color_name}`}
          >
            Не моё
          </Button>
        </div>
        {feedbackMutation.isError ? (
          <p className="text-[11px] text-red-600">Не удалось сохранить отзыв.</p>
        ) : null}
      </div>
    </div>
  );
}
