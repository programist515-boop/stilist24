import { z } from "zod";

// Zod-схемы для /reference-looks — соответствуют app/schemas/reference_looks.py.

export const MatchedItemSchema = z.object({
  slot: z.string(),
  item_id: z.string(),
  match_quality: z.number().min(0).max(1),
  match_reasons: z.array(z.string()).default([]),
});
export type MatchedItem = z.infer<typeof MatchedItemSchema>;

export const MissingSlotSchema = z.object({
  slot: z.string(),
  requires: z.record(z.unknown()).default({}),
  shopping_hint: z.string(),
});
export type MissingSlot = z.infer<typeof MissingSlotSchema>;

export const ReferenceLookSchema = z.object({
  look_id: z.string(),
  title: z.string(),
  occasion: z.string().nullable().optional(),
  image_url: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  matched_items: z.array(MatchedItemSchema).default([]),
  missing_slots: z.array(MissingSlotSchema).default([]),
  completeness: z.number().min(0).max(1),
  slot_order: z.array(z.string()).default([]),
});
export type ReferenceLook = z.infer<typeof ReferenceLookSchema>;

export const ReferenceLooksResponseSchema = z.object({
  subtype: z.string().nullable().optional(),
  looks: z.array(ReferenceLookSchema).default([]),
});
export type ReferenceLooksResponse = z.infer<typeof ReferenceLooksResponseSchema>;
