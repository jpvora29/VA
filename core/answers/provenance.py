"""Where an answer came from — the record that makes it checkable.

The roadmap's trust layer (§7): a reader should be able to open any answer and
see the question as it was interpreted, the scope it ran under, the business
definition of every term it used, the queries behind it, and whether each figure
in the prose is actually present in the rows.

"AI can make mistakes" is not a trust layer. It tells the reader to doubt
everything equally, which is the same as telling them nothing. This record lets
them check the one number they care about.

Three verification states, and each says something different:

* ``verified``   — evidence was gathered, and every checkable figure in the
                   prose appears in it.
* ``partial``    — evidence was gathered, and at least one figure does not.
                   The unmatched figures are named, so the reader can judge.
* ``unverified`` — nothing was gathered to check against (an out-of-scope
                   answer, a lookup the rails answered from a cached value).

Built once, at commit time, from the finished turn — the same moment the scope
chips are stamped — because the graph state is in hand then and gone afterwards.
Pure and JSON-serialisable: it rides in the transcript and survives a reload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from core.answers import figures as fig
from core.definitions import get_glossary

VERIFIED = "verified"
PARTIAL = "partial"
UNVERIFIED = "unverified"

# What each state says on the badge, and the tone it wears.
STATE_LABEL = {
    VERIFIED: "Verified against the data",
    PARTIAL: "Partly verified",
    UNVERIFIED: "Not verified",
}
STATE_TONE = {VERIFIED: "good", PARTIAL: "warn", UNVERIFIED: "neutral"}

# "Not verified" is the one badge that needs a sentence beside it: on its own it
# reads as an accusation — the reader assumes the answer failed a check, when in
# fact no check was possible. The other two states are explained by the figure
# list itself (see `figures.summary`), which is more specific than a fixed line.
NO_EVIDENCE_NOTE = (
    "There was no data behind this answer to check it against, so none of its "
    "figures have been confirmed."
)


@dataclass(frozen=True)
class EvidenceQuery:
    """One query the turn ran, as the reader needs to see it."""

    lens: str
    sql: str
    row_count: int
    columns: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "lens": self.lens,
            "sql": self.sql,
            "row_count": self.row_count,
            "columns": list(self.columns),
        }


@dataclass(frozen=True)
class TermUsed:
    """A governed business term the answer leaned on, with its definition."""

    label: str
    definition: str
    formula: str = ""
    never: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "definition": self.definition,
            "formula": self.formula,
            "never": self.never,
        }


@dataclass(frozen=True)
class Provenance:
    """Everything needed to answer "where did this come from?"."""

    question: str = ""
    route: str = ""
    state: str = UNVERIFIED
    queries: List[EvidenceQuery] = field(default_factory=list)
    terms: List[TermUsed] = field(default_factory=list)
    figures: List[fig.Figure] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return sum(q.row_count for q in self.queries)

    @property
    def unsupported(self) -> List[fig.Figure]:
        return fig.unsupported(self.figures)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "route": self.route,
            "state": self.state,
            "queries": [q.as_dict() for q in self.queries],
            "terms": [t.as_dict() for t in self.terms],
            "figures": [
                {"text": f.text, "value": f.value, "supported": f.supported,
                 "checkable": f.is_checkable}
                for f in self.figures
            ],
            "coverage": fig.coverage(self.figures),
        }


def _rows_of(item: Mapping[str, Any]) -> List[Any]:
    rows = item.get("rows")
    return list(rows) if isinstance(rows, list) else []


def evidence_sets(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every query the turn ran, whichever path produced it.

    Analyst turns carry `analyst_evidence` (one entry per solver query); the
    deterministic rails carry one SQL string and one result set per lens. Both
    reduce to the same {lens, sql, rows} shape so the drawer reads the same
    whichever route answered.
    """
    evidence = state.get("analyst_evidence") or []
    if evidence:
        return [
            {
                "lens": str(item.get("lens") or item.get("flow") or "query"),
                "sql": str(item.get("sql") or ""),
                "rows": _rows_of(item),
            }
            for item in evidence
            if isinstance(item, Mapping) and _rows_of(item)
        ]

    sets: List[Dict[str, Any]] = []
    for lens, sql_key, rows_key in (
        ("premium", "gpr_sql_query", "gpr_query_result"),
        ("survey", "survey_sql_query", "survey_query_result"),
        ("gimmi", "gimmi_sql_query", "gimmi_query_result"),
    ):
        rows = state.get(rows_key)
        if isinstance(rows, list) and rows:
            sets.append({"lens": lens, "sql": str(state.get(sql_key) or ""), "rows": list(rows)})
    return sets


