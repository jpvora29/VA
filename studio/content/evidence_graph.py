"""Evidence graph — a lightweight relation layer over an EvidencePack (Phase 4).

Not a generic knowledge graph: just typed nodes (subject, period, entity, fact)
and typed edges (about / in_period / derived_from / contributes_to) built
deterministically from the pack, so commentary planning can reason across
related facts ("this movement decomposes into these per-product movements",
"this entity is material") without replacing any deterministic calculation.

Pure data + pure builders — no engine, no LLM. Node/edge order is stable
(sorted by fact id) so downstream output is byte-deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

from studio.content.evidence_pack import EvidenceItem, EvidencePack

# dims columns → the entity kind they describe.
_DIM_KIND = {
    "Product_Line": "product",
    "Business_Line": "product",
    "Cover_Line": "product",
    "Country": "country",
    "Region": "country",
    "SIC_Major_Class": "industry",
    "SIC_Minor_Class": "industry",
    "Client_Segment": "practice",
    "entity": "carrier",
}

# Measures that decompose a movement — the graph marks these as driver candidates.
DECOMPOSITION_MEASURES = frozenset({"premium_movement", "movement_by_dim", "rate_volume_mix"})


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: str                              # carrier | product | country | industry | practice | period | fact
    label: str


@dataclass(frozen=True)
class GraphEdge:
    src: str
    relation: str                          # about | in_period | derived_from | contributes_to
    dst: str


@dataclass(frozen=True)
class EvidenceGraph:
    nodes: Mapping[str, GraphNode] = field(default_factory=dict)
    edges: Tuple[GraphEdge, ...] = ()

    def neighbors(self, node_id: str, relation: Optional[str] = None) -> Tuple[str, ...]:
        return tuple(
            e.dst for e in self.edges
            if e.src == node_id and (relation is None or e.relation == relation)
        )

    def incoming(self, node_id: str, relation: Optional[str] = None) -> Tuple[str, ...]:
        return tuple(
            e.src for e in self.edges
            if e.dst == node_id and (relation is None or e.relation == relation)
        )

    def fact_ids_about(self, entity_node_id: str) -> Tuple[str, ...]:
        """Every fact node attached to an entity, in stable order."""
        return tuple(sorted(
            n.removeprefix("fact:") for n in self.incoming(entity_node_id, "about")
        ))

    def entity_nodes(self, kind: Optional[str] = None) -> Tuple[GraphNode, ...]:
        return tuple(
            n for _, n in sorted(self.nodes.items())
            if n.kind not in ("fact", "period") and (kind is None or n.kind == kind)
        )

    def driver_candidates(self, movement_fact_id: str) -> Tuple[str, ...]:
        """Fact ids that contribute to a movement (the decomposition edges)."""
        return tuple(sorted(
            n.removeprefix("fact:")
            for n in self.incoming(f"fact:{movement_fact_id}", "contributes_to")
        ))


def _entity_node_id(kind: str, label: str) -> str:
    return f"{kind}:{label}"


def build_evidence_graph(pack: EvidencePack) -> EvidenceGraph:
    """Deterministic pack → graph projection."""
    nodes: Dict[str, GraphNode] = {}
    edges: List[GraphEdge] = []

    subject_id = _entity_node_id("carrier", pack.subject)
    nodes[subject_id] = GraphNode(subject_id, "carrier", pack.subject)

    for period in (pack.period, pack.comparison_period):
        pid = f"period:{period}"
        nodes.setdefault(pid, GraphNode(pid, "period", period))

    # Total-scope movement facts, used to wire per-dim contributions below.
    total_movements = [
        item for _, item in sorted(pack.items.items())
        if item.measure in ("premium_movement", "premium_movement_pct")
        and item.dims.get("scope") == "total"
    ]

    for fid, item in sorted(pack.items.items()):
        fact_node = f"fact:{fid}"
        nodes[fact_node] = GraphNode(fact_node, "fact", f"{item.measure}={item.rendered}")

        linked_entity = False
        for dim, value in sorted(item.dims.items(), key=lambda kv: str(kv[0])):
            kind = _DIM_KIND.get(str(dim))
            if kind is None or value is None:
                continue
            eid = _entity_node_id(kind, str(value))
            nodes.setdefault(eid, GraphNode(eid, kind, str(value)))
            edges.append(GraphEdge(fact_node, "about", eid))
            linked_entity = True
        if not linked_entity:
            edges.append(GraphEdge(fact_node, "about", subject_id))

        if item.provenance and item.provenance.period is not None:
            pid = f"period:FY{item.provenance.period}"
            nodes.setdefault(pid, GraphNode(pid, "period", f"FY{item.provenance.period}"))
            edges.append(GraphEdge(fact_node, "in_period", pid))

        for src_fid in item.derived_from:
            edges.append(GraphEdge(fact_node, "derived_from", f"fact:{src_fid}"))

        # A per-dimension movement contributes to the total movement — the
        # decomposition relation driver commentary must cite.
        if item.measure in DECOMPOSITION_MEASURES and item.dims.get("scope") != "total":
            for total in total_movements:
                edges.append(GraphEdge(fact_node, "contributes_to", f"fact:{total.fact_id}"))

    return EvidenceGraph(nodes=nodes, edges=tuple(edges))


# ── materiality over the graph (rules-driven, pure) ───────────────────────────


def material_entities(
    pack: EvidencePack, graph: EvidenceGraph, *, floor: Optional[float] = None
) -> Tuple[str, ...]:
    """Entity node ids whose premium clears the materiality floor (rules.yaml)."""
    from studio.rules import load_rules

    limit = floor if floor is not None else load_rules().materiality.min_premium_for_practice_commentary
    out: List[str] = []
    for node in graph.entity_nodes():
        if node.kind == "carrier":
            out.append(node.node_id)     # the subject is always in scope
            continue
        premiums = [
            pack.items[fid].value
            for fid in graph.fact_ids_about(node.node_id)
            if fid in pack.items and pack.items[fid].measure in ("premium_total", "whitespace_market")
        ]
        movements = [
            abs(pack.items[fid].value)
            for fid in graph.fact_ids_about(node.node_id)
            if fid in pack.items and pack.items[fid].measure == "premium_movement"
        ]
        if any(p >= limit for p in premiums) or any(m >= limit for m in movements):
            out.append(node.node_id)
    return tuple(sorted(out))
