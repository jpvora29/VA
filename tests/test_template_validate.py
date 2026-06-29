"""Live validation + auto-fix re-run for the template doc.

The bug this guards: issues used to be computed once and never re-checked. Here we
plant a blanked override, assert it's flagged as auto-fixable, run ``auto_fix``, and
assert the re-run count drops to zero — proving validation is live, not frozen.
"""
from __future__ import annotations

from studio.compute import compute_overall
from studio.template_fill import validate as V
from studio.template_fill.model import materialize_fields, new_template_doc, set_override

TEMPLATE = "template/qbr_template.pptx"


def _doc():
    return new_template_doc(compute_overall(filters={"carrier": "Zurich", "year": 2025}),
                            template_path=TEMPLATE)


def _first_mapped_key(doc):
    for key, fld in materialize_fields(doc).items():
        if fld["role"] and fld["filled"]:
            return key
    raise AssertionError("no mapped+filled slot")


def test_clean_doc_has_no_blanked_issues():
    assert V.summary(_doc())["errors"] == 0


def test_blanked_override_is_flagged_then_auto_fixed():
    doc = _doc()
    key = _first_mapped_key(doc)
    doc = set_override(doc, key, "   ")          # user clears a mapped value

    issues = V.validate_doc(doc)
    blanked = [i for i in issues if i["category"] == "blanked"]
    assert blanked and blanked[0]["auto_fixable"]

    fixed = V.auto_fix(doc)                       # repair + (implicit) re-check
    after = V.validate_doc(fixed)
    assert not [i for i in after if i["category"] == "blanked"]


def test_summary_counts_drop_after_auto_fix():
    doc = _doc()
    doc = set_override(doc, _first_mapped_key(doc), "")
    before = V.summary(doc)["total"]
    after = V.summary(V.auto_fix(doc))["total"]
    assert after < before
