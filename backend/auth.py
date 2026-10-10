"""Authentication and workspace authorization, independently enforced by FastAPI."""
from datetime import timedelta
from functools import lru_cache
import hmac
import logging
import os
import re
import secrets
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from redis import Redis
from sqlalchemy import delete, select, text

from services.auth.sessions import (
    auth_enabled, authenticate, cookie_name, create_session, digest, new_user,
    password_hash, production, user_view, utcnow, verify_password,
)
from services.storage.models import User, UserSession

router = APIRouter()
log = logging.getLogger("mcc.http")
SAFE = {"GET", "HEAD", "OPTIONS"}
LOGIN_COOKIE = "mcc_login"
RATE_SCRIPT = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"

@lru_cache
def limiter():
    return Redis.from_url(os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0"),
        socket_connect_timeout=2, socket_timeout=2)

def rate_limit(key, maximum, seconds):
    count = limiter().eval(RATE_SCRIPT, 1, "mcc:rate:" + digest(key, "rate"), seconds)
    if count > maximum:
        raise HTTPException(429, "RATE_LIMITED", headers={"Retry-After": str(seconds)})

def factory():
    from backend.app import database_sessions
    return database_sessions()

def origin():
    return os.environ.get("APP_ORIGIN", "http://localhost:3000").rstrip("/")

def set_cookie(response, name, value, ttl):
    response.set_cookie(name, value, max_age=ttl, httponly=True, secure=production(),
        samesite="strict", path="/")

def identity(request):
    value = getattr(request.state, "identity", None)
    if not value:
        raise HTTPException(401, "AUTHENTICATION_REQUIRED")
    return value

def admin(request):
    value = identity(request)
    if value["role"] != "admin":
        raise HTTPException(403, "ADMIN_REQUIRED")
    return value

def csrf_check(request, actor=None):
    if request.headers.get("origin") != origin():
        raise HTTPException(403, "CSRF_ORIGIN")
    token = request.headers.get("x-csrf-token", "")
    if len(token) > 128:
        raise HTTPException(403, "CSRF_INVALID")
    if actor:
        if not token or not hmac.compare_digest(actor["csrf_hash"], digest(token, "csrf")):
            raise HTTPException(403, "CSRF_INVALID")
    else:
        value = request.cookies.get(LOGIN_COOKIE, "")
        try:
            expiry, nonce, signature = value.split(".")
            assert int(expiry) > time.time() and int(expiry) <= time.time() + 901
            assert hmac.compare_digest(signature, digest(expiry + "." + nonce, "login"))
            assert hmac.compare_digest(token, digest(value, "login-csrf"))
        except (ValueError, AssertionError):
            raise HTTPException(403, "CSRF_INVALID") from None

async def protect(request, call_next):
    """Outer middleware: no provider commands permitted in authenticated READ mode."""
    request_id = str(uuid4())
    started = time.monotonic()
    response = None
    try:
        if auth_enabled():
            path = request.url.path
            if path in ("/docs", "/redoc", "/openapi.json"):
                raise HTTPException(404, "NOT_FOUND")
            if path.startswith("/api/"):
                ip = request.headers.get("x-real-ip") if os.environ.get("AUTH_TRUST_PROXY") == "true" else None
                ip = ip or (request.client.host if request.client else "unknown")
                rate_limit("api:" + ip, int(os.environ.get("API_RATE_PER_MINUTE", "240")), 60)
                request.state.client_ip = ip
                public = path in ("/api/auth/csrf", "/api/auth/login")
                actor = authenticate(factory(), request.cookies.get(cookie_name()))
                request.state.identity = actor
                if not public and not actor:
                    raise HTTPException(401, "AUTHENTICATION_REQUIRED")
                if request.method not in SAFE:
                    csrf_check(request, actor)
                    if not path.startswith(("/api/auth/", "/api/admin/", "/api/preferences/columns", "/api/economics/", "/api/smart-rules", "/api/manual-control/")):
                        raise HTTPException(403, "READ_ONLY")
                if path.startswith("/api/admin/"):
                    admin(request)
                # Disabled modules remain present in the repository, not exposed for control.
                if path.startswith(("/api/ai", "/api/automation")) or (
                    path.startswith("/api/actions") and path != "/api/actions/capabilities/info"):
                    raise HTTPException(403, "READ_ONLY")
        response = await call_next(request)
    except HTTPException as error:
        if error.detail in {"CSRF_ORIGIN", "CSRF_INVALID", "RATE_LIMITED", "AUTHENTICATION_REQUIRED", "READ_ONLY", "ADMIN_REQUIRED", "NOT_FOUND"}:
            request.state.auth_error_code = error.detail
        response = JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)
    except Exception:
        response = JSONResponse({"detail": "SERVICE_UNAVAILABLE"}, status_code=503)
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"
    log.info("request", extra={"request_id": request_id, "status": response.status_code,
        "method": request.method, "error_code": getattr(request.state, "auth_error_code", None) or {401:"AUTHENTICATION_REQUIRED",403:"FORBIDDEN",422:"INVALID_REQUEST",429:"RATE_LIMITED",503:"SERVICE_UNAVAILABLE"}.get(response.status_code),
        "elapsed_ms": round((time.monotonic()-started)*1000, 2)})
    return response

