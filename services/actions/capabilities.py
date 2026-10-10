"""Documentation evidence is distinct from runtime WRITE verification."""

from __future__ import annotations

import os
from pathlib import Path

from services.providers.models import ProviderConnection

OPERATIONS = (
    "PAUSE_AD",
    "ENABLE_AD",
    "SET_ADSET_BUDGET",
    "SET_CAMPAIGN_BUDGET",
    "SET_BID",
)


class ActionCapabilityRegistry:
    @staticmethod
    def inspect(session, workspace: str, provider: str) -> dict:
        connection = session.get(ProviderConnection, (workspace, provider))
        # READ credential settings never confer WRITE access.
        path = (
            os.environ.get("METRICFLOW_WRITE_KEY_FILE")
            if provider == "metricflow"
            else None
        )
        write_credential = bool(path and Path(path).is_file())
        connected = bool(connection and connection.enabled)
        return {
            "provider": provider,
            "connected": connected,
            "health": connection.status if connection else "disconnected",
            "credential_revision": connection.revision if connection else None,
            "read_credentials": connected,
            "write_credentials": write_credential,
            "write_permission": False,
            "required_permission": "campaigns:write"
            if provider == "metricflow"
            else "ads_management",
            "operations": {key: "UNVERIFIED" for key in OPERATIONS},
            "live_status": "BLOCKED",
            "last_checked_at": connection.checked_at.isoformat()
            if connection and connection.checked_at
            else None,
            "last_error": connection.error_code
            if connection
            else "PROVIDER_DISCONNECTED",
            "rate_limits": connection.quota if connection else {},
            "reason_codes": ["WRITE_CONTRACT_UNVERIFIED", "WRITE_PERMISSION_UNVERIFIED"]
            + ([] if write_credential else ["WRITE_CREDENTIAL_MISSING"]),
        }


class MetricFlowActionProvider:
    name = "metricflow"


class MetaActionProvider:
    name = "meta"
