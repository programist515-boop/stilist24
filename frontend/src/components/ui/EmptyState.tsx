import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface EmptyStateProps {
  title: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/**
 * Quiet empty state used inside cards / sections. Centered layout with
 * optional icon and CTA. Avoids the "wall of text" feel of a bare Card.
 */
export function EmptyState({
  title,
  hint,
  icon,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-2xl border border-dashed border-canvas-border bg-canvas-card px-6 py-12 text-center",
        className
      )}
    >
      {icon ? (
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent-soft text-ink-muted">
          {icon}
        </div>
      ) : null}
      <h3 className="text-base font-semibold tracking-tight text-ink">
        {title}
      </h3>
      {hint ? (
        <p className="mt-1 max-w-sm text-sm text-ink-muted">{hint}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
