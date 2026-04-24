"use client";

import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { clearSession, isAuthenticated } from "@/lib/session";
import { clearLastAnalysis } from "@/lib/local-store";
import { useEffect, useState } from "react";

/** Logout button — only visible when the user is authenticated.
 *
 * Clears the JWT + active persona + local analysis cache, invalidates
 * every React Query cache, and sends the user back to ``/sign-in``. We
 * deliberately keep the browser UUID (``user-id``) so the dev fallback
 * path keeps working if the user chooses to browse without logging in.
 */
export function AccountMenu() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    setAuthed(isAuthenticated());
  }, []);

  if (!authed) return null;

  const handleLogout = () => {
    clearSession();
    clearLastAnalysis();
    queryClient.clear();
    router.push("/sign-in");
  };

  return (
    <button
      type="button"
      onClick={handleLogout}
      className="rounded-full px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-accent-soft hover:text-ink"
    >
      Выйти
    </button>
  );
}
