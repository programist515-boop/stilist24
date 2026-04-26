import { z } from "zod";
import { apiRequest } from "./client";

/**
 * Backend schema is `app/schemas/gap_analysis.py::GapSuggestion`.
 * `from_reference_look` и `slot_hint` пришли из интеграции с Phase 7
 * (см. ai-stylist-starter/app/services/gap_analysis_service.py) — это
 * suggestions, рождённые из `missing_slots` референсных луков подтипа.
 */
export const GapSuggestionSchema = z.object({
  item: z.string(),
  category: z.string(),
  why: z.string(),
  action: z.string().default("Попробовать добавить"),
  from_reference_look: z.string().nullable().optional(),
  slot_hint: z.string().nullable().optional(),
});
export type GapSuggestion = z.infer<typeof GapSuggestionSchema>;

export const UntappedItemSchema = z.object({
  item_id: z.string(),
  category: z.string(),
  outfit_count: z.number(),
  reason: z.string(),
});
export type UntappedItem = z.infer<typeof UntappedItemSchema>;

export const GapAnalysisResponseSchema = z.object({
  suggestions: z.array(GapSuggestionSchema),
  untapped_items: z.array(UntappedItemSchema),
  missing_categories: z.array(z.string()),
  notes: z.array(z.string()),
});
export type GapAnalysisResponse = z.infer<typeof GapAnalysisResponseSchema>;

export async function fetchGapAnalysis(): Promise<GapAnalysisResponse> {
  const data = await apiRequest("/wardrobe/gap-analysis");
  return GapAnalysisResponseSchema.parse(data);
}
