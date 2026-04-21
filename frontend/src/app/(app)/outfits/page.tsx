"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import {
  OutfitCard,
  OutfitCardSkeleton,
} from "@/components/outfits/OutfitCard";
import { generateOutfits } from "@/lib/api/outfits";
import { trackEvent } from "@/lib/api/events";
import { listWardrobeItems } from "@/lib/api/wardrobe";
import { buildImageMap } from "@/components/today/TodayCard";
import type { OutfitGenerateResponse } from "@/lib/schemas";
import Link from "next/link";

function pluralizeOutfits(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "образ";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "образа";
  return "образов";
}

export default function OutfitsPage() {
  const [occasion, setOccasion] = useState("");
  const [season, setSeason] = useState("");

  const wardrobe = useQuery({
    queryKey: ["wardrobe"],
    queryFn: listWardrobeItems,
    staleTime: 5 * 60_000,
  });

  const imageById = useMemo(
    () => buildImageMap(wardrobe.data),
    [wardrobe.data]
  );

  const mutation = useMutation<OutfitGenerateResponse>({
    mutationFn: () =>
      generateOutfits({
        occasion: occasion || undefined,
        season: season || undefined,
      }),
    onSuccess: (data) => {
      trackEvent("outfits_generated", {
        count: data.count ?? data.outfits?.length ?? 0,
        occasion: occasion || null,
        season: season || null,
      });
    },
  });

  const wardrobeEmpty =
    wardrobe.isSuccess && (wardrobe.data?.length ?? 0) === 0;

  const generated = mutation.data?.outfits ?? [];
  const hasGenerated = mutation.isSuccess && generated.length > 0;

  return (
    <>
      <PageHeader
        eyebrow="Образы"
        title="Собраны из вашего гардероба"
        subtitle="Задайте контекст или просто запустите подбор — алгоритм выберет сам."
        action={
          hasGenerated ? (
            <Button
              variant="secondary"
              onClick={() => mutation.mutate()}
              loading={mutation.isPending}
              loadingText="Подбираем…"
            >
              Подобрать ещё
            </Button>
          ) : null
        }
      />

      <Card>
        <SectionHeader title="Контекст" className="pb-4" />
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="occasion">Повод</Label>
            <Input
              id="occasion"
              value={occasion}
              onChange={(e) => setOccasion(e.target.value)}
              placeholder="работа, ужин, casual…"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="season">Сезон</Label>
            <Input
              id="season"
              value={season}
              onChange={(e) => setSeason(e.target.value)}
              placeholder="весна, осень…"
            />
          </div>
        </div>
        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-ink-muted">
            {wardrobeEmpty
              ? "Сначала добавьте вещи в гардероб — образы собираются из того, что у вас есть."
              : "Нажмите «Подобрать», чтобы увидеть варианты с оценками по цвету, силуэту и стилю."}
          </p>
          <Button
            onClick={() => mutation.mutate()}
            disabled={wardrobeEmpty}
            loading={mutation.isPending}
            loadingText="Подбираем…"
            className="sm:w-auto"
            fullWidth
          >
            Подобрать
          </Button>
        </div>
      </Card>

      {wardrobeEmpty ? (
        <EmptyState
          title="Гардероб пока пуст"
          hint="Добавьте хотя бы верх, низ и обувь (или платье и обувь), прежде чем запускать подбор."
          action={
            <Link href="/wardrobe">
              <Button>Добавить вещи</Button>
            </Link>
          }
        />
      ) : null}

      {mutation.isError ? (
        <ErrorState
          title="Не удалось подобрать образы"
          error={mutation.error}
          onRetry={() => mutation.mutate()}
        />
      ) : null}

      {mutation.isPending ? (
        <section className="space-y-4">
          <SectionHeader
            title="Ищем сочетания…"
            description="Собираем варианты с оценками по вашему гардеробу."
          />
          <div className="grid gap-4 lg:grid-cols-2">
            <OutfitCardSkeleton />
            <OutfitCardSkeleton />
            <OutfitCardSkeleton />
            <OutfitCardSkeleton />
          </div>
        </section>
      ) : null}

      {mutation.isSuccess && !mutation.isPending ? (
        generated.length === 0 ? (
          <Card>
            <CardTitle>Подходящих сочетаний пока нет</CardTitle>
            <CardSubtitle className="mt-1">
              Добавьте больше разнообразия — минимум верх, низ и обувь (или
              платье и обувь).
            </CardSubtitle>
          </Card>
        ) : (
          <section className="space-y-4">
            <SectionHeader
              title={`Подобрано ${
                mutation.data?.count ?? generated.length
              } ${pluralizeOutfits(
                mutation.data?.count ?? generated.length
              )}`}
              description="Чем выше общая оценка, тем сильнее образ совпадает с вашим стилевым профилем."
            />
            <div className="grid gap-4 lg:grid-cols-2">
              {generated.map((outfit, idx) => (
                <OutfitCard
                  key={outfit.id ?? idx}
                  outfit={outfit}
                  imageById={imageById}
                />
              ))}
            </div>
          </section>
        )
      ) : null}
    </>
  );
}
