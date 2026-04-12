import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface SectionHeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

/**
 * In-page section title. One step down from PageHeader — use to group
 * related blocks inside a screen (e.g. "Your wardrobe", "Notes").
 */
export function SectionHeader({
  title,
  description,
  action,
  className,
}: SectionHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-end justify-between gap-3 pb-3",
        className
      )}
    >
      <div>
        <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-muted">
          {title}
        </h2>
        {description ? (
          <p className="mt-1 text-sm text-ink-muted/90">{description}</p>
        ) : null}
      </div>
      {action ? <div>{action}</div> : null}
    </div>
  );
}
