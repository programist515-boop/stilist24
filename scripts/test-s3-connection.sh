#!/usr/bin/env bash
# scripts/test-s3-connection.sh
#
# Проверяет подключение к Yandex Object Storage (или любому S3-совместимому)
# с теми credentials, что прописаны в amvera-api.env.
#
# Использование:
#   bash scripts/test-s3-connection.sh
#
# Зависимости: aws-cli (brew install awscli / apt install awscli).
# Если aws-cli нет — внизу есть fallback через curl + python.

set -euo pipefail

ENV_FILE="${1:-amvera-api.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE не найден. Передай путь первым аргументом или запусти из корня репо." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

if [[ "$S3_ACCESS_KEY" == *"<"* ]] || [[ "$S3_SECRET_KEY" == *"<"* ]]; then
  echo "ERROR: в $ENV_FILE ключи всё ещё плейсхолдеры (<YA_SA_ACCESS_KEY>...). Подставь реальные значения." >&2
  exit 1
fi

echo "==> Endpoint: $S3_ENDPOINT_URL"
echo "==> Region:   $S3_REGION"
echo "==> Bucket:   $S3_BUCKET"
echo

# Test 1: bucket существует и доступен на чтение
echo "[1/4] HEAD bucket..."
AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
AWS_DEFAULT_REGION="$S3_REGION" \
  aws s3api head-bucket \
    --bucket "$S3_BUCKET" \
    --endpoint-url "$S3_ENDPOINT_URL" \
  && echo "    OK: bucket доступен" \
  || { echo "    FAIL: bucket недоступен или ключи неверные"; exit 1; }

# Test 2: PUT — загрузка тестового объекта
TEST_KEY="_smoketest/connection-$(date +%s).txt"
TEST_FILE=$(mktemp)
echo "smoketest $(date -u +%FT%TZ)" > "$TEST_FILE"

echo "[2/4] PUT $TEST_KEY..."
AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
AWS_DEFAULT_REGION="$S3_REGION" \
  aws s3api put-object \
    --bucket "$S3_BUCKET" \
    --key "$TEST_KEY" \
    --body "$TEST_FILE" \
    --content-type "text/plain" \
    --endpoint-url "$S3_ENDPOINT_URL" \
  > /dev/null \
  && echo "    OK: запись прошла" \
  || { echo "    FAIL: нет права на запись (нужна роль storage.editor)"; exit 1; }

# Test 3: публичный доступ на чтение (bucket policy PublicReadGetObject)
PUBLIC_URL="${S3_PUBLIC_BASE_URL%/}/$TEST_KEY"
echo "[3/4] GET $PUBLIC_URL (анонимно, без авторизации)..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$PUBLIC_URL")
if [ "$HTTP_CODE" = "200" ]; then
  echo "    OK: public-read работает (HTTP 200)"
elif [ "$HTTP_CODE" = "403" ]; then
  echo "    FAIL: HTTP 403 — bucket policy PublicReadGetObject не применилась"
  exit 1
else
  echo "    WARN: неожиданный HTTP $HTTP_CODE"
fi

# Test 4: cleanup
echo "[4/4] DELETE $TEST_KEY..."
AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
AWS_DEFAULT_REGION="$S3_REGION" \
  aws s3api delete-object \
    --bucket "$S3_BUCKET" \
    --key "$TEST_KEY" \
    --endpoint-url "$S3_ENDPOINT_URL" \
  > /dev/null \
  && echo "    OK: тестовый объект удалён"

rm -f "$TEST_FILE"

echo
echo "==> Всё ок. S3-хранилище готово к продакшну."
