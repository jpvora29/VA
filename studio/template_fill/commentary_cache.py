"""Commentary a model already wrote, kept until something that changes it changes.

Re-exporting a deck, nudging a font, or rebuilding after a Windows temp sweep should not
cost a single model call: the evidence did not move, so the right words have not moved
either. Equally, a data refresh must not be papered over with yesterday's sentences.

Both of those are one question — *what would make this answer wrong?* — and the key is the
answer:

    carrier + topic + line count + the rendered EVIDENCE + the column's brief
      + voice/style + prompt version + tier + deployment

Anything in that list changing produces a different key and a fresh call; anything outside
it (which slide the column lands on, the file name, the export format) does not. The
evidence is hashed from its RENDERED lines rather than the raw fact dict, because that is
exactly what the model was shown — a fact that recomputes to the same displayed value is
the same evidence, and a float that drifts in the sixteenth decimal place is not new news.

**Where it lives.** A small JSON file per entry under ``STUDIO_COMMENTARY_CACHE`` (default:
a ``commentary`` directory beside the other Studio caches). On disk rather than in memory
because the point is to survive the process — the app is restarted between a Generate and
the export far more often than it is not. Reads and writes are individually best-effort: a
cache that cannot be read costs a model call, and a cache that cannot be written costs
nothing at all, so neither may ever raise into a build.

**Not a memo.** :mod:`studio.memo` is build-scoped and deliberately discarded; this
outlives the build on purpose, which is why the key has to carry everything above.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from logger import get_logger

logger = get_logger(__name__)

#: Entries older than this are ignored and swept. Long enough to span a working session and
#: an export, short enough that a stale answer cannot follow a carrier into next quarter.
DEFAULT_TTL_DAYS = 7

_DISABLED = {"off", "0", "false", "no"}

#: Field separator inside the hashed payload. A character no prompt or carrier name
#: contains, so two different key tuples cannot join to the same string.
_SEP = ""


@dataclass(frozen=True)
class CacheKey:
    """Everything that would make a cached column the wrong answer."""

    subject: str
    topic: str
    bullets: int
    evidence: str            # the rendered evidence lines, joined
    brief: str               # the column's own rules — brief, questions, voice
    style: str
    prompt_version: str
    tier: str
    deployment: str
    #: A digest of the deterministic draft. In it because the draft carries the CLAIM
    #: SELECTION the ledger made for this column, and two columns on one page can share a
    #: topic and a length while asking for different claims — the summary page's survey
    #: column is exactly that. Without it they would share one cached answer and the
    #: survey pointer would silently vanish from the page that owns it.
    draft: str = ""

    def digest(self) -> str:
        payload = _SEP.join([
            self.subject, self.topic, str(self.bullets), self.evidence, self.brief,
            self.style, self.prompt_version, self.tier, self.deployment, self.draft,
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def evidence_digest(lines: Sequence[str]) -> str:
    """A stable digest of the rendered evidence a column was shown."""
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


def enabled() -> bool:
    """``STUDIO_COMMENTARY_CACHE=off`` turns it off; anything else leaves it on."""
    return (os.getenv("STUDIO_COMMENTARY_CACHE", "") or "").strip().lower() not in _DISABLED


def cache_dir() -> Path:
    """Where entries live — ``STUDIO_COMMENTARY_CACHE`` when it names a directory."""
    configured = (os.getenv("STUDIO_COMMENTARY_CACHE", "") or "").strip()
    if configured and configured.lower() not in _DISABLED:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "_cache" / "commentary"


def _ttl_seconds() -> float:
    try:
        return float(os.getenv("STUDIO_COMMENTARY_CACHE_DAYS", DEFAULT_TTL_DAYS)) * 86400
    except ValueError:
        return DEFAULT_TTL_DAYS * 86400


def _path(key: CacheKey) -> Path:
    return cache_dir() / f"{key.digest()}.json"


def get(key: CacheKey) -> Optional[str]:
    """The cached text for this key, or ``None`` — never raises."""
    if not enabled():
        return None
    path = _path(key)
    try:
        if not path.exists():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(entry.get("written_at") or 0) > _ttl_seconds():
            return None
        text = entry.get("text")
        return text if isinstance(text, str) and text.strip() else None
    except Exception as exc:  # noqa: BLE001 — a miss costs a call, an exception costs the build
        logger.debug("commentary_cache: unreadable entry %s (%s)", path.name, exc)
        return None


def put(key: CacheKey, text: str) -> None:
    """Store the text for this key. Silent on any failure — never raises."""
    if not enabled() or not (text or "").strip():
        return
    try:
        directory = cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        _path(key).write_text(json.dumps({
            "written_at": time.time(), "text": text, "subject": key.subject,
            "topic": key.topic, "prompt_version": key.prompt_version,
            "deployment": key.deployment,
        }), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — an unwritable cache must cost nothing
        logger.debug("commentary_cache: could not write %s (%s)", key.digest(), exc)


def clear() -> int:
    """Drop every entry; returns how many went. For tests and for an operator."""
    directory = cache_dir()
    if not directory.exists():
        return 0
    gone = 0
    for entry in directory.glob("*.json"):
        try:
            entry.unlink()
            gone += 1
        except OSError:                     # noqa: PERF203 — one locked file must not stop the sweep
            continue
    return gone
