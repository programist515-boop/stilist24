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
    HeuristicCategoryClassifier,
    OpenAICategoryClassifier,
    OpenAIVisionAnalyzer,
    VisionAnalysisResult,
    _CircuitBreaker,
    get_category_classifier,
    get_vision_analyzer,
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
# OpenAICategoryClassifier — happy path
# ---------------------------------------------------------------------------


def _openai_response_body(
    category: str,
    confidence: float,
    reasoning: str = "",
    *,
    decoration: str = "",
) -> dict:
    """Build a fake Chat Completions API response.

    Mirrors the OpenAI shape — a ``choices`` array whose first entry has
    a ``message.content`` string carrying the JSON object. ``decoration``
    lets a test simulate the model wrapping the object in a code fence
    or stray prose, so the safety-net parser stays robust.
    """
    payload = {"category": category, "confidence": confidence}
    if reasoning:
        payload["reasoning"] = reasoning
    json_str = json.dumps(payload)
    text = decoration.replace("{}", json_str) if decoration else json_str
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-5-nano",
        "usage": {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230},
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
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


def test_openai_high_confidence_returns_prediction():
    body = _openai_response_body("blouses", 0.95, "white silk blouse")
    classifier = OpenAICategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"fake-jpeg-bytes", attrs_hint={"primary_color": "white"})

    assert pred.category == "blouses"
    assert pred.confidence == 0.95
    assert pred.source == "cloud_llm"
    assert pred.reasoning == "white silk blouse"


def test_openai_uses_bearer_auth():
    body = _openai_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = OpenAICategoryClassifier(api_key="sk-test", client=client)

    classifier.classify(b"x")

    headers = client.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-test"
    assert "x-api-key" not in headers


def test_openai_posts_to_chat_completions_endpoint():
    body = _openai_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = OpenAICategoryClassifier(
        api_key="sk-test",
        base_url="https://api.openai.com",
        client=client,
    )

    classifier.classify(b"x")

    url = client.post.call_args.args[0]
    assert url == "https://api.openai.com/v1/chat/completions"


def test_openai_sends_image_url_block_with_data_url():
    body = _openai_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = OpenAICategoryClassifier(api_key="sk-test", client=client)

    # PNG bytes get re-encoded to JPEG by _shrink_for_upload (PIL writes
    # a real JPEG header even from a 1px synthetic input). What we check
    # is the wire shape, not the exact bytes.
    classifier.classify(b"fake-png-bytes", media_type="image/png")

    sent = client.post.call_args.kwargs["json"]
    user_content = sent["messages"][1]["content"]
    image_block = next(b for b in user_content if b["type"] == "image_url")
    assert "image_url" in image_block
    url = image_block["image_url"]["url"]
    assert url.startswith("data:image/")
    assert ";base64," in url


def test_openai_uses_image_url_with_detail_low():
    """``detail:"low"`` is critical: it pins a fixed 85 input tokens
    per image regardless of resolution. If anyone removes this, vision
    cost suddenly scales with image size — guard via this test."""
    body = _openai_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = OpenAICategoryClassifier(api_key="sk-test", client=client)

    classifier.classify(b"x")

    sent = client.post.call_args.kwargs["json"]
    image_block = next(
        b for b in sent["messages"][1]["content"] if b["type"] == "image_url"
    )
    assert image_block["image_url"]["detail"] == "low"


def test_openai_uses_response_format_json_object():
    """``response_format: {type: json_object}`` is what makes the
    classifier reliable: the API validates the output is JSON before
    returning. Removing it puts us back in JSON-in-text fragility land."""
    body = _openai_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = OpenAICategoryClassifier(api_key="sk-test", client=client)

    classifier.classify(b"x")

    sent = client.post.call_args.kwargs["json"]
    assert sent["response_format"] == {"type": "json_object"}


