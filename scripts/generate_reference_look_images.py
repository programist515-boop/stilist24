"""Generate real reference-look images via GrsAI (gpt-image-2).

Replaces placeholder gradient+text JPEGs in
``frontend/public/reference_looks/<subtype>/<look_id>.jpg`` with
AI-generated fashion photography. The YAML and API paths don't change;
this script just overwrites the files on disk.

Usage:
    export GRSAI_API_KEY=sk-...
    python scripts/generate_reference_look_images.py --dry-run  # preview prompts
    python scripts/generate_reference_look_images.py --look rm_wrap_dress_silk
    python scripts/generate_reference_look_images.py --only romantic,dramatic --limit 5
    python scripts/generate_reference_look_images.py --all

Reads YAMLs from ``ai-stylist-starter/config/rules/reference_looks/`` and
writes 600×800 JPEGs back to ``frontend/public/reference_looks/``.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml
from PIL import Image


# ----- paths --------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
YAML_DIR = ROOT / "ai-stylist-starter" / "config" / "rules" / "reference_looks"
OUTPUT_DIR = ROOT / "frontend" / "public" / "reference_looks"
LOG_PATH = ROOT / ".cache" / "reference_look_generation.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

API_HOST = "https://api.grsai.com"
COMPLETIONS_URL = f"{API_HOST}/v1/draw/completions"
RESULT_URL = f"{API_HOST}/v1/draw/result"

TARGET_SIZE = (600, 800)
PLACEHOLDER_MAX_SIZE_BYTES = 50 * 1024  # files ≤50 KB are treated as placeholders

SUBTYPE_TO_FAMILY = {
    "dramatic": "dramatic",
    "soft_dramatic": "dramatic",
    "flamboyant_natural": "natural",
    "soft_natural": "natural",
    "natural": "natural",
    "dramatic_classic": "classic",
    "soft_classic": "classic",
    "classic": "classic",
    "flamboyant_gamine": "gamine",
    "soft_gamine": "gamine",
    "gamine": "gamine",
    "romantic": "romantic",
    "theatrical_romantic": "romantic",
}

SUBTYPE_DISPLAY_EN = {
    "dramatic": "Dramatic",
    "soft_dramatic": "Soft Dramatic",
    "flamboyant_natural": "Flamboyant Natural",
    "soft_natural": "Soft Natural",
    "natural": "Natural",
    "dramatic_classic": "Dramatic Classic",
    "soft_classic": "Soft Classic",
    "classic": "Classic",
    "flamboyant_gamine": "Flamboyant Gamine",
    "soft_gamine": "Soft Gamine",
    "gamine": "Gamine",
    "romantic": "Romantic",
    "theatrical_romantic": "Theatrical Romantic",
}

FAMILY_CHARACTER_EN = {
    "dramatic": (
        "tall vertical line, sharp angular features, narrow frame — "
        "commanding and austere elegance, never softened"
    ),
    "natural": (
        "relaxed blunt lines, moderate width, effortless athletic proportions — "
        "no precious fussy details, honest natural fabrics"
    ),
    "classic": (
        "balanced symmetry, moderate proportions, timeless elegance — "
        "nothing extreme in any direction, quiet sophistication"
    ),
    "gamine": (
        "compact petite frame with contrasting yin-yang features, graphic bold energy, "
        "crisp short silhouettes, NEVER elongated or flowing"
    ),
    "romantic": (
        "soft curves, lush hourglass silhouette with defined waist, "
        "delicate rounded features, draping fabrics that hug the body"
    ),
}

SEASON_EN = {
    "all": "year-round",
    "spring": "spring",
    "summer": "summer",
    "autumn": "autumn",
    "winter": "winter",
    "spring_summer": "spring and summer",
    "autumn_winter": "autumn and winter",
    "spring_autumn": "spring and autumn",
}

STYLE_EN = {
    "casual": "casual daywear",
    "smart_casual": "smart-casual",
    "office": "office/work",
    "weekend": "weekend leisure",
    "evening": "evening wear",
    "dramatic": "dramatic signature",
    "dramatic_classic": "polished classic",
    "military": "military-inspired",
}


def _slot_en(slot: str) -> str:
    return slot.replace("_", " ")


def _requires_en(requires: dict | None) -> str:
    """Translate a requires-dict into a human-readable English phrase.

    We deliberately keep this simple: drop the ``pending_`` prefix, swap
    underscores for spaces, flatten list values. The generation model
    doesn't need structured semantics — it needs rich descriptive text.
    """
    if not requires:
        return ""
    parts: list[str] = []
    for key, value in requires.items():
        clean_key = key.replace("pending_", "").replace("_", " ")
        if isinstance(value, list):
            value_str = " or ".join(str(v).replace("_", " ") for v in value)
        elif value is None:
            continue
        else:
            value_str = str(value).replace("_", " ")
        parts.append(f"{clean_key}: {value_str}")
    return "; ".join(parts)


def _items_brief(items: list[dict]) -> str:
    """Short list of slot/category pairs for the opening line of the prompt."""
    brief_parts: list[str] = []
    for it in items:
        slot = _slot_en(it.get("slot", "garment"))
        req = it.get("requires", {}) or {}
        cat = req.get("category", "")
        if isinstance(cat, list):
            cat = " or ".join(str(c).replace("_", " ") for c in cat)
        else:
            cat = str(cat).replace("_", " ")
        if cat:
            brief_parts.append(f"{cat}")
        else:
            brief_parts.append(slot)
    return ", ".join(brief_parts)


def build_prompt(look: dict, subtype: str) -> str:
    """Assemble the EN prompt for gpt-image-2 from a look YAML block."""
    family = SUBTYPE_TO_FAMILY[subtype]
    subtype_en = SUBTYPE_DISPLAY_EN[subtype]
    family_character = FAMILY_CHARACTER_EN[family]

    name = look.get("name", look.get("id", "look"))
    style_key = look.get("style", "casual")
    style_en = STYLE_EN.get(style_key, style_key.replace("_", " "))
    season_key = look.get("season_hint", "all")
    season_en = SEASON_EN.get(season_key, season_key.replace("_", " "))

    items = look.get("items", []) or []
    accessories = look.get("accessories", []) or []
    notes = look.get("notes", []) or []

    items_brief = _items_brief(items)
    items_detail_lines = []
    for it in items:
        slot = _slot_en(it.get("slot", "garment"))
        req_en = _requires_en(it.get("requires"))
        if req_en:
            items_detail_lines.append(f"  - {slot}: {req_en}")
        else:
            items_detail_lines.append(f"  - {slot}")
    items_detail = "\n".join(items_detail_lines)

    accessories_lines = []
    for acc in accessories:
        if not isinstance(acc, dict):
            continue
        atype = str(acc.get("type", "accessory")).replace("_", " ")
        req_en = _requires_en(acc.get("requires"))
        accessories_lines.append(
            f"  - {atype}: {req_en}" if req_en else f"  - {atype}"
        )
    accessories_section = (
        "Accessories:\n" + "\n".join(accessories_lines) + "\n"
        if accessories_lines
        else ""
    )

    notes_en = " ".join(str(n) for n in notes)

    gamine_face_hint = ""
    if family == "gamine":
        gamine_face_hint = (
            " Compact petite figure — do NOT visually elongate the body."
        )

    prompt = f"""Professional fashion photography, full-body editorial shot, portrait 2:3 aspect ratio.

