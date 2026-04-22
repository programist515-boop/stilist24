import { apiRequest } from "./client";
import {
  ColorTryOnResponseSchema,
  type ColorTryOnResponse,
  type ColorTryOnFeedback,
} from "@/lib/schemas/colorTryOn";

/**
 * API-клиент для color try-on.
 *
 * Три вызова:
 *  - POST /color-tryon/{itemId}            — запустить генерацию.
 *  - GET  /color-tryon/{itemId}            — вернуть из кэша.
 *  - POST /color-tryon/{itemId}/feedback   — отметить вариант 👍/👎.
 */

export async function generateColorTryOn(
  itemId: string
): Promise<ColorTryOnResponse> {
  const data = await apiRequest(`/color-tryon/${itemId}`, {
    method: "POST",
  });
  return ColorTryOnResponseSchema.parse(data);
}

export async function getColorTryOn(
  itemId: string
): Promise<ColorTryOnResponse> {
  const data = await apiRequest(`/color-tryon/${itemId}`);
  return ColorTryOnResponseSchema.parse(data);
}

export async function sendColorTryOnFeedback(
  itemId: string,
  payload: ColorTryOnFeedback
): Promise<void> {
  await apiRequest(`/color-tryon/${itemId}/feedback`, {
    method: "POST",
    json: payload,
  });
}
