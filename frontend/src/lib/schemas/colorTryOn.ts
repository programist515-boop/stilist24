import { z } from "zod";

// Zod-схемы для color try-on (примерка вещи в цветах палитры).
// Отражают app/schemas/color_tryon.py на бэке.

export const ColorTryOnVariantSchema = z.object({
  color_hex: z.string(), // "#E8735A"
  color_name: z.string(), // "терракотовый"
  image_url: z.string(),
});
export type ColorTryOnVariant = z.infer<typeof ColorTryOnVariantSchema>;

export const ColorTryOnResponseSchema = z.object({
  item_id: z.string(),
  variants: z.array(ColorTryOnVariantSchema).default([]),
  quality: z.string().default("high"), // high / medium / low
  // Машинно-читаемая причина пустого/низкокачественного результата:
  // "pattern_unfit" (принт/металлик), "palette_missing" (нет палитры).
  // Для quality="high" — null/undefined.
  reason: z.string().nullable().optional(),
});
export type ColorTryOnResponse = z.infer<typeof ColorTryOnResponseSchema>;

export const ColorTryOnFeedbackSchema = z.object({
  variant_hex: z.string(),
  liked: z.boolean(),
});
export type ColorTryOnFeedback = z.infer<typeof ColorTryOnFeedbackSchema>;