Outfit: "{name}" — {style_en}, suitable for {season_en}.
Subject: woman wearing {items_brief}, shown from chest down or 3/4 body — face NOT the focus.{gamine_face_hint}

Outfit composition:
{items_detail}

{accessories_section}Kibbe body type character ({subtype_en}, {family} family):
{family_character}

Styling notes from the stylist:
{notes_en}

Technical: neutral minimal studio background (soft beige, warm grey or off-white),
diffused natural lighting, clean uncluttered composition, fashion magazine editorial quality,
realistic photography, sharp focus on the garments and their textures.

Avoid: text, watermark, logo, cartoon style, 3D render, distorted anatomy,
extra limbs, low quality, overly stylized illustration, busy background, cluttered scene.
"""
    return prompt.strip()


# ----- API client ---------------------------------------------------------


class GrsAIError(RuntimeError):
    pass


def _post_with_retries(
    url: str, api_key: str, payload: dict, *, max_retries: int = 3
) -> dict:
    """POST with exponential backoff. Raises GrsAIError on final failure."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
                stream=True,
            )
            r.raise_for_status()
            # GrsAI may stream multiple JSON lines; we take the last valid JSON.
            final: dict | None = None
            buf = ""
            for chunk in r.iter_content(chunk_size=4096, decode_unicode=True):
                if not chunk:
                    continue
                buf += chunk
            # Try to parse; if the body is a single JSON, this is enough.
            try:
                import json as _json

                try:
                    final = _json.loads(buf)
                except _json.JSONDecodeError:
                    # Multi-line: parse each line separately, keep last.
                    for line in buf.strip().splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            final = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
            except Exception as exc:  # pragma: no cover
                raise GrsAIError(f"failed to parse response body: {exc}")
            if final is None:
                raise GrsAIError(f"empty response body (status={r.status_code})")
            return final
        except (requests.RequestException, GrsAIError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                backoff = 2**attempt
                print(f"  [retry {attempt + 1}/{max_retries}] {exc} — sleep {backoff}s")
                time.sleep(backoff)
    raise GrsAIError(f"all retries failed: {last_exc}")


def generate_image_bytes(prompt: str, *, api_key: str, quality: str = "high") -> bytes:
    """Submit a generation task and poll until ready. Returns JPEG/PNG bytes.

    Uses ``webHook: "-1"`` to get an immediate task_id, then polls
    ``/v1/draw/result`` every 3 seconds for up to 90 seconds.
    """
    submit_payload = {
        "model": "gpt-image-2",
        "prompt": prompt,
        "size": "2:3",
        "quality": quality,
        "variants": 1,
        "webHook": "-1",
    }
    submit = _post_with_retries(COMPLETIONS_URL, api_key, submit_payload)
    task_id = submit.get("id") or submit.get("task_id") or submit.get("data", {}).get(
        "id"
    )
    if not task_id:
        # Some providers return the result inline for quick tasks.
        image_url = (
            submit.get("url")
            or submit.get("image_url")
            or (submit.get("data") or {}).get("url")
        )
        if image_url:
            return _download(image_url)
        raise GrsAIError(f"submit response has no task_id and no inline url: {submit}")

    deadline = time.time() + 90
    last_status: dict = {}
    while time.time() < deadline:
        poll = _post_with_retries(RESULT_URL, api_key, {"id": task_id})
        last_status = poll
        data = poll.get("data") if isinstance(poll.get("data"), dict) else poll
        status = (data or {}).get("status")
        if status in {"succeeded", "success", "completed", "done"}:
            url = (data or {}).get("url") or (data or {}).get("image_url")
            if url:
                return _download(url)
            results = (data or {}).get("results") or (data or {}).get("images") or []
            if results and isinstance(results, list):
                first = results[0]
                if isinstance(first, dict):
                    url = first.get("url") or first.get("image_url")
                elif isinstance(first, str):
                    url = first
                if url:
                    return _download(url)
            raise GrsAIError(f"succeeded but no url: {poll}")
        if status in {"failed", "error"}:
            raise GrsAIError(
                f"task failed: {(data or {}).get('failure_reason') or poll}"
            )
        time.sleep(3)
    raise GrsAIError(f"timed out after 90s; last status: {last_status}")


def _download(url: str) -> bytes:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content


# ----- image processing ---------------------------------------------------


def resize_and_crop(img_bytes: bytes, target: tuple[int, int] = TARGET_SIZE) -> bytes:
    """Center-crop to 3:4 aspect, resize to target, save as JPEG quality=90."""
    src = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    tw, th = target  # 600, 800
    target_ratio = tw / th

    sw, sh = src.size
    src_ratio = sw / sh
    if src_ratio > target_ratio:
        new_w = int(sh * target_ratio)
        off_x = (sw - new_w) // 2
        src = src.crop((off_x, 0, off_x + new_w, sh))
    elif src_ratio < target_ratio:
        new_h = int(sw / target_ratio)
        off_y = (sh - new_h) // 2
        src = src.crop((0, off_y, sw, off_y + new_h))

    src = src.resize(target, Image.LANCZOS)
    out = io.BytesIO()
    src.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue()


# ----- orchestration ------------------------------------------------------


def load_all_looks() -> list[tuple[str, str, dict]]:
    """Return flat list of (subtype, look_id, look_dict) from every YAML."""
    out: list[tuple[str, str, dict]] = []
    for yaml_path in sorted(YAML_DIR.glob("*.yaml")):
        text = yaml_path.read_text(encoding="utf-8")
        doc = yaml.safe_load(text) or {}
        subtype = doc.get("subtype") or yaml_path.stem
        for look in doc.get("reference_looks", []) or []:
            look_id = look.get("id")
            if not look_id:
                continue
            out.append((subtype, look_id, look))
    return out


def should_skip(subtype: str, look_id: str, skip_existing: bool) -> bool:
    if not skip_existing:
        return False
    target = OUTPUT_DIR / subtype / f"{look_id}.jpg"
    if not target.is_file():
        return False
    return target.stat().st_size > PLACEHOLDER_MAX_SIZE_BYTES


def log_result(subtype: str, look_id: str, status: str, message: str = "") -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}\t{subtype}\t{look_id}\t{status}\t{message}\n"
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


