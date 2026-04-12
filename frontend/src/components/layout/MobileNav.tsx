"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { NAV_ITEMS } from "./nav-items";

export function MobileNav() {
  const pathname = usePathname();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-canvas-border bg-canvas/95 backdrop-blur lg:hidden">
      <ul className="mx-auto flex max-w-3xl items-stretch gap-1 overflow-x-auto px-3 py-2">
        {NAV_ITEMS.map((item) => {
          const active = pathname?.startsWith(item.href);
          return (
            <li key={item.href} className="flex-1 min-w-[64px]">
              <Link
                href={item.href}
                className={cn(
                  "flex h-11 flex-col items-center justify-center rounded-xl px-2 text-[11px] font-medium transition-colors",
                  active
                    ? "bg-ink text-canvas"
                    : "text-ink-muted hover:bg-accent-soft hover:text-ink"
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
