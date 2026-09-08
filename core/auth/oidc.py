"""The OIDC authorization-code flow, as three routes on the app's Flask server.

An adapter over Authlib, and nothing more — the protocol details (discovery, PKCE-less
code exchange, JWKS fetch, id-token signature and nonce validation) belong to the
library, and every decision this app actually makes is one of the small functions here.

    GET /auth/login      → redirect to the identity provider
    GET /auth/callback   → exchange the code, validate the token, sign the person in
    GET /auth/logout     → forget them here, then end the session at the provider

Two things are worth stating because they are the reason this exists at all:

  * **no credential reaches this app.** The user authenticates at the provider; what
    comes back is a signed token. There is nothing here to leak, which is the whole
    argument against the username box it replaces.
  * **the browser store is not authority.** ``/auth/callback`` writes the Flask session
    (:mod:`core.auth.session`), which is signed with the server's secret key. The Dash
    store is a copy for the layout callbacks to read.

Registered only when an IdP is configured, so a local run and the test suite are
unaffected — see :func:`register_auth`.
"""
from __future__ import annotations

from typing import Any, Optional

from flask import Blueprint, Flask, redirect, request, url_for

from core.auth.identity import Identity, from_claims
from core.auth.session import current_user, sign_in, sign_out
from core.auth.settings import CALLBACK_PATH, LOGIN_PATH, LOGOUT_PATH, OIDCSettings, load_settings
from core.store.users import get_or_create_sso_user
from logger import get_logger

log = get_logger(__name__)

#: Authlib's registry name for the one provider. A constant, not a setting: this app
#: signs in against exactly one IdP, and naming it after the vendor would make the
#: generic client look provider-specific.
CLIENT_NAME = "idp"


def build_client(app: Flask, settings: OIDCSettings):
    """Register the OIDC client on ``app`` and return it.

    Discovery does the work: the provider's own metadata document supplies the
    authorization, token, JWKS and end-session endpoints, so nothing here is written
    per-vendor and a tenant move is a change of one environment variable.
    """
    from authlib.integrations.flask_client import OAuth

    oauth = OAuth(app)
    oauth.register(
        name=CLIENT_NAME,
        server_metadata_url=settings.metadata_url,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        client_kwargs={"scope": settings.scopes},
    )
    return oauth.create_client(CLIENT_NAME)


def claims_from_token(client, token: dict) -> Optional[Identity]:
    """The identity in ``token``, preferring the id token and falling back to userinfo.

    The id token is the authenticated statement and is already signature-checked by the
    time it is here. Some providers (Entra, by default) put almost nothing in it, so the
    userinfo endpoint fills the gaps — merged rather than replaced, because ``sub`` is
    the one claim that must come from the token.
    """
    claims = dict(token.get("userinfo") or {})
    if not claims:
        try:
            claims = dict(client.userinfo(token=token) or {})
        except Exception as exc:  # noqa: BLE001 — a userinfo outage must not 500 the login
            log.warning("oidc: userinfo lookup failed: %s", exc)
    return from_claims(claims)


def build_blueprint(client, settings: OIDCSettings) -> Blueprint:
    """The three routes, with ``client`` injected so the flow is testable with a fake."""
    bp = Blueprint("va_auth", __name__)

    @bp.get(LOGIN_PATH)
    def login():
        """Start the flow. Already signed in? Go straight back to the app."""
        if current_user():
            return redirect("/")
        return client.authorize_redirect(_callback_url(settings))

    @bp.get(CALLBACK_PATH)
    def callback():
        """Finish the flow: exchange the code, validate the token, create the session.

        Any failure lands back on the sign-in screen with a reason in the query string
        rather than a stack trace — a user who cannot sign in needs a next step, and the
        detail belongs in the server log where it is not shown to them.
        """
        try:
            token = client.authorize_access_token()
        except Exception as exc:  # noqa: BLE001 — a bad/expired/replayed code is routine
            log.warning("oidc: token exchange failed: %s", exc)
            return redirect("/?auth=failed")
        identity = claims_from_token(client, token)
        if identity is None:
            log.warning("oidc: token carried no subject claim")
            return redirect("/?auth=noidentity")
        user = get_or_create_sso_user(identity)
        sign_in(user)
        _seed_profile(user)
        log.info("oidc: signed in user %s", user["id"])
        return redirect("/")

    @bp.get(LOGOUT_PATH)
    def logout():
        """Forget them here, then end the session at the provider if it supports it.

        Clearing only the local session is the bug people file as "logout does not log
        me out": the next click on Sign in goes back to a provider that still has a live
        session and returns instantly, signed in as the same person.
        """
        sign_out()
        end_session = _end_session_url(settings)
        return redirect(end_session or "/")

    return bp


