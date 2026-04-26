"use client";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { QueryState } from "@/components/ui/QueryState";
import { Skeleton } from "@/components/ui/Skeleton";
import { PageHeader } from "@/components/layout/PageHeader";
import { ColorTryOnGallery } from "@/components/color-tryon/ColorTryOnGallery";
import { generateColorTryOn, getColorTryOn } from "@/lib/api/colorTryOn";

/**
 * Страница «Примерь в цветах твоей палитры».
 *
 * Флоу:
 *   1. Заходим на `/wardrobe/{id}/color-tryon`.
 *   2. GET /color-tryon/{itemId} (сервер сам сгенерит при первом визите).
 *   3. Галерея. Клик по 👍/👎 → POST /color-tryon/{itemId}/feedback.
 *   4. Кнопка «Перегенерировать» — ручной POST /color-tryon/{itemId}.
 */
export default function ColorTryOnPage() {
  const params = useParams<{ id: string }>();
  const itemId = params?.id ?? "";

  const query = useQuery({
    queryKey: ["color-tryon", itemId],
    queryFn: () => getColorTryOn(itemId),
    enabled: Boolean(itemId),
    // Перегенерация долгая — не автообновляем.
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
  });

  const regenerate = useMutation({
    mutationFn: () => generateColorTryOn(itemId),
    onSuccess: (data) => query.refetch().catch(() => data),
  });

  return (
    <>
      <PageHeader
        eyebrow="Гардероб"
        title="Примерь в цветах твоей палитры"
        subtitle="Мы перекрасим эту вещь в каждый цвет из твоей палитры цветотипа и покажем, как она будет смотреться."
      />

      <div className="mb-4">
        <Link
          href="/wardrobe"
          className="text-sm text-ink-muted underline-offset-2 hover:underline"
        >
          ← Назад к гардеробу
        </Link>
      </div>

      <QueryState
        isLoading={query.isLoading}
        isError={query.isError}
        error={query.error}
        onRetry={() => query.refetch()}
        loadingFallback={<ColorTryOnSkeleton />}
      >
        {query.data ? (
          <div className="space-y-6">
            <ColorTryOnGallery
              itemId={itemId}
              variants={query.data.variants}
              quality={query.data.quality}
              reason={query.data.reason ?? null}
            />

            <Card>
              <CardTitle>Что-то не так?</CardTitle>
              <CardSubtitle className="mt-1">
                Мы кэшируем варианты, чтобы открывались быстро. Если палитра
                поменялась или хочется освежить рендер — запустите вручную.
              </CardSubtitle>
              <div className="mt-3">
                <Button
                  variant="secondary"
                  onClick={() => regenerate.mutate()}
                  disabled={regenerate.isPending}
                >
                  {regenerate.isPending
                    ? "Генерация…"
                    : "Перегенерировать"}
                </Button>
              </div>
              {regenerate.isError ? (
                <p className="mt-2 text-xs text-red-600">
                  Не удалось запустить генерацию.
                </p>
              ) : null}
            </Card>
          </div>
        ) : null}
      </QueryState>
    </>
  );
}

function ColorTryOnSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-5 w-48" />
      <div className="grid gap-4 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="overflow-hidden rounded-2xl border border-canvas-border bg-canvas-card"
          >
            <Skeleton className="aspect-square rounded-none" />
            <div className="space-y-2 p-3">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-8 w-full" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
