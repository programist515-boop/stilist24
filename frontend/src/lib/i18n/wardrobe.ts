/**
 * Localization для слотов в референс-луках, аксессуаров, occasion и
 * категорий гардероба. Бэк отдаёт стабильные английские enum-ключи (см.
 * `config/rules/reference_looks/*.yaml` и `category_rules/*.yaml`),
 * UI читает из этого файла, чтобы пользователь видел всё по-русски.
 *
 * `shopping_hint` уже переведён на бэке (см. `_build_shopping_hint` в
 * `app/services/reference_matcher.py`), здесь живут только метки слотов
 * и occasion — которые на бэке хранятся как стабильные ключи.
 *
 * Missing keys → `humanize` fallback: `foo_bar` → `Foo bar`. Так UI
 * не показывает подчёркивания для подтипов, под которые ещё нет копи.
 */

// ---- slot имена в референсном луке ------------------------------------

export const SLOT_LABEL: Record<string, string> = {
  // верх
  top: "Верх",
  blouse: "Блуза",
  shirt: "Рубашка",
  sweater: "Свитер",
  longsleeve: "Лонгслив",
  // низ / целое платье
  bottom: "Низ",
  dress: "Платье",
  skirt: "Юбка",
  pants: "Брюки",
  // обувь / верхняя одежда
  shoes: "Обувь",
  outerwear: "Верхняя одежда",
  jacket: "Куртка",
  coat: "Пальто",
  // головные уборы / аксессуары
  headwear: "Головной убор",
  bag: "Сумка",
  belt: "Ремень",
  jewelry: "Украшения",
  scarf: "Платок",
  hosiery: "Колготки",
  eyewear: "Очки",
  // составные слоты вида `accessory:bag`
  "accessory:bag": "Сумка",
  "accessory:jewelry": "Украшения",
  "accessory:belt": "Ремень",
  "accessory:scarf": "Платок",
  "accessory:hat": "Головной убор",
};

export function formatSlot(slot: string): string {
  if (!slot) return "—";
  return SLOT_LABEL[slot.toLowerCase()] ?? humanize(slot);
}

// ---- occasion / стиль -------------------------------------------------

export const OCCASION_LABEL: Record<string, string> = {
  day: "День",
  work: "Работа",
  smart_casual: "Smart casual",
  evening: "Вечер",
  sport: "Спорт",
  casual: "Повседневный",
  // season hints из YAML
  all: "Любой сезон",
  spring_autumn: "Весна-осень",
  summer: "Лето",
  winter: "Зима",
};

export function formatOccasion(value: string | null | undefined): string {
  if (!value) return "";
  return OCCASION_LABEL[value.toLowerCase()] ?? humanize(value);
}

// ---- категории и sub_types вещей --------------------------------------

export const CATEGORY_LABEL: Record<string, string> = {
  // верх
  top: "Верх",
  blouse: "Блуза",
  ruffled_top: "Топ с воланами",
  fitted_tshirt: "Приталенная футболка",
  fine_knit: "Тонкий трикотаж",
  fine_knit_top: "Тонкий трикотаж",
  knit_sweater: "Вязаный свитер",
  knit_top: "Вязаный топ",
  silk_shell: "Шёлковый топ",
  silk_top: "Шёлковый топ",
  silk_shirt: "Шёлковая рубашка",
  button_blouse: "Блуза на пуговицах",
  button_shirt: "Рубашка на пуговицах",
  fitted_shirt: "Приталенная рубашка",
  wrap_blouse: "Блуза на запах",
  draped_knit_top: "Трикотаж с драпировкой",
  twinset: "Твинсет",
  longsleeve: "Лонгслив",
  sweater: "Свитер",
  bodysuit_fitted: "Приталенное боди",
  bustier_top: "Топ-бюстье",
  corset_top_soft: "Мягкий корсетный топ",
  // платья
  dress: "Платье",
  wrap_dress: "Платье на запах",
  slip_dress_evening: "Вечернее платье-комбинация",
  gown: "Вечернее платье",
  // низ
  bottom: "Низ",
  jeans: "Джинсы",
  trousers: "Брюки",
  cigarette_pants: "Брюки-сигареты",
  cropped_jeans: "Укороченные джинсы",
  midi_skirt: "Юбка миди",
  circle_skirt: "Юбка-солнце",
  a_line_skirt: "Юбка А-силуэта",
  mini_skirt: "Мини-юбка",
  // обувь
  shoes: "Обувь",
  heels: "Каблуки",
  kitten_heels: "Низкий каблук",
  ballet_flats: "Балетки",
  pumps: "Лодочки",
  loafers: "Лоферы",
  ankle_boots: "Ботильоны",
  knee_boots: "Сапоги",
  combat_boots: "Армейские ботинки",
  chunky_sneakers: "Массивные кроссовки",
  espadrilles: "Эспадрильи",
  mules: "Мюли",
  sandals: "Босоножки",
  // верхняя одежда
  outerwear: "Верхняя одежда",
  coat: "Пальто",
  trench: "Тренч",
  leather_jacket: "Кожаная куртка",
  blazer: "Пиджак",
  blazer_short: "Короткий пиджак",
  denim_jacket: "Джинсовая куртка",
  jacket: "Куртка",
};

export function formatCategory(value: string | null | undefined): string {
  if (!value) return "";
  return CATEGORY_LABEL[value.toLowerCase()] ?? humanize(value);
}

// ---- helpers ----------------------------------------------------------

/**
 * Fallback: ``foo_bar`` → ``Foo bar``. Никогда не возвращает пустую
 * строку — так UI не показывает «пробел вместо названия».
 */
function humanize(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  if (!s) return key;
  return s.charAt(0).toUpperCase() + s.slice(1);
}
