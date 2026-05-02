import { apiRequest } from "./client";
import {
  ActiveProfileSourceResponseSchema,
  ColorAdvanceToSeasonResponseSchema,
  ColorCompleteResponseSchema,
  ColorStartResponseSchema,
  IdentityAdvanceToTryOnResponseSchema,
  IdentityCompleteResponseSchema,
  IdentityStartResponseSchema,
  IdentityTryOnStatusResponseSchema,
  type ActiveProfileSourceResponse,
  type ColorAdvanceToSeasonResponse,
  type ColorCompleteResponse,
  type ColorStartResponse,
  type IdentityAdvanceToTryOnResponse,
  type IdentityCompleteResponse,
  type IdentityStartResponse,
  type IdentityTryOnStatusResponse,
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

export async function advanceToTryon(
  sessionId: string,
  userPhotoId: string
): Promise<IdentityAdvanceToTryOnResponse> {
  // Backend builds three FASHN try-on jobs sequentially (each: submit +
  // up to 180s polling against the FASHN provider + S3 upload), so the
  // whole call can take 1–3 min on a slow FASHN day. The default 30s
  // client timeout was killing the request before the first job even
  // finished. 4 min gives the backend room without letting requests
  // hang forever if FASHN is dead.
  const data = await apiRequest(
    `/preference-quiz/identity/${sessionId}/advance-to-tryon`,
    {
      method: "POST",
      query: { user_photo_id: userPhotoId },
      timeoutMs: 240_000,
    }
  );
  return IdentityAdvanceToTryOnResponseSchema.parse(data);
}

export async function getTryonStatus(
  sessionId: string
): Promise<IdentityTryOnStatusResponse> {
  const data = await apiRequest(
    `/preference-quiz/identity/${sessionId}/tryon-status`
  );
  return IdentityTryOnStatusResponseSchema.parse(data);
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
