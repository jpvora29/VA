"""SSO: sign in at the identity provider, not at a username box.

The sign-in this replaces was a name field with no password — anyone who could reach the
address could be anyone. What replaces it is a generic OIDC authorization-code flow, so
the credential never reaches this app at all, and the same client works against Entra ID,
Okta, Google Workspace and Auth0 by changing one environment variable.

The risks worth pinning down are not the protocol (that is Authlib's) but the seams
around it:

  * claim shapes differ per provider, and reading them wrong silently creates a second
    account for someone who already has one;
  * an account key has to be stable, or history is lost on the next sign-in;
  * signing out has to reach the provider, or the next click signs you straight back in;
  * with no IdP configured, everything must fall back to the username sign-in, or a
    laptop and this test suite cannot run the app at all.
"""
from __future__ import annotations

import pytest
from flask import Flask

from core.auth.identity import Identity, from_claims
from core.auth.settings import OIDCSettings, load_settings, sso_enabled


# ── configuration ────────────────────────────────────────────────────────────


@pytest.fixture
def no_idp(monkeypatch):
    for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET",
                 "OIDC_SCOPES", "OIDC_PROVIDER_NAME", "OIDC_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def entra(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://login.microsoftonline.com/tenant-id/v2.0")
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "shhh")
    monkeypatch.setenv("OIDC_PROVIDER_NAME", "Microsoft")
    monkeypatch.delenv("OIDC_REDIRECT_URI", raising=False)


def test_sso_is_off_until_an_issuer_is_configured(no_idp):
    """A laptop with no tenant must still run the app."""
    from core.auth.settings import describe

    assert sso_enabled() is False
    assert "local mode" in describe()


def test_a_partial_configuration_is_not_half_enabled(monkeypatch, no_idp):
    """An issuer with no secret is a misconfiguration, not a reduced-security mode."""
    monkeypatch.setenv("OIDC_ISSUER", "https://accounts.google.com")
    assert sso_enabled() is False


@pytest.mark.parametrize("issuer", [
    "https://login.microsoftonline.com/tenant-id/v2.0",     # Entra ID
    "https://acme.okta.com/oauth2/default",                 # Okta
    "https://accounts.google.com",                          # Google Workspace
    "https://acme.eu.auth0.com/",                           # Auth0 (trailing slash)
])
def test_one_client_discovers_every_provider(issuer):
    """The whole argument for a generic client: the discovery URL is the same shape."""
    settings = OIDCSettings(issuer=issuer, client_id="c", client_secret="s")
    assert settings.metadata_url.endswith("/.well-known/openid-configuration")
    assert "//.well-known" not in settings.metadata_url, "a trailing slash must not double"


def test_the_button_names_the_provider(entra):
    assert load_settings().provider_name == "Microsoft"


# ── claims → one person, across providers ────────────────────────────────────


def test_entra_sends_its_address_as_preferred_username():
    """Entra's default id token has no `email` claim at all. Reading only `email`
    would key every Microsoft user on their opaque `sub`."""
    identity = from_claims({"sub": "oid-1", "preferred_username": "Jash@marsh.com",
                            "name": "Jash Vora"})
    assert identity.email == "jash@marsh.com"      # lower-cased: an address is an address
    assert identity.key == "jash@marsh.com"
    assert identity.label == "Jash Vora"


def test_okta_and_google_send_email_and_it_wins():
    identity = from_claims({"sub": "s", "email": "a@b.com",
                            "preferred_username": "not-an-address", "name": "A B"})
    assert identity.email == "a@b.com"


def test_a_preferred_username_that_is_not_an_address_is_not_stored_as_one():
    """Guest and federated accounts send a display string here. Left as an email it
    would later be matched against somebody's real address."""
    identity = from_claims({"sub": "guest-1", "preferred_username": "Jash (Guest)"})
    assert identity.email == ""
    assert identity.key == "guest-1", "falls back to the one claim that is always unique"
    assert identity.label == "Jash (Guest)"


def test_a_token_with_no_subject_is_not_an_authentication():
    """Signing someone in as "" would hand every such caller the same account."""
    assert from_claims({"email": "a@b.com"}) is None
    assert from_claims({}) is None
    assert from_claims(None) is None


