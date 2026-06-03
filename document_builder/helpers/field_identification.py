from typing import Any
import re

# --- LLM Field Resolution -----------------------------------------------------

_FIELD_SPECS: dict[str, dict[str, list[str]]] = {
    "carrier": {
        "include": ["carrier", "carriergroup", "carriername", "insurer", "company"],
        "exclude": [],
    },
    "year": {"include": ["year", "surveyyear"], "exclude": []},
    "product": {
        "include": [
            "productline",
            "product",
            "surveypractice",
            "practice",
            "lineofbuiness",
            "lob",
        ],
        "exclude": [],
    },
    "section": {"include": ["section", "category", "dimension"], "exclude": []},
    "industry": {
        "include": [
            "industry",
            "sicmajorclass",
            "sicminorclass",
            "sicmajor",
            "sicminor",
            "sic",
            "sector",
        ],
        "exclude": [],
    },
    "segment": {
        "include": [
            "segment",
            "clientsegment",
            "customersegment",
            "surveysegment",
            "businesssegment",
        ],
        "exclude": [],
    },
    "attribute": {
        "include": ["attribute", "factor", "driver", "metric"],
        "exclude": [],
    },
    "premium": {
        "include": ["premium", "gwp", "grosspremium", "writtenpremium"],
        "exclude": ["change", "delta", "growth", "yoy", "prior", "previous"],
    },
    "yoy": {
        "include": [
            "yoy",
            "yearoveryear",
            "growthpct",
            "growthpercentage",
            "yoygrowth",
        ],
        "exclude": [],
    },
    "rank": {
        "include": ["rank", "ranking", "position"],
        "exclude": ["change", "delta", "diff", "movement"],
    },
    "rank_change": {
        "include": [
            "rankchange",
            "rankdelta",
            "deltarank",
            "rankdiff",
            "rankmovement",
            "rankshift",
            "rankyoy",
            "movement",
            "shift",
        ],
        "exclude": [],
    },
    "sow": {
        "include": [
            "sow",
            "shareofwallet",
            "walletshare",
            "marshshare",
            "shareofbook",
            "bookshare",
        ],
        "exclude": [],
    },
    "appetite": {
        "include": ["apptite"],
        "exclude": ["marsh", "delta", "change", "diff"],
    },
    "marsh_appetite": {"include": ["marshappetite"], "exclude": []},
    "peer_avg": {
        "include": ["peeraverage", "peeravg", "peermean", "peerbenchmark"],
        "exclude": [],
    },
    "score": {
        "include": ["score", "carriersurveyscore", "surveyscore"],
        "exclude": ["rank", "change"],
    },
}


def _normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key).lower())


def find_field(row: dict[str, Any], field_key: str) -> Any:
    """Locate a value in a dict-row by fuzzy keyword match."""

    if not row:
        return None
    spec = _FIELD_SPECS.get(field_key)
    if not spec:
        return row.get(field_key)
    includes = spec["include"]
    excludes = spec["exclude"]

    candidates: list[tuple[str, Any]] = []
    for k, v in row.items():
        if k == "__source_table" or v in (None, "", "-"):
            continue
        nk = _normalize_key(k)
        if not nk or any(ex in nk for ex in excludes):
            continue
        candidates.append((nk, v))

    for inc in includes:
        for nk, v in candidates:
            if nk == inc:
                return v

    for inc in includes:
        for nk, v in candidates:
            if inc in nk:
                return v
    return None


def classify_question(question: str) -> str:
    q = (question or "").lower()
    if "appetite" in q:
        return "appetite"
    if "peer" in q:
        return "peer"
    if "top and bottom" in q or "top/bottom" in q:
        return "broker_perception"
    if "share" in q:
        return "share"
    if "rank" in q:
        return "rank"
    return "generic"
