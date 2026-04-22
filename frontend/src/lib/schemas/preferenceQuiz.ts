import { z } from "zod";

/**
 * Schemas for the preference-based quiz.
 *
 * Two parallel flows:
 *  - identity: pick Kibbe subtype by liking reference photos (two stages:
 *    stock photos, then try-on composites on the user's own body).
 *  - color: pick the 12-season palette by liking drapery composites
 *    (stage 1 narrows to a season family, stage 2 picks the season).
 *
 * Responses all wear `.passthrough()` so unexpected backend fields never
 * turn into a crash.
 */

/* ---------- shared ---------- */

export const VoteActionSchema = z.enum(["like", "dislike"]);
export type VoteAction = z.infer<typeof VoteActionSchema>;

export const ProfileSourceSchema = z.enum(["algorithmic", "preference"]);
export type ProfileSource = z.infer<typeof ProfileSourceSchema>;

const RankingEntrySchema = z
  .object({
    subtype: z.string().optional(),
    season: z.string().optional(),
    family: z.string().optional(),
    score: z.number().optional(),
    likes: z.number().optional(),
    dislikes: z.number().optional(),
  })
  .passthrough();

/* ---------- identity quiz ---------- */

export const IdentityStockCandidateSchema = z
  .object({
    candidate_id: z.string(),
    subtype: z.string(),
    image_url: z.string().nullable().optional(),
    title: z.string().nullable().optional(),
    subtitle: z.string().nullable().optional(),
    stage: z.literal("stock"),
  })
  .passthrough();
export type IdentityStockCandidate = z.infer<typeof IdentityStockCandidateSchema>;

export const IdentityStartResponseSchema = z
  .object({
    session_id: z.string(),
    candidates: z.array(IdentityStockCandidateSchema).default([]),
  })
  .passthrough();
export type IdentityStartResponse = z.infer<typeof IdentityStartResponseSchema>;

export const IdentityTryOnCandidateSchema = z
  .object({
    candidate_id: z.string(),
    subtype: z.string(),
    tryon_job_id: z.string(),
    title: z.string().nullable().optional(),
    subtitle: z.string().nullable().optional(),
    stage: z.literal("tryon"),
  })
  .passthrough();
export type IdentityTryOnCandidate = z.infer<typeof IdentityTryOnCandidateSchema>;

export const IdentityAdvanceToTryOnResponseSchema = z
  .object({
    session_id: z.string(),
    candidates: z.array(IdentityTryOnCandidateSchema).default([]),
    tryon_job_ids: z.array(z.string()).default([]),
  })
  .passthrough();
export type IdentityAdvanceToTryOnResponse = z.infer<
  typeof IdentityAdvanceToTryOnResponseSchema
>;

export const TryOnStatusSchema = z.enum([
  "pending",
  "running",
  "succeeded",
  "failed",
]);
export type TryOnStatus = z.infer<typeof TryOnStatusSchema>;

export const TryOnJobStatusSchema = z
  .object({
    job_id: z.string(),
    status: z.string(),
    result_image_url: z.string().nullable().optional(),
    error_message: z.string().nullable().optional(),
  })
  .passthrough();
export type TryOnJobStatus = z.infer<typeof TryOnJobStatusSchema>;

export const IdentityTryOnStatusResponseSchema = z
  .object({
    jobs: z.array(TryOnJobStatusSchema).default([]),
  })
  .passthrough();
export type IdentityTryOnStatusResponse = z.infer<
  typeof IdentityTryOnStatusResponseSchema
>;

export const IdentityCompleteResponseSchema = z
  .object({
    winner: z.string().nullable(),
    confidence: z.number(),
    ranking: z.array(RankingEntrySchema).default([]),
  })
  .passthrough();
export type IdentityCompleteResponse = z.infer<
  typeof IdentityCompleteResponseSchema
>;

/* ---------- color quiz ---------- */

export const ColorFamilyCandidateSchema = z
  .object({
    candidate_id: z.string(),
    family: z.string(),
    hex: z.string(),
    image_url: z.string().nullable().optional(),
    title: z.string().nullable().optional(),
    stage: z.literal("family"),
  })
  .passthrough();
export type ColorFamilyCandidate = z.infer<typeof ColorFamilyCandidateSchema>;

export const ColorStartResponseSchema = z
  .object({
    session_id: z.string(),
    candidates: z.array(ColorFamilyCandidateSchema).default([]),
  })
  .passthrough();
export type ColorStartResponse = z.infer<typeof ColorStartResponseSchema>;

export const ColorSeasonCandidateSchema = z
  .object({
    candidate_id: z.string(),
    season: z.string(),
    hex: z.string(),
    image_url: z.string().nullable().optional(),
    title: z.string().nullable().optional(),
    stage: z.literal("season"),
  })
  .passthrough();
export type ColorSeasonCandidate = z.infer<typeof ColorSeasonCandidateSchema>;

export const ColorAdvanceToSeasonResponseSchema = z
  .object({
    session_id: z.string(),
    candidates: z.array(ColorSeasonCandidateSchema).default([]),
  })
  .passthrough();
export type ColorAdvanceToSeasonResponse = z.infer<
  typeof ColorAdvanceToSeasonResponseSchema
>;

export const ColorCompleteResponseSchema = z
  .object({
    winner: z.string().nullable(),
    confidence: z.number(),
    ranking: z.array(RankingEntrySchema).default([]),
    family: z.string().nullable().optional(),
  })
  .passthrough();
export type ColorCompleteResponse = z.infer<typeof ColorCompleteResponseSchema>;

/* ---------- active profile source switch ---------- */

export const ActiveProfileSourceResponseSchema = z
  .object({
    source: ProfileSourceSchema,
    kibbe_type: z.string().nullable().optional(),
    color_season: z.string().nullable().optional(),
  })
  .passthrough();
export type ActiveProfileSourceResponse = z.infer<
  typeof ActiveProfileSourceResponseSchema
>;
