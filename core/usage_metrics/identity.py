"""Who is using the app, read from the machine they run it on.

Each user runs the app on their own laptop, so the Windows login IS the user:

    user id  ``getpass.getuser()`` — the Windows login name (e.g. the corporate ID)
    email    the login's User Principal Name (``GetUserNameExW``), which on a
             company-joined laptop is the work email; else the email of the signed-in
             OneDrive for Business account; else the app's SSO username when it is
             an email address; else blank.

The machine lookups are cached: they cannot change while the process runs.
"""

from __future__ import annotations

import ctypes
import getpass
import os
import sys
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from core.usage_metrics.events import UsageActor

_NAME_USER_PRINCIPAL = 8  # EXTENDED_NAME_FORMAT.NameUserPrincipal
_ONEDRIVE_ACCOUNTS = r"Software\Microsoft\OneDrive\Accounts"


def current_actor(app_username: str | None = None) -> UsageActor:
    """The person at this machine; ``app_username`` only fills a missing email."""
    return UsageActor(user_id=system_user_id(), email=resolve_email(app_username))


def actor_for_store(user_store: Mapping[str, Any] | None) -> UsageActor | None:
    """The actor behind a browser ``user-store``, or ``None`` before sign-in."""
    if not user_store or user_store.get("id") is None:
        return None
    return current_actor(user_store.get("username"))


def actor_for_app_user(app_user_id: int | str | None) -> UsageActor | None:
    """The actor for an app user id — for a chat turn finishing on a worker thread."""
    if app_user_id is None:
        return None
    try:
        from core.store.users import get_user

        username = (get_user(app_user_id) or {}).get("username")
    except Exception:  # noqa: BLE001 — the machine identity is enough on its own
        username = None
    return current_actor(username)


@lru_cache(maxsize=1)
def system_user_id() -> str:
    """The OS login name of the person running the app."""
    try:
        return getpass.getuser().strip()
    except Exception:  # noqa: BLE001 — no login name in this environment
        return os.environ.get("USERNAME", "").strip()


@lru_cache(maxsize=1)
def system_email() -> str:
    """The work email of the person running the app, or ``""`` when none is found."""
    return windows_upn() or onedrive_business_email()


def resolve_email(app_username: str | None = None) -> str:
    """The machine email, else the app username when it is an email address."""
    email = system_email()
    if email:
        return email
    name = (app_username or "").strip()
    return name.lower() if "@" in name else ""


def windows_upn() -> str:
    """The login's User Principal Name (``name@company.com``) on a domain-joined PC."""
    if sys.platform != "win32":
        return ""
    try:
        get_name = ctypes.windll.secur32.GetUserNameExW
        size = ctypes.c_ulong(0)
        get_name(_NAME_USER_PRINCIPAL, None, ctypes.byref(size))
        if not size.value:
            return ""
        buffer = ctypes.create_unicode_buffer(size.value)
        if not get_name(_NAME_USER_PRINCIPAL, buffer, ctypes.byref(size)):
            return ""
    except Exception:  # noqa: BLE001 — not on a domain, or the call is unavailable
        return ""
    return _as_email(buffer.value)


def onedrive_business_email() -> str:
    """The email of the first signed-in OneDrive for Business account (Business1…)."""
    if sys.platform != "win32":
        return ""
    import winreg

    for index in range(1, 10):
        key_path = rf"{_ONEDRIVE_ACCOUNTS}\Business{index}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "UserEmail")
        except OSError:
            continue
        email = _as_email(str(value))
        if email:
            return email
    return ""


def _as_email(value: str) -> str:
    text = (value or "").strip().lower()
    return text if "@" in text else ""
