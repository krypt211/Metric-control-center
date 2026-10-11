"""The fail-closed gate shared by every advertising WRITE boundary."""

from __future__ import annotations

import os

from services.providers.contracts import WriteDisabled


class ActionSafetyGate:
    @staticmethod
    def allowed() -> bool:
        return (
            os.environ.get("ACTIONS_ENABLED", "false").lower() == "true"
            and os.environ.get("LOCAL_READ_ONLY", "true").lower() == "false"
        )

    @staticmethod
    def require_verified_contract() -> None:
        """No LIVE adapter has an accepted provider contract in this phase."""
        raise WriteDisabled("WRITE_CONTRACT_UNVERIFIED")

    @classmethod
    def require_write(cls) -> None:
        if not cls.allowed():
            raise WriteDisabled()
        cls.require_verified_contract()
