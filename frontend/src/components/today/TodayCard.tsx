import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import type { TodaySlot, WardrobeItem } from "@/lib/schemas";

type SlotMeta = {
  title: string;
  tag: string;
  description: string;
  accent: string;
  ring: string;
  badgeTone: "neutral" | "info" | "warning";
};

const COPY: Record<TodaySlot["label"], SlotMeta> = {
  safe: {
    title: "Безопасный",
    tag: "Комфортно",
    description: "Близко к тому, что уже точно работает.",
    accent: "from-canvas to-accent-soft/40",
    ring: "ring-1 ring-canvas-border",
    badgeTone: "neutral",
  },
  balanced: {
    title: "Сбалансированный",
    tag: "На грани",
    description: "Небольшой шаг за пределы привычного.",
    accent: "from-sky-50/60 to-canvas",
    ring: "ring-1 ring-sky-100",
    badgeTone: "info",
  },
  expressive: {
    title: "Смелый",
    tag: "Рискнуть",
    description: "Двигает ваш стиль в новом направлении.",
    accent: "from-amber-50/70 to-canvas",
    ring: "ring-1 ring-amber-100",
    badgeTone: "warning",
  },
};

interface TodayCardProps {
  slot: TodaySlot;
  imageById: Map<string, string>;
}

export function TodayCard({ slot, imageById }: TodayCardProps) {
  const meta = COPY[slot.label];
  const items = slot.outfit.items ?? [];
  const overall = slot.outfit.scores?.overall;

  return (
    <Card
      padding="md"
      className={cn(
        "relative flex h-full flex-col bg-gradient-to-b",
        meta.accent,
        meta.ring
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <CardTitle className="text-lg">{meta.title}</CardTitle>
          <CardSubtitle className="mt-1">{meta.description}</CardSubtitle>
        </div>
        <Badge tone={meta.badgeTone}>{meta.tag}</Badge>
      </div>

      {typeof overall === "number" ? (
        <div className="mt-4 flex items-baseline gap-2">
          <span className="font-display text-3xl leading-none text-ink">
            {Math.round(overall * 100)}
          </span>
          <span className="text-[10px] uppercase tracking-wide text-ink-muted">
            оценка
          </span>
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="mt-5 grid grid-cols-3 gap-2">
          {items.map((item, idx) => {
            const image =
              item.image_url ?? (item.id ? imageById.get(item.id) : undefined);
            return (
              <li
                key={item.id ?? idx}
                className="aspect-square overflow-hidden rounded-xl border border-canvas-border bg-canvas-card"
              >
                {image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={image}
                    alt={item.category ?? ""}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center px-1 text-center text-[10px] capitalize text-ink-muted">
                    {item.category ?? "вещь"}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}

      {slot.reasons.length > 0 ? (
        <details className="mt-5 group">
          <summary className="flex cursor-pointer items-center gap-1 text-xs font-medium text-ink-muted transition-colors hover:text-ink">
            <span>Почему этот образ</span>
            <span className="transition-transform group-open:rotate-90">›</span>
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-ink-muted">
            {slot.reasons.slice(0, 4).map((r, i) => (
              <li key={i}>· {r}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}

export function TodayCardSkeleton() {
  return (
    <Card padding="md" className="animate-pulse">
      <div className="h-5 w-24 rounded-full bg-canvas-border/70" />
      <div className="mt-2 h-4 w-40 rounded-full bg-canvas-border/60" />
      <div className="mt-5 grid grid-cols-3 gap-2">
        <div className="aspect-square rounded-xl bg-canvas-border/60" />
        <div className="aspect-square rounded-xl bg-canvas-border/60" />
        <div className="aspect-square rounded-xl bg-canvas-border/60" />
      </div>
    </Card>
  );
}

export function buildImageMap(items: WardrobeItem[] | undefined): Map<string, string> {
  const map = new Map<string, string>();
  for (const item of items ?? []) {
    if (item.id && item.image_url) map.set(item.id, item.image_url);
  }
  return map;
}
