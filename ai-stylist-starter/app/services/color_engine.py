from app.services.rules_loader import load_rules


class ColorEngine:
    def __init__(self) -> None:
        self.rules = load_rules()

    def _match_value(self, observed: str, allowed: list[str]) -> float:
        return 1.0 if observed in allowed else 0.0

    def family_scores(self, profile: dict[str, str]) -> dict[str, float]:
        cfg = self.rules["season_families"]["season_families"]
        scores: dict[str, float] = {}
        for season, season_cfg in cfg.items():
            weights = season_cfg["weights"]
            conditions = season_cfg["conditions"]
            total = 0.0
            total += weights.get("undertone_match", 0.0) * self._match_value(profile.get("undertone", ""), conditions.get("undertone", []))
            total += weights.get("chroma_match", 0.0) * self._match_value(profile.get("chroma", ""), conditions.get("chroma", []))
            total += weights.get("depth_match", 0.0) * self._match_value(profile.get("depth", ""), conditions.get("depth", []))
            total += weights.get("contrast_match", 0.0) * self._match_value(profile.get("contrast", ""), conditions.get("contrast", []))
            scores[season] = round(total, 3)
        return scores

    def season12_scores(self, profile: dict[str, str]) -> list[dict]:
        cfg = self.rules["seasons_12"]["seasons_12"]
        results = []
        for season, cond in cfg.items():
            score = 0.0
            score += 0.35 if profile.get("undertone") in cond.get("undertone", []) else 0.0
            score += 0.25 if profile.get("depth") in cond.get("depth", []) else 0.0
            score += 0.25 if profile.get("chroma") in cond.get("chroma", []) else 0.0
            score += 0.15 if profile.get("contrast") in cond.get("contrast", []) else 0.0
            results.append({"season": season, "score": round(score, 3)})
        return sorted(results, key=lambda x: x["score"], reverse=True)

    def analyze(self, profile: dict[str, str]) -> dict:
        family = self.family_scores(profile)
        seasons12 = self.season12_scores(profile)
        best = seasons12[0]
        alternatives = seasons12[1:3]
        return {"family_scores": family, "season_top_1": best["season"], "confidence": best["score"], "alternatives": alternatives, "axes": profile}