def _callback_url(settings: OIDCSettings) -> str:
    """Where the provider sends the browser back to.

    Derived from the request so a developer needs no configuration, but overridable:
    behind a proxy that terminates TLS, the derived URL is the internal http:// one and
    will not match what is registered with the IdP.
    """
    return settings.redirect_uri or url_for("va_auth.callback", _external=True)


def _end_session_url(settings: OIDCSettings) -> str:
    """The provider's RP-initiated logout URL, or ``""`` when it publishes none.

    Not every provider does, and discovery can be down at the moment someone logs out —
    neither is a reason to fail the logout, so both fall back to the local one, which
    has already happened by the time this is called.
    """
    from urllib.parse import urlencode

    try:
        endpoint = str(_metadata().get("end_session_endpoint") or "")
    except Exception as exc:  # noqa: BLE001 — logout must work even if discovery is down
        log.warning("oidc: could not read end_session_endpoint: %s", exc)
        return ""
    if not endpoint:
        return ""
    return f"{endpoint}?{urlencode({'post_logout_redirect_uri': request.url_root})}"


def _metadata() -> dict:
    """The provider's discovery document, as Authlib cached it on the client."""
    from flask import current_app

    client = current_app.extensions.get("va_oidc_client")
    return dict(client.load_server_metadata()) if client is not None else {}


def _seed_profile(user: dict) -> None:
    """Give the greeting a name to use, exactly as the local sign-in does."""
    try:
        from core.memory import semantic

        semantic.set_fact(user["id"], "username", user["username"])
        semantic.set_fact(user["id"], "display_name", user["username"])
    except Exception as exc:  # noqa: BLE001 — a profile seed must not fail a sign-in
        log.warning("oidc: could not seed profile for %s: %s", user["id"], exc)


def register_auth(server: Flask) -> bool:
    """Wire SSO onto ``server``. Returns whether it was switched on.

    A no-op when no IdP is configured, which is what keeps ``python app.py`` and the
    test suite working on a laptop with no tenant: the login screen falls back to the
    username box (:func:`core.auth.settings.sso_enabled` is what it asks).
    """
    settings = load_settings()
    if not settings.enabled:
        log.info("auth: no OIDC issuer configured — local username sign-in is active")
        return False
    _ensure_secret_key(server)
    client = build_client(server, settings)
    server.extensions["va_oidc_client"] = client
    server.register_blueprint(build_blueprint(client, settings))
    log.info("auth: SSO enabled against %s", settings.issuer)
    return True


def _ensure_secret_key(server: Flask) -> None:
    """A signed session cookie needs a secret. A generated one is a last resort.

    Generated per process, so it does not survive a restart and does not work across
    more than one worker — both of which sign everybody out. That is the right failure
    for a missing secret (annoying, not insecure), and it is logged loudly enough to
    fix before it reaches more than one machine.
    """
    import os
    import secrets

    key = (os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY") or "").strip()
    if not key:
        key = secrets.token_urlsafe(32)
        log.warning(
            "auth: no FLASK_SECRET_KEY set — using a per-process key, so every restart "
            "signs everyone out and more than one worker will not share sessions"
        )
    server.secret_key = key
    server.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        # Lax, not Strict: the IdP redirects the browser back to /auth/callback as a
        # top-level GET, and Strict would withhold the cookie carrying the OAuth state
        # that the callback has to check.
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_secure_cookies(),
    )


def _secure_cookies() -> bool:
    """Whether to mark the session cookie Secure — on unless explicitly told otherwise.

    ``OIDC_INSECURE_TRANSPORT=1`` is the escape hatch for a developer testing the real
    flow over http://localhost, and is named so that nobody sets it in production by
    accident.
    """
    import os

    return (os.environ.get("OIDC_INSECURE_TRANSPORT", "") or "").strip().lower() not in {
        "1", "true", "on", "yes",
    }


__all__ = [
    "register_auth", "build_blueprint", "build_client", "claims_from_token", "CLIENT_NAME",
]
