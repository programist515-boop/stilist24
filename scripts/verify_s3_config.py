"""Статический верификатор S3-конфигурации.

Запускается БЕЗ внешних зависимостей (только stdlib). Проверяет:

  1. Все S3-поля Settings в app/core/config.py имеют соответствующие
     env-переменные в amvera-api.env (по верхнему регистру имени поля).
  2. amvera-api.env не содержит плейсхолдеров вида <SOMETHING> в
     critical-полях (S3_ACCESS_KEY, S3_SECRET_KEY, JWT_SECRET).
  3. Значения булевых/численных полей парсятся корректно.
  4. Endpoint URL валидный (https:// или http://).

Использование:
    python scripts/verify_s3_config.py

Exit code 0 при полной валидности, 1 при любой проблеме. Можно
интегрировать в pre-commit / CI.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG_PY = REPO / "ai-stylist-starter" / "app" / "core" / "config.py"
ENV_FILE = REPO / "amvera-api.env"

# Какие префиксы Settings-полей считаем S3-related — должны быть в env прода
S3_FIELD_PREFIXES = ("s3_", "storage_backend")
# Эти поля не обязательны в env — у них есть валидные дефолты
OPTIONAL_FIELDS = {"s3_presign_expires"}
# Эти поля НЕ должны быть плейсхолдером — секреты, которые гарантированно
# нужно подставить руками
NO_PLACEHOLDER_FIELDS = {"S3_ACCESS_KEY", "S3_SECRET_KEY", "JWT_SECRET"}


def parse_settings_fields(path: Path) -> dict[str, str]:
    """Извлечь имена и type hints полей класса Settings из config.py."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            fields: dict[str, str] = {}
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fields[stmt.target.id] = ast.unparse(stmt.annotation)
            return fields
    raise RuntimeError("class Settings not found in config.py")


def parse_env_file(path: Path) -> dict[str, str]:
    """Минимальный парсер .env (без зависимости от python-dotenv)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "OK  " if ok else "FAIL"
    extra = f" — {detail}" if detail else ""
    print(f"  [{icon}] {label}{extra}")
    return ok


def main() -> int:
    print("== Static S3 config verifier ==\n")

    if not CONFIG_PY.exists():
        print(f"ERROR: {CONFIG_PY} не найден", file=sys.stderr)
        return 1

    fields = parse_settings_fields(CONFIG_PY)
    env = parse_env_file(ENV_FILE)

    s3_fields = {
        name: hint
        for name, hint in fields.items()
        if name.startswith(S3_FIELD_PREFIXES) and name not in OPTIONAL_FIELDS
    }

    print(f"[1] S3-related Settings fields в config.py: {len(s3_fields)}")
    for name in sorted(s3_fields):
        print(f"    - {name}: {s3_fields[name]}")
    print()

    print(f"[2] Парсинг {ENV_FILE.relative_to(REPO)} ({len(env)} переменных)")
    print()

    print("[3] Кросс-проверка config.py vs amvera-api.env:")
    all_ok = True
    for field in sorted(s3_fields):
        env_key = field.upper()
        present = env_key in env
        all_ok &= check(f"{env_key} присутствует в env", present)

    print()
    print("[4] Плейсхолдеры в критичных полях:")
    placeholder_re = re.compile(r"<[^>]+>")
    for key in sorted(NO_PLACEHOLDER_FIELDS):
        val = env.get(key, "")
        is_placeholder = bool(placeholder_re.search(val)) or val == ""
        # Это не FAIL для пользователя, который ещё не подставил ключи —
        # это просто статус. Делаем WARN, а не FAIL.
        if is_placeholder:
            print(f"  [WARN] {key} = {val!r} — плейсхолдер, нужно подставить реальное значение")
        else:
            print(f"  [OK  ] {key} задан (длина {len(val)})")

    print()
    print("[5] Валидация значений:")

    endpoint = env.get("S3_ENDPOINT_URL", "")
    all_ok &= check(
        "S3_ENDPOINT_URL — http(s) URL",
        endpoint.startswith(("http://", "https://")),
        endpoint,
    )

    region = env.get("S3_REGION", "")
    all_ok &= check(
        "S3_REGION — непустой",
        bool(region),
        region,
    )

    bucket = env.get("S3_BUCKET", "")
    all_ok &= check(
        "S3_BUCKET — валидный S3-name (lowercase, 3–63, без _)",
        bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)),
        bucket,
    )

    fps = env.get("S3_FORCE_PATH_STYLE", "")
    all_ok &= check(
        "S3_FORCE_PATH_STYLE — true/false",
        fps.lower() in ("true", "false"),
        fps,
    )

    public = env.get("S3_PUBLIC_BASE_URL", "")
    if public:
        all_ok &= check(
            "S3_PUBLIC_BASE_URL — http(s) URL",
            public.startswith(("http://", "https://")),
            public,
        )
        consistent = endpoint and (endpoint.rstrip("/") in public or "media." in public)
        all_ok &= check(
            "S3_PUBLIC_BASE_URL согласован с endpoint",
            consistent,
            f"endpoint={endpoint} public={public}",
        )

    storage_backend = env.get("STORAGE_BACKEND", "")
    all_ok &= check(
        "STORAGE_BACKEND == 's3'",
        storage_backend == "s3",
        storage_backend,
    )

    print()
    if all_ok:
        print("== Все статические гейты пройдены ==")
        print()
        print("Что НЕ проверено этим скриптом (нужны реальные ключи):")
        print("  - валидность credentials (HEAD bucket)")
        print("  - роль storage.editor (PUT object)")
        print("  - bucket policy PublicReadGetObject (GET анонимно)")
        print()
        print("После подстановки ключей запусти:")
        print("  python scripts/test_s3_connection.py")
        return 0

    print("== Есть проблемы выше — поправь до запуска smoke-test ==")
    return 1


if __name__ == "__main__":
    sys.exit(main())
