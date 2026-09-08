"""The signed-in user, as the server remembers it.

The browser store (``user-store``) is what the Dash callbacks read, and it is not proof
of anything: it lives in the browser, so anyone can put an id in it. Under SSO the
authority is this — a Flask session cookie, signed with the server's secret key, written
only after the identity provider's token has been validated.

The two travel together: the Flask session says who the IdP vouched for, and the store is
the copy the layout callbacks read on every render. :func:`current_user` is what lets a
page reload re-adopt a session without another round trip to the IdP.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

#: Key inside the Flask session. Namespaced because the session cookie is shared with
#: anything else on the server that wants one (Authlib keeps its OAuth state there too).
SESSION_KEY = "va_user"


def _session() -> Optional[Any]:
    """The Flask session, or ``None`` when there is not a usable one.

    Two ways there is not, and both must read as "nobody is signed in" rather than
    raise. Outside a request context there is no session at all — these functions are
    imported by tests and by module-level code as well as by callbacks. And with no
    secret key, Flask raises the moment the session is touched: that is the state a
    local run is in (``register_auth`` only sets a key when SSO is on), where the
    browser store is the whole of the sign-in and a server session is not wanted.
    """
    try:
        from flask import current_app, has_request_context, session
    except ImportError:  # pragma: no cover — Flask ships with Dash
        return None
    if not has_request_context():
        return None
    return session if getattr(current_app, "secret_key", None) else None


def sign_in(user: Dict[str, Any]) -> None:
    """Record ``{"id", "username"}`` as the session's signed-in user."""
    session = _session()
    if session is None:
        return
    session[SESSION_KEY] = {"id": int(user["id"]), "username": str(user["username"])}
    # A sign-in that survives the browser being closed is a sign-in nobody performed.
    session.permanent = False


def current_user() -> Optional[Dict[str, Any]]:
    """The signed-in user for this request, or ``None``."""
    session = _session()
    user = (session or {}).get(SESSION_KEY)
    if not isinstance(user, dict) or user.get("id") is None:
        return None
    return {"id": int(user["id"]), "username": str(user.get("username") or "")}


def sign_out() -> None:
    """Forget the signed-in user — and Authlib's in-flight OAuth state with them."""
    session = _session()
    if session is None:
        return
    session.pop(SESSION_KEY, None)
    for key in [k for k in list(session) if str(k).startswith("_state_")]:
        session.pop(key, None)


__all__ = ["SESSION_KEY", "sign_in", "current_user", "sign_out"]