def test_openai_uses_max_completion_tokens_not_max_tokens():
    """GPT-5 family rejects the legacy ``max_tokens`` field with a 400.
    The body must use ``max_completion_tokens``."""
    body = _openai_response_body("blouses", 0.9)
    client = _mock_httpx_client(body)
    classifier = OpenAICategoryClassifier(api_key="sk-test", client=client)

    classifier.classify(b"x")

    sent = client.post.call_args.kwargs["json"]
    assert "max_completion_tokens" in sent
    assert "max_tokens" not in sent


def test_openai_low_confidence_still_returned():
    """Low confidence is the route's decision (threshold), not the
    classifier's. The classifier reports honestly; the route writes
    category=None when below threshold."""
    body = _openai_response_body("blouses", 0.4)
    classifier = OpenAICategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"fake-bytes")

    assert pred.confidence == 0.4
    assert pred.source == "cloud_llm"


def test_openai_clamps_confidence_to_unit_interval():
    body = _openai_response_body("blouses", 1.5)  # buggy LLM
    classifier = OpenAICategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"fake-bytes")

    assert pred.confidence == 1.0


def test_openai_unknown_category_falls_back_to_heuristic():
    """If the LLM returns a category outside our enum, treat it as a
    failure and use the heuristic fallback so we never store garbage."""
    body = _openai_response_body("alien_garment", 0.99)
    classifier = OpenAICategoryClassifier(
        api_key="sk-test",
        client=_mock_httpx_client(body),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(
        b"fake-bytes", attrs_hint={"occasion": "work", "structure": "tailored"}
    )

    assert pred.source == "heuristic"
    assert pred.category in WARDROBE_CATEGORIES


def test_openai_unparseable_text_falls_back_to_heuristic():
    """When the model writes prose without a JSON object — fall through
    to heuristic instead of storing the previous prediction."""
    body = {
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "I think this is a blouse."},
            }
        ]
    }
    classifier = OpenAICategoryClassifier(
        api_key="sk-test",
        client=_mock_httpx_client(body),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"x", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"


def test_openai_handles_json_in_code_fence():
    """Even with response_format, a misbehaving model could wrap output
    in ```json ... ```. Safety-net parser must still extract it."""
    body = {
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"category":"jackets","confidence":0.92}\n```',
                },
            }
        ]
    }
    classifier = OpenAICategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"x")

    assert pred.category == "jackets"
    assert pred.confidence == 0.92
    assert pred.source == "cloud_llm"


def test_openai_handles_json_with_surrounding_prose():
    """Model occasionally adds 'Here is the result:' before the JSON.
    We should still extract the embedded object."""
    body = {
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": 'Here is the result: {"category":"shoes","confidence":0.88}',
                },
            }
        ]
    }
    classifier = OpenAICategoryClassifier(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    pred = classifier.classify(b"x")

    assert pred.category == "shoes"


def test_openai_empty_choices_falls_back_to_heuristic():
    """If the API returns 200 with an empty choices array (rare but
    possible on safety filter trips), fall through to heuristic."""
    body: dict = {"choices": []}
    classifier = OpenAICategoryClassifier(
        api_key="sk-test",
        client=_mock_httpx_client(body),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"x", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"


def test_openai_401_unauthorized_falls_back_to_heuristic():
    """Bad/expired key — OpenAI returns 401 with ``{error:{...}}`` body.
    The classifier must not crash the upload; it falls through to the
    heuristic so the user can still complete the form (with a manual
    category dropdown). Operators see the failure in /cv-classifier/recent."""
    body = {
        "error": {
            "message": "Incorrect API key provided",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }
    }
    classifier = OpenAICategoryClassifier(
        api_key="sk-bad",
        client=_mock_httpx_client(body, status_code=401),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"x", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"


def test_openai_429_rate_limit_falls_back_to_heuristic():
    """Burst hitting per-minute caps — same UX as any other failure."""
    body = {
        "error": {
            "message": "Rate limit reached for requests",
            "type": "rate_limit_error",
            "code": "rate_limit_exceeded",
        }
    }
    classifier = OpenAICategoryClassifier(
        api_key="sk-test",
        client=_mock_httpx_client(body, status_code=429),
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"x", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"


def test_openai_retries_once_on_timeout_then_succeeds():
    """One transient timeout should be retried automatically before the
    classifier gives up and falls through to heuristic."""
    success_body = _openai_response_body("blouses", 0.92)

    success_response = MagicMock(spec=httpx.Response)
    success_response.status_code = 200
    success_response.json.return_value = success_body
    success_response.raise_for_status = MagicMock()

    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = [
        httpx.TimeoutException("read timeout"),
        success_response,
    ]
    classifier = OpenAICategoryClassifier(api_key="sk-test", client=client)

    pred = classifier.classify(b"x")

    assert pred.source == "cloud_llm"
    assert pred.category == "blouses"
    # First attempt + 1 retry == 2 calls.
    assert client.post.call_count == 2


def test_openai_two_consecutive_timeouts_fall_back_to_heuristic():
    """Both attempts time out → give up, heuristic kicks in. The breaker
    counts this as one failure (not two) so a temporarily slow upstream
    doesn't trip the 3-strike cooldown after one bad request."""
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.TimeoutException("read timeout")
    breaker = _CircuitBreaker(fail_threshold=3, cooldown_s=60.0)
    classifier = OpenAICategoryClassifier(
        api_key="sk-test",
        client=client,
        breaker=breaker,
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"x", attrs_hint={"occasion": "work"})

    assert pred.source == "heuristic"
    # 1 attempt + 1 retry — the breaker should count it as a single
    # failure, not two, so legitimate retries don't accelerate the trip.
    assert client.post.call_count == 2
    assert not breaker.is_open()


def test_openai_network_error_falls_back_to_heuristic():
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.TimeoutException("network timeout")
    classifier = OpenAICategoryClassifier(
        api_key="sk-test",
        client=client,
        fallback=HeuristicCategoryClassifier(),
    )

    pred = classifier.classify(b"fake-bytes", attrs_hint={"occasion": "work"})

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


def test_openai_skips_api_when_breaker_open():
    """Once the breaker trips, the classifier should skip the API
    entirely until cooldown — saves wall-clock time when the upstream
    is genuinely down."""
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.TimeoutException("flaky network")
    breaker = _CircuitBreaker(fail_threshold=3, cooldown_s=60.0)
    classifier = OpenAICategoryClassifier(
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
        "enable_vision_analysis": False,
        "openai_api_key": "",
        "openai_base_url": "https://api.openai.com",
        "openai_model": "gpt-5-mini",
        "openai_http_proxy": "",
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
            openai_api_key="sk-anything",
        )
    )
    assert isinstance(classifier, HeuristicCategoryClassifier)


def test_factory_returns_heuristic_when_openai_key_missing():
    classifier = get_category_classifier(
        _settings(
            use_cv_category_classifier=True,
            category_classifier_provider="openai",
            openai_api_key="",
        )
    )
    assert isinstance(classifier, HeuristicCategoryClassifier)


def test_factory_returns_openai_when_fully_configured():
    classifier = get_category_classifier(
        _settings(
            use_cv_category_classifier=True,
            category_classifier_provider="openai",
            openai_api_key="sk-test",
        )
    )
    assert isinstance(classifier, OpenAICategoryClassifier)


def test_factory_returns_heuristic_for_unknown_provider():
    """Old prod configs may still ship ``provider=claude`` after the
    migration. The factory must fall back to heuristic instead of
    crashing on import — env-flip rollback stays safe."""
    classifier = get_category_classifier(
        _settings(
            use_cv_category_classifier=True,
            category_classifier_provider="claude",
            openai_api_key="sk-test",
        )
    )
    assert isinstance(classifier, HeuristicCategoryClassifier)


# ---------------------------------------------------------------------------
# CategoryPrediction dataclass
# ---------------------------------------------------------------------------


def test_category_prediction_is_immutable():
    pred = CategoryPrediction(category="blouses", confidence=0.9, source="cloud_llm")
    with pytest.raises((AttributeError, Exception)):
        pred.category = "pants"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# OpenAIVisionAnalyzer — расширенный анализ за один запрос
# ---------------------------------------------------------------------------


def _vision_response_body(
    *,
    category: str = "blouses",
    confidence: float = 0.9,
    name: str | None = "белая блузка",
    primary_color: str | None = "white",
    attrs: dict | None = None,
    reasoning: str | None = "white silk",
    decoration: str = "",
) -> dict:
    """Build a Chat-Completions response carrying a vision JSON payload."""
    payload: dict = {
        "category": category,
        "confidence": confidence,
        "name": name,
        "primary_color": primary_color,
        "attrs": attrs if attrs is not None else {},
        "reasoning": reasoning,
    }
    json_str = json.dumps(payload, ensure_ascii=False)
    text = decoration.replace("{}", json_str) if decoration else json_str
    return {
        "id": "chatcmpl-vision",
        "object": "chat.completion",
        "model": "gpt-5-mini",
        "usage": {"prompt_tokens": 250, "completion_tokens": 120, "total_tokens": 370},
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
    }


def test_vision_returns_full_result_with_attrs():
    body = _vision_response_body(
        attrs={
            "fabric_rigidity": "soft",
            "fabric_finish": "matte",
            "occasion": "smart_casual",
            "neckline_type": "v",
            "sleeve_type": "puff_sharp",
            "sleeve_length": "long_wrist",
            "pattern_scale": None,
            "pattern_character": None,
            "pattern_symmetry": None,
            "detail_scale": "medium",
            "structure": "semi_structured",
            "cut_lines": "soft_flowing",
            "shoulder_emphasis": "neutral",
            "style_tags": ["romantic", "smart_casual"],
        }
    )
    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    result = analyzer.analyze(b"fake-jpeg")

    assert isinstance(result, VisionAnalysisResult)
    assert result.category == "blouses"
    assert 0.0 <= result.confidence <= 1.0
    assert result.name == "белая блузка"
    assert result.primary_color == "white"
    assert result.source == "cloud_llm"
    assert result.attrs["fabric_rigidity"] == "soft"
    assert result.attrs["sleeve_type"] == "puff_sharp"
    assert result.attrs["style_tags"] == ["romantic", "smart_casual"]


def test_vision_strips_invalid_attribute_values():
    """Если модель отдала значение вне whitelist — оно нормализуется в None."""
    body = _vision_response_body(
        attrs={
            "fabric_rigidity": "invented_value",  # не в whitelist
            "occasion": "smart_casual",  # валидно
            "style_tags": ["romantic", "fakeStyle"],  # отфильтруется
        }
    )
    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    result = analyzer.analyze(b"x")

    assert result.attrs["fabric_rigidity"] is None
    assert result.attrs["occasion"] == "smart_casual"
    assert result.attrs["style_tags"] == ["romantic"]


def test_vision_truncates_long_name():
    long_name = "очень длинное название платья в розовый горошек " * 5
    body = _vision_response_body(name=long_name)
    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    result = analyzer.analyze(b"x")

    assert result.name is not None
    assert len(result.name) <= 60


def test_vision_handles_null_name_and_color():
    body = _vision_response_body(name=None, primary_color=None, attrs={})
    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    result = analyzer.analyze(b"x")

    assert result.name is None
    assert result.primary_color is None
    # Все 14 атрибутов в attrs со значением None — не падаем.
    assert result.attrs["fabric_rigidity"] is None
    assert result.attrs["style_tags"] is None


def test_vision_uses_max_completion_tokens_not_max_tokens():
    """gpt-5-mini требует ``max_completion_tokens``; ``max_tokens`` устарело."""
    body = _vision_response_body()
    client = _mock_httpx_client(body)
    analyzer = OpenAIVisionAnalyzer(api_key="sk-test", client=client)

    analyzer.analyze(b"x")

    posted = client.post.call_args.kwargs["json"]
    assert "max_completion_tokens" in posted
    assert "max_tokens" not in posted


def test_vision_uses_response_format_json_object():
    body = _vision_response_body()
    client = _mock_httpx_client(body)
    analyzer = OpenAIVisionAnalyzer(api_key="sk-test", client=client)

    analyzer.analyze(b"x")

    posted = client.post.call_args.kwargs["json"]
    assert posted["response_format"] == {"type": "json_object"}


def test_vision_unparseable_response_raises():
    body = _vision_response_body()
    body["choices"][0]["message"]["content"] = "not a json"
    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    with pytest.raises(RuntimeError):
        analyzer.analyze(b"x")


def test_vision_unknown_category_raises():
    body = _vision_response_body(category="unknown_garment")
    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test", client=_mock_httpx_client(body)
    )

    with pytest.raises(RuntimeError):
        analyzer.analyze(b"x")


def test_vision_factory_returns_none_when_disabled():
    assert get_vision_analyzer(_settings(enable_vision_analysis=False)) is None


def test_vision_factory_returns_none_without_api_key():
    assert (
        get_vision_analyzer(
            _settings(enable_vision_analysis=True, openai_api_key="")
        )
        is None
    )


def test_vision_factory_returns_analyzer_when_configured():
    analyzer = get_vision_analyzer(
        _settings(
            enable_vision_analysis=True,
            openai_api_key="sk-test",
            openai_model="gpt-5-mini",
        )
    )
    assert isinstance(analyzer, OpenAIVisionAnalyzer)


def test_vision_factory_passes_proxy_through():
    """``openai_http_proxy`` из Settings должен попасть в analyzer."""
    analyzer = get_vision_analyzer(
        _settings(
            enable_vision_analysis=True,
            openai_api_key="sk-test",
            openai_http_proxy="http://user:pass@proxy.example.com:8080",
        )
    )
    assert analyzer is not None
    assert analyzer._proxy == "http://user:pass@proxy.example.com:8080"


def test_vision_factory_empty_proxy_becomes_none():
    """Пустая строка proxy не должна стать ``proxy=""`` в httpx.Client."""
    analyzer = get_vision_analyzer(
        _settings(
            enable_vision_analysis=True,
            openai_api_key="sk-test",
            openai_http_proxy="",
        )
    )
    assert analyzer is not None
    assert analyzer._proxy is None


def test_classifier_factory_passes_proxy_through():
    classifier = get_category_classifier(
        _settings(
            use_cv_category_classifier=True,
            category_classifier_provider="openai",
            openai_api_key="sk-test",
            openai_http_proxy="http://10.0.0.1:3128",
        )
    )
    assert isinstance(classifier, OpenAICategoryClassifier)
    assert classifier._proxy == "http://10.0.0.1:3128"


# ---------------------------------------------------------------------------
# RemoteProtocolError → авто-переключение http:// → https:// в proxy URL
# ---------------------------------------------------------------------------


def test_vision_retries_on_remote_protocol_error_with_https():
    """Если первый POST ловит RemoteProtocolError и proxy начинается с
    http:// — переключаемся на https:// и повторяем один раз."""
    success_body = _vision_response_body()

    success_response = MagicMock(spec=httpx.Response)
    success_response.status_code = 200
    success_response.json.return_value = success_body
    success_response.raise_for_status = MagicMock()

    client = MagicMock(spec=httpx.Client)
    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.RemoteProtocolError("illegal request line")
        return success_response

    client.post.side_effect = fake_post

    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test",
        proxy="http://user:pass@host:8080",
        client=client,
    )

    result = analyzer.analyze(b"fake-jpeg")

    assert result.category == "blouses"
    # Прокси переписан на https://, флаг попытки взведён.
    assert analyzer._proxy.startswith("https://")
    assert analyzer._proxy_https_attempted is True
    # Один retry == два http POST'а.
    assert client.post.call_count == 2


def test_vision_does_not_loop_when_cascade_exhausted():
    """Каскад http → https → socks5: после трёх попыток сдаёмся."""
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.RemoteProtocolError("illegal request line")

    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test",
        proxy="http://user:pass@host:8080",
        client=client,
    )

    with pytest.raises(RuntimeError):
        analyzer.analyze(b"fake-jpeg")

    # Каскад из трёх схем — три POST'а.
    assert client.post.call_count == 3
    assert analyzer._proxy.startswith("socks5://")


def test_vision_cascade_is_cyclic_from_any_starting_scheme():
    """Любая стартовая схема перебирает все три варианта каскада.

    proxy-seller выдаёт креды без явной схемы — пользователь может
    задать в секрете любой префикс. Если стартуем с ``socks5://``
    и она не работает — следующая попытка идёт на ``http://``,
    потом на ``https://``, и только после трёх неудач сдаёмся.
    """
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.RemoteProtocolError("illegal request line")

    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test",
        proxy="socks5://user:pass@host:8080",
        client=client,
    )

    with pytest.raises(RuntimeError):
        analyzer.analyze(b"fake-jpeg")

    # Циклический каскад: socks5 → http → https — три попытки.
    assert client.post.call_count == 3
    # Последняя попытка осталась в _proxy для дебага.
    assert analyzer._proxy.startswith("https://")


def test_vision_cascade_recovers_on_http_when_starting_from_https():
    """Регрессия 2026-05-03: стартуем с https:// (как было в проде),
    https и socks5 падают handshake-ошибками, http отвечает 200.

    Цикл должен пройти https → socks5 → http и вернуть успешный
    ответ — раньше каскад был линейным и до http не доходил.
    """
    success_body = _vision_response_body()
    success_response = MagicMock(spec=httpx.Response)
    success_response.status_code = 200
    success_response.json.return_value = success_body
    success_response.raise_for_status = MagicMock()

    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("[SSL] record layer failure (_ssl.c:1016)")
        if call_count["n"] == 2:
            raise httpx.RemoteProtocolError("Malformed reply")
        return success_response

    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = fake_post

    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test",
        proxy="https://user:pass@host:8080",
        client=client,
    )

    result = analyzer.analyze(b"fake-jpeg")

    assert result.category == "blouses"
    assert client.post.call_count == 3
    assert analyzer._proxy == "http://user:pass@host:8080"
    assert analyzer._proxy_resolved is True


def test_vision_cascade_http_to_https_to_socks5_succeeds():
    """proxy-seller сценарий: http даёт illegal request line, https даёт
    SSL record layer failure, socks5 наконец отвечает 200."""
    success_body = _vision_response_body()
    success_response = MagicMock(spec=httpx.Response)
    success_response.status_code = 200
    success_response.json.return_value = success_body
    success_response.raise_for_status = MagicMock()

    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.RemoteProtocolError("illegal request line")
        if call_count["n"] == 2:
            raise httpx.ConnectError("[SSL] record layer failure (_ssl.c:1016)")
        return success_response

    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = fake_post

    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test",
        proxy="http://user:pass@host:8080",
        client=client,
    )

    result = analyzer.analyze(b"fake-jpeg")

    assert result.category == "blouses"
    assert client.post.call_count == 3
    assert analyzer._proxy == "socks5://user:pass@host:8080"
    assert analyzer._proxy_resolved is True


def test_vision_cascade_does_not_eat_unrelated_connect_errors():
    """ConnectError без SSL/TLS в сообщении — это сетевая проблема до
    OpenAI, не дело каскада. Схема прокси не должна меняться."""
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.ConnectError("Name or service not known")

    analyzer = OpenAIVisionAnalyzer(
        api_key="sk-test",
        proxy="http://user:pass@host:8080",
        client=client,
    )

    with pytest.raises(RuntimeError):
        analyzer.analyze(b"fake-jpeg")

    # Каскад НЕ активирован: схема прокси осталась исходной.
    assert analyzer._proxy.startswith("http://")
    assert analyzer._proxy_resolved is False
