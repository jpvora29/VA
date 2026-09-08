"""Who signed in, read out of an OIDC token's claims.

Pure mapping, no IO — which matters more than it looks. Providers disagree about which
claim carries a person's name and email (Entra sends ``preferred_username`` and often no
``email`` at all; Okta sends ``email``; Google sends both plus ``name``), and getting
that wrong silently creates a second account for someone who already has one. Keeping it
a pure function over a dict means every provider's real claim shape can be a test.

The account KEY is chosen for stability, not for looks. ``sub`` is the only claim an IdP
guarantees is unique and permanent, but it is an opaque string, and a database full of
opaque strings is unusable for support. So the key is the email address where there is
one — people keep those, and they are what an admin searches by — and ``sub`` only when
there is not.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

#: Claims that may carry an email address, best first. Entra's ``preferred_username`` is
#: an email in almost every tenant, and is the only one it sends by default.
_EMAIL_CLAIMS = ("email", "preferred_username", "upn", "unique_name")

#: Claims that may carry a human name, best first.
_NAME_CLAIMS = ("name", "given_name", "preferred_username", "email")


@dataclass(frozen=True)
class Identity:
    """One signed-in person, normalised across providers."""

    subject: str
    email: str = ""
    display_name: str = ""

    @property
    def key(self) -> str:
        """The stable account key: the email address, else the provider's subject id."""
        return self.email or self.subject

    @property
    def label(self) -> str:
        """What the navbar shows — a name if the IdP sent one, else the account key."""
        return self.display_name or self.key


def _first(claims: Mapping[str, Any], names: tuple) -> str:
    for name in names:
        value = str(claims.get(name) or "").strip()
        if value:
            return value
    return ""


def from_claims(claims: Optional[Mapping[str, Any]]) -> Optional[Identity]:
    """The identity in an OIDC ``userinfo`` / id-token claim set, or ``None``.

    ``None`` rather than a partial identity when there is no subject: a token without
    one is not an authentication result, and signing someone in as "" would hand every
    such caller the same account.
    """
    claims = claims or {}
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        return None
    email = _first(claims, _EMAIL_CLAIMS).lower()
    return Identity(
        subject=subject,
        # Only an address is an address. Entra sends `preferred_username` for guest and
        # federated accounts as something that is not one, and a display name in the
        # email column would later be matched against a real address.
        email=email if "@" in email else "",
        display_name=_first(claims, _NAME_CLAIMS),
    )


__all__ = ["Identity", "from_claims"]
