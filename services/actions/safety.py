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
    def require_verified_contract(contract=None) -> None:
        """Only a private, request-bound contract can release this boundary."""
        from services.actions.pilot_contract import PilotContract

        if type(contract) is not PilotContract:
            raise WriteDisabled("WRITE_CONTRACT_UNVERIFIED")
        contract.verify()

    @classmethod
    def require_write(cls, contract=None) -> None:
        if not cls.allowed():
            raise WriteDisabled()
        if contract is None:
            cls.require_verified_contract()
        else:
            cls.require_verified_contract(contract)
