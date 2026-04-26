import { Select } from "./Select";

/**
 * Список стилей синхронизирован с ``ai-stylist-starter/config/rules/styles.yaml``.
 * Ключи — те же, что попадают в ``style_tag[]`` вещей и ``selected_style`` в
 * ``user_context``. Backend (``style_affinity`` scorer) фильтрует style_tags
 * вещей под выбранное значение; пустая строка = «любой стиль».
 */
export const STYLE_OPTIONS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "smart_casual", label: "Смарт-кэжуал" },
  { key: "casual", label: "Кэжуал" },
  { key: "military", label: "Милитари" },
  { key: "dandy", label: "Денди" },
  { key: "preppy", label: "Преппи" },
  { key: "romantic_adapted", label: "Романтический" },
  { key: "dramatic", label: "Драматический" },
  { key: "twenties", label: "Двадцатые" },
];

export interface StyleSelectorProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  /** Текст «любой стиль» — пустое значение. */
  anyLabel?: string;
}

export function StyleSelector({
  id,
  value,
  onChange,
  anyLabel = "Любой стиль",
}: StyleSelectorProps) {
  return (
    <Select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{anyLabel}</option>
      {STYLE_OPTIONS.map(({ key, label }) => (
        <option key={key} value={key}>
          {label}
        </option>
      ))}
    </Select>
  );
}
