"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Label } from "@/components/ui/Label";
import { Select } from "@/components/ui/Select";
import { PageHeader } from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { TryOnResult } from "@/components/tryon/TryOnResult";
import { generateTryOn } from "@/lib/api/tryon";
import { listUserPhotos } from "@/lib/api/user";
import { listWardrobeItems } from "@/lib/api/wardrobe";
import type { TryOnJob } from "@/lib/schemas";

const PHOTO_SLOT_LABEL: Record<string, string> = {
  front: "анфас",
  side: "профиль",
  portrait: "портрет",
};

export default function TryOnPage() {
  const [itemId, setItemId] = useState("");
  const [userPhotoId, setUserPhotoId] = useState("");

  // Reference photos come from the live `GET /user/photos` endpoint, not
  // from a localStorage snapshot of the last analysis. This way a change
  // to the backend's public URL base (or any DB update to the rows) is
  // reflected on the next page load without forcing the user to re-run
  // the analysis.
  const userPhotos = useQuery({
    queryKey: ["user", "photos"],
    queryFn: listUserPhotos,
    staleTime: 60_000,
  });
  const photos = useMemo(() => userPhotos.data ?? [], [userPhotos.data]);

  // Auto-select the first photo once the list lands.
  useEffect(() => {
    if (!userPhotoId && photos.length > 0) {
      setUserPhotoId(photos[0].id);
    }
  }, [photos, userPhotoId]);

  const wardrobe = useQuery({
    queryKey: ["wardrobe"],
    queryFn: listWardrobeItems,
    staleTime: 5 * 60_000,
  });

  // Auto-select the first wardrobe item once the list lands.
  useEffect(() => {
    if (!itemId && wardrobe.data && wardrobe.data.length > 0) {
      setItemId(wardrobe.data[0].id);
    }
  }, [wardrobe.data, itemId]);

  const selectedPhoto = useMemo(
    () => photos.find((p) => p.id === userPhotoId) ?? null,
    [photos, userPhotoId]
  );
  const selectedItem = useMemo(
    () => wardrobe.data?.find((i) => i.id === itemId) ?? null,
    [wardrobe.data, itemId]
  );

  const mutation = useMutation<TryOnJob>({
    mutationFn: () =>
      generateTryOn({ item_id: itemId, user_photo_id: userPhotoId }),
  });

  // Wait for the server roundtrip before claiming the user has no photos,
  // otherwise the first paint flashes an empty state for one frame.
  const noPhotos = userPhotos.isSuccess && photos.length === 0;
  const noItems = wardrobe.isSuccess && (wardrobe.data?.length ?? 0) === 0;
  const ready = !!itemId && !!userPhotoId;

  return (
    <>
      <PageHeader
        eyebrow="Примерка"
        title="Покажем вещь на вас"
        subtitle="Выберите фото и вещь из гардероба. Алгоритм вернёт визуальный мокап."
      />

      <Card className="border-amber-100 bg-amber-50">
        <p className="text-sm text-amber-900">
          <strong className="font-semibold">Важно — </strong>
          результат примерки — это визуальная симуляция, а не точный прогноз
          посадки. Драпировка и пропорции могут отличаться от реальной вещи на
          реальном теле.
        </p>
      </Card>

      {noPhotos || noItems ? (
        <EmptyState
          title="Не хватает данных"
          hint={
            noPhotos && noItems
              ? "Для примерки нужно хотя бы одно фото и хотя бы одна вещь в гардеробе."
              : noPhotos
              ? "Для примерки нужно фото. Запустите анализ, чтобы добавить его."
              : "Для примерки нужна хотя бы одна вещь в гардеробе."
          }
          action={
            <div className="flex flex-wrap justify-center gap-3">
              {noPhotos ? (
                <Link href="/analyze">
                  <Button>Запустить анализ</Button>
                </Link>
              ) : null}
              {noItems ? (
                <Link href="/wardrobe">
                  <Button variant="secondary">Добавить вещь</Button>
                </Link>
              ) : null}
            </div>
          }
        />
      ) : null}

      {!noPhotos && !noItems && !mutation.data ? (
        <Card>
          <SectionHeader title="Новая примерка" className="pb-4" />

          <div className="grid gap-6 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="photo">Фото</Label>
              <Select
                id="photo"
                value={userPhotoId}
                onChange={(e) => setUserPhotoId(e.target.value)}
              >
                {photos.map((p) => (
                  <option key={p.id} value={p.id}>
                    {PHOTO_SLOT_LABEL[p.slot] ?? p.slot}
                  </option>
                ))}
              </Select>
              {selectedPhoto?.image_url ? (
                <div className="aspect-[3/4] overflow-hidden rounded-xl border border-canvas-border bg-accent-soft">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={selectedPhoto.image_url}
                    alt={selectedPhoto.slot}
                    className="h-full w-full object-cover"
                  />
                </div>
              ) : (
                <div className="flex aspect-[3/4] items-center justify-center rounded-xl border border-dashed border-canvas-border bg-accent-soft text-xs text-ink-muted">
                  Нет превью
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="item">Вещь из гардероба</Label>
              <Select
                id="item"
                value={itemId}
                onChange={(e) => setItemId(e.target.value)}
              >
                {wardrobe.data?.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.category ?? "вещь"} — {item.id.slice(0, 6)}
                  </option>
                ))}
              </Select>
              {selectedItem?.image_url ? (
                <div className="aspect-square overflow-hidden rounded-xl border border-canvas-border bg-accent-soft">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={selectedItem.image_url}
                    alt={selectedItem.category ?? "вещь"}
                    className="h-full w-full object-cover"
                  />
                </div>
              ) : (
                <div className="flex aspect-square items-center justify-center rounded-xl border border-dashed border-canvas-border bg-accent-soft text-xs text-ink-muted">
                  Нет превью
                </div>
              )}
            </div>
          </div>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-ink-muted">
              {mutation.isPending
                ? "Запрос отправлен. Обычно это занимает несколько секунд."
                : "Генерация обычно занимает несколько секунд."}
            </p>
            <Button
              onClick={() => mutation.mutate()}
              disabled={!ready}
              loading={mutation.isPending}
              loadingText="Генерируем…"
              fullWidth
              className="sm:w-auto"
            >
              Сгенерировать примерку
            </Button>
          </div>
        </Card>
      ) : null}

      {mutation.isError ? (
        <ErrorState
          title="Не удалось выполнить примерку"
          error={mutation.error}
          onRetry={() => mutation.mutate()}
        />
      ) : null}

      {mutation.data ? (
        <>
          <Card padding="none" className="overflow-hidden">
            <div className="grid gap-0 sm:grid-cols-2">
              <div className="space-y-1 border-b border-canvas-border p-4 sm:border-b-0 sm:border-r">
                <p className="text-[10px] font-medium uppercase tracking-wide text-ink-muted">
                  Фото
                </p>
                <p className="text-sm capitalize text-ink">
                  {selectedPhoto
                    ? PHOTO_SLOT_LABEL[selectedPhoto.slot] ?? selectedPhoto.slot
                    : "—"}
                </p>
              </div>
              <div className="space-y-1 p-4">
                <p className="text-[10px] font-medium uppercase tracking-wide text-ink-muted">
                  Вещь
                </p>
                <p className="text-sm capitalize text-ink">
                  {selectedItem?.category ?? "—"}
                </p>
              </div>
            </div>
          </Card>

          <TryOnResult job={mutation.data} onReset={() => mutation.reset()} />
        </>
      ) : null}
    </>
  );
}
