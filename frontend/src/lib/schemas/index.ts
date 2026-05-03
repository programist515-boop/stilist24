import { z } from "zod";

/* ---------- user analysis ---------- */
export const AnalysisPhotoSchema = z
  .object({
    id: z.string(),
    slot: z.enum(["front", "side", "portrait"]),
    image_key: z.string().nullable().optional(),
    image_url: z.string().nullable().optional(),
  })
  .passthrough();
export type AnalysisPhoto = z.infer<typeof AnalysisPhotoSchema>;

export const KibbeAnalysisSchema = z
  .object({
    main_type: z.string().optional(),
    confidence: z.number().optional(),
    family_scores: z.record(z.number()).optional(),
    alternatives: z
      .array(z.object({ family: z.string(), score: z.number() }).passthrough())
      .optional(),
  })
  .passthrough();

export const ColorAnalysisSchema = z
  .object({
    season_top_1: z.string().optional(),
    confidence: z.number().optional(),
    family_scores: z.record(z.number()).optional(),
    alternatives: z
      .array(z.object({ season: z.string(), score: z.number() }).passthrough())
      .optional(),
    axes: z.record(z.string()).optional(),
  })
  .passthrough();

export const UserAnalysisSchema = z
  .object({
    kibbe: KibbeAnalysisSchema.optional(),
    color: ColorAnalysisSchema.optional(),
    style_vector: z.record(z.number()).optional(),
    analyzed_at: z.string().optional(),
    photos: z.array(AnalysisPhotoSchema).default([]),
  })
  .passthrough();
export type UserAnalysis = z.infer<typeof UserAnalysisSchema>;

/* ---------- wardrobe ---------- */
export const WardrobeItemSchema = z
  .object({
    id: z.string(),
    category: z.string().nullable().optional(),
    name: z.string().nullable().optional(),
    attributes: z.record(z.unknown()).default({}),
    image_key: z.string().nullable().optional(),
    image_url: z.string().nullable().optional(),
    is_verified: z.boolean().optional(),
  })
  .passthrough();
export type WardrobeItem = z.infer<typeof WardrobeItemSchema>;

/**
 * Backend wraps the wardrobe list in `{ items, count }` (see
 * `app/schemas/wardrobe.py::WardrobeListOut`). We keep the wrapper here so
 * the `count` is typed; `listWardrobeItems` unwraps and returns the bare
 * array so existing callers keep working.
 */
export const WardrobeListResponseSchema = z
  .object({
    items: z.array(WardrobeItemSchema).default([]),
    count: z.number().int().nonnegative().default(0),
  })
  .passthrough();
export type WardrobeListResponse = z.infer<typeof WardrobeListResponseSchema>;

/**
 * `POST /wardrobe/confirm` now returns `{ item: WardrobeItem }` on success
 * and a 404 error envelope on miss (handled by the global ApiError path in
 * `api/client.ts`). No UI consumes this yet — schema is here for symmetry
 * with the backend contract.
 */
export const WardrobeConfirmResponseSchema = z
  .object({
    item: WardrobeItemSchema,
  })
  .passthrough();
export type WardrobeConfirmResponse = z.infer<typeof WardrobeConfirmResponseSchema>;

/* ---------- outfits ---------- */
export const OutfitItemSchema = z
  .object({
    id: z.string().optional(),
    category: z.string().nullable().optional(),
    name: z.string().nullable().optional(),
    image_url: z.string().nullable().optional(),
  })
  .passthrough();
export type OutfitItem = z.infer<typeof OutfitItemSchema>;

export const OutfitSchema = z
  .object({
    id: z.string().optional(),
    items: z.array(OutfitItemSchema).default([]),
    occasion: z.string().nullable().optional(),
    scores: z.record(z.number()).default({}),
    explanation: z.union([z.string(), z.array(z.string())]).optional(),
    scoring_reasons: z.array(z.string()).optional(),
    filter_pass_reasons: z.array(z.string()).optional(),
    breakdown: z.record(z.unknown()).optional(),
    generation: z
      .object({
        template: z.string().optional(),
        optional_used: z.string().nullable().optional(),
      })
      .partial()
      .passthrough()
      .optional(),
  })
  .passthrough();
export type Outfit = z.infer<typeof OutfitSchema>;

/**
 * `POST /outfits/generate` returns `{ outfits, count }` — the top-level
 * key is `outfits`, NOT `items`. The inner `OutfitSchema` still has its
 * own `items` field (the clothing pieces of a single look); that's a
 * separate level and stays unchanged.
 */
export const OutfitGenerateResponseSchema = z
  .object({
    count: z.number().optional(),
    outfits: z.array(OutfitSchema).default([]),
  })
  .passthrough();
export type OutfitGenerateResponse = z.infer<typeof OutfitGenerateResponseSchema>;

