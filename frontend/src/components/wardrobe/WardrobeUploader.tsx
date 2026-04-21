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
import { uploadWardrobeItem } from "@/lib/api/wardrobe";
import { trackEvent } from "@/lib/api/events";

const CATEGORIES: Array<{ value: string; label: string }> = [
  { value: "top", label: "Верх" },
  { value: "bottom", label: "Низ" },
  { value: "outerwear", label: "Верхняя одежда" },
  { value: "shoes", label: "Обувь" },
  { value: "dress", label: "Платье" },
  { value: "accessory", label: "Аксессуар" },
];

export function WardrobeUploader() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [category, setCategory] = useState("top");

  const mutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Сначала выберите изображение");
      return uploadWardrobeItem({ image: file, category });
    },
    onSuccess: (item) => {
      setFile(null);
      queryClient.invalidateQueries({ queryKey: ["wardrobe"] });
      trackEvent("wardrobe_item_uploaded", {
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
            Загрузите фото — мы определим теги и поместим вещь в гардероб.
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
            <Label htmlFor="category">Категория</Label>
            <Select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
            <p className="text-xs text-ink-muted">
              Используется алгоритмом подбора, чтобы поставить вещь в нужный
              слот.
            </p>
          </div>
          <Button
            onClick={() => mutation.mutate()}
            disabled={!file}
            loading={mutation.isPending}
            loadingText="Загружаем…"
            fullWidth
            className="sm:w-auto"
          >
            Загрузить вещь
          </Button>
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
    </Card>
  );
}
