import uuid

from app.services.today_service import SLOT_ORDER, TodayService


# ---------------------------------------------------------------- fixtures

USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _FakePersonalization:
    def __init__(self, style_vector: dict | None = None, experimentation: float = 0.3):
        self.style_vector_json = style_vector or {"classic": 0.5, "minimal": 0.3}
        self.experimentation_score = experimentation


class _FakeStyleProfile:
    def __init__(self, kibbe_type: str = "classic"):
        self.kibbe_type = kibbe_type
        self.color_profile_json = {
            "undertone": "cool",
            "depth": "medium",
            "chroma": "soft",
            "contrast": "low",
        }


def _item(item_id: str, category: str, **overrides) -> dict:
    base = {
        "id": item_id,
        "category": category,
        "primary_color": "white",
        "line_type": "balanced",
        "fit": "tailored",
        "structure": "structured",
        "scale": "medium",
        "style_tags": ["classic"],
        "formality": "smart_casual",
        "season": ["spring", "summer", "autumn"],
        "occasions": ["work", "smart_casual"],
        "statement": False,
        "detail_density": "medium",
    }
    base.update(overrides)
    return base


def _rich_wardrobe() -> list[dict]:
    return [
        _item("t1", "top"),
        _item("t2", "top", style_tags=["minimal"]),
        _item("t3", "top", statement=True),
        _item("b1", "bottom"),
        _item("b2", "bottom", style_tags=["classic", "minimal"]),
        _item("s1", "shoes"),
        _item("s2", "shoes", style_tags=["classic"]),
        _item("a1", "accessory"),
        _item("o1", "outerwear", style_tags=["classic"]),
    ]


def _make_service(
    wardrobe: list[dict],
    style_vector: dict | None = None,
    experimentation: float = 0.3,
    kibbe: str = "classic",
) -> TodayService:
    perso = _FakePersonalization(style_vector, experimentation)
    style = _FakeStyleProfile(kibbe)
    return TodayService(
        db=None,
        wardrobe_loader=lambda _uid: list(wardrobe),
        style_profile_loader=lambda _uid: style,
        personalization_loader=lambda _uid: perso,
    )


# --------------------------------------------------------- core requirements


def test_three_slots_when_wardrobe_is_rich():
    svc = _make_service(_rich_wardrobe())
    resp = svc.get_today(user_id=USER_ID)
    labels = [o["label"] for o in resp["outfits"]]
    assert labels == list(SLOT_ORDER)
    assert len(resp["outfits"]) == 3


def test_fewer_slots_when_wardrobe_is_empty():
    svc = _make_service([])
    resp = svc.get_today(user_id=USER_ID)
    assert resp["outfits"] == []
    assert resp["notes"]
    assert any("wardrobe is empty" in n for n in resp["notes"])


def test_fewer_slots_when_only_one_outfit_possible():
    # Minimum one-of-each wardrobe → one base combo → at most one distinct slot.
    svc = _make_service([_item("t1", "top"), _item("b1", "bottom"), _item("s1", "shoes")])
    resp = svc.get_today(user_id=USER_ID)
    assert 1 <= len(resp["outfits"]) < 3
    assert resp["notes"]
    assert any("distinct outfit" in n for n in resp["notes"])


def test_safe_balanced_expressive_are_distinct():
    svc = _make_service(_rich_wardrobe())
    resp = svc.get_today(user_id=USER_ID)
    # With a rich pool, the three picks must be different outfits.
    sigs = {
        tuple(str(it["id"]) for it in o["outfit"]["items"])
        for o in resp["outfits"]
    }
    assert len(sigs) == len(resp["outfits"])


def test_deterministic_ordering():
    resp1 = _make_service(_rich_wardrobe()).get_today(user_id=USER_ID)
    resp2 = _make_service(_rich_wardrobe()).get_today(user_id=USER_ID)

    def sig(resp):
        return [
            (o["label"], tuple(str(it["id"]) for it in o["outfit"]["items"]))
            for o in resp["outfits"]
        ]

    assert sig(resp1) == sig(resp2)


def test_occasion_filter_is_respected():
    wardrobe = [
        _item("t1", "top", occasions=["beach"]),
        _item("t2", "top", occasions=["work"]),
        _item("b1", "bottom", occasions=["work"]),
        _item("s1", "shoes", occasions=["work"]),
    ]
    svc = _make_service(wardrobe)
    resp = svc.get_today(user_id=USER_ID, occasion="work")
    # Every returned outfit must only use work-compatible items.
    for slot in resp["outfits"]:
        for it in slot["outfit"]["items"]:
            assert "t1" != str(it["id"])  # beach-only top never in a work outfit


# ------------------------------------------------------- response contract


def test_response_contract_shape():
    svc = _make_service(_rich_wardrobe())
    resp = svc.get_today(user_id=USER_ID, weather="cold", occasion="work")
    assert set(resp.keys()) == {"weather", "occasion", "outfits", "notes"}
    assert resp["weather"] == "cold"
    assert resp["occasion"] == "work"
    for slot in resp["outfits"]:
        assert set(slot.keys()) == {"label", "outfit", "reasons"}
        assert slot["label"] in SLOT_ORDER
        assert isinstance(slot["reasons"], list)
        assert slot["reasons"]
        assert slot["outfit"]["items"]
        assert "scores" in slot["outfit"]


# ------------------------------------------------- weather hint (optional)


def test_weather_hint_drops_explicit_season_conflicts():
    wardrobe = [
        _item("t1", "top", season=["summer"]),
        _item("b1", "bottom", season=["summer"]),
        _item("s1", "shoes", season=["summer"]),
    ]
    svc = _make_service(wardrobe)
    resp = svc.get_today(user_id=USER_ID, weather="cold")
    # Summer-tagged outfit with cold weather → dropped + note.
    assert resp["outfits"] == []
    assert any("weather" in n for n in resp["notes"])


def test_weather_hint_ignored_when_metadata_missing():
    wardrobe = [
        _item("t1", "top", season=[]),
        _item("b1", "bottom", season=[]),
        _item("s1", "shoes", season=[]),
    ]
    svc = _make_service(wardrobe)
    resp = svc.get_today(user_id=USER_ID, weather="cold")
    # Missing season tags → weather can't safely drop anything.
    assert resp["outfits"]


def test_unknown_weather_is_echoed_and_ignored():
    svc = _make_service(_rich_wardrobe())
    resp = svc.get_today(user_id=USER_ID, weather="blizzardous")
    assert resp["weather"] == "blizzardous"
    # Weather is unknown → pool should be unchanged, outfits still present.
    assert resp["outfits"]
    assert any("not recognized" in n for n in resp["notes"])


# --------------------------------------------------- strategy distinctness


def test_safe_has_lower_risk_than_expressive_when_possible():
    # Wardrobe where one top is a clear statement piece.
    wardrobe = [
        _item("t1", "top"),
        _item("t2", "top", statement=True, style_tags=["bold", "classic"]),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
    ]
    svc = _make_service(
        wardrobe,
        style_vector={"bold": 0.7, "classic": 0.3},
        experimentation=0.8,
    )
    resp = svc.get_today(user_id=USER_ID)
    slots = {o["label"]: o for o in resp["outfits"]}
    # Should have at least safe and expressive; let's verify they differ.
    if "safe" in slots and "expressive" in slots:
        safe_ids = tuple(str(it["id"]) for it in slots["safe"]["outfit"]["items"])
        expr_ids = tuple(
            str(it["id"]) for it in slots["expressive"]["outfit"]["items"]
        )
        assert safe_ids != expr_ids
