"""Addressed disposable economics fixtures; never changes advertising facts."""

from __future__ import annotations

import json
import os
import re
import secrets

from sqlalchemy import delete, select, text

from backend.app import database_sessions
from services.auth.sessions import new_user
from services.economics.models import (
    ApprovalObservation,
    EconomicsAssignment,
    EconomicsAuditLog,
    EconomicsEvaluation,
    EconomicsGrant,
    EconomicsProfile,
)
from services.storage.models import (
    User,
    UserColumnPreset,
    UserSession,
    UserTablePreference,
)

nonce = os.environ["UI_FIXTURE_NONCE"]
if not re.fullmatch(r"[a-f0-9]{32}", nonce):
    raise RuntimeError("INVALID_FIXTURE_NONCE")
if (
    os.environ.get("APP_ENV") == "production"
    or os.environ.get("LOCAL_READ_ONLY") != "true"
    or os.environ.get("ACTIONS_ENABLED") != "false"
):
    raise RuntimeError("LOCAL_READ_ONLY_REQUIRED")
workspace = os.environ.get("WORKSPACE_ID", "default")
logins = [f"economics-ui-{nonce}-{i}@local.test" for i in range(3)]
with database_sessions().begin() as s:
    if s.scalar(text("SELECT version_num FROM alembic_version")) not in ("0010_economics", "0011_smart_rules"):
        raise RuntimeError("ECONOMICS_MIGRATION_REQUIRED")
    if os.environ["UI_FIXTURE_MODE"] == "create":
        password = secrets.token_urlsafe(24)
        users = []
        for login, role in zip(logins, ["admin", "operator", "viewer"], strict=True):
            u = new_user(s, workspace, login, password, role)
            s.flush()
            users.append({"id": u.id, "login": login, "password": password})
        print(json.dumps(users))
    elif os.environ["UI_FIXTURE_MODE"] == "cleanup":
        ids = list(
            s.scalars(
                select(User.id).where(
                    User.workspace_id == workspace, User.email.in_(logins)
                )
            )
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
        for model in (ApprovalObservation, EconomicsAssignment, EconomicsEvaluation):
            if profiles:
                s.execute(
                    delete(model).where(
                        model.workspace_id == workspace, model.profile_id.in_(profiles)
                    )
                )
        if ids:
            s.execute(
                delete(EconomicsAuditLog).where(
                    EconomicsAuditLog.workspace_id == workspace,
                    EconomicsAuditLog.actor_id.in_(ids),
                )
            )
            s.execute(
                delete(EconomicsGrant).where(
                    EconomicsGrant.workspace_id == workspace,
                    EconomicsGrant.user_id.in_(ids),
                )
            )
            if profiles:
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
                    "removed_profiles": len(profiles),
                    "advertising_facts_modified": 0,
                }
            )
        )
    else:
        raise RuntimeError("INVALID_FIXTURE_MODE")
