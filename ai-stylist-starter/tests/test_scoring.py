from app.services.personalization_service import PersonalizationService


def test_personalization_updates_profile():
    service = PersonalizationService()
    profile = {}
    out = service.update_profile(
        profile,
        "outfit_liked",
        {"style_tags": ["classic"], "line_tags": ["soft"], "color_tags": ["muted"]},
    )
    assert out["style_vector_json"]["classic"] > 0
