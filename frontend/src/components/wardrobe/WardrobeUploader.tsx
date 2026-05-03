"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { FileDropzone } from "@/components/ui/FileDropzone";
import { Label } from "@/components/ui/Label";
import {
  updateWardrobeItem,
  uploadWardrobeItem,
} from "@/lib/api/wardrobe";
import { trackEvent } from "@/lib/api/events";
import type { WardrobeItem } from "@/lib/schemas";

const CATEGORIES: Array<{ value: string; label: string }> = [
  { value: "blouses", label: "Блузки и рубашки" },
  { value: "sweaters", label: "Свитеры и трикотаж" },
  { value: "dresses", label: "Платья" },
  { value: "jackets", label: "Жакеты и пиджаки" },
  { value: "outerwear", label: "Верхняя одежда" },
  { value: "pants", label: "Брюки и джинсы" },
  { value: "skirts", label: "Юбки" },
  { value: "shoes", label: "Обувь" },
  { value: "hosiery", label: "Колготки и чулки" },
  { value: "bags", label: "Сумки" },
  { value: "belts", label: "Ремни" },
  { value: "eyewear", label: "Очки" },
  { value: "headwear", label: "Головные уборы" },
  { value: "jewelry", label: "Украшения" },
  { value: "swimwear", label: "Купальники" },
];

// Старые items, загруженные до расширения enum, имеют legacy-категории.
// Показываем человекочитаемые лейблы, чтобы UI не отображал «top».
const LEGACY_CATEGORY_LABEL: Record<string, string> = {
  top: "Верх (старая запись)",
  bottom: "Низ (старая запись)",
  dress: "Платье (старая запись)",
  accessory: "Аксессуар (старая запись)",
};

const CATEGORY_LABEL: Record<string, string> = {
  ...Object.fromEntries(CATEGORIES.map((c) => [c.value, c.label])),
  ...LEGACY_CATEGORY_LABEL,
};

const PROGRESS_STEPS = [
  "Определяем по фото",
  "Вырезаем фон",
  "Загружаем в гардероб",
] as const;

export function WardrobeUploader() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [lastUploaded, setLastUploaded] = useState<WardrobeItem | null>(null);

  const mutation = useMutation({
    mutationFn: (image: File) => uploadWardrobeItem({ image }),
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

  // Автозапуск: как только пользователь выбрал файл, сразу шлём на бэк.
  // Никакой кнопки «Загрузить» — uploader работает по факту выбора.
  const handleFile = (next: File | null) => {
    setFile(next);
    if (next) {
      mutation.mutate(next);
    }
  };

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Добавить вещь</CardTitle>
          <CardSubtitle className="mt-1">
            Перетащите фото — мы определим по фото и уберём фон.
          </CardSubtitle>
        </div>
        {mutation.isSuccess ? (
          <Badge tone="success">Добавлено в гардероб</Badge>
        ) : null}
      </div>

      <div className="mt-6 grid gap-5 sm:grid-cols-[200px,1fr]">
        <FileDropzone label="Фото вещи" file={file} onChange={handleFile} />
        <div className="space-y-3">
          {mutation.isPending ? (
            <UploadProgressStepper />
          ) : (
            <p className="text-sm text-ink-muted">
              После выбора фото мы автоматически определим вещь, обрежем
              фон и сохраним в гардероб. Категорию и название сможете
              поправить в карточке после распознавания.
            </p>
          )}
        </div>
      </div>

      {mutation.isError ? (
        <div className="mt-4">
          <ErrorState
            title="Не удалось загрузить"
            error={mutation.error}
            onRetry={() => file && mutation.mutate(file)}
          />
        </div>
      ) : null}

      {lastUploaded && !mutation.isPending && !mutation.isError ? (
        <LastUploadedReview
          key={lastUploaded.id}
          item={lastUploaded}
          onClose={() => setLastUploaded(null)}
        />
      ) : null}
    </Card>
  );
}

/**
 * Псевдо-stepper «Определяем → Вырезаем фон → Загружаем». Один POST
 * под капотом длится ~5–30s, мы переключаем step по таймеру каждые
 * 2.5s. Реальная цепочка идёт ровно в этом порядке (vision-вызов,
 * затем save nobg, затем DB), поэтому подписи не лгут.
 */
function UploadProgressStepper() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setStep((s) => (s + 1 < PROGRESS_STEPS.length ? s + 1 : s));
    }, 2500);
    return () => clearInterval(id);
  }, []);

  return (
    <ul className="space-y-2">
      {PROGRESS_STEPS.map((label, idx) => {
        const isDone = idx < step;
        const isActive = idx === step;
        return (
          <li
            key={label}
            className="flex items-center gap-2 text-sm text-ink"
          >
            <span
              className={
                isDone
                  ? "inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-[11px] text-white"
                  : isActive
                  ? "inline-flex h-5 w-5 animate-spin rounded-full border-2 border-ink/40 border-t-ink"
                  : "inline-flex h-5 w-5 rounded-full border border-canvas-border"
              }
              aria-hidden
            >
              {isDone ? "✓" : ""}
            </span>
            <span
              className={
                isActive
                  ? "font-medium"
                  : isDone
                  ? "text-ink-muted line-through"
                  : "text-ink-muted"
              }
            >
              {label}…
            </span>
          </li>
        );
      })}
      <p className="pt-1 text-xs text-ink-muted">
        На первом фото может занять до минуты.
      </p>
    </ul>
  );
}

