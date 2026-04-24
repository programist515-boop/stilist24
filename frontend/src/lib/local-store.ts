/**
 * Tiny localStorage facade for cross-screen state that doesn't belong on
 * the server yet. We persist the latest user-analysis response so the
 * Try-on screen can pick a `user_photo_id` without forcing the user to
 * paste UUIDs by hand.
 *
 * After the multi-persona migration, each persona has its own cached
 * analysis: switching personas in the nav bar must not surface the
 * previous persona's photos. The key is therefore namespaced by the
 * active persona id; calls without a persona id fall back to the
 * legacy bare key so existing dev sessions continue to read their last
 * cached analysis.
 */

import type { AnalysisPhoto, UserAnalysis } from "@/lib/schemas";
import { getActivePersonaId } from "@/lib/session";

const LEGACY_ANALYSIS_KEY = "ai-stylist:last-analysis";
const ANALYSIS_KEY_PREFIX = "ai-stylist:last-analysis:";

function currentKey(): string {
  const personaId = getActivePersonaId();
  return personaId ? `${ANALYSIS_KEY_PREFIX}${personaId}` : LEGACY_ANALYSIS_KEY;
}

export function saveLastAnalysis(analysis: UserAnalysis): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(currentKey(), JSON.stringify(analysis));
  } catch {
    /* quota or serialization — fine to skip */
  }
}

export function loadLastAnalysis(): UserAnalysis | null {
  if (typeof window === "undefined") return null;
  const key = currentKey();
  let raw = window.localStorage.getItem(key);
  // Transparent legacy fallback: if the persona-scoped key is empty but
  // the old single-slot key has data, return it once so returning users
  // don't see an empty analyze screen after upgrading.
  if (!raw && key !== LEGACY_ANALYSIS_KEY) {
    raw = window.localStorage.getItem(LEGACY_ANALYSIS_KEY);
  }
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserAnalysis;
  } catch {
    return null;
  }
}

export function loadLastAnalysisPhotos(): AnalysisPhoto[] {
  return loadLastAnalysis()?.photos ?? [];
}

export function clearLastAnalysis(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(currentKey());
  // On logout the caller wipes session anyway, but kill the legacy key
  // too so a future anonymous session starts clean.
  window.localStorage.removeItem(LEGACY_ANALYSIS_KEY);
}
