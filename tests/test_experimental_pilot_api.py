"""Private READ-only preparation still requires real admin sessions and CSRF."""

from unittest.mock import AsyncMock, patch

import httpx
from test_auth import AuthTests

from services.actions import credential_service as service
from services.actions.experimental import PREPARE


class ExperimentalPrivateApiTests(AuthTests):
    async def test_preparation_auth_and_statement_are_independent_of_live_flags(self):
        payload = {
            "entity_id": "ad",
            "credential_revision": 1,
            "management_confirmed": True,
            "statement": PREPARE,
        }
        with (
            patch.dict(
                "os.environ",
                {
                    "APP_ORIGIN": "http://127.0.0.1:3001",
                    "ACTIONS_ENABLED": "false",
                    "LOCAL_READ_ONLY": "true",
                },
            ),
            patch.object(service, "factory", return_value=self.sessions),
            patch.object(
                service, "check_stored_credential", new_callable=AsyncMock
            ) as check,
            patch.object(
                service,
                "prepare_experiment",
                new_callable=AsyncMock,
                return_value={"status": "PREPARED_NO_POST_AUTHORIZATION"},
            ) as prepare,
            patch.object(service, "vault"),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=service.app), base_url="http://test"
            ) as client:
                path = "/controlled-pilot-experimental/prepare"
                assert (await client.post(path, json=payload)).status_code == 401
                for role in ("viewer", "operator"):
                    await self.login(role)
                    client.cookies.update(self.client.cookies)
                    assert (
                        await client.post(path, json=payload, headers=await self.csrf())
                    ).status_code == 403
                await self.login("admin")
                client.cookies.update(self.client.cookies)
                assert (await client.post(path, json=payload)).status_code == 403
                assert (
                    await client.post(
                        path,
                        json={**payload, "statement": "AUTHORIZE_POST"},
                        headers=await self.csrf(),
                    )
                ).status_code == 422
                assert (
                    await client.post(
                        path,
                        json={**payload, "baseline": {}},
                        headers=await self.csrf(),
                    )
                ).status_code == 422
                check.assert_not_called()
                prepare.assert_not_called()
                response = await client.post(
                    path, json=payload, headers=await self.csrf()
                )
                assert (
                    response.status_code == 200
                    and response.json()["status"] == "PREPARED_NO_POST_AUTHORIZATION"
                )
                assert check.await_count == prepare.await_count == 1