type CategoryMeta = {
  value?: string | null;
  confidence?: number | null;
  source?: string | null;
};

function readCategoryMeta(item: WardrobeItem): CategoryMeta {
  const attrs = item.attributes as Record<string, unknown> | undefined;
  const meta = attrs?.category;
  if (meta && typeof meta === "object") {
    const m = meta as Record<string, unknown>;
    return {
      value: typeof m.value === "string" ? m.value : null,
      confidence: typeof m.confidence === "number" ? m.confidence : null,
      source: typeof m.source === "string" ? m.source : null,
    };
  }
  return {};
}

/**
 * Карточка после успешной загрузки. Поля имени и категории заполнены
 * vision-анализатором — пользователь либо сразу жмёт «ОК», либо
 * правит inline и тогда жмёт «ОК». Никакого auto-save.
 */
function LastUploadedReview({
  item,
  onClose,
}: {
  item: WardrobeItem;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [editName, setEditName] = useState<string>(item.name ?? "");
  const [editCategory, setEditCategory] = useState<string>(item.category ?? "");

  const meta = readCategoryMeta(item);
  const isAutoDetected = meta.source === "cloud_llm" || meta.source === "heuristic";
  const confidencePct =
    typeof meta.confidence === "number" ? Math.round(meta.confidence * 100) : null;
  const isUndetected = !item.category;

  const headline = isUndetected
    ? "Не получилось определить категорию — выберите сами"
    : isAutoDetected && confidencePct !== null && confidencePct < 75
    ? `Похоже на это — уверенность ${confidencePct}%, поправьте при желании`
    : "Распознали — проверьте и нажмите ОК";

  const updateMutation = useMutation({
    mutationFn: () => {
      const payload: { category?: string; name?: string } = {};
      const trimmedName = editName.trim();
      const originalName = (item.name ?? "").trim();
      const originalCategory = item.category ?? "";
      if (trimmedName !== originalName) {
        payload.name = trimmedName;
      }
      if (editCategory !== originalCategory && editCategory) {
        payload.category = editCategory;
      }
      // Никаких изменений → resolve с текущим item (no-op на сети).
      if (Object.keys(payload).length === 0) {
        return Promise.resolve(item);
      }
      return updateWardrobeItem(item.id, payload);
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["wardrobe"] });
      if (updated.id !== item.id) {
        // На всякий случай — апдейт-функция не должна менять id.
        return;
      }
      if (
        (updated.category ?? "") !== (item.category ?? "") ||
        (updated.name ?? "") !== (item.name ?? "")
      ) {
        trackEvent("wardrobe_item_corrected", {
          item_id: updated.id,
          category: updated.category,
          name_changed: (updated.name ?? "") !== (item.name ?? ""),
        });
      }
      onClose();
    },
  });

  return (
    <div className="mt-5 flex flex-col gap-4 rounded-xl border border-canvas-border bg-canvas-card p-4 sm:flex-row">
      {item.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={item.image_url}
          alt={editName || "Загруженная вещь"}
          className="h-28 w-28 flex-shrink-0 rounded-lg object-cover"
        />
      ) : null}
      <div className="flex-1 space-y-3">
        <p className="text-sm font-medium text-ink">{headline}</p>

        <div className="space-y-1.5">
          <Label htmlFor="item-name">Название</Label>
          <input
            id="item-name"
            type="text"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            placeholder="например, белая блузка с пышными рукавами"
            disabled={updateMutation.isPending}
            className="h-9 w-full rounded-lg border border-canvas-border bg-canvas-card px-3 text-sm text-ink disabled:opacity-60"
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="item-category">Категория</Label>
          <select
            id="item-category"
            value={editCategory}
            onChange={(e) => setEditCategory(e.target.value)}
            disabled={updateMutation.isPending}
            autoFocus={isUndetected}
            className="h-9 w-full rounded-lg border border-canvas-border bg-canvas-card px-3 text-sm text-ink disabled:opacity-60"
          >
            {isUndetected ? (
              <option value="" disabled>
                — выберите категорию —
              </option>
            ) : null}
            {item.category && CATEGORY_LABEL[item.category] && !CATEGORIES.find((c) => c.value === item.category) ? (
              <option value={item.category}>{CATEGORY_LABEL[item.category]}</option>
            ) : null}
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button
            onClick={() => updateMutation.mutate()}
            loading={updateMutation.isPending}
            loadingText="Сохраняем…"
            disabled={isUndetected && !editCategory}
          >
            ОК
          </Button>
          {updateMutation.isError ? (
            <span className="text-xs text-red-600">
              Не удалось сохранить — попробуйте ещё раз.
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
