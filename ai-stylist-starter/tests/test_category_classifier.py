"""Tests for the wardrobe category classifier (cloud + heuristic + factory).

The cloud HTTP layer is mocked through dependency injection of an
``httpx.Client`` — no real network calls. The integration with the full
upload route is covered by the schema tests in
``test_wardrobe_category_schema.py`` (project style avoids TestClient).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.categories import (
    WARDROBE_CATEGORIES,
    is_legacy_category,
    legacy_to_detailed,
)
from app.services.category_classifier import (
    CategoryPrediction,
    ClaudeCategoryClassifier,
    HeuristicCategoryClassifier,
    _CircuitBreaker,
    get_category_classifier,
)


# ---------------------------------------------------------------------------
# categories.py — single source of truth
# ---------------------------------------------------------------------------


def test_wardrobe_categories_match_yaml_dir():
    """The 15 detailed categories mirror the category_rules YAML files.

    If the YAML directory grows or shrinks, the constant in categories.py
    must follow — both are imported by schemas, classifier, and frontend.
    """
    expected = {
        "bags",
        "belts",
        "blouses",
        "dresses",
        "eyewear",
        "headwear",
        "hosiery",
        "jackets",
        "jewelry",
        "outerwear",
        "pants",
        "shoes",
        "skirts",
        "sweaters",
        "swimwear",
    }
    assert set(WARDROBE_CATEGORIES) == expected


def test_legacy_to_detailed_known_values():
    assert legacy_to_detailed("top") == "blouses"
    assert legacy_to_detailed("bottom") == "pants"
    assert legacy_to_detailed("dress") == "dresses"
    assert legacy_to_detailed("outerwear") == "outerwear"
    assert legacy_to_detailed("shoes") == "shoes"


def test_legacy_to_detailed_accessory_returns_none():
    """Accessory has no single best detailed bucket — return None so the
    caller can ask the user instead of silently picking 'bags'."""
    assert legacy_to_detailed("accessory") is None


def test_is_legacy_category():
    assert is_legacy_category("top")
    assert is_legacy_category("accessory")
    assert not is_legacy_category("blouses")
    assert not is_legacy_category("pants")


# ---------------------------------------------------------------------------
# ClaudeCategoryClassifier — happy path
# ---------------------------------------------------------------------------


def _claude_response_body(
    category: str,
    confidence: float,
    reasoning: str = "",
    *,
    decoration: str = "",
) -> dict:
    """Build a fake Messages API response with a JSON-in-text block.

    Mirrors what kie.ai actually emits — a ``content`` array with a single
    ``text`` block whose body is the JSON object. ``decoration`` lets a
    test simulate the model wrapping the object in a code fence or stray
    prose, so the parser stays robust.
    """
    payload = {"category": category, "confidence": confidence}
    if reasoning:
        payload["reasoning"] = reasoning
    json_str = json.dumps(payload)
    text = decoration.replace("{}", json_str) if decoration else json_str
    return {
        "role": "assistant",
        "id": "msg_test",
        "type": "message",
        "stop_reason": "end_turn",
        "model": "claude-haiku-4-5-20251001",
        "usage": {"input_tokens": 100, "output_tokens": 30},
        "content": [{"type": "text", "text": text}],
    }


def _mock_httpx_client(response_body: dict, status_code: int = 200) -> MagicMock:
    """Build an ``httpx.Client`` mock returning a single canned response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = response_body
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=response
        )

    client = MagicMock(spec=httpx.Client)
    client.post.return_value = response
    return client


def test_claude_high_confidence_returns_prediction():
    body = _claude_response_body("blouses", 0.95, "white silk blouse")
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"fake-jpeg-bytes", attrs_hint={"primary_color": "white"})

    assert pred.category == "blouses"
    assert pred.confidence == 0.95
    assert pred.source == "cloud_llm"
    assert pred.reasoning == "white silk blouse"


def test_claude_uses_bearer_auth_by_default():
    body = _claude_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = ClaudeCategoryClassifier(api_key="sk-test", client=client)

    classifier.classify(b"x")

    args, kwargs = client.post.call_args
    headers = kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-test"
    assert "x-api-key" not in headers


def test_claude_uses_x_api_key_when_configured():
    """Direct Anthropic API requires x-api-key + anthropic-version. The
    auth_scheme switch must produce the right headers."""
    body = _claude_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = ClaudeCategoryClassifier(
        api_key="sk-ant-real",
        base_url="https://api.anthropic.com",
        auth_scheme="x-api-key",
        client=client,
    )

    classifier.classify(b"x")

    headers = client.post.call_args.kwargs["headers"]
    assert headers["x-api-key"] == "sk-ant-real"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers


