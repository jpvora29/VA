"""Cut catalog package.

Public surface is the decorator + scoped registry in ``catalog``. Importing this
package imports the cut modules so their ``@cut`` registrations populate the
``CATALOG`` (metadata only — nothing is computed at import time).
"""
from __future__ import annotations

from studio.cuts.catalog import (
    CATALOG,
    CutContext,
    CutSpec,
    ScopedRegistry,
    UnknownCutError,
    build_scoped_registry,
    catalog,
    cut,
    cuts_for,
)

# Side-effect imports: register the built-in cuts. Keep this list explicit so the
# set of registered cuts is obvious and grep-able (no auto-discovery magic).
from studio.cuts import gpr_industry  # noqa: F401,E402 - registers GPR industry cuts

__all__ = [
    "CATALOG",
    "CutContext",
    "CutSpec",
    "ScopedRegistry",
    "UnknownCutError",
    "build_scoped_registry",
    "catalog",
    "cut",
    "cuts_for",
]
