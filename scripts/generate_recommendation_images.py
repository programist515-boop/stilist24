"""Generate illustration thumbnails for every bullet in recommendation_guides.yaml.

Reads ``ai-stylist-starter/config/rules/recommendation_guides.yaml``, walks
every ``recommended`` / ``avoid`` bullet in every section of every Kibbe
family, and for each bullet without an attached image:

1. Slugifies the text (transliterates Russian → latin, snake_case, ≤ 50 chars).
2. Builds a prompt from a single template (so the whole 361-image set has
   one visual identity: flat editorial illustration on a soft off-white
   background, faceless mannequin, no people / brands / text).
3. Calls grsai.ai ``gpt-image-2`` (POST /v1/draw/completions, then poll
   /v1/draw/result until the task is done).
4. Resizes the returned PNG → 512×512 JPEG q85 with Pillow.
5. Writes it to ``frontend/public/recommendations/{family}/{section}/{slug}.jpg``.
6. Updates the YAML in place — the bullet becomes ``{text, slug, image}``
   instead of a plain string. Existing comments / quoting / order are
   preserved by ruamel.yaml.

The script is **idempotent**: a bullet that already has ``image`` and the
file on disk exists is skipped. Re-runs only do new bullets.

Env vars (read from ``ai-stylist-starter/.env`` automatically):

    GRSAI_API_KEY       required, ``Bearer`` token for grsai.ai
    GRSAI_BASE_URL      optional, default ``https://grsaiapi.com``

Usage:

    pip install httpx pillow ruamel.yaml
    python scripts/generate_recommendation_images.py --dry-run
    python scripts/generate_recommendation_images.py --family romantic --limit 1   # smoke
    python scripts/generate_recommendation_images.py --family romantic              # pilot
    python scripts/generate_recommendation_images.py                                # all 361

Flags:

    --family <name>     limit to one Kibbe family (dramatic|natural|classic|gamine|romantic)
    --section <key>     limit to one section key (e.g. lines_silhouette)
    --limit N           cap pending jobs (handy for smoke tests)
    --dry-run           don't call API, don't write files; print what *would* happen
    --concurrency N     parallel image requests (default 4)
    --quality {low,medium,high,auto}   gpt-image-2 quality tier (default medium)

The Russian bullet text is sent to gpt-image-2 directly — the model
handles Russian prompts; if a particular bullet doesn't render well,
edit its YAML node and add a ``prompt_en`` override field; the script
will use that string for the API call instead.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import time
from pathlib import Path
from typing import Any

# These imports are intentionally inside try/except so a fresh checkout
# can still run --help even if optional deps are missing.
try:
    import httpx
    from PIL import Image
    from ruamel.yaml import YAML
except ImportError as e:
    print(
        f"Missing dependency: {e}\n"
        f"Install with: pip install httpx pillow ruamel.yaml",
        file=sys.stderr,
    )
    sys.exit(2)


# ---------------------------------------------------------------- paths

REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = REPO_ROOT / "ai-stylist-starter" / "config" / "rules" / "recommendation_guides.yaml"
PUBLIC_DIR = REPO_ROOT / "frontend" / "public" / "recommendations"
URL_PREFIX = "/recommendations"  # what the browser fetches

KIBBE_FAMILIES = ("dramatic", "natural", "classic", "gamine", "romantic")


# ---------------------------------------------------------------- slugify

# Minimal RU→latin table — enough for fashion vocabulary; matches the
# project's existing approach of inline-mapping rather than pulling
# in a transliteration library.
_RU2LAT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        "А": "a", "Б": "b", "В": "v", "Г": "g", "Д": "d", "Е": "e", "Ё": "e",
        "Ж": "zh", "З": "z", "И": "i", "Й": "i", "К": "k", "Л": "l", "М": "m",
        "Н": "n", "О": "o", "П": "p", "Р": "r", "С": "s", "Т": "t", "У": "u",
        "Ф": "f", "Х": "h", "Ц": "ts", "Ч": "ch", "Ш": "sh", "Щ": "sch",
        "Ъ": "", "Ы": "y", "Ь": "", "Э": "e", "Ю": "yu", "Я": "ya",
    }
)

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_words: int = 4, max_len: int = 50) -> str:
    """Make a stable, ASCII, snake_case slug from a Russian bullet."""
    if not text:
        return "item"
    latin = text.translate(_RU2LAT).lower()
    cleaned = _NON_ALNUM.sub(" ", latin).strip()
    words = [w for w in cleaned.split() if w][:max_words]
    slug = "_".join(words) if words else "item"
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("_")
    return slug


def make_unique(slug: str, taken: set[str]) -> str:
    """Append _2, _3, ... if slug already used in this section."""
    if slug not in taken:
        taken.add(slug)
        return slug
    n = 2
    while f"{slug}_{n}" in taken:
        n += 1
    final = f"{slug}_{n}"
    taken.add(final)
    return final


# ---------------------------------------------------------------- prompt

PROMPT_TEMPLATE = (
    "Minimalist editorial fashion illustration of: «{subject}». "
    "Show the clothing piece (or fashion concept) on a faceless dress form / mannequin, "
    "centered, isolated on a soft off-white background (#F5F2EC). "
    "Flat colors, clean line art, soft floor shadow. "
    "No people, no faces, no text, no logos, no brand marks. "
    "Square 1:1 format, neutral palette: muted earth tones with one quiet accent. "
    "Style consistent with a calm, premium fashion guide."
)


def build_prompt(item: dict | str) -> str:
    if isinstance(item, dict):
        override = item.get("prompt_en")
        if override:
            return PROMPT_TEMPLATE.format(subject=str(override).strip())
        subject = str(item.get("text") or "").strip()
    else:
        subject = str(item).strip()
    return PROMPT_TEMPLATE.format(subject=subject)


# ---------------------------------------------------------------- grsai.ai

# grsai.ai is a paid aggregator that exposes ``gpt-image-2`` (the OpenAI
# image model behind a Chinese reseller). Two-step async flow:
#
#   POST {BASE}/v1/draw/completions  →  {code, msg, data:{id}}
#   POST {BASE}/v1/draw/result       →  {code, msg, data:{status, results, ...}}
#
# Setting ``webHook="-1"`` makes the submit return immediately with a
# task id; we then poll the result endpoint until the task is done.
# Image URLs in ``data.results`` are valid for 2 hours, so we download
# them inline before moving on.

DEFAULT_BASE_URL = "https://grsaiapi.com"
DEFAULT_MODEL = "gpt-image-2"
POLL_INTERVAL_SECONDS = 3.0
JOB_TIMEOUT_SECONDS = 180.0


class _ModerationBlocked(Exception):
    """grsai refused the prompt or output for moderation reasons."""


async def _submit_task(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    prompt: str,
    quality: str,
    model: str,
) -> str:
    body = {
        "model": model,
        "prompt": prompt,
        "aspectRatio": "1:1",
        "quality": quality,
        "webHook": "-1",   # polling mode — get id immediately
        "shutProgress": True,
    }
    r = await client.post(
        f"{base_url}/v1/draw/completions", json=body, timeout=60.0
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 0:
        raise RuntimeError(
            f"grsai submit failed: code={payload.get('code')} msg={payload.get('msg')}"
        )
    task_id = (payload.get("data") or {}).get("id")
    if not task_id:
        raise RuntimeError(f"grsai submit returned no task id: {payload!r}")
    return str(task_id)


async def _poll_result(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    task_id: str,
) -> str:
    """Poll until the task is done, return the image URL."""
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    last_err: str | None = None
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"grsai timeout after {JOB_TIMEOUT_SECONDS:.0f}s (task={task_id}, last_err={last_err})"
            )
        r = await client.post(
            f"{base_url}/v1/draw/result",
            json={"id": task_id},
            timeout=30.0,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"grsai result failed: code={payload.get('code')} msg={payload.get('msg')}"
            )
        data = payload.get("data") or {}
        status = data.get("status")
        if status == "succeeded":
            results = data.get("results") or []
            if not results or not results[0].get("url"):
                raise RuntimeError(f"grsai succeeded but no url (task={task_id})")
            return str(results[0]["url"])
        if status == "failed":
            reason = data.get("failure_reason") or ""
            err = data.get("error") or ""
            if reason in ("input_moderation", "output_moderation"):
                raise _ModerationBlocked(f"{reason}: {err} (task={task_id})")
            raise RuntimeError(
                f"grsai task failed (task={task_id}): reason={reason} error={err}"
            )
        # status == "running" or unknown — keep polling
        last_err = f"status={status}"
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def generate_one(
    client: httpx.AsyncClient,
    prompt: str,
    *,
    quality: str,
    model: str,
    base_url: str,
) -> tuple[bytes, str]:
    """Submit a draw task, poll until done, return (image_bytes, task_id)."""
    task_id = await _submit_task(
        client, base_url=base_url, prompt=prompt, quality=quality, model=model
    )
    image_url = await _poll_result(client, base_url=base_url, task_id=task_id)
    img = await client.get(image_url, timeout=60.0)
    img.raise_for_status()
    return img.content, task_id


def to_jpeg_512(png_bytes: bytes) -> bytes:
    """Resize PNG → 512×512 JPEG q85, white background flatten."""
    src = Image.open(io.BytesIO(png_bytes))
    if src.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", src.size, (245, 242, 236))  # off-white
        bg.paste(src, mask=src.split()[-1])
        src = bg
    elif src.mode != "RGB":
        src = src.convert("RGB")
    src = src.resize((512, 512), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    src.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------- main

def collect_jobs(
    guides: dict,
    *,
    only_family: str | None,
    only_section: str | None,
) -> list[dict]:
    """Walk YAML and yield jobs: one per bullet that needs a picture.

    Each job carries a reference to the live YAML node (the dict or the
    enclosing list+index), so after generation we can mutate it in place.
    """
    jobs: list[dict] = []
    rec_root = guides.get("recommendation_guides") or guides
    if not isinstance(rec_root, dict):
        return jobs

    for family, bundle in rec_root.items():
        if only_family and family != only_family:
            continue
        if not isinstance(bundle, dict):
            continue
        sections = bundle.get("sections") or []
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_key = str(section.get("key") or "").strip()
            if not section_key:
                continue
            if only_section and section_key != only_section:
                continue
            for list_key in ("recommended", "avoid"):
                bullets = section.get(list_key)
                if not isinstance(bullets, list):
                    continue
                taken_slugs: set[str] = set()
                for i, bullet in enumerate(bullets):
                    text = (
                        bullet.get("text") if isinstance(bullet, dict) else bullet
                    )
                    text = str(text or "").strip()
                    if not text:
                        continue
                    existing_slug = (
                        bullet.get("slug") if isinstance(bullet, dict) else None
                    )
                    existing_image = (
                        bullet.get("image") or bullet.get("image_url")
                        if isinstance(bullet, dict)
                        else None
                    )
                    if existing_slug:
                        taken_slugs.add(existing_slug)
                    slug = existing_slug or make_unique(slugify(text), taken_slugs)
                    rel_path = f"{URL_PREFIX}/{family}/{section_key}/{slug}.jpg"
                    abs_path = PUBLIC_DIR / family / section_key / f"{slug}.jpg"
                    skip = bool(existing_image) and abs_path.exists()
                    jobs.append(
                        {
                            "family": family,
                            "section": section_key,
                            "list_key": list_key,
                            "index": i,
                            "text": text,
                            "slug": slug,
                            "rel_path": rel_path,
                            "abs_path": abs_path,
                            "bullet": bullet,
                            "bullets": bullets,
                            "skip": skip,
                        }
                    )
    return jobs


def write_back_yaml(yaml: YAML, guides: dict, path: Path, jobs: list[dict]) -> None:
    """Mutate the YAML tree so each generated bullet becomes a {text, slug, image} dict."""
    for job in jobs:
        if job.get("skip") or not job.get("done"):
            continue
        bullet = job["bullet"]
        if isinstance(bullet, dict):
            bullet["text"] = job["text"]
            bullet["slug"] = job["slug"]
            bullet["image"] = job["rel_path"]
        else:
            new_node = {
                "text": job["text"],
                "slug": job["slug"],
                "image": job["rel_path"],
            }
            job["bullets"][job["index"]] = new_node
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.dump(guides, f)


async def run_jobs(
    jobs: list[dict],
    *,
    concurrency: int,
    quality: str,
    api_key: str,
    base_url: str,
) -> int:
    """Execute pending jobs, return count of successfully generated images."""
    pending = [j for j in jobs if not j["skip"]]
    if not pending:
        print("Nothing to generate — every bullet already has an image.")
        return 0

    sem = asyncio.Semaphore(concurrency)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    succeeded = 0
    failed = 0
    moderation_blocked = 0

    async with httpx.AsyncClient(headers=headers) as client:

        async def worker(job: dict) -> None:
            nonlocal succeeded, failed, moderation_blocked
            async with sem:
                bullet = job["bullet"] if isinstance(job["bullet"], dict) else job["text"]
                prompt = build_prompt(bullet)
                t0 = time.perf_counter()
                # One retry on transient "error" — grsai docs explicitly recommend it.
                last_exc: Exception | None = None
                for attempt in range(2):
                    try:
                        png, task_id = await generate_one(
                            client,
                            prompt,
                            quality=quality,
                            model=DEFAULT_MODEL,
                            base_url=base_url,
                        )
                        jpeg = to_jpeg_512(png)
                        job["abs_path"].parent.mkdir(parents=True, exist_ok=True)
                        job["abs_path"].write_bytes(jpeg)
                        job["done"] = True
                        succeeded += 1
                        dt = time.perf_counter() - t0
                        print(
                            f"  ok  {job['family']}/{job['section']}/{job['list_key']}[{job['index']}] "
                            f"→ {job['slug']}.jpg ({len(jpeg)//1024}kB, {dt:.1f}s, task={task_id[:8]})"
                        )
                        return
                    except _ModerationBlocked as e:
                        moderation_blocked += 1
                        print(
                            f"  MOD {job['family']}/{job['section']}/{job['list_key']}[{job['index']}] "
                            f"({job['text'][:40]}…): {e}",
                            file=sys.stderr,
                        )
                        return
                    except Exception as e:
                        last_exc = e
                        if attempt == 0:
                            await asyncio.sleep(2.0)
                            continue
                failed += 1
                print(
                    f"  ERR {job['family']}/{job['section']}/{job['list_key']}[{job['index']}] "
                    f"({job['text'][:40]}…): {last_exc}",
                    file=sys.stderr,
                )

        await asyncio.gather(*(worker(j) for j in pending))

    print(
        f"\nDone: {succeeded} generated, {failed} failed, "
        f"{moderation_blocked} moderation-blocked, "
        f"{len(jobs) - len(pending)} skipped."
    )
    return succeeded


def _load_env_file(path: Path) -> None:
    """Minimal .env loader — sets missing vars from a KEY=VALUE file.

    Avoids pulling in python-dotenv. Skips empty lines and ``#`` comments.
    Existing environment values take precedence so ``$env:GRSAI_API_KEY``
    can still override the file at the shell.
    """
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


def main() -> int:
    # Force UTF-8 stdout/stderr so Cyrillic text and arrows print on Windows.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    # Pull GRSAI_API_KEY etc. out of the gitignored .env so users don't have
    # to remember to ``set``/``export`` it for every shell.
    _load_env_file(REPO_ROOT / "ai-stylist-starter" / ".env")

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--family", choices=KIBBE_FAMILIES, default=None)
    p.add_argument("--section", default=None, help="e.g. lines_silhouette")
    p.add_argument("--limit", type=int, default=None, help="cap pending jobs (smoke tests)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--quality",
        choices=("low", "medium", "high", "auto"),
        default="medium",
    )
    args = p.parse_args()

    if not YAML_PATH.exists():
        print(f"YAML not found: {YAML_PATH}", file=sys.stderr)
        return 1

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    with YAML_PATH.open(encoding="utf-8") as f:
        guides = yaml.load(f)

    jobs = collect_jobs(guides, only_family=args.family, only_section=args.section)
    if not jobs:
        print("No bullets matched the filters.")
        return 0

    pending = [j for j in jobs if not j["skip"]]
    skipped = len(jobs) - len(pending)

    print(f"Bullets: {len(jobs)}  pending: {len(pending)}  skipped (already done): {skipped}")
    if pending:
        sample = pending[0]
        print(f"Example: {sample['family']}/{sample['section']}/{sample['list_key']}[{sample['index']}] "
              f"  text=«{sample['text'][:60]}»  → {sample['rel_path']}")

    # Apply --limit *after* skip filtering so smoke tests don't waste budget
    # on already-done bullets.
    if args.limit:
        kept = 0
        for j in jobs:
            if j["skip"]:
                continue
            kept += 1
            if kept > args.limit:
                j["skip"] = True

    if args.dry_run:
        print("\n[dry-run] no API calls, no files written.")
        return 0

    api_key = os.environ.get("GRSAI_API_KEY")
    if not api_key:
        print("GRSAI_API_KEY env var is missing — required for image generation.", file=sys.stderr)
        return 1
    base_url = os.environ.get("GRSAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    print(f"Provider: grsai.ai  base={base_url}  key=…{api_key[-4:]}")

    asyncio.run(
        run_jobs(
            jobs,
            concurrency=args.concurrency,
            quality=args.quality,
            api_key=api_key,
            base_url=base_url,
        )
    )

    write_back_yaml(yaml, guides, YAML_PATH, jobs)
    print(f"YAML updated: {YAML_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
