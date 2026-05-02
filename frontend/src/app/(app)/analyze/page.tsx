"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { PhotoSlot } from "@/components/analysis/PhotoSlot";
import { AnalysisResultCard } from "@/components/analysis/AnalysisResultCard";
import { IdentityDNACard } from "@/components/analysis/IdentityDNACard";
import { analyzeUser, listUserPhotos } from "@/lib/api/user";
import { trackEvent } from "@/lib/api/events";
import { saveLastAnalysis } from "@/lib/local-store";
import type { AnalysisPhoto, UserAnalysis } from "@/lib/schemas";

/**
 * Resolve a slot's payload to a real ``File`` for ``POST /user/analyze``.
 *
 * - Fresh pick (``file``)     → use as-is.
 * - Preloaded URL only        → ``fetch`` it back into a ``Blob`` and wrap
 *                                into a ``File`` so the multipart contract
 *                                is preserved without bothering the user
 *                                to re-upload identical bytes.
 *
 * The backend always extracts CV features from raw pixels, so we cannot
 * "re-analyze" by reference (no ``image_key``-based endpoint exists).
 * Re-uploading the same bytes is a small price for the much better UX.
 */
async function resolveSlotFile(
  slotName: string,
  file: File | null,
  preloadedUrl: string | null,
): Promise<File> {
  if (file) return file;
  if (!preloadedUrl) {
    throw new Error(`Слот «${slotName}» пуст`);
  }
  const r = await fetch(preloadedUrl, { credentials: "omit" });
  if (!r.ok) {
    throw new Error(`Не удалось загрузить сохранённое фото (${slotName})`);
  }
  const blob = await r.blob();
  const ext = (blob.type.split("/")[1] || "jpg").replace("jpeg", "jpg");
  return new File([blob], `${slotName}.${ext}`, {
    type: blob.type || "image/jpeg",
  });
}

function pickPreloaded(
  photos: AnalysisPhoto[] | undefined,
  slot: string,
): string | null {
  if (!photos || photos.length === 0) return null;
  // ``listUserPhotos`` returns rows freshest-first, so the first match
  // for the slot is the most recent upload.
  const hit = photos.find((p) => p.slot === slot);
  return hit?.image_url ?? null;
}

