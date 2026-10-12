"""Local target union, Unicode search, assignments, authorization and history."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from test_economics import ACTOR, NOW, EconomicsApiTests
from test_smart_rules import config, rule_store

from services.automation.smart_models import (
    RuleAuditLog,
    RuleSimulation,
    RuleVersion,
)
from services.automation.smart_schema import BulkTargets, RuleTarget
from services.automation.smart_simulation import simulate
from services.automation.smart_store import change_targets, save
from services.automation.smart_targets import (
    resolve_targets,
    search_catalog,
)
from services.storage.models import (
    ActionExecution,
    ActionRequest,
    Ad,
    Entity,
)

store = rule_store


def target(kind="CAMPAIGN", key="c", account="a", provider="metricflow", **extras):
    return RuleTarget(
        scope_type=kind, scope_id=key, account_id=account, provider=provider, **extras
    )


def command(revision, targets, operation="add"):
    return BulkTargets(revision=revision, targets=targets, operation=operation)


@pytest.mark.parametrize(
    "kind,key", [("ACCOUNT", "a"), ("CAMPAIGN", "c"), ("ADSET", "g"), ("AD", "d")]
)
def test_each_level_resolves_verified_children(store, kind, key):
    with store() as s:
        result = resolve_targets(s, "default", [target(kind, key)], NOW.date())
        assert result["total"] == 1
        assert result["provenance"][("metricflow", "a", "d")][0]["scope_type"] == kind
        assert result["issues"] == []


def test_overlap_union_and_new_ad_keep_all_origins(store):
    with store.begin() as s:
        targets = [target(), target("ADSET", "g"), target("AD", "d")]
        first = resolve_targets(s, "default", targets, NOW.date())
        assert (
            first["total"] == 1
            and len(first["provenance"][("metricflow", "a", "d")]) == 3
        )
        s.add(Entity(id="new", account_id="a", kind="ad", external_id="456", labels={}))
        s.flush()
        s.add(Ad(entity_id="new", adset_id="g"))
        s.flush()
        second = resolve_targets(s, "default", targets, NOW.date())
        assert second["total"] == 2
        assert len(second["provenance"][("metricflow", "a", "new")]) == 2


@pytest.mark.parametrize(
    "query",
    [
        "italy",
        "ADEN",
        "01",
        "aden italy",
        "ITALY 01",
        "\u043a\u0430\u043c\u043f\u0430\u043d\u0438\u044f",
    ],
)
def test_unicode_and_id_and_semantics(store, query):
    with store.begin() as s:
        s.get(
            Entity, "c"
        ).name = "Italy Adenofrin 01 \u041a\u0430\u043c\u043f\u0430\u043d\u0438\u044f"
        s.flush()
        found = search_catalog(s, "default", "campaign", query)
        assert found["total"] == 1
        assert search_catalog(s, "default", "campaign", query + " absent")["total"] == 0


def test_full_catalog_search_cascade_stable_pagination_and_no_foreign(store):
    with store.begin() as s:
        for n in range(25):
            s.add(
                Entity(
                    id=f"c{n:02}",
                    account_id="a",
                    kind="campaign",
                    external_id=f"90{n:02}",
                    name=f"Item {n:02}",
                    labels={},
                )
            )
        s.flush()
        assert search_catalog(s, "default", "campaign", offset=20)["rows"]
        assert (
            search_catalog(s, "default", "campaign", "Item 24")["rows"][0]["id"]
            == "c24"
        )
        assert (
            search_catalog(
                s, "default", "ad", accounts=["a"], campaigns=["c"], adsets=["g"]
            )["total"]
            == 1
        )
        assert search_catalog(s, "default", "ad", accounts=["foreign"])["total"] == 0
        assert search_catalog(s, "other", "ad")["total"] == 0
        assert search_catalog(s, "default", "campaign", "%' OR 1=1 --")["total"] == 0


@pytest.mark.parametrize(
    "bad", [target(key="missing"), target(account="other"), target(provider="meta")]
)
def test_atomic_rejects_invalid_batch_without_rule_copy(store, bad):
    with store.begin() as s:
        rule = save(s, ACTOR, config())
    with pytest.raises(HTTPException), store.begin() as s:
        change_targets(s, ACTOR, rule["id"], command(1, [target(), bad]))
    with store() as s:
        assert s.scalar(select(func.count()).select_from(RuleVersion)) == 1


def test_dedup_cas_dates_soft_removal_and_version_history(store):
    with store.begin() as s:
        rule = save(s, ACTOR, config(selection={"campaign": "c"}))
        saved = change_targets(
            s, ACTOR, rule["id"], command(1, [target(), target("AD", "d")])
        )
        assert len(saved["definition"]["selection"]["targets"]) == 2
        again = change_targets(s, ACTOR, rule["id"], command(2, [target()]))
        assert len(again["definition"]["selection"]["targets"]) == 2
        removed = change_targets(
            s, ACTOR, rule["id"], command(3, [target("AD", "d")], "remove")
        )
        assert len(removed["definition"]["selection"]["targets"]) == 1
        assert (
            removed["definition"]["selection"]["targets"][0]["scope_type"] == "CAMPAIGN"
        )
        assert s.scalar(select(func.count()).select_from(RuleVersion)) == 4
        assert s.scalar(select(func.count()).select_from(RuleAuditLog)) >= 4
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0
        with pytest.raises(HTTPException) as caught:
            change_targets(s, ACTOR, rule["id"], command(3, [target()]))
        assert caught.value.status_code == 409


def test_empty_explicit_scope_never_means_all(store):
    with store.begin() as s:
        rule = save(s, ACTOR, config(selection={"target_mode": True, "targets": []}))
        result = simulate(s, ACTOR, rule["id"], 1, now=NOW)
        assert result["total"] == 0
        assert result["target_issues"] == [{"reason_code": "NO_MATCHING_ADS"}]


def test_real_economics_unique_ad_provenance_and_selected_simulation_history(store):
    with store.begin() as s:
        selected = [target(), target("ADSET", "g"), target("AD", "d")]
        rule = save(
            s,
            ACTOR,
            config(
                selection={
                    "target_mode": True,
                    "targets": [t.model_dump() for t in selected],
                }
            ),
        )
        result = simulate(s, ACTOR, rule["id"], 1, now=NOW)
        assert result["total"] == 1 and len(result["rows"][0]["target_provenance"]) == 3
        frozen = deepcopy(result)
        subset = simulate(s, ACTOR, rule["id"], 1, now=NOW, targets=[target("AD", "d")])
        assert subset["total"] == 1 and len(subset["rows"][0]["target_provenance"]) == 1
        assert s.get(RuleSimulation, result["id"]).payload["rows"] == frozen["rows"]
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


@pytest.mark.parametrize("reason", ["missing", "hierarchy", "dates", "revision"])
def test_unresolved_targets_do_not_broaden_scope(store, reason):
    with store.begin() as s:
        item = target()
        if reason == "missing":
            item.scope_id = "missing"
        elif reason == "hierarchy":
            item = target("AD", "d")
            s.get(Ad, "d").adset_id = None
            s.flush()
        elif reason == "dates":
            item.effective_start = NOW.date().replace(year=2099)
        else:
            item.credential_revision = 99
        result = resolve_targets(s, "default", [item], NOW.date())
        assert result["total"] == 0
        if reason != "dates":
            assert result["issues"]


def test_schema_duplicate_limit_and_dates():
    with pytest.raises(ValidationError):
        config(selection={"target_mode": True, "targets": [target().model_dump()] * 2})
    with pytest.raises(ValidationError):
        command(1, [target()] * 201)
    with pytest.raises(ValidationError):
        target(effective_start="2026-10-20", effective_end="2026-10-01")


class TargetApiTests(EconomicsApiTests):
    async def test_bulk_roles_csrf_targets_search_and_dry_run(self):
        base = "/api/smart-rules"
        await self.login()
        rule = (
            await self.client.post(
                base, headers=await self.csrf(), json=config().model_dump(mode="json")
            )
        ).json()
        endpoint = base + "/" + rule["id"]
        body = command(1, [target()]).model_dump(mode="json")
        assert (
            await self.client.post(endpoint + "/assignments/bulk", json=body)
        ).status_code == 403
        response = await self.client.post(
            endpoint + "/assignments/bulk", headers=await self.csrf(), json=body
        )
        assert response.status_code == 200, response.text
        assert (await self.client.get(endpoint + "/targets")).json()["targets"][0][
            "actor_id"
        ]
        search = await self.client.get(
            base + "/catalog/search", params={"kind": "ad", "q": "d"}
        )
        assert search.status_code == 200 and search.json()["total"] == 1
        result = await self.client.post(
            endpoint + "/simulate-selected",
            headers=await self.csrf(),
            json=command(2, [target("AD", "d")]).model_dump(mode="json"),
        )
        assert result.status_code == 200, result.text
        assert (
            result.json()["total"] == 1 and result.json()["action_eligibility"] is False
        )
        for role in ("operator", "viewer"):
            await self.login(role)
            assert (await self.client.get(endpoint + "/targets")).status_code == 200
            assert (
                await self.client.post(
                    endpoint + "/assignments/bulk",
                    headers=await self.csrf(),
                    json=command(2, [target()]).model_dump(mode="json"),
                )
            ).status_code == 403


def test_disappeared_saved_target_can_be_removed_without_broadening(store):
    with store.begin() as s:
        rule = save(
            s,
            ACTOR,
            config(
                selection={
                    "target_mode": True,
                    "targets": [target("AD", "d").model_dump()],
                }
            ),
        )
        s.get(Ad, "d").adset_id = None
        s.flush()
        changed = change_targets(
            s, ACTOR, rule["id"], command(1, [target("AD", "d")], "remove")
        )
        assert changed["definition"]["selection"]["target_mode"]
        assert changed["definition"]["selection"]["targets"] == []


def test_assignment_dates_and_actor_are_server_scoped(store):
    with store.begin() as s:
        rule = save(
            s,
            ACTOR,
            config(
                selection={
                    "target_mode": True,
                    "targets": [
                        target(
                            effective_start="2026-10-01",
                            effective_end="2026-10-31",
                            actor_id="forged",
                        ).model_dump()
                    ],
                }
            ),
        )
        row = rule["definition"]["selection"]["targets"][0]
        assert row["actor_id"] == ACTOR["id"] and row["created_at"]
        assert row["version_policy"] == "LATEST"
        assert resolve_targets(s, "default", [row], NOW.date())["total"] == 1
        assert (
            resolve_targets(s, "default", [row], NOW.date().replace(month=11))["total"]
            == 0
        )


def test_legacy_conjunction_cannot_be_silently_broadened(store):
    with store.begin() as s:
        rule = save(s, ACTOR, config(selection={"campaign": "c", "ad": "d"}))
        changed = change_targets(s, ACTOR, rule["id"], command(1, [target()]))
        assert {
            t["scope_type"] for t in changed["definition"]["selection"]["targets"]
        } == {"AD", "CAMPAIGN"}


def test_unmapped_campaign_has_explicit_reason(store):
    with store.begin() as s:
        s.add(
            Entity(
                id="unmapped",
                account_id="a",
                kind="campaign",
                external_id="999",
                labels={},
            )
        )
        s.flush()
        result = resolve_targets(s, "default", [target(key="unmapped")], NOW.date())
        assert result["total"] == 0
        assert result["issues"][0]["reason_code"] == "HIERARCHY_UNVERIFIED"


def test_empty_bulk_requires_explicit_replace():
    with pytest.raises(ValidationError):
        command(1, [])
    with pytest.raises(ValidationError):
        command(1, [], "remove")
    assert command(1, [], "replace").targets == []
