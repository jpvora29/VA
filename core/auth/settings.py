"""How this deployment is wired to its identity provider — read once, from the environment.

Deliberately ONE generic OIDC client rather than a provider SDK. Microsoft Entra ID,
Okta, Google Workspace and Auth0 all publish the same discovery document, so pointing
``OIDC_ISSUER`` at a tenant is the entire difference between them; a provider-specific
integration would buy nothing and would have to be rewritten the first time the company
changed IdP.

    OIDC_ISSUER          https://login.microsoftonline.com/<tenant-id>/v2.0
                         https://<org>.okta.com/oauth2/default
                         https://accounts.google.com
    OIDC_CLIENT_ID       the application (client) id registered with the IdP
    OIDC_CLIENT_SECRET   its secret
    OIDC_SCOPES          optional; defaults to "openid email profile"
    OIDC_PROVIDER_NAME   optional; the words on the button ("Microsoft", "Okta")
    OIDC_REDIRECT_URI    optional; the absolute callback URL to register with the IdP.
                         Only needed behind a proxy that rewrites the host — otherwise
                         it is derived from the request.

With none of them set, ``enabled`` is False and the app keeps the username-only sign-in
so a local run and the test suite still work. That is a fallback, not a mode anyone
should deploy: :func:`describe` says which one is live so the login screen can be honest
about it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_SCOPES = "openid email profile"
CALLBACK_PATH = "/auth/callback"
LOGIN_PATH = "/auth/login"
LOGOUT_PATH = "/auth/logout"


@dataclass(frozen=True)
class OIDCSettings:
    """One identity provider, as configured for this deployment."""

    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = DEFAULT_SCOPES
    provider_name: str = "SSO"
    redirect_uri: Optional[str] = None

    @property
    def enabled(self) -> bool:
        """True only when a real IdP is configured — all three, or none of them."""
        return bool(self.issuer and self.client_id and self.client_secret)

    @property
    def metadata_url(self) -> str:
        """The discovery document every OIDC provider publishes under its issuer."""
        return f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def load_settings() -> OIDCSettings:
    """The settings for this process. Read on demand — tests set the environment."""
    return OIDCSettings(
        issuer=_env("OIDC_ISSUER"),
        client_id=_env("OIDC_CLIENT_ID"),
        client_secret=_env("OIDC_CLIENT_SECRET"),
        scopes=_env("OIDC_SCOPES", DEFAULT_SCOPES),
        provider_name=_env("OIDC_PROVIDER_NAME", "SSO"),
        redirect_uri=_env("OIDC_REDIRECT_URI") or None,
    )


def sso_enabled() -> bool:
    """Whether this deployment signs people in through an identity provider."""
    return load_settings().enabled


def describe() -> str:
    """One line for the login screen, so nobody has to guess which sign-in is live."""
    settings = load_settings()
    if settings.enabled:
        return f"Sign in with {settings.provider_name}"
    return "No identity provider is configured — this app is running in local mode."


__all__ = [
    "OIDCSettings", "load_settings", "sso_enabled", "describe",
    "DEFAULT_SCOPES", "CALLBACK_PATH", "LOGIN_PATH", "LOGOUT_PATH",
]
