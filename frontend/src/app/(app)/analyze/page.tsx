"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { PhotoSlot } from "@/components/analysis/PhotoSlot";
import { AnalysisResultCard } from "@/components/analysis/AnalysisResultCard";
import { analyzeUser } from "@/lib/api/user";
import { trackEvent } from "@/lib/api/events";
import { saveLastAnalysis } from "@/lib/local-store";
import type { UserAnalysis } from "@/lib/schemas";

export default function AnalyzePage() {
  const [front, setFront] = useState<File | null>(null);
  const [side, setSide] = useState<File | null>(null);
  const [portrait, setPortrait] = useState<File | null>(null);

  const mutation = useMutation<UserAnalysis>({
    mutationFn: () => {
      if (!front || !side || !portrait) {
        throw new Error("Загрузите все три фото");
      }
      return analyzeUser({ front, side, portrait });
    },
    onSuccess: (data) => {
      saveLastAnalysis(data);
      trackEvent("analysis_completed", {
        kibbe_type: data.kibbe?.main_type ?? null,
        season: data.color?.season_top_1 ?? null,
      });
    },
  });

  const filledCount = [front, side, portrait].filter(Boolean).length;
  const ready = filledCount === 3;

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
            onChange={setFront}
          />
          <PhotoSlot
            index={2}
            label="Профиль"
            hint="Сбоку, в полный рост"
            file={side}
            onChange={setSide}
          />
          <PhotoSlot
            index={3}
            label="Портрет"
            hint="Лицо, нейтральный свет"
            file={portrait}
            onChange={setPortrait}
          />
        </div>
      </section>

      <Card>
        <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>
              {ready ? "Готово к анализу" : `${filledCount} из 3 фото добавлено`}
            </CardTitle>
            <CardSubtitle className="mt-1">
              {ready
                ? "Определим ваш Kibbe-тип, сезонную палитру и стилевой вектор."
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
            Запустить анализ
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
