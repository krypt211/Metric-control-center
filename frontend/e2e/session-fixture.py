"""Local UI fixture sessions; never prunes sessions belonging to existing users."""

import os
import re
import secrets
from datetime import timedelta

from backend.auth import cookie_name
from services.auth.sessions import digest, utcnow
from services.storage.models import UserSession


def fixture_cookies(session, user):
    if os.environ.get("UI_SESSION_FIXTURES") != "true":
        return []
    if (
        os.environ.get("APP_ENV") == "production"
        or os.environ.get("LOCAL_READ_ONLY") != "true"
        or os.environ.get("ACTIONS_ENABLED") != "false"
        or not re.fullmatch(
            r"(rules-ui|economics-ui|ui1)-[a-f0-9]{32}-[0-9]+@local\.test", user.email
        )
    ):
        raise RuntimeError("LOCAL_ADDRESSED_SESSION_FIXTURE_REQUIRED")
    now = utcnow()
    ttl = max(300, min(int(os.environ.get("SESSION_TTL_SECONDS", "28800")), 604800))
    cookies = []
    count = (
        32 if os.environ.get("POSTGRES_DB", "").startswith("mcc_integrations_") else 8
    )
    for _ in range(count):
        token = secrets.token_urlsafe(32)
        csrf = digest(token, "csrf-value")
        session.add(
            UserSession(
                token_hash=digest(token),
                user_id=user.id,
                csrf_hash=digest(csrf, "csrf"),
                created_at=now,
                expires_at=now + timedelta(seconds=ttl),
            )
        )
        cookies.append(
            {
                "name": cookie_name(),
                "value": token,
                "httpOnly": True,
                "sameSite": "Strict",
                "secure": False,
                "expires": int(now.timestamp()) + ttl,
            }
        )
    return cookies
