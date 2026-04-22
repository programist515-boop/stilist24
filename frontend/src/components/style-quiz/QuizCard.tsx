"use client";

import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import type { VoteAction } from "@/lib/schemas/preferenceQuiz";

interface QuizCardProps {
  imageUrl: string | null | undefined;
  title?: string | null;
  subtitle?: string | null;
  badge?: {
    label: string;
    hex?: string;
  } | null;
  disabled?: boolean;
  onVote: (action: VoteAction) => void;
  /**
   * Overlay hint — set by the SwipeStack while it animates an outgoing card
   * so the user sees "like" / "dislike" feedback before the card disappears.
   */
  overlay?: VoteAction | null;
  /** Stack depth (0 = top card). Used only for visual stacking. */
  depth?: number;
  className?: string;
}

/**
 * Card + two voting buttons. Stateless — parent (usually `SwipeStack`)
 * owns the animation lifecycle.
 */
export function QuizCard({
  imageUrl,
  title,
  subtitle,
  badge,
  disabled,
  onVote,
  overlay,
  depth = 0,
  className,
}: QuizCardProps) {
  const isTop = depth === 0;
  return (
    <div
      className={cn(
        "relative flex w-full max-w-sm flex-col overflow-hidden rounded-3xl border border-canvas-border bg-canvas-card shadow-card",
        className
      )}
    >
      <div className="relative aspect-[3/4] w-full bg-accent-soft">
        {imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageUrl}
            alt={title ?? "кандидат"}
            className="h-full w-full object-cover"
            draggable={false}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs text-ink-muted">
            Нет изображения
          </div>
        )}

        {badge ? (
          <div className="absolute left-3 top-3 flex items-center gap-2">
            {badge.hex ? (
              <span
                aria-hidden
                className="inline-block h-5 w-5 rounded-full border border-white shadow"
                style={{ backgroundColor: badge.hex }}
              />
            ) : null}
            <Badge tone="neutral">{badge.label}</Badge>
          </div>
        ) : null}

        {overlay ? (
          <div
            className={cn(
              "pointer-events-none absolute inset-0 flex items-center justify-center text-5xl font-bold uppercase tracking-widest",
              overlay === "like"
                ? "bg-emerald-500/25 text-emerald-700"
                : "bg-red-500/25 text-red-700"
            )}
          >
            {overlay === "like" ? "Нравится" : "Не моё"}
          </div>
        ) : null}
      </div>

      {(title || subtitle) && (
        <div className="px-5 pt-4">
          {title ? (
            <p className="font-display text-lg tracking-tight text-ink">
              {title}
            </p>
          ) : null}
          {subtitle ? (
            <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>
          ) : null}
        </div>
      )}

      {isTop ? (
        <div className="flex gap-3 p-5">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onVote("dislike")}
            className={cn(
              "flex h-14 flex-1 items-center justify-center gap-2 rounded-full border-2 border-red-200 bg-red-50 text-base font-semibold text-red-700 transition-colors",
              "hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400",
              "disabled:cursor-not-allowed disabled:opacity-60"
            )}
          >
            <span aria-hidden>✕</span>
            <span>Не моё</span>
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onVote("like")}
            className={cn(
              "flex h-14 flex-1 items-center justify-center gap-2 rounded-full bg-emerald-500 text-base font-semibold text-white transition-colors",
              "hover:bg-emerald-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400",
              "disabled:cursor-not-allowed disabled:opacity-60"
            )}
          >
            <span aria-hidden>♥</span>
            <span>Нравится</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