def test_the_key_is_stable_when_the_display_name_changes():
    """A rename at the IdP must not orphan somebody's conversations."""
    before = from_claims({"sub": "s", "email": "a@b.com", "name": "A Before"})
    after = from_claims({"sub": "s", "email": "a@b.com", "name": "A After"})
    assert before.key == after.key
    assert before.label != after.label


# ── the account row ──────────────────────────────────────────────────────────
#
# These touch the real app-state database (``app_engine`` is bound at import, so an
# APP_DB_PATH set here would come too late). The accounts they create are removed
# afterwards, or a test run would leave fake people in a developer's own sidebar.


@pytest.fixture
def scratch_accounts():
    """Yield a list to record account keys in; delete those rows on the way out."""
    keys: list[str] = []
    yield keys
    from sqlalchemy import delete

    from core.store.db import app_engine, users

    with app_engine.begin() as conn:
        for key in keys:
            conn.execute(delete(users).where(users.c.username == key))


def test_signing_in_twice_is_one_account(scratch_accounts):
    from core.store.users import get_or_create_sso_user

    scratch_accounts.append("dup@marsh.com")
    identity = Identity(subject="oid-9", email="dup@marsh.com", display_name="Dup One")
    first = get_or_create_sso_user(identity)
    second = get_or_create_sso_user(Identity(subject="oid-9", email="dup@marsh.com",
                                             display_name="Dup Renamed"))
    assert first["id"] == second["id"]
    assert second["username"] == "Dup Renamed", "the label follows the IdP"


def test_an_sso_user_adopts_the_local_row_with_the_same_key(scratch_accounts):
    """Somebody who used the username box with their email address before SSO was
    switched on keeps their history rather than starting again beside a duplicate."""
    from core.store.users import get_or_create_sso_user, get_or_create_user

    scratch_accounts.append("adopted@marsh.com")
    local = get_or_create_user("adopted@marsh.com")
    sso = get_or_create_sso_user(
        Identity(subject="oid-10", email="adopted@marsh.com", display_name="Adopted")
    )
    assert sso["id"] == local["id"]


def test_an_identity_with_no_key_is_refused():
    from core.store.users import get_or_create_sso_user

    with pytest.raises(ValueError):
        get_or_create_sso_user(Identity(subject="", email=""))


# ── the routes ───────────────────────────────────────────────────────────────


class _FakeClient:
    """Stands in for the Authlib client — the protocol is the library's to get right."""

    def __init__(self, token=None, fail=False):
        self.token, self.fail = token or {}, fail
        self.redirected_to = None

    def authorize_redirect(self, redirect_uri):
        self.redirected_to = redirect_uri
        return "redirected"

    def authorize_access_token(self):
        if self.fail:
            raise RuntimeError("bad code")
        return self.token

    def userinfo(self, token=None):
        return {}


def _server(client) -> Flask:
    from core.auth.oidc import build_blueprint

    app = Flask(__name__)
    app.secret_key = "test-key"
    app.register_blueprint(build_blueprint(client, OIDCSettings(
        issuer="https://idp.example/", client_id="c", client_secret="s")))
    return app


def test_a_successful_callback_signs_the_person_in(scratch_accounts):
    from core.auth.session import SESSION_KEY

    scratch_accounts.append("flow@marsh.com")
    client = _FakeClient(token={"userinfo": {"sub": "oid-11", "email": "flow@marsh.com",
                                             "name": "Flow Tester"}})
    with _server(client).test_client() as http:
        response = http.get("/auth/callback")
        assert response.status_code == 302 and response.headers["Location"] == "/"
        from flask import session

        assert session[SESSION_KEY]["username"] == "Flow Tester"


def test_a_failed_exchange_lands_back_on_the_sign_in_screen():
    """A replayed or expired code is routine. The user needs a next step, not a 500."""
    with _server(_FakeClient(fail=True)).test_client() as http:
        response = http.get("/auth/callback")
        assert response.status_code == 302
        assert response.headers["Location"] == "/?auth=failed"