export default function AnalyzePage() {
  const [front, setFront] = useState<File | null>(null);
  const [side, setSide] = useState<File | null>(null);
  const [portrait, setPortrait] = useState<File | null>(null);

  // Pull persisted photos from the backend so a returning user sees
  // their existing analysis photos in the slots instead of empty
  // dropzones. They can keep them, replace any one, or replace all.
  const photosQuery = useQuery({
    queryKey: ["user-photos"],
    queryFn: listUserPhotos,
    staleTime: 60_000,
  });

  const preloaded = useMemo(
    () => ({
      front: pickPreloaded(photosQuery.data, "front"),
      side: pickPreloaded(photosQuery.data, "side"),
      portrait: pickPreloaded(photosQuery.data, "portrait"),
    }),
    [photosQuery.data],
  );

  const mutation = useMutation<UserAnalysis>({
    mutationFn: async () => {
      const [frontFile, sideFile, portraitFile] = await Promise.all([
        resolveSlotFile("Анфас", front, preloaded.front),
        resolveSlotFile("Профиль", side, preloaded.side),
        resolveSlotFile("Портрет", portrait, preloaded.portrait),
      ]);
      return analyzeUser({
        front: frontFile,
        side: sideFile,
        portrait: portraitFile,
      });
    },
    onSuccess: (data) => {
      saveLastAnalysis(data);
      trackEvent("analysis_completed", {
        kibbe_type: data.kibbe?.main_type ?? null,
        season: data.color?.season_top_1 ?? null,
      });
      // Refresh persisted photo list so a follow-up reload shows the
      // new uploads, not the previous ones.
      photosQuery.refetch();
    },
  });

  const slotFilled = (file: File | null, url: string | null) =>
    Boolean(file || url);
  const filledCount = [
    slotFilled(front, preloaded.front),
    slotFilled(side, preloaded.side),
    slotFilled(portrait, preloaded.portrait),
  ].filter(Boolean).length;
  const ready = filledCount === 3;
  const allFromServer =
    ready &&
    !front &&
    !side &&
    !portrait &&
    Boolean(preloaded.front && preloaded.side && preloaded.portrait);

  return (
    <>
      <PageHeader
        eyebrow="Шаг 1"
        title="Считываем вашу отправную точку"
        subtitle="Загрузите три фото, чтобы мы определили вашу фигуру, палитру и стиль. Фото не выходят за пределы вашего аккаунта."
      />

      <section>
        <SectionHeader
          title="Фото для анализа"
          description="Лучше всего работает естественное освещение и однотонный фон."
        />
        <div className="grid gap-4 sm:grid-cols-3">
          <PhotoSlot
            index={1}
            label="Анфас"
            hint="Спереди, в полный рост"
            file={front}
            preloadedUrl={preloaded.front}
            onChange={setFront}
          />
          <PhotoSlot
            index={2}
            label="Профиль"
            hint="Сбоку, в полный рост"
            file={side}
            preloadedUrl={preloaded.side}
            onChange={setSide}
          />
          <PhotoSlot
            index={3}
            label="Портрет"
            hint="Лицо, нейтральный свет"
            file={portrait}
            preloadedUrl={preloaded.portrait}
            onChange={setPortrait}
          />
        </div>
      </section>

      <Card>
        <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>
              {ready
                ? allFromServer
                  ? "Фото из прошлого анализа уже здесь"
                  : "Готово к анализу"
                : `${filledCount} из 3 фото добавлено`}
            </CardTitle>
            <CardSubtitle className="mt-1">
              {ready
                ? allFromServer
                  ? "Можно перезапустить анализ на тех же фото или заменить любое из них на свежее."
                  : "Определим ваш Kibbe-тип, сезонную палитру и стилевой вектор."
                : "Добавьте оставшиеся фото, чтобы запустить анализ."}
            </CardSubtitle>
          </div>
          <Button
            onClick={() => mutation.mutate()}
            disabled={!ready}
            loading={mutation.isPending}
            loadingText="Анализируем…"
            size="lg"
            className="sm:flex-shrink-0"
          >
            {allFromServer ? "Перезапустить анализ" : "Запустить анализ"}
          </Button>
        </div>
      </Card>

      {mutation.isError ? (
        <ErrorState
          title="Не удалось выполнить анализ"
          error={mutation.error}
          onRetry={() => mutation.mutate()}
        />
      ) : null}

      {mutation.data ? (
        <section className="space-y-4">
          <Card padding="md" className="border-emerald-200 bg-emerald-50">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="text-emerald-900">
                  Анализ готов
                </CardTitle>
                <CardSubtitle className="mt-1 text-emerald-800">
                  Фото сохранены. Теперь их можно использовать в примерке.
                </CardSubtitle>
              </div>
              <div className="flex flex-wrap gap-2">
                <Link href="/recommendations">
                  <Button variant="primary">Открыть рекомендации</Button>
                </Link>
                <Link href="/tryon">
                  <Button variant="secondary">Перейти к примерке</Button>
                </Link>
              </div>
            </div>
          </Card>
          <AnalysisResultCard result={mutation.data} />
          <IdentityDNACard />
          <Card className="border-sky-200 bg-sky-50">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="max-w-xl">
                <CardTitle className="text-sky-900">
                  Не уверены в результате?
                </CardTitle>
                <CardSubtitle className="mt-1 text-sky-800">
                  Пройдите квиз по лайкам — 5 минут, без загрузок. В конце
                  сравним два профиля и вы сами решите, какой использовать.
                </CardSubtitle>
              </div>
              <Link href="/style-quiz">
                <Button variant="primary">Уточнить по лайкам</Button>
              </Link>
            </div>
          </Card>
        </section>
      ) : null}
    </>
  );
}
