"""Explicit GET-only connectivity check. Output contains no raw provider data."""
import argparse
import asyncio
from datetime import date
import json
import os

from .errors import APIError, MetricFlowError, PermissionDenied
from .reader import MetricFlowConnector


def safe_error(error):
    if isinstance(error, APIError):
        return {401: "MetricFlow API key invalid or unauthorized", 403: "MetricFlow permissions denied. Use a READ key with analytics:read, ad_accounts:read and campaigns:read", 429: "MetricFlow rate limit reached", 402: "MetricFlow subscription is inactive"}.get(error.status_code, f"MetricFlow READ API failed (HTTP {error.status_code})")
    return {"QuotaExhausted": "Local MetricFlow request budget reached", "ConfigurationError": "MetricFlow READ key is missing or has an invalid format", "TransportUnavailable": "MetricFlow is unreachable", "InvalidResponse": "MetricFlow returned an unsupported response"}.get(type(error).__name__, "MetricFlow READ check failed; no secret or response body was logged")


def scope_check(payload):
    # Reject explicitly reported write privileges. Never log owner identity.
    scopes = payload.get("scopes") if isinstance(payload, dict) else None
    for key in ("data", "key", "api_key"):
        child = payload.get(key) if isinstance(payload, dict) else None
        if scopes is None and isinstance(child, dict):
            scopes = child.get("scopes")
    if isinstance(scopes, str):
        scopes = scopes.replace(",", " ").split()
    if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes):
        if any(s == "*" or s.endswith(":write") for s in scopes):
            raise PermissionDenied(403, "Use a separate READ-only key")
        return True
    return False


def account_count(payload):
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for name in ("total", "total_count", "count"):
            value = payload.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        candidates = [payload[k] for k in ("items", "accounts", "ad_accounts", "data") if isinstance(payload.get(k), list)]
        if len(candidates) == 1:
            return len(candidates[0])
        if isinstance(payload.get("data"), dict):
            return account_count(payload["data"])
    return None


def usage_summary(payload):
    if not isinstance(payload, dict):
        return "available (format not yet mapped)"
    safe = {}
    for name in ("used", "daily_used", "requests", "requests_used", "limit", "daily_limit", "remaining", "daily_remaining"):
        value = payload.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            safe[name] = value
    if not safe and isinstance(payload.get("data"), dict):
        return usage_summary(payload["data"])
    return json.dumps(safe) if safe else "available (format not yet mapped)"


async def check(connector):
    identity = await connector.get_me()
    permissions_confirmed = scope_check(identity)
    usage = await connector.get_usage()
    accounts = await connector.get_accounts()
    return {"accounts": accounts, "usage": usage, "permissions_confirmed": permissions_confirmed}


def print_summary(result):
    print("MetricFlow READ API: OK")
    count = account_count(result["accounts"])
    print(f"Accounts found (reported total or first page): {count if count is not None else 'UNKNOWN'}")
    print("API usage: " + usage_summary(result["usage"]))
    print("READ scopes: " + ("confirmed" if result["permissions_confirmed"] else "not reported; all requests remain GET-only"))


async def run(args):
    engine, budget = None, None
    if os.environ.get("POSTGRES_PASSWORD_FILE") or os.environ.get("DATABASE_URL"):
        from services.storage.database import make_engine, sessions
        from services.metricflow.local import ReadBudget
        engine = make_engine()
        budget = ReadBudget(sessions(engine))
    try:
        from .secrets import read_key_file
        async with MetricFlowConnector(read_key_file(os.environ.get("METRICFLOW_READ_KEY_FILE")), before_request=budget.reserve if budget else None) as connector:
            result = await check(connector)
            if args.summary:
                print_summary(result)
            else:
                for label in ("identity", "usage", "accounts"):
                    print(json.dumps({"check": label, "status": "ok"}))
            if args.start:
                await connector.get_insights(args.start, args.end)
                print(json.dumps({"check": "insights", "status": "ok"}))
    except Exception as error:
        from .errors import RateLimitExceeded
        if budget and isinstance(error, RateLimitExceeded):
            budget.block(error.retry_after_seconds)
        raise
    finally:
        if engine:
            engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Check MetricFlow READ access (3 or 4 GET calls)")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if bool(args.start) != bool(args.end):
        parser.error("Pass both --start and --end")
    if args.start and args.start > args.end:
        parser.error("--start must not exceed --end")
    print("MCC_APPLICATION_STARTED")
    try:
        asyncio.run(run(args))
    except Exception as error:
        code = 23 if type(error).__name__ in ("QuotaExhausted", "RateLimitExceeded") else 20
        parser.exit(code, safe_error(error)+"\n")


if __name__ == "__main__":
    main()
