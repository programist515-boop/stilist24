"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { VoteAction } from "@/lib/schemas/preferenceQuiz";

export interface SwipeStackItem {
  /** Unique id used as React key and echoed back in the vote callback. */
  id: string;
}

export interface SwipeStackVote<T extends SwipeStackItem> {
  card: T;
  action: VoteAction;
}

interface SwipeStackProps<T extends SwipeStackItem> {
  cards: T[];
  /** Called once per vote — parent persists each one to the backend. */
  onVote: (vote: SwipeStackVote<T>) => void;
  /** Called after the last card is voted on. */
  onFinished?: (votes: SwipeStackVote<T>[]) => void;
  /**
   * Render a single card. `depth` is 0 for the top card, 1/2 for the
   * ghost cards layered beneath it. Use `onVote` to trigger the animation.
   */
  renderCard: (args: {
    card: T;
    depth: number;
    overlay: VoteAction | null;
    onVote: (action: VoteAction) => void;
    disabled: boolean;
  }) => ReactNode;
  className?: string;
}

/**
 * Stack of cards with CSS-only swipe-out animation.
 *
 * The top card is interactive. Up to two more cards are rendered beneath
 * it with a scale+opacity ladder so the stack has visible depth. When the
 * user votes we freeze interaction for 280ms while the top card slides
 * out, then pop it from the internal queue and the next card takes over.
 *
 * No gesture library — the buttons inside `renderCard` (see `QuizCard`)
 * are the only way to vote.
 */
export function SwipeStack<T extends SwipeStackItem>({
  cards,
  onVote,
  onFinished,
  renderCard,
  className,
}: SwipeStackProps<T>) {
  const [remaining, setRemaining] = useState<T[]>(cards);
  const [outgoing, setOutgoing] = useState<{
    card: T;
    action: VoteAction;
  } | null>(null);
  const [history, setHistory] = useState<SwipeStackVote<T>[]>([]);

  // If the parent swaps the card list (different quiz stage), reset.
  useEffect(() => {
    setRemaining(cards);
    setOutgoing(null);
    setHistory([]);
  }, [cards]);

  const top = remaining[0];
  const visible = useMemo(() => remaining.slice(0, 3), [remaining]);

  const handleVote = (action: VoteAction) => {
    if (!top || outgoing) return;
    setOutgoing({ card: top, action });
    const vote: SwipeStackVote<T> = { card: top, action };
    onVote(vote);

    // Drop the card from state once the CSS transition wraps up. Using a
    // plain timeout keeps this dependency-free.
    window.setTimeout(() => {
      setRemaining((prev) => prev.slice(1));
      setOutgoing(null);
      setHistory((prev) => {
        const next = [...prev, vote];
        if (next.length === cards.length) {
          onFinished?.(next);
        }
        return next;
      });
    }, 280);
  };

  if (!top) {
    return null;
  }

  return (
    <div
      className={cn(
        "relative mx-auto h-[560px] w-full max-w-sm",
        className
      )}
    >
      {visible
        .slice()
        .reverse()
        .map((card) => {
          const depth = remaining.indexOf(card);
          const isTop = depth === 0;
          const isOutgoing = isTop && outgoing?.card.id === card.id;

          const depthStyle = isTop
            ? ""
            : depth === 1
              ? "scale-[0.96] translate-y-3 opacity-80"
              : "scale-[0.92] translate-y-6 opacity-60";

          const outgoingStyle = isOutgoing
            ? outgoing!.action === "like"
              ? "translate-x-[140%] rotate-12 opacity-0"
              : "-translate-x-[140%] -rotate-12 opacity-0"
            : "";

          return (
            <div
              key={card.id}
              className={cn(
                "absolute inset-x-0 top-0 flex justify-center transition-all duration-300 ease-out",
                depthStyle,
                outgoingStyle
              )}
              style={{ zIndex: 10 - depth }}
            >
              {renderCard({
                card,
                depth,
                overlay: isOutgoing ? outgoing!.action : null,
                onVote: handleVote,
                disabled: !isTop || !!outgoing,
              })}
            </div>
          );
        })}
    </div>
  );
}

/**
 * Small helper — exposes a status summary above / below the stack.
 */
export function SwipeStackProgress({
  total,
  done,
  likes,
}: {
  total: number;
  done: number;
  likes: number;
}) {
  return (
    <div className="flex items-center justify-center gap-4 text-xs text-ink-muted">
      <span>
        Пройдено <span className="font-medium text-ink">{done}</span> из{" "}
        <span className="font-medium text-ink">{total}</span>
      </span>
      <span className="h-3 w-px bg-canvas-border" />
      <span>
        Лайков <span className="font-medium text-emerald-700">{likes}</span>
      </span>
    </div>
  );
}
