import { apiRequest } from "./client";
import {
  WardrobeItemSchema,
  WardrobeListResponseSchema,
  type WardrobeItem,
} from "@/lib/schemas";

/**
 * Backend wraps the list as `{ items, count }` since the Phase 3 contract
 * polish. We unwrap here so every page that already consumes a bare array
 * (wardrobe/outfits/tryon/today) stays untouched. If a screen needs the
 * `count` value in the future, switch to reading the wrapper directly.
 */
export async function listWardrobeItems(): Promise<WardrobeItem[]> {
  const data = await apiRequest("/wardrobe/items");
  return WardrobeListResponseSchema.parse(data).items;
}

export async function uploadWardrobeItem(input: {
  image: File;
  category?: string;
}): Promise<WardrobeItem> {
  const form = new FormData();
  form.append("image", input.image);
  if (input.category) form.append("category", input.category);

  // Upload + rembg (cold-start ONNX модели может занять 30–60s) +
  // CV-распознавание + S3-сохранение → 90s — реалистичный потолок.
  // Дефолтный 30s в apiRequest для этого эндпоинта мал.
  const data = await apiRequest("/wardrobe/upload", {
    method: "POST",
    form,
    timeoutMs: 120_000,
  });
  return WardrobeItemSchema.parse(data);
}

/**
 * Заменить категорию существующей вещи. Используется для ручного
 * исправления, когда CV-определение оказалось неверным или пользователь
 * хочет переместить вещь в другой слот.
 */
export async function updateWardrobeItemCategory(
  itemId: string,
  category: string
): Promise<WardrobeItem> {
  const data = await apiRequest(`/wardrobe/${itemId}/category`, {
    method: "PATCH",
    json: { category },
  });
  return WardrobeItemSchema.parse(data);
}

/**
 * Расширенный PATCH: подменить имя и/или категорию одним запросом.
 * Любое поле опционально. Используется на экране подтверждения после
 * автоматического распознавания (`LastUploadedReview` → кнопка «ОК»).
 */
export async function updateWardrobeItem(
  itemId: string,
  payload: { category?: string; name?: string }
): Promise<WardrobeItem> {
  const data = await apiRequest(`/wardrobe/${itemId}`, {
    method: "PATCH",
    json: payload,
  });
  return WardrobeItemSchema.parse(data);
}
