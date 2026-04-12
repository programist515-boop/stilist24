import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-11 w-full rounded-xl border border-canvas-border bg-canvas-card px-4 text-sm text-ink",
        "placeholder:text-ink-muted",
        "focus-visible:border-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/10",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";
