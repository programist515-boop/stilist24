#!/usr/bin/env bash
# Generate random secrets for production rotation.
#
# The production .env.prod is written by GitHub Actions from repository
# secrets on every push (see .github/workflows/deploy.yml). This script
# produces new values you can paste into GitHub → Settings → Secrets
# when rotating (JWT compromise, employee offboarding, annual policy,
# etc.). It does NOT write a .env.prod file anywhere — paste into
# GitHub, let the next push redeploy.
#
#   ./scripts/generate-secrets.sh
#
# Nothing here depends on GNU coreutils — portable across any modern
# Linux or macOS box with OpenSSL.
set -euo pipefail

# 32-char URL-safe token. openssl is present on every server image that
# has Docker, so we don't add another dep.
rand() {
  local bytes="${1:-32}"
  openssl rand -base64 "$((bytes * 3 / 4 + 3))" | tr -d '+/=\n' | cut -c -"$bytes"
}

cat <<EOF
# --- rotation set ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ---
# Paste each value into GitHub → Settings → Secrets → Actions.
# Rotating POSTGRES_PASSWORD also requires a DB password change on the
# server before the next deploy, or connections will fail.
POSTGRES_PASSWORD=$(rand 32)
S3_ACCESS_KEY=$(rand 24)
S3_SECRET_KEY=$(rand 40)
JWT_SECRET=$(rand 64)
EOF
