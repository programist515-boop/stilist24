"use client";

/**
 * Sends a `page_viewed` funnel event whenever the route changes.
 *
 * Mounted once inside ``AppShell`` so every screen inside the authenticated
 * layout reports its path automatically — no need to sprinkle
 * ``trackEvent`` calls at the top of every page. The emit is
 * fire-and-forget; failures never bubble up (see ``lib/api/events.ts``).
 */

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { trackEvent } from "@/lib/api/events";

export function PageViewTracker() {
  const pathname = usePathname();

  useEffect(() => {
    if (!pathname) return;
    trackEvent("page_viewed", { path: pathname });
  }, [pathname]);

  return null;
}
