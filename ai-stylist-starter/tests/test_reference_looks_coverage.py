"""
Test: каждый подтип из identity_subtype_profiles.yaml имеет соответствующий
файл reference_looks/<subtype>.yaml с валидной структурой.

Используется фичей "preference-based квиз по лайкам": мы для каждой первой
карточки берём primary_look_id, поэтому структура должна быть одинакова
для всех подтипов.
"""
from pathlib import Path

import yaml


RULES_DIR = Path(__file__).resolve().parent.parent / "config" / "rules"
PROFILES_PATH = RULES_DIR / "identity_subtype_profiles.yaml"
REFERENCE_LOOKS_DIR = RULES_DIR / "reference_looks"


def _load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_every_subtype_has_reference_looks_file():
    profiles = _load_yaml(PROFILES_PATH)
    assert "identity_subtype_profiles" in profiles, (
        "identity_subtype_profiles.yaml должен иметь корневой ключ "
        "'identity_subtype_profiles'"
    )

    subtype_keys = list(profiles["identity_subtype_profiles"].keys())
    assert len(subtype_keys) >= 13, (
        f"Ожидали как минимум 13 подтипов Kibbe, получили {len(subtype_keys)}"
    )

    missing_files = []
    errors = []

    for subtype in subtype_keys:
        look_file = REFERENCE_LOOKS_DIR / f"{subtype}.yaml"
        if not look_file.exists():
            missing_files.append(str(look_file))
            continue

        try:
            data = _load_yaml(look_file)
        except yaml.YAMLError as exc:
            errors.append(f"{subtype}: YAML parse error: {exc}")
            continue

        if not isinstance(data, dict):
            errors.append(f"{subtype}: файл должен быть словарём")
            continue

        if data.get("subtype") != subtype:
            errors.append(
                f"{subtype}: поле 'subtype' в YAML = "
                f"{data.get('subtype')!r}, ожидали {subtype!r}"
            )

        looks = data.get("reference_looks")
        if not isinstance(looks, list) or len(looks) < 3:
            errors.append(
                f"{subtype}: ожидали reference_looks как список длиной >= 3, "
                f"получили {type(looks).__name__} длиной "
                f"{len(looks) if isinstance(looks, list) else 'N/A'}"
            )
            continue

        look_ids = set()
        for idx, look in enumerate(looks):
            if not isinstance(look, dict):
                errors.append(f"{subtype}: лук #{idx} не является словарём")
                continue
            for required_key in ("id", "name", "image_url", "items"):
                if required_key not in look:
                    errors.append(
                        f"{subtype}: лук #{idx} не содержит поля "
                        f"{required_key!r}"
                    )
            look_id = look.get("id")
            if look_id:
                look_ids.add(look_id)

        primary_id = data.get("primary_look_id")
        if not primary_id:
            errors.append(f"{subtype}: отсутствует поле 'primary_look_id'")
        elif primary_id not in look_ids:
            errors.append(
                f"{subtype}: primary_look_id={primary_id!r} не найден среди "
                f"id луков {sorted(look_ids)}"
            )

    assert not missing_files, (
        "Отсутствуют файлы reference_looks:\n  - "
        + "\n  - ".join(missing_files)
    )
    assert not errors, (
        "Ошибки валидации reference_looks:\n  - " + "\n  - ".join(errors)
    )
