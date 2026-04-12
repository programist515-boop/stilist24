import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/**
 * Plain shimmering placeholder block. Use as a building block inside
 * feature-specific skeletons (outfit card skeleton, today card skeleton…).
 */
export function Skeleton({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn(
        "animate-pulse rounded-xl bg-canvas-border/70",
        className
      )}
      {...props}
    />
  );
}