def test_claude_posts_to_correct_endpoint():
    body = _claude_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test",
        base_url="https://api.kie.ai/claude",
        client=client,
    )

    classifier.classify(b"x")

    url = client.post.call_args.args[0]
    assert url == "https://api.kie.ai/claude/v1/messages"


def test_claude_sends_image_block():
    body = _claude_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = ClaudeCategoryClassifier(api_key="sk-test", client=client)

    classifier.classify(b"PNGFAKEBYTES", media_type="image/png")

    sent = client.post.call_args.kwargs["json"]
    image_block = sent["messages"][0]["content"][0]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    # body bytes must be base64-encoded — not the raw bytes verbatim.
    assert image_block["source"]["data"] != "PNGFAKEBYTES"


def test_claude_low_confidence_still_returned():
    """Low confidence is the route's decision (threshold), not the
    classifier's. The classifier reports honestly; the route writes
    category=None when below threshold."""
    body = _claude_response_body("blouses", 0.4)
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"fake-bytes")

    assert pred.confidence == 0.4
    assert pred.source == "cloud_llm"


def test_claude_clamps_confidence_to_unit_interval():
    body = _claude_response_body("blouses", 1.5)  # buggy LLM
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"fake-bytes")

    assert pred.confidence == 1.0


def test_claude_unknown_category_falls_back_to_heuristic():
    """If the LLM returns a category outside our enum, treat it as a
    failure and use the heuristic fallback so we never store garbage."""
    body = _claude_response_body("alien_garment", 0.99)
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test",
        client=_mock_httpx_client(body),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"fake-bytes", attrs_hint={"occasion": "work", "structure": "tailored"})

    assert pred.source == "heuristic"
    assert pred.category in WARDROBE_CATEGORIES


def test_claude_unparseable_text_falls_back_to_heuristic():
    """When the model writes prose without a JSON object — fall through
    to heuristic instead of storing the previous prediction."""
    body = {
        "role": "assistant",
        "content": [{"type": "text", "text": "I think this is a blouse."}],
        "stop_reason": "end_turn",
    }
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test",
        client=_mock_httpx_client(body),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"x", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"


def test_claude_handles_json_in_code_fence():
    """kie.ai often wraps the object in ```json ... ``` — must still
    parse correctly."""
    body = {
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": '```json\n{"category":"jackets","confidence":0.92}\n```',
            }
        ],
        "stop_reason": "end_turn",
    }
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"x")

    assert pred.category == "jackets"
    assert pred.confidence == 0.92
    assert pred.source == "cloud_llm"


def test_claude_handles_json_with_surrounding_prose():
    """Model occasionally adds 'Here is the result:' before the JSON.
    We should still extract the embedded object."""
    body = {
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": 'Here is the result: {"category":"shoes","confidence":0.88}',
            }
        ],
        "stop_reason": "end_turn",
    }
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"x")

    assert pred.category == "shoes"


def test_claude_empty_content_falls_back_to_heuristic():
    """kie.ai returns an empty content array when ``tools`` is sent —
    treat that the same as any other malformed response."""
    body = {
        "role": "assistant",
        "content": [],
        "stop_reason": "end_turn",
    }
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test",
        client=_mock_httpx_client(body),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"x", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"


def test_claude_does_not_send_tools_or_tool_choice():
    """kie.ai breaks on ``tools``/``tool_choice``. The classifier must
    request plain JSON-in-text only — locking this in via a test so a
    well-meaning future refactor doesn't reintroduce the broken path."""
    body = _claude_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = ClaudeCategoryClassifier(api_key="sk-test", client=client)

    classifier.classify(b"x")

    sent = client.post.call_args.kwargs["json"]
    assert "tools" not in sent
    assert "tool_choice" not in sent


def test_claude_network_error_falls_back_to_heuristic():
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.TimeoutException("network timeout")
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test",
        client=client,
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"fake-bytes", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"


def test_claude_http_4xx_falls_back_to_heuristic():
    body = {"error": {"type": "authentication_error", "message": "Invalid key"}}
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test",
        client=_mock_httpx_client(body, status_code=401),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"x", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_trips_after_three_consecutive_failures():
    breaker = _CircuitBreaker(fail_threshold=3, cooldown_s=60.0)
    assert not breaker.is_open()

    breaker.record_failure()
    assert not breaker.is_open()
    breaker.record_failure()
    assert not breaker.is_open()
    breaker.record_failure()
    assert breaker.is_open()


