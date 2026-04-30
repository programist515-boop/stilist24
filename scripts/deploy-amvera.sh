#!/usr/bin/env bash
# Deploy stilist24 apps to Amvera Cloud via git subtree push.
#
# Usage:
#   ./scripts/deploy-amvera.sh api     # deploy backend only
#   ./scripts/deploy-amvera.sh web     # deploy frontend only
#   ./scripts/deploy-amvera.sh all     # deploy both
#   ./scripts/deploy-amvera.sh setup   # add Amvera git remotes (one-time)
#
# Prerequisites:
#   1. Apps created in Amvera UI (stilist24-api, stilist24-web)
#   2. Env vars set in Amvera UI for each app
#   3. Git remotes added (run: ./scripts/deploy-amvera.sh setup)

set -euo pipefail

AMVERA_USER="${AMVERA_USER:-expertgds}"
API_DIR="ai-stylist-starter"
WEB_DIR="frontend"
API_REMOTE="amvera-api"
WEB_REMOTE="amvera-web"
API_DOMAIN="stilist24-api-${AMVERA_USER}.amvera.io"
WEB_DOMAIN="stilist24-web-${AMVERA_USER}.amvera.io"

setup_remotes() {
  echo "=== Setting up Amvera git remotes ==="
  local api_url="https://git.amvera.ru/${AMVERA_USER}/stilist24-api"
  local web_url="https://git.amvera.ru/${AMVERA_USER}/stilist24-web"

  if git remote get-url "$API_REMOTE" &>/dev/null; then
    echo "  Remote $API_REMOTE already exists: $(git remote get-url $API_REMOTE)"
  else
    git remote add "$API_REMOTE" "$api_url"
    echo "  Added remote $API_REMOTE → $api_url"
  fi

  if git remote get-url "$WEB_REMOTE" &>/dev/null; then
    echo "  Remote $WEB_REMOTE already exists: $(git remote get-url $WEB_REMOTE)"
  else
    git remote add "$WEB_REMOTE" "$web_url"
    echo "  Added remote $WEB_REMOTE → $web_url"
  fi

  echo "Done. Amvera will ask for credentials on first push."
}

deploy_app() {
  local dir="$1"
  local remote="$2"
  local name="$3"

  echo ""
  echo "=== Deploying $name ($dir → $remote) ==="

  # Ensure all changes are committed
  if ! git diff --quiet HEAD -- "$dir"; then
    echo "ERROR: uncommitted changes in $dir. Commit first."
    exit 1
  fi

  # Split subtree into a temporary branch
  local branch="amvera-deploy-${name}"
  echo "  Splitting subtree $dir → branch $branch ..."
  git subtree split --prefix="$dir" -b "$branch"

  # Push to Amvera (force to handle rebased history from split)
  echo "  Pushing $branch → $remote master ..."
  git push "$remote" "${branch}:master" --force

  # Clean up temporary branch
  git branch -D "$branch"

  echo "  Done. Build logs: https://cloud.amvera.ru"
}

smoke_test() {
  local domain="$1"
  local name="$2"
  local url="https://${domain}"

  echo ""
  echo "=== Smoke test: $name ($url) ==="

  local max_wait=180
  local interval=15
  local elapsed=0

  while [ $elapsed -lt $max_wait ]; do
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" "${url}/health" 2>/dev/null || echo "000")
    if [ "$status" = "200" ]; then
      echo "  PASS: ${url}/health → 200"
      return 0
    fi
    echo "  Waiting... (${elapsed}s / ${max_wait}s, last status: $status)"
    sleep "$interval"
    elapsed=$((elapsed + interval))
  done

  echo "  FAIL: ${url}/health did not return 200 within ${max_wait}s"
  return 1
}

case "${1:-help}" in
  setup)
    setup_remotes
    ;;
  api)
    deploy_app "$API_DIR" "$API_REMOTE" "api"
    echo ""
    echo "Waiting for Amvera build + deploy..."
    smoke_test "$API_DOMAIN" "api"
    ;;
  web)
    deploy_app "$WEB_DIR" "$WEB_REMOTE" "web"
    echo ""
    echo "Waiting for Amvera build + deploy..."
    echo "  (frontend has no /health — check https://${WEB_DOMAIN}/ manually)"
    ;;
  all)
    deploy_app "$API_DIR" "$API_REMOTE" "api"
    deploy_app "$WEB_DIR" "$WEB_REMOTE" "web"
    echo ""
    echo "Waiting for Amvera builds..."
    smoke_test "$API_DOMAIN" "api"
    echo ""
    echo "Check frontend: https://${WEB_DOMAIN}/"
    ;;
  help|*)
    echo "Usage: $0 {setup|api|web|all}"
    echo ""
    echo "  setup  — add Amvera git remotes (one-time)"
    echo "  api    — deploy backend + smoke test"
    echo "  web    — deploy frontend"
    echo "  all    — deploy both + smoke test"
    exit 1
    ;;
esac
