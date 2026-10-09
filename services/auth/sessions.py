"""Opaque, revocable PostgreSQL sessions. Tokens never enter stored records or logs."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import hmac
import os
from pathlib import Path
import secrets
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import delete, select

from services.storage.models import User, UserSession
from services.sync.engine import aware

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
ROLES = ("admin", "operator", "viewer")

def utcnow():
    return datetime.now(timezone.utc)

def auth_enabled():
    return os.environ.get("AUTH_ENABLED", "false").lower() == "true"

def production():
    return os.environ.get("APP_ENV") == "production"

def cookie_name():
    return "__Host-mcc_session" if production() else "mcc_session"

@lru_cache
def _secret(path):
    value = Path(path).read_bytes().strip()
    if len(value) < 32:
        raise RuntimeError("SESSION_SECRET_INVALID")
    return value

def digest(value, namespace="session"):
    path = os.environ.get("SESSION_SECRET_FILE")
    if not path:
        raise RuntimeError("SESSION_SECRET_MISSING")
    return hmac.new(_secret(path), (namespace + ":" + value).encode(), hashlib.sha256).hexdigest()

def valid_password(password):
    # Long passphrases allowed; byte cap prevents resource abuse.
    return isinstance(password, str) and 12 <= len(password) <= 256 and len(password.encode()) <= 1024

def password_hash(password):
    if not valid_password(password):
        raise ValueError("Password must contain 12 to 256 characters")
    return HASHER.hash(password)

def verify_password(stored, password):
    try:
        return HASHER.verify(stored or DUMMY_HASH, password) and bool(stored)
    except (VerificationError, InvalidHashError):
        return False

def user_view(user):
    return {"id": user.id, "login": user.email, "role": user.role.lower(), "workspace": user.workspace_id}

def create_session(session, user, now=None):
    now = now or utcnow()
    token = secrets.token_urlsafe(32)
    csrf = digest(token, "csrf-value")
    ttl = max(300, min(int(os.environ.get("SESSION_TTL_SECONDS", "28800")), 604800))
    session.execute(delete(UserSession).where(UserSession.expires_at <= now))
    session.add(UserSession(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf, "csrf"),
        created_at=now, expires_at=now + timedelta(seconds=ttl)))
    return token, csrf, ttl

def authenticate(factory, token, now=None):
    if not token or len(token) > 128:
        return None
    now = now or utcnow()
    with factory() as session:
        observation = session.get(UserSession, digest(token))
        if not observation or aware(observation.expires_at) <= now:
            return None
        user = session.get(User, observation.user_id)
        if not user or not user.is_active or not user.password_hash or user.role.lower() not in ROLES:
            return None
        if user.workspace_id != os.environ.get("WORKSPACE_ID", "default"):
            return None
        return {**user_view(user), "csrf_hash": observation.csrf_hash, "token_hash": observation.token_hash}

def csrf_for_session(factory, identity):
    # Rotate token on every explicit GET /auth/csrf; old tokens stop being valid.
    csrf = secrets.token_urlsafe(32)
    with factory.begin() as session:
        row = session.get(UserSession, identity["token_hash"])
        if not row:
            raise ValueError("SESSION_REVOKED")
        row.csrf_hash = digest(csrf, "csrf")
    return csrf

def new_user(session, workspace, login, password, role="viewer"):
    login = login.strip().lower()
    if not login or len(login) > 320 or any(c.isspace() for c in login) or role not in ROLES:
        raise ValueError("Invalid login or role")
    if session.scalar(select(User).where(User.workspace_id == workspace, User.email == login)):
        raise ValueError("Login already exists")
    user = User(id=str(uuid4()), workspace_id=workspace, email=login, role=role,
                password_hash=password_hash(password), is_active=True)
    session.add(user)
    return user