def test_circuit_breaker_resets_on_success():
    breaker = _CircuitBreaker(fail_threshold=3, cooldown_s=60.0)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()

    assert not breaker.is_open()


def test_claude_skips_api_when_breaker_open():
    """Once the breaker trips, the classifier should skip the API
    entirely until cooldown — saves wall-clock time when the upstream
    is genuinely down."""
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.TimeoutException("flaky network")
    breaker = _CircuitBreaker(fail_threshold=3, cooldown_s=60.0)
    classifier = ClaudeCategoryClassifier(
        api_key="sk-test",
        client=client,
        breaker=breaker,
        fallback=HeuristicCategoryClassifier(),
    )

    # Trip the breaker via three real calls.
    for _ in range(3):
        classifier.classify(b"x", attrs_hint={"occasion": "work"})

    # Reset the call counter — the next classify should not hit the API.
    client.post.reset_mock()

    pred = classifier.classify(b"y", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"
    client.post.assert_not_called()


# ---------------------------------------------------------------------------
# Heuristic classifier
# ---------------------------------------------------------------------------


def test_heuristic_returns_zero_confidence_when_no_hints():
    """Without any attribute hints we honestly admit defeat — confidence
    0 makes the route store category=None and ask the user."""
    classifier = HeuristicCategoryClassifier()

    pred = classifier.classify(b"x", attrs_hint=None)

    assert pred.confidence == 0.0
    assert pred.source == "heuristic"


def test_heuristic_picks_jackets_for_tailored_work():
    classifier = HeuristicCategoryClassifier()

    pred = classifier.classify(
        b"x", attrs_hint={"occasion": "work", "structure": "tailored"}
    )

    assert pred.category == "jackets"
    assert pred.confidence > 0.0


def test_heuristic_returns_known_category():
    """Whatever the rule path, the result must be in WARDROBE_CATEGORIES
    so the route can store it directly."""
    classifier = HeuristicCategoryClassifier()

    pred = classifier.classify(b"x", attrs_hint={"occasion": "casual"})

    assert pred.category in WARDROBE_CATEGORIES


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _settings(**overrides):
    """Minimal settings stub for the factory.

    The factory only reads the relevant fields, so we don't need a real
    Settings instance — a SimpleNamespace works and avoids loading .env.
    """
    base = {
        "use_cv_category_classifier": False,
        "claude_api_key": "",
        "claude_base_url": "https://api.kie.ai/claude",
        "claude_model": "claude-haiku-4-5",
        "claude_auth_scheme": "bearer",
        "category_classifier_provider": "heuristic",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_factory_returns_heuristic_when_flag_off():
    classifier = get_category_classifier(_settings(use_cv_category_classifier=False))
    assert isinstance(classifier, HeuristicCategoryClassifier)


def test_factory_returns_heuristic_when_provider_is_heuristic():
    classifier = get_category_classifier(
        _settings(
            use_cv_category_classifier=True,
            category_classifier_provider="heuristic",
            claude_api_key="sk-anything",
        )
    )
    assert isinstance(classifier, HeuristicCategoryClassifier)


def test_factory_returns_heuristic_when_claude_key_missing():
    classifier = get_category_classifier(
        _settings(
            use_cv_category_classifier=True,
            category_classifier_provider="claude",
            claude_api_key="",
        )
    )
    assert isinstance(classifier, HeuristicCategoryClassifier)


def test_factory_returns_claude_when_fully_configured():
    classifier = get_category_classifier(
        _settings(
            use_cv_category_classifier=True,
            category_classifier_provider="claude",
            claude_api_key="sk-test",
        )
    )
    assert isinstance(classifier, ClaudeCategoryClassifier)


def test_factory_accepts_legacy_anthropic_provider_name():
    """During the migration we used "anthropic" as the provider value;
    accept it as an alias for "claude" so old .env files don't break."""
    classifier = get_category_classifier(
        _settings(
            use_cv_category_classifier=True,
            category_classifier_provider="anthropic",
            claude_api_key="sk-test",
        )
    )
    assert isinstance(classifier, ClaudeCategoryClassifier)


# ---------------------------------------------------------------------------
# CategoryPrediction dataclass
# ---------------------------------------------------------------------------


def test_category_prediction_is_immutable():
    pred = CategoryPrediction(category="blouses", confidence=0.9, source="cloud_llm")
    with pytest.raises((AttributeError, Exception)):
        pred.category = "pants"  # type: ignore[misc]
