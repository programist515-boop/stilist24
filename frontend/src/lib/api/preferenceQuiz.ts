import { apiRequest } from "./client";
import {
  ActiveProfileSourceResponseSchema,
  ColorAdvanceToSeasonResponseSchema,
  ColorCompleteResponseSchema,
  ColorStartResponseSchema,
  IdentityCompleteResponseSchema,
  IdentityStartResponseSchema,
  IdentityWardrobeMatchResponseSchema,
  type ActiveProfileSourceResponse,
  type ColorAdvanceToSeasonResponse,
  type ColorCompleteResponse,
  type ColorStartResponse,
  type IdentityCompleteResponse,
  type IdentityStartResponse,
  type IdentityWardrobeMatchResponse,
  type ProfileSource,
  type VoteAction,
} from "@/lib/schemas/preferenceQuiz";

/* ---------- identity ---------- */

export async function startIdentityQuiz(): Promise<IdentityStartResponse> {
  const data = await apiRequest("/preference-quiz/identity/start", {
    method: "POST",
  });
  return IdentityStartResponseSchema.parse(data);
}

export async function voteIdentity(
  sessionId: string,
  candidateId: string,
  action: VoteAction
): Promise<void> {
  await apiRequest(`/preference-quiz/identity/${sessionId}/vote`, {
    method: "POST",
    json: { candidate_id: candidateId, action },
  });
}

/**
 * Project every liked stock-stage look against the user's wardrobe.
 *
 * For each (subtype, look_id) the user liked, the backend returns
 * the matched wardrobe items + missing slots (with shopping hints) +
 * completeness. This is fast (no FASHN, no external API) — the
 * default 30s timeout is plenty.
 */
export async function getWardrobeMatch(
  sessionId: string
): Promise<IdentityWardrobeMatchResponse> {
  const data = await apiRequest(
    `/preference-quiz/identity/${sessionId}/wardrobe-match`,
    { method: "POST" }
  );
  return IdentityWardrobeMatchResponseSchema.parse(data);
}

export async function completeIdentityQuiz(
  sessionId: string
): Promise<IdentityCompleteResponse> {
  const data = await apiRequest(
    `/preference-quiz/identity/${sessionId}/complete`,
    { method: "POST" }
  );
  return IdentityCompleteResponseSchema.parse(data);
}

/* ---------- color ---------- */

export async function startColorQuiz(): Promise<ColorStartResponse> {
  const data = await apiRequest("/preference-quiz/color/start", {
    method: "POST",
  });
  return ColorStartResponseSchema.parse(data);
}

export async function voteColor(
  sessionId: string,
  candidateId: string,
  action: VoteAction
): Promise<void> {
  await apiRequest(`/preference-quiz/color/${sessionId}/vote`, {
    method: "POST",
    json: { candidate_id: candidateId, action },
  });
}

export async function advanceToSeason(
  sessionId: string
): Promise<ColorAdvanceToSeasonResponse> {
  const data = await apiRequest(
    `/preference-quiz/color/${sessionId}/advance-to-season`,
    { method: "POST" }
  );
  return ColorAdvanceToSeasonResponseSchema.parse(data);
}

export async function completeColorQuiz(
  sessionId: string
): Promise<ColorCompleteResponse> {
  const data = await apiRequest(
    `/preference-quiz/color/${sessionId}/complete`,
    { method: "POST" }
  );
  return ColorCompleteResponseSchema.parse(data);
}

/* ---------- active profile switch ---------- */

export async function setActiveProfileSource(
  source: ProfileSource
): Promise<ActiveProfileSourceResponse> {
  const data = await apiRequest("/user/active-profile-source", {
    method: "POST",
    json: { source },
  });
  return ActiveProfileSourceResponseSchema.parse(data);
}
