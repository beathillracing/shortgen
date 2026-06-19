from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.config import settings


def _month_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _provider_result(
    provider: str,
    *,
    status: str,
    source: str,
    spent_usd: float | None = None,
    budget_usd: float = 0.0,
    message: str = "",
) -> dict:
    remaining_usd = None
    if spent_usd is not None and budget_usd > 0:
        remaining_usd = max(budget_usd - spent_usd, 0.0)

    return {
        "provider": provider,
        "status": status,
        "source": source,
        "spent_usd": spent_usd,
        "budget_usd": budget_usd if budget_usd > 0 else None,
        "remaining_usd": remaining_usd,
        "credit_balance_usd": None,
        "credit_balance_available": False,
        "message": message,
    }


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            return "Admin key is missing required billing/usage permissions."
        if status_code == 404:
            return "Billing endpoint was not available for this account/key."
        return f"Provider returned HTTP {status_code}."
    return str(exc)


def _sum_openai_costs(payload: dict) -> float:
    total = 0.0
    for bucket in payload.get("data", []):
        for row in bucket.get("results", []):
            total += _to_float(row.get("amount", {}).get("value"))
    return total


def _fetch_openai_spend(start: datetime, end: datetime) -> dict:
    key = settings.openai_admin_key or (
        settings.openai_api_key if settings.openai_api_key.startswith("sk-admin-") else ""
    )
    budget = settings.openai_monthly_budget_usd

    if not key:
        return _provider_result(
            "OpenAI",
            status="setup_needed",
            source="Admin Costs API",
            budget_usd=budget,
            message="Set OPENAI_ADMIN_KEY to enable monthly spend polling.",
        )

    params = {
        "start_time": int(start.timestamp()),
        "end_time": int(end.timestamp()),
        "bucket_width": "1d",
        "limit": 31,
    }

    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(
                "https://api.openai.com/v1/organization/costs",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                params=params,
            )
            response.raise_for_status()
        return _provider_result(
            "OpenAI",
            status="ok",
            source="Admin Costs API",
            spent_usd=_sum_openai_costs(response.json()),
            budget_usd=budget,
        )
    except Exception as exc:
        return _provider_result(
            "OpenAI",
            status="error",
            source="Admin Costs API",
            budget_usd=budget,
            message=_safe_error_message(exc),
        )


def _anthropic_amount_to_usd(value: Any) -> float:
    try:
        cents = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0
    return float(cents / Decimal("100"))


def _sum_anthropic_costs(payload: dict) -> float:
    total = 0.0
    for bucket in payload.get("data", []):
        for row in bucket.get("results", []):
            total += _anthropic_amount_to_usd(row.get("amount"))
    return total


def _fetch_anthropic_spend(start: datetime, end: datetime) -> dict:
    key = settings.anthropic_admin_key
    budget = settings.anthropic_monthly_budget_usd

    if not key:
        return _provider_result(
            "Anthropic",
            status="setup_needed",
            source="Admin Cost Report",
            budget_usd=budget,
            message="Set ANTHROPIC_ADMIN_KEY to enable monthly spend polling.",
        )

    params = {
        "starting_at": start.isoformat().replace("+00:00", "Z"),
        "ending_at": end.isoformat().replace("+00:00", "Z"),
        "bucket_width": "1d",
        "limit": 31,
    }

    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(
                "https://api.anthropic.com/v1/organizations/cost_report",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                params=params,
            )
            response.raise_for_status()
        return _provider_result(
            "Anthropic",
            status="ok",
            source="Admin Cost Report",
            spent_usd=_sum_anthropic_costs(response.json()),
            budget_usd=budget,
            message="Anthropic does not expose current prepaid credit balance through the public Admin API; available credits are shown in Console Billing.",
        )
    except Exception as exc:
        return _provider_result(
            "Anthropic",
            status="error",
            source="Admin Cost Report",
            budget_usd=budget,
            message=_safe_error_message(exc),
        )


def _groq_status() -> dict:
    return _provider_result(
        "Groq",
        status="dashboard_only",
        source="Groq Console",
        budget_usd=settings.groq_monthly_budget_usd,
        message="Groq exposes usage in the console and spend alerts; ShortGen is not polling a public billing API for Groq.",
    )


def get_billing_status() -> dict:
    start, end = _month_bounds()
    return {
        "period_start": start.isoformat().replace("+00:00", "Z"),
        "period_end": end.isoformat().replace("+00:00", "Z"),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "providers": [
            _fetch_anthropic_spend(start, end),
        ],
    }
