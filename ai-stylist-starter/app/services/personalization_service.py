class PersonalizationService:
    STEP_UP = 0.04
    STEP_DOWN = 0.03
    AVOID_UP = 0.05

    def _bump(self, vector: dict[str, float], key: str, delta: float) -> None:
        vector[key] = max(0.0, min(1.0, vector.get(key, 0.0) + delta))

    def update_profile(self, profile: dict, event_type: str, payload: dict) -> dict:
        style_vector = profile.setdefault("style_vector_json", {})
        line_vector = profile.setdefault("line_vector_json", {})
        color_vector = profile.setdefault("color_vector_json", {})
        avoidance_vector = profile.setdefault("avoidance_vector_json", {})

        style_tags = payload.get("style_tags", [])
        line_tags = payload.get("line_tags", [])
        color_tags = payload.get("color_tags", [])
        negative_tags = payload.get("negative_tags", [])

        if event_type in {"outfit_liked", "item_liked", "outfit_saved", "outfit_worn"}:
            for tag in style_tags:
                self._bump(style_vector, tag, self.STEP_UP)
            for tag in line_tags:
                self._bump(line_vector, tag, self.STEP_UP)
            for tag in color_tags:
                self._bump(color_vector, tag, self.STEP_UP)

        if event_type in {"outfit_disliked", "item_disliked", "item_ignored"}:
            for tag in negative_tags:
                self._bump(avoidance_vector, tag, self.AVOID_UP)
            for tag in style_tags:
                self._bump(style_vector, tag, -self.STEP_DOWN)
            for tag in line_tags:
                self._bump(line_vector, tag, -self.STEP_DOWN)
            for tag in color_tags:
                self._bump(color_vector, tag, -self.STEP_DOWN)

        if event_type == "tryon_opened":
            profile["experimentation_score"] = min(1.0, profile.get("experimentation_score", 0.3) + 0.01)
        return profile

    def record_color_preference(
        self,
        profile: dict,
        hex_code: str,
        liked: bool,
    ) -> dict:
        """Записать лайк/дизлайк на цвет в ``color_vector_json``.

        Используется обратной связью из color-tryon: пользователь
        отмечает понравившиеся варианты палитры, мы постепенно
        «смещаем» персональный color_vector к его вкусу. Ключ хранится
        в нижнем регистре без префикса ``#``, чтобы не плодить дубли
        (``#E8735A`` и ``e8735a`` попадают в одну ячейку).
        """
        color_vector = profile.setdefault("color_vector_json", {})
        key = (hex_code or "").strip().lstrip("#").lower()
        if not key:
            return profile
        if liked:
            self._bump(color_vector, key, self.STEP_UP)
        else:
            self._bump(color_vector, key, -self.STEP_DOWN)
        return profile
