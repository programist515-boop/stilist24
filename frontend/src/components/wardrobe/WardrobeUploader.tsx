"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { FileDropzone } from "@/components/ui/FileDropzone";
import { Label } from "@/components/ui/Label";
import { Select } from "@/components/ui/Select";
import {
  updateWardrobeItemCategory,
  uploadWardrobeItem,
} from "@/lib/api/wardrobe";
import { trackEvent } from "@/lib/api/events";
import type { WardrobeItem } from "@/lib/schemas";

const CATEGORIES: Array<{ value: string; label: string }> = [
  { value: "top", label: "Верх" },
  { value: "bottom", label: "Низ" },
  { value: "outerwear", label: "Верхняя одежда" },
  { value: "shoes", label: "Обувь" },
  { value: "dress", label: "Платье" },
  { value: "accessory", label: "Аксессуар" },
];

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((c) => [c.value, c.label])
);

export function WardrobeUploader() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  // "" = «Угадай по фото» — backend определит категорию по CV.
  const [category, setCategory] = useState("");
  const [lastUploaded, setLastUploaded] = useState<WardrobeItem | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Сначала выберите изображение");
      return uploadWardrobeItem({
        image: file,
        category: category || undefined,
      });
    },
    onSuccess: (item) => {
      setFile(null);
      setLastUploaded(item);
      queryClient.invalidateQueries({ queryKey: ["wardrobe"] });
      trackEvent("wardrobe_item_uploaded", {
        item_id: item.id,
        category: item.category,
      });
    },
  });

  const updateCategoryMutation = useMutation({
    mutationFn: (newCategory: string) => {
      if (!lastUploaded) throw new Error("Нет последней загруженной вещи");
      return updateWardrobeItemCategory(lastUploaded.id, newCategory);
    },
    onSuccess: (item) => {
      setLastUploaded(item);
      queryClient.invalidateQueries({ queryKey: ["wardrobe"] });
      trackEvent("wardrobe_item_category_corrected", {
        item_id: item.id,
        category: item.category,
      });
    },
  });

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Добавить вещь</CardTitle>
          <CardSubtitle className="mt-1">
            Загрузите фото — мы уберём фон, определим категорию и атрибуты.
          </CardSubtitle>
        </div>
        {mutation.isSuccess ? (
          <Badge tone="success">Добавлено в гардероб</Badge>
        ) : null}
      </div>

      <div className="mt-6 grid gap-5 sm:grid-cols-[200px,1fr]">
        <FileDropzone label="Фото вещи" file={file} onChange={setFile} />
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="category">Категория (необязательно)</Label>
            <Select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="">Угадаем по фото</option>
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
            <p className="text-xs text-ink-muted">
              Можно оставить «Угадаем по фото» — поправить можно после
              загрузки.
            </p>
          </div>
          <Button
            onClick={() => mutation.mutate()}
            disabled={!file}
            loading={mutation.isPending}
            loadingText="Идёт CV-анализ…"
            fullWidth
            className="sm:w-auto"
          >
            Загрузить вещь
          </Button>
          {mutation.isPending ? (
            <p className="text-xs text-ink-muted">
              Загружаем фото, убираем фон и распознаём вещь — на первом
              фото это может занять до минуты.
            </p>
          ) : null}
        </div>
      </div>

      {mutation.isError ? (
        <div className="mt-4">
          <ErrorState
            title="Не удалось загрузить"
            error={mutation.error}
            onRetry={() => mutation.mutate()}
          />
        </div>
      ) : null}

      {lastUploaded && !mutation.isPending && !mutation.isError ? (
        <LastUploadedReview
          item={lastUploaded}
          onChangeCategory={(c) => updateCategoryMutation.mutate(c)}
          isUpdating={updateCategoryMutation.isPending}
          updateError={updateCategoryMutation.error}
        />
      ) : null}
    </Card>
  );
}

function LastUploadedReview({
  item,
  onChangeCategory,
  isUpdating,
  updateError,
}: {
  item: WardrobeItem;
  onChangeCategory: (category: string) => void;
  isUpdating: boolean;
  updateError: unknown;
}) {
  const currentCategory = item.category ?? "";
  const currentLabel =
    CATEGORY_LABEL[currentCategory] ?? currentCategory ?? "не определена";

  return (
    <div className="mt-5 flex flex-col gap-3 rounded-xl border border-canvas-border bg-canvas-card p-4 sm:flex-row sm:items-center">
      {item.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={item.image_url}
          alt="Загруженная вещь"
          className="h-20 w-20 flex-shrink-0 rounded-lg object-cover"
        />
      ) : null}
      <div className="flex-1 space-y-1.5">
        <p className="text-sm text-ink">
          Категория:{" "}
          <span className="font-medium">{currentLabel}</span>
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor="fix-category" className="!normal-case">
            Не та?
          </Label>
          <select
            id="fix-category"
            value={currentCategory}
            onChange={(e) => onChangeCategory(e.target.value)}
            disabled={isUpdating}
            className="h-9 rounded-lg border border-canvas-border bg-canvas-card px-3 text-sm text-ink disabled:opacity-60"
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
          {isUpdating ? (
            <span className="text-xs text-ink-muted">Обновляем…</span>
          ) : null}
        </div>
        {updateError ? (
          <p className="text-xs text-red-600">
            Не удалось изменить категорию.
          </p>
        ) : null}
      </div>
    </div>
  );
}
