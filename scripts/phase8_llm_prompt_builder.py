"""
phase8_llm_prompt_builder.py — сборка LLM-промпта для наполнения подтипа
Kibbe в identity_subtype_profiles.yaml (Фаза 8 плана identity DNA).

Usage:
    python scripts/phase8_llm_prompt_builder.py <subtype>

Печатает готовый промпт на stdout. Копируете в Claude/GPT, получаете YAML-блок,
вставляете в ai-stylist-starter/config/rules/identity_subtype_profiles.yaml
вместо placeholder'а.

celebrity_examples LLM НЕ генерирует — собирается отдельно из community-источников
(r/Kibbe, VK-сообщества). См. plans/2026-04-21-каталог-фич-из-отчёта-типажа.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "ai-stylist-starter" / "config" / "rules"
PROFILES_PATH = RULES_DIR / "identity_subtype_profiles.yaml"
FAMILIES_PATH = RULES_DIR / "identity_families.yaml"
SUBTYPES_PATH = RULES_DIR / "identity_subtypes.yaml"

REFERENCE_SUBTYPE = "flamboyant_gamine"


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _dump_yaml(data: object) -> str:
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=80,
    ).rstrip()


def _find_subtype_rule(subtypes_cfg: dict, subtype: str) -> dict | None:
    for family_cfg in (subtypes_cfg.get("identity_subtypes") or {}).values():
        for rule in family_cfg.get("rules", []):
            if rule.get("name") == subtype:
                return rule
    return None


def build_prompt(subtype: str) -> str:
    profiles = _load(PROFILES_PATH).get("identity_subtype_profiles", {})
    families = _load(FAMILIES_PATH).get("identity_families", {})
    subtypes_cfg = _load(SUBTYPES_PATH)

    if subtype not in profiles:
        available = ", ".join(sorted(profiles.keys()))
        raise SystemExit(
            f"Неизвестный subtype: {subtype!r}.\nДоступные: {available}"
        )
    if subtype == REFERENCE_SUBTYPE:
        raise SystemExit(
            f"{REFERENCE_SUBTYPE} — это эталон, уже заполнен. "
            f"Выберите placeholder-подтип."
        )

    target = profiles[subtype]
    family_key = target.get("family") or ""
    family_cfg = families.get(family_key, {})
    rule = _find_subtype_rule(subtypes_cfg, subtype) or {}

    reference_yaml = _dump_yaml({REFERENCE_SUBTYPE: profiles[REFERENCE_SUBTYPE]})
    family_yaml = _dump_yaml({family_key: family_cfg}) if family_cfg else "(нет данных)"
    formula_yaml = _dump_yaml({"rule": rule}) if rule else "(правило не найдено)"

    return PROMPT_TEMPLATE.format(
        subtype=subtype,
        display_name_ru=target.get("display_name_ru", ""),
        display_name_en=target.get("display_name_en", ""),
        family=family_key,
        family_yaml=family_yaml,
        formula_yaml=formula_yaml,
        reference_yaml=reference_yaml,
    )


PROMPT_TEMPLATE = """\
Ты — стилист-эксперт по системе Дэвида Кибби (классическая версия 1987 г., 13 подтипов).
Помоги наполнить YAML-профиль подтипа для AI-стилиста «stilist24». Аудитория —
девушки 22–35 лет, РФ, офис / IT. Тон позитивный, коуч, не «жалостливый».

# Методология
Классическая система Кибби: 5 семейств × 13 подтипов. Каждый подтип определяется
комбинацией осей: vertical_line, bone_sharpness, softness, curve_presence,
compactness, width, facial_sharpness, symmetry, waist_definition, moderation.

# Семейство подтипа — {family}
{family_yaml}

# Формула целевого подтипа — {subtype} ({display_name_ru} / {display_name_en})
{formula_yaml}

# ЭТАЛОН (flamboyant_gamine) — стиль, тон, длина, структура
{reference_yaml}

# ЗАДАНИЕ
Сгенерируй YAML-блок для подтипа «{subtype}» в ТОМ ЖЕ формате, что эталон.

Требования к полям:
- display_name_ru, display_name_en, family — уже заданы, оставь как есть.
- associations: 7–8 одиночных слов (существительные/прилагательные) — черты
  характера, эмоции, типажная «суть». НЕ фразы, НЕ клише.
- motto: одна фраза-девиз, до ~80 символов. Императив, конкретно про этот подтип.
  НЕ «будь собой», НЕ «люби себя», НЕ обобщения.
- philosophy: параграф 150–200 слов. Тон как у эталона — коуч, не жалость.
  ЗАПРЕЩЕНО «проще», «земнее», «тихо», «скромнее» с оттенком снисхождения.
  Работаем только с ПОЗИТИВНОЙ силой подтипа — что он даёт, а не чем обделён.
- key_principles: 5–6 императивных коротких правил. КАЖДОЕ правило ОБЯЗАНО
  называть конкретный артефакт одежды или визуальную характеристику: рукав,
  вырез, длина, ткань, силуэт, контраст, принт, детали. ЗАПРЕЩЕНО абстракции
  вроде «sharp meets soft» без конкретного предмета.
- celebrity_examples: оставь пустым списком ([]). Собираю отдельно из
  community-источников (r/Kibbe wiki, VK «Типажи Кибби», Aly Art).

Формат вывода: СТРОГО YAML-блок под ключ «{subtype}:», без пояснений до или после.
Отступы — 2 пробела, как в эталоне. Для длинной philosophy используй `>`-скаляр.
"""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Собирает LLM-промпт для подтипа Kibbe (Фаза 8 плана identity DNA).",
    )
    parser.add_argument(
        "subtype",
        help="Код подтипа, например: gamine, soft_classic, theatrical_romantic",
    )
    args = parser.parse_args()
    print(build_prompt(args.subtype))
    return 0


if __name__ == "__main__":
    sys.exit(main())
