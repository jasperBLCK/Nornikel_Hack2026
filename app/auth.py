"""Authentication & role-based access control.

Two modes, selected automatically:
  * Keycloak (KEYCLOAK_URL set): the backend proxies the OIDC password grant
    to Keycloak (`/realms/{realm}/protocol/openid-connect/token`) and verifies
    access tokens locally against the realm JWKS (RS256).
  * Local fallback (no KEYCLOAK_URL): built-in demo users with the same role
    model, HS256 tokens signed with AUTH_SECRET. Lets the app run with zero
    infrastructure while keeping an identical API contract.

Roles: admin, project_manager, analyst, researcher, external_partner.
Document sensitivity levels: public < internal < confidential.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "").rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "hydrax")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "hydrax-app")
KEYCLOAK_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "hydrax-dev-secret-change-me")
TOKEN_TTL = int(os.environ.get("AUTH_TOKEN_TTL", "28800"))  # 8h

ROLES = ("admin", "project_manager", "analyst", "researcher",
         "external_partner")

ROLE_LABELS = {
    "admin": "Администратор",
    "project_manager": "Руководитель проекта",
    "analyst": "Аналитик",
    "researcher": "Исследователь",
    "external_partner": "Внешний партнёр",
}

# Sensitivity clearance per role (levels the role is allowed to read).
SENSITIVITY_ORDER = ("public", "internal", "confidential")
ROLE_CLEARANCE = {
    "admin": "confidential",
    "project_manager": "confidential",
    "analyst": "internal",
    "researcher": "internal",
    "external_partner": "public",
}

# Which roles may export data (reports, .md, JSON-LD, PDF).
EXPORT_ROLES = {"admin", "project_manager", "analyst", "researcher"}

SENSITIVITY_LABELS = {
    "public": "Открытые",
    "internal": "Внутренние",
    "confidential": "Коммерческая тайна",
}

# Document sensitivity by source type. Internal R&D reports are internal,
# regulations carry commercial process data (confidential), published
# articles are public.
_DOC_RULES = (
    ("otchet", "internal"), ("отчет", "internal"), ("отчёт", "internal"),
    ("reglament", "confidential"), ("регламент", "confidential"),
    ("statya", "public"), ("статья", "public"),
)


def classify_sensitivity(doc_name: str) -> str:
    low = (doc_name or "").lower()
    for marker, level in _DOC_RULES:
        if marker in low:
            return level
    return "internal"


def clearance_levels(role_clearance: str) -> set[str]:
    idx = SENSITIVITY_ORDER.index(role_clearance)
    return set(SENSITIVITY_ORDER[: idx + 1])


@dataclass
class User:
    username: str
    name: str
    roles: list[str] = field(default_factory=list)

    @property
    def primary_role(self) -> str:
        for r in ROLES:
            if r in self.roles:
                return r
        return "external_partner"

    @property
    def clearance(self) -> str:
        return ROLE_CLEARANCE[self.primary_role]

    @property
    def can_export(self) -> bool:
        return self.primary_role in EXPORT_ROLES

    def allowed_levels(self) -> set[str]:
        return clearance_levels(self.clearance)

    def as_dict(self) -> dict:
        return {
            "username": self.username,
            "name": self.name,
            "roles": self.roles,
            "role": self.primary_role,
            "role_label": ROLE_LABELS[self.primary_role],
            "clearance": self.clearance,
            "clearance_label": SENSITIVITY_LABELS[self.clearance],
            "can_export": self.can_export,
        }


# -- local fallback user store ------------------------------------------------

def _hash(pw: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"hydrax-salt",
                               100_000).hex()


LOCAL_USERS = {
    "admin": {"password": _hash("admin123"), "name": "Администратор системы",
              "roles": ["admin"]},
    "manager": {"password": _hash("manager123"),
                "name": "Пётр Руководитель", "roles": ["project_manager"]},
    "analyst": {"password": _hash("analyst123"), "name": "Анна Аналитик",
                "roles": ["analyst"]},
    "researcher": {"password": _hash("researcher123"),
                   "name": "Иван Исследователь", "roles": ["researcher"]},
    "partner": {"password": _hash("partner123"),
                "name": "Внешний Партнёр (ООО «ГеоТех»)",
                "roles": ["external_partner"]},
}


def keycloak_enabled() -> bool:
    return bool(KEYCLOAK_URL)


def _kc_base() -> str:
    return f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"


_jwks_cache: dict = {"keys": None, "ts": 0.0}


async def _kc_jwks() -> dict:
    if _jwks_cache["keys"] and time.time() - _jwks_cache["ts"] < 3600:
        return _jwks_cache["keys"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_kc_base()}/protocol/openid-connect/certs")
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()
        _jwks_cache["ts"] = time.time()
    return _jwks_cache["keys"]


async def login(username: str, password: str) -> dict:
    """Returns {access_token, refresh_token?, user} or raises HTTPException."""
    if keycloak_enabled():
        data = {
            "grant_type": "password", "client_id": KEYCLOAK_CLIENT_ID,
            "username": username, "password": password,
        }
        if KEYCLOAK_CLIENT_SECRET:
            data["client_secret"] = KEYCLOAK_CLIENT_SECRET
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_kc_base()}/protocol/openid-connect/token", data=data)
        except httpx.HTTPError:
            raise HTTPException(503, "Keycloak недоступен")
        if resp.status_code != 200:
            raise HTTPException(401, "Неверный логин или пароль")
        tokens = resp.json()
        user = await verify_token(tokens["access_token"])
        return {"access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "expires_in": tokens.get("expires_in"),
                "user": user.as_dict()}

    rec = LOCAL_USERS.get(username)
    if rec is None or rec["password"] != _hash(password):
        raise HTTPException(401, "Неверный логин или пароль")
    now = int(time.time())
    token = jwt.encode(
        {"sub": username, "name": rec["name"], "roles": rec["roles"],
         "iat": now, "exp": now + TOKEN_TTL, "iss": "hydrax-local"},
        AUTH_SECRET, algorithm="HS256")
    user = User(username, rec["name"], rec["roles"])
    return {"access_token": token, "refresh_token": None,
            "expires_in": TOKEN_TTL, "user": user.as_dict()}


async def refresh(refresh_token: str) -> dict:
    if not keycloak_enabled():
        raise HTTPException(400, "refresh недоступен в локальном режиме")
    data = {"grant_type": "refresh_token", "client_id": KEYCLOAK_CLIENT_ID,
            "refresh_token": refresh_token}
    if KEYCLOAK_CLIENT_SECRET:
        data["client_secret"] = KEYCLOAK_CLIENT_SECRET
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_kc_base()}/protocol/openid-connect/token", data=data)
    if resp.status_code != 200:
        raise HTTPException(401, "Сессия истекла, войдите заново")
    tokens = resp.json()
    user = await verify_token(tokens["access_token"])
    return {"access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "expires_in": tokens.get("expires_in"),
            "user": user.as_dict()}


async def verify_token(token: str) -> User:
    if keycloak_enabled():
        try:
            jwks = await _kc_jwks()
            header = jwt.get_unverified_header(token)
            key = next((k for k in jwks["keys"]
                        if k.get("kid") == header.get("kid")), None)
            if key is None:
                raise HTTPException(401, "Неизвестный ключ подписи")
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
            claims = jwt.decode(token, public_key, algorithms=["RS256"],
                                options={"verify_aud": False})
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(401, "Недействительный токен")
        roles = [r for r in (claims.get("realm_access") or {}).get("roles", [])
                 if r in ROLES]
        return User(claims.get("preferred_username", claims.get("sub", "")),
                    claims.get("name")
                    or claims.get("preferred_username", ""), roles)

    try:
        claims = jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(401, "Недействительный токен")
    return User(claims["sub"], claims.get("name", claims["sub"]),
                [r for r in claims.get("roles", []) if r in ROLES])


_bearer = HTTPBearer(auto_error=False)


async def current_user(
        request: Request,
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    token = creds.credentials if creds else request.query_params.get("token")
    if not token:
        raise HTTPException(401, "Требуется вход в систему")
    return await verify_token(token)


def require_roles(*roles: str):
    async def guard(user: User = Depends(current_user)) -> User:
        if not set(user.roles) & set(roles):
            raise HTTPException(403, "Недостаточно прав")
        return user
    return guard


require_admin = require_roles("admin")
