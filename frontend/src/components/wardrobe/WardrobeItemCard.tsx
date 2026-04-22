import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import type { WardrobeItem } from "@/lib/schemas";

const CATEGORY_LABEL: Record<string, string> = {
  top: "Верх",
  bottom: "Низ",
  outerwear: "Верхняя одежда",
  shoes: "Обувь",
  dress: "Платье",
  accessory: "Аксессуар",
};

function getStringList(
  attrs: Record<string, unknown>,
  key: string
): string[] {
  const raw = attrs[key];
  if (Array.isArray(raw))
    return raw.filter((v): v is string => typeof v === "string");
  return [];
}

export function WardrobeItemCard({ item }: { item: WardrobeItem }) {
  const attrs = (item.attributes ?? {}) as Record<string, unknown>;
  const tags = getStringList(attrs, "style_tags");
  const colors = getStringList(attrs, "colors");
  const categoryLabel = item.category
    ? CATEGORY_LABEL[item.category] ?? item.category
    : "вещь";

  return (
    <div className="group flex h-full flex-col overflow-hidden rounded-2xl border border-canvas-border bg-canvas-card shadow-card transition-shadow hover:shadow-lg">
      <div className="relative aspect-square w-full overflow-hidden bg-accent-soft">
        {item.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.image_url}
            alt={categoryLabel}
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs text-ink-muted">
            Нет фото
          </div>
        )}
        {item.is_verified ? (
          <div className="absolute right-2 top-2">
            <Badge tone="success">Проверено</Badge>
          </div>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h3 className="text-sm font-semibold text-ink">
          {categoryLabel}
        </h3>
        {tags.length > 0 || colors.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {tags.slice(0, 3).map((t) => (
              <Badge key={`tag-${t}`}>{t}</Badge>
            ))}
            {colors.slice(0, 2).map((c) => (
              <Badge key={`color-${c}`} tone="neutral">
                {c}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-xs text-ink-muted">Тегов пока нет</p>
        )}
        <Link
          href={`/wardrobe/${item.id}/color-tryon`}
          className="mt-auto text-xs font-medium text-ink underline-offset-2 hover:underline"
        >
          Примерь в цветах палитры →
        </Link>
      </div>
    </div>
  );
}