/* ---------- today ---------- */
export const TodaySlotSchema = z
  .object({
    label: z.enum(["safe", "balanced", "expressive"]),
    outfit: OutfitSchema,
    reasons: z.array(z.string()).default([]),
  })
  .passthrough();
export type TodaySlot = z.infer<typeof TodaySlotSchema>;

export const TodayResponseSchema = z
  .object({
    weather: z.string().nullable().optional(),
    occasion: z.string().nullable().optional(),
    outfits: z.array(TodaySlotSchema).default([]),
    notes: z.array(z.string()).default([]),
  })
  .passthrough();
export type TodayResponse = z.infer<typeof TodayResponseSchema>;

/* ---------- insights ---------- */
export const InsightsBehaviorSchema = z
  .object({
    total_events: z.number().default(0),
    outfits_liked: z.number().default(0),
    outfits_disliked: z.number().default(0),
    outfits_saved: z.number().default(0),
    outfits_worn: z.number().default(0),
    items_liked: z.number().default(0),
    items_disliked: z.number().default(0),
    items_worn: z.number().default(0),
    items_ignored: z.number().default(0),
    tryons_opened: z.number().default(0),
  })
  .passthrough();

export const InsightsPatternsSchema = z
  .object({
    patterns: z.array(z.string()).default([]),
    tag_counts: z
      .object({
        style: z.record(z.number()).default({}),
        line: z.record(z.number()).default({}),
        color: z.record(z.number()).default({}),
        avoidance: z.record(z.number()).default({}),
      })
      .partial()
      .passthrough()
      .default({}),
  })
  .passthrough();

export const InsightsUnderusedItemSchema = z
  .object({
    id: z.string(),
    category: z.string(),
    reason: z.string(),
  })
  .passthrough();

export const InsightsStyleShiftSchema = z
  .object({
    lines: z.array(z.string()).default([]),
    style: z
      .array(z.object({ tag: z.string(), delta: z.number() }).passthrough())
      .default([]),
    line: z
      .array(z.object({ tag: z.string(), delta: z.number() }).passthrough())
      .default([]),
    color: z
      .array(z.object({ tag: z.string(), delta: z.number() }).passthrough())
      .default([]),
  })
  .passthrough();

export const InsightsResponseSchema = z
  .object({
    window: z
      .object({
        start: z.string(),
        end: z.string(),
        days: z.number(),
      })
      .partial()
      .passthrough()
      .optional(),
    behavior: InsightsBehaviorSchema.optional(),
    preference_patterns: InsightsPatternsSchema.optional(),
    underused_items: z.array(InsightsUnderusedItemSchema).default([]),
    underused_categories: z.array(z.string()).default([]),
    style_shift: InsightsStyleShiftSchema.optional(),
    notes: z.array(z.string()).default([]),
  })
  .passthrough();
export type InsightsResponse = z.infer<typeof InsightsResponseSchema>;

/* ---------- recommendations ---------- */
export const RecommendationItemSchema = z
  .object({
    text: z.string(),
    slug: z.string().nullable().optional(),
    image_url: z.string().nullable().optional(),
  })
  .passthrough();
export type RecommendationItem = z.infer<typeof RecommendationItemSchema>;

export const RecommendationSectionSchema = z
  .object({
    key: z.string(),
    title: z.string(),
    description: z.string().default(""),
    recommended: z.array(RecommendationItemSchema).default([]),
    avoid: z.array(RecommendationItemSchema).default([]),
  })
  .passthrough();
export type RecommendationSection = z.infer<typeof RecommendationSectionSchema>;

export const RecommendationIdentitySchema = z
  .object({
    kibbe_family: z.string().nullable().optional(),
    kibbe_type: z.string().nullable().optional(),
    color_profile_summary: z.string().nullable().optional(),
    style_key: z.string().nullable().optional(),
    top_style_tags: z.array(z.string()).default([]),
  })
  .passthrough();
export type RecommendationIdentity = z.infer<
  typeof RecommendationIdentitySchema
>;

export const RecommendationGuideSchema = z
  .object({
    identity: RecommendationIdentitySchema,
    summary: z.string().default(""),
    sections: z.array(RecommendationSectionSchema).default([]),
    closing_note: z.string().default(""),
    notes: z.array(z.string()).default([]),
  })
  .passthrough();
export type RecommendationGuide = z.infer<typeof RecommendationGuideSchema>;

/* ---------- try-on ---------- */
export const TryOnJobSchema = z
  .object({
    job_id: z.string(),
    status: z.string(),
    provider: z.string().optional().nullable(),
    provider_job_id: z.string().optional().nullable(),
    result_image_key: z.string().optional().nullable(),
    result_image_url: z.string().optional().nullable(),
    metadata: z.record(z.unknown()).optional(),
    error_message: z.string().optional().nullable(),
    note: z.string().optional(),
  })
  .passthrough();
export type TryOnJob = z.infer<typeof TryOnJobSchema>;
