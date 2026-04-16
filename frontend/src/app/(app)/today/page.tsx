"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { QueryState } from "@/components/ui/QueryState";
import {
  TodayCard,
  TodayCardSkeleton,
  buildImageMap,
} from "@/components/today/TodayCard";
import { getToday } from "@/lib/api/today";
import { listWardrobeItems } from "@/lib/api/wardrobe";

function pluralizeLooks(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "образ";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "образа";
  return "образов";
}

export default function TodayPage() {
  const [weather, setWeather] = useState("");
  const [occasion, setOccasion] = useState("");

  const today = useQuery({
    queryKey: ["today", weather, occasion],
    queryFn: () => getToday({ weather, occasion }),
  });

  // Outfit responses strip image_url from items, so we join client-side
  // with the wardrobe list. Cached separately so it doesn't refetch on
  // every form keystroke.
  const wardrobe = useQuery({
    queryKey: ["wardrobe"],
    queryFn: listWardrobeItems,
    staleTime: 5 * 60_000,
  });

  const imageById = useMemo(
    () => buildImageMap(wardrobe.data),
    [wardrobe.data]
  );

  const slots = today.data?.outfits ?? [];
  const notes = today.data?.notes ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Сегодня"
        title="Три образа на день"
        subtitle="Выберите настроение — безопасный, сбалансированный или смелый — остальное мы соберём."
      />

      <Card padding="md">
        <SectionHeader
          title="Уточнить день"
          description="Опционально. Оставьте пустым для дефолтной подборки."
          className="pb-4"
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="weather">Погоода</Label>
            <Input
              id="weather"
              value={weather}
              onChange={(e) => setWeather(e.target.value)}
              placeholder="тепло, холодно, дождь…"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="occasion">Повод</Label>
            <Input
              id="occasion"
              value={occasion}
              onChange={(e) => setOccasion(e.target.value)}
              placeholder="работа, свидание, casual…"
            />
          </div>
        </div>
      </Card>

      <QueryState
        isLoading={today.isLoading}
        isError={today.isError}
        error={today.error}
        onRetry={() => today.refetch()}
        isEmpty={!today.isLoading && slots.length === 0}
        emptyTitle="Пока нечего предложить"
        emptyHint={
          notes[0] ??
          "Добавьте несколько вещей в гардероб — «Сегодня» собирает три образа из того, что у вас есть."
        }
        loadingFallback={
          <div className="grid gap-4 lg:grid-cols-3">
            <TodayCardSkeleton />
            <TodayCardSkeleton />
            <TodayCardSkeleton />
          </div>
        }
      >
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            {slots.map((slot) => (
              <TodayCard
                key={slot.label}
                slot={slot}
                imageById={imageById}
              />
            ))}
          </div>

          {slots.length > 0 && slots.length < 3 ? (
            <p className="mt-4 text-xs text-ink-muted">
              Удалось собрать только {slots.length}{" "}
              {pluralizeLooks(slots.length)} из вашего гардероба. Добавьте
              больше разнообразия для полного набора.
            </p>
          ) : null}
        </>
      </QueryState>

      {notes.length > 0 && slots.length > 0 ? (
        <section>
          <SectionHeader
            title="Заметки от алгоритма"
            description="Почему сегодня именно эти варианты."
          />
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
  );
}
