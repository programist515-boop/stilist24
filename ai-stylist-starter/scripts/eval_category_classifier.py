"""Acceptance harness for the wardrobe category classifier.

Reads a labelled dataset (image path → expected category) and runs each
image through a configured classifier. Reports top-1 accuracy, p95
latency, and per-image errors. Used as a go/no-go gate before flipping
the production feature flag.

Run::

    ANTHROPIC_API_KEY=sk-... python -m scripts.eval_category_classifier \\
        --dataset scripts/eval_dataset.tsv

Dataset format — one ``relative-image-path<TAB>expected_category`` per
line, ``#`` for comments. Paths are resolved relative to the repo root.
Sample (using reference-look photos, where the prominent item is
unambiguous)::

    # blouses (top-half garments)
    ../frontend/public/reference_looks/classic/cl_blouse_pencil_belt.jpg	blouses
    # dresses (head-to-toe single-item photos)
    ../frontend/public/reference_looks/romantic/rm_wrap_dress_silk.jpg	dresses
    ...

Pass criteria for prod rollout:
  * accuracy ≥ 0.85 over ≥ 50 samples
  * p95 latency < 3.0 s
  * error rate < 0.02
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.services.categories import WARDROBE_CATEGORIES
from app.services.category_classifier import (
    AnthropicCategoryClassifier,
    CategoryClassifier,
    HeuristicCategoryClassifier,
    get_category_classifier,
)


PASS_ACCURACY = 0.85
PASS_P95_LATENCY_S = 3.0
PASS_ERROR_RATE = 0.02


def _parse_dataset(path: Path) -> list[tuple[Path, str]]:
    samples: list[tuple[Path, str]] = []
    base = path.parent
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rel_path, expected = line.split("\t", 1)
        except ValueError:
            print(f"  skip malformed line: {line!r}", file=sys.stderr)
            continue
        expected = expected.strip()
        if expected not in WARDROBE_CATEGORIES:
            print(
                f"  skip unknown expected category {expected!r} in {line!r}",
                file=sys.stderr,
            )
            continue
        img = (base / rel_path).resolve()
        if not img.is_file():
            print(f"  skip missing file: {img}", file=sys.stderr)
            continue
        samples.append((img, expected))
    return samples


def _build_classifier(force_provider: str | None) -> CategoryClassifier:
    """Pick a classifier matching CLI flags, ignoring the global flag.

    The global ``USE_CV_CATEGORY_CLASSIFIER`` is for the route — the
    eval script always wants to actually run the classifier we asked
    for, even when prod is OFF.
    """
    provider = force_provider or settings.category_classifier_provider
    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key
        if not api_key:
            print(
                "ERROR: ANTHROPIC_API_KEY not set — pass --provider heuristic "
                "for an offline run, or export the key first.",
                file=sys.stderr,
            )
            sys.exit(2)
        return AnthropicCategoryClassifier(api_key=api_key)
    if provider == "heuristic":
        return HeuristicCategoryClassifier()
    # "disabled" or anything else — fall through to the factory's defaults
    # (heuristic when flag is off).
    return get_category_classifier(settings)


def _media_type_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"  # best-effort default — Claude accepts most JPEGs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to a TSV file with `image_path\\texpected_category` lines.",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "heuristic"],
        default=None,
        help="Override Settings.category_classifier_provider for this run.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Stop after N samples (handy for smoke runs).",
    )
    args = parser.parse_args()

    samples = _parse_dataset(args.dataset)
    if args.max_samples:
        samples = samples[: args.max_samples]
    if not samples:
        print("No usable samples — check the dataset.", file=sys.stderr)
        return 2

    classifier = _build_classifier(args.provider)
    print(
        f"Running {len(samples)} samples through {type(classifier).__name__}",
        flush=True,
    )

    correct = 0
    errors = 0
    latencies: list[float] = []
    confusions: dict[tuple[str, str], int] = {}

    for idx, (img_path, expected) in enumerate(samples, 1):
        try:
            image_bytes = img_path.read_bytes()
            t0 = time.perf_counter()
            pred = classifier.classify(
                image_bytes, media_type=_media_type_from_path(img_path)
            )
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)

            actual = pred.category
            ok = actual == expected
            correct += int(ok)
            if not ok:
                key = (expected, actual)
                confusions[key] = confusions.get(key, 0) + 1
            print(
                f"  [{idx:3d}/{len(samples)}] {img_path.name:40s} "
                f"expected={expected:10s} actual={actual:10s} "
                f"conf={pred.confidence:.2f} ({elapsed:.2f}s) "
                f"{'OK' if ok else 'MISS'}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 — we report every kind of failure
            errors += 1
            print(
                f"  [{idx:3d}/{len(samples)}] {img_path.name}: ERROR {exc!r}",
                flush=True,
            )

    n = len(samples)
    accuracy = correct / n if n else 0.0
    error_rate = errors / n if n else 0.0
    p95 = (
        statistics.quantiles(latencies, n=20)[18]  # 95th percentile
        if len(latencies) >= 20
        else (max(latencies) if latencies else 0.0)
    )
    median = statistics.median(latencies) if latencies else 0.0

    print()
    print(f"samples:    {n}")
    print(f"accuracy:   {accuracy:.2%}  (target ≥ {PASS_ACCURACY:.0%})")
    print(f"errors:     {errors} ({error_rate:.2%})")
    print(f"latency:    median={median:.2f}s  p95={p95:.2f}s  (target p95 < {PASS_P95_LATENCY_S}s)")

    if confusions:
        print()
        print("confusions (expected → actual: count):")
        for (exp, act), cnt in sorted(confusions.items(), key=lambda kv: -kv[1]):
            print(f"  {exp:12s} → {act:12s}: {cnt}")

    passed = (
        accuracy >= PASS_ACCURACY
        and p95 < PASS_P95_LATENCY_S
        and error_rate < PASS_ERROR_RATE
    )
    print()
    print("RESULT:", "PASS — safe to flip the prod flag" if passed else "FAIL — do not enable in prod")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
