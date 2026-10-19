"""Private pilot routes: real session/CSRF checks, closed gates, zero provider HTTP."""

from datetime import UTC, datetime
from unittest.mock import patch

import httpx
from test_auth import AuthTests

from services.actions import credential_service as service


class PilotPrivateApiTests(AuthTests):
    async def test_private_pilot_routes_require_admin_csrf_and_cannot_open_vault(self):
        bodies = {
            "authorize": {
                "revision": 1,
                "credential_revision": 1,
                "account_id": "act_100",
                "entity_id": "1003",
                "operation": "PAUSE_AD",
                "expected_status": "ACTIVE",
                "statement": "AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST",
            },
            "execute": {"revision": 1},
            "readback": {
                "revision": 1,
                "account_id": "act_100",
                "entity_id": "1003",
                "configured_status": "PAUSED",
                "effective_status": "PAUSED",
                "observed_at": datetime.now(UTC).isoformat(),
                "statement": "RECORD_MANUAL_META_READBACK",
            },
        }
        with (
            patch.dict("os.environ", {"APP_ORIGIN": "http://127.0.0.1:3001"}),
            patch.object(service, "factory", return_value=self.sessions),
            patch.object(service, "vault") as vault,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=service.app), base_url="http://test"
            ) as private:
                for operation, body in bodies.items():
                    path = f"/controlled-pilot/missing/{operation}"
                    response = await private.post(path, json=body)
                    assert response.status_code == 401
                for role in ("viewer", "operator"):
                    await self.login(role)
                    private.cookies.update(self.client.cookies)
                    for operation, body in bodies.items():
                        response = await private.post(
                            f"/controlled-pilot/missing/{operation}",
                            json=body,
                            headers=await self.csrf(),
                        )
                        assert response.status_code == 403
                await self.login("admin")
                private.cookies.update(self.client.cookies)
                for operation, body in bodies.items():
                    path = f"/controlled-pilot/missing/{operation}"
                    assert (await private.post(path, json=body)).status_code == 403
                    response = await private.post(
                        path, json=body, headers=await self.csrf()
                    )
                    assert response.status_code == 409
                    if operation != "readback":
                        assert response.json()["detail"] == "WRITE_DISABLED"
                extra = {**bodies["execute"], "allow_write": True}
                assert (
                    await private.post(
                        "/controlled-pilot/missing/execute",
                        json=extra,
                        headers=await self.csrf(),
                    )
                ).status_code == 422
            vault.assert_not_called()
