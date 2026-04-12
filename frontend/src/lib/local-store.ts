/**
 * Tiny localStorage facade for cross-screen state that doesn't belong on
 * the server yet. We persist the latest user-analysis response so the
 * Try-on screen can pick a `user_photo_id` without forcing the user to
 * paste UUIDs by hand.
 */

import type { AnalysisPhoto, UserAnalysis } from "@/lib/schemas";

const ANALYSIS_KEY = "ai-stylist:last-analysis";

export function saveLastAnalysis(analysis: UserAnalysis): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ANALYSIS_KEY, JSON.stringify(analysis));
  } catch {
    /* quota or serialization — fine to skip */
  }
}

export function loadLastAnalysis(): UserAnalysis | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(ANALYSIS_KEY);
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
  window.localStorage.removeItem(ANALYSIS_KEY);
}
