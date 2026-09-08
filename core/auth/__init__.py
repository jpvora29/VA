"""Authentication — who is using the app, and how the server knows.

    settings   how this deployment is wired to an identity provider (env vars)
    identity   an OIDC claim set, normalised into one person across providers
    session    the server-side record of who is signed in (a signed Flask cookie)
    oidc       the authorization-code flow, as three routes on the Dash app's server

One generic OIDC client covers Microsoft Entra ID, Okta, Google Workspace and Auth0 —
pointing ``OIDC_ISSUER`` at a tenant is the whole difference between them. With nothing
configured, :func:`~core.auth.settings.sso_enabled` is False and the app keeps its
username-only sign-in so a local run and the test suite still work.

``app.py`` calls :func:`~core.auth.oidc.register_auth`; the login screen asks
:func:`~core.auth.settings.sso_enabled` which sign-in to draw.
"""
from core.auth.identity import Identity, from_claims
from core.auth.session import current_user, sign_in, sign_out
from core.auth.settings import OIDCSettings, describe, load_settings, sso_enabled

__all__ = [
    "Identity", "from_claims",
    "current_user", "sign_in", "sign_out",
    "OIDCSettings", "load_settings", "sso_enabled", "describe",
]
