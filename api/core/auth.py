import time
from typing import Any, Callable

import httpx
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwk, jwt

from .config import Settings, get_settings

DEV_USER: dict[str, Any] = {
    "sub": "dev-user",
    "preferred_username": "dev-admin",
    "email": "dev-admin@example.com",
    "realm_access": {"roles": ["certifs-admin", "certifs-viewer"]},
}


_keycloak_key_cache: dict = {"key": None, "expires_at": 0.0}
_KEY_TTL_SECONDS = 3600


def get_keycloak_public_key(settings: Settings) -> str:
    """Retourne la clé publique Keycloak, mise en cache 1h pour éviter N appels réseau."""
    now = time.monotonic()
    if _keycloak_key_cache["key"] and now < _keycloak_key_cache["expires_at"]:
        return _keycloak_key_cache["key"]

    well_known_url = (
        f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
        "/.well-known/openid-configuration"
    )
    with httpx.Client(timeout=5.0) as client:
        discovery = client.get(well_known_url)
        discovery.raise_for_status()
        jwks_uri = discovery.json()["jwks_uri"]

        jwks_response = client.get(jwks_uri)
        jwks_response.raise_for_status()
        jwks = jwks_response.json()

    signing_keys = [key for key in jwks["keys"] if key.get("use") == "sig"]
    key_data = signing_keys[0] if signing_keys else jwks["keys"][0]

    public_key = jwk.construct(key_data, algorithm="RS256")
    pem = public_key.to_pem().decode("utf-8")

    _keycloak_key_cache["key"] = pem
    _keycloak_key_cache["expires_at"] = now + _KEY_TTL_SECONDS
    return pem


def verify_token(token: str, settings: Settings) -> dict[str, Any]:
    public_key = get_keycloak_public_key(settings)
    issuer = f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"

    return jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=issuer,
        options={"verify_aud": False},
    )


def get_user_roles(token_claims: dict[str, Any]) -> list[str]:
    return token_claims.get("realm_access", {}).get("roles", [])


def _extract_claims(request: Request, settings: Settings) -> dict[str, Any]:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = auth_header.removeprefix("Bearer ").strip()

    try:
        return verify_token(token, settings)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def require_role(role: str) -> Callable[..., dict[str, Any]]:
    def dependency(
        request: Request,
        settings: Settings = Depends(get_settings),
    ) -> dict[str, Any]:
        if settings.DEV_MODE:
            return DEV_USER

        claims = _extract_claims(request, settings)
        if role not in get_user_roles(claims):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required role: {role}",
            )

        return claims

    return dependency


def require_any_role(roles: list[str]) -> Callable[..., dict[str, Any]]:
    def dependency(
        request: Request,
        settings: Settings = Depends(get_settings),
    ) -> dict[str, Any]:
        if settings.DEV_MODE:
            return DEV_USER

        claims = _extract_claims(request, settings)
        if not set(roles) & set(get_user_roles(claims)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required role (any of): {', '.join(roles)}",
            )

        return claims

    return dependency
