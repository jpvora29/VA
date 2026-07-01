"""Merge engine — concatenate several filled ``.pptx`` files into one deck.

The split-template model fills small author-made sub-decks separately (``overall``,
one ``product`` deck per product, one ``country`` deck per country) and then stitches
them, in order, into a single presentation. python-pptx has no native "append the
slides of deck B onto deck A", so this does it at the OPC layer.

How it works (and why it survives think-cell / native charts):
  * a slide is copied by cloning its *part graph* — the slide part plus every part it
    reaches (layout → master → theme, images, charts + their embedded workbooks, and
    think-cell OLE objects) — into the destination package;
  * each clone keeps the **original bytes** of its source part, and its relationships are
    rebuilt with the **same rId keys**, so the in-XML ``r:embed`` / ``r:id`` references
    inside the copied blob stay valid without ever editing the XML — nothing is
    re-serialized, so OLE objects and externally-linked charts are not disturbed;
  * fresh, collision-free partnames are allocated in the destination so two decks that
    both ship ``/ppt/slides/slide1.xml`` don't clash.

Entry points:
    ``merge_pptx(paths) -> Presentation``     stitch in order, return the live object
    ``merge_to_file(paths, out_path) -> str``  …and save it
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set

from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TARGET_MODE as RTM
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part, _Relationship
from pptx.opc.packuri import PackURI

from logger import get_logger

logger = get_logger(__name__)

# A slide part's own forward relationship — every appended slide gets exactly one of
# these from the destination presentation part.
_SLIDE_RELTYPE = RT.SLIDE

_TRAILING_INT = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")


def _name_template(partname: PackURI) -> str:
    """A printf template for new partnames in the same folder/extension as ``partname``.

    ``/ppt/media/image3.png`` → ``/ppt/media/image%d.png``;
    ``/ppt/slides/slide1.xml`` → ``/ppt/slides/slide%d.xml``.
    """
    s = str(partname)
    m = _TRAILING_INT.match(s)
    if m:
        return f"{m.group(1)}%d{m.group(3)}"
    base, dot, ext = s.rpartition(".")
    return f"{base}%d.{ext}" if dot else f"{s}%d"


def _alloc_partname(package, template: str, reserved: Set[str]) -> PackURI:
    """Next free partname for ``template`` considering BOTH the package and names this
    merge has already handed out but not yet linked into the part graph.

    ``package.next_partname`` only sees parts reachable through relationships, so during
    the clone recursion freshly-created (not-yet-linked) siblings are invisible to it and
    would be assigned the same name — hence the explicit ``reserved`` set.
    """
    existing = {str(p.partname) for p in package.iter_parts()} | reserved
    n = 1
    while (template % n) in existing:
        n += 1
    name = template % n
    reserved.add(name)
    return PackURI(name)


def _clone_part(package, src_part: Part, cloned: Dict[int, Part], reserved: Set[str]) -> Part:
    """Deep-clone ``src_part`` (and everything it reaches) into ``package``.

    Returns the destination clone. Memoised by source-object identity so a part shared by
    several slides of the same source deck (a master, a theme) is copied once.
    """
    memo = cloned.get(id(src_part))
    if memo is not None:
        return memo

    dst_part = Part(
        _alloc_partname(package, _name_template(src_part.partname), reserved),
        src_part.content_type,
        package,
        src_part.blob,            # original bytes — never re-serialized
    )
    cloned[id(src_part)] = dst_part

    base_uri = dst_part.partname.baseURI
    dst_rels = dst_part.rels._rels  # the {rId: _Relationship} backing dict
    for rId, rel in src_part.rels.items():
        if rel.is_external:
            dst_rels[rId] = _Relationship(base_uri, rId, rel.reltype, RTM.EXTERNAL, rel.target_ref)
        else:
            target = _clone_part(package, rel.target_part, cloned, reserved)
            dst_rels[rId] = _Relationship(base_uri, rId, rel.reltype, RTM.INTERNAL, target)
    return dst_part


def _append_slide(base: Presentation, src_slide, cloned: Dict[int, Part], reserved: Set[str]) -> None:
    """Clone one source slide's part graph into ``base`` and register it as a new slide."""
    dst_slide_part = _clone_part(base.part.package, src_slide.part, cloned, reserved)
    rId = base.part.relate_to(dst_slide_part, _SLIDE_RELTYPE)
    base.slides._sldIdLst.add_sldId(rId)


def merge_pptx(paths: List[str]) -> Presentation:
    """Concatenate the slides of ``paths`` (in order) into one |Presentation|.

    The first path is opened as the base; every slide of each later deck is appended.
    Raises ``ValueError`` if ``paths`` is empty.
    """
    if not paths:
        raise ValueError("merge_pptx: no input paths")
    base = Presentation(paths[0])
    reserved: Set[str] = set()
    for path in paths[1:]:
        src = Presentation(path)
        cloned: Dict[int, Part] = {}   # per-source-deck identity memo
        for slide in src.slides:
            _append_slide(base, slide, cloned, reserved)
    logger.info("merge_pptx: stitched %d deck(s) -> %d slide(s)", len(paths), len(base.slides._sldIdLst))
    return base


def merge_to_file(paths: List[str], out_path: str) -> str:
    """Merge ``paths`` and save the result to ``out_path`` (returned)."""
    prs = merge_pptx(paths)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    prs.save(out_path)
    logger.info("merge_pptx: exported -> %s", out_path)
    return out_path
