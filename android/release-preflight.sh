#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

required_env=(
    GOOGLE_WEB_CLIENT_ID
    GOOGLE_PLAY_SERVICE_ACCOUNT_FILE
    GOOGLE_PLAY_PACKAGE_NAME
    GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID
    META_APP_ID
    META_APP_SECRET
    INSTAGRAM_APP_ID
    INSTAGRAM_APP_SECRET
    TIKTOK_CLIENT_KEY
    TIKTOK_CLIENT_SECRET
)

for name in "${required_env[@]}"; do
    if ! grep -Eq "^${name}=.+" .env; then
        echo "Missing required setting: ${name}" >&2
        exit 1
    fi
done

git diff --check
/var/www/shortgen/venv/bin/python -m compileall -q app
systemctl is-active --quiet shortgen
systemctl is-active --quiet shortgen-worker

/var/www/shortgen/venv/bin/python - <<'PY'
from app.config import settings
from app.main import app
from app.services.mobile_accounts import _publisher_service

routes = {route.path for route in app.routes}
required = {
    "/api/mobile/account",
    "/api/mobile/billing/verify",
    "/api/mobile/connections",
    "/api/mobile/connections/{provider}/auth",
    "/api/instagram/callback",
    "/api/instagram/deauthorize",
    "/api/instagram/data-deletion",
}
missing = sorted(required - routes)
if missing:
    raise SystemExit(f"Missing API routes: {', '.join(missing)}")

service = _publisher_service()
try:
    service.monetization().subscriptions().get(
        packageName=settings.google_play_package_name,
        productId=settings.google_play_subscription_product_id,
    ).execute()
except Exception as exc:
    raise SystemExit(
        "Google Play subscription is unavailable. Create and activate "
        f"{settings.google_play_subscription_product_id}: {exc}"
    )
PY

curl -fsS https://shortgen.beathillracing.fi/public/privacy >/dev/null
curl -fsS https://shortgen.beathillracing.fi/public/terms >/dev/null

cd android
./build-play.sh

echo "Release preflight passed."
