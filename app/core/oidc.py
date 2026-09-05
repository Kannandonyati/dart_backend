"""OIDC authorization-code + PKCE exchange.

Matches the old Dart `sso_exchange.py` flow: discovery → token → JWKS →
email claim. Tests monkeypatch `exchange_authorization_code` so they
never hit a real IdP.
"""

from dataclasses import dataclass
from typing import Any

import httpx
from jose import jwt

from app.core.exceptions import UnauthorizedError


@dataclass(frozen=True)
class OidcIdentity:
    email: str


async def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    discovery_url: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> OidcIdentity:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        discovery = await client.get(discovery_url)
        discovery.raise_for_status()
        oidc = discovery.json()

        token_endpoint = oidc["token_endpoint"]
        jwks_uri = oidc["jwks_uri"]
        methods = oidc.get("token_endpoint_auth_methods_supported", ["client_secret_post"])
        use_basic = "client_secret_basic" in methods

        token_params = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
        if use_basic:
            token_resp = await client.post(token_endpoint, data=token_params, auth=(client_id, client_secret))
        else:
            token_resp = await client.post(
                token_endpoint,
                data={**token_params, "client_id": client_id, "client_secret": client_secret},
            )
        if token_resp.status_code != 200:
            raise UnauthorizedError("Token exchange with identity provider failed.")

        token_data = token_resp.json()
        id_token = token_data.get("id_token")
        access_token = token_data.get("access_token")
        if not id_token:
            raise UnauthorizedError("No identity token received from provider.")

        jwks_headers = {"Accept": "application/json"}
        jwks_resp = await client.get(jwks_uri, headers=jwks_headers)
        if jwks_resp.status_code == 401 and access_token:
            jwks_resp = await client.get(
                str(jwks_resp.url),
                headers={**jwks_headers, "Authorization": f"Bearer {access_token}"},
            )
        if jwks_resp.status_code == 401:
            jwks_resp = await client.get(jwks_uri, headers=jwks_headers, auth=(client_id, client_secret))
        jwks_resp.raise_for_status()
        jwks = jwks_resp.json()

    email = _email_from_id_token(id_token, client_id, jwks)
    return OidcIdentity(email=email)


def _email_from_id_token(id_token: str, client_id: str, jwks: dict[str, Any]) -> str:
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    keys = jwks.get("keys", [])
    key = next((item for item in keys if item.get("kid") == kid), keys[0] if keys else None)
    if key is None:
        raise UnauthorizedError("Could not verify identity token.")

    decoded = jwt.decode(
        id_token,
        key,
        algorithms=["RS256"],
        audience=client_id,
        options={"verify_at_hash": False, "leeway": 10},
    )
    email = decoded.get("email") or decoded.get("preferred_username") or decoded.get("sub")
    if not email or not isinstance(email, str):
        raise UnauthorizedError("Could not extract email from identity token.")
    return email.lower()
