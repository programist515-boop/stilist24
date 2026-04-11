from app.services.rules_loader import load_rules


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class IdentityEngine:
    def __init__(self) -> None:
        self.rules = load_rules()

    def _score_family(self, features: dict[str, float], formula: dict[str, float]) -> float:
        score = 0.0
        for key, weight in formula.items():
            if key == "low_softness":
                value = 1 - features.get("softness", 0.0)
            elif key == "low_vertical_line":
                value = 1 - features.get("vertical_line", 0.0)
            elif key == "low_symmetry":
                value = 1 - features.get("symmetry", 0.0)
            elif key == "low_bone_sharpness":
                value = 1 - features.get("bone_sharpness", 0.0)
            else:
                value = features.get(key, 0.0)
            score += value * weight
        return clamp01(score)

    def get_family_scores(self, features: dict[str, float]) -> dict[str, float]:
        families = self.rules["identity_families"]["identity_families"]
        return {name: self._score_family(features, cfg["score_formula"]) for name, cfg in families.items()}

    def resolve_subtype(self, family: str, features: dict[str, float]) -> tuple[str, float]:
        subtype_cfg = self.rules["identity_subtypes"]["identity_subtypes"].get(family)
        if not subtype_cfg:
            return family, 0.0
        best_name = family
        best_score = 0.0
        derived = {
            "sharpness_minus_softness": features.get("bone_sharpness", 0.0) - features.get("softness", 0.0),
            "softness_minus_sharpness": features.get("softness", 0.0) - features.get("bone_sharpness", 0.0),
        }
        full = {**features, **derived}
        for rule in subtype_cfg["rules"]:
            ok = True
            for key, constraints in rule["when"].items():
                val = full.get(key, 0.0)
                if "min" in constraints and val < constraints["min"]:
                    ok = False
                    break
                if "max" in constraints and val > constraints["max"]:
                    ok = False
                    break
            if ok and rule["score_boost"] > best_score:
                best_name = rule["name"]
                best_score = rule["score_boost"]
        return best_name, best_score

    def analyze(self, features: dict[str, float]) -> dict:
        family_scores = self.get_family_scores(features)
        sorted_families = sorted(family_scores.items(), key=lambda kv: kv[1], reverse=True)
        top_family, top_score = sorted_families[0]
        second_score = sorted_families[1][1] if len(sorted_families) > 1 else 0.0
        subtype, subtype_boost = self.resolve_subtype(top_family, features)
        confidence = clamp01(top_score - second_score + subtype_boost)
        alternatives = [{"family": fam, "score": round(score, 3)} for fam, score in sorted_families[1:3]]
        return {"family_scores": family_scores, "main_type": subtype, "confidence": round(confidence, 3), "alternatives": alternatives}