def main() -> int:
    # Windows console defaults to cp1251; Cyrillic look names and notes
    # render as mojibake there. This only affects the debug print —
    # the HTTP body itself is always UTF-8 via requests' json= kwarg.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--only", help="comma-separated subtype filter")
    p.add_argument("--look", help="single look_id to regenerate")
    p.add_argument("--all", action="store_true", help="generate every look")
    p.add_argument("--skip-existing", action="store_true",
                   help="skip looks whose file already exceeds placeholder size")
    p.add_argument("--quality", default="high", choices=["standard", "high"])
    p.add_argument("--dry-run", action="store_true",
                   help="print prompts without calling the API")
    p.add_argument("--limit", type=int, default=None,
                   help="hard cap on number of API calls (budget safety)")
    args = p.parse_args()

    if not (args.only or args.look or args.all):
        print("pick one of --only <subtype>, --look <id>, or --all", file=sys.stderr)
        return 2

    api_key = os.environ.get("GRSAI_API_KEY", "")
    if not api_key and not args.dry_run:
        print("GRSAI_API_KEY env var is required (not set). "
              "Export it before running, or use --dry-run.", file=sys.stderr)
        return 2

    all_looks = load_all_looks()

    if args.look:
        looks = [t for t in all_looks if t[1] == args.look]
        if not looks:
            print(f"look_id {args.look!r} not found in any YAML", file=sys.stderr)
            return 2
    elif args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        looks = [t for t in all_looks if t[0] in wanted]
    else:
        looks = list(all_looks)

    if args.limit:
        looks = looks[: args.limit]

    print(f"{'='*60}")
    print(f"Plan: {len(looks)} looks; quality={args.quality}; dry_run={args.dry_run}")
    print(f"{'='*60}")

    successes = 0
    failures: list[tuple[str, str, str]] = []
    for subtype, look_id, look in looks:
        if should_skip(subtype, look_id, args.skip_existing):
            print(f"  [skip] {subtype}/{look_id} (exists, >{PLACEHOLDER_MAX_SIZE_BYTES}B)")
            continue

        prompt = build_prompt(look, subtype)
        print(f"\n[{subtype}/{look_id}] prompt length={len(prompt)}")

        if args.dry_run:
            print("--- PROMPT ---")
            print(prompt)
            print("--- /PROMPT ---")
            continue

        try:
            raw = generate_image_bytes(prompt, api_key=api_key, quality=args.quality)
            final = resize_and_crop(raw)
            target = OUTPUT_DIR / subtype / f"{look_id}.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(final)
            print(f"  [ok] {target} ({len(final)//1024} KB)")
            log_result(subtype, look_id, "ok", f"{len(final)} bytes")
            successes += 1
        except Exception as exc:
            print(f"  [FAIL] {exc}")
            log_result(subtype, look_id, "fail", str(exc))
            failures.append((subtype, look_id, str(exc)))

    print(f"\n{'='*60}")
    print(f"Done: {successes} generated, {len(failures)} failed")
    if failures:
        print("Failures:")
        for s, lid, err in failures:
            print(f"  - {s}/{lid}: {err}")
    print(f"Log: {LOG_PATH}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