def test_a_token_without_a_subject_does_not_sign_anyone_in():
    from core.auth.session import SESSION_KEY

    client = _FakeClient(token={"userinfo": {"email": "nosub@marsh.com"}})
    with _server(client).test_client() as http:
        response = http.get("/auth/callback")
        assert response.headers["Location"] == "/?auth=noidentity"
        from flask import session

        assert SESSION_KEY not in session


def test_logout_clears_the_server_session(scratch_accounts):
    """Clearing only the browser store is the bug people file as "logout does not log
    me out" — the next render would adopt the live session straight back."""
    from core.auth.session import SESSION_KEY

    scratch_accounts.append("out@marsh.com")
    client = _FakeClient(token={"userinfo": {"sub": "oid-12", "email": "out@marsh.com"}})
    app = _server(client)
    with app.test_client() as http:
        http.get("/auth/callback")
        http.get("/auth/logout")
        from flask import session

        assert SESSION_KEY not in session


def test_login_while_already_signed_in_does_not_round_trip_to_the_provider(scratch_accounts):
    scratch_accounts.append("again@marsh.com")
    client = _FakeClient(token={"userinfo": {"sub": "oid-13", "email": "again@marsh.com"}})
    app = _server(client)
    with app.test_client() as http:
        http.get("/auth/callback")
        response = http.get("/auth/login")
        assert response.headers["Location"] == "/"
        assert client.redirected_to is None


def test_the_callback_url_can_be_pinned_for_a_proxy():
    """Behind TLS termination the derived URL is the internal http:// one, which will
    not match what is registered with the IdP."""
    from core.auth.oidc import _callback_url

    settings = OIDCSettings(issuer="https://idp/", client_id="c", client_secret="s",
                            redirect_uri="https://analyst.marsh.com/auth/callback")
    assert _callback_url(settings) == "https://analyst.marsh.com/auth/callback"


# ── the session is not the browser store ─────────────────────────────────────


def test_no_server_session_without_a_secret_key():
    """Local mode sets no secret key, and Flask raises the moment the session is
    touched. That has to read as "nobody is signed in", not as a crash on every page."""
    from core.auth.session import current_user, sign_in

    app = Flask(__name__)                      # deliberately no secret_key
    with app.test_request_context("/"):
        sign_in({"id": 1, "username": "x"})    # must not raise
        assert current_user() is None


def test_the_session_round_trips_a_user():
    from core.auth.session import current_user, sign_in, sign_out

    app = Flask(__name__)
    app.secret_key = "k"
    with app.test_request_context("/"):
        sign_in({"id": 7, "username": "Seven"})
        assert current_user() == {"id": 7, "username": "Seven"}
        sign_out()
        assert current_user() is None


# ── the login screen ─────────────────────────────────────────────────────────


def test_the_login_screen_offers_sso_when_it_is_configured(entra):
    from core.auth.settings import LOGIN_PATH
    from ui.components.sidebar import login_screen

    card = str(login_screen())
    assert "Sign in with Microsoft" in card
    assert LOGIN_PATH in card


def test_the_login_screen_keeps_the_username_box_reachable_only_in_local_mode(entra):
    """The field must stay in the DOM — `handle_login` is registered unconditionally and
    Dash refuses a callback whose Input the app can never render — but it must not be a
    way in when an identity provider is configured."""
    from ui.components.sidebar import login_screen

    assert "login-username" in str(login_screen()), "the component still exists"
    assert "login-local-hidden" in str(login_screen()), "…inside the hidden wrapper"


def test_local_mode_says_so_on_the_card(no_idp):
    """Nobody should have to read the environment to find out the app is unprotected."""
    from ui.components.sidebar import login_screen

    card = str(login_screen())
    assert "login-local-hidden" not in card
    assert "Local mode" in card


def test_the_hidden_username_box_is_actually_unreachable():
    """`display: none` and nothing weaker — a merely-invisible field is still tabbable."""
    import pathlib

    css = pathlib.Path("assets/va_shell.css").read_text(encoding="utf-8")
    block = css.split(".login-local-hidden {", 1)[1].split("}", 1)[0]
    assert "display: none" in block
