"""Disposable addressed rule fixtures; no advertising facts or credentials changed."""

from __future__ import annotations

import json
import os
import re
import secrets

from sqlalchemy import delete, func, select, text

from backend.app import database_sessions
from services.auth.sessions import new_user
from services.actions.manual_models import ManualActionGrant, ManualGrantAudit
from services.automation.smart_models import (
    RuleAuditLog,
    RuleGrant,
    RuleSimulation,
    RuleVersion,
)
from services.economics.models import (
    EconomicsAuditLog,
    EconomicsEvaluation,
    EconomicsProfile,
)
from services.economics.schema import ProfileInput
from services.economics.store import create_profile
from services.providers.matching import identity_maps
from services.storage.models import (
    AdAccount,
    ActionRequest,
    ActionLog,
    ActionExecution,
    Entity,
    Rule,
    User,
    UserColumnPreset,
    UserSession,
    UserTablePreference,
)

nonce = os.environ["UI_FIXTURE_NONCE"]
if (
    not re.fullmatch(r"[a-f0-9]{32}", nonce)
    or os.environ.get("APP_ENV") == "production"
    or os.environ.get("LOCAL_READ_ONLY") != "true"
    or os.environ.get("ACTIONS_ENABLED") != "false"
):
    raise RuntimeError("LOCAL_RULE_FIXTURE_GUARD")
workspace = os.environ.get("WORKSPACE_ID", "default")
logins = [f"rules-ui-{nonce}-{i}@local.test" for i in range(3)]
with database_sessions().begin() as s:
    if s.scalar(text("SELECT version_num FROM alembic_version")) != "0012_manual_actions":
        raise RuntimeError("RULES_MIGRATION_REQUIRED")
    if os.environ["UI_FIXTURE_MODE"] == "create":
        password = secrets.token_urlsafe(24)
        users = []
        for login, role in zip(logins, ["admin", "operator", "viewer"], strict=True):
            u = new_user(s, workspace, login, password, role)
            s.flush()
            users.append({"id": u.id, "login": login, "password": password})
        profile = create_profile(
            s,
            {"id": users[0]["id"], "workspace": workspace, "role": "admin"},
            ProfileInput(
                name="Приёмка правил — длинное русское название " + nonce,
                offer="",
                geo="",
                payout="16",
                currency="USD",
                target_roi="20",
                minimum_roi="0",
                planned_approval_rate="0.3",
                minimum_sales=0,
            ),
        )
        account_id = s.scalar(
            select(AdAccount.id)
            .join(Entity)
            .where(
                AdAccount.workspace_id == workspace,
                AdAccount.provider == "metricflow",
                Entity.kind == "ad",
            )
            .group_by(AdAccount.id)
            .order_by(func.count(Entity.id).desc())
            .limit(1)
        )
        account_map, _ = identity_maps(s, workspace)
        print(
            json.dumps(
                {
                    "users": users,
                    "profile": profile,
                    "account_id": account_map.get(account_id, account_id),
                }
            )
        )
    elif os.environ["UI_FIXTURE_MODE"] == "cleanup":
        ids = list(
            s.scalars(
                select(User.id).where(
                    User.workspace_id == workspace, User.email.in_(logins)
                )
            )
        )
        rules = (
            list(
                s.scalars(
                    select(Rule.id).where(
                        Rule.workspace_id == workspace, Rule.owner_id.in_(ids)
                    )
                )
            )
            if ids
            else []
        )
        profiles = (
            list(
                s.scalars(
                    select(EconomicsProfile.id).where(
                        EconomicsProfile.workspace_id == workspace,
                        EconomicsProfile.created_by.in_(ids),
                    )
                )
            )
            if ids
            else []
        )
        for model in (RuleSimulation, RuleVersion):
            if rules:
                s.execute(
                    delete(model).where(
                        model.workspace_id == workspace, model.rule_id.in_(rules)
                    )
                )
        if ids:
            requests = list(s.scalars(select(ActionRequest.id).where(ActionRequest.workspace_id == workspace, ActionRequest.initiator_id.in_(ids))))
            if requests:
                for model in (ActionLog, ActionExecution):
                    s.execute(delete(model).where(model.request_id.in_(requests)))
                s.execute(delete(ActionRequest).where(ActionRequest.id.in_(requests)))
            s.execute(delete(ManualActionGrant).where(ManualActionGrant.workspace_id == workspace, ManualActionGrant.user_id.in_(ids)))
            s.execute(delete(ManualGrantAudit).where(ManualGrantAudit.workspace_id == workspace, ManualGrantAudit.actor_id.in_(ids)))
            for model in (RuleAuditLog, EconomicsAuditLog):
                s.execute(
                    delete(model).where(
                        model.workspace_id == workspace, model.actor_id.in_(ids)
                    )
                )
            s.execute(
                delete(RuleGrant).where(
                    RuleGrant.workspace_id == workspace, RuleGrant.user_id.in_(ids)
                )
            )
            if rules:
                s.execute(
                    delete(Rule).where(
                        Rule.workspace_id == workspace, Rule.id.in_(rules)
                    )
                )
            if profiles:
                s.execute(
                    delete(EconomicsEvaluation).where(
                        EconomicsEvaluation.workspace_id == workspace,
                        EconomicsEvaluation.profile_id.in_(profiles),
                    )
                )
                s.execute(
                    delete(EconomicsProfile).where(
                        EconomicsProfile.workspace_id == workspace,
                        EconomicsProfile.id.in_(profiles),
                    )
                )
            for model in (UserColumnPreset, UserTablePreference, UserSession):
                s.execute(delete(model).where(model.user_id.in_(ids)))
            s.execute(
                delete(User).where(
                    User.workspace_id == workspace,
                    User.id.in_(ids),
                    User.email.in_(logins),
                )
            )
        print(
            json.dumps(
                {
                    "removed_users": len(ids),
                    "removed_rules": len(rules),
                    "advertising_facts_modified": 0,
                }
            )
        )
    else:
        raise RuntimeError("INVALID_FIXTURE_MODE")