@router.get("/api/auth/csrf")
def csrf(request: Request):
    actor = getattr(request.state, "identity", None)
    if actor:
        token = digest(request.cookies[cookie_name()], "csrf-value")
        return {"csrf_token": token}
    value = str(int(time.time()) + 900) + "." + secrets.token_urlsafe(24)
    value += "." + digest(value, "login")
    response = JSONResponse({"csrf_token": digest(value, "login-csrf")})
    set_cookie(response, LOGIN_COOKIE, value, 900)
    return response

class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=1, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=256)

@router.post("/api/auth/login")
def login(command: Login, request: Request):
    if not auth_enabled():
        raise HTTPException(503, "AUTH_NOT_CONFIGURED")
    normalized = command.login.strip().lower()
    rate_limit("login-ip:" + request.state.client_ip, int(os.environ.get("LOGIN_RATE_LIMIT", "10")), 900)
    rate_limit("login-user:" + normalized, int(os.environ.get("LOGIN_RATE_LIMIT", "10")), 900)
    with factory().begin() as session:
        user = session.scalar(select(User).where(User.workspace_id == os.environ.get("WORKSPACE_ID", "default"), User.email == normalized))
        verified = verify_password(user.password_hash if user else None, command.password.get_secret_value())
        if not verified or not user or not user.is_active or user.role.lower() not in ("admin", "operator", "viewer"):
            request.state.auth_error_code = "INVALID_CREDENTIALS"
            raise HTTPException(401, "INVALID_CREDENTIALS")
        old = request.cookies.get(cookie_name())
        if old and len(old) <= 128:
            session.execute(delete(UserSession).where(UserSession.token_hash == digest(old)))
        token, csrf_token, ttl = create_session(session, user)
        view = user_view(user)
    response = JSONResponse({"user": view, "csrf_token": csrf_token})
    set_cookie(response, cookie_name(), token, ttl)
    response.delete_cookie(LOGIN_COOKIE, path="/", secure=production(), httponly=True, samesite="strict")
    return response

@router.get("/api/auth/me")
def me(request: Request):
    actor = identity(request)
    return {"user": {k: actor[k] for k in ("id", "login", "role", "workspace")}}

@router.post("/api/auth/logout")
def logout(request: Request):
    actor = identity(request)
    with factory().begin() as session:
        session.execute(delete(UserSession).where(UserSession.token_hash == actor["token_hash"]))
    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie(cookie_name(), path="/", secure=production(), httponly=True, samesite="strict")
    return response

@router.get("/api/admin/users")
def list_users(request: Request):
    actor = admin(request)
    with factory()() as session:
        users = session.scalars(select(User).where(User.workspace_id == actor["workspace"]).order_by(User.email)).all()
        return {"users": [{**user_view(u), "active": u.is_active, "can_login": bool(u.password_hash)} for u in users]}

class UserCreate(Login):
    role: str = Field(default="viewer", pattern="^(admin|operator|viewer)$")

@router.post("/api/admin/users", status_code=201)
def add_user(command: UserCreate, request: Request):
    actor = admin(request)
    try:
        with factory().begin() as session:
            user = new_user(session, actor["workspace"], command.login, command.password.get_secret_value(), command.role)
            view = user_view(user)
        return {"user": view}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None

class UserChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str | None = Field(default=None, pattern="^(admin|operator|viewer)$")
    active: bool | None = None
    password: SecretStr | None = Field(default=None, min_length=12, max_length=256)

@router.patch("/api/admin/users/{user_id}")
def change_user(user_id: str, command: UserChange, request: Request):
    actor = admin(request)
    with factory().begin() as session:
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(670718401)"))
        user = session.get(User, user_id)
        if not user or user.workspace_id != actor["workspace"]:
            raise HTTPException(404, "USER_NOT_FOUND")
        admins = session.scalars(select(User).where(User.workspace_id == actor["workspace"], User.role == "admin",
            User.is_active.is_(True), User.password_hash.is_not(None))).all()
        if user in admins and len(admins) == 1 and (command.active is False or command.role not in (None, "admin")):
            raise HTTPException(409, "LAST_ADMIN_REQUIRED")
        if command.role is not None: user.role = command.role
        if command.active is not None: user.is_active = command.active
        if command.password is not None: user.password_hash = password_hash(command.password.get_secret_value())
        session.execute(delete(UserSession).where(UserSession.user_id == user.id))
        return {"user": user_view(user), "sessions_revoked": True}

def validate_environment():
    if production():
        if not auth_enabled() or os.environ.get("LOCAL_READ_ONLY") != "true" or os.environ.get("ACTIONS_ENABLED") != "false":
            raise RuntimeError("PRODUCTION_REQUIRES_AUTH_READ_ONLY")
        if not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]+)?", origin()):
            raise RuntimeError("HTTPS_ORIGIN_REQUIRED")
        if any(os.environ.get(k, "false") != "false" for k in ("AI_ENABLED", "AI_AUTOPILOT_ALLOWED", "TELEGRAM_ENABLED")):
            raise RuntimeError("CONTROL_MODULES_MUST_BE_DISABLED")
        if os.environ.get("METRICFLOW_WRITE_KEY_FILE"):
            raise RuntimeError("WRITE_SECRET_FORBIDDEN")
    if auth_enabled():
        digest("startup")
