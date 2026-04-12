/**
 * Localization dictionaries for the user analysis result screen.
 *
 * The backend returns stable English keys (see `config/rules/*.yaml`):
 *   - Kibbe families:   dramatic / natural / classic / gamine / romantic
 *   - 12-season palette: light_spring, true_spring, ..., bright_winter
 *   - Color axes:        undertone / depth / chroma / contrast
 *   - Axis values:       warm, cool, light, deep, soft, bright, low, high, ...
 *
 * Components should never display these raw keys. Use the helpers below
 * so that every surface (AnalysisResultCard, Today, Outfits, ...) reads
 * from one source of truth. Missing keys fall back to a prettified
 * capitalized form so the UI never shows `undefined` or a raw `foo_bar`.
 */

// ---- Kibbe / style vector families -----------------------------------------

export const KIBBE_FAMILY_LABEL: Record<string, string> = {
  dramatic: "Драматик",
  natural: "Натурал",
  classic: "Классик",
  gamine: "Гамин",
  romantic: "Романтик",
};

export function formatKibbeFamily(key: string): string {
  return KIBBE_FAMILY_LABEL[key.toLowerCase()] ?? prettify(key);
}

// ---- 12-season color palette -----------------------------------------------

export const SEASON_LABEL: Record<string, string> = {
  // spring family
  light_spring: "Светлая весна",
  true_spring: "Истинная весна",
  bright_spring: "Яркая весна",
  // summer family
  light_summer: "Светлое лето",
  true_summer: "Истинное лето",
  soft_summer: "Мягкое лето",
  // autumn family
  soft_autumn: "Мягкая осень",
  true_autumn: "Истинная осень",
  deep_autumn: "Глубокая осень",
  // winter family
  deep_winter: "Глубокая зима",
  true_winter: "Истинная зима",
  bright_winter: "Яркая зима",
};

export function formatSeason(key: string | null | undefined): string {
  if (!key) return "—";
  return SEASON_LABEL[key.toLowerCase()] ?? prettify(key);
}

// ---- Color axes (labels + values) ------------------------------------------

export const COLOR_AXIS_LABEL: Record<string, string> = {
  undertone: "Подтон",
  depth: "Глубина",
  chroma: "Насыщенность",
  contrast: "Контраст",
};

export const COLOR_AXIS_VALUE_LABEL: Record<string, string> = {
  // undertone
  warm: "тёплый",
  "warm-neutral": "тёпло-нейтральный",
  "neutral-warm": "нейтрально-тёплый",
  cool: "холодный",
  "cool-neutral": "холодно-нейтральный",
  "neutral-cool": "нейтрально-холодный",
  neutral: "нейтральный",
  // depth
  light: "светлая",
  "medium-light": "средне-светлая",
  medium: "средняя",
  "medium-deep": "средне-глубокая",
  deep: "глубокая",
  // chroma
  bright: "яркая",
  "medium-bright": "умеренно-яркая",
  clear: "чистая",
  "medium-soft": "умеренно-мягкая",
  soft: "мягкая",
  // contrast
  low: "низкий",
  "medium-low": "ниже среднего",
  "medium-high": "выше среднего",
  high: "высокий",
};

export function formatColorAxisLabel(key: string): string {
  return COLOR_AXIS_LABEL[key.toLowerCase()] ?? prettify(key);
}

export function formatColorAxisValue(value: string): string {
  return COLOR_AXIS_VALUE_LABEL[value.toLowerCase()] ?? prettify(value);
}

// ---- Photo slots -----------------------------------------------------------

export const PHOTO_SLOT_LABEL: Record<string, string> = {
  front: "Анфас",
  side: "Профиль",
  portrait: "Портрет",
};

export function formatPhotoSlot(slot: string): string {
  return PHOTO_SLOT_LABEL[slot.toLowerCase()] ?? prettify(slot);
}

// ---- helpers ---------------------------------------------------------------

/**
 * Fallback formatter for unknown keys. Turns `soft_summer` → `Soft summer`,
 * `medium-high` → `Medium high`. Never returns an empty string.
 */
function prettify(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  if (!s) return key;
  return s.charAt(0).toUpperCase() + s.slice(1);
}