def _columns_of(rows: Sequence[Any]) -> List[str]:
    first = rows[0] if rows else None
    return [str(c) for c in first] if isinstance(first, Mapping) else []


def terms_used(text: str, columns: Sequence[str]) -> List[TermUsed]:
    """The governed terms this answer actually leans on.

    Matched against the prose AND the evidence's column names, because an answer
    can compute a share of wallet without ever writing the phrase. A term whose
    definition the reader cannot see is a term the answer can quietly stretch —
    which is what `never` in the glossary exists to stop.
    """
    # Column names are normalised: the row says `Share_of_Wallet` and the
    # glossary says "share of wallet", and an underscore should not hide a term
    # the answer is plainly built on.
    named = " ".join(str(c).replace("_", " ") for c in columns)
    haystack = " ".join([text or "", named]).lower()
    glossary = get_glossary()
    found: List[TermUsed] = []
    seen: set = set()
    for key in glossary.keys():
        term = glossary.get(key)
        if term is None or term.key in seen:
            continue
        names = [term.label, *term.aliases, term.key.replace("_", " ")]
        if any(name and name.lower() in haystack for name in names):
            seen.add(term.key)
            found.append(
                TermUsed(
                    label=term.label,
                    definition=term.definition,
                    formula=term.formula,
                    never=term.never,
                )
            )
    return found


def verification_state(queries: Sequence[EvidenceQuery], checked: Sequence[fig.Figure]) -> str:
    """The badge this answer earns.

    An answer with no evidence is UNVERIFIED rather than verified-by-default:
    "nothing to check against" and "checked and correct" must never look alike.
    """
    if not queries or not any(q.row_count for q in queries):
        return UNVERIFIED
    return PARTIAL if fig.unsupported(checked) else VERIFIED


def reverify(record: Mapping[str, Any], answer: str, rows: Sequence[Any]) -> Dict[str, Any]:
    """Re-run the figure check over an EDITED answer, keeping the rest.

    An answer a person rewrote must not keep a badge earned by the text it
    replaced — a panel that says "verified" about words nobody checked is worse
    than no panel. So the check runs again over what is now on screen: type a
    figure the rows do not contain and the badge says so, and names it, exactly
    as it would for the model.

    The queries and the definitions are untouched: those describe how the data
    was gathered, which an edit does not change.
    """
    record = dict(record or {})
    checked = fig.check(answer, {"answer": list(rows or [])})
    queries = [
        EvidenceQuery(
            lens=str(q.get("lens") or ""),
            sql=str(q.get("sql") or ""),
            row_count=int(q.get("row_count") or 0),
            columns=list(q.get("columns") or []),
        )
        for q in (record.get("queries") or [])
    ]
    record["state"] = verification_state(queries, checked)
    record["figures"] = [
        {"text": f.text, "value": f.value, "supported": f.supported, "checkable": f.is_checkable}
        for f in checked
    ]
    record["coverage"] = fig.coverage(checked)
    record["edited"] = True
    return record


def build(state: Mapping[str, Any], answer: str, *, question: str = "") -> Provenance:
    """The provenance record for one finished answer."""
    sets = evidence_sets(state)
    queries = [
        EvidenceQuery(
            lens=item["lens"],
            sql=item["sql"],
            row_count=len(item["rows"]),
            columns=_columns_of(item["rows"]),
        )
        for item in sets
    ]
    checked = fig.check(answer, {item["lens"]: item["rows"] for item in sets})
    columns = [c for q in queries for c in q.columns]
    return Provenance(
        question=(question or str(state.get("rephrased_user_query") or "")).strip(),
        route=str(state.get("current_route") or ""),
        state=verification_state(queries, checked),
        queries=queries,
        terms=terms_used(answer, columns),
        figures=checked,
    )


def checked_figures(record: Mapping[str, Any]) -> List[fig.Figure]:
    """The figure check from a STORED record, back as `Figure`s.

    A record makes the round trip through the transcript as plain JSON, so by the
    time the drawer renders it the figures are dicts. Rehydrating them here keeps
    the wording of the check in one place (`core.answers.figures`) instead of
    re-deriving it from dict keys in the view.
    """
    out: List[fig.Figure] = []
    for item in (record or {}).get("figures") or []:
        if not isinstance(item, Mapping):
            continue
        if not item.get("checkable", True):
            continue  # years and ordinals were never claims — see `figures._TRIVIAL`
        out.append(
            fig.Figure(
                text=str(item.get("text") or ""),
                value=str(item.get("value") or ""),
                supported=bool(item.get("supported")),
            )
        )
    return out
