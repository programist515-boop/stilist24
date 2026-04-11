from functools import lru_cache
from pathlib import Path
import yaml

RULES_DIR = Path("config/rules")


def _load_yaml(filename: str) -> dict:
    path = RULES_DIR / filename
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_rules() -> dict[str, dict]:
    return {
        "identity_families": _load_yaml("identity_families.yaml"),
        "identity_subtypes": _load_yaml("identity_subtypes.yaml"),
        "season_families": _load_yaml("season_families.yaml"),
        "seasons_12": _load_yaml("seasons_12.yaml"),
        "garment_line_rules": _load_yaml("garment_line_rules.yaml"),
        "outfit_rules": _load_yaml("outfit_rules.yaml"),
    }
