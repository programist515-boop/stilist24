from app.services.rules_loader import load_rules

# Human-readable labels for each axis value used in explanation strings
_AXIS_LABELS: dict[str, dict[str, str]] = {
    "undertone": {
        "warm": "warm undertone",
        "cool": "cool undertone",
        "neutral-warm": "neutral-warm undertone",
        "cool-neutral": "cool-neutral undertone",
        "neutral": "neutral undertone",
        "warm-neutral": "warm-neutral undertone",
        "neutral-cool": "neutral-cool undertone",
    },
    "depth": {
        "light": "light depth",
        "medium-light": "medium-light depth",
        "medium": "medium depth",
        "medium-deep": "medium-deep depth",
        "deep": "deep depth",
    },
    "chroma": {
        "soft": "soft/muted chroma",
        "medium-soft": "medium-soft chroma",
        "medium-bright": "medium-bright chroma",
        "bright": "bright chroma",
        "clear": "clear/vivid chroma",
    },
    "contrast": {
        "low": "low contrast",
        "medium-low": "medium-low contrast",
        "medium": "medium contrast",
        "medium-high": "medium-high contrast",
        "high": "high contrast",
    },
}

_AXIS_WEIGHTS = {"undertone": 0.35, "depth": 0.25, "chroma": 0.25, "contrast": 0.15}


class ColorEngine:
    def __init__(self) -> None:
        self.rules = load_rules()

    def _match_value(self, observed: str, allowed: list[str]) -> float:
        return 1.0 if observed in allowed else 0.0

    def _explain_season(self, profile: dict[str, str], cond: dict[str, list[str]]) -> str:
        matched, unmatched = [], []
        for axis in ("undertone", "depth", "chroma", "contrast"):
            val = profile.get(axis, "")
            label = _AXIS_LABELS.get(axis, {}).get(val, val)
            if val in cond.get(axis, []):
                matched.append(label)
            else:
                unmatched.append(label)
        parts = [f"✓ {m}" for m in matched]
        if unmatched:
            parts += [f"✗ {u}" for u in unmatched]
        return " · ".join(parts) if parts else "no axes matched"

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
            explanation = self._explain_season(profile, cond)
            results.append({"season": season, "score": round(score, 3), "explanation": explanation})
        return sorted(results, key=lambda x: x["score"], reverse=True)

    def get_palette(self, season_name: str) -> dict[str, list[str]]:
        cfg = self.rules.get("seasons_palette", {}).get("seasons_palette", {})
        season_data = cfg.get(season_name, {})
        return {
            "best_neutrals": list(season_data.get("best_neutrals", [])),
            "accent_colors": list(season_data.get("accent_colors", [])),
            "avoid_colors": list(season_data.get("avoid_colors", [])),
            "canonical_colors": list(season_data.get("canonical_colors", [])),
            "metals": list(season_data.get("metals", [])),
        }

    def analyze(self, profile: dict[str, str]) -> dict:
        family = self.family_scores(profile)
        seasons12 = self.season12_scores(profile)
        best = seasons12[0]
        top3 = seasons12[:3]
        # Gap-based confidence: how decisively top-1 beats top-2
        top2_score = seasons12[1]["score"] if len(seasons12) > 1 else 0.0
        confidence = round(best["score"] - top2_score, 3)
        # Adjacent seasons: positions 4-6 with any score > 0
        adjacent = [s["season"] for s in seasons12[3:6] if s["score"] > 0.0]
        palette = self.get_palette(best["season"])
        palette_hex = palette["best_neutrals"] + palette["accent_colors"]
        palette_summary = {
            "base_colors": {
                "label": "Your base colors",
                "colors": palette["best_neutrals"],
            },
            "accent_colors": {
                "label": "Accent colors",
                "colors": palette["accent_colors"],
            },
            "avoid_colors": {
                "label": "Better to avoid",
                "colors": palette.get("avoid_colors", []),
            },
            "canonical_colors": {
                "label": "Signature colors",
                "colors": palette.get("canonical_colors", []),
            },
        }
        return {
            "family_scores": family,
            "season_top_1": best["season"],
            "confidence": confidence,
            "top_3_seasons": top3,
            "adjacent_seasons": adjacent,
            "axes": profile,
            "palette": palette,
            "palette_hex": palette_hex,
            "palette_summary": palette_summary,
            # kept for backward compat
            "alternatives": seasons12[1:3],
        }
