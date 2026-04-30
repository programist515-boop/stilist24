"""Smoke-test S3-подключения для Yandex Object Storage (или любого S3-совместимого).

Использование:
    python scripts/test_s3_connection.py [path/to/env-file]

По умолчанию читает amvera-api.env из корня репо.

Зависимости: boto3 (уже в pyproject.toml). Если запускаешь вне venv —
    pip install boto3 python-dotenv

Что проверяет (4 гейта):
  1. HEAD bucket — credentials валидны, bucket существует.
  2. PUT тестового объекта — у service account есть storage.editor.
  3. GET по публичному URL без авторизации — bucket policy PublicReadGetObject применилась.
  4. DELETE — cleanup.

Exit code: 0 при полном успехе, 1 при любом фейле.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path


def _load_env(env_path: Path) -> dict[str, str]:
    """Минимальный парсер .env — без python-dotenv, чтобы не тащить зависимость."""
    env: dict[str, str] = {}
    if not env_path.exists():
        print(f"ERROR: {env_path} не найден", file=sys.stderr)
        sys.exit(1)
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _require(env: dict[str, str], key: str) -> str:
    val = env.get(key, "")
    if not val or "<" in val:
        print(f"ERROR: {key} не задан или плейсхолдер ({val!r})", file=sys.stderr)
        sys.exit(1)
    return val


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    env_path = Path(sys.argv[1]) if len(sys.argv) > 1 else repo_root / "amvera-api.env"
    env = _load_env(env_path)

    endpoint = _require(env, "S3_ENDPOINT_URL")
    region = _require(env, "S3_REGION")
    access_key = _require(env, "S3_ACCESS_KEY")
    secret_key = _require(env, "S3_SECRET_KEY")
    bucket = _require(env, "S3_BUCKET")
    public_base = env.get("S3_PUBLIC_BASE_URL", "").rstrip("/")
    force_path_style = env.get("S3_FORCE_PATH_STYLE", "true").lower() == "true"

    print(f"==> Endpoint: {endpoint}")
    print(f"==> Region:   {region}")
    print(f"==> Bucket:   {bucket}")
    print(f"==> Public:   {public_base or '(presigned URLs)'}")
    print()

    try:
        import boto3
        from botocore.client import Config
        from botocore.exceptions import ClientError
    except ImportError:
        print("ERROR: boto3 не установлен. pip install boto3", file=sys.stderr)
        return 1

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            s3={"addressing_style": "path" if force_path_style else "auto"},
            signature_version="s3v4",
        ),
    )

    # [1/4] HEAD bucket
    print("[1/4] HEAD bucket...")
    try:
        client.head_bucket(Bucket=bucket)
        print("    OK: bucket доступен")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "?")
        print(f"    FAIL: {code} — {exc}", file=sys.stderr)
        if code in ("404", "NoSuchBucket"):
            print(f"    подсказка: bucket {bucket!r} не существует — создай в Yandex Console", file=sys.stderr)
        if code in ("403", "Forbidden", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            print("    подсказка: ключи неверные или у SA нет доступа к bucket", file=sys.stderr)
        return 1

    # [2/4] PUT
    test_key = f"_smoketest/connection-{int(time.time())}.txt"
    body = f"smoketest {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}".encode()
    print(f"[2/4] PUT {test_key}...")
    try:
        client.put_object(Bucket=bucket, Key=test_key, Body=body, ContentType="text/plain")
        print("    OK: запись прошла (роль storage.editor работает)")
    except ClientError as exc:
        print(f"    FAIL: {exc}", file=sys.stderr)
        print("    подсказка: проверь роль SA — нужна storage.editor", file=sys.stderr)
        return 1

    # [3/4] GET анонимно по public URL
    if public_base:
        public_url = f"{public_base}/{test_key}"
        print(f"[3/4] GET {public_url} (анонимно)...")
        try:
            with urllib.request.urlopen(public_url, timeout=10) as resp:
                if resp.status == 200:
                    print("    OK: public-read работает (HTTP 200)")
                else:
                    print(f"    WARN: HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                print("    FAIL: HTTP 403 — bucket policy PublicReadGetObject не применилась", file=sys.stderr)
                print("    подсказка: проверь Object Storage → bucket → Политика доступа", file=sys.stderr)
                client.delete_object(Bucket=bucket, Key=test_key)  # cleanup
                return 1
            print(f"    WARN: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        except Exception as exc:
            print(f"    WARN: {exc}", file=sys.stderr)
    else:
        print("[3/4] SKIP: S3_PUBLIC_BASE_URL не задан — public-read не проверяется")

    # [4/4] DELETE
    print(f"[4/4] DELETE {test_key}...")
    try:
        client.delete_object(Bucket=bucket, Key=test_key)
        print("    OK: тестовый объект удалён")
    except ClientError as exc:
        print(f"    WARN: cleanup не прошёл — {exc}", file=sys.stderr)

    print()
    print("==> Все 4 гейта пройдены. S3-хранилище готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
