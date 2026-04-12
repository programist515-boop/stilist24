import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Tone = "default" | "neutral" | "success" | "warning" | "danger" | "info";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

const TONES: Record<Tone, string> = {
  default: "bg-accent-soft text-ink",
  neutral: "bg-canvas-card border border-canvas-border text-ink-muted",
  success: "bg-emerald-50 text-emerald-900 border border-emerald-100",
  warning: "bg-amber-50 text-amber-900 border border-amber-100",
  danger: "bg-red-50 text-red-900 border border-red-100",
  info: "bg-sky-50 text-sky-900 border border-sky-100",
};

export function Badge({ className, tone = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
        TONES[tone],
        className
      )}
      {...props}
    />
  );
}
