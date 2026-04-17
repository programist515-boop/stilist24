"""Weather-aware seasonality scorer.

Maps a plain-text weather hint to expected seasonality tags and scores
how many outfit pieces are suitable for those conditions.
"""

from __future__ import annotations

from app.services.outfits.scoring.base import BaseScorer, ScorerResult

# Coarse weather → seasonality tag mapping
_WEATHER_TO_SEASON: dict[str, frozenset[str]] = {
    "hot": frozenset({"summer", "spring_summer", "all_season"}),
    "warm": frozenset({"spring", "summer", "spring_summer", "all_season"}),
    "mild": frozenset({"spring", "autumn", "spring_summer", "autumn_winter", "all_season"}),
    "cool": frozenset({"autumn", "spring", "autumn_winter", "all_season"}),
    "cold": frozenset({"winter", "autumn", "autumn_winter", "all_season"}),
    "freezing": frozenset({"winter", "autumn_winter", "all_season"}),
}

# Heavy outer layers penalised in warm/hot weather
_HEAVY_OUTER_CATEGORIES = frozenset({"outerwear"})
_WARM_CONDITIONS = frozenset({"hot", "warm"})


class WeatherScorer(BaseScorer):
    """Penalises weather-inappropriate pieces.

    Reads ``context['weather']`` (str, one of the keys in ``_WEATHER_TO_SEASON``).
    Missing weather → neutral score.
    """

    weight: float = 0.10

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        weather = (context.get("weather") or "").strip().lower()
        if not weather or weather not in _WEATHER_TO_SEASON:
            return ScorerResult(
                score=0.5,
                weight=self.weight,
                reasons=[f"weather: no weather context or unknown '{weather}' — neutral"],
            )

        allowed_seasons = _WEATHER_TO_SEASON[weather]
        reasons: list[str] = []
        warnings: list[str] = []
        item_scores: list[float] = []

        for item in outfit_items:
            attrs = self._item_attrs(item)
            seasonality = self._extract_val(attrs, "seasonality")
            cat = (item.get("category") or "").lower()

            # Heavy outerwear in hot/warm conditions
            if cat in _HEAVY_OUTER_CATEGORIES and weather in _WARM_CONDITIONS:
                item_scores.append(0.0)
                warnings.append(f"weather: outerwear in {weather} weather — not suitable")
                continue

            if not seasonality:
                item_scores.append(0.7)
                reasons.append(f"weather: item has no seasonality — assume compatible")
                continue

            s = seasonality.strip().lower()
            if s == "all_season" or s in allowed_seasons:
                item_scores.append(1.0)
                reasons.append(f"weather: {s} fits {weather} conditions")
            else:
                item_scores.append(0.1)
                warnings.append(f"weather: {s} item in {weather} conditions")

        if not item_scores:
            return ScorerResult(
                score=0.5,
                weight=self.weight,
                reasons=["weather: no items to evaluate"],
            )

        avg = sum(item_scores) / len(item_scores)
        return ScorerResult(
            score=round(avg, 3),
            weight=self.weight,
            reasons=reasons,
            warnings=warnings,
        )
